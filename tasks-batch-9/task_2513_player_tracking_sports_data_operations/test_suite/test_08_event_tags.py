"""
Event tags: which refusal wins when one create breaks two rules, and how the
game's tag census survives a correction round trip and a supersession.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_BIOMETRIC_CONSENT_MISSING,
    ERR_PLAYER_NOT_IN_GAME,
)
from test_helpers.assertions import (
    assert_quality_index,
    assert_tag_census,
    expected_quality_index,
)
from test_helpers.constants import (
    RELEASE_NONE,
    TAG_ACCEPTED,
    TAG_SUPERSEDED,
)
from test_helpers.test_users import (
    OPS_HEADERS,
    REVIEWER_QA_HEADERS,
    STATISTICIAN_HEADERS,
)

TAG_CONFIDENCE = 0.9


# ---------------------------------------------------------------------------
# Safety refusals outrank referential refusals
# ---------------------------------------------------------------------------

def _outsider_world(api: ApiClient) -> fx.World:
    """A LIVE game plus a player from a third club who has no consent at all."""
    world = fx.live_game_world(api)
    world.third_club = get_success_data(
        api.create_club(fac.third_club_payload(), OPS_HEADERS)
    )
    world.extra["outsider"] = fx.register_player(
        api, world.third_club["id"], full_name="Kai Mori", jersey_number=11
    )
    return world


def _outsider_tag(api: ApiClient, world: fx.World, biometric: bool):
    return api.create_event_tag(
        fac.event_tag_payload(
            world.game_id,
            world.extra["outsider"]["id"],
            world.game_version,
            biometric_payload_present=biometric,
        ),
        STATISTICIAN_HEADERS,
    )


def test_a_biometric_tag_without_consent_is_refused_before_the_roster_check(api, clock):
    """PRD §2.10: "Checks are evaluated in the following fixed order, and the first
    violated check determines the response."
    PRD §2.10: "Biometric consent: a tag whose `biometric_payload_present` is true names
    a player whose `biometric_release_state` is `GRANTED` — otherwise
    `ERR_BIOMETRIC_CONSENT_MISSING` (HTTP 422)."
    PRD §2.10: "Roster membership: the attributed player's `club_id` is the game's
    `home_club_id` or `away_club_id` — otherwise `ERR_PLAYER_NOT_IN_GAME` (HTTP 409)."

    One create breaks both rules; the consent refusal is the one returned.

    Design: Difficulty/priority_pair_validation_conflict/safety_precedes_referential_on_event_tag_create
    """
    world = _outsider_world(api)

    validate_error(
        _outsider_tag(api, world, biometric=True), ERR_BIOMETRIC_CONSENT_MISSING
    )


def test_dropping_the_biometric_flag_exposes_the_roster_refusal(api, clock):
    """PRD §3.5: "And the attributed player must actually be in the game: their `club_id`
    must equal the game's `home_club_id` or its `away_club_id`, or the request is
    refused with `ERR_PLAYER_NOT_IN_GAME`."

    With the safety violation gone the player's club is still neither side.

    Design: Difficulty/priority_pair_validation_conflict/safety_precedes_referential_on_event_tag_create
    """
    world = _outsider_world(api)
    validate_error(
        _outsider_tag(api, world, biometric=True), ERR_BIOMETRIC_CONSENT_MISSING
    )

    validate_error(_outsider_tag(api, world, biometric=False), ERR_PLAYER_NOT_IN_GAME)


def test_neither_refused_create_touches_the_game_or_the_player(api, clock):
    """PRD §3.5: "A successful create yields a tag in `DRAFT` `review_status`, with
    `tagged_by_user_id` stamped from the acting `X-User-ID`, and with
    `reviewed_by_user_id`, `superseded_by_tag_id` and `corrected_clock_ms` null,
    `correction_count` at zero, and `biometric_masked` false."
    PRD §3.5: "The game's `version` is incremented by one, its `total_tag_count` and
    `draft_tag_count` each rise by one, and the tag's `game_version_at_tag` is stamped
    with the game's `version` *after* that increment — it is the audit anchor a reviewer
    uses to reconstruct which concurrency generation a disputed tag was written
    against."

    No tag is minted and the game's concurrency version does not move.

    Design: Difficulty/priority_pair_validation_conflict/safety_precedes_referential_on_event_tag_create
    """
    world = _outsider_world(api)
    version_before = world.game_version

    validate_error(
        _outsider_tag(api, world, biometric=True), ERR_BIOMETRIC_CONSENT_MISSING
    )
    validate_error(_outsider_tag(api, world, biometric=False), ERR_PLAYER_NOT_IN_GAME)

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert game["total_tag_count"] == 0
    assert game["draft_tag_count"] == 0
    assert game["version"] == version_before

    outsider = validate_success(
        api.get_player(world.extra["outsider"]["id"], OPS_HEADERS)
    )
    assert outsider["biometric_release_state"] == RELEASE_NONE


# ---------------------------------------------------------------------------
# The tag census as a conserved cardinality
# ---------------------------------------------------------------------------

def _current_version(api: ApiClient, game_id: str) -> int:
    return validate_success(api.get_game(game_id, STATISTICIAN_HEADERS))["version"]


def _census_world(api: ApiClient) -> fx.World:
    """One ACCEPTED tag under an open correction, plus one DRAFT tag."""
    world = fx.accepted_tag_world(
        api, reviewer=REVIEWER_QA_HEADERS, confidence=TAG_CONFIDENCE
    )
    world.extra["second_tag"] = fx.create_tag(
        api,
        world.game_id,
        world.player["id"],
        _current_version(api, world.game_id),
        STATISTICIAN_HEADERS,
        tag_type="PASS",
        clock_ms=130000,
        confidence=TAG_CONFIDENCE,
    )
    world.correction = fx.open_correction(api, world.tag_id, STATISTICIAN_HEADERS)
    return world


def test_an_open_correction_moves_a_tag_between_buckets_without_creating_one(api, clock):
    """PRD §3.6: "The tag moves `ACCEPTED → UNDER_CORRECTION`, the game's
    `accepted_tag_count` falls by one and its `under_correction_tag_count` rises by one
    while `total_tag_count` stays put, the game's `version` is incremented, and the
    `quality_index` is recomputed."
    PRD §2.11: "A game's `draft_tag_count`, `submitted_tag_count`, `accepted_tag_count`,
    `under_correction_tag_count` and `superseded_tag_count` sum to exactly its
    `total_tag_count`."

    The accepted tag becomes under-correction; the total is still two.

    Design: Difficulty/compensating_invariant/game_tag_census_conserved_through_correction_and_supersession
    """
    world = _census_world(api)

    game = validate_success(api.get_game(world.game_id, REVIEWER_QA_HEADERS))
    assert_tag_census(
        game, draft=1, submitted=0, accepted=0, under_correction=1, superseded=0, total=2
    )


def test_rejecting_the_correction_returns_the_tag_and_records_the_penalty(api, clock):
    """PRD §3.6: "The request moves `SUBMITTED → REJECTED` with the same
    `reviewed_by_user_id` and `resolved_at_utc` stamps, and the tag moves
    `UNDER_CORRECTION → ACCEPTED` with every field unchanged and `correction_count`
    unchanged."
    PRD §3.6: "The game's `rejected_correction_count` rises by one, its census is
    restored exactly as on approval, its `quality_index` is recomputed — with the
    lighter rejected-dispute weight, so a rejected challenge costs the game far less
    than an upheld one — and its `version` is incremented."
    PRD §3.6: "The second is the correction penalty: the game's
    `approved_correction_count` is taken at full weight of 1.0 and its
    `rejected_correction_count` at a quarter weight of 0.25, those two products are
    added, the sum is divided by the greater of 1 and the game's `accepted_tag_count`,
    and the result is capped at 1.0."

    The tag reads ACCEPTED again with no correction applied to it.

    A rejected correction still costs the game a quarter-weight penalty, so the
    quality index settles at 0.7250.

    Design: Difficulty/compensating_invariant/game_tag_census_conserved_through_correction_and_supersession
    """
    world = _census_world(api)

    validate_success(api.reject_correction(world.correction["id"], REVIEWER_QA_HEADERS))

    tag = validate_success(api.get_event_tag(world.tag_id, STATISTICIAN_HEADERS))
    assert tag["review_status"] == TAG_ACCEPTED
    assert tag["correction_count"] == 0
    assert tag["corrected_clock_ms"] is None

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert game["rejected_correction_count"] == 1
    assert_tag_census(
        game, draft=1, submitted=0, accepted=1, under_correction=0, superseded=0, total=2
    )
    assert_quality_index(game, 0.7250)
    assert_quality_index(game, expected_quality_index([TAG_CONFIDENCE], 0, 1, 1))


def test_a_supersession_moves_the_old_tag_and_conserves_the_total(api, clock):
    """PRD §3.5: "The triple of `game_id`, `tag_type` and `clock_ms` identifies one event,
    and a new tag on a triple that an existing non-superseded tag already occupies
    **supersedes** that existing tag."
    PRD §3.5: "Supersession is permitted out of `DRAFT`, `SUBMITTED` or `ACCEPTED`: the
    older tag moves to `SUPERSEDED`, its `superseded_by_tag_id` is set to the new tag's
    id, and the game's census moves that row out of whichever bucket held it and into
    `superseded_tag_count`, leaving `total_tag_count` unchanged for the superseded row."

    A third tag on the same coordinate supersedes the first; the sum still holds.

    Design: Difficulty/compensating_invariant/game_tag_census_conserved_through_correction_and_supersession
    """
    world = _census_world(api)
    validate_success(api.reject_correction(world.correction["id"], REVIEWER_QA_HEADERS))

    third = fx.create_tag(
        api,
        world.game_id,
        world.player["id"],
        _current_version(api, world.game_id),
        STATISTICIAN_HEADERS,
        tag_type="SHOT",
        clock_ms=120000,
        confidence=TAG_CONFIDENCE,
    )

    superseded = validate_success(api.get_event_tag(world.tag_id, STATISTICIAN_HEADERS))
    assert superseded["review_status"] == TAG_SUPERSEDED
    assert superseded["superseded_by_tag_id"] == third["id"]

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_tag_census(
        game, draft=2, submitted=0, accepted=0, under_correction=0, superseded=1, total=3
    )
    assert_quality_index(game, 0.0)
    assert third["game_version_at_tag"] == game["version"]
