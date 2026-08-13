"""Kiln charge scheduling, temporal rules, overlap buffer, and the rework cycle."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId,
    create_completed_run, list_run_packages, create_kiln_charge,
    start_charge, complete_charge, run_kiln_cycle, get_package,
    set_clock, stamp_package, create_active_contract, place_order,
    create_kiln_charge_payload, kiln_reading_payload, create_sales_order_payload,
    make_kiln_operator_headers, make_grader_headers, make_sales_rep_headers,
)


def _two_green_packages():
    """One completed run producing two GREEN DF packages, green_mbf 20.0 each."""
    specs = [{"green_mbf": 20.0}, {"green_mbf": 20.0}]
    run, packages = create_completed_run(specs)
    return run, packages


def _one_green_package():
    specs = [{"green_mbf": 20.0}]
    run, packages = create_completed_run(specs)
    return run, packages[0]


def _one_dry_package():
    """One DF package dried through a completed charge (measured 18.8)."""
    run, packages = create_completed_run([{"green_mbf": 20.0}])
    pkg_id = packages[0]["id"]
    charge = create_kiln_charge([pkg_id])
    run_kiln_cycle(charge["id"], [
        {"package_id": pkg_id, "exit_moisture_pct": 14.0, "measured_dry_mbf": 18.8},
    ])
    return get_package(pkg_id)


class TestScheduleTemporalRules:
    def test_kiln_end_not_after_start_rejected(self, api):
        """PRD Section 3.4: "The `scheduled_start` must not lie in the past relative to the current logical time — a start before now is rejected with `ERR_SCHEDULE_IN_PAST` (HTTP 422) — and the `scheduled_end` must be strictly after `scheduled_start`, an end at or before the start drawing `ERR_END_BEFORE_START` (HTTP 422)."

        Design: Corner/validations/kiln_end_not_after_start_rejected
        """
        _run, pkg = _one_green_package()
        res = api.create_kiln_charge(
            create_kiln_charge_payload(
                [pkg["id"]],
                scheduled_start="2026-08-03T00:00:00Z",
                scheduled_end="2026-08-03T00:00:00Z",
            ),
            make_kiln_operator_headers(),
        )
        validate_error(res, ApiErrorId.ERR_END_BEFORE_START)
        assert get_package(pkg["id"])["status"] == "GREEN", (
            "a rejected charge leaves its packages untouched"
        )

    def test_start_charge_before_window_returns_schedule_in_past(self, api):
        """PRD Section 3.4: "Starting a charge requires that the charge is `SCHEDULED` and that the current logical time has reached `scheduled_start`; starting early is rejected with `ERR_SCHEDULE_IN_PAST`."

        Design: Corner/validations/start_charge_before_window_returns_schedule_in_past
        """
        _run, pkg = _one_green_package()
        charge = create_kiln_charge(
            [pkg["id"]],
            scheduled_start="2026-08-03T00:00:00Z",
            scheduled_end="2026-08-06T00:00:00Z",
        )
        set_clock("2026-08-02T00:00:00Z")
        res = api.start_kiln_charge(charge["id"], make_kiln_operator_headers())
        validate_error(res, ApiErrorId.ERR_SCHEDULE_IN_PAST)
        after = validate_success(api.get_kiln_charge(charge["id"], make_kiln_operator_headers()), 200)
        assert after["status"] == "SCHEDULED", f"early start rejected, got {after['status']}"

    def test_start_charge_twice_returns_invalid_state(self, api):
        """PRD Section 3.4: "Starting a charge requires that the charge is `SCHEDULED` and that the current logical time has reached `scheduled_start`; starting early is rejected with `ERR_SCHEDULE_IN_PAST`."
        PRD Section 2.7: "Only after the request is well-formed does the server evaluate entity state preconditions for the invoked transition (`ERR_INVALID_STATE`, or `ERR_CONTRACT_NOT_ACTIVE` where a contract order is involved), then business-temporal rules (schedule windows), then business constraints (chamber and line occupancy, deck capacity, run log-set integrity), then referential linkage (species and grade agreement), and finally fiscal rules (contract volume, price-list availability, allocation pool sufficiency, byproduct on-hand)."

        Design: Corner/state_machines/start_charge_twice_returns_invalid_state
        """
        _run, pkg = _one_green_package()
        charge = create_kiln_charge([pkg["id"]])
        start_charge(charge["id"], scheduled_start="2026-08-02T00:00:00Z")
        res = api.start_kiln_charge(charge["id"], make_kiln_operator_headers())
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_abort_completed_charge_rejected(self, api):
        """PRD Section 3.4: "Aborting is the escape hatch, available from either `SCHEDULED` or `IN_PROGRESS`."

        Design: Corner/state_machines/abort_completed_charge_terminal_lockdown
        """
        run, packages = create_completed_run([{"green_mbf": 20.0}])
        pkg_id = packages[0]["id"]
        charge = create_kiln_charge([pkg_id])
        run_kiln_cycle(charge["id"], [
            {"package_id": pkg_id, "exit_moisture_pct": 14.0, "measured_dry_mbf": 18.8},
        ])
        res = api.abort_kiln_charge(charge["id"], make_kiln_operator_headers())
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_package(pkg_id)["status"] == "DRY", (
            "COMPLETED is terminal; the dried package must not roll back"
        )


class TestSpeciesLinkage:
    def test_product_mismatch_on_charge_and_contract_order(self, api):
        """PRD Section 3.4: "Every id in `package_ids` must reference a package currently `GREEN` whose `species` equals the charge's `species`; a package of the wrong species, or a contract-style mismatch of the same family on the order side, is rejected with `ERR_PRODUCT_MISMATCH` (HTTP 422), while a package not in `GREEN` state fails as `ERR_INVALID_STATE`."
        PRD Section 3.7: "The order's `species` and `grade` must equal the contract's, otherwise `ERR_PRODUCT_MISMATCH`."

        Design: Corner/validations/product_mismatch_on_charge_and_contract_order
        """
        run, packages = create_completed_run(
            [{"species": "CEDAR", "green_mbf": 20.0}],
            load_overrides={"species": "CEDAR", "log_grade": "SAWLOG_2",
                            "supplier_name": "Cedar Rim LLC"},
        )
        cedar_pkg = packages[0]
        charge_res = api.create_kiln_charge(
            create_kiln_charge_payload([cedar_pkg["id"]], species="DOUGLAS_FIR"),
            make_kiln_operator_headers(),
        )
        validate_error(charge_res, ApiErrorId.ERR_PRODUCT_MISMATCH)

        contract = create_active_contract()
        order_res = api.create_sales_order(
            create_sales_order_payload(
                customer_name="Acme Builders", contract_id=contract["id"],
                species="CEDAR", volume_mbf=5,
            ),
            make_sales_rep_headers(),
        )
        validate_error(order_res, ApiErrorId.ERR_PRODUCT_MISMATCH)


class TestPackageStateGate:
    def test_charge_rejects_package_already_in_kiln(self, api):
        """PRD Section 3.4: "Every id in `package_ids` must reference a package currently `GREEN` whose `species` equals the charge's `species`; a package of the wrong species, or a contract-style mismatch of the same family on the order side, is rejected with `ERR_PRODUCT_MISMATCH` (HTTP 422), while a package not in `GREEN` state fails as `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/charge_creation_gated_on_package_green
        """
        _run, pkg = _one_green_package()
        charge_a = create_kiln_charge([pkg["id"]], chamber="KILN_1")
        # Same window on a different chamber: occupancy cannot interfere, so the
        # only failing rule is the package's state (IN_KILN, not GREEN).
        res = api.create_kiln_charge(
            create_kiln_charge_payload([pkg["id"]], chamber="KILN_2"),
            make_kiln_operator_headers(),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_second_charge_leaves_no_side_effects(self, api):
        """PRD Section 3.4: "A successfully created charge enters at `SCHEDULED`, returns 201, and immediately moves every charged package from `GREEN` to `IN_KILN`, stamping each package's `kiln_charge_id` with the new charge's id and incrementing each package's `version`."

        Design: Difficulty/cross_entity_state_dependency/charge_creation_gated_on_package_green
        """
        _run, pkg = _one_green_package()
        charge_a = create_kiln_charge([pkg["id"]], chamber="KILN_1")
        res = api.create_kiln_charge(
            create_kiln_charge_payload([pkg["id"]], chamber="KILN_2"),
            make_kiln_operator_headers(),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after_charge = validate_success(api.get_kiln_charge(charge_a["id"], make_kiln_operator_headers()), 200)
        assert after_charge["status"] == "SCHEDULED"
        after_pkg = get_package(pkg["id"])
        assert after_pkg["status"] == "IN_KILN"
        assert after_pkg["kiln_charge_id"] == charge_a["id"], (
            "the package stays attached to charge A only"
        )


class TestOverlapBuffer:
    def test_start_two_hours_after_end_violates_turnaround(self, api):
        """PRD Section 3.4: "Exactly 4 hours of adjacency is allowed in either direction; anything less violates the buffer and is rejected with `ERR_KILN_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/kiln_charge_overlap_turnaround_buffer
        """
        _run, packages = _two_green_packages()
        p1, p2 = packages[0]["id"], packages[1]["id"]
        charge_a = create_kiln_charge(
            [p1], chamber="KILN_1",
            scheduled_start="2026-08-02T00:00:00Z", scheduled_end="2026-08-04T00:00:00Z",
        )
        assert charge_a["status"] == "SCHEDULED"
        res = api.create_kiln_charge(
            create_kiln_charge_payload(
                [p2], chamber="KILN_1",
                scheduled_start="2026-08-04T02:00:00Z", scheduled_end="2026-08-06T00:00:00Z",
            ),
            make_kiln_operator_headers(),
        )
        validate_error(res, ApiErrorId.ERR_KILN_OVERLAP)
        assert get_package(p2)["status"] == "GREEN", "rejected charge leaves no side effects"

    def test_start_exactly_four_hours_after_end_allowed(self, api):
        """PRD Section 3.4: "A chamber turns around between charges: a new charge on a chamber may be scheduled only if, against every existing `SCHEDULED` or `IN_PROGRESS` charge on that same chamber, either the new charge's start is at least 4 hours after the existing charge's end, or the new charge's end is at least 4 hours before the existing charge's start."

        Design: Difficulty/resource_temporal_overlap/kiln_charge_overlap_turnaround_buffer
        """
        _run, packages = _two_green_packages()
        p1, p2 = packages[0]["id"], packages[1]["id"]
        create_kiln_charge(
            [p1], chamber="KILN_1",
            scheduled_start="2026-08-02T00:00:00Z", scheduled_end="2026-08-04T00:00:00Z",
        )
        res = api.create_kiln_charge(
            create_kiln_charge_payload(
                [p2], chamber="KILN_1",
                scheduled_start="2026-08-04T04:00:00Z", scheduled_end="2026-08-06T04:00:00Z",
            ),
            make_kiln_operator_headers(),
        )
        charge_c = validate_success(res, 201)
        assert charge_c["status"] == "SCHEDULED"
        assert get_package(p2)["status"] == "IN_KILN"


class TestTemporalBeatsConstraint:
    def test_past_start_and_overlap_reports_schedule_in_past(self, api):
        """PRD Section 2.7: "Only after the request is well-formed does the server evaluate entity state preconditions for the invoked transition (`ERR_INVALID_STATE`, or `ERR_CONTRACT_NOT_ACTIVE` where a contract order is involved), then business-temporal rules (schedule windows), then business constraints (chamber and line occupancy, deck capacity, run log-set integrity), then referential linkage (species and grade agreement), and finally fiscal rules (contract volume, price-list availability, allocation pool sufficiency, byproduct on-hand)."
        PRD Section 3.4: "Temporal rules come first."

        Design: Difficulty/priority_pair_validation_conflict/kiln_create_temporal_beats_constraint
        """
        _run, packages = _two_green_packages()
        p1, p2 = packages[0]["id"], packages[1]["id"]
        create_kiln_charge(
            [p1], chamber="KILN_1",
            scheduled_start="2026-08-09T00:00:00Z", scheduled_end="2026-08-12T00:00:00Z",
        )
        set_clock("2026-08-10T00:00:00Z")
        # [08-08, 08-10) both starts in the past AND overlaps the existing charge.
        res = api.create_kiln_charge(
            create_kiln_charge_payload(
                [p2], chamber="KILN_1",
                scheduled_start="2026-08-08T00:00:00Z", scheduled_end="2026-08-10T00:00:00Z",
            ),
            make_kiln_operator_headers(),
        )
        validate_error(res, ApiErrorId.ERR_SCHEDULE_IN_PAST)

    def test_temporal_rejection_leaves_no_side_effects(self, api):
        """PRD Section 3.4: "Temporal rules come first. The `scheduled_start` must not lie in the past relative to the current logical time — a start before now is rejected with `ERR_SCHEDULE_IN_PAST` (HTTP 422) — and the `scheduled_end` must be strictly after `scheduled_start`, an end at or before the start drawing `ERR_END_BEFORE_START` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/kiln_create_temporal_beats_constraint
        """
        _run, packages = _two_green_packages()
        p1, p2 = packages[0]["id"], packages[1]["id"]
        charge_a = create_kiln_charge(
            [p1], chamber="KILN_1",
            scheduled_start="2026-08-09T00:00:00Z", scheduled_end="2026-08-12T00:00:00Z",
        )
        set_clock("2026-08-10T00:00:00Z")
        res = api.create_kiln_charge(
            create_kiln_charge_payload(
                [p2], chamber="KILN_1",
                scheduled_start="2026-08-08T00:00:00Z", scheduled_end="2026-08-10T00:00:00Z",
            ),
            make_kiln_operator_headers(),
        )
        validate_error(res, ApiErrorId.ERR_SCHEDULE_IN_PAST)
        assert get_package(p2)["status"] == "GREEN", "no partial charge side effects"
        after_a = validate_success(api.get_kiln_charge(charge_a["id"], make_kiln_operator_headers()), 200)
        assert after_a["status"] == "SCHEDULED"


class TestMoistureGate:
    def _complete_with_moistures(self, api, m1, m2):
        """Two packages, one charge; complete with the given exit moistures."""
        _run, packages = _two_green_packages()
        p1, p2 = packages[0]["id"], packages[1]["id"]
        charge = create_kiln_charge([p1, p2], chamber="KILN_1")
        completed = run_kiln_cycle(charge["id"], [
            {"package_id": p1, "exit_moisture_pct": m1, "measured_dry_mbf": 18.8},
            {"package_id": p2, "exit_moisture_pct": m2, "measured_dry_mbf": 18.8},
        ])
        return completed, p1, p2

    def test_moisture_exactly_at_tolerance_passes(self, api):
        """PRD Section 3.4: "The moisture gate is then applied per package, with a tolerance of 2.0 percentage points: a package whose `exit_moisture_pct` is at most `target_moisture_pct` plus 2.0 passes, while one above that threshold fails — the comparison is at 1 decimal place with an inclusive boundary, so a reading exactly 2.0 points over target still passes."
        PRD Section 3.4: "Passing packages flip from `IN_KILN` to `DRY`: their `actual_dry_mbf` is set from the reading, their `dry_mbf` reconciles from the estimate to the measured figure as §3.5 describes, their `kiln_charge_id` is cleared, and their `version` increments."

        Design: Difficulty/boundary_precision_check/moisture_gate_exactly_at_tolerance
        """
        completed, p1, _p2 = self._complete_with_moistures(api, 17.0, 17.1)
        assert completed["status"] == "COMPLETED"
        pkg1 = get_package(p1)
        assert pkg1["status"] == "DRY", f"17.0 <= 15.0 + 2.0 passes, got {pkg1['status']}"
        assert pkg1["dry_mbf"] == pytest.approx(18.8, abs=1e-6)
        assert pkg1["actual_dry_mbf"] == pytest.approx(18.8, abs=1e-6)
        assert pkg1["kiln_charge_id"] is None

    def test_moisture_one_tenth_over_tolerance_fails(self, api):
        """PRD Section 3.4: "Failing packages flip back from `IN_KILN` to `GREEN` for rework: `kiln_charge_id` is cleared, `actual_dry_mbf` is left null, and `version` increments."

        Design: Difficulty/boundary_precision_check/moisture_gate_exactly_at_tolerance
        """
        completed, _p1, p2 = self._complete_with_moistures(api, 17.0, 17.1)
        assert completed["status"] == "COMPLETED"
        pkg2 = get_package(p2)
        assert pkg2["status"] == "GREEN", f"17.1 > 17.0 fails to rework, got {pkg2['status']}"
        assert pkg2["kiln_charge_id"] is None
        assert pkg2.get("actual_dry_mbf") is None, "failed packages keep no measured tally"


class TestReworkCycle:
    def test_moisture_failure_returns_package_to_green(self, api):
        """PRD Section 3.4: "Failing packages flip back from `IN_KILN` to `GREEN` for rework: `kiln_charge_id` is cleared, `actual_dry_mbf` is left null, and `version` increments."
        PRD Section 3.4: "The rework cycle `GREEN` → `IN_KILN` → `GREEN` — whether from a moisture failure or an abort — is unbounded: a failed package may simply be charged again under a new charge."

        Design: Difficulty/non_linear_state_machine/kiln_rework_cycle_green_to_dry
        """
        _run, pkg = _one_green_package()
        ch1 = create_kiln_charge([pkg["id"]], chamber="KILN_1")
        completed = run_kiln_cycle(ch1["id"], [
            {"package_id": pkg["id"], "exit_moisture_pct": 19.5, "measured_dry_mbf": 19.0},
        ])
        assert completed["status"] == "COMPLETED", "the charge completes; packages route individually"
        after = get_package(pkg["id"])
        assert after["status"] == "GREEN", f"19.5 > 15.0 + 2.0 -> rework, got {after['status']}"
        assert after.get("actual_dry_mbf") is None
        assert after["kiln_charge_id"] is None

    def test_second_charge_passes_and_sets_actual(self, api):
        """PRD Section 3.4: "The rework cycle `GREEN` → `IN_KILN` → `GREEN` — whether from a moisture failure or an abort — is unbounded: a failed package may simply be charged again under a new charge."
        PRD Section 3.4: "Passing packages flip from `IN_KILN` to `DRY`: their `actual_dry_mbf` is set from the reading, their `dry_mbf` reconciles from the estimate to the measured figure as §3.5 describes, their `kiln_charge_id` is cleared, and their `version` increments."

        Design: Difficulty/non_linear_state_machine/kiln_rework_cycle_green_to_dry
        """
        _run, pkg = _one_green_package()
        ch1 = create_kiln_charge([pkg["id"]], chamber="KILN_1")
        run_kiln_cycle(ch1["id"], [
            {"package_id": pkg["id"], "exit_moisture_pct": 19.5, "measured_dry_mbf": 19.0},
        ])
        ch2 = create_kiln_charge(
            [pkg["id"]], chamber="KILN_2",
            scheduled_start="2026-08-06T00:00:00Z", scheduled_end="2026-08-09T00:00:00Z",
        )
        run_kiln_cycle(ch2["id"], [
            {"package_id": pkg["id"], "exit_moisture_pct": 14.0, "measured_dry_mbf": 18.4},
        ], scheduled_start="2026-08-06T00:00:00Z", scheduled_end="2026-08-09T00:00:00Z")
        fin = get_package(pkg["id"])
        assert fin["status"] == "DRY", f"second lap passes (14.0 <= 17.0), got {fin['status']}"
        assert fin["kiln_charge_id"] is None
        assert fin["dry_mbf"] == pytest.approx(18.4, abs=1e-6)


class TestKilnRbac:
    def test_kiln_operator_cannot_stamp_returns_forbidden(self, api):
        """PRD Section 2.1: "Once authenticated, the role is checked against the endpoint's authorized role list; a role not on that list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD Section 4: "POST /api/lumber-packages/{id}/grade-inspections ... Grader"

        Design: Corner/rbac/kiln_operator_cannot_stamp_returns_forbidden
        """
        pkg = _one_dry_package()
        res = api.create_grade_inspection(
            pkg["id"], {"inspector_grade": "NO_2", "action": "STAMP"}, make_kiln_operator_headers()
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        assert get_package(pkg["id"])["status"] == "DRY"
