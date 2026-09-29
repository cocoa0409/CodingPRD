"""Requests that violate two rules at once, and the single error each may return.

Each pair here is asserted twice over.  The conflicting request must surface the
higher-ranked refusal, and a control request built to violate only the lower-ranked
rule must then surface that rule's own code, which proves the outranked rule was
genuinely live and merely lost the ordering.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_CANDIDATE_STATE_INVALID,
    ERR_INTERLOCK_LIMIT_EXCEEDED,
    ERR_INTERVIEWER_DOUBLE_BOOKED,
    ERR_SEARCH_FEE_BUDGET_EXCEEDED,
)
from test_helpers.assertions import assert_fields_equal, assert_firm_ledger, assert_page
from test_helpers.test_users import STAFF, make_committee_chair_headers

# One completed interview is enough for a reference check, so the pipeline stays short.
MIN_COMPLETED_INTERVIEWS = 1

# The window already booked on the interviewer's calendar, and a second window that
# starts inside it, so the two genuinely overlap on the half-open interval.
BOOKED_START_AT = "2026-03-02T10:00:00Z"
BOOKED_END_AT = "2026-03-02T11:00:00Z"
OVERLAP_START_AT = "2026-03-02T10:30:00Z"
OVERLAP_END_AT = "2026-03-02T11:30:00Z"

# The firm's tier-1 percentage and the candidates' target pay: 27.5 percent of
# 35000020 cents is 9625005.5, which rounds half up to 9625006 whole cents.
PLACEMENT_FEE_PCT = 27.5
PLACEMENT_FEE_TIER2_PCT = 22.5
TARGET_ANNUAL_COMP_CENTS = 35000020

# The slate's budget is far below that single 9625006-cent fee, so the fiscal gate
# is armed for whichever nominee reaches it.
SEARCH_FEE_BUDGET_CENTS = 1000000

# Nine seats stand for election, so the seat-count gate never fires first.
SLATE_SEAT_COUNT = 9

# A slate is born at version 1 and no rejected write may move it.
SLATE_VERSION_AT_OPEN = 1


def _proposal_candidate(client, name, email, birth_date):
    """A shareholder-proposal candidate, so no search firm and no fee is involved."""
    return X.new_candidate(
        client,
        full_name=name,
        email=email,
        birth_date=birth_date,
        source_channel="SHAREHOLDER_PROPOSAL",
        shareholder_proponent_name="Cedar Ridge Capital",
    )


def _interview_calendar_world(client):
    """Interviewer X already holds one booked window on 2026-03-02.

    Candidate B is left at its initial status with no screen at all, so a
    scheduling request naming B breaks the candidate-state rule and the calendar
    rule at once.  Candidate C is screen-passed, so the identical window breaks
    only the calendar rule.
    """
    X.adopt_policy(client, min_completed_interviews=MIN_COMPLETED_INTERVIEWS)
    chair = X.new_seated_director(
        client,
        full_name="Dana Chair",
        email="dana.chair@issuer.example",
        birth_date="1962-03-15",
        appointed_on="2019-05-01",
    )
    chair_headers = make_committee_chair_headers(chair["id"])
    interviewer = X.new_seated_director(
        client,
        full_name="Xavier Interviewer",
        email="xavier@issuer.example",
        birth_date="1966-07-07",
        appointed_on="2020-05-01",
    )

    candidate_a = _proposal_candidate(client, "Aida Alpha", "aida@cand.example", "1974-01-05")
    X.advance_to_screen_passed(client, candidate_a["id"], chair_headers)
    session_a = X.schedule_interview(
        client, candidate_a["id"], interviewer["id"], BOOKED_START_AT, BOOKED_END_AT
    )

    candidate_b = _proposal_candidate(client, "Bruno Beta", "bruno@cand.example", "1975-02-06")

    candidate_c = _proposal_candidate(client, "Carla Gamma", "carla@cand.example", "1976-03-07")
    X.advance_to_screen_passed(client, candidate_c["id"], chair_headers)

    return {
        "interviewer_id": interviewer["id"],
        "sourced_candidate_id": candidate_b["id"],
        "screen_passed_candidate_id": candidate_c["id"],
        "session_a_id": session_a["id"],
    }


def _overlapping_schedule_attempt(client, candidate_id, interviewer_id):
    """The same overlapping window, aimed at whichever candidate the test names."""
    return client.schedule_interview(
        F.interview_payload(
            candidate_id,
            interviewer_id,
            start_at=OVERLAP_START_AT,
            end_at=OVERLAP_END_AT,
        ),
        STAFF,
    )


def _nominee_gate_world(client):
    """Two cleared search-firm candidates and a slate whose fee budget is tiny.

    The interlocked candidate shares both of the incumbent director's outside
    public boards, so the shared-board count reaches the policy's limit of two;
    it also carries a placement fee far above the slate's budget, so its add
    breaks a safety guideline and the fiscal limit at once.  The clean candidate
    shares no board and therefore breaks only the fiscal limit.
    """
    X.adopt_policy(client, min_completed_interviews=MIN_COMPLETED_INTERVIEWS)
    firm = X.new_search_firm(
        client,
        name="Aurora Board Search",
        contact_email="partners@aurora.example",
        fee_model="CONTINGENT",
        retainer_fee_cents=0,
        placement_fee_pct=PLACEMENT_FEE_PCT,
        placement_fee_tier2_pct=PLACEMENT_FEE_TIER2_PCT,
    )
    chair = X.new_seated_director(
        client,
        full_name="Dana Chair",
        email="dana.chair@issuer.example",
        birth_date="1962-03-15",
        appointed_on="2019-05-01",
    )
    chair_headers = make_committee_chair_headers(chair["id"])
    interviewer = X.new_seated_director(
        client,
        full_name="Ivan Interviewer",
        email="ivan@issuer.example",
        birth_date="1966-07-07",
        appointed_on="2020-05-01",
    )
    incumbent = X.new_seated_director(
        client,
        full_name="Ines Incumbent",
        email="ines@issuer.example",
        birth_date="1965-08-08",
        appointed_on="2021-01-01",
        is_independent=True,
    )

    shared_one = X.new_external_company(
        client, name="Northwind Industries", ticker="NWI", is_public=True, is_competitor=False
    )
    shared_two = X.new_external_company(
        client, name="Cascade Logistics", ticker="CSL", is_public=True, is_competitor=False
    )
    X.give_director_boards(client, incumbent["id"], [shared_one["id"], shared_two["id"]])

    interlocked = X.new_search_firm_candidate(
        client,
        firm["id"],
        full_name="Dora Delta",
        email="dora@cand.example",
        birth_date="1972-04-02",
        target_annual_comp_cents=TARGET_ANNUAL_COMP_CENTS,
    )
    X.advance_to_slate_eligible(
        client, interlocked["id"], chair_headers, [interviewer["id"]], scores=(4,), first_slot=0
    )
    # The shared seats are recorded only after clearance, so the interlock rule
    # bites for the first time at the nominee add.
    X.give_candidate_boards(client, interlocked["id"], [shared_one["id"], shared_two["id"]])

    clean = X.new_search_firm_candidate(
        client,
        firm["id"],
        full_name="Elias Epsilon",
        email="elias@cand.example",
        birth_date="1973-05-03",
        target_annual_comp_cents=TARGET_ANNUAL_COMP_CENTS,
    )
    X.advance_to_slate_eligible(
        client, clean["id"], chair_headers, [interviewer["id"]], scores=(4,), first_slot=1
    )

    slate = X.new_slate(
        client,
        cycle_year=C.CYCLE_YEAR,
        seat_count=SLATE_SEAT_COUNT,
        search_fee_budget_cents=SEARCH_FEE_BUDGET_CENTS,
    )

    return {
        "firm_id": firm["id"],
        "interlocked_id": interlocked["id"],
        "clean_id": clean["id"],
        "slate_id": slate["id"],
        "slate_version": slate["version"],
    }


def _nominee_add_attempt(client, world, candidate_id, ballot_order):
    """Add one nominee, echoing the slate version the slate was opened at."""
    return client.add_slate_nominee(
        world["slate_id"],
        F.nominee_payload(world["slate_version"], ballot_order, candidate_id=candidate_id),
        STAFF,
    )


def test_candidate_state_error_outranks_the_interviewer_double_booking(client):
    """One scheduling request names a candidate that never left its initial status and
    also overlaps the interviewer's booked window; only the state refusal comes back.

    PRD: "exactly one error is returned, and which one is fully determined. Checks run in the following order, and the first failure wins"

    Design: Difficulty/priority_pair_validation_conflict/interview_scheduling_state_error_wins_over_double_booking_error
    """
    world = _interview_calendar_world(client)

    response = _overlapping_schedule_attempt(
        client, world["sourced_candidate_id"], world["interviewer_id"]
    )

    error = validate_error(response, ERR_CANDIDATE_STATE_INVALID, expected_status=409)
    assert error["error_id"] != ERR_INTERVIEWER_DOUBLE_BOOKED


def test_the_outranked_double_booking_rule_is_genuinely_violated(client):
    """The identical window offered for a screen-passed candidate surfaces the calendar
    refusal, and the interviewer's calendar still holds exactly the one booked session.

    PRD: "it must not overlap any session of the same `interviewer_director_id` whose `status` is `SCHEDULED` or `COMPLETED`"

    Design: Difficulty/priority_pair_validation_conflict/interview_scheduling_state_error_wins_over_double_booking_error
    """
    world = _interview_calendar_world(client)

    validate_error(
        _overlapping_schedule_attempt(
            client, world["screen_passed_candidate_id"], world["interviewer_id"]
        ),
        ERR_INTERVIEWER_DOUBLE_BOOKED,
        expected_status=409,
    )

    rows, _meta = assert_page(
        client.list_interviews(
            STAFF, params={"interviewer_director_id": world["interviewer_id"]}
        ),
        expected_total=1,
        expected_ids=[world["session_a_id"]],
    )
    assert_fields_equal(rows[0], {"status": "SCHEDULED"})


def test_neither_rejected_scheduling_attempt_advances_its_candidate(client):
    """Scheduling is the only route into interviewing, so both refused requests leave
    their candidates exactly where they were.

    PRD: "Scheduling the first session of a round moves the candidate from screen-passed into interviewing"

    Design: Difficulty/priority_pair_validation_conflict/interview_scheduling_state_error_wins_over_double_booking_error
    """
    world = _interview_calendar_world(client)

    validate_error(
        _overlapping_schedule_attempt(
            client, world["sourced_candidate_id"], world["interviewer_id"]
        ),
        ERR_CANDIDATE_STATE_INVALID,
        expected_status=409,
    )
    validate_error(
        _overlapping_schedule_attempt(
            client, world["screen_passed_candidate_id"], world["interviewer_id"]
        ),
        ERR_INTERVIEWER_DOUBLE_BOOKED,
        expected_status=409,
    )

    assert_fields_equal(
        X.get_candidate(client, world["sourced_candidate_id"]),
        {"status": "SOURCED", "interview_round": 0},
    )
    assert_fields_equal(
        X.get_candidate(client, world["screen_passed_candidate_id"]),
        {"status": "SCREEN_PASSED", "interview_round": 0},
    )


def test_interlock_safety_error_outranks_the_search_fee_budget_on_a_nominee_add(client):
    """The interlocked candidate's add breaches the interlocking-directorate guideline
    and the slate's fee budget at once; the safety code is the one returned.

    PRD: "`ERR_SEARCH_FEE_BUDGET_EXCEEDED` (422) is the final gate on a nominee add, so a nominee that also breaches a safety guideline surfaces the safety code, not the budget code."

    Design: Difficulty/priority_pair_validation_conflict/interlock_safety_error_wins_over_search_fee_budget_error_on_nominee_add
    """
    world = _nominee_gate_world(client)

    response = _nominee_add_attempt(client, world, world["interlocked_id"], 1)

    error = validate_error(response, ERR_INTERLOCK_LIMIT_EXCEEDED, expected_status=422)
    assert error["error_id"] != ERR_SEARCH_FEE_BUDGET_EXCEEDED


def test_the_outranked_search_fee_budget_gate_is_genuinely_violated(client):
    """The candidate with no shared board carries the same 9625006-cent tier-1 fee, so
    its add reaches the last gate of all and is refused on the budget.

    PRD: "the slate's `committed_search_fee_cents` including the new nominee may not exceed the slate's `search_fee_budget_cents`"

    Design: Difficulty/priority_pair_validation_conflict/interlock_safety_error_wins_over_search_fee_budget_error_on_nominee_add
    """
    world = _nominee_gate_world(client)

    response = _nominee_add_attempt(client, world, world["clean_id"], 1)

    validate_error(response, ERR_SEARCH_FEE_BUDGET_EXCEEDED, expected_status=422)


def test_neither_rejected_nominee_add_moves_the_slate_off_its_opening_values(client):
    """After both refusals the slate still carries every rollup it was born with, its
    version has not advanced, and neither subject has been placed on the card.

    PRD: "The slate is born `DRAFT` with `nominee_count`, `independent_nominee_count`, `committed_search_fee_cents`, `revision_count`, `votes_for`, `votes_against`, `votes_abstain` and `votes_recused` all 0"

    Design: Difficulty/priority_pair_validation_conflict/interlock_safety_error_wins_over_search_fee_budget_error_on_nominee_add
    """
    world = _nominee_gate_world(client)

    validate_error(
        _nominee_add_attempt(client, world, world["interlocked_id"], 1),
        ERR_INTERLOCK_LIMIT_EXCEEDED,
        expected_status=422,
    )
    validate_error(
        _nominee_add_attempt(client, world, world["clean_id"], 1),
        ERR_SEARCH_FEE_BUDGET_EXCEEDED,
        expected_status=422,
    )

    assert_fields_equal(
        X.get_slate(client, world["slate_id"]),
        {
            "status": "DRAFT",
            "nominee_count": 0,
            "independent_nominee_count": 0,
            "independent_nominee_pct": 0.00,
            "committed_search_fee_cents": 0,
            "version": SLATE_VERSION_AT_OPEN,
        },
    )
    assert_fields_equal(
        X.get_candidate(client, world["interlocked_id"]), {"status": "SLATE_ELIGIBLE"}
    )
    assert_fields_equal(X.get_candidate(client, world["clean_id"]), {"status": "SLATE_ELIGIBLE"})


def test_neither_rejected_nominee_add_commits_a_cent_to_the_firm_ledger(client):
    """Both candidates were sourced by the same retained firm, and both refusals leave
    that firm's server-maintained ledger exactly at zero.

    PRD: "Four ledger fields on the firm are maintained by the server and never written by a client: `placed_nominee_count`, `committed_fee_cents`, `retainer_credit_applied_cents` and `net_payable_cents`, all starting at 0."

    Design: Difficulty/priority_pair_validation_conflict/interlock_safety_error_wins_over_search_fee_budget_error_on_nominee_add
    """
    world = _nominee_gate_world(client)

    validate_error(
        _nominee_add_attempt(client, world, world["interlocked_id"], 1),
        ERR_INTERLOCK_LIMIT_EXCEEDED,
        expected_status=422,
    )
    validate_error(
        _nominee_add_attempt(client, world, world["clean_id"], 1),
        ERR_SEARCH_FEE_BUDGET_EXCEEDED,
        expected_status=422,
    )

    assert_firm_ledger(X.get_firm(client, world["firm_id"]), 0, 0, 0, 0)
