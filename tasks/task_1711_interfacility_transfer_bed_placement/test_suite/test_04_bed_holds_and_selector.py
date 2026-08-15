"""Bed selector policy, hold lifecycle, lazy expiry, and hold OCC guard."""
from test_helpers import (
    ApiErrorId,
    assert_bed_hold,
    accept_case,
    assert_timestamp_equals,
    certify_screening,
    create_case,
    create_facility,
    create_bed,
    create_physician,
    create_screening,
    current_case_version,
    drive_to_accepted,
    drive_to_awaiting,
    request_acceptance,
    get_case,
    get_facility,
    get_hold,
    list_facility_beds,
    list_holds,
    make_bed_manager_headers,
    make_receiving_physician_headers,
    parse_timestamp,
    release_hold,
    set_bed_status,
    set_clock,
    setup_certified_case,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANY


class TestAcceptSelector:
    def test_accept_no_eligible_bed_rejected(self, api):
        """PRD: "An empty pool rejects the acceptance with
        `ERR_NO_ELIGIBLE_BED`."
        PRD: "A bed is eligible when it belongs to the receiving facility, is
        `AVAILABLE`, matches the case's `required_unit_type`, and — when the
        case's `requires_isolation` is true — is `isolation_capable`."

        Design: Corner/state_machines/accept_no_eligible_bed_rejected
        """
        ws = setup_certified_case(acuity="CRITICAL", unit="ICU",
                                  rcv_beds=(("MS-01", "MED_SURG", None),),
                                  patient_ref="PT-NOBED-1")
        drive_to_awaiting(ws)
        resp = api.accept_case(
            ws["case"]["id"], {},
            make_receiving_physician_headers(ws["phys_r"]["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_BED, 409)
        assert get_case(ws["case"]["id"])["status"] == "AWAITING_ACCEPTANCE"
        assert list_holds(transfer_case_id=ws["case"]["id"]) == []

    def test_bed_selector_isolation_preservation_ranking(self, api):
        """PRD: "Eligible beds are ranked by isolation preservation first (when
        the case does not require isolation, beds that are not isolation-capable
        rank ahead of those that are, keeping isolation capacity free), then by
        `created_at` ascending so the oldest bed wins, and finally by
        `bed_code` ascending in lexicographic order as the tie-break."

        Design: Corner/cross_cutting_layers/bed_selector_isolation_preservation_ranking
        """
        ws = setup_certified_case(
            acuity="CRITICAL", unit="ICU",
            rcv_beds=(("ICU-01", "ICU", True), ("ICU-02", "ICU", False)),
            patient_ref="PT-SEL-1")
        bed_iso, bed_reg = ws["beds"]
        drive_to_awaiting(ws)
        drive_to_accepted(ws)
        hold = get_hold(ws["hold_id"])
        assert hold["bed_id"] == bed_reg["id"], (
            "non-isolation case must preserve the isolation-capable bed"
        )
        assert get_facility(ws["fac_r"]["id"])["unavailable_bed_count"] == 1
        iso_bed = [b for b in
                   list_facility_beds(ws["fac_r"]["id"])
                   if b["id"] == bed_iso["id"]][0]
        assert iso_bed["status"] == "AVAILABLE"

    def test_bed_selector_tiebreak_bed_code(self, api):
        """PRD: "Eligible beds are ranked by isolation preservation first (when
        the case does not require isolation, beds that are not isolation-capable
        rank ahead of those that are, keeping isolation capacity free), then by
        `created_at` ascending so the oldest bed wins, and finally by
        `bed_code` ascending in lexicographic order as the tie-break."
        PRD: "All time in the system — timestamps on state transitions, hold
        expiries, notification SLAs, diversion windows, and every computed
        duration — reads a single logical clock, never the wall clock."

        Design: Corner/cross_cutting_layers/bed_selector_tiebreak_bed_code
        """
        # Creation order (ICU-07 then ICU-03) disagrees with code order; the
        # frozen logical clock ties created_at, so bed_code must decide.
        ws = setup_certified_case(
            acuity="CRITICAL", unit="ICU",
            rcv_beds=(("ICU-07", "ICU", False), ("ICU-03", "ICU", False)),
            patient_ref="PT-SEL-2")
        bed_03 = ws["beds"][1]
        drive_to_awaiting(ws)
        drive_to_accepted(ws)
        hold = get_hold(ws["hold_id"])
        assert hold["bed_id"] == bed_03["id"], (
            "identical created_at must fall through to the bed_code ASC tie-break"
        )


class TestHoldExpiryConstants:
    def test_hold_expiry_constants_by_acuity(self, api):
        """PRD: "A successful acceptance flips the round's communication
        `PENDING → ACCEPTED` with `responded_at` stamped, moves the selected bed
        `AVAILABLE → HELD`, and creates a `BedHold` in `ACTIVE` with
        `hold_started_at` stamped from the clock and `hold_expires_at` computed
        from the case's acuity: sixty minutes for `CRITICAL`, two hours for
        `EMERGENT`, four hours for `URGENT`, and eight hours for `STABLE`."
        PRD: "Before any call is made, the logical clock reads exactly
        2026-08-01T00:00:00Z and it never falls back to wall-clock time."

        Design: Corner/calculations/hold_expiry_constants_by_acuity
        """
        fac_s = create_facility()
        fac_r = create_facility(name="Receiving Trauma Center", facility_code="RCV",
                                trauma_level="LEVEL_1",
                                capabilities=["CARDIAC_CATH"])
        create_bed(fac_r["id"], "ICU-01", "ICU")
        create_bed(fac_r["id"], "MS-01", "MED_SURG")
        phys_s = create_physician("Dr Send", fac_s["id"], "EMERGENCY")
        phys_r = create_physician("Dr Recv", fac_r["id"], "INTENSIVIST")

        case_e = create_case(fac_s["id"], phys_s["id"], "EMERGENT", "ICU",
                             "CARDIAC_CATH", False, "PT-HC-EMG")
        create_screening(case_e["id"], phys_s["id"], True, True)
        certify_screening(case_e["id"], phys_s["id"])
        request_acceptance(case_e["id"], fac_r["id"], phys_r["id"])

        case_s = create_case(fac_s["id"], phys_s["id"], "STABLE", "MED_SURG",
                             "CARDIAC_CATH", False, "PT-HC-STB")
        create_screening(case_s["id"], phys_s["id"], False, True)
        certify_screening(case_s["id"], phys_s["id"])
        request_acceptance(case_s["id"], fac_r["id"], phys_r["id"])

        acc_e = accept_case(case_e["id"], phys_r["id"])
        acc_s = accept_case(case_s["id"], phys_r["id"])
        hold_e = get_hold(acc_e["active_bed_hold_id"])
        hold_s = get_hold(acc_s["active_bed_hold_id"])
        assert_bed_hold(hold_e)
        assert_timestamp_equals(hold_e["hold_started_at"], "2026-08-01T00:00:00Z")
        assert_timestamp_equals(hold_e["hold_expires_at"], "2026-08-01T02:00:00Z")
        assert_timestamp_equals(hold_s["hold_expires_at"], "2026-08-01T08:00:00Z")


class TestHoldRelease:
    def test_hold_release_twice_rejected(self, api):
        """PRD: "A facility's `BedManager` may instead release an `ACTIVE` hold
        manually — the hold must be `ACTIVE` (`ERR_HOLD_NOT_ACTIVE`), the case
        still `ACCEPTED` (`ERR_INVALID_STATE`), and the caller's `X-User-ID`
        equal to the held bed's `facility_id` (`ERR_NOT_FACILITY_MANAGER`) —
        which stamps `release_reason` `MANUAL`, frees the bed, clears
        `active_bed_hold_id`, and recomputes occupancy."

        Design: Corner/state_machines/hold_release_twice_rejected
        """
        ws = setup_certified_case(acuity="CRITICAL", unit="ICU",
                                  patient_ref="PT-REL-1")
        drive_to_awaiting(ws)
        drive_to_accepted(ws)
        hold_id = ws["hold_id"]
        release_hold(hold_id, ws["fac_r"]["id"])

        resp = api.release_bed_hold(
            hold_id, make_bed_manager_headers(ws["fac_r"]["id"]))
        validate_error(resp, ApiErrorId.ERR_HOLD_NOT_ACTIVE, 409)

        fac = get_facility(ws["fac_r"]["id"])
        assert fac["unavailable_bed_count"] == 0, (
            "a rejected second release must not replay compensation"
        )

    def test_hold_lazy_expiry_on_direct_read(self, api):
        """PRD: "Expiry is lazy: any read or write that touches an `ACTIVE`
        hold while the clock is at or past `hold_expires_at` flips it to
        `EXPIRED` with `release_reason` `EXPIRED`, returns the bed `HELD →
        AVAILABLE`, clears the case's `active_bed_hold_id`, bumps the case
        version, and recomputes occupancy."
        PRD: "reading a single hold applies lazy expiry before answering."

        Design: Corner/state_machines/hold_lazy_expiry_on_direct_read
        """
        ws = setup_certified_case(acuity="CRITICAL", unit="ICU",
                                  patient_ref="PT-LAZY-1")
        drive_to_awaiting(ws)
        drive_to_accepted(ws)
        hold_id = ws["hold_id"]
        set_clock("2026-08-01T01:00:01Z")  # one second past a CRITICAL hold

        hold = get_hold(hold_id)
        assert hold["status"] == "EXPIRED"
        assert hold["release_reason"] == "EXPIRED"

        fac = get_facility(ws["fac_r"]["id"])
        assert fac["unavailable_bed_count"] == 0, "the read freed the bed"
        case = get_case(ws["case"]["id"])
        assert case["status"] == "ACCEPTED"
        assert case["active_bed_hold_id"] is None


class TestManualHoldLinkErrors:
    def test_manual_hold_bed_link_errors_rejected(self, api):
        """PRD: "The caller's `X-User-ID` must equal the case's
        `receiving_facility_id`, the case must be `ACCEPTED`, the bed must
        exist, belong to the case's receiving facility
        (`ERR_BED_FACILITY_MISMATCH`), match the case's `required_unit_type`
        (`ERR_BED_UNIT_MISMATCH`), be `AVAILABLE` (`ERR_BED_NOT_AVAILABLE`),
        and be isolation-capable when the case requires isolation
        (`ERR_ISOLATION_REQUIRED`)."

        Design: Corner/validations/manual_hold_bed_link_errors_rejected
        """
        fac_t = create_facility(name="Third Hospital", facility_code="THD",
                                trauma_level="LEVEL_2",
                                capabilities=["CARDIAC_CATH"])
        ws = setup_certified_case(
            acuity="CRITICAL", unit="ICU", requires_isolation=True,
            rcv_beds=(("ICU-ISO", "ICU", True), ("ICU-02", "ICU", False),
                      ("MS-ISO", "MED_SURG", True)),
            patient_ref="PT-ISO-1")
        bed_z = ws["beds"][1]   # RCV ICU, not isolation-capable
        bed_y = ws["beds"][2]   # RCV MED_SURG
        bed_x = create_bed(fac_t["id"], "ICU-THD", "ICU", True)
        drive_to_awaiting(ws)
        drive_to_accepted(ws)
        hold1 = ws["hold_id"]   # auto-hold consumed the only isolation ICU bed
        case_v = current_case_version(ws["case"]["id"])
        mgr = make_bed_manager_headers(ws["fac_r"]["id"])

        def attempt(bed_id):
            return api.create_bed_hold(
                ws["case"]["id"],
                {"bed_id": bed_id, "expected_transfer_case_version": case_v},
                mgr)

        validate_error(attempt(bed_x["id"]), ApiErrorId.ERR_BED_FACILITY_MISMATCH, 422)
        validate_error(attempt(bed_y["id"]), ApiErrorId.ERR_BED_UNIT_MISMATCH, 422)
        validate_error(attempt(bed_z["id"]), ApiErrorId.ERR_ISOLATION_REQUIRED, 422)

        assert get_hold(hold1)["status"] == "ACTIVE", (
            "rejected attempts must not supersede the live hold"
        )


class TestHoldOcc:
    def test_occ_bedhold_create_stale_version_rejected(self, api):
        """PRD: "Manually placing a bed hold against a case requires a
        non-optional `expected_transfer_case_version` field carrying the
        `TransferCase` `version` the client last observed; if the case's
        current `version` has advanced since, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD: "Because a successful hold creation supersedes any prior active
        hold and bumps the case version, a client holding a pre-supersede
        version is writing against a stale case view."

        Design: Corner/cross_cutting_layers/occ_bedhold_create_stale_version_rejected
        """
        fac_s = create_facility()
        fac_r = create_facility(name="Receiving Trauma Center", facility_code="RCV",
                                trauma_level="LEVEL_1",
                                capabilities=["CARDIAC_CATH"])
        bed1 = create_bed(fac_r["id"], "ICU-01", "ICU")
        bed2 = create_bed(fac_r["id"], "ICU-02", "ICU")
        phys_s = create_physician("Dr Send", fac_s["id"], "EMERGENCY")
        phys_r = create_physician("Dr Recv", fac_r["id"], "INTENSIVIST")
        case = create_case(fac_s["id"], phys_s["id"], "CRITICAL", "ICU",
                           "CARDIAC_CATH", False, "PT-OCC-1")
        create_screening(case["id"], phys_s["id"], True, True)
        certify_screening(case["id"], phys_s["id"])
        request_acceptance(case["id"], fac_r["id"], phys_r["id"])
        accept_case(case["id"], phys_r["id"])
        case_v = current_case_version(case["id"])
        mgr = make_bed_manager_headers(fac_r["id"])

        first = validate_success(api.create_bed_hold(
            case["id"],
            {"bed_id": bed2["id"], "expected_transfer_case_version": case_v},
            mgr), 201)
        assert first["status"] == "ACTIVE"
        assert get_case(case["id"])["version"] == case_v + 1, (
            "a successful manual hold bumps the case version"
        )

        resp = api.create_bed_hold(
            case["id"],
            {"bed_id": bed1["id"], "expected_transfer_case_version": case_v},
            mgr)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        assert get_hold(first["id"])["status"] == "ACTIVE", (
            "the 412 rejection must not supersede the fresh hold"
        )
        beds = {b["bed_code"]: b["status"]
                for b in list_facility_beds(fac_r["id"])}
        assert beds["ICU-02"] == "HELD"


class TestManualHoldGatedByBedStatus:
    def _workspace(self):
        """ACCEPTED CRITICAL ICU case (auto-hold ICU-01); ICU-02 OCCUPIED;
        ICU-03 AVAILABLE."""
        ws = setup_certified_case(
            acuity="CRITICAL", unit="ICU",
            rcv_beds=(("ICU-01", "ICU", None), ("ICU-02", "ICU", None),
                      ("ICU-03", "ICU", None)),
            patient_ref="PT-HOLD-1")
        drive_to_awaiting(ws)
        drive_to_accepted(ws)
        set_bed_status(ws["beds"][1]["id"], ws["fac_r"]["id"], "OCCUPIED")
        return ws

    def test_manual_hold_on_occupied_bed_rejected(self, api):
        """PRD: "The caller's `X-User-ID` must equal the case's
        `receiving_facility_id`, the case must be `ACCEPTED`, the bed must
        exist, belong to the case's receiving facility
        (`ERR_BED_FACILITY_MISMATCH`), match the case's `required_unit_type`
        (`ERR_BED_UNIT_MISMATCH`), be `AVAILABLE` (`ERR_BED_NOT_AVAILABLE`),
        and be isolation-capable when the case requires isolation
        (`ERR_ISOLATION_REQUIRED`)."

        Design: Difficulty/cross_entity_state_dependency/manual_hold_gated_by_bed_status
        """
        ws = self._workspace()
        case_v = current_case_version(ws["case"]["id"])
        mgr = make_bed_manager_headers(ws["fac_r"]["id"])

        resp = api.create_bed_hold(
            ws["case"]["id"],
            {"bed_id": ws["beds"][1]["id"],
             "expected_transfer_case_version": case_v},
            mgr)
        validate_error(resp, ApiErrorId.ERR_BED_NOT_AVAILABLE, 409)

        placed = validate_success(api.create_bed_hold(
            ws["case"]["id"],
            {"bed_id": ws["beds"][2]["id"],
             "expected_transfer_case_version": case_v},
            mgr), 201)
        assert placed["status"] == "ACTIVE"
        assert placed["bed_id"] == ws["beds"][2]["id"]

    def test_manual_hold_success_supersedes_prior_hold(self, api):
        """PRD: "Success supersedes any prior `ACTIVE` hold of the case — the
        old hold flips to `RELEASED` with `release_reason` `SUPERSEDED` and its
        bed returns to `AVAILABLE` — moves the new bed to `HELD`, creates the
        new `ACTIVE` hold with the same acuity-scaled expiry math, bumps the
        case version, and recomputes occupancy."

        Design: Difficulty/cross_entity_state_dependency/manual_hold_gated_by_bed_status
        """
        ws = self._workspace()
        hold1 = ws["hold_id"]
        case_v = current_case_version(ws["case"]["id"])
        mgr = make_bed_manager_headers(ws["fac_r"]["id"])
        placed = validate_success(api.create_bed_hold(
            ws["case"]["id"],
            {"bed_id": ws["beds"][2]["id"],
             "expected_transfer_case_version": case_v},
            mgr), 201)

        old = get_hold(hold1)
        assert old["status"] == "RELEASED"
        assert old["release_reason"] == "SUPERSEDED"
        case = get_case(ws["case"]["id"])
        assert case["active_bed_hold_id"] == placed["id"]
        assert case["version"] > case_v
        beds = {b["bed_code"]: b["status"]
                for b in list_facility_beds(ws["fac_r"]["id"])}
        assert beds["ICU-01"] == "AVAILABLE", "superseded bed is freed"
        assert beds["ICU-03"] == "HELD"


class TestHoldHalfOpenAdjacency:
    def _workspace(self):
        ws = setup_certified_case(acuity="CRITICAL", unit="ICU",
                                  patient_ref="PT-ADJ-1")
        drive_to_awaiting(ws)
        drive_to_accepted(ws)
        return ws

    def test_new_hold_inside_window_rejected(self, api):
        """PRD: "A hold occupies its bed over a half-open interval — from
        `hold_started_at` up to but not including `hold_expires_at`; when the
        clock reaches the expiry instant exactly, the hold no longer blocks."

        Design: Difficulty/resource_temporal_overlap/bed_hold_half_open_interval_adjacency_allowed
        """
        ws = self._workspace()
        bed_id = ws["beds"][0]["id"]
        case_v = current_case_version(ws["case"]["id"])
        set_clock("2026-08-01T00:59:00Z")  # inside [00:00, 01:00)

        resp = api.create_bed_hold(
            ws["case"]["id"],
            {"bed_id": bed_id, "expected_transfer_case_version": case_v},
            make_bed_manager_headers(ws["fac_r"]["id"]))
        validate_error(resp, ApiErrorId.ERR_BED_NOT_AVAILABLE, 409)

    def test_new_hold_at_expiry_instant_allowed(self, api):
        """PRD: "A hold occupies its bed over a half-open interval — from
        `hold_started_at` up to but not including `hold_expires_at`; when the
        clock reaches the expiry instant exactly, the hold no longer blocks."
        PRD: "Expiry is lazy: any read or write that touches an `ACTIVE` hold
        while the clock is at or past `hold_expires_at` flips it to `EXPIRED`
        with `release_reason` `EXPIRED`, returns the bed `HELD → AVAILABLE`,
        clears the case's `active_bed_hold_id`, bumps the case version, and
        recomputes occupancy."

        Design: Difficulty/resource_temporal_overlap/bed_hold_half_open_interval_adjacency_allowed
        """
        ws = self._workspace()
        bed_id = ws["beds"][0]["id"]
        hold1 = ws["hold_id"]
        set_clock("2026-08-01T01:00:00Z")  # exactly hold_expires_at

        # The direct hold read applies lazy expiry first.
        old = get_hold(hold1)
        assert old["status"] == "EXPIRED"
        assert old["release_reason"] == "EXPIRED"
        case = get_case(ws["case"]["id"])
        assert case["active_bed_hold_id"] is None

        placed = validate_success(api.create_bed_hold(
            ws["case"]["id"],
            {"bed_id": bed_id,
             "expected_transfer_case_version": case["version"]},
            make_bed_manager_headers(ws["fac_r"]["id"])), 201)
        assert_timestamp_equals(placed["hold_started_at"], "2026-08-01T01:00:00Z")
        assert_timestamp_equals(placed["hold_expires_at"], "2026-08-01T02:00:00Z")
        assert placed["status"] == "ACTIVE"
        beds = {b["bed_code"]: b["status"]
                for b in list_facility_beds(ws["fac_r"]["id"])}
        assert beds["ICU-01"] == "HELD"


class TestHoldParityInvariant:
    def _workspace(self):
        ws = setup_certified_case(
            acuity="CRITICAL", unit="ICU",
            rcv_beds=(("ICU-01", "ICU", None), ("ICU-02", "ICU", None)),
            patient_ref="PT-PAR-1")
        drive_to_awaiting(ws)
        return ws

    def test_accept_places_exactly_one_active_hold(self, api):
        """PRD: "`unavailable_bed_count` counts beds in `HELD` or `OCCUPIED`."
        PRD: "A successful acceptance flips the round's communication
        `PENDING → ACCEPTED` with `responded_at` stamped, moves the selected bed
        `AVAILABLE → HELD`, and creates a `BedHold` in `ACTIVE` with
        `hold_started_at` stamped from the clock and `hold_expires_at` computed
        from the case's acuity: sixty minutes for `CRITICAL`, two hours for
        `EMERGENT`, four hours for `URGENT`, and eight hours for `STABLE`."

        Design: Difficulty/compensating_invariant/hold_create_release_parity_invariant
        """
        ws = self._workspace()
        baseline = get_facility(ws["fac_r"]["id"])
        assert baseline["unavailable_bed_count"] == 0

        drive_to_accepted(ws)
        mid = get_facility(ws["fac_r"]["id"])
        assert mid["unavailable_bed_count"] == 1
        assert mid["occupancy_pct"] == 50.0
        active = list_holds(transfer_case_id=ws["case"]["id"], status="ACTIVE")
        assert len(active) == 1, "one HELD bed pairs with exactly one ACTIVE hold"

    def test_release_restores_baseline_exactly(self, api):
        """PRD: "A facility's `BedManager` may instead release an `ACTIVE` hold
        manually — the hold must be `ACTIVE` (`ERR_HOLD_NOT_ACTIVE`), the case
        still `ACCEPTED` (`ERR_INVALID_STATE`), and the caller's `X-User-ID`
        equal to the held bed's `facility_id` (`ERR_NOT_FACILITY_MANAGER`) —
        which stamps `release_reason` `MANUAL`, frees the bed, clears
        `active_bed_hold_id`, and recomputes occupancy."
        PRD: "Holds are listable, filterable by `bed_id`, `transfer_case_id`,
        or `status`, and reading a single hold applies lazy expiry before
        answering."

        Design: Difficulty/compensating_invariant/hold_create_release_parity_invariant
        """
        ws = self._workspace()
        drive_to_accepted(ws)
        released = release_hold(ws["hold_id"], ws["fac_r"]["id"])
        assert released["status"] == "RELEASED"
        assert released["release_reason"] == "MANUAL"

        end = get_facility(ws["fac_r"]["id"])
        assert end["unavailable_bed_count"] == 0, "forward + compensate returns to baseline"
        assert end["occupancy_pct"] == 0.0
        assert list_holds(transfer_case_id=ws["case"]["id"], status="ACTIVE") == []
        assert get_case(ws["case"]["id"])["active_bed_hold_id"] is None
