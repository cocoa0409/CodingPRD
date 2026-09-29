"""Integer and empty-set boundaries: the overboarding limit, and empty denominators.

The first half pins both sides of one off-by-one integer edge on the outside-board
count.  The second half exercises two aggregates whose denominator is empty before
any row exists, where the answer is a defined zero rather than a division.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_INDEPENDENCE_SHORTFALL,
    ERR_OVERBOARDING_LIMIT_EXCEEDED,
)
from test_helpers.assertions import assert_fields_equal, assert_gap_row
from test_helpers.test_users import STAFF, make_committee_chair_headers

# One completed interview is enough for a reference check, so the pipeline stays short.
MIN_COMPLETED_INTERVIEWS = 1

# The shipped policy allows four public boards in total for a director who is not a
# sitting chief executive, so three outside seats sit exactly on the edge and four
# are one too many: 3 + 1 lands on the limit of 4, while 4 + 1 exceeds it.
BOARDS_ON_THE_LIMIT = 3
BOARDS_OVER_THE_LIMIT = 4

# Nine seats stand for election, so the seat-count gate never fires first.
SLATE_SEAT_COUNT = 9

# The single category used for the empty-board gap arithmetic.
CATEGORY_CODE = "CYBER_RISK"
CATEGORY_STRATEGIC_WEIGHT = 0.75
CATEGORY_REQUIRED_MIN_DIRECTORS = 2

# With no director in the population the coverage count is 0, so the whole
# required_min_directors of 2 becomes the gap, and 2 * 0.75 * the 1.5 risk-oversight
# multiplier is the weighted figure and, being the only category, the board index.
EXPECTED_GAP = 2
EXPECTED_WEIGHTED_GAP = 2.25
EXPECTED_BOARD_GAP_INDEX = 2.25
EMPTY_BOARD_GAP_INDEX = 0.00


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


def _overboarding_boundary_world(client):
    """Two cleared candidates, one on three outside public boards and one on four.

    Both clear conflicts before any outside seat is recorded, so the board counts
    are first weighed against the limit at the nominee add.  Neither the chair nor
    the interviewer holds an outside seat, so no shared board is ever in play.
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
        full_name="Ivan Interviewer",
        email="ivan@issuer.example",
        birth_date="1966-07-07",
        appointed_on="2020-05-01",
    )

    companies = X.new_public_companies(client, BOARDS_OVER_THE_LIMIT)

    on_the_limit = _proposal_candidate(
        client, "Priya Pass", "priya@cand.example", "1972-04-02"
    )
    X.advance_to_slate_eligible(
        client, on_the_limit["id"], chair_headers, [interviewer["id"]], scores=(4,), first_slot=0
    )
    over_the_limit = _proposal_candidate(
        client, "Quinn Quota", "quinn@cand.example", "1973-05-03"
    )
    X.advance_to_slate_eligible(
        client, over_the_limit["id"], chair_headers, [interviewer["id"]], scores=(4,), first_slot=1
    )

    X.give_candidate_boards(
        client,
        on_the_limit["id"],
        [company["id"] for company in companies[:BOARDS_ON_THE_LIMIT]],
    )
    X.give_candidate_boards(
        client, over_the_limit["id"], [company["id"] for company in companies]
    )

    slate = X.new_slate(client, cycle_year=C.CYCLE_YEAR, seat_count=SLATE_SEAT_COUNT)

    return {
        "on_the_limit_id": on_the_limit["id"],
        "over_the_limit_id": over_the_limit["id"],
        "slate_id": slate["id"],
    }


def _nominee_add_attempt(client, slate_id, candidate_id, ballot_order):
    """Add one nominee, echoing the slate's version as it stands right now."""
    return client.add_slate_nominee(
        slate_id,
        F.nominee_payload(
            X.slate_version(client, slate_id), ballot_order, candidate_id=candidate_id
        ),
        STAFF,
    )


def test_candidate_sitting_exactly_on_the_overboarding_limit_is_admitted(client):
    """Three outside public boards plus the seat now under consideration equals the
    limit of four, which does not strictly exceed it, so the nominee is created.

    PRD: "The overboarding test fails when the count *strictly exceeds* the limit."

    Design: Difficulty/boundary_precision_check/overboarding_limit_off_by_one_three_boards_admitted_four_boards_rejected
    """
    world = _overboarding_boundary_world(client)

    nominee = X.add_candidate_nominee(
        client, world["slate_id"], world["on_the_limit_id"], 1
    )

    assert_fields_equal(nominee, {"status": "PROPOSED", "ballot_order": 1})
    assert_fields_equal(
        X.get_candidate(client, world["on_the_limit_id"]), {"status": "NOMINATED"}
    )


def test_candidate_one_board_past_the_overboarding_limit_is_refused(client):
    """Four outside public boards plus the seat under consideration is five against a
    limit of four, and at the slate the guideline is a hard refusal.

    PRD: "The same three tests are re-evaluated when the candidate is actually placed on a slate, but there they are hard refusals rather than recorded outcomes"

    Design: Difficulty/boundary_precision_check/overboarding_limit_off_by_one_three_boards_admitted_four_boards_rejected
    """
    world = _overboarding_boundary_world(client)

    response = _nominee_add_attempt(client, world["slate_id"], world["over_the_limit_id"], 1)

    validate_error(response, ERR_OVERBOARDING_LIMIT_EXCEEDED, expected_status=422)


def test_only_the_admitted_side_of_the_boundary_joins_the_counted_nominee_set(client):
    """With both candidates offered to the same slate, the counted set holds exactly the
    one that sat on the limit, and the refused candidate is left where it was.

    PRD: "The `nominee_count` is the size of that set and the `independent_nominee_count` is the number of those rows whose `is_independent` is true."

    Design: Difficulty/boundary_precision_check/overboarding_limit_off_by_one_three_boards_admitted_four_boards_rejected
    """
    world = _overboarding_boundary_world(client)

    X.add_candidate_nominee(client, world["slate_id"], world["on_the_limit_id"], 1)
    validate_error(
        _nominee_add_attempt(client, world["slate_id"], world["over_the_limit_id"], 2),
        ERR_OVERBOARDING_LIMIT_EXCEEDED,
        expected_status=422,
    )

    assert_fields_equal(
        X.get_slate(client, world["slate_id"]),
        {"nominee_count": 1, "independent_nominee_count": 1, "independent_nominee_pct": 100.00},
    )
    assert_fields_equal(
        X.get_candidate(client, world["over_the_limit_id"]), {"status": "SLATE_ELIGIBLE"}
    )


def test_gap_analysis_over_an_empty_matrix_reports_a_defined_zero(client):
    """With a policy adopted and nothing else in the register, the board-wide index is a
    stated zero and no category can be singled out as the priority.

    PRD: "When no skill category has been registered at all, `board_gap_index` is 0.00 and `priority_category_code` is null."

    Design: Difficulty/boundary_precision_check/empty_set_denominator_boundaries_gap_index_and_slate_independence_pct
    """
    X.adopt_policy(client)

    analysis = X.get_gap_analysis(client)

    assert_fields_equal(
        analysis,
        {
            "variant": "SELF_REPORTED",
            "seated_director_count": 0,
            "category_count": 0,
            "board_gap_index": EMPTY_BOARD_GAP_INDEX,
            "priority_category_code": None,
            "categories": [],
        },
    )


def test_one_category_with_no_seated_director_reports_the_widest_possible_gap(client):
    """A single risk-oversight category against an empty board leaves the whole required
    minimum uncovered, so the weighted figure is the full 2.25 and the index matches it.

    PRD: "The `weighted_gap` is the `gap` multiplied by the category's `strategic_weight` multiplied by that risk multiplier, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/empty_set_denominator_boundaries_gap_index_and_slate_independence_pct
    """
    X.adopt_policy(client)
    X.new_skill_category(
        client,
        code=CATEGORY_CODE,
        name="Cybersecurity Risk Oversight",
        strategic_weight=CATEGORY_STRATEGIC_WEIGHT,
        required_min_directors=CATEGORY_REQUIRED_MIN_DIRECTORS,
        risk_oversight=True,
        criticality="CORE",
    )

    analysis = X.get_gap_analysis(client, variant="VALIDATED_ONLY")

    assert_fields_equal(
        analysis,
        {
            "seated_director_count": 0,
            "category_count": 1,
            "board_gap_index": EXPECTED_BOARD_GAP_INDEX,
            "priority_category_code": CATEGORY_CODE,
        },
    )
    assert_gap_row(
        analysis, CATEGORY_CODE, 0, EXPECTED_GAP, EXPECTED_WEIGHTED_GAP, "CRITICAL_GAP"
    )


def test_a_slate_with_no_nominee_reports_zero_pct_and_no_shortfall(client):
    """The independence percentage over an empty nominee set is a defined zero, and that
    zero is explicitly not read as falling short of the floor.

    PRD: "a percentage exactly equal to the floor is not a shortfall, and an empty slate is never a shortfall."

    Design: Difficulty/boundary_precision_check/empty_set_denominator_boundaries_gap_index_and_slate_independence_pct
    """
    X.adopt_policy(client)
    slate = X.new_slate(client, cycle_year=C.CYCLE_YEAR, seat_count=SLATE_SEAT_COUNT)

    assert_fields_equal(
        X.get_slate(client, slate["id"]),
        {
            "nominee_count": 0,
            "independent_nominee_count": 0,
            "independent_nominee_pct": 0.00,
            "independence_shortfall": False,
            "committed_search_fee_cents": 0,
        },
    )


def test_an_empty_slate_is_still_refused_review_on_the_at_least_one_nominee_leg(client):
    """No shortfall is recorded on the empty slate, yet review demands at least one
    nominee, so the submission is refused and the slate stays where it was.

    PRD: "The slate must carry at least one nominee and its `independent_nominee_pct` must be at or above the policy's `independence_min_pct`, else `ERR_INDEPENDENCE_SHORTFALL`"

    Design: Difficulty/boundary_precision_check/empty_set_denominator_boundaries_gap_index_and_slate_independence_pct
    """
    X.adopt_policy(client)
    slate = X.new_slate(client, cycle_year=C.CYCLE_YEAR, seat_count=SLATE_SEAT_COUNT)

    response = client.submit_slate_for_review(slate["id"], STAFF)

    validate_error(response, ERR_INDEPENDENCE_SHORTFALL, expected_status=422)
    assert_fields_equal(X.get_slate(client, slate["id"]), {"status": "DRAFT"})
