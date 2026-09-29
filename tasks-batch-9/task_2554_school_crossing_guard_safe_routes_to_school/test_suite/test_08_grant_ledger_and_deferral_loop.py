"""The grant ledger under an award and its withdrawal, and the deferral loop.

Money is the conserved quantity of this program: total_cents always equals
committed plus remaining, and a withdrawal must restore the pre-award figures
exactly. The same withdrawal also drives a sibling project backwards around the
SCORED to DEFERRED to SCORED loop without re-scoring it.
"""
from test_helpers.assertions import (
    assert_grant_ledger_conserved,
    assert_same_instant,
    assert_grant_program,
    assert_infrastructure_project,
)
from test_helpers.fixtures import (
    advance_clock,
    fund,
    read_program,
    read_project,
    setup_grant_competition,
    setup_warranted_intersection,
    withdraw,
)

SCORING_CLOCK = "2026-09-30T09:00:00Z"
WITHDRAWAL_REASON = "Scope moved to the FY28 cycle."
UTILITY_CONFLICT = "Utility conflict discovered during design."


def _competition(total_cents, requests):
    """A grant competition whose projects are scored at the fixed scoring clock."""
    scenario = setup_warranted_intersection()
    advance_clock(SCORING_CLOCK)
    return setup_grant_competition(total_cents, requests, scenario)


def _three_way_competition_with_the_pool_drained():
    """A 6,000,000-cent pool spent on the top two projects, which leaves the third
    deferred by cascade rather than by any act of its own."""
    competition = _competition(6_000_000, [(4_000_000, 500), (2_000_000, 300),
                                           (2_000_000, 150)])
    first, second, third = competition["projects"]
    assert first["benefit_cost_score"] == 42.23
    assert second["benefit_cost_score"] == 38.23
    assert third["benefit_cost_score"] == 35.23

    fund(first["id"], read_program(competition["program"]["id"]))
    assert read_project(third["id"])["status"] == "SCORED"
    fund(second["id"], read_program(competition["program"]["id"]))

    competition["projects"] = [first, second, third]
    return competition


def test_a_sibling_withdrawal_walks_the_deferred_project_back_to_scored(api):
    """The third project never receives a request of its own: a sibling's award
    defers it and that sibling's withdrawal revives it, score intact.

    PRD: "every project of the program in `DEFERRED` returns `DEFERRED → SCORED`,
    re-entering the ranking pool with the `benefit_cost_score` it was previously
    given rather than being re-scored, and `deferred_project_count` and
    `next_cycle_carryover_cents` are recomputed."

    Design: Difficulty/non_linear_state_machine/project_scored_deferred_scored_reentry_loop
    """
    competition = _three_way_competition_with_the_pool_drained()
    _, second, third = competition["projects"]
    program_id = competition["program"]["id"]
    deferred = read_project(third["id"])
    assert deferred["status"] == "DEFERRED"
    assert read_program(program_id)["deferred_project_count"] == 1
    assert read_program(program_id)["next_cycle_carryover_cents"] == 2_000_000

    withdraw(second["id"], read_program(program_id), reason=WITHDRAWAL_REASON)

    revived = read_project(third["id"])
    assert_infrastructure_project(revived)
    assert revived["status"] == "SCORED"
    assert revived["benefit_cost_score"] == 35.23
    assert revived["awarded_cents"] == 0
    assert revived["funded_at"] is None
    assert revived["withdrawal_reason"] is None


def test_the_withdrawn_project_returns_to_scored_and_keeps_its_history(api):
    """The withdrawal is the inverse of the award on the program's counters, while
    the withdrawn project keeps the fact that money once moved.

    PRD: "Withdrawal moves the project `FUNDED → SCORED`, resets `awarded_cents`
    to 0 and stores the `withdrawal_reason`, while `funded_at` is retained as
    history so the fact that money once moved remains visible."

    Design: Difficulty/non_linear_state_machine/project_scored_deferred_scored_reentry_loop
    """
    competition = _three_way_competition_with_the_pool_drained()
    first, second, _ = competition["projects"]
    program_id = competition["program"]["id"]
    drained = read_program(program_id)
    assert drained["remaining_cents"] == 0

    released = withdraw(second["id"], drained, reason=WITHDRAWAL_REASON)

    assert released["status"] == "SCORED"
    assert released["awarded_cents"] == 0
    assert released["withdrawal_reason"] == WITHDRAWAL_REASON
    assert_same_instant(released["funded_at"], SCORING_CLOCK,
                        "InfrastructureProject.funded_at")
    assert released["benefit_cost_score"] == 38.23
    program = read_program(program_id)
    assert_grant_program(program)
    assert program["committed_cents"] == 4_000_000
    assert program["remaining_cents"] == 2_000_000
    assert program["funded_project_count"] == 1
    assert program["deferred_project_count"] == 0
    assert program["next_cycle_carryover_cents"] == 0
    assert program["version"] == drained["version"] + 1
    still_funded = read_project(first["id"])
    assert still_funded["status"] == "FUNDED"
    assert still_funded["awarded_cents"] == 4_000_000


def test_the_grant_ledger_balances_before_during_and_after_an_award(api):
    """Three observation points, one conserved quantity: committed plus remaining
    equals the pool at each of them, and the withdrawal restores the opening figures
    exactly.

    PRD: "A new program begins with `committed_cents` at 0, `remaining_cents` equal
    to `total_cents`, and `funded_project_count`, `deferred_project_count` and
    `next_cycle_carryover_cents` all at 0." ... "On the program, `committed_cents`
    decreases and `remaining_cents` increases by the released amount,
    `funded_project_count` decrements by 1, and `version` increments by 1."

    Design: Difficulty/compensating_invariant/grant_ledger_conserved_across_award_and_withdrawal
    """
    competition = _competition(9_000_000, [(5_000_000, 500), (3_000_000, 300)])
    winner = competition["projects"][0]
    opening = read_program(competition["program"]["id"])
    assert_grant_ledger_conserved(opening)
    assert opening["total_cents"] == 9_000_000
    assert opening["committed_cents"] == 0
    assert opening["remaining_cents"] == 9_000_000
    assert opening["funded_project_count"] == 0

    funded = fund(winner["id"], opening)
    awarded = read_program(opening["id"])
    assert_grant_ledger_conserved(awarded)
    assert awarded["committed_cents"] == 5_000_000
    assert awarded["remaining_cents"] == 4_000_000
    assert awarded["funded_project_count"] == 1
    assert awarded["version"] == opening["version"] + 1
    assert funded["status"] == "FUNDED"
    assert funded["awarded_cents"] == 5_000_000
    assert funded["cost_factor"] == 1.00
    assert funded["benefit_cost_score"] == 42.23

    released = withdraw(winner["id"], awarded, reason=UTILITY_CONFLICT)

    restored = read_program(opening["id"])
    assert_grant_ledger_conserved(restored)
    assert restored["committed_cents"] == 0
    assert restored["remaining_cents"] == 9_000_000
    assert restored["funded_project_count"] == 0
    assert restored["version"] == awarded["version"] + 1
    assert released["status"] == "SCORED"
    assert released["awarded_cents"] == 0
    assert released["withdrawal_reason"] == UTILITY_CONFLICT
    assert_same_instant(released["funded_at"], SCORING_CLOCK,
                        "InfrastructureProject.funded_at")
    assert released["benefit_cost_score"] == 42.23


def test_an_award_that_leaves_money_behind_defers_nothing(api):
    """Because the balance never reaches 0 the deferral cascade cannot fire, so the
    runner-up is untouched at all three observation points.

    PRD: "`deferred_project_count` is the number of the program's projects whose
    `status` is `DEFERRED`, and `next_cycle_carryover_cents` is the sum of
    `requested_cost_cents` across exactly that set"

    Design: Difficulty/compensating_invariant/grant_ledger_conserved_across_award_and_withdrawal
    """
    competition = _competition(9_000_000, [(5_000_000, 500), (3_000_000, 300)])
    winner, runner_up = competition["projects"]
    opening = read_program(competition["program"]["id"])
    assert opening["deferred_project_count"] == 0
    assert opening["next_cycle_carryover_cents"] == 0
    assert runner_up["status"] == "SCORED"
    assert runner_up["benefit_cost_score"] == 38.23

    fund(winner["id"], opening)
    awarded = read_program(opening["id"])
    assert awarded["deferred_project_count"] == 0
    assert awarded["next_cycle_carryover_cents"] == 0
    mid = read_project(runner_up["id"])
    assert mid["status"] == "SCORED"
    assert mid["benefit_cost_score"] == 38.23
    assert mid["version"] == runner_up["version"]

    withdraw(winner["id"], awarded, reason=UTILITY_CONFLICT)

    restored = read_program(opening["id"])
    assert restored["deferred_project_count"] == 0
    assert restored["next_cycle_carryover_cents"] == 0
    after = read_project(runner_up["id"])
    assert_infrastructure_project(after)
    assert after["status"] == "SCORED"
    assert after["benefit_cost_score"] == 38.23
    assert after["awarded_cents"] == 0
    assert after["version"] == runner_up["version"]
