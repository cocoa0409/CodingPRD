"""Non-linear state-machine shape tests.

Estate has a true cycle PROBATE_OPEN -> CONTESTED -> PROBATE_OPEN; ProbateOrder
DRAFT->ENTERED branches into different cascades based on order_type.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    bootstrap_estate_in_probate_open_with_beneficiary,
    bootstrap_estate_in_probate_open,
    create_probate_order,
    enter_probate_order,
    make_judge_headers,
    make_beneficiary_headers,
    make_executor_headers,
    make_planner_headers,
)


class TestEstateContestCycle:
    """PRD §3.7: contest moves PROBATE_OPEN -> CONTESTED; resolve returns
    CONTESTED -> PROBATE_OPEN."""

    def test_contest_advances_to_contested_then_resolve_returns(self, api):
        """PRD §3.7: "The contest action moves the estate from PROBATE_OPEN
        to CONTESTED."
        PRD §3.7: "A judge resolves the contest by submitting a
        resolution_note and moves the estate from CONTESTED back to
        PROBATE_OPEN."

        Design: Difficulty/non_linear_state_machine/estate_contested_cycle_back_to_probate_open
        """
        ctx = bootstrap_estate_in_probate_open_with_beneficiary()
        ben_id = ctx["beneficiary"]["id"]
        est = ctx["estate"]
        # Sanity: state pre-contest.
        assert est["status"] == "PROBATE_OPEN"
        v_pre = est["version"]
        # Beneficiary contests.
        resp_contest = api.contest_estate(
            est["id"],
            expected_estate_version=v_pre,
            reason="validity challenge",
            headers=make_beneficiary_headers(ben_id),
        )
        d_contest = validate_success(resp_contest, expected_status=200)
        assert d_contest["status"] == "CONTESTED"
        # Judge resolves.
        resp_resolve = api.resolve_contest(
            est["id"], resolution_note="court resolved",
            headers=make_judge_headers(),
        )
        d_resolve = validate_success(resp_resolve, expected_status=200)
        assert d_resolve["status"] == "PROBATE_OPEN", (
            f"After resolve-contest the estate should return to PROBATE_OPEN, "
            f"got {d_resolve['status']!r}"
        )

    def test_each_cycle_hop_increments_version(self, api):
        """PRD §3.7: "The estate's version increments by one for the contest
        as a whole, regardless of how many orders were superseded."
        PRD §3.7: "Estate.version increments by one on resolution."

        Design: Difficulty/non_linear_state_machine/estate_contested_cycle_back_to_probate_open
        """
        ctx = bootstrap_estate_in_probate_open_with_beneficiary()
        ben_id = ctx["beneficiary"]["id"]
        est = ctx["estate"]
        v_pre = est["version"]
        # Contest.
        resp_contest = api.contest_estate(
            est["id"], expected_estate_version=v_pre,
            reason="r", headers=make_beneficiary_headers(ben_id),
        )
        d_contest = validate_success(resp_contest, expected_status=200)
        assert d_contest["version"] == v_pre + 1, (
            f"Estate.version should bump by exactly 1 on contest "
            f"({v_pre}->{v_pre+1}), got {d_contest['version']}"
        )
        # Resolve.
        resp_resolve = api.resolve_contest(
            est["id"], resolution_note="r2", headers=make_judge_headers(),
        )
        d_resolve = validate_success(resp_resolve, expected_status=200)
        assert d_resolve["version"] == d_contest["version"] + 1, (
            f"Estate.version should bump by exactly 1 on resolve "
            f"({d_contest['version']}->{d_contest['version']+1}), "
            f"got {d_resolve['version']}"
        )


class TestProbateOrderBranchingByType:
    """PRD §3.5: enter on different order_type produces different cascades
    from the same FROM=DRAFT state."""

    def test_approve_inventory_branch_advances_to_administration(self, api):
        """PRD §3.5: "Entering an APPROVE_INVENTORY order advances the estate
        from PROBATE_OPEN to ADMINISTRATION, but only if every asset on the
        estate has a non-DRAFT status (no draft asset may slip through into
        administration) and the gross estate value is strictly positive"

        Design: Difficulty/non_linear_state_machine/probate_order_branching_by_order_type
        """
        ctx = bootstrap_estate_in_probate_open(
            clock="2026-01-01T00:00:00Z",
            date_of_death="2026-01-15T00:00:00Z",
            asset_value_cents=500000,
            domicile_state_code="FL",
        )
        approve = create_probate_order(ctx["estate"]["id"], "APPROVE_INVENTORY")
        enter_probate_order(approve["id"])
        # Estate must now be in ADMINISTRATION.
        resp = api.get_estate(ctx["estate"]["id"], make_judge_headers())
        d = validate_success(resp, expected_status=200)
        assert d["status"] == "ADMINISTRATION", (
            f"APPROVE_INVENTORY branch should advance to ADMINISTRATION, "
            f"got {d['status']!r}"
        )

    def test_open_probate_branch_confirms_executor(self, api):
        """PRD §3.5: "Entering an OPEN_PROBATE order advances the estate from
        PROBATE_PENDING to PROBATE_OPEN, stamps Estate.probate_opened_at with
        the order's entered_at, and cascades the unique ACCEPTED executor up
        to COURT_CONFIRMED."

        Design: Difficulty/non_linear_state_machine/probate_order_branching_by_order_type
        """
        # bootstrap_estate_in_probate_open already enters an OPEN_PROBATE order.
        ctx = bootstrap_estate_in_probate_open()
        # Re-fetch executor to confirm COURT_CONFIRMED.
        exec_id = ctx["executor"]["id"]
        resp = api.get_executor(exec_id, make_executor_headers(exec_id))
        d = validate_success(resp, expected_status=200)
        assert d["status"] == "COURT_CONFIRMED", (
            f"Executor should be cascaded to COURT_CONFIRMED via OPEN_PROBATE "
            f"branch, got {d['status']!r}"
        )
