"""Transfer intake, the accepting-physician consult cycle, and rebalancing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    T_0030,
    add_physician,
    assert_instant_equal,
    assert_transfer_request,
    create_accepted_request,
    create_facility,
    create_transfer_request,
    dispatch_consult,
    get_success_data,
    make_accepting_physician_headers,
    make_coordinator_headers,
    respond_consult,
    run_sweep,
    set_clock,
    setup_facility_with_physician,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["sysadmin_headers"]
COORD = TEST_USERS["coordinator_headers"]
SUPERVISOR = TEST_USERS["house_supervisor_headers"]


class TestConsultDispatch:
    def test_consult_dispatch_sets_deadline_side_effect(self, api):
        """PRD §3.3: "A successful dispatch moves the request to
        `CONSULT_PENDING`, records the physician as `accepting_physician_id`,
        sets `consult_deadline` to thirty minutes after the dispatch time,
        increments `consult_count` by one (re-consult rounds included), clears
        `decline_reason` to null, and increments the request's `version` by
        one."

        Design: Corner/state_machines/consult_dispatch_sets_deadline_side_effect
        """
        set_clock()
        facility = create_facility(name="Side Fac")
        physician = add_physician(facility["id"], full_name="Dr S",
                                  services=("NEURO",))
        request = create_transfer_request(
            facility["id"], patient_ref="PS2", acuity="ACUITY_2_STEPDOWN",
            service="NEURO", priority="EMERGENT")
        updated = dispatch_consult(request["id"], physician["id"])
        assert updated["status"] == "CONSULT_PENDING"
        assert_instant_equal(updated["consult_deadline"], "2026-08-01T00:30:00Z")
        assert updated["consult_count"] == 1
        assert updated["accepting_physician_id"] == physician["id"]

    def test_consult_response_from_intake_rejected(self, api):
        """PRD §3.3: "responding from any status other than `CONSULT_PENDING`
        is rejected with `ERR_TRANSFER_INVALID_STATE`."

        Design: Corner/state_machines/consult_response_from_intake_rejected
        """
        set_clock()
        bundle = setup_facility_with_physician(name="Inv Fac")
        facility, physician = bundle["facility"], bundle["physician"]
        request = create_transfer_request(facility["id"], patient_ref="PV1")
        # Walk to ACCEPTED so the responding caller IS the request's accepting
        # physician (§3.3 clears accepting_physician_id only on decline,
        # timeout, diversion, and cancel — an ACCEPT retains it, which is also
        # what backs §4's per-physician accepted-requests listing). With
        # ownership satisfied, the state rule fires unambiguously: ACCEPTED is
        # "any status other than CONSULT_PENDING".
        dispatch_consult(request["id"], physician["id"])
        accepted = respond_consult(request["id"], physician["id"],
                                   decision="ACCEPT")
        assert accepted["status"] == "ACCEPTED"
        resp = api.consult_response(
            request["id"], {"decision": "ACCEPT"},
            make_accepting_physician_headers(physician["id"]))
        validate_error(resp, ApiErrorId.ERR_TRANSFER_INVALID_STATE)
        after = validate_success(api.get_transfer_request(request["id"], COORD))
        assert after["status"] == "ACCEPTED", "rejected response mutates nothing"

    def test_consult_physician_not_credentialed(self, api):
        """PRD §3.3: "the physician must be credentialed for the request's
        `service`, meaning the service appears in the physician's `services`
        list (`ERR_PHYSICIAN_NOT_CREDENTIALED_FOR_SERVICE`)".

        Design: Corner/validations/consult_physician_not_credentialed
        """
        set_clock()
        facility = create_facility(name="Cred Fac")
        physician = add_physician(facility["id"], full_name="Dr N",
                                  services=("NEURO",))
        request = create_transfer_request(
            facility["id"], patient_ref="PCRD", service="CARDIAC")
        resp = api.dispatch_consult(
            request["id"], {"physician_id": physician["id"]},
            make_coordinator_headers("coord_1"))
        validate_error(
            resp, ApiErrorId.ERR_PHYSICIAN_NOT_CREDENTIALED_FOR_SERVICE)

    def test_consult_physician_off_call_rejected(self, api):
        """PRD §3.3: "only then is the physician's roster status checked, which
        must be `ON_CALL` (`ERR_PHYSICIAN_NOT_ON_CALL`)."

        Design: Corner/validations/consult_physician_off_call_rejected
        """
        set_clock()
        facility = create_facility(name="Call Fac")
        physician = add_physician(facility["id"], full_name="Dr OC",
                                  services=("CARDIAC",))
        tr1 = create_transfer_request(facility["id"], patient_ref="POC1")
        tr2 = create_transfer_request(facility["id"], patient_ref="POC2")
        first = dispatch_consult(tr1["id"], physician["id"])
        assert first["status"] == "CONSULT_PENDING"
        get_success_data(api.set_physician_status(
            physician["id"], {"to_status": "OFF_CALL"}, SUPERVISOR))
        resp = api.dispatch_consult(
            tr2["id"], {"physician_id": physician["id"]},
            make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_PHYSICIAN_NOT_ON_CALL)

    def test_consult_response_after_deadline_rejected(self, api):
        """PRD §3.3: "the response must arrive while the current time is still
        strictly before `consult_deadline`; a response arriving at or after the
        deadline is rejected with `ERR_CONSULT_WINDOW_EXPIRED`".

        Design: Corner/validations/consult_response_after_deadline_rejected
        """
        set_clock()
        bundle = setup_facility_with_physician(name="Temp Fac")
        facility, physician = bundle["facility"], bundle["physician"]
        request = create_transfer_request(facility["id"], patient_ref="PTMP")
        dispatch_consult(request["id"], physician["id"])
        set_clock(T_0030)  # exactly the consult deadline
        resp = api.consult_response(
            request["id"], {"decision": "ACCEPT"},
            make_accepting_physician_headers(physician["id"]))
        validate_error(resp, ApiErrorId.ERR_CONSULT_WINDOW_EXPIRED)


class TestConsultReconsultCycle:
    def test_reconsult_after_decline_switches_physician(self, api):
        """PRD §3.3: "from `DECLINED` (or `EXPIRED`) the coordinator may
        dispatch a fresh consult to the same or a different physician."
        PRD §3.3: "increments `consult_count` by one (re-consult rounds
        included), clears `decline_reason` to null".

        Design: Difficulty/non_linear_state_machine/transfer_request_consult_reconsult_cycle
        """
        set_clock()
        facility = create_facility(name="Cycle Facility")
        dr1 = add_physician(facility["id"], full_name="Dr One",
                            services=("CARDIAC",))
        dr2 = add_physician(facility["id"], full_name="Dr Two",
                            services=("CARDIAC",))
        request = create_transfer_request(
            facility["id"], patient_ref="PCY", priority="EMERGENT")
        dispatch_consult(request["id"], dr1["id"])
        declined = respond_consult(
            request["id"], dr1["id"], decision="DECLINE",
            decline_reason="PHYSICIAN_DECLINED")
        assert declined["status"] == "DECLINED"
        second = dispatch_consult(request["id"], dr2["id"])
        assert second["consult_count"] == 2
        accepted = respond_consult(request["id"], dr2["id"], decision="ACCEPT")
        assert accepted["status"] == "ACCEPTED"
        assert accepted["accepting_physician_id"] == dr2["id"]
        assert accepted["decline_reason"] is None

    def test_reconsult_from_expired_reopens_consult(self, api):
        """PRD §3.3: "From `INTAKE` — and again from `DECLINED` or `EXPIRED`,
        forming the re-consult loop — the coordinator dispatches an
        accepting-physician consult by naming a `physician_id`."

        Design: Difficulty/non_linear_state_machine/transfer_request_consult_reconsult_cycle
        """
        set_clock()
        bundle = setup_facility_with_physician(name="Cycle2 Fac")
        facility, physician = bundle["facility"], bundle["physician"]
        request = create_transfer_request(facility["id"], patient_ref="PCY2")
        dispatch_consult(request["id"], physician["id"])
        set_clock(T_0030)
        run_sweep()
        expired = validate_success(
            api.get_transfer_request(request["id"], COORD))
        assert expired["status"] == "EXPIRED"
        assert expired["decline_reason"] == "TIMEOUT"
        # The cycle reopens: a fresh consult from EXPIRED succeeds.
        second = dispatch_consult(request["id"], physician["id"])
        assert second["status"] == "CONSULT_PENDING"
        assert second["consult_count"] == 2
        assert second["decline_reason"] is None


class TestConsultSweepExpiry:
    def test_sweep_expires_consult_past_deadline(self, api):
        """PRD §3.3: "If a sweep observes the current time at or past
        `consult_deadline`, the request moves from `CONSULT_PENDING` to
        `EXPIRED` with `decline_reason` set to `TIMEOUT`, and
        `accepting_physician_id` and `consult_deadline` are cleared."

        Design: Corner/state_machines/sweep_expires_consult_past_deadline
        """
        set_clock()
        bundle = setup_facility_with_physician(name="Sweep Fac")
        facility, physician = bundle["facility"], bundle["physician"]
        request = create_transfer_request(facility["id"], patient_ref="PW9")
        dispatch_consult(request["id"], physician["id"])
        set_clock(T_0030)  # exactly the deadline — the >= boundary
        report = run_sweep()
        assert request["id"] in report["expired_consult_request_ids"]
        after = validate_success(
            api.get_transfer_request(request["id"], COORD))
        assert after["status"] == "EXPIRED"
        assert after["decline_reason"] == "TIMEOUT"
        assert after["accepting_physician_id"] is None
        assert after["consult_deadline"] is None


class TestTransferCancel:
    def test_terminal_transfer_request_rejects_cancel(self, api):
        """PRD §3.3: "cancelling a terminal request is rejected with
        `ERR_TRANSFER_INVALID_STATE`."

        Design: Corner/state_machines/terminal_transfer_request_rejects_cancel
        """
        set_clock()
        bundle = setup_facility_with_physician(name="Term Fac")
        facility, physician = bundle["facility"], bundle["physician"]
        from test_helpers import add_bed, walk_request_to_completed
        bed = add_bed(facility["id"], unit="C-1", label="B1", service="CARDIAC",
                      max_acuity="ACUITY_1_CRITICAL",
                      isolation_capability="AIRBORNE")
        request, _hold, _assignment = walk_request_to_completed(
            facility["id"], physician["id"], bed["id"],
            acuity="ACUITY_1_CRITICAL", priority="EMERGENT")
        assert request["status"] == "COMPLETED"
        resp = api.cancel_transfer_request(
            request["id"], make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_TRANSFER_INVALID_STATE)
        after = validate_success(
            api.get_transfer_request(request["id"], COORD))
        assert after["status"] == "COMPLETED"


class TestTransferListFilter:
    def test_transfer_request_list_status_filter(self, api):
        """PRD §4: "diversion, admission, transfer-request, hold, assignment,
        huddle, and forecast lists also accept an optional `status` filter".
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/transfer_request_list_status_filter
        """
        set_clock()
        facility = create_facility(name="Filter Fac")
        f1 = create_transfer_request(facility["id"], patient_ref="PF1")
        create_transfer_request(facility["id"], patient_ref="PF2")
        f3 = create_transfer_request(facility["id"], patient_ref="PF3",
                                     priority="ELECTIVE")
        get_success_data(api.cancel_transfer_request(
            f3["id"], make_coordinator_headers("coord_1")))
        data, meta = validate_paginated(api.list_transfer_requests(
            facility["id"], COORD, params={"status": "CANCELLED"}))
        assert [r["id"] for r in data] == [f3["id"]]
        assert meta["total_count"] == 1
        _all_data, all_meta = validate_paginated(
            api.list_transfer_requests(facility["id"], COORD))
        assert all_meta["total_count"] == 3
        assert f1["id"] != f3["id"]


class TestRebalance:
    def test_rebalance_margin_below_threshold_rejected(self, api):
        """PRD §3.7: "the source facility's `load_score_weighted` minus the
        target facility's `load_score_weighted` must be at least 10.0, with a
        margin of exactly 10.0 permitted; anything smaller is rejected with
        `ERR_REBALANCE_MARGIN_NOT_MET`."

        Design: Corner/validations/rebalance_margin_below_threshold_rejected
        """
        set_clock()
        from test_helpers import (
            add_bed,
            create_admission,
            create_boarding_record_payload,
        )
        # Two facilities built to identical load pictures: margin 0.0 < 10.0.
        fs = create_facility(name="Src Fac")
        ft = create_facility(name="Tgt Fac")
        drs = add_physician(fs["id"], full_name="Dr S", services=("CARDIAC",))
        drt = add_physician(ft["id"], full_name="Dr T", services=("CARDIAC",))

        def build_load(fac, dr, label_prefix):
            b1 = add_bed(fac["id"], unit="ICU-1", label=f"{label_prefix}1",
                         service="CARDIAC", max_acuity="ACUITY_1_CRITICAL",
                         isolation_capability="AIRBORNE")
            b2 = add_bed(fac["id"], unit="ICU-1", label=f"{label_prefix}2",
                         service="CARDIAC", max_acuity="ACUITY_1_CRITICAL",
                         isolation_capability="AIRBORNE")
            b3 = add_bed(fac["id"], unit="ED-1", label=f"{label_prefix}3",
                         service="MEDICAL")
            b4 = add_bed(fac["id"], unit="M-1", label=f"{label_prefix}4",
                         service="MEDICAL")
            add_bed(fac["id"], unit="N-1", label=f"{label_prefix}5",
                    service="NEURO", max_acuity="ACUITY_2_STEPDOWN")
            create_admission(fac["id"], b1["id"], patient_ref=f"{label_prefix}A1",
                             acuity="ACUITY_1_CRITICAL", service="CARDIAC")
            adm_ed = create_admission(
                fac["id"], b3["id"], patient_ref=f"{label_prefix}A3",
                service="MEDICAL")
            create_admission(fac["id"], b4["id"], patient_ref=f"{label_prefix}A4",
                             service="MEDICAL")
            get_success_data(api.create_boarding_record(
                fac["id"], create_boarding_record_payload(adm_ed["id"]), COORD))
            # One HOLD_PLACED request (holds b2) plus one extra INTAKE request.
            from test_helpers import create_request_with_hold
            create_request_with_hold(
                fac["id"], dr["id"], b2["id"],
                patient_ref=f"{label_prefix}H",
                acuity="ACUITY_3_MEDICAL_SURGICAL", service="CARDIAC")
            create_transfer_request(fac["id"], patient_ref=f"{label_prefix}X",
                                    service="CARDIAC", priority="ELECTIVE")
            # The request that will be rebalanced away. It must exist BEFORE
            # the margin is measured: every non-terminal request contributes
            # one half to its own facility's pressure numerator (§3.2), so
            # creating it only on the source afterwards would lift the source
            # by exactly 10.0 points (0.5 / 5 staffed beds) and make the
            # margin exactly 10.0 — which §3.7 permits. The twin keeps the
            # two facilities' pictures identical at rebalance time.
            return create_transfer_request(
                fac["id"], patient_ref=f"{label_prefix}Y", service="CARDIAC",
                priority="ELECTIVE")

        trx = build_load(fs, drs, "S")
        build_load(ft, drt, "T")
        # Sanity: both facilities show the same weighted score.
        ls_s = validate_success(api.get_facility_load_score(fs["id"], COORD))
        ls_t = validate_success(api.get_facility_load_score(ft["id"], COORD))
        assert ls_s["pressure_weighted_pct"] == ls_t["pressure_weighted_pct"]
        resp = api.rebalance_transfer_request(
            trx["id"], {"target_facility_id": ft["id"]},
            make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_REBALANCE_MARGIN_NOT_MET)
        after = validate_success(api.get_transfer_request(trx["id"], COORD))
        assert after["facility_id"] == fs["id"]
        assert after["status"] == "INTAKE"
