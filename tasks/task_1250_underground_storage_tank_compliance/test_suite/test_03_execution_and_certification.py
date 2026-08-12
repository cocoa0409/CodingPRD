"""Fieldwork execution, result determination, certification & rework (PRD §3.4, §3.5)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_owner_headers, make_technician_headers,
    make_reviewer_headers,
    assert_result_record, assert_ts_equal,
    set_clock, create_technician, create_order, schedule_order, start_order,
    record_results, certify_order, get_order, get_component, get_deficiency,
    deficiency_for_order, latest_result_record,
    setup_active_facility_with_tank, setup_tightness_site,
    setup_started_tightness_order, setup_cp_site, setup_started_cp_order,
    create_started_order, add_component,
    tightness_readings, lld_readings, spill_readings, cp_readings,
    cp_divergence_readings,
    api_client,
)

OWNER = TEST_USERS["facility_owner_headers"]
ADMIN = TEST_USERS["contractor_admin_headers"]
READER = TEST_USERS["any_headers"]


class TestStartGates:
    def test_start_by_non_assigned_technician_forbidden(self, api):
        """PRD §3.4: "Only the assigned technician may start an order, and only
        inside its window: starting requires the order to be `SCHEDULED`
        (`ERR_ORDER_NOT_SCHEDULED`), the caller's `X-User-ID` to equal the order's
        `technician_id` (`ERR_NOT_RESOURCE_OWNER`)"

        Design: Corner/state_machines/start_by_non_assigned_technician_forbidden
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_tightness_site()
        t2 = create_technician(["TIGHTNESS_TESTER"], full_name="T2")
        order = create_order(ctx["facility"]["id"], ctx["tank"]["id"], "TANK_TIGHTNESS")
        schedule_order(order["id"], ctx["tester"]["id"],
                       "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")
        set_clock("2026-05-02T10:30:00Z")
        res = api.start_service_order(order["id"], make_technician_headers(t2["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)

    def test_start_outside_window_rejected(self, api):
        """PRD §3.4: "the logical clock to fall at or after `window_start` and at
        or before `window_end` (`ERR_OUTSIDE_SERVICE_WINDOW` when outside).
        Starting moves the order `SCHEDULED` → `IN_PROGRESS` and records the caller
        as `performed_by_technician_id`."

        Design: Corner/validations/start_outside_window_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_tightness_site()
        order = create_order(ctx["facility"]["id"], ctx["tank"]["id"], "TANK_TIGHTNESS")
        schedule_order(order["id"], ctx["tester"]["id"],
                       "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")

        set_clock("2026-05-02T09:00:00Z")  # before window_start
        res = api.start_service_order(
            order["id"], make_technician_headers(ctx["tester"]["id"]))
        validate_error(res, ApiErrorId.ERR_OUTSIDE_SERVICE_WINDOW)

        # At exactly window_start the containment gate passes (inclusive bound).
        started = start_order(order["id"], ctx["tester"]["id"], "2026-05-02T10:00:00Z")
        assert started["status"] == "IN_PROGRESS"
        assert started["performed_by_technician_id"] == ctx["tester"]["id"]


class TestResultDetermination:
    def test_tightness_rate_exactly_threshold_passes(self, api):
        """PRD §3.4: "For `TANK_TIGHTNESS` and `LINE_TIGHTNESS`, the reading is
        `leak_rate_gph` in gallons per hour compared at 3 decimal places: the test
        passes when the leak rate is at most 0.100 — a reading of exactly 0.100
        passes — and fails otherwise."

        Design: Difficulty/boundary_precision_check/tightness_rate_exactly_threshold_passes
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_started_tightness_order()
        record_results(ctx["order"]["id"], ctx["tester"]["id"],
                       tightness_readings(0.100))
        record = latest_result_record(ctx["order"]["id"])
        assert record["outcome"] == "PASS", "0.100 <= 0.100: inclusive bound passes"

    def test_tightness_pass_at_threshold_creates_no_deficiency(self, api):
        """PRD §3.4: "When a `TANK_TIGHTNESS` or `LINE_TIGHTNESS` order fails, the
        system opens a `CRITICAL` deficiency of origin `TEST_FAILURE`" and
        "simultaneously opens a `SUSPECTED` release event with `discovered_at` set
        to the current clock and `tank_system_id` set to the tested tank" — a
        passing reading opens neither.

        Design: Difficulty/boundary_precision_check/tightness_rate_exactly_threshold_passes
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_started_tightness_order()
        record_results(ctx["order"]["id"], ctx["tester"]["id"],
                       tightness_readings(0.100))

        data, meta = validate_paginated(api.list_deficiencies(
            READER, params={"tank_system_id": ctx["tank"]["id"]}))
        assert meta["total_count"] == 0, "no deficiency on a boundary PASS"
        data, meta = validate_paginated(api.list_release_events(
            READER, params={"tank_system_id": ctx["tank"]["id"]}))
        assert meta["total_count"] == 0, "no release event on a boundary PASS"

    def test_spill_overfill_boundary_values_pass(self, api):
        """PRD §3.4: "For `SPILL_OVERFILL_INSPECTION`, passing requires all three
        conditions: `visual_cracks_found` is false, `drain_test_hold_minutes` is at
        least 5 minutes (exactly 5 passes), and `overfill_activates_pct` — compared
        at 1 decimal place — is at most 95.0 (exactly 95.0 passes)."

        Design: Corner/calculations/spill_overfill_boundary_values_pass
        """
        set_clock("2026-05-01T00:00:00Z")
        facility, tank = setup_active_facility_with_tank()
        comp = add_component(tank["id"], "SPILL_BUCKET", serial_no="SB-9")
        t_in = create_technician(["INSPECTOR"], full_name="Insp")
        ctx = {"facility": facility, "tank": tank, "tester": t_in}
        so1 = create_started_order(ctx, "SPILL_OVERFILL_INSPECTION",
                                   "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z",
                                   "2026-05-02T10:30:00Z", component_id=comp["id"],
                                   line_items=[{"description": "s1", "qty": 1,
                                                "unit_price_cents": 30000}])
        so2 = create_order(facility["id"], tank["id"], "SPILL_OVERFILL_INSPECTION",
                           component_id=comp["id"],
                           line_items=[{"description": "s2", "qty": 1,
                                        "unit_price_cents": 30000}])
        schedule_order(so2["id"], t_in["id"],
                       "2026-05-03T10:00:00Z", "2026-05-03T11:00:00Z")

        # Both inclusive bounds hit exactly: hold 5, overfill 95.0 -> PASS.
        record_results(so1["id"], t_in["id"],
                       spill_readings(False, 5, 95.0))
        start_order(so2["id"], t_in["id"], "2026-05-03T10:30:00Z")
        # Hold 4 < 5 -> FAIL.
        record_results(so2["id"], t_in["id"],
                       spill_readings(False, 4, 95.0))

        assert latest_result_record(so1["id"])["outcome"] == "PASS"
        assert latest_result_record(so2["id"])["outcome"] == "FAIL"
        deficiency = deficiency_for_order(so2["id"])
        assert deficiency["severity"] == "MAJOR"
        data, meta = validate_paginated(api.list_deficiencies(
            READER, params={"source_service_order_id": so1["id"]}))
        assert meta["total_count"] == 0, "the boundary PASS opened no deficiency"
        data, meta = validate_paginated(
            api.list_components(READER, params={"tank_system_id": tank["id"]}))
        assert meta["total_count"] == 1

    def test_lld_result_determination(self, api):
        """PRD §3.4: "For `LLD_FUNCTION`, the reading `detects_simulated_leak` must
        be true to pass." and "When a `CP_SURVEY`, `LLD_FUNCTION`, or
        `SPILL_OVERFILL_INSPECTION` order fails, the system instead opens a `MAJOR`
        deficiency of origin `TEST_FAILURE` referencing the tested component, and
        that component moves to `DEFICIENT`."

        Design: Corner/calculations/lld_result_determination
        """
        set_clock("2026-05-01T00:00:00Z")
        facility, tank = setup_active_facility_with_tank()
        comp = add_component(tank["id"], "LINE_LEAK_DETECTOR", serial_no="LLD-9")
        t_lld = create_technician(["LLD_TESTER"], full_name="LLD Tech")
        ctx = {"facility": facility, "tank": tank, "tester": t_lld}
        order = create_started_order(ctx, "LLD_FUNCTION",
                                     "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z",
                                     "2026-05-02T10:30:00Z", component_id=comp["id"],
                                     line_items=[{"description": "lld", "qty": 1,
                                                  "unit_price_cents": 25000}])
        record_results(order["id"], t_lld["id"], lld_readings(False))

        assert latest_result_record(order["id"])["outcome"] == "FAIL"
        deficiency = deficiency_for_order(order["id"])
        assert deficiency["severity"] == "MAJOR"
        assert get_component(comp["id"])["status"] == "DEFICIENT"
        data, meta = validate_paginated(api.list_release_events(
            READER, params={"tank_system_id": tank["id"]}))
        assert meta["total_count"] == 0, "an LLD failure opens no release event"


class TestCpSurveyDualCriterion:
    def _setup_two_started_cp_orders(self):
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_cp_site()
        ctx["so1"] = create_started_order(
            ctx, "CP_SURVEY", "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z",
            "2026-05-02T10:30:00Z", component_id=ctx["component"]["id"],
            line_items=[{"description": "cp survey", "qty": 1,
                         "unit_price_cents": 40000}])
        ctx["so2"] = create_started_order(
            ctx, "CP_SURVEY", "2026-05-03T10:00:00Z", "2026-05-03T11:00:00Z",
            "2026-05-03T10:30:00Z", component_id=ctx["component"]["id"],
            line_items=[{"description": "cp survey 2", "qty": 1,
                         "unit_price_cents": 40000}])
        return ctx

    def test_cp_identical_triple_fails_instant_off(self, api):
        """PRD §3.4: "under `INSTANT_OFF`, the survey passes when `instant_off_mv`
        is at most −850 millivolts — that is, at least 850 millivolts of cathodic
        polarization, with exactly −850 passing." and "The two criteria are
        genuinely different instruments: an identical voltage triple can pass under
        `POLARIZATION_SHIFT` while failing under `INSTANT_OFF`."

        Design: Difficulty/dual_variant_calc/cp_survey_criterion_divergence_same_readings
        """
        ctx = self._setup_two_started_cp_orders()
        record_results(ctx["so1"]["id"], ctx["tester"]["id"],
                       cp_divergence_readings("INSTANT_OFF"))
        record_results(ctx["so2"]["id"], ctx["tester"]["id"],
                       cp_divergence_readings("POLARIZATION_SHIFT"))

        r1 = latest_result_record(ctx["so1"]["id"])
        r2 = latest_result_record(ctx["so2"]["id"])
        assert r1["outcome"] == "FAIL", "-800 is not <= -850 under INSTANT_OFF"
        assert r2["outcome"] == "PASS", "-500 - (-700) = 200 >= 100 under POLARIZATION_SHIFT"
        assert r1["outcome"] != r2["outcome"], (
            "identical voltage triples diverge across the two criteria")

    def test_cp_fail_opens_major_deficiency_pass_does_not(self, api):
        """PRD §3.4: "When a `CP_SURVEY`, `LLD_FUNCTION`, or
        `SPILL_OVERFILL_INSPECTION` order fails, the system instead opens a `MAJOR`
        deficiency of origin `TEST_FAILURE` referencing the tested component, and
        that component moves to `DEFICIENT`."

        Design: Difficulty/dual_variant_calc/cp_survey_criterion_divergence_same_readings
        """
        ctx = self._setup_two_started_cp_orders()
        record_results(ctx["so1"]["id"], ctx["tester"]["id"],
                       cp_divergence_readings("INSTANT_OFF"))
        record_results(ctx["so2"]["id"], ctx["tester"]["id"],
                       cp_divergence_readings("POLARIZATION_SHIFT"))

        deficiency = deficiency_for_order(ctx["so1"]["id"])
        assert deficiency["severity"] == "MAJOR"
        data, meta = validate_paginated(api.list_deficiencies(
            READER, params={"source_service_order_id": ctx["so2"]["id"]}))
        assert meta["total_count"] == 0, "the passing survey opened no deficiency"


class TestReworkCycle:
    def _run_rework_loop(self):
        """CP order: INCONCLUSIVE record -> return-for-correction -> PASS record
        -> certify. Returns (ctx, order)."""
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_started_cp_order()
        order_id = ctx["order"]["id"]
        record_results(order_id, ctx["tester"]["id"],
                       cp_readings(valid_contact=False))  # INCONCLUSIVE
        validate_success(api_client.return_for_correction(
            order_id, make_reviewer_headers(ctx["reviewer"]["id"])), 200)
        record_results(order_id, ctx["tester"]["id"],
                       cp_readings())  # PASS (-900 <= -850)
        certify_order(order_id, ctx["reviewer"]["id"])
        return ctx, get_order(order_id)

    def test_rework_cycle_converges_certified_latest_outcome_wins(self, api):
        """PRD §3.5: "Returning an order for correction moves it `UNDER_REVIEW` →
        `IN_PROGRESS` for rework; the recorded `result_outcome` stays as it was,
        and all prior ResultRecords remain immutable."
        PRD §3.4: "When `valid_contact` is false, the outcome is `INCONCLUSIVE`
        and the voltages are ignored." and "mirrors that outcome onto the order's
        `result_outcome` — so `result_outcome` always reflects the latest
        ResultRecord on the order."

        Design: Difficulty/non_linear_state_machine/service_order_review_rework_cycle
        """
        ctx, order = self._run_rework_loop()
        assert order["status"] == "CERTIFIED", (
            "IN_PROGRESS -> UNDER_REVIEW -> IN_PROGRESS -> UNDER_REVIEW -> CERTIFIED")
        assert order["result_outcome"] == "PASS", "latest record wins"

        data, meta = validate_paginated(api.list_result_records(
            READER, params={"service_order_id": order["id"]}))
        assert meta["total_count"] == 2
        assert data[0]["outcome"] == "INCONCLUSIVE"
        assert data[1]["outcome"] == "PASS"

    def test_rework_history_is_append_only_oldest_first(self, api):
        """PRD §3.5: "A subsequent results recording simply adds a new ResultRecord
        — the result-record ledger lists oldest first, filterable by
        `service_order_id` and `outcome`, so a multi-record rework history replays
        deterministically."

        Design: Difficulty/non_linear_state_machine/service_order_review_rework_cycle
        """
        ctx, order = self._run_rework_loop()
        data, _ = validate_paginated(api.list_result_records(
            READER, params={"service_order_id": order["id"]}))
        assert len(data) == 2, "rework history preserved both records"
        first, second = data
        for rec in (first, second):
            assert_result_record(rec)
        # Oldest first: the INCONCLUSIVE record precedes the PASS record and was
        # never mutated by the later recording or the certification.
        assert first["outcome"] == "INCONCLUSIVE"
        assert first["readings"]["valid_contact"] is False
        assert second["outcome"] == "PASS"


class TestResultRecordImmutability:
    def test_result_record_immutable_no_version_field(self, api):
        """PRD §2.5: "Two resources are deliberately immutable ledgers and deviate
        from this convention: a ResultRecord and a TrainingRecord each carry only
        `id` and `created_at`. Both `updated_at` and `version` are absent from
        them, because neither resource can ever be modified after creation."
        PRD §3.4: "Recording results creates an immutable ResultRecord bound to
        the order through `service_order_id`, stamped with `recorded_at` from the
        logical clock, carrying a computed `outcome`"

        Design: Corner/entities/result_record_immutable_no_version_field
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_started_tightness_order()
        record_results(ctx["order"]["id"], ctx["tester"]["id"],
                       tightness_readings(0.05))
        record = latest_result_record(ctx["order"]["id"])

        detail = validate_success(api.get_result_record(record["id"], READER), 200)
        assert_result_record(detail)
        for key in ("id", "created_at", "service_order_id", "readings",
                    "outcome", "recorded_at"):
            assert key in detail, f"ResultRecord must carry {key}"
        assert "version" not in detail and "updated_at" not in detail
        assert detail["outcome"] == "PASS"
        assert_ts_equal(detail["recorded_at"], "2026-05-02T10:30:00Z",
                        label="recorded_at equals the logical clock at recording")


class TestCertificationGates:
    def test_self_certification_rejected(self, api):
        """PRD §2.11: "The person who performs a test may never be the person who
        certifies it." and "Certification by the same technician who performed the
        work is rejected with `ERR_SELF_CERTIFICATION` (HTTP 403)."

        Design: Corner/validations/self_certification_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_started_tightness_order()
        record_results(ctx["order"]["id"], ctx["tester"]["id"],
                       tightness_readings(0.05))
        res = api.certify_service_order(
            ctx["order"]["id"], make_reviewer_headers(ctx["tester"]["id"]))
        validate_error(res, ApiErrorId.ERR_SELF_CERTIFICATION, expected_status=403)
        order = get_order(ctx["order"]["id"])
        assert order["status"] == "UNDER_REVIEW", "rejected certify changed nothing"

    def test_certify_state_error_precedes_self_certification(self, api):
        """PRD §2.7: "When several checks guard the same operation, the system
        evaluates them in a fixed precedence so that the earliest failing check
        determines the error returned, and no later check can mask an earlier
        failure." and "5. State preconditions — the target resource sits in the
        from-state the transition requires." and "6. Segregation of duties at
        certification."

        Design: Difficulty/priority_pair_validation_conflict/certify_state_error_precedes_self_certification
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_started_tightness_order()  # IN_PROGRESS, performed by tester
        # Caller IS the performing technician (self-certification) AND the order
        # is not UNDER_REVIEW: the state error must win.
        res = api.certify_service_order(
            ctx["order"]["id"], make_reviewer_headers(ctx["tester"]["id"]))
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_UNDER_REVIEW, expected_status=409)

    def test_certify_state_error_no_side_effects(self, api):
        """PRD §3.5: "A `ComplianceReviewer` certifies an order in `UNDER_REVIEW`
        (`ERR_ORDER_NOT_UNDER_REVIEW` otherwise)"
        PRD §2.7: "5. State preconditions — the target resource sits in the
        from-state the transition requires. 6. Segregation of duties at
        certification."

        Design: Difficulty/priority_pair_validation_conflict/certify_state_error_precedes_self_certification
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_started_tightness_order()
        res = api.certify_service_order(
            ctx["order"]["id"], make_reviewer_headers(ctx["tester"]["id"]))
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_UNDER_REVIEW, expected_status=409)
        order = get_order(ctx["order"]["id"])
        assert order["status"] == "IN_PROGRESS"
        assert order.get("certified_by_technician_id") is None

    def test_certify_from_requested_rejected(self, api):
        """PRD §3.5: "A `ComplianceReviewer` certifies an order in `UNDER_REVIEW`
        (`ERR_ORDER_NOT_UNDER_REVIEW` otherwise)"

        Design: Corner/state_machines/certify_from_requested_rejected
        """
        from test_helpers import create_facility, create_tank
        facility = create_facility(facility_name="BadTrans Site")
        tank = create_tank(facility["id"])
        order = create_order(facility["id"], tank["id"], "TANK_TIGHTNESS")
        reviewer = create_technician([], full_name="Reviewer")
        res = api.certify_service_order(
            order["id"], make_reviewer_headers(reviewer["id"]))
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_UNDER_REVIEW, expected_status=409)
        order = get_order(order["id"])
        assert order["status"] == "REQUESTED"
        assert order.get("certified_by_technician_id") is None

    def test_certified_order_terminal_lockdown(self, api):
        """PRD §3.5: "Certification stamps `certified_by_technician_id` with the
        caller and moves the order to its terminal `CERTIFIED` state." and "A
        `ComplianceReviewer` certifies an order in `UNDER_REVIEW`
        (`ERR_ORDER_NOT_UNDER_REVIEW` otherwise)"; "Review can instead bounce the
        work back. Returning an order for correction moves it `UNDER_REVIEW` →
        `IN_PROGRESS` for rework"

        Design: Corner/state_machines/certified_order_terminal_lockdown
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_started_cp_order()
        record_results(ctx["order"]["id"], ctx["tester"]["id"], cp_readings())
        certify_order(ctx["order"]["id"], ctx["reviewer"]["id"])
        assert get_order(ctx["order"]["id"])["status"] == "CERTIFIED"

        res1 = api.certify_service_order(
            ctx["order"]["id"], make_reviewer_headers(ctx["reviewer"]["id"]))
        validate_error(res1, ApiErrorId.ERR_ORDER_NOT_UNDER_REVIEW)
        res2 = api.return_for_correction(
            ctx["order"]["id"], make_reviewer_headers(ctx["reviewer"]["id"]))
        validate_error(res2, ApiErrorId.ERR_ORDER_NOT_UNDER_REVIEW)


class TestFieldWorkRoleSegregation:
    def test_reviewer_cannot_record_results_forbidden(self, api):
        """PRD §2.1: "When the caller's role is not among the roles an endpoint
        authorizes, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /service-orders/{id}/results is authorized to `Technician`.

        Design: Corner/rbac/reviewer_cannot_record_results_forbidden
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_started_tightness_order()
        reviewer = create_technician([], full_name="Rev")
        res = api.record_results(
            ctx["order"]["id"], {"readings": tightness_readings(0.05)},
            make_reviewer_headers(reviewer["id"]))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_owner_cannot_certify_forbidden(self, api):
        """PRD §2.1: "When the caller's role is not among the roles an endpoint
        authorizes, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /service-orders/{id}/certify is authorized to
        `ComplianceReviewer`.

        Design: Corner/rbac/owner_cannot_certify_forbidden
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_started_tightness_order()
        record_results(ctx["order"]["id"], ctx["tester"]["id"],
                       tightness_readings(0.05))
        res = api.certify_service_order(ctx["order"]["id"], OWNER)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
