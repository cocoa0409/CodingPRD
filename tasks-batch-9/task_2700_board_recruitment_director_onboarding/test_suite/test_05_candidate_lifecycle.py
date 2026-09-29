"""The candidate loop back into screening: NOMINATED, deferred, then screened again.

SCREENING is visited twice.  The second visit is reached backwards, through the
void of a nominee row, and it is gated on a later cycle being in force, so the
reopen only lands once a 2027 policy has superseded the 2026 one.
"""
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import fixtures as X
from test_helpers.api_errors import ERR_CANDIDATE_STATE_INVALID
from test_helpers.assertions import assert_fields_equal, assert_page
from test_helpers.test_users import SECRETARY, STAFF, make_committee_chair_headers

# The cycle the candidate is nominated in, and the cycle that unlocks the reopen.
DEFERRED_CYCLE_YEAR = 2026
REOPEN_CYCLE_YEAR = 2027
CYCLE_2026_EFFECTIVE_FROM = "2026-01-01T00:00:00Z"
CYCLE_2027_EFFECTIVE_FROM = "2027-01-01T00:00:00Z"

# One completed interview is enough to close the interview stage in this cycle.
MIN_COMPLETED_INTERVIEWS = 1

# The slate stands nine seats, so a single nominee is never a seat-count problem.
SLATE_SEAT_COUNT = 9
BALLOT_ORDER = 1

# A screen with every factual field at its stated default value.
CLEAN_SCREEN = dict(
    payments_to_company_cents=0,
    recipient_gross_revenue_cents=0,
    family_member_employed=False,
    auditor_affiliation=False,
    charitable_contributions_cents=0,
    company_gross_revenue_cents=0,
)


def _nominated_in_2026(client):
    """Drive one shareholder-proposal candidate all the way to NOMINATED for 2026.

    Returns the ids the tests need: the 2026 policy, the chair's headers, the
    candidate, its first (determined) screen, the slate and the nominee row.
    """
    policy_2026 = X.adopt_policy(
        client,
        cycle_year=DEFERRED_CYCLE_YEAR,
        effective_from=CYCLE_2026_EFFECTIVE_FROM,
        min_completed_interviews=MIN_COMPLETED_INTERVIEWS,
    )
    chair = X.new_seated_director(
        client,
        full_name="Dana Chair",
        email="dana.chair@issuer.example",
        birth_date="1962-03-15",
        appointed_on="2019-05-01",
    )
    interviewer = X.new_seated_director(
        client,
        full_name="Ivan Interviewer",
        email="ivan@issuer.example",
        birth_date="1966-07-07",
        appointed_on="2020-05-01",
    )
    chair_headers = make_committee_chair_headers(chair["id"])

    candidate = X.new_candidate(
        client,
        full_name="Lena Looper",
        email="lena@cand.example",
        birth_date="1973-11-11",
        source_channel="SHAREHOLDER_PROPOSAL",
        shareholder_proponent_name="Cedar Ridge Capital",
    )
    first_screen = X.screen_candidate(
        client, candidate["id"], chair_headers, **CLEAN_SCREEN
    )
    X.run_interviews(client, candidate["id"], [interviewer["id"]], [4])
    X.record_reference_check(
        client, candidate["id"], reference_count=3, adverse_findings=False
    )
    X.run_conflict_clearance(client, candidate["id"], chair_headers)

    slate = X.new_slate(
        client, cycle_year=DEFERRED_CYCLE_YEAR, seat_count=SLATE_SEAT_COUNT
    )
    nominee = X.add_candidate_nominee(
        client, slate["id"], candidate["id"], BALLOT_ORDER
    )
    return {
        "policy_2026": policy_2026,
        "chair_headers": chair_headers,
        "candidate": candidate,
        "first_screen": first_screen,
        "slate": slate,
        "nominee": nominee,
    }


def _void(client, nominee_id):
    return validate_success(client.void_slate_nominee(nominee_id, STAFF), 200)


def _adopt_2027(client):
    return X.adopt_policy(
        client,
        cycle_year=REOPEN_CYCLE_YEAR,
        effective_from=CYCLE_2027_EFFECTIVE_FROM,
        min_completed_interviews=MIN_COMPLETED_INTERVIEWS,
    )


def _reopen_screening(client, candidate_id):
    return validate_success(client.reopen_screening(candidate_id, STAFF), 200)


def test_voiding_the_nominee_row_stamps_it_voided_at_the_clock_instant(client):
    """The backward edge out of NOMINATED starts at the nominee row: the void moves it to
    VOIDED and records the instant it left the card.

    PRD: "The row becomes `VOIDED` with `voided_at` set to the logical clock instant"

    Design: Difficulty/non_linear_state_machine/candidate_cross_cycle_loop_nominated_to_deferred_back_to_screening
    """
    world = _nominated_in_2026(client)

    voided = _void(client, world["nominee"]["id"])

    assert voided["status"] == "VOIDED"
    assert voided["voided_at"] is not None, "voided_at must carry the clock instant"


def test_voiding_the_only_nominee_empties_the_slate_rollups(client):
    """With its single nominee gone the slate re-derives an empty counted set, and an empty
    slate is never an independence shortfall.

    PRD: "the slate re-derives `nominee_count`, `independent_nominee_count`, `independent_nominee_pct`, `independence_shortfall`, `committed_search_fee_cents`, `contested` and `universal_proxy_applicable`"

    Design: Difficulty/non_linear_state_machine/candidate_cross_cycle_loop_nominated_to_deferred_back_to_screening
    """
    world = _nominated_in_2026(client)

    _void(client, world["nominee"]["id"])

    assert_fields_equal(
        X.get_slate(client, world["slate"]["id"]),
        {
            "nominee_count": 0,
            "independent_nominee_count": 0,
            "independent_nominee_pct": 0.00,
            "independence_shortfall": False,
            "status": "DRAFT",
        },
    )


def test_the_deferred_candidate_cannot_reopen_inside_the_cycle_that_deferred_them(client):
    """The void defers the candidate against cycle 2026, and while the 2026 policy still
    governs the reopen is refused, so the loop is genuinely cross-cycle.

    PRD: "so a candidate deferred in one cycle cannot be reopened inside that same cycle; a premature attempt is refused with `ERR_CANDIDATE_STATE_INVALID`"

    Design: Difficulty/non_linear_state_machine/candidate_cross_cycle_loop_nominated_to_deferred_back_to_screening
    """
    world = _nominated_in_2026(client)

    _void(client, world["nominee"]["id"])

    assert_fields_equal(
        X.get_candidate(client, world["candidate"]["id"]),
        {"status": "DEFERRED", "deferred_cycle_year": DEFERRED_CYCLE_YEAR},
    )
    validate_error(
        client.reopen_screening(world["candidate"]["id"], STAFF),
        ERR_CANDIDATE_STATE_INVALID,
        409,
    )


def test_adopting_the_2027_policy_supersedes_the_cycle_that_deferred_the_candidate(client):
    """Adoption of the next cycle's policy is what unlocks the loop: the 2026 row is
    superseded and the 2027 row becomes the governing policy.

    PRD: "every prior policy whose `status` is `ACTIVE` becomes `SUPERSEDED`, and the new row is created `ACTIVE` and immediately becomes the governing policy"

    Design: Difficulty/non_linear_state_machine/candidate_cross_cycle_loop_nominated_to_deferred_back_to_screening
    """
    world = _nominated_in_2026(client)
    _void(client, world["nominee"]["id"])

    policy_2027 = _adopt_2027(client)

    assert_fields_equal(
        validate_success(client.get_policy(world["policy_2026"]["id"], SECRETARY), 200),
        {"status": "SUPERSEDED", "cycle_year": DEFERRED_CYCLE_YEAR},
    )
    assert_fields_equal(
        validate_success(client.get_policy(policy_2027["id"], SECRETARY), 200),
        {"status": "ACTIVE", "cycle_year": REOPEN_CYCLE_YEAR},
    )


def test_the_reopen_returns_the_candidate_to_screening_on_a_fresh_draft_screen(client):
    """Second visit to SCREENING: the reopen resets the independence verdict and the round
    counter and opens a brand-new draft screen alongside the old one.

    PRD: "a fresh screen is created in `DRAFT`, `independence_result` resets to `PENDING` and `interview_round` resets to 0"

    Design: Difficulty/non_linear_state_machine/candidate_cross_cycle_loop_nominated_to_deferred_back_to_screening
    """
    world = _nominated_in_2026(client)
    _void(client, world["nominee"]["id"])
    _adopt_2027(client)

    _reopen_screening(client, world["candidate"]["id"])

    assert_fields_equal(
        X.get_candidate(client, world["candidate"]["id"]),
        {
            "status": "SCREENING",
            "independence_result": "PENDING",
            "interview_round": 0,
        },
    )
    screens, _ = assert_page(
        client.list_candidate_screens(world["candidate"]["id"], STAFF), expected_total=2
    )
    fresh = [row for row in screens if row["id"] != world["first_screen"]["id"]]
    assert len(fresh) == 1, "the reopen must add exactly one screen"
    assert_fields_equal(fresh[0], {"status": "DRAFT", "determination": "PENDING"})


def test_the_first_determination_stays_on_the_file_after_the_reopen(client):
    """The screen that carried the candidate to NOMINATED is history, not governing: its
    determination and the standard frozen onto it survive the reopen untouched.

    PRD: "A screen that was submitted under the `BRIGHT_LINE` standard keeps `standard_applied` at `BRIGHT_LINE` forever"

    Design: Difficulty/non_linear_state_machine/candidate_cross_cycle_loop_nominated_to_deferred_back_to_screening
    """
    world = _nominated_in_2026(client)
    _void(client, world["nominee"]["id"])
    _adopt_2027(client)

    _reopen_screening(client, world["candidate"]["id"])

    assert_fields_equal(
        X.get_screen(client, world["first_screen"]["id"]),
        {
            "status": "DETERMINED_INDEPENDENT",
            "determination": "INDEPENDENT",
            "standard_applied": "BRIGHT_LINE",
        },
    )
