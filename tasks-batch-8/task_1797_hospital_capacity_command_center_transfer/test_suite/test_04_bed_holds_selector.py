"""Bed holds: explicit placement validation, the selector, quota, cooling, OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    T_0030,
    T_0059,
    T_0100,
    T_0114,
    T_0115,
    add_bed,
    add_physician,
    assert_bed_hold,
    assert_instant_equal,
    create_accepted_request,
    create_facility,
    create_request_with_hold,
    get_success_data,
    make_coordinator_headers,
    place_assignment,
    place_hold,
    place_holds_for_n_requests,
    run_sweep,
    set_clock,
    setup_accepted_request_scenario,
    setup_facility_with_physician,
    setup_hold_placed_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["sysadmin_headers"]
BED_MGR = TEST_USERS["bed_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestHoldCreation:
    def test_bed_hold_initial_state_and_expiry_computation(self, api):
        """PRD §3.4: "A created hold records its `bed_id`, the
        `transfer_request_id` it serves, a `starts_at` equal to the
        logical-clock time of creation, the effective `ttl_minutes` (defaulting
        to 60 when omitted), an `expires_at` equal to `starts_at` plus
        `ttl_minutes`, an `extend_count` of zero, and `ACTIVE` status."

        Design: Corner/state_machines/bed_hold_initial_state_and_expiry_computation
        """
        set_clock()
        scenario = setup_accepted_request_scenario(name="Init Fac")
        hold = place_hold(scenario["request"]["id"],
                          bed_id=scenario["bed"]["id"], ttl_minutes=90)
        assert_bed_hold(hold)
        assert hold["status"] == "ACTIVE"
        assert hold["extend_count"] == 0
        assert hold["version"] == 1
        assert_instant_equal(hold["starts_at"], "2026-08-01T00:00:00Z")
        assert_instant_equal(hold["expires_at"], "2026-08-01T01:30:00Z")
        assert hold["ttl_minutes"] == 90

    def test_out_of_service_bed_blocks_hold_create(self, api):
        """PRD §3.4: "Eligibility is identical in both modes and has four
        clauses beyond basic availability: the bed must be `AVAILABLE`, flagged
        `staffed`, and outside ED units".
        PRD §3.4: "after the state check that the bed is available, staffed,
        and non-ED (`ERR_BED_NOT_AVAILABLE`)".

        Design: Difficulty/cross_entity_state_dependency/out_of_service_bed_blocks_hold_create
        """
        set_clock()
        scenario = setup_accepted_request_scenario(name="OOS Facility")
        bed = scenario["bed"]
        request = scenario["request"]
        get_success_data(api.set_bed_status(
            bed["id"], {"to_status": "OUT_OF_SERVICE"}, BED_MGR))
        resp = api.create_bed_hold(
            request["id"], {"bed_id": bed["id"]},
            make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_BED_NOT_AVAILABLE)
        after = validate_success(api.get_transfer_request(request["id"], COORD))
        assert after["status"] == "ACCEPTED", "no hold was placed"

    def test_out_of_service_bed_blocks_selector_hold_create(self, api):
        """PRD §3.4: "In selector mode, ineligible beds are silently excluded
        from the candidate pool." and "hold placement with an omitted `bed_id`
        and an empty pool is rejected with `ERR_NO_ELIGIBLE_BED`."
        PRD §3.4: "the bed must be `AVAILABLE`, flagged `staffed`, and outside
        ED units".

        Design: Difficulty/cross_entity_state_dependency/out_of_service_bed_blocks_hold_create
        """
        set_clock()
        scenario = setup_accepted_request_scenario(name="OOS Facility Sel")
        bed = scenario["bed"]
        request = scenario["request"]
        get_success_data(api.set_bed_status(
            bed["id"], {"to_status": "OUT_OF_SERVICE"}, BED_MGR))
        # Selector mode: the only bed is out of service, so the pool is empty.
        resp = api.create_bed_hold(request["id"], {},
                                   make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_BED)
        after = validate_success(api.get_transfer_request(request["id"], COORD))
        assert after["status"] == "ACCEPTED"


class TestHoldSafetyOrder:
    def test_hold_explicit_bed_acuity_and_service_violations(self, api):
        """PRD §3.4: "In explicit mode, failures map to errors in a pinned
        order — after the state check that the bed is available, staffed, and
        non-ED (`ERR_BED_NOT_AVAILABLE`), isolation compatibility is checked
        first (`ERR_ISOLATION_INCOMPATIBLE`), then acuity capability
        (`ERR_ACUITY_EXCEEDS_BED_CAPABILITY`), then service match
        (`ERR_SERVICE_MISMATCH`)."

        Design: Corner/errors/hold_explicit_bed_acuity_and_service_violations
        """
        set_clock()
        bundle = setup_facility_with_physician(
            name="Safe Fac", services=("CARDIAC", "NEURO"))
        facility, physician = bundle["facility"], bundle["physician"]
        b_low = add_bed(facility["id"], unit="C-1", label="LOW",
                        service="CARDIAC", max_acuity="ACUITY_4_OBSERVATION",
                        isolation_capability="AIRBORNE")
        b_neuro = add_bed(facility["id"], unit="N-1", label="NEU",
                          service="NEURO", max_acuity="ACUITY_2_STEPDOWN",
                          isolation_capability="AIRBORNE")
        tr_hi = create_accepted_request(
            facility["id"], physician["id"], patient_ref="PHI",
            acuity="ACUITY_1_CRITICAL", service="CARDIAC", priority="EMERGENT")
        tr_sv = create_accepted_request(
            facility["id"], physician["id"], patient_ref="PSV",
            acuity="ACUITY_3_MEDICAL_SURGICAL", service="CARDIAC")
        resp_acu = api.create_bed_hold(
            tr_hi["id"], {"bed_id": b_low["id"]},
            make_coordinator_headers("coord_1"))
        validate_error(resp_acu, ApiErrorId.ERR_ACUITY_EXCEEDS_BED_CAPABILITY)
        resp_svc = api.create_bed_hold(
            tr_sv["id"], {"bed_id": b_neuro["id"]},
            make_coordinator_headers("coord_1"))
        validate_error(resp_svc, ApiErrorId.ERR_SERVICE_MISMATCH)
        for req in (tr_hi, tr_sv):
            after = validate_success(api.get_transfer_request(req["id"], COORD))
            assert after["status"] == "ACCEPTED"
        for bed in (b_low, b_neuro):
            after_bed = validate_success(api.get_bed(bed["id"], COORD))
            assert after_bed["status"] == "AVAILABLE"


class TestSelector:
    def test_bed_match_score_tiered_ranking(self, api):
        """PRD §3.4: "The selector scores each eligible bed with integer
        arithmetic: one thousand points when the bed's service exactly matches
        the request's service; an acuity-fit component computed as four minus
        the number of ranks by which the bed's `max_acuity` exceeds the
        request's `acuity`, multiplied by one hundred points, so an exact
        acuity match earns four hundred points and each rank of headroom costs
        one hundred; ten points when the bed's isolation capability exactly
        equals the request's isolation need; and five points when the request
        names a `preferred_unit` and the bed's `unit` equals it."

        Design: Difficulty/combinatorial_formula/bed_match_score_tiered_ranking
        """
        set_clock()
        facility = create_facility(name="Match Facility")
        b_a = add_bed(facility["id"], unit="U1", label="BA", service="CARDIAC",
                      max_acuity="ACUITY_2_STEPDOWN", isolation_capability="CONTACT")
        b_b = add_bed(facility["id"], unit="U2", label="BB", service="CARDIAC",
                      max_acuity="ACUITY_1_CRITICAL",
                      isolation_capability="AIRBORNE")
        b_c = add_bed(facility["id"], unit="U1", label="BC", service="MEDICAL",
                      max_acuity="ACUITY_3_MEDICAL_SURGICAL",
                      isolation_capability="CONTACT")
        b_d = add_bed(facility["id"], unit="U1", label="BD", service="CARDIAC",
                      max_acuity="ACUITY_4_OBSERVATION",
                      isolation_capability="CONTACT")
        b_e = add_bed(facility["id"], unit="U1", label="BE", service="CARDIAC",
                      max_acuity="ACUITY_2_STEPDOWN", isolation_capability="NONE")
        from test_helpers import create_transfer_request
        request = create_transfer_request(
            facility["id"], patient_ref="PM",
            acuity="ACUITY_3_MEDICAL_SURGICAL", isolation_need="CONTACT",
            service="CARDIAC", preferred_unit="U1")
        resp = api.get_bed_candidates(facility["id"], request["id"], COORD)
        body = validate_success(resp, 200)
        candidates = body["candidates"] if isinstance(body, dict) else body
        ids = [c["bed_id"] if "bed_id" in c else c["id"] for c in candidates]
        assert ids == [b_a["id"], b_b["id"], b_c["id"]], (
            f"expected ranked order [bA, bB, bC], got {ids}")
        scores = { (c.get("bed_id") or c["id"]): c["score"] for c in candidates }
        assert scores[b_a["id"]] == 1315
        assert scores[b_b["id"]] == 1200
        assert scores[b_c["id"]] == 415
        assert b_d["id"] not in ids, "acuity-ineligible bed excluded"
        assert b_e["id"] not in ids, "isolation-ineligible bed excluded"

    def test_bed_match_score_excludes_ed_and_unstaffed_beds(self, api):
        """PRD §3.4: "the bed must be `AVAILABLE`, flagged `staffed`, and
        outside ED units (its `unit` label must not begin with ED)".
        PRD §3.4: "In selector mode, ineligible beds are silently excluded from
        the candidate pool."

        Design: Difficulty/combinatorial_formula/bed_match_score_tiered_ranking
        """
        set_clock()
        facility = create_facility(name="Match Facility 2")
        b_ed = add_bed(facility["id"], unit="ED-9", label="BED", service="CARDIAC",
                       max_acuity="ACUITY_1_CRITICAL",
                       isolation_capability="AIRBORNE")
        b_unstaffed = add_bed(facility["id"], unit="C-1", label="BUS",
                              service="CARDIAC", max_acuity="ACUITY_1_CRITICAL",
                              isolation_capability="AIRBORNE", staffed=False)
        b_ok = add_bed(facility["id"], unit="C-1", label="BOK", service="CARDIAC",
                       max_acuity="ACUITY_1_CRITICAL",
                       isolation_capability="AIRBORNE")
        from test_helpers import create_transfer_request
        request = create_transfer_request(
            facility["id"], patient_ref="PM2",
            acuity="ACUITY_3_MEDICAL_SURGICAL", isolation_need="CONTACT",
            service="CARDIAC")
        resp = api.get_bed_candidates(facility["id"], request["id"], COORD)
        body = validate_success(resp, 200)
        candidates = body["candidates"] if isinstance(body, dict) else body
        ids = [c["bed_id"] if "bed_id" in c else c["id"] for c in candidates]
        assert ids == [b_ok["id"]], (
            f"only the staffed non-ED bed is eligible, got {ids}")
        assert b_ed["id"] not in ids
        assert b_unstaffed["id"] not in ids

    def test_selector_tie_break_uses_created_at(self, api):
        """PRD §3.4: "Candidates are ordered by score descending, with ties
        broken by the bed's `created_at`, earliest first — never by bed id."

        Design: Corner/calculations/selector_tie_break_uses_created_at
        """
        set_clock()
        bundle = setup_facility_with_physician(name="Tie Fac")
        facility, physician = bundle["facility"], bundle["physician"]
        b_old = add_bed(facility["id"], unit="C-1", label="OLD",
                        service="CARDIAC",
                        max_acuity="ACUITY_3_MEDICAL_SURGICAL",
                        isolation_capability="NONE")
        add_bed(facility["id"], unit="C-2", label="NEW", service="CARDIAC",
                max_acuity="ACUITY_3_MEDICAL_SURGICAL",
                isolation_capability="NONE")
        request = create_accepted_request(
            facility["id"], physician["id"], patient_ref="PTIE",
            acuity="ACUITY_3_MEDICAL_SURGICAL", isolation_need="NONE",
            service="CARDIAC")
        hold = place_hold(request["id"])  # selector mode: bed_id omitted
        assert hold["bed_id"] == b_old["id"], (
            "both beds score identically; the earlier-created bed wins the tie")

    def test_selector_empty_pool_returns_no_eligible_bed(self, api):
        """PRD §3.4: "the bed-candidates read, which takes a
        `transfer_request_id` and applies the same eligibility, scoring, and
        ordering, returns an empty list in that case, while hold placement with
        an omitted `bed_id` and an empty pool is rejected with
        `ERR_NO_ELIGIBLE_BED`."

        Design: Corner/calculations/selector_empty_pool_returns_no_eligible_bed
        """
        set_clock()
        bundle = setup_facility_with_physician(name="Empty Fac",
                                               services=("MEDICAL",))
        facility, physician = bundle["facility"], bundle["physician"]
        add_bed(facility["id"], unit="ED-1", label="E1", service="MEDICAL")
        request = create_accepted_request(
            facility["id"], physician["id"], patient_ref="PEM",
            acuity="ACUITY_3_MEDICAL_SURGICAL", service="MEDICAL")
        resp = api.create_bed_hold(request["id"], {},
                                   make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_BED)


class TestHoldQuota:
    def test_hold_quota_seventh_hold_rejected(self, api):
        """PRD §3.4: "A facility may carry at most six `ACTIVE` holds at one
        time: with six already active the quota is full — the sixth hold
        succeeds and a seventh is rejected with `ERR_HOLD_QUOTA_EXCEEDED`."

        Design: Corner/calculations/hold_quota_seventh_hold_rejected
        """
        set_clock()
        bundle = setup_facility_with_physician(name="Quota Fac")
        facility, physician = bundle["facility"], bundle["physician"]
        bed_ids = []
        for i in range(1, 8):
            unit = "C-1" if i <= 3 else ("C-2" if i <= 6 else "C-3")
            bed = add_bed(facility["id"], unit=unit, label=f"H{i}",
                          service="CARDIAC", max_acuity="ACUITY_1_CRITICAL",
                          isolation_capability="AIRBORNE")
            bed_ids.append(bed["id"])
        place_holds_for_n_requests(facility["id"], physician["id"],
                                   bed_ids[:6])
        tr7 = create_accepted_request(
            facility["id"], physician["id"], patient_ref="Q7",
            acuity="ACUITY_3_MEDICAL_SURGICAL", service="CARDIAC")
        resp = api.create_bed_hold(
            tr7["id"], {"bed_id": bed_ids[6]},
            make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_HOLD_QUOTA_EXCEEDED)
        bed7 = validate_success(api.get_bed(bed_ids[6], COORD))
        assert bed7["status"] == "AVAILABLE", "rejected hold leaves bed untouched"


class TestCoolingWindow:
    def test_bed_cooling_buffer_closed_interval(self, api):
        """PRD §2.11: "When a hold ends or a discharge is confirmed, the bed
        enters a turnover buffer ending at `cooling_until`; a new hold on that
        bed is rejected precisely while the current time is strictly before
        `cooling_until`, so a hold placed exactly at the `cooling_until`
        instant is allowed."
        PRD §3.4: "a new hold arriving while the current time is strictly
        before `cooling_until` is rejected with
        `ERR_BED_HOLD_WINDOW_CONFLICT`; arrival exactly at `cooling_until` is
        permitted."

        Design: Difficulty/resource_temporal_overlap/bed_cooling_buffer_closed_interval
        """
        set_clock()
        bundle = setup_facility_with_physician(name="Cooling Facility")
        facility, physician = bundle["facility"], bundle["physician"]
        bed = add_bed(facility["id"], unit="C-1", label="B1", service="CARDIAC",
                      max_acuity="ACUITY_1_CRITICAL",
                      isolation_capability="AIRBORNE")
        tr1, hold1 = create_request_with_hold(
            facility["id"], physician["id"], bed["id"], patient_ref="PW1")
        tr2 = create_accepted_request(
            facility["id"], physician["id"], patient_ref="PW2",
            acuity="ACUITY_1_CRITICAL", service="CARDIAC")
        set_clock(T_0030)
        get_success_data(api.release_bed_hold(
            hold1["id"], make_coordinator_headers("coord_1")))
        # 00:30 release + 45-minute turnover => cooling_until 01:15.
        set_clock(T_0114)
        resp = api.create_bed_hold(
            tr2["id"], {"bed_id": bed["id"]},
            make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_BED_HOLD_WINDOW_CONFLICT)
        set_clock(T_0115)
        hold2 = place_hold(tr2["id"], bed_id=bed["id"])
        assert hold2["status"] == "ACTIVE"
        bed_after = validate_success(api.get_bed(bed["id"], COORD))
        assert bed_after["status"] == "HELD"
        assert bed_after["cooling_until"] is None
        tr2_after = validate_success(api.get_transfer_request(tr2["id"], COORD))
        assert tr2_after["status"] == "HOLD_PLACED"

    def test_discharge_cooling_blocks_then_allows_hold(self, api):
        """PRD §2.11: "When a hold ends or a discharge is confirmed, the bed
        enters a turnover buffer ending at `cooling_until`; a new hold on that
        bed is rejected precisely while the current time is strictly before
        `cooling_until`, so a hold placed exactly at the `cooling_until`
        instant is allowed."
        PRD §3.6: "`cooling_until` is set to the confirmation time plus
        `turnover_minutes`, during which §3.4's cooling rule blocks new holds."

        Design: Difficulty/resource_temporal_overlap/bed_cooling_buffer_closed_interval
        """
        set_clock()
        bundle = setup_facility_with_physician(name="Cooling Facility 2")
        facility, physician = bundle["facility"], bundle["physician"]
        from test_helpers import create_admission
        bed = add_bed(facility["id"], unit="C-1", label="B1", service="CARDIAC",
                      max_acuity="ACUITY_1_CRITICAL",
                      isolation_capability="AIRBORNE")
        admission = create_admission(
            facility["id"], bed["id"], patient_ref="PD1",
            acuity="ACUITY_1_CRITICAL", service="CARDIAC")
        get_success_data(api.mark_pending_discharge(
            admission["id"],
            {"expected_discharge_at": "2026-08-01T00:30:00Z",
             "discharge_order_signed": True},
            TEST_USERS["bed_manager_headers"]))
        set_clock(T_0030)
        get_success_data(api.confirm_discharge(
            admission["id"], TEST_USERS["bed_manager_headers"]))
        # Discharge confirmed at 00:30 + 45-minute turnover => cooling 01:15.
        bed_mid = validate_success(api.get_bed(bed["id"], COORD))
        assert_instant_equal(bed_mid["cooling_until"], "2026-08-01T01:15:00Z")
        tr = create_accepted_request(
            facility["id"], physician["id"], patient_ref="PD2",
            acuity="ACUITY_1_CRITICAL", service="CARDIAC")
        set_clock(T_0114)
        resp = api.create_bed_hold(
            tr["id"], {"bed_id": bed["id"]}, make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_BED_HOLD_WINDOW_CONFLICT)
        set_clock(T_0115)
        hold = place_hold(tr["id"], bed_id=bed["id"])
        assert hold["status"] == "ACTIVE"


class TestHoldExpiry:
    def test_hold_expires_at_exactly_expires_at(self, api):
        """PRD §3.4: "A hold expires when the current time reaches or passes
        `expires_at` — expiry happens exactly at the deadline — which a sweep
        detects and processes."

        Design: Difficulty/boundary_precision_check/hold_expires_at_exactly_expires_at
        """
        set_clock()
        bundle = setup_facility_with_physician(name="Expiry Facility")
        facility, physician = bundle["facility"], bundle["physician"]
        bed = add_bed(facility["id"], unit="C-1", label="B1", service="CARDIAC",
                      max_acuity="ACUITY_1_CRITICAL",
                      isolation_capability="AIRBORNE")
        request, hold = create_request_with_hold(
            facility["id"], physician["id"], bed["id"], patient_ref="PE1")
        assert_instant_equal(hold["expires_at"], "2026-08-01T01:00:00Z")
        set_clock(T_0059)
        run_sweep()
        mid = validate_success(api.get_bed_hold(hold["id"], COORD))
        assert mid["status"] == "ACTIVE", "one minute before expiry it stays ACTIVE"
        set_clock(T_0100)
        report = run_sweep()
        assert hold["id"] in report["expired_hold_ids"]
        after = validate_success(api.get_bed_hold(hold["id"], COORD))
        assert after["status"] == "EXPIRED"
        bed_after = validate_success(api.get_bed(bed["id"], COORD))
        assert bed_after["status"] == "AVAILABLE"
        assert_instant_equal(bed_after["cooling_until"], "2026-08-01T01:45:00Z")
        request_after = validate_success(
            api.get_transfer_request(request["id"], COORD))
        assert request_after["status"] == "ACCEPTED", (
            "expiry loops the request back to ACCEPTED")

    def test_hold_active_one_minute_before_expiry(self, api):
        """PRD §3.4: "A hold expires when the current time reaches or passes
        `expires_at` — expiry happens exactly at the deadline — which a sweep
        detects and processes."
        PRD §2.4: "A sweep performs four duties: it expires every `ACTIVE` bed
        hold whose `expires_at` has been reached or passed".

        Design: Difficulty/boundary_precision_check/hold_expires_at_exactly_expires_at
        """
        set_clock()
        bundle = setup_facility_with_physician(name="Expiry Facility 2")
        facility, physician = bundle["facility"], bundle["physician"]
        bed = add_bed(facility["id"], unit="C-1", label="B1", service="CARDIAC",
                      max_acuity="ACUITY_1_CRITICAL",
                      isolation_capability="AIRBORNE")
        _request, hold = create_request_with_hold(
            facility["id"], physician["id"], bed["id"], patient_ref="PE2")
        # One minute before expires_at the sweep must leave the hold ACTIVE.
        set_clock(T_0059)
        report = run_sweep()
        assert hold["id"] not in report["expired_hold_ids"]
        mid = validate_success(api.get_bed_hold(hold["id"], COORD))
        assert mid["status"] == "ACTIVE"
        # At the deadline exactly, the same sweep expires it.
        set_clock(T_0100)
        report2 = run_sweep()
        assert hold["id"] in report2["expired_hold_ids"]
        after = validate_success(api.get_bed_hold(hold["id"], COORD))
        assert after["status"] == "EXPIRED"

    def test_scheduled_deferred_clock_determinism(self, api):
        """PRD §2.4: "At startup, before any adjustment, the logical clock
        reads exactly 2026-08-01T00:00:00Z; the server must not fall back to
        wall-clock time under any circumstance."

        Design: Corner/cross_cutting_layers/scheduled_deferred_clock_determinism
        """
        # No set_clock call at all: the startup default must apply.
        bundle = setup_facility_with_physician(name="Clock Fac")
        facility, physician = bundle["facility"], bundle["physician"]
        bed = add_bed(facility["id"], unit="C-1", label="B1", service="CARDIAC",
                      max_acuity="ACUITY_1_CRITICAL",
                      isolation_capability="AIRBORNE")
        request = create_accepted_request(
            facility["id"], physician["id"], patient_ref="PCLK",
            acuity="ACUITY_1_CRITICAL", service="CARDIAC")
        hold = place_hold(request["id"], bed_id=bed["id"])
        assert_instant_equal(hold["starts_at"], "2026-08-01T00:00:00Z")
        assert_instant_equal(hold["expires_at"], "2026-08-01T01:00:00Z")


class TestHoldExtendOcc:
    def test_occ_hold_extend_stale_and_limit(self, api):
        """PRD §2.9: "Extending a bed hold requires the non-optional field
        `expected_bed_hold_version`, carrying the hold's `version` as last
        observed. Because a successful extension both pushes `expires_at`
        forward and advances the hold's `version`, an extension carrying a
        pre-extension version is operating on a stale view and is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.4: "its `extend_count` must still be below two — the hard cap —
        so a third extension is rejected with `ERR_HOLD_EXTEND_LIMIT_EXCEEDED`."

        Design: Corner/cross_cutting_layers/occ_hold_extend_stale_and_limit
        """
        set_clock()
        scenario = setup_hold_placed_scenario(name="OCC2 Fac")
        hold = scenario["hold"]
        hold_v = hold["version"]
        first = validate_success(api.extend_bed_hold(
            hold["id"], {"expected_bed_hold_version": hold_v},
            make_coordinator_headers("coord_1")), 200)
        assert_instant_equal(first["expires_at"], "2026-08-01T01:30:00Z")
        assert first["extend_count"] == 1
        assert first["version"] == hold_v + 1
        stale = api.extend_bed_hold(
            hold["id"], {"expected_bed_hold_version": hold_v},
            make_coordinator_headers("coord_1"))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        second = validate_success(api.extend_bed_hold(
            hold["id"], {"expected_bed_hold_version": first["version"]},
            make_coordinator_headers("coord_1")), 200)
        assert_instant_equal(second["expires_at"], "2026-08-01T02:00:00Z")
        assert second["extend_count"] == 2
        third = api.extend_bed_hold(
            hold["id"], {"expected_bed_hold_version": second["version"]},
            make_coordinator_headers("coord_1"))
        validate_error(third, ApiErrorId.ERR_HOLD_EXTEND_LIMIT_EXCEEDED)


class TestHoldRelease:
    def test_hold_release_twice_rejected(self, api):
        """PRD §3.4: "the hold must be `ACTIVE` (`ERR_HOLD_INVALID_STATE`)".

        Design: Corner/errors/hold_release_twice_rejected
        """
        set_clock()
        scenario = setup_hold_placed_scenario(name="HIS Fac")
        hold = scenario["hold"]
        get_success_data(api.release_bed_hold(
            hold["id"], make_coordinator_headers("coord_1")))
        resp = api.release_bed_hold(
            hold["id"], make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_HOLD_INVALID_STATE)
        after = validate_success(api.get_bed_hold(hold["id"], COORD))
        assert after["status"] == "RELEASED"


class TestAssignmentOcc:
    def test_occ_assignment_stale_version_rejected(self, api):
        """PRD §2.9: "Creating a bed assignment against a transfer request
        requires the non-optional field `expected_transfer_request_version`,
        carrying the transfer request's `version` as the client last read it.
        If the request's current `version` has advanced since that read — for
        example because another writer placed or released a hold, each of which
        legitimately moves the request between `ACCEPTED` and `HOLD_PLACED` and
        advances its version — the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_assignment_stale_version_rejected
        """
        set_clock()
        bundle = setup_facility_with_physician(name="OCC Fac")
        facility, physician = bundle["facility"], bundle["physician"]
        bed = add_bed(facility["id"], unit="C-1", label="B1", service="CARDIAC",
                      max_acuity="ACUITY_1_CRITICAL",
                      isolation_capability="AIRBORNE")
        request = create_accepted_request(
            facility["id"], physician["id"], patient_ref="POCC",
            acuity="ACUITY_1_CRITICAL", service="CARDIAC", priority="EMERGENT")
        stale_version = request["version"]
        hold = place_hold(request["id"], bed_id=bed["id"])
        # The hold create advanced the request's version; replaying the
        # pre-hold version must fail.
        resp = api.create_bed_assignment(
            request["id"],
            {"bed_hold_id": hold["id"],
             "expected_transfer_request_version": stale_version},
            make_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        fresh = validate_success(api.get_transfer_request(request["id"], COORD))
        ok = validate_success(api.create_bed_assignment(
            request["id"],
            {"bed_hold_id": hold["id"],
             "expected_transfer_request_version": fresh["version"]},
            make_coordinator_headers("coord_1")), 201)
        assert ok["status"] == "PLACED"
        after = validate_success(api.get_transfer_request(request["id"], COORD))
        assert after["version"] == fresh["version"] + 1
        assert after["status"] == "ASSIGNED"


class TestImmediateConsistency:
    def test_immediate_visibility_of_hold_side_effects(self, api):
        """PRD §3.2: "Consistency is immediate: each mutation's effects are
        visible in that same request's response."

        Design: Corner/consistency_model/immediate_visibility_of_hold_side_effects
        """
        set_clock()
        scenario = setup_accepted_request_scenario(name="Imm Fac")
        request = scenario["request"]
        bed = scenario["bed"]
        hold = place_hold(request["id"], bed_id=bed["id"])
        assert hold["status"] == "ACTIVE"
        bed_after = validate_success(api.get_bed(bed["id"], COORD))
        assert bed_after["status"] == "HELD"
        request_after = validate_success(
            api.get_transfer_request(request["id"], COORD))
        assert request_after["status"] == "HOLD_PLACED"
        facility_after = validate_success(
            api.get_facility(scenario["facility"]["id"], COORD))
        assert facility_after["held_beds"] == 1
        assert facility_after["available_beds"] == 0
