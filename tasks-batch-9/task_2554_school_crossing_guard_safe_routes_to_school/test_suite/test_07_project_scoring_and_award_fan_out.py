"""Benefit-cost scoring and the fan-out of a single grant award.

A project's score is a capped four-term weighted sum divided by a cost factor
that is floored at 1.00, and awarding money to the winner fans out along two
unrelated chains at once: the program's balance and the cited complaint. These
tests pin the caps, the floor, both branches of the fan-out, and which error a
project that breaks two funding rules at once must report.
"""
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_grant_ledger_conserved,
    assert_same_instant,
    assert_grant_program,
    assert_infrastructure_project,
)
from test_helpers.factories import fund_project_payload
from test_helpers.fixtures import (
    ADMIN,
    ENGINEER,
    advance_clock,
    create_grant_program,
    fund,
    propose_project,
    read_complaint,
    read_intersection,
    read_program,
    read_project,
    setup_grant_competition,
    setup_scored_project,
    setup_triaged_complaint,
    setup_warranted_intersection,
)

# The crash lookback is anchored on the clock, so scoring is done at a fixed
# instant: the 1095-day window ending 2026-09-30 holds both canonical crashes.
SCORING_CLOCK = "2026-09-30T09:00:00Z"


def _warranted_intersection_at_scoring_clock():
    scenario = setup_warranted_intersection()
    advance_clock(SCORING_CLOCK)
    intersection = read_intersection(scenario["intersection"]["id"])
    assert intersection["latest_warrant_score"] == 66.19
    assert intersection["crash_severity_points"] == 23
    return scenario, intersection


def test_the_student_cap_and_the_cost_factor_floor_bind_together(api):
    """500 students sit exactly on the 50.0 student cap and a 3,000,000-cent request
    is floored at 1.00, so the score is 42.23 rather than the 70.38 an unclamped
    0.60 cost factor would produce.

    PRD: "`cost_factor` is `requested_cost_cents` divided by 5,000,000, floored at
    1.00, and is stored to four decimal places; the floor means a project costing
    under $50,000 is never rewarded for being cheap, while above that threshold
    the score falls linearly with cost."

    Design: Difficulty/combinatorial_formula/project_score_nested_caps_and_cost_factor_floor
    """
    scenario, intersection = _warranted_intersection_at_scoring_clock()
    program = create_grant_program(total_cents=12_000_000)
    project = propose_project(program["id"], intersection["id"],
                              requested_cost_cents=3_000_000,
                              students_benefited=500)
    assert project["status"] == "PROPOSED"
    assert project["benefit_points"] is None

    scored = validate_success(api.score_project(project["id"], ENGINEER))

    assert_infrastructure_project(scored)
    assert scored["referred_complaint_count_at_scoring"] == 0
    assert scored["benefit_points"] == 42.2260
    assert scored["cost_factor"] == 1.00
    assert scored["benefit_cost_score"] == 42.23
    assert scored["benefit_cost_score"] != 70.38
    assert scored["status"] == "SCORED"
    assert scored["version"] == project["version"] + 1


def test_students_above_the_cap_add_nothing_while_cost_above_the_floor_divides(api):
    """800 students score exactly as 500 do, and only a request above 5,000,000
    cents starts moving the cost factor.

    PRD: "plus 0.20 times `students_benefited` divided by 10, that quotient capped
    at 50.0" ... "`benefit_cost_score` is `benefit_points` divided by
    `cost_factor`, rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/project_score_nested_caps_and_cost_factor_floor
    """
    scenario, intersection = _warranted_intersection_at_scoring_clock()
    program = create_grant_program(total_cents=12_000_000)

    at_cap = setup_scored_project(program["id"], intersection["id"],
                                  requested_cost_cents=3_000_000,
                                  students_benefited=500)
    above_cap = setup_scored_project(program["id"], intersection["id"],
                                     requested_cost_cents=3_000_000,
                                     students_benefited=800)
    expensive = setup_scored_project(program["id"], intersection["id"],
                                     requested_cost_cents=10_000_000,
                                     students_benefited=500)

    assert above_cap["benefit_points"] == at_cap["benefit_points"] == 42.2260
    assert above_cap["cost_factor"] == at_cap["cost_factor"] == 1.00
    assert above_cap["benefit_cost_score"] == at_cap["benefit_cost_score"] == 42.23
    assert expensive["benefit_points"] == 42.2260
    assert expensive["cost_factor"] == 2.00
    assert expensive["benefit_cost_score"] == 21.11


def _competition_with_a_cited_complaint():
    """One HIGH SPEEDING complaint referred to engineering, a 4,000,000-cent pool,
    and two scored projects on the same intersection — only the first cites the
    complaint, but both count it."""
    scenario = setup_warranted_intersection()
    advance_clock(SCORING_CLOCK)
    intersection_id = scenario["intersection"]["id"]
    complaint = setup_triaged_complaint(intersection_id)
    program = create_grant_program(total_cents=4_000_000)
    winner = setup_scored_project(program["id"], intersection_id,
                                  requested_cost_cents=4_000_000,
                                  students_benefited=500,
                                  source_complaint_id=complaint["id"])
    runner_up = setup_scored_project(program["id"], intersection_id,
                                     requested_cost_cents=2_000_000,
                                     students_benefited=300)
    return {
        "intersection_id": intersection_id,
        "complaint": complaint,
        "program": read_program(program["id"]),
        "winner": winner,
        "runner_up": runner_up,
    }


def test_the_award_drains_the_pool_and_defers_the_sibling_project(api):
    """Branch one of the fan-out: the money chain runs award to balance to sibling
    deferral to carryover.

    PRD: "Three consequences then chain on the program: `committed_cents`
    increases by the awarded amount while `remaining_cents` decreases by the same
    amount, `funded_project_count` increments by 1, and the program's `version`
    increments by 1." ... "and the program's `deferred_project_count` and
    `next_cycle_carryover_cents` are recomputed from that newly deferred set."

    Design: Difficulty/transitive_cascade/fund_award_fans_out_to_grant_balance_sibling_deferral_and_complaint_resolution
    """
    competition = _competition_with_a_cited_complaint()
    before = competition["program"]
    assert before["committed_cents"] == 0
    assert before["remaining_cents"] == 4_000_000
    assert before["deferred_project_count"] == 0
    assert before["next_cycle_carryover_cents"] == 0
    assert competition["winner"]["benefit_cost_score"] == 42.98
    assert competition["runner_up"]["benefit_cost_score"] == 38.98

    fund(competition["winner"]["id"], before)

    program = read_program(before["id"])
    assert_grant_program(program)
    assert_grant_ledger_conserved(program)
    assert program["committed_cents"] == 4_000_000
    assert program["remaining_cents"] == 0
    assert program["funded_project_count"] == 1
    assert program["version"] == before["version"] + 1
    assert program["deferred_project_count"] == 1
    assert program["next_cycle_carryover_cents"] == 2_000_000
    deferred = read_project(competition["runner_up"]["id"])
    assert deferred["status"] == "DEFERRED"
    assert deferred["awarded_cents"] == 0
    assert deferred["benefit_cost_score"] == 38.98


def test_the_award_also_resolves_the_complaint_the_project_cited(api):
    """Branch two of the fan-out reaches the complaint and the intersection, neither
    of which is on the money chain.

    PRD: "Independently of the balance chain, when the project carries a non-null
    `source_complaint_id`, the cited complaint moves `REFERRED → RESOLVED`, which
    drops the intersection's `open_complaint_count` by 1."

    Design: Difficulty/transitive_cascade/fund_award_fans_out_to_grant_balance_sibling_deferral_and_complaint_resolution
    """
    competition = _competition_with_a_cited_complaint()
    winner = competition["winner"]
    cited = read_complaint(competition["complaint"]["id"])
    assert cited["status"] == "REFERRED"
    assert cited["referred_project_id"] == winner["id"]
    assert read_intersection(competition["intersection_id"])["open_complaint_count"] == 1
    assert winner["referred_complaint_count_at_scoring"] == 1

    funded = fund(winner["id"], competition["program"])

    assert_infrastructure_project(funded)
    assert funded["status"] == "FUNDED"
    assert funded["awarded_cents"] == 4_000_000
    assert_same_instant(funded["funded_at"], SCORING_CLOCK,
                        "InfrastructureProject.funded_at")
    assert funded["version"] == winner["version"] + 1
    resolved = read_complaint(competition["complaint"]["id"])
    assert resolved["status"] == "RESOLVED"
    assert resolved["referred_project_id"] == winner["id"]
    assert read_intersection(competition["intersection_id"])["open_complaint_count"] == 0


def _competition(total_cents, requests):
    """A grant competition scored at the fixed scoring clock."""
    scenario = setup_warranted_intersection()
    advance_clock(SCORING_CLOCK)
    return setup_grant_competition(total_cents, requests, scenario)


def test_a_deferred_and_unaffordable_project_reports_the_state_error(api):
    """The runner-up is both out of state and out of money; affordability is checked
    last, so the state error is what the client sees.

    PRD: "Because affordability is checked last, a `DEFERRED` project that also
    could not be afforded reports the state error, never the funds error."

    Design: Difficulty/priority_pair_validation_conflict/deferred_and_unaffordable_project_reports_state_error_not_fiscal_error
    """
    competition = _competition(2_000_000, [(2_000_000, 500), (1_500_000, 300)])
    winner, runner_up = competition["projects"]
    assert winner["benefit_cost_score"] == 42.23
    assert runner_up["benefit_cost_score"] == 38.23
    fund(winner["id"], competition["program"])
    before = read_program(competition["program"]["id"])
    assert before["remaining_cents"] == 0
    assert read_project(runner_up["id"])["status"] == "DEFERRED"

    response = api.fund_project(runner_up["id"],
                                fund_project_payload(before["version"]), ADMIN)

    error = validate_error(response, ApiErrorId.ERR_PROJECT_NOT_SCORED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_GRANT_FUNDS_EXHAUSTED.value
    assert error["error_id"] != ApiErrorId.ERR_PROJECT_NOT_TOP_RANKED.value
    assert response.status_code != 402
    after = read_program(before["id"])
    assert after["version"] == before["version"]
    assert after["remaining_cents"] == 0
    assert after["committed_cents"] == 2_000_000
    assert after["funded_project_count"] == 1
    assert read_project(runner_up["id"])["status"] == "DEFERRED"


def test_the_funds_error_is_what_a_scored_but_unaffordable_project_gets(api):
    """With the state gate satisfied the fiscal gate finally speaks, which is what
    makes the ordering of the two observable.

    PRD: "Last of all, affordability: `requested_cost_cents` must be at most the
    program's `remaining_cents`, and exact equality is allowed and drives the
    balance to precisely 0; exceeding it is refused with
    `ERR_GRANT_FUNDS_EXHAUSTED` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/deferred_and_unaffordable_project_reports_state_error_not_fiscal_error
    """
    competition = _competition(2_000_000, [(3_000_000, 500)])
    only_candidate = competition["projects"][0]
    before = read_program(competition["program"]["id"])
    assert only_candidate["status"] == "SCORED"
    assert only_candidate["benefit_cost_score"] == 42.23

    response = api.fund_project(only_candidate["id"],
                                fund_project_payload(before["version"]), ADMIN)

    error = validate_error(response,
                           ApiErrorId.ERR_GRANT_FUNDS_EXHAUSTED.value, 402)
    assert error["error_id"] != ApiErrorId.ERR_PROJECT_NOT_SCORED.value
    after = read_program(before["id"])
    assert after["version"] == before["version"]
    assert after["committed_cents"] == 0
    assert after["remaining_cents"] == 2_000_000
    assert after["funded_project_count"] == 0
    unchanged = read_project(only_candidate["id"])
    assert unchanged["status"] == "SCORED"
    assert unchanged["awarded_cents"] == 0
    assert unchanged["funded_at"] is None
