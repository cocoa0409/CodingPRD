"""Timesheet intervals, the labour rollup, the budget posture boundary and expenses."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    assert_time_entry, assert_expense, assert_project_posture_invariants,
    state_payload, create_time_entry_payload, create_expense_payload, create_phase_payload,
    make_staff_architect_headers,
    setup_project, setup_executed_project,
    activate_phase, create_time_entry, submit_time_entry, approve_time_entry,
    create_approved_time_entry, read_project, read_time_entry, PRINCIPAL,
)

# An architect whose internal cost is a round 10_000 cents/hour: an eight-hour day costs
# exactly 80_000 cents, which makes the budget boundary land on a whole number.
COSTLY_ARCHITECT = {"billing_rate_cents_per_hour": 20_000, "cost_rate_cents_per_hour": 10_000}


def _project_with_sd_phase_only(api, project_number, labor_budget_cents, arch_overrides=None):
    """Project + a bare SD phase, with no contract written yet."""
    bundle = setup_project(
        project_number=project_number,
        labor_budget_cents=labor_budget_cents,
        arch_overrides=arch_overrides,
    )
    sd = validate_success(
        api.create_phase(
            create_phase_payload(bundle["project_id"], "SD", 2500), bundle["pm_headers"]
        ),
        201,
    )
    bundle["phases"] = {"SD": sd}
    bundle["phase_ids"] = {"SD": sd["id"]}
    return bundle


class TestHalfOpenTimesheetInterval:

    def test_a_new_entry_starting_exactly_when_another_ends_is_accepted(self, api):
        """PRD §3.4: "Intervals that merely touch — a new entry starting at precisely the instant
        another ends — do **not** collide and are accepted."
        PRD §3.4: "`hours` is the elapsed time between the two instants expressed in seconds,
        divided by 3600, rounded half up to two decimal places; `cost_cents` is those `hours`
        multiplied by the staff member's `cost_rate_cents_per_hour`, rounded half up to whole
        cents; and `billable_cents` is those `hours` multiplied by the staff member's
        `billing_rate_cents_per_hour`, rounded half up — except on a non-billable entry, where
        `billable_cents` is 0 outright."

        Design: Difficulty/resource_temporal_overlap/staff_timesheet_half_open_interval_admits_adjacency_rejects_strict_overlap
        """
        bundle = setup_executed_project(project_number="OVL-001", name="Overlap Outpost")
        activate_phase(bundle, "SD")
        create_time_entry(
            bundle, "SD",
            start_utc="2026-05-04T09:00:00Z", end_utc="2026-05-04T17:00:00Z",
        )

        adjacent = validate_success(
            api.create_time_entry(
                create_time_entry_payload(
                    bundle["phase_ids"]["SD"], bundle["arch_id"],
                    start_utc="2026-05-04T17:00:00Z", end_utc="2026-05-04T19:00:00Z",
                ),
                bundle["pm_headers"],
            ),
            201,
        )
        assert_time_entry(adjacent)
        assert adjacent["hours"] == pytest.approx(2.0, abs=0.01)
        # The default architect's cost_rate_cents_per_hour is 5_000.
        assert adjacent["cost_cents"] == 10_000
        assert adjacent["status"] == "DRAFT"

    def test_a_new_entry_that_strictly_overlaps_another_is_rejected(self, api):
        """PRD §3.4: "a new entry is rejected when any other entry for the same `staff_member_id`
        in status `DRAFT`, `SUBMITTED` or `APPROVED` satisfies both that the new entry starts
        before the other ends and that the other starts before the new entry ends."
        PRD §3.4: "A genuine overlap is rejected with `ERR_TIME_ENTRY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/staff_timesheet_half_open_interval_admits_adjacency_rejects_strict_overlap
        """
        bundle = setup_executed_project(project_number="OVL-002", name="Overlap Outbuilding")
        activate_phase(bundle, "SD")
        create_time_entry(
            bundle, "SD",
            start_utc="2026-05-04T09:00:00Z", end_utc="2026-05-04T17:00:00Z",
        )
        validate_success(
            api.create_time_entry(
                create_time_entry_payload(
                    bundle["phase_ids"]["SD"], bundle["arch_id"],
                    start_utc="2026-05-04T17:00:00Z", end_utc="2026-05-04T19:00:00Z",
                ),
                bundle["pm_headers"],
            ),
            201,
        )

        # 16:00 falls strictly inside [09:00, 17:00): this is a genuine overlap, not a touch.
        response = api.create_time_entry(
            create_time_entry_payload(
                bundle["phase_ids"]["SD"], bundle["arch_id"],
                start_utc="2026-05-04T16:00:00Z", end_utc="2026-05-04T18:00:00Z",
            ),
            bundle["pm_headers"],
        )
        validate_error(response, ApiErrorId.ERR_TIME_ENTRY_OVERLAP.value)

        rows, meta = validate_paginated(
            api.list_time_entries(
                bundle["pm_headers"], params={"staff_member_id": bundle["arch_id"]}
            )
        )
        assert meta["total_count"] == 2, "only the two non-overlapping entries may exist"
        assert len(rows) == 2


class TestBudgetPostureBoundary:

    def test_labor_cost_below_the_budget_keeps_the_project_within_budget(self, api):
        """PRD §3.4: "Because `labor_cost_cents` moved, `budget_posture` is re-derived: it becomes
        `OVER_BUDGET` when `labor_cost_cents` is greater than **or equal to** `labor_budget_cents`,
        and `WITHIN_BUDGET` otherwise."
        PRD §3.4: "The project's `approved_hours` and `labor_cost_cents` are recomputed as the sums
        of `hours` and of `cost_cents` respectively across every time entry in status `APPROVED`
        whose phase belongs to that project — entries in `DRAFT`, `SUBMITTED` or `REJECTED`
        contribute nothing at all."

        Design: Difficulty/boundary_precision_check/labor_cost_exactly_equal_to_budget_flips_posture_to_over_budget
        """
        bundle = setup_executed_project(
            project_number="BND-001", name="Boundary Barracks",
            labor_budget_cents=160_000, arch_overrides=COSTLY_ARCHITECT,
        )
        activate_phase(bundle, "SD")

        entry = create_approved_time_entry(
            bundle, "SD",
            start_utc="2026-05-04T09:00:00Z", end_utc="2026-05-04T17:00:00Z",
        )
        assert_time_entry(entry)
        assert entry["hours"] == pytest.approx(8.0, abs=0.01)
        assert entry["cost_cents"] == 80_000

        project = read_project(bundle)
        assert project["labor_cost_cents"] == 80_000
        assert project["budget_posture"] == "WITHIN_BUDGET", "80_000 < 160_000"
        assert_project_posture_invariants(project)

    def test_labor_cost_landing_exactly_on_the_budget_flips_to_over_budget(self, api):
        """PRD §3.4: "Landing exactly on the budget flips the project to `OVER_BUDGET`."
        PRD §3.4: "Because `labor_cost_cents` moved, `budget_posture` is re-derived: it becomes
        `OVER_BUDGET` when `labor_cost_cents` is greater than **or equal to** `labor_budget_cents`,
        and `WITHIN_BUDGET` otherwise."

        Design: Difficulty/boundary_precision_check/labor_cost_exactly_equal_to_budget_flips_posture_to_over_budget
        """
        bundle = setup_executed_project(
            project_number="BND-002", name="Boundary Bastion",
            labor_budget_cents=160_000, arch_overrides=COSTLY_ARCHITECT,
        )
        activate_phase(bundle, "SD")

        create_approved_time_entry(
            bundle, "SD",
            start_utc="2026-05-04T09:00:00Z", end_utc="2026-05-04T17:00:00Z",
        )
        assert read_project(bundle)["budget_posture"] == "WITHIN_BUDGET"

        create_approved_time_entry(
            bundle, "SD",
            start_utc="2026-05-05T09:00:00Z", end_utc="2026-05-05T17:00:00Z",
        )

        project = read_project(bundle)
        assert project["labor_cost_cents"] == 160_000
        assert project["approved_hours"] == pytest.approx(16.0, abs=0.01)
        assert project["budget_posture"] == "OVER_BUDGET", (
            "equality flips the posture — the comparison is >=, not >"
        )
        assert_project_posture_invariants(project)


class TestIntervalGateOutranksMoneyGate:

    def test_overlapping_entry_on_an_over_budget_project_reports_the_overlap_error(self, api):
        """PRD §2.7: "14. **Interval occupancy** — `ERR_TIME_ENTRY_OVERLAP`,
        `ERR_CONSULTANT_REVIEW_CAPACITY` (409)."
        PRD §2.7: "15. **Money gates** — `ERR_LABOR_BUDGET_EXCEEDED`,
        `ERR_BILLING_THRESHOLD_NOT_MET`, `ERR_ZERO_INVOICE_AMOUNT`, `ERR_OVERPAYMENT`,
        `ERR_INVOICE_ALREADY_PAID` (409)."
        PRD §2.7: "Checks are therefore evaluated in a fixed order, and the **first** failing check
        determines the response."

        Design: Difficulty/priority_pair_validation_conflict/time_entry_overlap_outranks_labor_budget_exceeded
        """
        bundle = _over_budget_with_two_approved_days(api, "PRI-001", "Priority Pavilion")

        project = read_project(bundle)
        assert project["labor_cost_cents"] == 160_000
        assert project["budget_posture"] == "OVER_BUDGET"

        # This request violates the interval rule (it sits inside 09:00-17:00 on 05-04) AND the
        # money rule (the project is already OVER_BUDGET).
        response = api.create_time_entry(
            create_time_entry_payload(
                bundle["phase_ids"]["SD"], bundle["arch_id"],
                start_utc="2026-05-04T10:00:00Z", end_utc="2026-05-04T12:00:00Z",
            ),
            bundle["pm_headers"],
        )
        error = validate_error(response, ApiErrorId.ERR_TIME_ENTRY_OVERLAP.value)
        assert error["error_id"] != ApiErrorId.ERR_LABOR_BUDGET_EXCEEDED.value

    def test_the_doubly_invalid_entry_is_not_persisted(self, api):
        """PRD §3.4: "A genuine overlap is rejected with `ERR_TIME_ENTRY_OVERLAP`."
        PRD §2.7: "Read this ordering literally."

        Design: Difficulty/priority_pair_validation_conflict/time_entry_overlap_outranks_labor_budget_exceeded
        """
        bundle = _over_budget_with_two_approved_days(api, "PRI-002", "Priority Porch")

        validate_error(
            api.create_time_entry(
                create_time_entry_payload(
                    bundle["phase_ids"]["SD"], bundle["arch_id"],
                    start_utc="2026-05-04T10:00:00Z", end_utc="2026-05-04T12:00:00Z",
                ),
                bundle["pm_headers"],
            ),
            ApiErrorId.ERR_TIME_ENTRY_OVERLAP.value,
        )

        rows, meta = validate_paginated(
            api.list_time_entries(
                bundle["pm_headers"], params={"staff_member_id": bundle["arch_id"]}
            )
        )
        assert meta["total_count"] == 2, "the rejected entry must not have been written"
        starts = {row["start_utc"] for row in rows}
        assert not any("2026-05-04T10:00" in start for start in starts)


class TestApprovalReversalConservesTheRollup:

    def test_reversal_clears_the_approver_and_restores_hours_and_cost(self, api):
        """PRD §3.4: "A `ProjectManager` or `PrincipalArchitect` may drive an entry from `APPROVED`
        back to `SUBMITTED`, clearing `approved_by_user_id` to null and reversing all three cascade
        hops exactly: `approved_hours` and `labor_cost_cents` fall back, `budget_posture` is
        re-derived from the reduced cost, and the contract's `earned_to_date_cents`,
        `wip_balance_cents` and `version` are recomputed."

        Design: Difficulty/compensating_invariant/time_entry_reversal_restores_approved_hours_and_labor_cost_identity
        """
        bundle = setup_executed_project(
            project_number="REV-001", name="Reversal Ridge",
            labor_budget_cents=80_000, arch_overrides=COSTLY_ARCHITECT,
        )
        activate_phase(bundle, "SD")
        entry = create_approved_time_entry(
            bundle, "SD",
            start_utc="2026-05-04T09:00:00Z", end_utc="2026-05-04T17:00:00Z",
        )

        before = read_project(bundle)
        assert before["approved_hours"] == pytest.approx(8.0, abs=0.01)
        assert before["labor_cost_cents"] == 80_000
        assert before["budget_posture"] == "OVER_BUDGET"

        reversed_entry = validate_success(
            api.set_time_entry_state(
                entry["id"], state_payload("SUBMITTED"), bundle["pm_headers"]
            )
        )
        assert_time_entry(reversed_entry)
        assert reversed_entry["status"] == "SUBMITTED"
        assert reversed_entry["approved_by_user_id"] is None

    def test_reversal_returns_the_budget_posture_to_within_budget_with_no_residue(self, api):
        """PRD §3.4: "The project's `approved_hours` and `labor_cost_cents` are recomputed as the
        sums of `hours` and of `cost_cents` respectively across every time entry in status
        `APPROVED` whose phase belongs to that project — entries in `DRAFT`, `SUBMITTED` or
        `REJECTED` contribute nothing at all."
        PRD §2.9: "These compensating paths are not best-effort cleanups: they restore the ledger
        to precisely the state it would have held had the forward operation never run."

        Design: Difficulty/compensating_invariant/time_entry_reversal_restores_approved_hours_and_labor_cost_identity
        """
        bundle = setup_executed_project(
            project_number="REV-002", name="Reversal Row",
            labor_budget_cents=80_000, arch_overrides=COSTLY_ARCHITECT,
        )
        activate_phase(bundle, "SD")
        entry = create_approved_time_entry(
            bundle, "SD",
            start_utc="2026-05-04T09:00:00Z", end_utc="2026-05-04T17:00:00Z",
        )
        assert read_project(bundle)["budget_posture"] == "OVER_BUDGET"

        validate_success(
            api.set_time_entry_state(
                entry["id"], state_payload("SUBMITTED"), bundle["pm_headers"]
            )
        )

        after = read_project(bundle)
        assert after["approved_hours"] == 0
        assert after["labor_cost_cents"] == 0
        assert after["budget_posture"] == "WITHIN_BUDGET"
        assert_project_posture_invariants(after)


class TestTimeEntryValidation:

    def test_end_before_start_is_a_request_shape_error(self, api):
        """PRD §3.4: "A time entry is logged against a `phase_id` for a `staff_member_id`, bounded
        by `start_utc` (inclusive) and `end_utc` (exclusive), which must be strictly later than the
        start."
        PRD §2.7: "4. **Request shape** — required body fields are present, types are correct, enum
        members are valid, and numeric ranges hold (`ERR_INVALID_REQUEST`, 400)."

        Design: Corner/validations/time_entry_end_before_start_returns_invalid_request
        """
        bundle = _project_with_sd_phase_only(api, "BAD-001", 10_000_000)

        response = api.create_time_entry(
            create_time_entry_payload(
                bundle["phase_ids"]["SD"], bundle["arch_id"],
                start_utc="2026-05-04T17:00:00Z", end_utc="2026-05-04T09:00:00Z",
            ),
            bundle["pm_headers"],
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

        _, meta = validate_paginated(
            api.list_time_entries(
                bundle["pm_headers"], params={"staff_member_id": bundle["arch_id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_time_entry_creation_on_an_over_budget_project_is_rejected(self, api):
        """PRD §3.4: "Second, no time may be logged against a project whose `budget_posture` has
        already flipped to `OVER_BUDGET`; that attempt is rejected with `ERR_LABOR_BUDGET_EXCEEDED`."

        Design: Corner/validations/time_entry_creation_on_over_budget_project_is_rejected
        """
        bundle = _project_with_sd_phase_only(api, "BGT-001", 80_000,
                                             arch_overrides=COSTLY_ARCHITECT)
        create_approved_time_entry(
            bundle, "SD",
            start_utc="2026-05-04T09:00:00Z", end_utc="2026-05-04T17:00:00Z",
        )
        assert read_project(bundle)["budget_posture"] == "OVER_BUDGET"

        # A completely non-overlapping day: only the fiscal gate can fire here.
        response = api.create_time_entry(
            create_time_entry_payload(
                bundle["phase_ids"]["SD"], bundle["arch_id"],
                start_utc="2026-05-06T09:00:00Z", end_utc="2026-05-06T17:00:00Z",
            ),
            bundle["pm_headers"],
        )
        validate_error(response, ApiErrorId.ERR_LABOR_BUDGET_EXCEEDED.value)

        _, meta = validate_paginated(
            api.list_time_entries(
                bundle["pm_headers"], params={"staff_member_id": bundle["arch_id"]}
            )
        )
        assert meta["total_count"] == 1


class TestExpenseAmounts:

    def test_billable_cents_is_computed_from_amount_and_markup(self, api):
        """PRD §3.4: "The expense's `billable_cents` is computed at creation: on a reimbursable
        expense it is `amount_cents` multiplied by 10000 plus `markup_bp`, divided by 10000, rounded
        half up to whole cents; on a non-reimbursable expense it is 0."
        PRD §3.4: "A `reimbursable` boolean defaults to `true`, and a `markup_bp` — between 0 and
        5000 basis points inclusive — defaults to 1000, i.e. a ten percent markup."
        PRD §3.4: "Expenses begin in `SUBMITTED` with `invoice_id` null."

        Design: Corner/entities/expense_billable_cents_is_computed_and_client_supplied_value_ignored
        """
        bundle = setup_project(project_number="EXP-001", name="Expense Exchange",
                               labor_budget_cents=500_000)
        arch_headers = make_staff_architect_headers(bundle["arch_id"])

        reimbursable = validate_success(
            api.create_expense(
                create_expense_payload(
                    bundle["project_id"], bundle["arch_id"],
                    category="PRINTING", amount_cents=100_000,
                    reimbursable=True, markup_bp=1000,
                ),
                arch_headers,
            ),
            201,
        )
        assert_expense(reimbursable)
        assert reimbursable["billable_cents"] == 110_000  # 100_000 * 11000 / 10000
        assert reimbursable["status"] == "SUBMITTED"
        assert reimbursable["invoice_id"] is None

        non_reimbursable = validate_success(
            api.create_expense(
                create_expense_payload(
                    bundle["project_id"], bundle["arch_id"],
                    category="TRAVEL", amount_cents=100_000, reimbursable=False,
                ),
                arch_headers,
            ),
            201,
        )
        assert_expense(non_reimbursable)
        assert non_reimbursable["billable_cents"] == 0
        assert non_reimbursable["markup_bp"] == 1000, (
            "the declared default still applies even where it cannot affect billable_cents"
        )


class TestSegregationAndOwnershipOnTime:

    def test_project_manager_cannot_approve_their_own_time_entry(self, api):
        """PRD §2.1: "Approving or rejecting a time entry whose `staff_member_id` equals the
        approver's `X-User-ID` is forbidden."
        PRD §2.1: "All three are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A practical
        consequence: when a `ProjectManager` logs their own hours, only a `PrincipalArchitect` can
        approve them."
        PRD §3.4: "The entry's `approved_by_user_id` records the approver's `X-User-ID`."

        Design: Corner/rbac/project_manager_cannot_approve_their_own_time_entry
        """
        bundle = _project_with_sd_phase_only(api, "SOD-001", 10_000_000)
        pm = bundle["pm_headers"]

        entry = validate_success(
            api.create_time_entry(
                create_time_entry_payload(
                    bundle["phase_ids"]["SD"], bundle["pm_id"],
                    start_utc="2026-05-04T09:00:00Z", end_utc="2026-05-04T13:00:00Z",
                ),
                pm,
            ),
            201,
        )
        submit_time_entry(entry["id"], bundle)

        response = api.set_time_entry_state(entry["id"], state_payload("APPROVED"), pm)
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        assert read_time_entry(bundle, entry["id"])["status"] == "SUBMITTED"

        approved = validate_success(
            api.set_time_entry_state(entry["id"], state_payload("APPROVED"), PRINCIPAL)
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "principal-alice"
        # The manager's own cost_rate_cents_per_hour is 12_000; four hours cost 48_000.
        assert approved["hours"] == pytest.approx(4.0, abs=0.01)
        assert approved["cost_cents"] == 48_000

        project = read_project(bundle)
        assert project["approved_hours"] == pytest.approx(4.0, abs=0.01)
        assert project["labor_cost_cents"] == 48_000

    def test_staff_architect_cannot_log_time_for_another_staff_member(self, api):
        """PRD §2.1: "A `StaffArchitect` may only create a time entry, an expense or a field report
        whose `staff_member_id` equals their own `X-User-ID`; acting for another staff member is
        rejected with `ERR_NOT_OWNER` (HTTP 403)."

        Design: Corner/rbac/staff_architect_cannot_log_time_for_another_staff_member
        """
        bundle = _project_with_sd_phase_only(api, "OWN-002", 10_000_000)
        colleague = validate_success(
            api.create_staff(
                {
                    "full_name": "Blair Builder", "title": "DESIGNER",
                    "billing_rate_cents_per_hour": 9_000, "cost_rate_cents_per_hour": 4_000,
                },
                PRINCIPAL,
            ),
            201,
        )
        arch_headers = make_staff_architect_headers(bundle["arch_id"])

        response = api.create_time_entry(
            create_time_entry_payload(
                bundle["phase_ids"]["SD"], colleague["id"],
                start_utc="2026-05-04T09:00:00Z", end_utc="2026-05-04T17:00:00Z",
            ),
            arch_headers,
        )
        validate_error(response, ApiErrorId.ERR_NOT_OWNER.value)

        own = validate_success(
            api.create_time_entry(
                create_time_entry_payload(
                    bundle["phase_ids"]["SD"], bundle["arch_id"],
                    start_utc="2026-05-04T09:00:00Z", end_utc="2026-05-04T17:00:00Z",
                ),
                arch_headers,
            ),
            201,
        )
        assert own["staff_member_id"] == bundle["arch_id"]
        assert own["status"] == "DRAFT"


def _over_budget_with_two_approved_days(api, project_number, name):
    """Executed project whose labour cost sits exactly on its 160_000-cent budget."""
    bundle = setup_executed_project(
        project_number=project_number, name=name,
        labor_budget_cents=160_000, arch_overrides=COSTLY_ARCHITECT,
    )
    activate_phase(bundle, "SD")
    create_approved_time_entry(
        bundle, "SD", start_utc="2026-05-04T09:00:00Z", end_utc="2026-05-04T17:00:00Z"
    )
    create_approved_time_entry(
        bundle, "SD", start_utc="2026-05-05T09:00:00Z", end_utc="2026-05-05T17:00:00Z"
    )
    return bundle
