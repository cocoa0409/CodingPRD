"""Capital project approval gates (availability, schedule, posture, SoD,
OCC), the three-bucket capital ledger invariant, and draw authorization
boundaries."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_project,
    assert_capital_ledger_invariant,
    create_capital_project_payload,
    create_funding_draw_payload,
    create_project,
    get_plan,
    get_success_data,
    lines_plan10,
    make_committee_headers,
    setup_plan_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director"]
AM = TEST_USERS["asset_manager"]
IC = TEST_USERS["committee"]
ANALYST = TEST_USERS["analyst"]


def _approved_plan_ctx(api):
    """FY2027 APPROVED plan with PLAN10 lines (CAPITAL budget 36,000,000,
    monthly schedule cap floor(36,000,000/12) = 3,000,000)."""
    return setup_plan_scenario(fiscal_year=2027, lines=lines_plan10())


class TestScheduleCapacityOverlap:
    """Difficulty instance: resource_temporal_overlap /
    capital_schedule_capacity_overlap_rejected."""

    def test_overlapping_month_over_commit_rejected(self, api):
        """PRD §3.4: "The schedule check caps each month's committed spend at
        one twelfth of the plan's `total_capital_budget_cents`, rounded down
        to a whole cent: for every fiscal month inside the project's closed
        schedule interval, the spend of the plan's other `APPROVED` or
        `IN_PROGRESS` projects whose intervals also contain that month, plus
        this project's own spend for the month, must not exceed the cap, or
        approval fails with `ERR_CAPITAL_SCHEDULE_OVER_COMMITTED`."

        Design: Difficulty/resource_temporal_overlap/capital_schedule_capacity_overlap_rejected
        """
        ctx = _approved_plan_ctx(api)
        x = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                           10000000, 3, 6, name="X")
        approve_project(x["id"], ctx["plan"]["id"], IC)  # 2,500,000/month m3-6
        y = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                           4000000, 4, 5, name="Y")      # 2,000,000/month m4-5
        plan = get_plan(ctx["plan"]["id"])
        res = api.approve_capital_project(
            y["id"], {"expected_plan_version": plan["version"]}, IC)
        validate_error(res, ApiErrorId.ERR_CAPITAL_SCHEDULE_OVER_COMMITTED)
        project = get_success_data(api.get_capital_project(y["id"], ANALYST))
        assert project["status"] == "PROPOSED", (
            "month 4 committed 2,500,000 + 2,000,000 = 4,500,000 > cap "
            "3,000,000 — Y must stay PROPOSED")

    def test_disjoint_intervals_approve_cleanly(self, api):
        """PRD §3.4: "Intervals are closed at both ends, so a project ending
        in a given month collides with another starting in that same month."
        — disjoint intervals share no month and stay within the cap.

        Design: Difficulty/resource_temporal_overlap/capital_schedule_capacity_overlap_rejected
        """
        ctx = _approved_plan_ctx(api)
        x = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                           10000000, 3, 6, name="X")
        approve_project(x["id"], ctx["plan"]["id"], IC)
        y = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                           4000000, 7, 8, name="Y")
        approved = approve_project(y["id"], ctx["plan"]["id"], IC)
        assert approved["status"] == "APPROVED", (
            "months 7-8 share no month with X's [3,6] and 2,000,000/month is "
            "under the 3,000,000 cap")


class TestCapitalAuthorizationConserved:
    """Difficulty instance: compensating_invariant /
    capital_authorization_conserved_across_lifecycle."""

    def _setup(self, api):
        ctx = _approved_plan_ctx(api)
        x = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                           10000000, 3, 6, name="X")
        return ctx, x

    def test_approve_then_release_shift_buckets(self, api):
        """PRD §3.4: "A successful approval sets `approved_amount_cents` equal
        to `requested_amount_cents`, reserves the amount against the plan's
        ledger".
        PRD §3.4: "Money moves only when the director releases an approved
        draw: the project's `drawn_cents` increases by the draw amount ... and
        the plan's drawn and available buckets are recomputed".

        Design: Difficulty/compensating_invariant/capital_authorization_conserved_across_lifecycle
        """
        ctx, x = self._setup(api)
        plan = get_plan(ctx["plan"]["id"])
        assert (plan["available_capital_cents"], plan["reserved_capital_cents"],
                plan["drawn_capital_cents"]) == (36000000, 0, 0)

        approve_project(x["id"], ctx["plan"]["id"], IC)
        plan = get_plan(ctx["plan"]["id"])
        assert (plan["available_capital_cents"], plan["reserved_capital_cents"],
                plan["drawn_capital_cents"]) == (26000000, 10000000, 0), (
            "approval reserves 10,000,000 against the plan")
        assert_capital_ledger_invariant(plan)

        draw = get_success_data(api.create_funding_draw(
            create_funding_draw_payload(x["id"], 6000000), AM))
        get_success_data(api.approve_funding_draw(draw["id"], IC))
        get_success_data(api.release_funding_draw(draw["id"], DIRECTOR))
        plan = get_plan(ctx["plan"]["id"])
        assert (plan["available_capital_cents"], plan["reserved_capital_cents"],
                plan["drawn_capital_cents"]) == (26000000, 4000000, 6000000), (
            "release shifts reserved -> drawn; available unchanged")
        assert_capital_ledger_invariant(plan)

    def test_cancel_releases_reservation_but_drawn_stays_sunk(self, api):
        """PRD §3.4: "Cancellation is available from either `APPROVED` or
        `IN_PROGRESS` ... it releases the same unused authorization back to
        the plan, leaves whatever was drawn standing in the plan's drawn
        bucket as sunk cost".
        PRD §3.4: "the invariant that the total capital budget equals
        available plus reserved plus drawn holds at all times."

        Design: Difficulty/compensating_invariant/capital_authorization_conserved_across_lifecycle
        """
        ctx, x = self._setup(api)
        approve_project(x["id"], ctx["plan"]["id"], IC)
        draw = get_success_data(api.create_funding_draw(
            create_funding_draw_payload(x["id"], 6000000), AM))
        get_success_data(api.approve_funding_draw(draw["id"], IC))
        get_success_data(api.release_funding_draw(draw["id"], DIRECTOR))

        get_success_data(api.start_capital_project(x["id"], AM))
        cancelled = validate_success(api.cancel_capital_project(x["id"], AM), 200)
        assert cancelled["status"] == "CANCELLED"

        plan = get_plan(ctx["plan"]["id"])
        assert (plan["available_capital_cents"], plan["reserved_capital_cents"],
                plan["drawn_capital_cents"]) == (30000000, 0, 6000000), (
            "cancel returns the undrawn 4,000,000 reservation; the released "
            "6,000,000 stays in drawn as sunk cost")
        assert_capital_ledger_invariant(plan)
        assert plan["total_capital_budget_cents"] == 36000000


class TestDrawAuthorizationBoundary:
    """Difficulty instance: boundary_precision_check /
    draw_at_exact_authorization_allowed."""

    def _setup(self, api):
        """Project APPROVED for 10,000,000 (months 3-6); first draw of
        6,000,000 already RELEASED (project.drawn_cents == 6,000,000)."""
        ctx = _approved_plan_ctx(api)
        x = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                           10000000, 3, 6, name="X")
        approve_project(x["id"], ctx["plan"]["id"], IC)
        d1 = get_success_data(api.create_funding_draw(
            create_funding_draw_payload(x["id"], 6000000), AM))
        get_success_data(api.approve_funding_draw(d1["id"], IC))
        get_success_data(api.release_funding_draw(d1["id"], DIRECTOR))
        return ctx, x

    def test_draw_at_exact_authorization_allowed(self, api):
        """PRD §3.4: "the project's `drawn_cents` plus the new `amount_cents`
        must not exceed `approved_amount_cents`, with equality allowed, and
        any excess is `ERR_DRAW_EXCEEDS_AUTHORIZATION`" — 6,000,000 drawn +
        4,000,000 new == 10,000,000 approves.

        Design: Difficulty/boundary_precision_check/draw_at_exact_authorization_allowed
        """
        ctx, x = self._setup(api)
        d2 = get_success_data(api.create_funding_draw(
            create_funding_draw_payload(x["id"], 4000000), AM))
        approved = validate_success(api.approve_funding_draw(d2["id"], IC), 200)
        assert approved["status"] == "APPROVED", \
            "cumulative 10,000,000 == approved 10,000,000 passes (inclusive <=)"

    def test_one_cent_over_authorization_rejected(self, api):
        """PRD §3.4: "the project's `drawn_cents` plus the new `amount_cents`
        must not exceed `approved_amount_cents`, with equality allowed, and
        any excess is `ERR_DRAW_EXCEEDS_AUTHORIZATION`" — with the full
        10,000,000 released, one more cent overflows.

        Design: Difficulty/boundary_precision_check/draw_at_exact_authorization_allowed
        """
        ctx, x = self._setup(api)
        d2 = get_success_data(api.create_funding_draw(
            create_funding_draw_payload(x["id"], 4000000), AM))
        get_success_data(api.approve_funding_draw(d2["id"], IC))
        get_success_data(api.release_funding_draw(d2["id"], DIRECTOR))
        # project.drawn_cents is now exactly 10,000,000
        d3 = get_success_data(api.create_funding_draw(
            create_funding_draw_payload(x["id"], 1), AM))
        res = api.approve_funding_draw(d3["id"], IC)
        validate_error(res, ApiErrorId.ERR_DRAW_EXCEEDS_AUTHORIZATION)
        # The rejected draw is never approved onward.
        draws, _ = validate_paginated(
            api.list_capital_project_funding_draws(x["id"], ANALYST))
        d3_after = [d for d in draws if d["id"] == d3["id"]][0]
        assert d3_after["status"] == "REQUESTED"


class TestSelfApprovalPriority:
    """Difficulty instance: priority_pair_validation_conflict /
    self_approval_conflict_beats_budget_conflict."""

    def _setup(self, api):
        """Plan with 36,000,000 available; 40,000,000 project proposed by
        user am-1 (budget violation armed alongside the SoD violation)."""
        ctx = _approved_plan_ctx(api)
        big = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                             40000000, 1, 12, name="Too big")
        return ctx, big

    def test_self_approval_conflict_beats_budget_conflict(self, api):
        """PRD §3.4: "Segregation of duties follows: the approver's
        `X-User-ID` must differ from the project's `proposed_by_user_id`
        (`ERR_SELF_APPROVAL_FORBIDDEN`). Portfolio posture comes next ... Only
        then do the two fiscal checks run — availability before schedule".
        PRD §2.9: "6. Segregation of duties on capital approval and
        disposition ratification (`ERR_SELF_APPROVAL_FORBIDDEN`)." precedes
        "11. Money checks".

        Design: Difficulty/priority_pair_validation_conflict/self_approval_conflict_beats_budget_conflict
        """
        ctx, big = self._setup(api)
        plan = get_plan(ctx["plan"]["id"])
        # Approver's user id equals the proposer's (am-1) AND the amount
        # (40,000,000) exceeds available capital (36,000,000): SoD must win.
        res = api.approve_capital_project(
            big["id"], {"expected_plan_version": plan["version"]},
            make_committee_headers("am-1"))
        err = validate_error(res, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
        assert err["error_id"] == "ERR_SELF_APPROVAL_FORBIDDEN", \
            "NOT ERR_CAPITAL_BUDGET_EXCEEDED though both violations hold"

    def test_self_approval_rejection_leaves_project_proposed(self, api):
        """PRD §3.4: "the approver's `X-User-ID` must differ from the
        project's `proposed_by_user_id` (`ERR_SELF_APPROVAL_FORBIDDEN`)" — a
        rejected approval performs no state change.

        Design: Difficulty/priority_pair_validation_conflict/self_approval_conflict_beats_budget_conflict
        """
        ctx, big = self._setup(api)
        plan = get_plan(ctx["plan"]["id"])
        validate_error(api.approve_capital_project(
            big["id"], {"expected_plan_version": plan["version"]},
            make_committee_headers("am-1")),
            ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
        project = get_success_data(api.get_capital_project(big["id"], ANALYST))
        assert project["status"] == "PROPOSED"
        assert get_plan(ctx["plan"]["id"])["available_capital_cents"] == 36000000


class TestCapitalApprovalRules:
    def test_capital_budget_exceeded_rejected(self, api):
        """PRD §3.4: "The availability check requires `requested_amount_cents`
        not to exceed the plan's `available_capital_cents`, with equality
        permitted: a full draw-down to zero is valid, and anything more is
        `ERR_CAPITAL_BUDGET_EXCEEDED`."
        PRD §2.9: "Within tier 11, a capital approval that would both exceed
        available capital and over-commit the schedule surfaces
        `ERR_CAPITAL_BUDGET_EXCEEDED`, never the schedule error."

        Design: Corner/endpoints/capital_budget_exceeded_rejected
        """
        ctx = _approved_plan_ctx(api)
        big = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                             40000000, 1, 12, name="BIG")
        plan = get_plan(ctx["plan"]["id"])
        res = api.approve_capital_project(
            big["id"], {"expected_plan_version": plan["version"]}, IC)
        validate_error(res, ApiErrorId.ERR_CAPITAL_BUDGET_EXCEEDED)

    def test_emergency_capital_bypasses_budget_check(self, api):
        """PRD §3.4: "Only then do the two fiscal checks run — availability
        before schedule — and emergency projects skip both, which is the only
        way `available_capital_cents` may go negative."

        Design: Corner/endpoints/emergency_capital_bypasses_budget_check
        """
        ctx = _approved_plan_ctx(api)
        x = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                           30000000, 1, 12, name="X")
        approve_project(x["id"], ctx["plan"]["id"], IC)
        plan = get_plan(ctx["plan"]["id"])
        assert plan["available_capital_cents"] == 6000000

        e = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                           10000000, 1, 6, name="E", is_emergency=True)
        approved = approve_project(e["id"], ctx["plan"]["id"], DIRECTOR)
        assert approved["status"] == "APPROVED", (
            "emergency projects bypass availability and schedule checks")
        plan_after = get_plan(ctx["plan"]["id"])
        assert plan_after["available_capital_cents"] == -4000000, (
            "6,000,000 available - 10,000,000 emergency reservation = "
            "-4,000,000 (the documented negative)")

    def test_emergency_capital_committee_forbidden(self, api):
        """PRD §3.4: "Caller role first: an emergency project approved by
        anyone but a `PortfolioDirector` is `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/endpoints/emergency_capital_committee_forbidden
        """
        ctx = _approved_plan_ctx(api)
        e = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                           5000000, 1, 6, name="E", is_emergency=True)
        plan = get_plan(ctx["plan"]["id"])
        res = api.approve_capital_project(
            e["id"], {"expected_plan_version": plan["version"]}, IC)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_occ_capital_approve_stale_plan_version(self, api):
        """PRD §2.7: "Approving a capital project (`POST
        /api/capital-projects/{id}/approve`) requires `expected_plan_version`
        matching the plan's current `version`; a mismatch is rejected with
        `ERR_STALE_PLAN_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_capital_approve_stale_plan_version
        """
        ctx = _approved_plan_ctx(api)
        x = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                           10000000, 3, 6, name="X")
        y = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                           2000000, 7, 8, name="Y")
        stale = get_plan(ctx["plan"]["id"])["version"]
        first = validate_success(api.approve_capital_project(
            x["id"], {"expected_plan_version": stale}, IC), 200)
        assert first["status"] == "APPROVED"
        res = api.approve_capital_project(
            y["id"], {"expected_plan_version": stale}, IC)
        validate_error(res, ApiErrorId.ERR_STALE_PLAN_VERSION)


class TestProjectDrawPreconditions:
    def test_draw_create_on_proposed_project_rejected(self, api):
        """PRD §3.4: "The asset manager requests a draw with `project_id` and
        an `amount_cents` greater than zero, against a project that is
        `APPROVED` or `IN_PROGRESS` — anything else is
        `ERR_PROJECT_NOT_FUNDABLE`".

        Design: Corner/state_machines/draw_create_on_proposed_project_rejected
        """
        ctx = _approved_plan_ctx(api)
        project = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                                 1000000, 3, 4, name="X")
        res = api.create_funding_draw(
            create_funding_draw_payload(project["id"], 100000), AM)
        validate_error(res, ApiErrorId.ERR_PROJECT_NOT_FUNDABLE)

    def test_project_complete_without_funding_rejected(self, api):
        """PRD §3.4: "Completion — also by the asset manager — requires that
        something was actually drawn: `drawn_cents` must be greater than zero,
        else `ERR_PROJECT_NEVER_FUNDED`."

        Design: Corner/state_machines/project_complete_without_funding_rejected
        """
        ctx = _approved_plan_ctx(api)
        project = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                                 1000000, 3, 4, name="X")
        approve_project(project["id"], ctx["plan"]["id"], IC)
        get_success_data(api.start_capital_project(project["id"], AM))
        res = api.complete_capital_project(project["id"], AM)
        validate_error(res, ApiErrorId.ERR_PROJECT_NEVER_FUNDED)
        after = get_success_data(api.get_capital_project(project["id"], ANALYST))
        assert after["status"] == "IN_PROGRESS"
