"""Validation corners: boundary passes, guideline refusals and interval sanity.

Each test drives one declared refusal (or the boundary case that must NOT be
refused) and checks that the surrounding record is left exactly as it was.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_APPROVAL_THRESHOLD_NOT_MET,
    ERR_CLOCK_NOT_MONOTONIC,
    ERR_COMMITTEE_INDEPENDENCE_REQUIRED,
    ERR_CYCLE_YEAR_NOT_ADVANCED,
    ERR_DUPLICATE_RESOURCE,
    ERR_INVALID_INTERVAL,
    ERR_QUORUM_NOT_MET,
    ERR_READINESS_BELOW_THRESHOLD,
    ERR_RETIREMENT_AGE_EXCEEDED,
    ERR_SEAT_COUNT_EXCEEDED,
    ERR_SOURCE_CHANNEL_MISMATCH,
    ERR_TENURE_LIMIT_EXCEEDED,
    ERR_UNIVERSAL_PROXY_MINIMUM,
)
from test_helpers.assertions import (
    assert_fields_equal,
    assert_page,
    assert_slate_tallies,
)
from test_helpers.test_users import (
    SECRETARY,
    STAFF,
    make_committee_chair_headers,
    make_committee_member_headers,
)

# Two independent nominees out of three is 100 * 2 / 3 carried to two decimal
# places, which lands exactly on the shipped 66.67 independence floor.
FLOOR_INDEPENDENCE_PCT = 66.67

# Appointed on this date, a director has completed 15 whole years of service by
# the default clock date, which reaches the shipped 15-year tenure guideline.
TENURE_LIMIT_APPOINTED_ON = "2011-01-01"
# Born on this date, a director is exactly 75 by the default clock date, which
# reaches the shipped mandatory retirement age of 75.
RETIREMENT_AGE_BIRTH_DATE = "1951-01-01"

# One completed interview scored 1 gives an 8.00 interview component; a
# universal-proxy candidate then adds 30.00 independence, 5.00 channel and
# 10.00 board capacity.
READINESS_BELOW_FLOOR = 53.00
# One completed interview scored 5 caps the interview component at 40.00, so the
# same candidate reaches 40.00 + 30.00 + 5.00 + 10.00.
READINESS_ABOVE_FLOOR = 85.00

# One FOR ballot against a non-recused denominator of three ballots.
FAILING_APPROVAL_PCT = 33.33

# A single required item, completed, satisfies the whole required set.
COMPLETE_ONBOARDING_PCT = 100.00

# A single nominee on a one-nominee slate is 100 percent independent.
SOLE_INDEPENDENT_NOMINEE_PCT = 100.00

# The clock is moved to this instant once, and then both an earlier instant and
# this same instant are offered back to it.
CLOCK_FORWARD = "2026-09-01T00:00:00Z"
CLOCK_BACKWARDS = "2026-08-15T00:00:00Z"
# Born 1970-08-15 and appointed 2019-06-01, measured against the moved clock.
AGE_AFTER_FORWARD_MOVE = 56
TENURE_AFTER_FORWARD_MOVE = 7
# The single director on file is the only row the clock move refreshes.
RECOMPUTED_DIRECTOR_COUNT = 1

# A cycle year below the governing policy's, and one exactly equal to it.
STALE_CYCLE_YEAR = 2025
LATER_CYCLE_YEAR = 2027

# A reversed calendar window used on the assignment term and the award service
# window, and the identical instant pair used on the interview.
REVERSED_START_ON = "2026-12-31"
REVERSED_END_ON = "2026-01-01"
DEGENERATE_INSTANT = "2026-03-02T10:00:00Z"


# ---------------------------------------------------------------------------
# Local setup helpers
# ---------------------------------------------------------------------------
def _chair(client, email="dana.chair@issuer.example"):
    """A seated director plus the committee-chair headers that act as them."""
    chair = X.new_seated_director(
        client,
        full_name="Dana Chair",
        email=email,
        birth_date="1962-03-15",
        appointed_on="2019-05-01",
    )
    return chair, make_committee_chair_headers(chair["id"])


def _seated(client, name, email, **kwargs):
    return X.new_seated_director(client, full_name=name, email=email, **kwargs)


def _universal_proxy_candidate(client, interview_score):
    """Policy, chair, interviewer and one universal-proxy candidate at SLATE_ELIGIBLE.

    The policy asks for a single completed interview so the readiness arithmetic
    rests on exactly one score.
    """
    X.adopt_policy(client, min_completed_interviews=1)
    chair, chair_headers = _chair(client)
    interviewer = _seated(
        client,
        "Ivan Interviewer",
        "ivan@issuer.example",
        birth_date="1966-07-07",
        appointed_on="2020-05-01",
    )
    candidate = X.new_candidate(
        client,
        full_name="Uma Universal",
        email="uma@cand.example",
        birth_date="1974-01-01",
        source_channel="UNIVERSAL_PROXY_NOMINATION",
        shareholder_proponent_name="Activist Partners LP",
    )
    X.advance_to_slate_eligible(
        client,
        candidate["id"],
        chair_headers,
        [interviewer["id"]],
        scores=(interview_score,),
    )
    return candidate


def _slate_under_review_with_two_ballots(client):
    """A slate under committee review carrying one FOR and one AGAINST ballot.

    Returns the slate, the chair headers that record the decision, the third
    director who has not yet balloted, and the two ballots already cast.
    """
    X.adopt_policy(client)
    chair = _seated(
        client, "Cora Chair", "cora@issuer.example",
        birth_date="1962-01-01", appointed_on="2019-01-01",
    )
    member_one = _seated(
        client, "Mo Member", "mo@issuer.example",
        birth_date="1965-01-01", appointed_on="2020-01-01",
    )
    member_two = _seated(
        client, "Nia Member", "nia@issuer.example",
        birth_date="1966-01-01", appointed_on="2020-01-01",
    )
    nominee_one = _seated(
        client, "Nate Nominee", "nate@issuer.example",
        birth_date="1968-01-01", appointed_on="2021-01-01",
    )
    nominee_two = _seated(
        client, "Nora Nominee", "nora@issuer.example",
        birth_date="1969-01-01", appointed_on="2021-01-01",
    )
    slate = X.new_slate(client, cycle_year=C.CYCLE_YEAR, seat_count=9)
    X.add_incumbent_nominee(client, slate["id"], nominee_one["id"], 1)
    X.add_incumbent_nominee(client, slate["id"], nominee_two["id"], 2)
    X.submit_slate(client, slate["id"])
    chair_headers = make_committee_chair_headers(chair["id"])
    ballots = [
        X.cast_ballot(client, slate["id"], chair["id"], "FOR", chair_headers),
        X.cast_ballot(
            client,
            slate["id"],
            member_one["id"],
            "AGAINST",
            make_committee_member_headers(member_one["id"]),
        ),
    ]
    return slate, chair_headers, member_two, ballots


def _clock_moved_forward(client):
    """One seated director, with the logical clock moved forward once."""
    X.adopt_policy(client)
    director = _seated(
        client, "Cal Endar", "cal@issuer.example",
        birth_date="1970-08-15", appointed_on="2019-06-01",
    )
    moved = X.set_clock(client, CLOCK_FORWARD)
    assert_fields_equal(
        moved,
        {
            "current_utc": CLOCK_FORWARD,
            "recomputed_director_count": RECOMPUTED_DIRECTOR_COUNT,
        },
    )
    assert_fields_equal(
        X.get_director(client, director["id"]),
        {
            "age_years": AGE_AFTER_FORWARD_MOVE,
            "tenure_years": TENURE_AFTER_FORWARD_MOVE,
        },
    )
    return director


# ---------------------------------------------------------------------------
# The independence floor, met exactly
# ---------------------------------------------------------------------------
def test_two_independent_nominees_out_of_three_clear_the_independence_floor(client):
    """A slate landing exactly on the 66.67 floor reaches committee review rather
    than being refused, and the non-independent nominee copies its flag from the
    incumbent director it stands for.

    PRD: "its `independent_nominee_pct` must be at or above the policy's `independence_min_pct`, else `ERR_INDEPENDENCE_SHORTFALL`"

    Design: Corner/validations/slate_independence_exactly_at_the_floor_passes_submit_for_review
    """
    X.adopt_policy(client)
    first = _seated(
        client, "Indy One", "indy1@issuer.example",
        birth_date="1968-01-01", appointed_on="2021-01-01", is_independent=True,
    )
    second = _seated(
        client, "Indy Two", "indy2@issuer.example",
        birth_date="1969-01-01", appointed_on="2021-01-01", is_independent=True,
    )
    management = _seated(
        client, "Manny Management", "manny@issuer.example",
        birth_date="1970-01-01", appointed_on="2021-01-01",
        is_management=True, is_independent=False,
    )
    slate = X.new_slate(client, cycle_year=C.CYCLE_YEAR, seat_count=9)
    X.add_incumbent_nominee(client, slate["id"], first["id"], 1)
    X.add_incumbent_nominee(client, slate["id"], second["id"], 2)
    third_nominee = X.add_incumbent_nominee(client, slate["id"], management["id"], 3)

    reviewed = validate_success(client.submit_slate_for_review(slate["id"], STAFF), 200)

    assert_fields_equal(
        reviewed,
        {
            "status": "COMMITTEE_REVIEW",
            "nominee_count": 3,
            "independent_nominee_count": 2,
            "independent_nominee_pct": FLOOR_INDEPENDENCE_PCT,
            "independence_shortfall": False,
            "contested": False,
            "universal_proxy_applicable": False,
        },
    )
    assert_fields_equal(
        X.get_nominee(client, third_nominee["id"]), {"is_independent": False}
    )


# ---------------------------------------------------------------------------
# The tenure and retirement-age guidelines on a nominee add
# ---------------------------------------------------------------------------
def test_an_incumbent_who_reaches_the_tenure_cap_cannot_be_renominated(client):
    """An incumbent with exactly 15 completed years of service is refused, and the
    slate keeps its version and its empty nominee set.

    PRD: "guideline refuses the renomination of a sitting director whose completed years of service reach the policy's `max_tenure_years`, reported as `ERR_TENURE_LIMIT_EXCEEDED`"

    Design: Corner/validations/tenure_and_retirement_age_guidelines_each_reject_their_own_incumbent
    """
    X.adopt_policy(client)
    long_serving = _seated(
        client, "Terry Tenure", "terry@issuer.example",
        birth_date="1970-01-01", appointed_on=TENURE_LIMIT_APPOINTED_ON,
    )
    slate = X.new_slate(client, cycle_year=C.CYCLE_YEAR, seat_count=9)

    validate_error(
        client.add_slate_nominee(
            slate["id"],
            F.nominee_payload(slate["version"], 1, incumbent_director_id=long_serving["id"]),
            STAFF,
        ),
        ERR_TENURE_LIMIT_EXCEEDED,
        422,
    )

    assert_fields_equal(
        X.get_slate(client, slate["id"]),
        {"nominee_count": 0, "version": slate["version"], "status": "DRAFT"},
    )
    assert_fields_equal(
        X.get_director(client, long_serving["id"]), {"service_status": "SEATED"}
    )


def test_an_incumbent_who_reaches_the_retirement_age_cannot_be_renominated(client):
    """An incumbent who is exactly 75 at the clock date is refused on the
    retirement-age guideline, and the refusal leaves the director seated.

    PRD: "The same three tests are re-evaluated when the candidate is actually placed on a slate, but there they are hard refusals rather than recorded outcomes, surfacing as `ERR_INTERLOCK_LIMIT_EXCEEDED`, `ERR_OVERBOARDING_LIMIT_EXCEEDED` and `ERR_RETIREMENT_AGE_EXCEEDED`."

    Design: Corner/validations/tenure_and_retirement_age_guidelines_each_reject_their_own_incumbent
    """
    X.adopt_policy(client)
    retiring = _seated(
        client, "Rita Retire", "rita@issuer.example",
        birth_date=RETIREMENT_AGE_BIRTH_DATE, appointed_on="2022-01-01",
    )
    slate = X.new_slate(client, cycle_year=C.CYCLE_YEAR, seat_count=9)

    validate_error(
        client.add_slate_nominee(
            slate["id"],
            F.nominee_payload(slate["version"], 1, incumbent_director_id=retiring["id"]),
            STAFF,
        ),
        ERR_RETIREMENT_AGE_EXCEEDED,
        422,
    )

    assert_fields_equal(
        X.get_slate(client, slate["id"]),
        {"nominee_count": 0, "version": slate["version"], "status": "DRAFT"},
    )
    assert_fields_equal(
        X.get_director(client, retiring["id"]), {"service_status": "SEATED"}
    )


# ---------------------------------------------------------------------------
# The all-independent committee charter
# ---------------------------------------------------------------------------
def test_an_all_independent_committee_refuses_a_non_independent_director(client):
    """A committee chartered all-independent refuses the assignment of a management
    director, and neither its version nor its seat count moves.

    PRD: "When the committee's `requires_all_independent` is true, the assigned director's `is_independent` must be true, else `ERR_COMMITTEE_INDEPENDENCE_REQUIRED`."

    Design: Corner/validations/an_all_independent_committee_refuses_a_non_independent_assignment
    """
    X.adopt_policy(client)
    management = _seated(
        client, "Manny Management", "manny@issuer.example",
        birth_date="1970-01-01", appointed_on="2021-01-01",
        is_management=True, is_independent=False,
    )
    committee = X.new_committee(
        client,
        code="AUDIT",
        name="Audit Committee",
        authorized_seats=3,
        min_seats=1,
        requires_all_independent=True,
    )

    validate_error(
        client.create_assignment(
            committee["id"],
            F.assignment_payload(management["id"], committee["version"]),
            SECRETARY,
        ),
        ERR_COMMITTEE_INDEPENDENCE_REQUIRED,
        422,
    )

    assert_fields_equal(
        X.get_committee(client, committee["id"]),
        {"version": committee["version"], "filled_seats": 0},
    )
    assert_page(client.list_assignments(SECRETARY), expected_total=0)


def test_a_committee_without_the_flag_accepts_the_same_non_independent_director(client):
    """The independence requirement is conditional on the committee's own charter, so
    the identical director is proposed successfully onto a committee without the flag.

    PRD: "When the committee's `requires_all_independent` is true, the assigned director's `is_independent` must be true, else `ERR_COMMITTEE_INDEPENDENCE_REQUIRED`."

    Design: Corner/validations/an_all_independent_committee_refuses_a_non_independent_assignment
    """
    X.adopt_policy(client)
    management = _seated(
        client, "Manny Management", "manny@issuer.example",
        birth_date="1970-01-01", appointed_on="2021-01-01",
        is_management=True, is_independent=False,
    )
    committee = X.new_committee(
        client,
        code="RISK",
        name="Risk Committee",
        authorized_seats=3,
        min_seats=1,
        requires_all_independent=False,
    )

    assignment = validate_success(
        client.create_assignment(
            committee["id"],
            F.assignment_payload(management["id"], committee["version"]),
            SECRETARY,
        ),
        201,
    )

    assert_fields_equal(assignment, {"status": "PROPOSED", "seat_role": "MEMBER"})
    assert_fields_equal(
        X.get_committee(client, committee["id"]),
        {"filled_seats": 0, "status": "UNDER_STRENGTH"},
    )


# ---------------------------------------------------------------------------
# The readiness floor on a nominee add
# ---------------------------------------------------------------------------
def test_a_candidate_below_the_readiness_floor_cannot_be_nominated(client):
    """A fully cleared candidate whose readiness composite is 53.00 is still refused
    at the 60.00 floor, and the refusal leaves both the candidate and the slate alone.

    PRD: "must carry a `readiness_score` at or above the policy's `readiness_min_score`, else `ERR_READINESS_BELOW_THRESHOLD`"

    Design: Corner/validations/a_candidate_below_the_readiness_floor_cannot_be_nominated
    """
    candidate = _universal_proxy_candidate(client, 1)
    slate = X.new_slate(client, cycle_year=C.CYCLE_YEAR, seat_count=9)

    validate_error(
        client.add_slate_nominee(
            slate["id"],
            F.nominee_payload(slate["version"], 1, candidate_id=candidate["id"]),
            STAFF,
        ),
        ERR_READINESS_BELOW_THRESHOLD,
        422,
    )

    assert_fields_equal(
        X.get_candidate(client, candidate["id"]),
        {
            "readiness_score": READINESS_BELOW_FLOOR,
            "status": "SLATE_ELIGIBLE",
            "independence_result": "INDEPENDENT",
        },
    )
    assert_fields_equal(
        X.get_slate(client, slate["id"]),
        {"nominee_count": 0, "version": slate["version"], "status": "DRAFT"},
    )


# ---------------------------------------------------------------------------
# Quorum ahead of the approval percentage
# ---------------------------------------------------------------------------
def test_quorum_is_reported_before_the_approval_arithmetic_is_consulted(client):
    """A decision taken on two ballots against a quorum of three is refused for
    quorum, and no ballot is voided by the refusal.

    PRD: "Quorum is checked before the approval percentage, so a decision taken on too few ballots reports `ERR_QUORUM_NOT_MET`, and an adequately attended vote that falls short reports `ERR_APPROVAL_THRESHOLD_NOT_MET`."

    Design: Corner/validations/quorum_is_checked_before_approval_and_then_approval_fails_on_its_own
    """
    slate, chair_headers, _third_director, ballots = _slate_under_review_with_two_ballots(
        client
    )

    validate_error(
        client.decide_slate(slate["id"], F.decision_payload("APPROVE"), chair_headers),
        ERR_QUORUM_NOT_MET,
        422,
    )

    current = X.get_slate(client, slate["id"])
    assert_fields_equal(
        current,
        {"status": "COMMITTEE_REVIEW", "quorum_met": False, "revision_count": 0},
    )
    for ballot in ballots:
        assert_fields_equal(
            validate_success(client.get_vote(ballot["id"], STAFF), 200), {"status": "CAST"}
        )


def test_an_attended_vote_that_falls_short_reports_the_approval_threshold(client):
    """Once a third ballot carries the slate over quorum, the same decision is refused
    on the approval percentage instead, at a tally of one FOR against two AGAINST.

    PRD: "Quorum is checked before the approval percentage, so a decision taken on too few ballots reports `ERR_QUORUM_NOT_MET`, and an adequately attended vote that falls short reports `ERR_APPROVAL_THRESHOLD_NOT_MET`."

    Design: Corner/validations/quorum_is_checked_before_approval_and_then_approval_fails_on_its_own
    """
    slate, chair_headers, third_director, ballots = _slate_under_review_with_two_ballots(
        client
    )
    third_ballot = X.cast_ballot(
        client,
        slate["id"],
        third_director["id"],
        "AGAINST",
        make_committee_member_headers(third_director["id"]),
    )

    assert_slate_tallies(
        X.get_slate(client, slate["id"]),
        votes_for=1,
        votes_against=2,
        votes_abstain=0,
        votes_recused=0,
        approval_pct=FAILING_APPROVAL_PCT,
        quorum_met=True,
    )

    validate_error(
        client.decide_slate(slate["id"], F.decision_payload("APPROVE"), chair_headers),
        ERR_APPROVAL_THRESHOLD_NOT_MET,
        422,
    )

    assert_fields_equal(
        X.get_slate(client, slate["id"]),
        {"status": "COMMITTEE_REVIEW", "revision_count": 0},
    )
    for ballot in ballots + [third_ballot]:
        assert_fields_equal(
            validate_success(client.get_vote(ballot["id"], STAFF), 200), {"status": "CAST"}
        )


# ---------------------------------------------------------------------------
# The universal-proxy minimum on a contested slate
# ---------------------------------------------------------------------------
def test_a_contested_slate_with_one_nominee_fails_the_universal_proxy_minimum(client):
    """A single universal-proxy nominee makes the slate contested and therefore
    subject to the full alternative-board minimum, which one nominee cannot meet
    even though the independence floor is comfortably satisfied.

    PRD: "the slate must nominate at least the policy's `authorized_seats` less one, so the company's universal proxy card offers shareholders a full alternative board; a shorter contested slate is refused with `ERR_UNIVERSAL_PROXY_MINIMUM`"

    Design: Corner/validations/a_contested_slate_with_one_nominee_fails_the_universal_proxy_minimum
    """
    candidate = _universal_proxy_candidate(client, 5)
    assert_fields_equal(
        X.get_candidate(client, candidate["id"]),
        {"readiness_score": READINESS_ABOVE_FLOOR, "status": "SLATE_ELIGIBLE"},
    )
    slate = X.new_slate(client, cycle_year=C.CYCLE_YEAR, seat_count=9)
    X.add_candidate_nominee(client, slate["id"], candidate["id"], 1)

    validate_error(
        client.submit_slate_for_review(slate["id"], STAFF),
        ERR_UNIVERSAL_PROXY_MINIMUM,
        422,
    )

    assert_fields_equal(
        X.get_slate(client, slate["id"]),
        {
            "status": "DRAFT",
            "contested": True,
            "universal_proxy_applicable": True,
            "nominee_count": 1,
            "independent_nominee_pct": SOLE_INDEPENDENT_NOMINEE_PCT,
            "independence_shortfall": False,
        },
    )


# ---------------------------------------------------------------------------
# The authorized-seat ceiling on seating
# ---------------------------------------------------------------------------
def test_seating_beyond_the_authorized_seat_count_is_refused(client):
    """With more directors already seated than the charter authorizes, a director
    whose programme is complete is refused for seat count rather than for onboarding,
    and stays in onboarding.

    PRD: "The count of directors already at `SEATED` may not exceed the policy's `authorized_seats`, else `ERR_SEAT_COUNT_EXCEEDED`"

    Design: Corner/validations/seating_one_more_director_than_authorized_seats_is_refused
    """
    X.adopt_policy(client, authorized_seats=1)
    first_seated = _seated(
        client, "Solo Seat", "solo@issuer.example",
        birth_date="1968-01-01", appointed_on="2021-01-01",
    )
    second_seated = _seated(
        client, "Extra Seat", "extra@issuer.example",
        birth_date="1969-01-01", appointed_on="2021-01-01",
    )
    waiting = X.new_onboarding_director(
        client,
        full_name="Wait List",
        email="waitlist@issuer.example",
        birth_date="1972-01-01",
        appointed_on="2026-07-01",
    )
    item = X.new_onboarding_item(
        client,
        waiting["id"],
        module_code="BUSINESS_ORIENTATION_101",
        category="BUSINESS_ORIENTATION",
        is_required=True,
        credit_hours=2.0,
        due_on="2026-09-30",
    )
    X.complete_item(client, item["id"])

    validate_error(
        client.seat_director(waiting["id"], SECRETARY), ERR_SEAT_COUNT_EXCEEDED, 422
    )

    assert_fields_equal(
        X.get_director(client, waiting["id"]),
        {
            "onboarding_status": "COMPLETE",
            "onboarding_completion_pct": COMPLETE_ONBOARDING_PCT,
            "service_status": "ONBOARDING",
        },
    )
    for director in (first_seated, second_seated):
        assert_fields_equal(
            X.get_director(client, director["id"]), {"service_status": "SEATED"}
        )


# ---------------------------------------------------------------------------
# The monotonic logical clock
# ---------------------------------------------------------------------------
def test_the_logical_clock_refuses_to_move_backwards(client):
    """An instant earlier than the current logical clock is refused, and the director
    figures that ride on the clock are not recomputed back down.

    PRD: "The clock is monotonic: a `current_utc` that is not strictly after the current logical clock instant is refused with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422)."

    Design: Corner/validations/the_logical_clock_refuses_to_move_backwards_or_stand_still
    """
    director = _clock_moved_forward(client)

    validate_error(
        client.set_clock(F.clock_payload(CLOCK_BACKWARDS), SECRETARY),
        ERR_CLOCK_NOT_MONOTONIC,
        422,
    )

    assert_fields_equal(
        X.get_director(client, director["id"]),
        {
            "age_years": AGE_AFTER_FORWARD_MOVE,
            "tenure_years": TENURE_AFTER_FORWARD_MOVE,
        },
    )


def test_the_logical_clock_refuses_to_stand_still(client):
    """Offering the clock the instant it already holds is refused too, because the
    comparison is strictly after rather than at or after.

    PRD: "The clock is monotonic: a `current_utc` that is not strictly after the current logical clock instant is refused with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422)."

    Design: Corner/validations/the_logical_clock_refuses_to_move_backwards_or_stand_still
    """
    director = _clock_moved_forward(client)

    validate_error(
        client.set_clock(F.clock_payload(CLOCK_FORWARD), SECRETARY),
        ERR_CLOCK_NOT_MONOTONIC,
        422,
    )

    assert_fields_equal(
        X.get_director(client, director["id"]),
        {
            "age_years": AGE_AFTER_FORWARD_MOVE,
            "tenure_years": TENURE_AFTER_FORWARD_MOVE,
        },
    )


# ---------------------------------------------------------------------------
# Cycle-year advancement on a slate and on a policy
# ---------------------------------------------------------------------------
def test_a_slate_below_the_policy_cycle_year_is_refused_but_an_equal_one_opens(client):
    """A slate for a cycle behind the governing policy is refused, while a slate for
    exactly the policy's own cycle year opens, because the test is at or above.

    PRD: "The new slate's `cycle_year` must be greater than or equal to the governing policy's `cycle_year`, else `ERR_CYCLE_YEAR_NOT_ADVANCED`"

    Design: Corner/validations/a_slate_or_policy_that_does_not_advance_the_cycle_is_refused
    """
    X.adopt_policy(client)

    validate_error(
        client.create_slate(
            F.slate_payload(cycle_year=STALE_CYCLE_YEAR, seat_count=9), SECRETARY
        ),
        ERR_CYCLE_YEAR_NOT_ADVANCED,
        422,
    )

    opened = validate_success(
        client.create_slate(
            F.slate_payload(cycle_year=C.CYCLE_YEAR, seat_count=9), SECRETARY
        ),
        201,
    )
    assert_fields_equal(opened, {"cycle_year": C.CYCLE_YEAR, "status": "DRAFT"})
    assert_page(client.list_slates(SECRETARY), expected_total=1)


def test_a_policy_whose_effective_from_does_not_advance_is_refused(client):
    """A second adoption carrying the incumbent policy's own effective_from is refused,
    and the policy already in force keeps its ACTIVE status.

    PRD: "the currently `ACTIVE` policy's `effective_from`, else `ERR_CYCLE_YEAR_NOT_ADVANCED`, and only one `ACTIVE` policy may hold a given `cycle_year`."

    Design: Corner/validations/a_slate_or_policy_that_does_not_advance_the_cycle_is_refused
    """
    policy = X.adopt_policy(client)

    validate_error(
        client.adopt_policy(
            F.policy_payload(
                cycle_year=LATER_CYCLE_YEAR, effective_from=C.POLICY_EFFECTIVE_FROM
            ),
            SECRETARY,
        ),
        ERR_CYCLE_YEAR_NOT_ADVANCED,
        422,
    )

    assert_fields_equal(
        validate_success(client.get_policy(policy["id"], SECRETARY), 200),
        {"status": "ACTIVE", "cycle_year": C.CYCLE_YEAR},
    )
    assert_page(client.list_policies(SECRETARY), expected_total=1)


# ---------------------------------------------------------------------------
# Declared uniqueness keys
# ---------------------------------------------------------------------------
def test_a_second_committee_reusing_the_name_is_refused(client):
    """The committee name is a uniqueness key in its own right, so reusing it is
    refused even when the charter code is different, and nothing is created.

    PRD: "A committee is chartered with a `code` of `AUDIT`, `COMPENSATION`, `NOMINATING_GOVERNANCE` or `RISK` that is unique across committees, a `name` that is also unique across committees"

    Design: Corner/validations/uniqueness_keys_reject_a_duplicate_committee_name_and_category_code
    """
    X.adopt_policy(client)
    X.new_committee(
        client, code="AUDIT", name="Audit Committee", authorized_seats=3, min_seats=1
    )

    validate_error(
        client.create_committee(
            F.committee_payload(
                code="RISK", name="Audit Committee", authorized_seats=3, min_seats=1
            ),
            SECRETARY,
        ),
        ERR_DUPLICATE_RESOURCE,
        409,
    )

    rows, _meta = assert_page(client.list_committees(SECRETARY), expected_total=1)
    assert_fields_equal(rows[0], {"code": "AUDIT", "name": "Audit Committee"})


def test_a_second_skill_category_reusing_the_code_is_refused(client):
    """The skill-category code is the uniqueness key, so a second registration reusing
    it is refused even under a different name, and the original name survives.

    PRD: "once registered they are never edited, and duplicate `code` values are refused with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/uniqueness_keys_reject_a_duplicate_committee_name_and_category_code
    """
    X.adopt_policy(client)
    X.new_skill_category(
        client,
        code="CYBER",
        name="Cybersecurity Oversight",
        strategic_weight=0.80,
        required_min_directors=2,
    )

    validate_error(
        client.create_skill_category(
            F.skill_category_payload(
                code="CYBER",
                name="Cyber Risk",
                strategic_weight=0.50,
                required_min_directors=1,
            ),
            STAFF,
        ),
        ERR_DUPLICATE_RESOURCE,
        409,
    )

    rows, _meta = assert_page(client.list_skill_categories(STAFF), expected_total=1)
    assert_fields_equal(rows[0], {"code": "CYBER", "name": "Cybersecurity Oversight"})


# ---------------------------------------------------------------------------
# Source-channel coherence
# ---------------------------------------------------------------------------
def _screen_passed_candidate(client):
    """A candidate whose independence is settled, ready to be interviewed."""
    X.adopt_policy(client)
    chair, chair_headers = _chair(client)
    candidate = X.new_candidate(
        client,
        full_name="Priya Proposal",
        email="priya@cand.example",
        birth_date="1975-02-02",
        source_channel="SHAREHOLDER_PROPOSAL",
        shareholder_proponent_name="Meridian Pension Fund",
    )
    X.advance_to_screen_passed(client, candidate["id"], chair_headers)
    return chair, candidate


def test_a_search_firm_candidate_without_its_firm_identifier_is_refused(client):
    """The firm channel makes the firm identifier mandatory, so sourcing without it is
    refused and no candidate row is left behind.

    PRD: "When the channel is `SEARCH_FIRM`, a `search_firm_id` is required and `referring_director_id` must be absent."

    Design: Corner/validations/source_channel_coherence_rejects_missing_and_forbidden_subject_ids
    """
    X.adopt_policy(client)

    validate_error(
        client.create_candidate(
            F.candidate_payload(
                full_name="Frank Firmless",
                email="frank@cand.example",
                birth_date="1975-03-03",
                source_channel="SEARCH_FIRM",
            ),
            STAFF,
        ),
        ERR_SOURCE_CHANNEL_MISMATCH,
        422,
    )

    assert_page(client.list_candidates(STAFF), expected_total=0)


def test_a_shareholder_proposal_candidate_carrying_a_firm_identifier_is_refused(client):
    """A shareholder-proposed candidate must carry neither identifier field, so a
    stray firm identifier is refused even though the proponent name is present.

    PRD: "When the channel is `SHAREHOLDER_PROPOSAL` or `UNIVERSAL_PROXY_NOMINATION`, a `shareholder_proponent_name` is required and both identifier fields must be absent. Any other combination is refused with `ERR_SOURCE_CHANNEL_MISMATCH`."

    Design: Corner/validations/source_channel_coherence_rejects_missing_and_forbidden_subject_ids
    """
    X.adopt_policy(client)
    firm = X.new_search_firm(
        client, name="Beacon Search Partners", contact_email="partners@beacon.example"
    )

    validate_error(
        client.create_candidate(
            F.candidate_payload(
                full_name="Sam Straddle",
                email="sam@cand.example",
                birth_date="1975-04-04",
                source_channel="SHAREHOLDER_PROPOSAL",
                shareholder_proponent_name="Meridian Pension Fund",
                search_firm_id=firm["id"],
            ),
            STAFF,
        ),
        ERR_SOURCE_CHANNEL_MISMATCH,
        422,
    )

    assert_page(client.list_candidates(STAFF), expected_total=0)


def test_a_nominee_naming_both_a_candidate_and_an_incumbent_is_refused(client):
    """A nominee row names exactly one subject, so naming both is refused before the
    candidate's own pipeline status is ever consulted, and the slate is untouched.

    PRD: "The candidate's `source_channel` agrees with the supplied source identifiers, and a slate nominee names exactly one subject; a violation yields `ERR_SOURCE_CHANNEL_MISMATCH` (422)."

    Design: Corner/validations/source_channel_coherence_rejects_missing_and_forbidden_subject_ids
    """
    X.adopt_policy(client)
    incumbent = _seated(
        client,
        "Ida Incumbent",
        "ida@issuer.example",
        birth_date="1965-05-05",
        appointed_on="2020-01-01",
    )
    candidate = X.new_candidate(
        client,
        full_name="Priya Proposal",
        email="priya@cand.example",
        birth_date="1975-02-02",
        source_channel="SHAREHOLDER_PROPOSAL",
        shareholder_proponent_name="Meridian Pension Fund",
    )
    slate = X.new_slate(client, cycle_year=C.CYCLE_YEAR, seat_count=3)

    validate_error(
        client.add_slate_nominee(
            slate["id"],
            F.nominee_payload(
                slate["version"],
                1,
                candidate_id=candidate["id"],
                incumbent_director_id=incumbent["id"],
            ),
            STAFF,
        ),
        ERR_SOURCE_CHANNEL_MISMATCH,
        422,
    )

    assert_fields_equal(
        X.get_slate(client, slate["id"]),
        {"nominee_count": 0, "version": slate["version"], "status": "DRAFT"},
    )
    assert_fields_equal(X.get_candidate(client, candidate["id"]), {"status": "SOURCED"})
    assert_page(client.list_candidates(STAFF), expected_total=1)


# ---------------------------------------------------------------------------
# Interval sanity on three different endpoints
# ---------------------------------------------------------------------------
def test_an_interview_window_that_starts_and_ends_at_the_same_instant_is_refused(client):
    """The interview window is measured strictly, so a zero-length window is refused
    and no session is scheduled.

    PRD: "The `end_at` must be strictly after the `start_at`, else `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/degenerate_and_reversed_intervals_are_rejected_on_three_endpoints
    """
    chair, candidate = _screen_passed_candidate(client)

    validate_error(
        client.schedule_interview(
            F.interview_payload(
                candidate["id"],
                chair["id"],
                start_at=DEGENERATE_INSTANT,
                end_at=DEGENERATE_INSTANT,
            ),
            STAFF,
        ),
        ERR_INVALID_INTERVAL,
        422,
    )

    assert_page(client.list_interviews(STAFF), expected_total=0)
    assert_fields_equal(
        X.get_candidate(client, candidate["id"]), {"status": "SCREEN_PASSED"}
    )


def test_a_committee_term_that_ends_before_it_starts_is_refused(client):
    """A reversed committee term is refused, so the committee neither fills a seat nor
    moves its version.

    PRD: "The `term_end_on` must be on or after the `term_start_on`, else `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/degenerate_and_reversed_intervals_are_rejected_on_three_endpoints
    """
    X.adopt_policy(client)
    director = _seated(
        client,
        "Mona Member",
        "mona@issuer.example",
        birth_date="1968-06-06",
        appointed_on="2021-01-01",
    )
    committee = X.new_committee(
        client, code="AUDIT", name="Audit Committee", authorized_seats=4, min_seats=1
    )

    validate_error(
        client.create_assignment(
            committee["id"],
            F.assignment_payload(
                director["id"],
                committee["version"],
                term_start_on=REVERSED_START_ON,
                term_end_on=REVERSED_END_ON,
            ),
            SECRETARY,
        ),
        ERR_INVALID_INTERVAL,
        422,
    )

    assert_fields_equal(
        X.get_committee(client, committee["id"]),
        {"filled_seats": 0, "version": committee["version"]},
    )
    assert_page(client.list_assignments(SECRETARY), expected_total=0)


def test_an_award_service_window_that_ends_before_it_starts_is_refused(client):
    """A reversed service window on a compensation award is refused, so no award row
    is created for the director.

    PRD: "The `service_end_on` must be on or after the `service_start_on`, else `ERR_INVALID_INTERVAL`"

    Design: Corner/validations/degenerate_and_reversed_intervals_are_rejected_on_three_endpoints
    """
    X.adopt_policy(client)
    director = _seated(
        client,
        "Percy Paid",
        "percy@issuer.example",
        birth_date="1969-07-07",
        appointed_on="2021-02-01",
    )

    validate_error(
        client.create_comp_award(
            director["id"],
            F.comp_award_payload(
                cycle_year=C.CYCLE_YEAR,
                service_start_on=REVERSED_START_ON,
                service_end_on=REVERSED_END_ON,
            ),
            SECRETARY,
        ),
        ERR_INVALID_INTERVAL,
        422,
    )

    assert_page(client.list_comp_awards(SECRETARY), expected_total=0)
