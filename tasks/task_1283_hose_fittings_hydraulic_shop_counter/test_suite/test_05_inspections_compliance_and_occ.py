"""Inspections, due dates, compliance scoring, and optimistic concurrency
(PRD §2.5, §2.9, §2.10, §3.1, §3.7)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_instant_equal,
    complete_inspection,
    create_customer,
    create_equipment_asset,
    get_equipment_asset,
    schedule_inspection,
    set_clock,
    start_inspection,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStrictVsProjectedCompliance:
    def _setup_fleet(self):
        cust = create_customer(name="FleetCo", program_enrolled=True,
                               program_discount_pct=0.10,
                               inspection_interval_days=30)
        a1 = create_equipment_asset(cust["id"], asset_tag="EX-01",
                                    machine_type="excavator",
                                    installed_at="2026-07-15T00:00:00Z")
        a2 = create_equipment_asset(cust["id"], asset_tag="EX-02",
                                    machine_type="excavator",
                                    installed_at="2026-06-01T00:00:00Z")
        schedule_inspection(a2["id"], a2["version"],
                            "2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z",
                            inspector_name="J. Ruiz")
        return cust, a1, a2

    def test_strict_score_counts_only_current_compliant_postures(self, api):
        """PRD §3.7: "A customer's `compliance_score_strict` considers only assets in `ACTIVE` status and reports the percentage of them whose `compliance_posture` is `COMPLIANT` or `DUE_SOON`, expressed to two decimal places with half-up rounding — and reading 100.00 when the customer has no active assets at all."
        PRD §3.7: "The asset's `compliance_posture` then derives as a chain: when the latest completed inspection is a failure with no later pass, the posture is `NON_COMPLIANT`; otherwise, when the logical clock has moved past the `next_due_date`, the posture is `OVERDUE`; otherwise, when the gap between `next_due_date` and the clock is no more than 30 days, the posture is `DUE_SOON`; and in every remaining case the posture is `COMPLIANT`."

        At the 2026-08-01 clock with a 30-day interval: A1 (installed 2026-07-15,
        due 2026-08-14) is DUE_SOON; A2 (installed 2026-06-01, due 2026-07-01) is
        OVERDUE; strict = 1/2 = 50.00.

        Design: Difficulty/dual_variant_calc/compliance_score_strict_vs_projected
        """
        cust, a1, a2 = self._setup_fleet()
        a1_data = get_equipment_asset(a1["id"])
        a2_data = get_equipment_asset(a2["id"])
        assert a1_data["compliance_posture"] == "DUE_SOON"
        assert a2_data["compliance_posture"] == "OVERDUE"

        cust_data = validate_success(
            api.get_customer(cust["id"], TEST_USERS["shop_manager_headers"]), 200)
        assert cust_data["compliance_score_strict"] == pytest.approx(50.00, abs=0.005)

    def test_projected_score_counts_future_scheduled_inspection(self, api):
        """PRD §3.7: "The lenient sibling, `compliance_score_projected`, additionally counts `OVERDUE` and `NON_COMPLIANT` assets as compliant when the asset holds at least one `SCHEDULED` inspection whose `scheduled_window_end` is at or after the current logical clock, so the projected score never falls below the strict one on identical data."

        A2 is OVERDUE but holds a SCHEDULED inspection ending 2026-08-06 (at/after
        the 2026-08-01 clock), so projected = 100.00 while strict = 50.00.

        Design: Difficulty/dual_variant_calc/compliance_score_strict_vs_projected
        """
        cust, a1, a2 = self._setup_fleet()
        cust_data = validate_success(
            api.get_customer(cust["id"], TEST_USERS["shop_manager_headers"]), 200)
        assert cust_data["compliance_score_projected"] == pytest.approx(100.00, abs=0.005)
        assert (cust_data["compliance_score_projected"]
                > cust_data["compliance_score_strict"])


class TestInspectionPassFailBranching:
    def _setup_two_in_progress(self):
        cust = create_customer(name="BranchCo", program_enrolled=True,
                               program_discount_pct=0.10,
                               inspection_interval_days=30)
        a1 = create_equipment_asset(cust["id"], asset_tag="LD-01",
                                    machine_type="loader",
                                    installed_at="2026-07-20T00:00:00Z")
        a2 = create_equipment_asset(cust["id"], asset_tag="LD-02",
                                    machine_type="loader",
                                    installed_at="2026-07-20T00:00:00Z")
        i1 = schedule_inspection(a1["id"], a1["version"],
                                 "2026-07-28T00:00:00Z", "2026-07-29T00:00:00Z")
        i2 = schedule_inspection(a2["id"], a2["version"],
                                 "2026-07-28T00:00:00Z", "2026-07-29T00:00:00Z")
        start_inspection(i1["id"])
        start_inspection(i2["id"])
        return cust, a1, a2, i1, i2

    def test_passed_inspection_advances_last_passed_and_next_due(self, api):
        """PRD §3.7: "A `PASSED` inspection records the completion instant as the asset's `last_passed_inspection_at`, recomputes `next_due_date` with the just-recorded pass as its new base, recomputes the asset's `compliance_posture`, and recomputes the customer's scores and `program_status`."
        PRD §2.5: "Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its own."
        PRD §3.7: "An asset's `next_due_date` is its base date plus the customer's `inspection_interval_days`, where the base is `last_passed_inspection_at` when a pass exists and `installed_at` otherwise; when neither exists, the date is null."

        PASSED at the 2026-08-01 clock: last_passed 2026-08-01, next_due
        2026-08-01 + 30d = 2026-08-31.

        Design: Difficulty/non_linear_state_machine/inspection_pass_fail_branching
        """
        cust, a1, a2, i1, i2 = self._setup_two_in_progress()
        complete_inspection(i1["id"], "PASSED")

        a1_after = get_equipment_asset(a1["id"])
        assert_instant_equal(a1_after["last_passed_inspection_at"],
                             "2026-08-01T00:00:00Z")
        assert_instant_equal(a1_after["next_due_date"], "2026-08-31T00:00:00Z")

    def test_failed_inspection_drives_non_compliant_and_probation(self, api):
        """PRD §3.7: "A `FAILED` inspection leaves `last_passed_inspection_at` untouched; the asset's posture becomes `NON_COMPLIANT` and stays there until a later inspection passes, and the customer's scores recompute — which can flip `program_status` to `PROBATION` when the strict score falls below the bar."
        PRD §3.7: "Finally, `program_status` derives from enrollment and the strict score: `NONE` when the customer is not enrolled, `ACTIVE` when enrolled with a strict score of at least 70, and `PROBATION` otherwise."

        A1 passes, A2 fails: strict = 1/2 = 50.00 < 70, so the enrolled customer
        flips to PROBATION.

        Design: Difficulty/non_linear_state_machine/inspection_pass_fail_branching
        """
        cust, a1, a2, i1, i2 = self._setup_two_in_progress()
        complete_inspection(i1["id"], "PASSED")
        complete_inspection(i2["id"], "FAILED")

        a2_after = get_equipment_asset(a2["id"])
        assert a2_after["compliance_posture"] == "NON_COMPLIANT"
        assert a2_after["last_passed_inspection_at"] is None

        cust_after = validate_success(
            api.get_customer(cust["id"], TEST_USERS["shop_manager_headers"]), 200)
        assert cust_after["compliance_score_strict"] == pytest.approx(50.00, abs=0.005)
        assert cust_after["program_status"] == "PROBATION"


class TestDueDateBoundary:
    def _setup_in_progress_inspection(self):
        cust = create_customer(name="DueDateCo", inspection_interval_days=90)
        asset = create_equipment_asset(cust["id"], asset_tag="GR-01",
                                       machine_type="grader",
                                       installed_at="2026-05-03T00:00:00Z")
        insp = schedule_inspection(asset["id"], asset["version"],
                                   "2026-07-30T00:00:00Z", "2026-08-02T00:00:00Z")
        start_inspection(insp["id"])
        return cust, asset, insp

    def test_completion_exactly_on_due_date_is_on_time(self, api):
        """PRD §3.7: "Either way, the system stamps `performed_at` from the logical clock and computes `was_overdue`: true only when the asset had a computable `next_due_date` and the completion happened strictly later than that date — a completion exactly on the due date counts as on time, and the flag starts from its default of false whenever no due date exists."

        installed 2026-05-03 + 90d lands the due date exactly on the 2026-08-01
        clock; performed == due is NOT overdue. The pass re-bases next_due to
        2026-08-01 + 90d = 2026-10-30 and the posture is COMPLIANT.

        Design: Difficulty/boundary_precision_check/inspection_on_exact_due_date_not_overdue
        """
        cust, asset, insp = self._setup_in_progress_inspection()
        completed = complete_inspection(insp["id"], "PASSED")

        assert_instant_equal(completed["performed_at"], "2026-08-01T00:00:00Z")
        assert completed["was_overdue"] is False

        asset_after = get_equipment_asset(asset["id"])
        assert_instant_equal(asset_after["next_due_date"], "2026-10-30T00:00:00Z")
        assert asset_after["compliance_posture"] == "COMPLIANT"

    def test_completion_strictly_after_due_date_is_overdue(self, api):
        """PRD §3.7: "Either way, the system stamps `performed_at` from the logical clock and computes `was_overdue`: true only when the asset had a computable `next_due_date` and the completion happened strictly later than that date — a completion exactly on the due date counts as on time, and the flag starts from its default of false whenever no due date exists."
        PRD §2.5: "A manager-only test-driving capability advances the clock: the caller supplies a `to_iso8601` instant, and the response reports the resulting `current_utc`."

        Moving the logical clock to 2026-08-02 makes the completion strictly later
        than the 2026-08-01 due date, so was_overdue is true.

        Design: Difficulty/boundary_precision_check/inspection_on_exact_due_date_not_overdue
        """
        cust, asset, insp = self._setup_in_progress_inspection()
        set_clock("2026-08-02T00:00:00Z")

        completed = complete_inspection(insp["id"], "PASSED")
        assert_instant_equal(completed["performed_at"], "2026-08-02T00:00:00Z")
        assert completed["was_overdue"] is True


class TestInspectionSupersede:
    def test_new_inspection_supersedes_prior_scheduled(self, api):
        """PRD §3.7: "A successful schedule creates the inspection in `SCHEDULED` status, moves every prior `SCHEDULED` inspection of the same asset to `SUPERSEDED` atomically with the create, and increments the asset's `version` by one."

        I1 (window 2026-08-10..11) is superseded by I2 (window 2026-08-20..21);
        the asset version advances by exactly one per inspection create.

        Design: Corner/state_machines/new_inspection_supersedes_scheduled
        """
        cust = create_customer(name="SupersedeCo")
        asset = create_equipment_asset(cust["id"], asset_tag="SS-01",
                                       machine_type="skid steer",
                                       installed_at="2026-07-01T00:00:00Z")
        v0 = asset["version"]
        i1 = schedule_inspection(asset["id"], v0,
                                 "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z")
        assert i1["status"] == "SCHEDULED"

        asset_v1 = get_equipment_asset(asset["id"])
        assert asset_v1["version"] == v0 + 1

        i2 = schedule_inspection(asset["id"], asset_v1["version"],
                                 "2026-08-20T00:00:00Z", "2026-08-21T00:00:00Z")
        assert i2["status"] == "SCHEDULED"

        res = api.list_inspections(asset["id"], TEST_USERS["shop_manager_headers"])
        data, _meta = validate_paginated(res)
        by_id = {row["id"]: row for row in data}
        assert by_id[i1["id"]]["status"] == "SUPERSEDED"
        assert by_id[i2["id"]]["status"] == "SCHEDULED"

        asset_v2 = get_equipment_asset(asset["id"])
        assert asset_v2["version"] == v0 + 2


class TestOptimisticConcurrency:
    def test_stale_asset_version_rejected(self, api):
        """PRD §2.10: "The request must carry `expected_equipment_asset_version`, holding the asset `version` the client last observed. If that value does not match the asset's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.10: "Creating an inspection legitimately rewrites the asset's inspection calendar — every still-scheduled prior inspection of the same asset is superseded atomically with the create — and the act of doing so increments the asset's `version` by one."

        After the first create bumps the asset version, a second create carrying
        the previously observed version is stale; I1 stays SCHEDULED (no supersede).

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected
        """
        cust = create_customer(name="OccCo")
        asset = create_equipment_asset(cust["id"], asset_tag="OC-01",
                                       machine_type="crane",
                                       installed_at="2026-07-01T00:00:00Z")
        v1 = asset["version"]
        i1 = schedule_inspection(asset["id"], v1,
                                 "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z")

        res = api.create_inspection(asset["id"], {
            "expected_equipment_asset_version": v1,
            "scheduled_window_start": "2026-08-12T00:00:00Z",
            "scheduled_window_end": "2026-08-13T00:00:00Z",
        }, TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        res = api.list_inspections(asset["id"], TEST_USERS["shop_manager_headers"])
        data, _meta = validate_paginated(res)
        by_id = {row["id"]: row for row in data}
        assert by_id[i1["id"]]["status"] == "SCHEDULED"
        assert len(data) == 1


class TestAssetActiveGating:
    def _setup_decommissioned_with_scheduled(self, api):
        cust = create_customer(name="DecomCo")
        asset = create_equipment_asset(cust["id"], asset_tag="DR-01",
                                       machine_type="drill",
                                       installed_at="2026-07-01T00:00:00Z")
        insp = schedule_inspection(asset["id"], asset["version"],
                                   "2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z")
        decom = api.decommission_equipment_asset(
            asset["id"], TEST_USERS["shop_manager_headers"])
        validate_success(decom, 200)
        return cust, asset, insp

    def test_start_blocked_by_decommissioned_asset(self, api):
        """PRD §3.7: "A `FieldTechnician` begins a scheduled inspection, moving it from `SCHEDULED` to `IN_PROGRESS`; the asset must be `ACTIVE` at that moment or the start is rejected with `ERR_ASSET_NOT_ACTIVE`."

        The asset was decommissioned after scheduling; the start is rejected and
        the inspection remains SCHEDULED.

        Design: Difficulty/cross_entity_state_dependency/inspection_start_blocked_by_decommissioned_asset
        """
        cust, asset, insp = self._setup_decommissioned_with_scheduled(api)
        res = api.start_inspection(insp["id"],
                                   TEST_USERS["field_technician_headers"])
        validate_error(res, ApiErrorId.ERR_ASSET_NOT_ACTIVE, expected_status=422)

        res = api.list_inspections(asset["id"], TEST_USERS["shop_manager_headers"])
        data, _meta = validate_paginated(res)
        assert data[0]["id"] == insp["id"]
        assert data[0]["status"] == "SCHEDULED"

    def test_schedule_blocked_by_decommissioned_asset(self, api):
        """PRD §3.1: "A decommissioned asset drops out of the denominator of every compliance score and keeps the last compliance posture it computed, but it is barred from further use everywhere: scheduling a new inspection against it, starting an inspection on it, drafting an assembly order that names it, and completing an order onto it are all rejected with `ERR_ASSET_NOT_ACTIVE`."

        Scheduling a fresh inspection (with the current asset version and a valid
        window) against the decommissioned asset is rejected.

        Design: Difficulty/cross_entity_state_dependency/inspection_start_blocked_by_decommissioned_asset
        """
        cust, asset, insp = self._setup_decommissioned_with_scheduled(api)
        current = get_equipment_asset(asset["id"])

        res = api.create_inspection(asset["id"], {
            "expected_equipment_asset_version": current["version"],
            "scheduled_window_start": "2026-08-05T00:00:00Z",
            "scheduled_window_end": "2026-08-06T00:00:00Z",
        }, TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_ASSET_NOT_ACTIVE, expected_status=422)


class TestInspectionWindowConflict:
    def _setup_in_progress(self):
        cust = create_customer(name="TouchCo")
        asset = create_equipment_asset(cust["id"], asset_tag="RL-01",
                                       machine_type="roller",
                                       installed_at="2026-06-01T00:00:00Z")
        i1 = schedule_inspection(asset["id"], asset["version"],
                                 "2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z")
        start_inspection(i1["id"])
        current = get_equipment_asset(asset["id"])
        return cust, asset, i1, current["version"]

    def test_touching_window_conflicts_under_closed_semantics(self, api):
        """PRD §2.9: "An inspection window on an equipment asset is a **closed** interval, and its conflict check runs only against inspections currently in progress on that same asset. Here touching endpoints do count as overlap: a new window that begins exactly when an in-progress inspection's window ends is still a conflict."
        PRD §3.7: "then the closed-interval conflict check of §2.9 against inspections currently `IN_PROGRESS` on the same asset, with touching endpoints counting as overlap and conflicts rejected as `ERR_INSPECTION_WINDOW_CONFLICT`"

        A new window starting 2026-08-12 exactly when the IN_PROGRESS window ends
        counts as overlap -> ERR_INSPECTION_WINDOW_CONFLICT (409).

        Design: Difficulty/resource_temporal_overlap/inspection_closed_interval_touching_conflicts
        """
        cust, asset, i1, version = self._setup_in_progress()
        res = api.create_inspection(asset["id"], {
            "expected_equipment_asset_version": version,
            "scheduled_window_start": "2026-08-12T00:00:00Z",
            "scheduled_window_end": "2026-08-14T00:00:00Z",
        }, TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_INSPECTION_WINDOW_CONFLICT,
                       expected_status=409)

    def test_disjoint_window_is_allowed(self, api):
        """PRD §2.9: "An inspection window on an equipment asset is a **closed** interval, and its conflict check runs only against inspections currently in progress on that same asset. Here touching endpoints do count as overlap: a new window that begins exactly when an in-progress inspection's window ends is still a conflict."

        A window starting strictly after the in-progress window's end
        (2026-08-13 > 2026-08-12) shares no instant with it, so the create
        succeeds in SCHEDULED status.

        Design: Difficulty/resource_temporal_overlap/inspection_closed_interval_touching_conflicts
        """
        cust, asset, i1, version = self._setup_in_progress()
        res = api.create_inspection(asset["id"], {
            "expected_equipment_asset_version": version,
            "scheduled_window_start": "2026-08-13T00:00:00Z",
            "scheduled_window_end": "2026-08-14T00:00:00Z",
        }, TEST_USERS["counter_sales_headers"])
        created = validate_success(res, 201)
        assert created["status"] == "SCHEDULED"


class TestCustomerDefaults:
    def test_customer_program_defaults_when_not_enrolled(self, api):
        """PRD §3.1: "`credit_hold`, which defaults to false and, while true, blocks both order confirmation and dispatch booking; `program_enrolled`, which defaults to false and marks membership in the hose-management program; `program_discount_pct`, a fractional discount rate such as 0.10 that defaults to 0; and `inspection_interval_days`, the number of days between required hose inspections for this customer's assets, which defaults to 365 and must be at least 1. A freshly registered customer starts with both compliance scores at 100.00, and its `program_status` is derived immediately."
        PRD §3.7: "Finally, `program_status` derives from enrollment and the strict score: `NONE` when the customer is not enrolled, `ACTIVE` when enrolled with a strict score of at least 70, and `PROBATION` otherwise."

        A customer created with only a name: program_status NONE, both scores
        100.00, credit_hold false, inspection_interval_days 365.

        Design: Corner/entities/customer_program_defaults_when_not_enrolled
        """
        res = api.create_customer({"name": "PlainCo"},
                                  TEST_USERS["shop_manager_headers"])
        cust = validate_success(res, 201)
        assert cust["program_status"] == "NONE"
        assert cust["compliance_score_strict"] == pytest.approx(100.00, abs=0.005)
        assert cust["compliance_score_projected"] == pytest.approx(100.00, abs=0.005)
        assert cust["credit_hold"] is False
        assert cust["inspection_interval_days"] == 365


class TestNotFoundErrors:
    def test_asset_get_unknown_id_not_found(self, api):
        """PRD §2.11: "For a nested path, identifiers are validated left to right, and the first identifier that does not resolve produces the 404 specific to its resource kind: `ERR_CUSTOMER_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_REEL_NOT_FOUND`, `ERR_COUPLING_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, or `ERR_DISPATCH_NOT_FOUND`."

        GET /api/equipment-assets/{unknown uuid} -> ERR_ASSET_NOT_FOUND (404).

        Design: Corner/entities/asset_get_unknown_id_not_found
        """
        res = api.get_equipment_asset(NON_EXISTENT_UUID,
                                      TEST_USERS["shop_manager_headers"])
        validate_error(res, ApiErrorId.ERR_ASSET_NOT_FOUND, expected_status=404)

    def test_inspection_start_unknown_id_not_found(self, api):
        """PRD §2.11: "For a nested path, identifiers are validated left to right, and the first identifier that does not resolve produces the 404 specific to its resource kind: `ERR_CUSTOMER_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_REEL_NOT_FOUND`, `ERR_COUPLING_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, or `ERR_DISPATCH_NOT_FOUND`."

        POST /api/inspections/{unknown uuid}/start -> ERR_INSPECTION_NOT_FOUND (404).

        Design: Corner/errors/inspection_start_unknown_id_not_found
        """
        res = api.start_inspection(NON_EXISTENT_UUID,
                                   TEST_USERS["field_technician_headers"])
        validate_error(res, ApiErrorId.ERR_INSPECTION_NOT_FOUND,
                       expected_status=404)
