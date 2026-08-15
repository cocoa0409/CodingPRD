"""Compensating-pair invariants: the case ledger (money) and the resolution
posture (participant counts) survive a forfeiture and its later restoration
with zero drift."""
from test_helpers import (
    assert_fund_conservation,
    create_cleared_rollover,
    create_recorded_forfeiture,
    get_case,
    locate_participant,
    setup_case_in_distribution,
    setup_exhausted_search,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def _conservation_scenario(api, plan_name, plan_number):
    """Case in DISTRIBUTION_IN_PROGRESS: p1 (800000) MISSING with an exhausted,
    documented search; p2 (200000) resolved via a cleared rollover.
    Returns (case, p1, p2) with the forfeiture NOT yet recorded."""
    case, plist = setup_case_in_distribution(
        participants=[(800000, 100), (200000, 100)],
        plan_name=plan_name, plan_number=plan_number,
    )
    p1, p2 = plist
    create_cleared_rollover(p2["id"])
    setup_exhausted_search(case["id"], p1["id"], document=True)
    return get_case(case["id"]), p1, p2


class TestMoneyConservation:
    def test_forfeiture_forward_leg_conserves_total(self, api):
        """PRD §2.8: "The termination case maintains a conserved ledger. At
        every moment, `total_plan_assets_cents` equals the sum of
        `paid_out_cents`, `pbgc_transferred_cents`, `forfeited_cents`,
        `expense_paid_cents`, and `remaining_undistributed_cents`; this
        invariant is checked after every money-moving transition — payout clear
        or void, PBGC confirmation, forfeiture creation, forfeiture restoration,
        expense allocation, and effectuation."

        Design: Difficulty/compensating_invariant/forfeiture_restoration_money_conservation
        """
        case, p1, _ = _conservation_scenario(api, "Conserve Co 401k", "095")
        # After p2's rollover cleared:
        assert case["paid_out_cents"] == 200000
        assert case["forfeited_cents"] == 0
        assert case["remaining_undistributed_cents"] == 800000
        assert case["total_plan_assets_cents"] == 1000000
        assert_fund_conservation(case)

        create_recorded_forfeiture(p1["id"])
        case = get_case(case["id"])
        assert case["forfeited_cents"] == 800000
        assert case["remaining_undistributed_cents"] == 0, (
            "the forfeiture moves the amount from remaining to forfeited"
        )
        assert case["total_plan_assets_cents"] == 1000000
        assert_fund_conservation(case)

    def test_restoration_compensating_leg_restores_exactly(self, api):
        """PRD §2.8: "Forfeiture creation and its later restoration are a
        compensating pair: creation moves the forfeited amount from
        `remaining_undistributed_cents` to `forfeited_cents`, and a nominal
        restoration moves the same amount back, leaving the conserved total
        unchanged."

        Design: Difficulty/compensating_invariant/forfeiture_restoration_money_conservation
        """
        case, p1, _ = _conservation_scenario(api, "Conserve Co 401k", "095")
        create_recorded_forfeiture(p1["id"])
        locate_participant(p1["id"], verified_address="4 Found Rd")
        case = get_case(case["id"])
        assert case["forfeited_cents"] == 0
        assert case["remaining_undistributed_cents"] == 800000
        assert case["paid_out_cents"] == 200000
        assert case["sponsor_contribution_cents"] == 0
        assert case["total_plan_assets_cents"] == 1000000, (
            "the compensating pair leaves the conserved total unchanged"
        )
        assert_fund_conservation(case)


class TestCountConservation:
    def test_forfeiture_forward_leg_moves_participant_into_resolved(self, api):
        """PRD §2.8: "A parallel conservation holds over participant counts:
        `total_participant_count` always equals `resolved_participant_count`
        plus the number of participants whose `distribution_status` is
        `PENDING_ELECTION`, `ELECTION_SUBMITTED`, `ELECTION_ACCEPTED`, or
        `RESTORED`. A payout clearing moves one participant into the resolved
        set; a forfeiture restoration moves one back out."
        PRD §3.4: "the case's `forfeited_cents` increases by the forfeited
        amount, `remaining_undistributed_cents` decreases by it, and
        `resolved_participant_count` is recomputed — forfeited participants
        count as resolved for reconciliation purposes."

        Design: Difficulty/compensating_invariant/resolution_restoration_count_conservation
        """
        case, p1, _ = _conservation_scenario(api, "Count Co 401k", "096")
        # After p2's rollover cleared:
        assert case["total_participant_count"] == 2
        assert case["resolved_participant_count"] == 1
        assert case["all_participants_resolved"] is False

        create_recorded_forfeiture(p1["id"])
        case = get_case(case["id"])
        assert case["total_participant_count"] == 2
        assert case["resolved_participant_count"] == 2
        assert case["all_participants_resolved"] is True

    def test_restoration_compensating_leg_restores_count(self, api):
        """PRD §2.8: "A parallel conservation holds over participant counts:
        `total_participant_count` always equals `resolved_participant_count`
        plus the number of participants whose `distribution_status` is
        `PENDING_ELECTION`, `ELECTION_SUBMITTED`, `ELECTION_ACCEPTED`, or
        `RESTORED`. A payout clearing moves one participant into the resolved
        set; a forfeiture restoration moves one back out."

        Design: Difficulty/compensating_invariant/resolution_restoration_count_conservation
        """
        case, p1, _ = _conservation_scenario(api, "Count Co 401k", "096")
        create_recorded_forfeiture(p1["id"])
        locate_participant(p1["id"], verified_address="4 Found Rd")
        case = get_case(case["id"])
        assert case["total_participant_count"] == 2
        assert case["resolved_participant_count"] == 1, (
            "the restoration moves one participant back out of the resolved set"
        )
        assert case["all_participants_resolved"] is False
