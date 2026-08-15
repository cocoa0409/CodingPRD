"""Culture surveillance, quarantine cascade, exposure windows, release gates."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_clock,
    advance_step,
    assess_prep,
    assert_instants_equal,
    check_in,
    complete_procedure,
    confirm_prep,
    create_booking,
    create_culture,
    create_cycle,
    create_in_progress_booking,
    create_quarantined_scope,
    create_release_ready_scope,
    create_reprocessed_scope,
    create_scope,
    first_case_for_scope,
    get_booking,
    get_case,
    get_cycle,
    get_scope,
    get_usage,
    make_nurse_headers,
    make_registry,
    make_technician_headers,
    result_culture,
    run_complete_cycle,
    run_procedure_to_complete,
    run_reculture_cycle,
    send_to_reprocessing,
    setup_exposure_scenario,
    setup_two_negative_cultures_scenario,
    start_procedure,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["unit_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]
NURSE = TEST_USERS["nurse_headers"]


class TestCultureCreation:
    def test_culture_requires_complete_cycle_rejected(self, api):
        """PRD §3.7: "the referenced cycle must belong to that very scope
        (`ERR_CULTURE_SCOPE_MISMATCH` when it belongs to a different one) and must
        already be `COMPLETE` (`ERR_CYCLE_NOT_COMPLETE`)".

        Design: Corner/state_machines/culture_requires_complete_cycle_rejected
        """
        scope = create_scope(serial_number="SC-IC")
        send_to_reprocessing(scope["id"])
        cycle = create_cycle(scope["id"])
        resp = api.create_culture_test(
            {"scope_id": scope["id"], "reprocessing_cycle_id": cycle["id"]}, NURSE)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_COMPLETE)

    def test_culture_scope_cycle_mismatch_rejected(self, api):
        """PRD §3.7: "the referenced cycle must belong to that very scope
        (`ERR_CULTURE_SCOPE_MISMATCH` when it belongs to a different one)".

        Design: Corner/state_machines/culture_scope_cycle_mismatch_rejected
        """
        _sa, cya = create_reprocessed_scope(serial_number="SC-MA", lot="LOT-M")
        sb = create_scope(serial_number="SC-MB")
        resp = api.create_culture_test(
            {"scope_id": sb["id"], "reprocessing_cycle_id": cya["id"]}, NURSE)
        validate_error(resp, ApiErrorId.ERR_CULTURE_SCOPE_MISMATCH)
        assert resp.status_code == 400

    def test_reprocessing_technician_cannot_record_culture_result(self, api):
        """PRD §2.1: "a caller whose role is not in the endpoint's permitted set
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/endoscopy/culture-tests` | Create a surveillance
        culture test against a COMPLETE reprocessing cycle | InfectionControlNurse
        |"

        Design: Corner/rbac/reprocessing_technician_cannot_record_culture_result
        """
        scope = create_scope(serial_number="SC-RB1")
        resp = api.create_culture_test(
            {"scope_id": scope["id"], "reprocessing_cycle_id": NON_EXISTENT_UUID},
            make_technician_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_culture_test_not_found_returns_404(self, api):
        """
        PRD §2.6: "Each unresolved reference maps to its own error:
        `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_PROCEDURE_TYPE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND` (also raised for an
        unresolvable `new_room_id`), `ERR_ANESTHESIA_PROVIDER_NOT_FOUND`,
        `ERR_SCOPE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_SCOPE_USAGE_NOT_FOUND`,
        `ERR_REPROCESSING_CYCLE_NOT_FOUND`, `ERR_CULTURE_TEST_NOT_FOUND`,
        `ERR_QUARANTINE_CASE_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`,
        `ERR_QUALITY_REPORT_NOT_FOUND`, and `ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND`,
        all HTTP 404."

        Design: Corner/errors/culture_test_not_found_returns_404
        """
        resp = api.get_culture_test(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CULTURE_TEST_NOT_FOUND)


class TestCultureResult:
    def test_positive_culture_requires_organism_and_cfu(self, api):
        """PRD §3.7: "a `POSITIVE` result must be accompanied by an `organism`
        name and a `cfu_count` of zero or more, and a positive without them fails
        schema validation with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/positive_culture_requires_organism_and_cfu
        """
        scope, cycle = create_reprocessed_scope(serial_number="SC-PO", lot="LOT-P")
        culture = create_culture(scope["id"], cycle["id"])
        resp = api.result_culture_test(culture["id"], {"result": "POSITIVE"}, NURSE)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        after = validate_success(api.get_culture_test(culture["id"], NURSE))
        assert after["status"] == "PENDING"
        cases, meta = validate_paginated(api.list_quarantine_cases(
            NURSE, params={"scope_id": scope["id"]}))
        assert cases == [], "no QuarantineCase created by a rejected result"

    def test_culture_result_twice_rejected(self, api):
        """PRD §3.7: "Recording the result is likewise the
        `InfectionControlNurse`'s act and is legal only while the test is
        `PENDING` (`ERR_CULTURE_ALREADY_RESULTED` on a second attempt)."

        Design: Corner/state_machines/culture_result_twice_rejected
        """
        scope, cycle = create_reprocessed_scope(serial_number="SC-CT2", lot="LOT-C")
        culture = create_culture(scope["id"], cycle["id"])
        result_culture(culture["id"], "NEGATIVE")
        resp = api.result_culture_test(
            culture["id"], {"result": "POSITIVE", "organism": "E_COLI",
                            "cfu_count": 5}, NURSE)
        validate_error(resp, ApiErrorId.ERR_CULTURE_ALREADY_RESULTED)
        after = validate_success(api.get_culture_test(culture["id"], NURSE))
        assert after["result"] == "NEGATIVE"
        cases, _meta = validate_paginated(api.list_quarantine_cases(
            NURSE, params={"scope_id": scope["id"]}))
        assert cases == [], "no quarantine from a rejected second result"


class TestScopeCycleLoop:
    def _loop_to_second_cycle(self):
        reg = make_registry(mrn="M3301", serial="SC-LOOP")
        sc = reg["scope"]
        dr1 = reg["provider"]
        b1 = create_booking(reg["patient"]["id"], dr1["id"], reg["ptype"]["id"],
                            reg["room"]["id"], scheduled_start="2026-08-10T09:00:00Z")
        confirm_prep(b1["id"])
        cy1 = run_complete_cycle(sc["id"], "2026-08-10T08:00:00Z", lot="LOT-1",
                                 send_first=True)
        after_c1 = get_scope(sc["id"])
        run_procedure_to_complete(b1["id"], dr1["id"], sc["id"],
                                  "2026-08-10T09:00:00Z", "2026-08-10T09:40:00Z",
                                  bbps=(3, 3, 3), withdrawal_time_seconds=500)
        cy2 = run_complete_cycle(sc["id"], "2026-08-10T10:00:00Z", lot="LOT-2",
                                 booking_id=b1["id"])
        return reg, b1, cy1, after_c1, cy2

    def test_scope_cyclic_loop_closes_twice_and_refreshes_expiry(self, api):
        """PRD §3.6: "A scope's life is a cycle: `AVAILABLE` → `IN_USE` →
        `AWAITING_REPROCESS` → `REPROCESSING` → back to `AVAILABLE`".
        PRD §3.6: "in either case the scope's `storage_expires_at` is set to the
        cycle's `dried_at` plus 72 hours."
        PRD §3.4: "The chosen scope moves to `IN_USE` and its `use_count`
        increments by one".

        Design: Difficulty/non_linear_state_machine/scope_cyclic_loop_with_quarantine_branch
        """
        _reg, _b1, _cy1, after_c1, _cy2 = self._loop_to_second_cycle()
        assert after_c1["status"] == "AVAILABLE"
        assert_instants_equal(after_c1["storage_expires_at"], "2026-08-13T08:26:00Z")
        after_c2 = get_scope(_reg["scope"]["id"])
        assert after_c2["status"] == "AVAILABLE", "loop closed a second time"
        assert_instants_equal(after_c2["storage_expires_at"], "2026-08-13T10:26:00Z")
        assert after_c2["use_count"] == 1

    def test_quarantine_branch_reculture_stays_quarantined_until_release(self, api):
        """PRD §3.6: "When the cycle completes, its scope returns to `AVAILABLE` —
        unless the scope is under quarantine, in which case it stays `QUARANTINED`
        while the disinfection documentation is preserved".
        PRD §3.7: "A release that passes everything moves the scope from
        `QUARANTINED` back to `AVAILABLE` and settles the case at `RELEASED` with
        `released_by` set from the caller and `resolved_at` stamped."
        PRD §3.6: "When the scope was `QUARANTINED`, the cycle is flagged
        `is_reculture` true".

        Design: Difficulty/non_linear_state_machine/scope_cyclic_loop_with_quarantine_branch
        """
        reg, b1, _cy1, _after_c1, cy2 = self._loop_to_second_cycle()
        sc = reg["scope"]
        advance_clock("2026-08-10T10:30:00Z")
        cpos = create_culture(sc["id"], cy2["id"])
        result_culture(cpos["id"], "POSITIVE", organism="KLEBSIELLA_PNEUMONIAE",
                       cfu_count=120)
        assert get_scope(sc["id"])["status"] == "QUARANTINED"

        cy3 = run_reculture_cycle(sc["id"], technician_id="tech-9",
                                  start_iso="2026-08-10T10:45:00Z", lot="LOT-3")
        assert cy3["is_reculture"] is True
        assert get_scope(sc["id"])["status"] == "QUARANTINED", (
            "reculture completion does not free the scope")

        advance_clock("2026-08-10T11:30:00Z")
        cneg = create_culture(sc["id"], cy3["id"])
        result_culture(cneg["id"], "NEGATIVE")
        version = get_scope(sc["id"])["version"]
        data = validate_success(api.release_quarantine(
            sc["id"], {"expected_scope_version": version}, make_nurse_headers("nurse-1")),
            200)
        assert data["status"] == "AVAILABLE"
        case = first_case_for_scope(sc["id"])
        assert case["status"] == "RELEASED"
        assert case["released_by"] == "nurse-1"


class TestExposureCascade:
    def _trigger_positive(self, fx):
        c1 = create_culture(fx["scope"]["id"], fx["cyc"]["id"])
        result_culture(c1["id"], "POSITIVE", organism="KLEBSIELLA_PNEUMONIAE",
                       cfu_count=120)
        return c1

    def test_positive_culture_creates_case_with_exposure_window(self, api):
        """PRD §3.7: "Its end — the case's `exposure_window_end` — is the
        triggering culture's `sampled_at`. Its start — `exposure_window_start` —
        is the `sampled_at` of the latest `NEGATIVE` culture on the same scope
        taken strictly before the trigger".
        PRD §3.7: "A QuarantineCase opens in `OPEN` status with `opened_at`
        stamped, the `triggering_culture_id` recorded, and the window fields
        populated; the scope itself moves to `QUARANTINED`".

        Design: Difficulty/transitive_cascade/positive_culture_cascades_to_patient_recall_flags
        """
        fx = setup_exposure_scenario()
        c1 = self._trigger_positive(fx)
        assert get_scope(fx["scope"]["id"])["status"] == "QUARANTINED"
        case = first_case_for_scope(fx["scope"]["id"])
        assert case["status"] == "OPEN"
        assert case["triggering_culture_id"] == c1["id"]
        assert_instants_equal(case["exposure_window_start"], "2026-08-09T08:00:00Z")
        assert_instants_equal(case["exposure_window_end"], "2026-08-14T10:00:00Z")

    def test_exposure_window_boundaries_flag_usages_and_bookings(self, api):
        """PRD §3.7: "the interval is left-exclusive and right-inclusive, so a
        usage ending exactly at the last negative sample is excluded while one
        ending exactly at the trigger is included. Every usage in the set gets
        `exposure_flagged` set true, and each of their bookings gets
        `notification_flag` set true, which is how the recall list surfaces."

        Design: Difficulty/transitive_cascade/positive_culture_cascades_to_patient_recall_flags
        """
        fx = setup_exposure_scenario()
        self._trigger_positive(fx)
        case = first_case_for_scope(fx["scope"]["id"])
        exposures, _meta = validate_paginated(
            api.list_quarantine_case_exposures(case["id"], NURSE))
        assert {row["id"] for row in exposures} == {
            fx["u1"]["id"], fx["u2"]["id"], fx["u3"]["id"]}
        assert get_usage(fx["u_edge"]["id"])["exposure_flagged"] is False, (
            "usage ending exactly at the window start is excluded")
        assert get_usage(fx["u3"]["id"])["exposure_flagged"] is True, (
            "usage ending exactly at the trigger is included")
        for key in ("b1", "b2", "b3"):
            assert get_booking(fx[key]["id"])["notification_flag"] is True
        assert get_booking(fx["b_edge"]["id"])["notification_flag"] is False

    def test_exposure_window_uses_latest_negative_culture(self, api):
        """PRD §3.7: "Its start — `exposure_window_start` — is the `sampled_at` of
        the latest `NEGATIVE` culture on the same scope taken strictly before the
        trigger; if two such cultures share a timestamp, the one created later
        wins".

        Design: Corner/calculations/exposure_window_uses_latest_negative_culture
        """
        fx = setup_two_negative_cultures_scenario()
        advance_clock("2026-08-10T08:00:00Z")
        cp = create_culture(fx["scope"]["id"], fx["cyc"]["id"])
        result_culture(cp["id"], "POSITIVE", organism="SALMONELLA", cfu_count=60)
        case = first_case_for_scope(fx["scope"]["id"])
        assert_instants_equal(case["exposure_window_start"], "2026-08-09T08:00:00Z")
        exposures, _meta = validate_paginated(
            api.list_quarantine_case_exposures(case["id"], NURSE))
        assert [row["id"] for row in exposures] == [fx["u_in"]["id"]], (
            "the usage that ended before the latest negative is not exposed")
        assert get_usage(fx["u_mid"]["id"])["exposure_flagged"] is False


class TestQuarantineRelease:
    def test_release_without_reculture_cycle_rejected(self, api):
        """PRD §3.7: "A `NEGATIVE` culture must already exist against the case's
        `reculture_cycle_id` (`ERR_RECULTURE_NOT_NEGATIVE`)."

        Design: Difficulty/cross_entity_state_dependency/quarantine_release_requires_negative_reculture
        """
        scope, _q0, _c0, case = create_quarantined_scope(serial_number="SQ-1")
        version = get_scope(scope["id"])["version"]
        resp = api.release_quarantine(scope["id"], {"expected_scope_version": version},
                                      make_nurse_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_RECULTURE_NOT_NEGATIVE)
        assert get_case(case["id"])["status"] == "OPEN"

    def test_release_after_negative_reculture_succeeds(self, api):
        """PRD §3.7: "Creating a reprocessing cycle on the quarantined scope —
        §3.6 — moves the case from `OPEN` to `RECULTURING` and records the cycle
        as `reculture_cycle_id`; when that reculture cycle completes, the scope
        remains `QUARANTINED`, awaiting a verdict."
        PRD §3.7: "A release that passes everything moves the scope from
        `QUARANTINED` back to `AVAILABLE` and settles the case at `RELEASED` with
        `released_by` set from the caller and `resolved_at` stamped."

        Design: Difficulty/cross_entity_state_dependency/quarantine_release_requires_negative_reculture
        """
        scope, _q0, _c0, case = create_quarantined_scope(serial_number="SQ-2")
        advance_clock("2026-08-20T09:30:00Z")
        q1 = create_cycle(scope["id"], technician_id="tech-7")
        assert get_case(case["id"])["status"] == "RECULTURING"
        assert get_case(case["id"])["reculture_cycle_id"] == q1["id"]
        advance_step(q1["id"], "PRECLEANED", "tech-7")
        advance_clock("2026-08-20T09:51:00Z")  # 21 min: satisfies both soak modes
        advance_step(q1["id"], "CLEANED", "tech-7")
        advance_clock("2026-08-20T10:01:00Z")
        advance_step(q1["id"], "DISINFECTED", "tech-7",
                     hld_solution_lot="LOT-Q1", hld_concentration_ppm=400)
        advance_clock("2026-08-20T10:11:00Z")
        advance_step(q1["id"], "DRIED", "tech-7")
        advance_step(q1["id"], "COMPLETE", "tech-7")
        assert get_scope(scope["id"])["status"] == "QUARANTINED"

        # Reculture COMPLETE but no resulted culture yet: still rejected.
        version = get_scope(scope["id"])["version"]
        resp = api.release_quarantine(scope["id"], {"expected_scope_version": version},
                                      make_nurse_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_RECULTURE_NOT_NEGATIVE)

        advance_clock("2026-08-20T10:15:00Z")
        cq1 = create_culture(scope["id"], q1["id"])
        result_culture(cq1["id"], "NEGATIVE")
        version = get_scope(scope["id"])["version"]
        data = validate_success(api.release_quarantine(
            scope["id"], {"expected_scope_version": version},
            make_nurse_headers("nurse-1")), 200)
        assert data["status"] == "AVAILABLE"
        case_after = get_case(case["id"])
        assert case_after["status"] == "RELEASED"
        assert case_after["released_by"] == "nurse-1"
        assert case_after["reculture_cycle_id"] == q1["id"]

    def test_segregation_of_duties_blocks_releaser_who_reprocessed(self, api):
        """PRD §3.7: "And segregation of duties forbids the releaser from being
        the technician who performed the reculture cycle: the caller's `X-User-ID`
        must differ from the reculture cycle's `technician_id`
        (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/rbac/segregation_of_duties_blocks_releaser_who_reprocessed
        """
        scope, _q0, q1, _case = create_release_ready_scope(
            serial_number="SQ-SOD", reculture_technician="tech-7")
        version = get_scope(scope["id"])["version"]
        resp = api.release_quarantine(scope["id"], {"expected_scope_version": version},
                                      make_nurse_headers("tech-7"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        version = get_scope(scope["id"])["version"]
        data = validate_success(api.release_quarantine(
            scope["id"], {"expected_scope_version": version},
            make_nurse_headers("nurse-1")), 200)
        assert data["status"] == "AVAILABLE"

    def test_release_without_open_quarantine_rejected(self, api):
        """PRD §3.7: "An open quarantine case must exist for the scope, `OPEN` or
        `RECULTURING` (`ERR_NO_OPEN_QUARANTINE`)."

        Design: Corner/state_machines/release_without_open_quarantine_rejected
        """
        scope = create_scope(serial_number="SC-NOQ")
        version = get_scope(scope["id"])["version"]
        resp = api.release_quarantine(scope["id"], {"expected_scope_version": version},
                                      make_nurse_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_QUARANTINE)
        assert get_scope(scope["id"])["status"] == "AVAILABLE"


class TestRetirement:
    def test_retire_in_use_scope_rejected(self, api):
        """PRD §3.6: "Retirement is a `UnitAdmin` decision available from
        `AVAILABLE`, `AWAITING_REPROCESS`, or `QUARANTINED`; a scope that is
        `IN_USE` or `REPROCESSING` cannot be retired (`ERR_SCOPE_NOT_RETIRABLE`)."

        Design: Corner/state_machines/retire_in_use_scope_rejected
        """
        reg = make_registry(mrn="MRN-IU", serial="SC-INUSE")
        create_in_progress_booking(
            reg["patient"]["id"], reg["provider"]["id"], reg["ptype"]["id"],
            reg["room"]["id"], reg["scope"]["id"])
        resp = api.retire_scope(reg["scope"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SCOPE_NOT_RETIRABLE)
        assert get_scope(reg["scope"]["id"])["status"] == "IN_USE"

    def test_retire_quarantined_scope_closes_case(self, api):
        """PRD §3.6: "Retirement moves the scope to `OUT_OF_SERVICE`, and if a
        quarantine case is open on it, the case settles at `SCOPE_RETIRED` with
        `resolved_at` stamped."

        Design: Corner/state_machines/retire_quarantined_scope_closes_case
        """
        scope, _cy, _ct, case = create_quarantined_scope(serial_number="SC-RQ",
                                                         day="2026-08-01")
        data = validate_success(api.retire_scope(scope["id"], ADMIN), 200)
        assert data["status"] == "OUT_OF_SERVICE"
        case_after = get_case(case["id"])
        assert case_after["status"] == "SCOPE_RETIRED"
        assert case_after["resolved_at"] is not None
        assert_instants_equal(case_after["resolved_at"], "2026-08-01T09:00:00Z")

    def test_quarantine_case_not_found_returns_404(self, api):
        """
        PRD §2.6: "Each unresolved reference maps to its own error:
        `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_PROCEDURE_TYPE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND` (also raised for an
        unresolvable `new_room_id`), `ERR_ANESTHESIA_PROVIDER_NOT_FOUND`,
        `ERR_SCOPE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_SCOPE_USAGE_NOT_FOUND`,
        `ERR_REPROCESSING_CYCLE_NOT_FOUND`, `ERR_CULTURE_TEST_NOT_FOUND`,
        `ERR_QUARANTINE_CASE_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`,
        `ERR_QUALITY_REPORT_NOT_FOUND`, and `ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND`,
        all HTTP 404."

        Design: Corner/errors/quarantine_case_not_found_returns_404
        """
        resp = api.get_quarantine_case(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_QUARANTINE_CASE_NOT_FOUND)
