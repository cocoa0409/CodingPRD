"""
Two multi-level cascades: an engineering drift flag walking down to a feed
session, and a club's consent withdrawal walking down to masked tags.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_unit_ledger
from test_helpers.constants import (
    CLOCK_NOON,
    COLLECTION_LIVE,
    COLLECTION_SUSPENDED,
    CONSENT_WITHDRAWN,
    HALT_CONSENT_WITHDRAWN,
    HALT_VENUE_DEGRADED,
    INSTALLATION_RECALIBRATION_REQUIRED,
    POSTURE_CERTIFIED,
    POSTURE_UNCERTIFIED,
    QUALITY_FLAG_CLEAN,
    QUALITY_FLAG_DEGRADED,
    RELEASE_WITHDRAWN,
    SCOPE_BIOMETRIC,
    SESSION_ACTIVE,
    SESSION_SUSPENDED,
    TAG_DRAFT,
)
from test_helpers.test_users import (
    ENGINEER_ALT_HEADERS,
    ENGINEER_HEADERS,
    OPS_HEADERS,
    STATISTICIAN_HEADERS,
)

COMMERCIAL_WINDOW = {"max_latency_ms": 400, "allowed_scopes": ["POSITIONAL", "EVENT"]}
BIOMETRIC_WINDOW = {
    "max_latency_ms": 400,
    "allowed_scopes": ["POSITIONAL", "EVENT", "BIOMETRIC"],
}


# ---------------------------------------------------------------------------
# Drift on a rig, all the way down to the feed session
# ---------------------------------------------------------------------------

def _degradable_world(api: ApiClient) -> fx.World:
    """A LIVE game at a one-rig venue with an ACTIVE session reserving 900 units."""
    return fx.active_session_world(api, window_overrides=COMMERCIAL_WINDOW)


def test_one_drift_flag_walks_down_four_levels(api, clock):
    """PRD §3.2: "What follows is the system's most consequential cascade, and all three of
    its links fire inside the same request."
    PRD §3.2: "The second link, caused by the first, reaches every game hosted at that
    venue whose `collection_status` is `LIVE`: each such game moves `LIVE →
    SUSPENDED_COLLECTION` and its `data_quality_flag` moves from `CLEAN` to `DEGRADED`."
    PRD §3.2: "The third link, caused by the second, reaches every feed session on those
    games whose `status` is `ACTIVE`: each moves `ACTIVE → SUSPENDED` with `halt_reason`
    set to `VENUE_DEGRADED`."

    Rig, venue, game and session all move on a single flag-drift call.

    Design: Difficulty/transitive_cascade/drift_flag_cascades_to_venue_posture_game_suspension_and_feed_session
    """
    world = _degradable_world(api)

    flagged = validate_success(api.flag_drift(world.rig_id, ENGINEER_HEADERS))
    assert flagged["status"] == INSTALLATION_RECALIBRATION_REQUIRED

    venue = validate_success(api.get_venue(world.venue_id, OPS_HEADERS))
    assert venue["data_posture"] == POSTURE_UNCERTIFIED

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert game["collection_status"] == COLLECTION_SUSPENDED
    assert game["data_quality_flag"] == QUALITY_FLAG_DEGRADED

    session = validate_success(api.get_feed_session(world.session_id, OPS_HEADERS))
    assert session["status"] == SESSION_SUSPENDED
    assert session["halt_reason"] == HALT_VENUE_DEGRADED


def test_the_drift_cascade_is_quota_neutral(api, clock):
    """PRD §3.2: "Critically, a suspension of this kind leaves the licensee's quota
    completely untouched — neither `reserved_units` nor `available_units` moves, because
    the session has not been settled, merely paused."

    Suspension neither consumes nor releases a single reserved unit.

    Design: Difficulty/transitive_cascade/drift_flag_cascades_to_venue_posture_game_suspension_and_feed_session
    """
    world = _degradable_world(api)
    validate_success(api.flag_drift(world.rig_id, ENGINEER_HEADERS))

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert_unit_ledger(licensee, available=4100, reserved=900, consumed=0)


def test_posture_recovery_alone_does_not_resume_the_game(api, clock):
    """PRD §3.4: "Recovery is requested: once the venue's `data_posture` reads `CERTIFIED`
    again — which requires the offending rig to have been recalibrated and re-certified,
    or retired — `LeagueDataOps` resumes the game."
    PRD §3.4: "A game moves `LIVE → SUSPENDED_COLLECTION` only as the second link of the
    venue-degradation cascade of §3.2, and when it does, `data_quality_flag` flips to
    `DEGRADED` and every `ACTIVE` feed session on the game moves to `SUSPENDED` with
    `halt_reason` of `VENUE_DEGRADED`."

    Re-certifying the rig restores the venue but leaves the game suspended.

    Design: Difficulty/transitive_cascade/drift_flag_cascades_to_venue_posture_game_suspension_and_feed_session
    """
    world = _degradable_world(api)
    validate_success(api.flag_drift(world.rig_id, ENGINEER_HEADERS))
    fx.record_run(
        api,
        world.rig_id,
        ENGINEER_ALT_HEADERS,
        axis_rms_x_mm=75.0,
        axis_rms_y_mm=75.0,
        axis_rms_z_mm=75.0,
    )
    fx.certify_rig(api, world.rig_id, OPS_HEADERS)

    venue = validate_success(api.get_venue(world.venue_id, OPS_HEADERS))
    assert venue["data_posture"] == POSTURE_CERTIFIED

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert game["collection_status"] == COLLECTION_SUSPENDED


def test_resuming_collection_walks_the_cascade_back_up(api, clock):
    """PRD §3.4: "Resumption is permitted only from `SUSPENDED_COLLECTION`, re-checks the
    venue posture and is refused with `ERR_VENUE_NOT_CERTIFIED` when the posture has not
    recovered, advances `collection_status` `SUSPENDED_COLLECTION → LIVE`, returns
    `data_quality_flag` to `CLEAN`, increments the game's `version`, and reactivates
    precisely those sessions that the degradation paused: every feed session on the game
    in `SUSPENDED` status whose `halt_reason` is `VENUE_DEGRADED` moves `SUSPENDED →
    ACTIVE` with `halt_reason` cleared to null."
    PRD §3.4: "Sessions suspended for any other reason — a consent loss or a repeated
    SLA breach — are deliberately left where they are, because resuming collection says
    nothing about consent or delivery quality."

    The explicit resume restores the game and revives the halted session.

    Design: Difficulty/transitive_cascade/drift_flag_cascades_to_venue_posture_game_suspension_and_feed_session
    """
    world = _degradable_world(api)
    validate_success(api.flag_drift(world.rig_id, ENGINEER_HEADERS))
    fx.record_run(
        api,
        world.rig_id,
        ENGINEER_ALT_HEADERS,
        axis_rms_x_mm=75.0,
        axis_rms_y_mm=75.0,
        axis_rms_z_mm=75.0,
    )
    fx.certify_rig(api, world.rig_id, OPS_HEADERS)

    resumed = validate_success(api.resume_collection(world.game_id, OPS_HEADERS))
    assert resumed["collection_status"] == COLLECTION_LIVE
    assert resumed["data_quality_flag"] == QUALITY_FLAG_CLEAN

    session = validate_success(api.get_feed_session(world.session_id, OPS_HEADERS))
    assert session["status"] == SESSION_ACTIVE
    assert session["halt_reason"] is None

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert licensee["consumed_units"] == 0


# ---------------------------------------------------------------------------
# Consent withdrawal, all the way down to the masked tag
# ---------------------------------------------------------------------------

def _biometric_world(api: ApiClient) -> fx.World:
    """A LIVE game with a consented player, a biometric tag and a biometric feed."""
    world = fx.live_game_world(api)
    world.consent = fx.granted_biometric_consent(
        api, world.player["id"], world.home_club["id"]
    )
    world.licensee = fx.onboard_licensee(
        api, licensee_class="COMMERCIAL_LICENSEE", biometric_entitled=True
    )
    world.window = fx.allocate_window(
        api, world.game_id, world.licensee["id"], **BIOMETRIC_WINDOW
    )
    world.session = fx.open_session(
        api,
        world.licensee["id"],
        world.game_id,
        world.window["id"],
        scope=[SCOPE_BIOMETRIC],
    )
    current = validate_success(api.get_game(world.game_id, STATISTICIAN_HEADERS))
    world.tag = get_success_data(
        api.create_event_tag(
            fac.event_tag_payload(
                world.game_id,
                world.player["id"],
                current["version"],
                biometric_payload_present=True,
            ),
            STATISTICIAN_HEADERS,
        ),
        expected_status=201,
    )
    return world


def test_withdrawal_ends_the_record_and_the_players_release(api, clock):
    """PRD §3.3: "Withdrawal moves the record `ACTIVE → WITHDRAWN`, stamps
    `terminated_at_utc` with the logical clock, and clears the player's
    `active_consent_record_id` to null."
    PRD §3.3: "The first link moves the player's `biometric_release_state` from
    `GRANTED` to `WITHDRAWN`."

    The record is terminated at the current clock and the player loses its link.

    Design: Difficulty/transitive_cascade/consent_withdrawal_cascades_to_masked_tags_and_biometric_feed_session
    """
    world = _biometric_world(api)

    withdrawn = validate_success(
        api.withdraw_consent_record(world.consent["id"], world.home_officer)
    )
    assert withdrawn["status"] == CONSENT_WITHDRAWN
    assert withdrawn["terminated_at_utc"] == CLOCK_NOON

    player = validate_success(api.get_player(world.player["id"], OPS_HEADERS))
    assert player["biometric_release_state"] == RELEASE_WITHDRAWN
    assert player["active_consent_record_id"] is None


def test_withdrawal_masks_the_biometric_tag_without_moving_its_review(api, clock):
    """PRD §3.3: "The second link, caused by the first, reaches every event tag attributed
    to that player whose `biometric_payload_present` is true and whose `review_status`
    is anything other than `SUPERSEDED`: each such tag has `biometric_masked` set to
    true, suppressing the biometric attributes from every downstream read, and the
    player's `masked_tag_count` together with each affected game's `masked_tag_count`
    rises accordingly."

    The tag is masked and counted, and its review status stays DRAFT.

    Design: Difficulty/transitive_cascade/consent_withdrawal_cascades_to_masked_tags_and_biometric_feed_session
    """
    world = _biometric_world(api)
    validate_success(api.withdraw_consent_record(world.consent["id"], world.home_officer))

    tag = validate_success(api.get_event_tag(world.tag_id, STATISTICIAN_HEADERS))
    assert tag["biometric_masked"] is True
    assert tag["review_status"] == TAG_DRAFT

    player = validate_success(api.get_player(world.player["id"], OPS_HEADERS))
    assert player["masked_tag_count"] == 1

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert game["masked_tag_count"] == 1


def test_withdrawal_suspends_the_biometric_feed_and_leaves_collection_alone(api, clock):
    """PRD §3.3: "The third link, caused by the second, reaches every feed session in
    `ACTIVE` status that is running on a game which just gained a masked tag and whose
    requested `scope` includes `BIOMETRIC`: each such session moves `ACTIVE → SUSPENDED`
    with `halt_reason` set to `CONSENT_WITHDRAWN`, and, as with venue degradation, the
    licensee's quota is left untouched because nothing has been settled."

    The session halts for CONSENT_WITHDRAWN while the game stays LIVE.

    Design: Difficulty/transitive_cascade/consent_withdrawal_cascades_to_masked_tags_and_biometric_feed_session
    """
    world = _biometric_world(api)
    validate_success(api.withdraw_consent_record(world.consent["id"], world.home_officer))

    session = validate_success(api.get_feed_session(world.session_id, OPS_HEADERS))
    assert session["status"] == SESSION_SUSPENDED
    assert session["halt_reason"] == HALT_CONSENT_WITHDRAWN

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert game["collection_status"] == COLLECTION_LIVE

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert_unit_ledger(licensee, available=4100, reserved=900, consumed=0)
