"""
A game's two state dimensions, and the zero-cardinality boundary that blocks
certification.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ERR_NO_ACCEPTED_TAGS
from test_helpers.assertions import (
    assert_game_dimensions,
    assert_quality_index,
    assert_tag_census,
    expected_quality_index,
)
from test_helpers.constants import (
    CERTIFICATION_OFFICIAL,
    CERTIFICATION_PENDING,
    CERTIFICATION_PROVISIONAL,
    CLOCK_NOON,
    COLLECTION_ARCHIVED,
    COLLECTION_COLLECTED,
    COLLECTION_LIVE,
)
from test_helpers.test_users import OPS_HEADERS, REVIEWER_QA_HEADERS

TAG_CONFIDENCE = 0.95


def _tagged_live_world(api: ApiClient) -> fx.World:
    """A LIVE game whose single tag has been accepted by someone else."""
    return fx.accepted_tag_world(
        api, reviewer=REVIEWER_QA_HEADERS, confidence=TAG_CONFIDENCE
    )


def test_accepting_a_tag_advances_certification_and_leaves_collection_alone(api, clock):
    """PRD §3.5: "It also carries one cross-dimension effect: when this is the game's first
    acceptance, so that `accepted_tag_count` becomes at least 1 while
    `certification_status` still reads `PENDING`, the game's `certification_status`
    advances `PENDING → PROVISIONAL` in the same request."
    PRD §3.4: "`collection_status` tracks the data-collection pipeline and is driven by
    league operations and by the venue-posture cascade."

    The first acceptance moves certification to PROVISIONAL while play continues.

    Design: Difficulty/non_linear_state_machine/game_collection_and_certification_dimensions_advance_independently
    """
    world = _tagged_live_world(api)

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_game_dimensions(game, COLLECTION_LIVE, CERTIFICATION_PROVISIONAL)
    assert_tag_census(
        game, draft=0, submitted=0, accepted=1, under_correction=0, superseded=0, total=1
    )


def test_closing_collection_advances_collection_and_leaves_certification_alone(api, clock):
    """PRD §3.4: "It is permitted only from `LIVE`, advances `collection_status` `LIVE →
    COLLECTED`, and increments the game's `version`."
    PRD §3.4: "Neither dimension gates the other's transitions except where explicitly
    stated, and readers should not assume that a game whose collection has closed has a
    certified record, or vice versa."

    Collection reaches COLLECTED with certification still PROVISIONAL.

    Design: Difficulty/non_linear_state_machine/game_collection_and_certification_dimensions_advance_independently
    """
    world = _tagged_live_world(api)

    closed = validate_success(api.close_collection(world.game_id, OPS_HEADERS))
    assert_game_dimensions(closed, COLLECTION_COLLECTED, CERTIFICATION_PROVISIONAL)
    assert_quality_index(closed, 0.8250)
    assert_quality_index(
        closed,
        expected_quality_index([TAG_CONFIDENCE], 0, 0, 1),
    )


def test_only_certification_couples_the_two_dimensions(api, clock):
    """PRD §3.4: "When the game's `certification_status` reaches `OFFICIAL`, the system
    advances `collection_status` `COLLECTED → ARCHIVED` in the same request, with no
    effect beyond the status write and the accompanying `updated_at` and `version`
    refresh."
    PRD §3.6: "On success `certification_status` advances to `OFFICIAL`,
    `certified_at_utc` is stamped with the logical clock, `collection_status` advances
    `COLLECTED → ARCHIVED` (or stays `ARCHIVED` on a re-certification), and the game's
    `version` is incremented."

    Certifying drives certification to OFFICIAL and drags collection to ARCHIVED.

    Design: Difficulty/non_linear_state_machine/game_collection_and_certification_dimensions_advance_independently
    """
    world = _tagged_live_world(api)
    validate_success(api.close_collection(world.game_id, OPS_HEADERS))

    certified = validate_success(api.certify_game(world.game_id, OPS_HEADERS))
    assert_game_dimensions(certified, COLLECTION_ARCHIVED, CERTIFICATION_OFFICIAL)
    assert certified["certified_at_utc"] == CLOCK_NOON
    assert certified["accepted_tag_count"] == 1
    assert certified["total_tag_count"] == 1


# ---------------------------------------------------------------------------
# Certification with an empty accepted set
# ---------------------------------------------------------------------------

def _untagged_collected_world(api: ApiClient) -> fx.World:
    """A COLLECTED game that never carried a single tag."""
    world = fx.certified_venue(api)
    clubs = fx.register_clubs(api)
    world.home_club = clubs["home"]
    world.away_club = clubs["away"]
    world.game = get_success_data(
        api.create_game(
            fac.game_payload(
                world.venue["id"], world.home_club["id"], world.away_club["id"]
            ),
            OPS_HEADERS,
        )
    )
    validate_success(api.open_collection(world.game["id"], OPS_HEADERS))
    world.game = validate_success(api.close_collection(world.game["id"], OPS_HEADERS))
    return world


def test_a_game_with_no_accepted_tags_cannot_be_certified(api, clock):
    """PRD §3.6: "It is permitted only while `certification_status` is `PROVISIONAL` or
    `DISPUTED`; an already-official game is refused with `ERR_GAME_ALREADY_OFFICIAL`,
    and a game still in `PENDING` reaches the accepted-tags gate instead and is refused
    with `ERR_NO_ACCEPTED_TAGS`."
    PRD §2.10: "Accepted tags exist: the game's `accepted_tag_count` is at least 1 —
    otherwise `ERR_NO_ACCEPTED_TAGS` (HTTP 422)."

    Zero accepted tags is refused outright, not merely scored low.

    Design: Difficulty/boundary_precision_check/certify_rejects_empty_accepted_tag_set
    """
    world = _untagged_collected_world(api)
    assert world.game["accepted_tag_count"] == 0

    validate_error(api.certify_game(world.game_id, OPS_HEADERS), ERR_NO_ACCEPTED_TAGS)


def test_an_empty_scored_set_short_circuits_the_quality_index_to_zero(api, clock):
    """PRD §3.6: "The scored population is the set of the game's event tags whose
    `review_status` is either `ACCEPTED` or `UNDER_CORRECTION`; `DRAFT`, `SUBMITTED` and
    `SUPERSEDED` tags are excluded."
    PRD §3.6: "If that population is empty, the index short-circuits to 0.0000 and no
    weighting is applied at all."

    With nothing scored the index is 0.0000, not the weighted 0.3000.

    A naive weighting of mean confidence 0 with an unpenalised correction term
    would still credit the penalty weight; the empty set takes precedence.

    Design: Difficulty/boundary_precision_check/certify_rejects_empty_accepted_tag_set
    """
    world = _untagged_collected_world(api)

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_quality_index(game, 0.0)
    assert_quality_index(game, expected_quality_index([], 0, 0, 0))
    assert_tag_census(
        game, draft=0, submitted=0, accepted=0, under_correction=0, superseded=0, total=0
    )


def test_the_refused_certification_has_no_side_effects(api, clock):
    """PRD §2.10: "Accepted tags exist: the game's `accepted_tag_count` is at least 1 —
    otherwise `ERR_NO_ACCEPTED_TAGS` (HTTP 422)."
    PRD §3.6: "On success `certification_status` advances to `OFFICIAL`,
    `certified_at_utc` is stamped with the logical clock, `collection_status` advances
    `COLLECTED → ARCHIVED` (or stays `ARCHIVED` on a re-certification), and the game's
    `version` is incremented."

    Neither dimension moves and no certification instant is stamped.

    Design: Difficulty/boundary_precision_check/certify_rejects_empty_accepted_tag_set
    """
    world = _untagged_collected_world(api)
    validate_error(api.certify_game(world.game_id, OPS_HEADERS), ERR_NO_ACCEPTED_TAGS)

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_game_dimensions(game, COLLECTION_COLLECTED, CERTIFICATION_PENDING)
    assert game["certified_at_utc"] is None
