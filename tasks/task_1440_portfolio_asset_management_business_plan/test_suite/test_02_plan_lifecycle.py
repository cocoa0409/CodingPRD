"""Business plan lifecycle: revision loop, submit guards, duplicate-window,
supersede rules, approval gates, and plan-create OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_plan,
    create_business_plan_payload,
    create_budget_lines_payload,
    create_draft_plan,
    create_project,
    create_reforecast_payload,
    get_asset,
    get_plan,
    get_success_data,
    lines_nine_no_capital,
    lines_plan10,
    reforecast_lines,
    set_clock,
    setup_base_asset,
    setup_listed_asset,
    setup_plan_scenario,
    submit_plan,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director"]
AM = TEST_USERS["asset_manager"]
AM2 = TEST_USERS["asset_manager2"]
ANALYST = TEST_USERS["analyst"]


class TestPlanRevisionCycle:
    """Difficulty instance: non_linear_state_machine /
    plan_revision_cycle_rejected_to_resubmitted."""

    def _setup(self, api):
        ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_plan10(),
                                  submit=False, approve=False)
        return ctx

    def test_plan_revision_loop_status_sequence(self, api):
        """PRD §3.2: "The plan lifecycle is therefore a genuine revision loop
        — `DRAFT` to `SUBMITTED` to `REJECTED` and back to `SUBMITTED` — and
        it ends at one of the two terminal states, `SUPERSEDED` or `CLOSED`".

        Design: Difficulty/non_linear_state_machine/plan_revision_cycle_rejected_to_resubmitted
        """
        ctx = self._setup(api)
        plan = ctx["plan"]
        assert plan["status"] == "DRAFT"

        submitted = validate_success(api.submit_business_plan(plan["id"], AM), 200)
        assert submitted["status"] == "SUBMITTED"

        rejected = validate_success(api.reject_business_plan(
            plan["id"], {"reason": "Revise opex"}, DIRECTOR), 200)
        assert rejected["status"] == "REJECTED"

        resubmitted = validate_success(api.submit_business_plan(plan["id"], AM), 200)
        assert resubmitted["status"] == "SUBMITTED", \
            "REJECTED must loop back to SUBMITTED on resubmission"

        approved = validate_success(api.approve_business_plan(plan["id"], DIRECTOR), 200)
        assert approved["status"] == "APPROVED"

    def test_plan_revision_loop_version_and_current_plan(self, api):
        """PRD §2.4: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource."
        PRD §3.2: "Approval moves the plan from `SUBMITTED` to `APPROVED`,
        points the asset's `current_plan_id` at it".

        Design: Difficulty/non_linear_state_machine/plan_revision_cycle_rejected_to_resubmitted
        """
        ctx = self._setup(api)
        plan_id = ctx["plan"]["id"]
        # Baseline AFTER the budget-line batch: four transitions follow.
        v_base = get_plan(plan_id)["version"]

        validate_success(api.submit_business_plan(plan_id, AM), 200)
        validate_success(api.reject_business_plan(plan_id, {}, DIRECTOR), 200)
        validate_success(api.submit_business_plan(plan_id, AM), 200)
        validate_success(api.approve_business_plan(plan_id, DIRECTOR), 200)

        final = get_plan(plan_id)
        assert final["version"] == v_base + 4, (
            f"submit/reject/resubmit/approve must each bump the version once: "
            f"expected {v_base + 4}, got {final['version']}")
        asset = get_asset(ctx["asset"]["id"])
        assert asset["current_plan_id"] == plan_id


class TestPlanSubmitGuards:
    def test_plan_invalid_submit_transitions_rejected(self, api):
        """PRD §2.9: "State legality: the target must be in a from-state that
        permits the requested transition, terminal states reject all
        transitions (`ERR_INVALID_STATE_TRANSITION`)".
        PRD §3.2: "Submitting a plan is the asset manager's hand-off to the
        director. From `DRAFT`, submission requires the asset to be `OWNED`".

        Design: Corner/state_machines/plan_invalid_submit_transitions_rejected
        """
        ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_plan10(),
                                  submit=False, approve=False)
        plan_id = ctx["plan"]["id"]
        validate_success(api.submit_business_plan(plan_id, AM), 200)

        res1 = api.submit_business_plan(plan_id, AM)
        validate_error(res1, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        validate_success(api.approve_business_plan(plan_id, DIRECTOR), 200)
        res2 = api.submit_business_plan(plan_id, AM)
        validate_error(res2, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_plan(plan_id)["status"] == "APPROVED"

    def test_plan_submit_on_listed_asset_rejected(self, api):
        """PRD §3.2: "From `DRAFT`, submission requires the asset to be
        `OWNED` (`ERR_ASSET_NOT_OPERATING`, the earlier pipeline tier)".

        Design: Corner/state_machines/plan_submit_on_listed_asset_rejected
        """
        # Acquisition 2021-06-15 with hold_period_years 5 arms sell_signal at
        # the default clock (5 elapsed years >= 5), letting the SELL decision
        # execute and list the asset BEFORE the plan submit below.
        ctx = setup_listed_asset(acquisition_date="2021-06-15",
                                 hold_period_years=5)
        plan, _ = create_draft_plan(get_asset(ctx["asset"]["id"]), 2027,
                                    lines_plan10())
        res = api.submit_business_plan(plan["id"], AM)
        validate_error(res, ApiErrorId.ERR_ASSET_NOT_OPERATING)
        assert get_plan(plan["id"])["status"] == "DRAFT"

    def test_plan_submit_incomplete_categories_rejected(self, api):
        """PRD §3.2: "requires every one of the ten categories to hold at
        least one line (`ERR_PLAN_LINES_INCOMPLETE`)".

        Design: Corner/validations/plan_submit_incomplete_categories_rejected
        """
        ctx = setup_plan_scenario(fiscal_year=2027,
                                  lines=lines_nine_no_capital(),
                                  submit=False, approve=False)
        plan_id = ctx["plan"]["id"]
        res = api.submit_business_plan(plan_id, AM)
        validate_error(res, ApiErrorId.ERR_PLAN_LINES_INCOMPLETE)
        assert get_plan(plan_id)["status"] == "DRAFT"


class TestPlanCreateWindow:
    """Difficulty instance: resource_temporal_overlap /
    plan_year_window_occupied_rejected."""

    def test_plan_year_window_occupied_rejected(self, api):
        """PRD §3.2: "When a plan in `DRAFT` or `SUBMITTED` already exists for
        the same asset and fiscal year, creation fails with
        `ERR_DUPLICATE_PLAN`."

        Design: Difficulty/resource_temporal_overlap/plan_year_window_occupied_rejected
        """
        ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_plan10(),
                                  submit=False, approve=False)
        asset = get_asset(ctx["asset"]["id"])
        res = api.create_business_plan(
            create_business_plan_payload(asset["id"], 2027, asset["version"]), AM)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_PLAN)

    def test_adjacent_year_window_accepted(self, api):
        """PRD §3.2: "When a plan in `DRAFT` or `SUBMITTED` already exists for
        the same asset and fiscal year, creation fails with
        `ERR_DUPLICATE_PLAN`." — the guard keys on (asset, fiscal_year), so a
        different fiscal year is a free window.

        Design: Difficulty/resource_temporal_overlap/plan_year_window_occupied_rejected
        """
        ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_plan10(),
                                  submit=False, approve=False)
        asset = get_asset(ctx["asset"]["id"])
        res = api.create_business_plan(
            create_business_plan_payload(asset["id"], 2028, asset["version"]), AM2)
        plan2 = validate_success(res, 201)
        assert plan2["status"] == "DRAFT"
        assert plan2["fiscal_year"] == 2028


class TestPlanSupersede:
    def test_plan_create_supersedes_approved(self, api):
        """PRD §3.2: "When an `APPROVED` plan exists for the same asset and
        fiscal year, the new draft supersedes it — but only when that approved
        plan carries no capital project in `APPROVED` or `IN_PROGRESS`".
        PRD §3.2: "A successful supersede moves the old plan to `SUPERSEDED`,
        rejects its reforecasts still sitting in `DRAFT` or `SUBMITTED`, and
        recomputes the asset's `current_plan_id` — null until the new plan is
        itself approved — bumping the asset's `version` by one."

        Design: Corner/endpoints/plan_create_supersedes_approved
        """
        ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_plan10())
        old_plan = ctx["plan"]
        asset = get_asset(ctx["asset"]["id"])
        new_plan = validate_success(api.create_business_plan(
            create_business_plan_payload(asset["id"], 2027, asset["version"]),
            AM), 201)
        assert new_plan["status"] == "DRAFT"
        assert get_plan(old_plan["id"])["status"] == "SUPERSEDED"
        assert get_asset(ctx["asset"]["id"])["current_plan_id"] is None

    def test_plan_supersede_blocked_by_active_project(self, api):
        """PRD §3.2: "the new draft supersedes it — but only when that
        approved plan carries no capital project in `APPROVED` or
        `IN_PROGRESS`; otherwise the create call is refused with
        `ERR_PLAN_HAS_ACTIVE_PROJECTS`."

        Design: Corner/endpoints/plan_supersede_blocked_by_active_project
        """
        ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_plan10())
        project = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                                 1000000, 3, 4)
        plan = get_plan(ctx["plan"]["id"])
        validate_success(api.approve_capital_project(
            project["id"], {"expected_plan_version": plan["version"]},
            TEST_USERS["committee"]), 200)

        asset = get_asset(ctx["asset"]["id"])
        res = api.create_business_plan(
            create_business_plan_payload(asset["id"], 2027, asset["version"]), AM)
        validate_error(res, ApiErrorId.ERR_PLAN_HAS_ACTIVE_PROJECTS)
        assert get_plan(ctx["plan"]["id"])["status"] == "APPROVED", \
            "incumbent plan must stay APPROVED when the supersede is refused"


class TestPlanCreateOCC:
    def test_occ_plan_create_stale_asset_version(self, api):
        """PRD §2.7: "Creating a business plan (`POST /api/business-plans`)
        requires `expected_asset_version` matching the target asset's current
        `version`; a mismatch is rejected with `ERR_STALE_ASSET_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_plan_create_stale_asset_version
        """
        ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_plan10())
        asset = ctx["asset"]
        # Approval pointed the asset's current_plan_id at the FY2027 plan
        # (PRD §3.2), advancing Asset.version past the value captured when
        # the asset was created — that pre-approval version is now stale.
        stale_version = asset["version"]
        # A create carrying the stale version is refused (FY2028 avoids the
        # duplicate-window rule, isolating the concurrency failure).
        res = api.create_business_plan(
            create_business_plan_payload(asset["id"], 2028, stale_version), AM)
        validate_error(res, ApiErrorId.ERR_STALE_ASSET_VERSION)


class TestPlanApprovalSuspendedManager:
    """Difficulty instance: cross_entity_state_dependency /
    plan_approval_blocked_by_suspended_manager."""

    def _setup(self, api):
        ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_plan10(),
                                  approve=False)
        validate_success(api.suspend_property_manager(
            ctx["manager"]["id"], {}, DIRECTOR), 200)
        return ctx

    def test_plan_approve_blocked_by_suspended_manager(self, api):
        """PRD §3.2: "the asset's property manager must be `ACTIVE` — a
        `SUSPENDED` or `TERMINATED` manager blocks approval with
        `ERR_MANAGER_SUSPENDED`".

        Design: Difficulty/cross_entity_state_dependency/plan_approval_blocked_by_suspended_manager
        """
        ctx = self._setup(api)
        res = api.approve_business_plan(ctx["plan"]["id"], DIRECTOR)
        validate_error(res, ApiErrorId.ERR_MANAGER_SUSPENDED)

    def test_plan_state_unchanged_after_suspended_manager_rejection(self, api):
        """PRD §3.2: "the asset's property manager must be `ACTIVE` — a
        `SUSPENDED` or `TERMINATED` manager blocks approval with
        `ERR_MANAGER_SUSPENDED`" — a blocked approval writes nothing.

        Design: Difficulty/cross_entity_state_dependency/plan_approval_blocked_by_suspended_manager
        """
        ctx = self._setup(api)
        validate_error(api.approve_business_plan(ctx["plan"]["id"], DIRECTOR),
                       ApiErrorId.ERR_MANAGER_SUSPENDED)
        assert get_plan(ctx["plan"]["id"])["status"] == "SUBMITTED"
        manager = get_success_data(
            api.get_property_manager(ctx["manager"]["id"], ANALYST))
        assert manager["status"] == "SUSPENDED"


class TestReforecastStateBeatsCadence:
    """Difficulty instance: priority_pair_validation_conflict /
    plan_state_conflict_beats_cadence_conflict."""

    def test_draft_plan_reforecast_outside_cadence_returns_state_error(self, api):
        """PRD §2.9: "The full pipeline, in priority order:" places "5. State
        legality: the target must be in a from-state that permits the
        requested transition" before "10. Clock-derived temporal rules
        (`ERR_FUTURE_PERIOD`, `ERR_VALUATION_REGRESSIVE`, `ERR_STALE_VALUATION`,
        `ERR_REFORECAST_CADENCE`, `ERR_REFORECAST_LIMIT`,
        `ERR_LENDER_REPORT_GAP`)".
        PRD §3.3: "The plan must be `APPROVED` (`ERR_PLAN_NOT_APPROVED`)."

        Design: Difficulty/priority_pair_validation_conflict/plan_state_conflict_beats_cadence_conflict
        """
        ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_plan10(),
                                  submit=False, approve=False)
        set_clock("2027-02-10T00:00:00Z")  # fiscal month 2 — outside {4,7,10}
        res = api.create_reforecast(
            create_reforecast_payload(ctx["plan"]["id"], reforecast_lines()), AM)
        err = validate_error(res, ApiErrorId.ERR_PLAN_NOT_APPROVED)
        assert err["error_id"] == "ERR_PLAN_NOT_APPROVED", (
            "state (tier 5) must mask the cadence (tier 10) violation")

    def test_draft_plan_reforecast_inside_cadence_also_returns_state_error(self, api):
        """PRD §3.3: "The plan must be `APPROVED` (`ERR_PLAN_NOT_APPROVED`)."
        PRD §2.9: "5. State legality: the target must be in a from-state that
        permits the requested transition, terminal states reject all
        transitions (`ERR_INVALID_STATE_TRANSITION`), and domain state gates
        apply" — with the cadence window satisfied, the state gate fires alone.

        Design: Difficulty/priority_pair_validation_conflict/plan_state_conflict_beats_cadence_conflict
        """
        ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_plan10(),
                                  submit=False, approve=False)
        set_clock("2027-04-05T00:00:00Z")  # fiscal month 4 — cadence open
        res = api.create_reforecast(
            create_reforecast_payload(ctx["plan"]["id"], reforecast_lines()), AM)
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_APPROVED)
