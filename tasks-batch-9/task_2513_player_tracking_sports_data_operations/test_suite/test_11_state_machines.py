"""
Lifecycle edges: the state a row is born in, the transitions a terminal row must
refuse, and the side effects one transition fires on a neighbouring aggregate.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_CORRECTION_ALREADY_RESOLVED,
    ERR_GAME_ALREADY_OFFICIAL,
    ERR_INVALID_CONSENT_STATE,
    ERR_INVALID_GAME_COLLECTION_STATE,
    ERR_INVALID_INSTALLATION_STATE,
    ERR_INVALID_TAG_STATE,
    ERR_QUALITY_INDEX_BELOW_THRESHOLD,
)
from test_helpers.assertions import (
    assert_game_dimensions,
    assert_installation_census,
    assert_quality_index,
    assert_tag_census,
    assert_two_dp,
    assert_unit_ledger,
    expected_quality_index,
)
from test_helpers.constants import (
    CERTIFICATION_OFFICIAL,
    CERTIFICATION_PENDING,
    CERTIFICATION_PROVISIONAL,
    CLOCK_NOON,
    COLLECTION_ARCHIVED,
    COLLECTION_COLLECTED,
    CONSENT_WITHDRAWN,
    CORRECTION_APPROVED,
    CORRECTION_REJECTED,
    HALT_CLIENT_REQUEST,
    INSTALLATION_DEPLOYED,
    INSTALLATION_RETIRED,
    INSTALLATION_VALIDATED,
    POSTURE_UNCERTIFIED,
    RELEASE_WITHDRAWN,
    RESULT_PASS,
    SESSION_SUSPENDED,
    TAG_ACCEPTED,
    TAG_DRAFT,
    TAG_SUPERSEDED,
    WINDOW_ACTIVE,
)
from test_helpers.test_users import (
    ENGINEER_ALT_HEADERS,
    ENGINEER_HEADERS,
    ENGINEER_PRIMARY,
    OPS_HEADERS,
    REVIEWER_QA,
    REVIEWER_QA_HEADERS,
    STATISTICIAN_ALT_HEADERS,
    STATISTICIAN_HEADERS,
    STATISTICIAN_SECONDARY,
    make_club_data_officer_headers,
)

FIRST_TAG_CONFIDENCE = 0.4
SECOND_TAG_CONFIDENCE = 0.9
ACCEPTED_TAG_CONFIDENCE = 0.9


# ---------------------------------------------------------------------------
# Where a rig starts, and what its first passing run does
# ---------------------------------------------------------------------------

def test_a_new_rig_is_born_deployed_and_the_venue_stays_uncertified(api):
    """PRD §3.1: "A new rig enters the world in `DEPLOYED` status, with
    `latest_run_result`, `latest_run_composite_rms_mm`, `latest_run_recorded_at_utc`,
    `latest_run_engineer_user_id`, `certified_at_utc` and `certified_by_user_id` all
    null, and with `calibration_run_count` and `drift_flag_count` at zero."
    PRD §3.1: "Deployment lifts the venue's `active_installation_count` and
    `uncertified_installation_count` by one each and re-derives the venue's posture."
    PRD §3.1: "If the certified count is zero, `data_posture` is `UNCERTIFIED` — and
    that outcome holds regardless of how many rigs are mid-calibration."

    Deployment is not calibration: the rig arrives in DEPLOYED.

    Nothing is certified yet, so the venue's derived posture cannot move, and the
    fresh rig lands in the uncertified bucket rather than the recalibrating one.

    Design: Corner/state_machines/installation_starts_in_deployed_and_leaves_venue_uncertified
    """
    venue = fx.register_venue(api)

    rig = get_success_data(
        api.create_installation(
            fac.installation_payload(venue["id"], modality="OPTICAL_CAMERA"),
            OPS_HEADERS,
        ),
        expected_status=201,
    )
    assert rig["status"] == INSTALLATION_DEPLOYED

    read_back = validate_success(api.get_venue(venue["id"], OPS_HEADERS))
    assert read_back["data_posture"] == POSTURE_UNCERTIFIED
    assert read_back["active_installation_count"] == 1
    assert_installation_census(
        read_back, certified=0, recalibrating=0, uncertified=1, retired=0
    )


def test_a_passing_run_carries_the_rig_through_calibrating_to_validated(api, clock):
    """PRD §3.2: "The recording always moves the rig into `CALIBRATING`, whether it came
    from `DEPLOYED` or from `RECALIBRATION_REQUIRED`, and in both cases the same effects
    follow: the run row is created, the rig's `calibration_run_count` rises by one, and
    its four mirror fields — `latest_run_result`, `latest_run_composite_rms_mm`,
    `latest_run_recorded_at_utc` and `latest_run_engineer_user_id` — are refreshed from
    the run that now has the greatest `recorded_at_utc` (with `created_at` ascending as
    the tie-break, so the last-written of two runs sharing an instant wins)."
    PRD §3.2: "Immediately afterwards, and without any further call, a rig whose
    just-recorded verdict was `PASS` advances `CALIBRATING → VALIDATED`, and the venue
    census and posture are re-derived again to reflect the move."

    One request crosses two transitions and refreshes all four mirrors.

    The recording moves the rig into CALIBRATING and the PASS verdict immediately
    advances it again, so it must not be found waiting in CALIBRATING.

    Design: Corner/state_machines/passing_calibration_run_auto_validates_rig_and_refreshes_mirrors
    """
    venue = fx.register_venue(api)
    rig = fx.deploy_rig(api, venue["id"])

    run = get_success_data(
        api.create_calibration_run(
            rig["id"], fac.uniform_calibration_run_payload(75.0), ENGINEER_HEADERS
        ),
        expected_status=201,
    )
    assert_two_dp(run["composite_rms_mm"], 75.00)
    assert run["result"] == RESULT_PASS
    assert run["recorded_by_user_id"] == ENGINEER_PRIMARY
    assert run["recorded_at_utc"] == CLOCK_NOON

    read_back = validate_success(api.get_installation(rig["id"], ENGINEER_HEADERS))
    assert read_back["status"] == INSTALLATION_VALIDATED
    assert read_back["latest_run_result"] == RESULT_PASS
    assert_two_dp(read_back["latest_run_composite_rms_mm"], 75.00)
    assert read_back["latest_run_recorded_at_utc"] == CLOCK_NOON
    assert read_back["latest_run_engineer_user_id"] == ENGINEER_PRIMARY
    assert read_back["calibration_run_count"] == 1

    venue_after = validate_success(api.get_venue(venue["id"], OPS_HEADERS))
    assert venue_after["data_posture"] == POSTURE_UNCERTIFIED
    assert_installation_census(venue_after, certified=0, recalibrating=0, uncertified=1)


# ---------------------------------------------------------------------------
# Transitions a rig must refuse
# ---------------------------------------------------------------------------

def test_drift_cannot_be_flagged_on_a_rig_that_never_claimed_accuracy(api):
    """PRD §2.10: "Installation lifecycle: the rig's `status` is in the requested
    transition's allowed source set — recording a run allows `DEPLOYED`, `CALIBRATING`
    or `RECALIBRATION_REQUIRED`; certifying allows only `VALIDATED`; flagging drift
    allows only `CERTIFIED`; retiring allows `CERTIFIED` or `RECALIBRATION_REQUIRED` —
    otherwise `ERR_INVALID_INSTALLATION_STATE`, which is also what any attempt to act on
    a `RETIRED` rig returns."

    A DEPLOYED rig has no accuracy claim to invalidate.

    Design: Corner/state_machines/flag_drift_on_deployed_rig_rejects_with_invalid_installation_state
    """
    venue = fx.register_venue(api)
    rig = fx.deploy_rig(api, venue["id"])

    validate_error(
        api.flag_drift(rig["id"], ENGINEER_HEADERS), ERR_INVALID_INSTALLATION_STATE
    )

    read_back = validate_success(api.get_installation(rig["id"], ENGINEER_HEADERS))
    assert read_back["status"] == INSTALLATION_DEPLOYED
    assert read_back["drift_flag_count"] == 0

    venue_after = validate_success(api.get_venue(venue["id"], OPS_HEADERS))
    assert venue_after["data_posture"] == POSTURE_UNCERTIFIED
    assert_installation_census(venue_after, certified=0, recalibrating=0, uncertified=1)


def test_a_retired_rig_refuses_every_further_transition(api, clock):
    """PRD §3.2: "A rig may be retired from either `CERTIFIED` or `RECALIBRATION_REQUIRED`,
    and `RETIRED` is a terminal state from which no transition is possible."
    PRD §2.10: "Installation lifecycle: the rig's `status` is in the requested
    transition's allowed source set — recording a run allows `DEPLOYED`, `CALIBRATING`
    or `RECALIBRATION_REQUIRED`; certifying allows only `VALIDATED`; flagging drift
    allows only `CERTIFIED`; retiring allows `CERTIFIED` or `RECALIBRATION_REQUIRED` —
    otherwise `ERR_INVALID_INSTALLATION_STATE`, which is also what any attempt to act on
    a `RETIRED` rig returns."

    Retirement is permanent: run, certify, drift and re-retire all fail alike.

    Design: Corner/state_machines/retired_rig_refuses_every_further_transition
    """
    world = fx.certified_venue(api)
    retired = validate_success(api.retire_installation(world.rig_id, OPS_HEADERS))
    assert retired["status"] == INSTALLATION_RETIRED

    validate_error(
        api.create_calibration_run(
            world.rig_id,
            fac.uniform_calibration_run_payload(80.0),
            ENGINEER_ALT_HEADERS,
        ),
        ERR_INVALID_INSTALLATION_STATE,
    )
    validate_error(
        api.certify_installation(world.rig_id, OPS_HEADERS),
        ERR_INVALID_INSTALLATION_STATE,
    )
    validate_error(
        api.flag_drift(world.rig_id, ENGINEER_ALT_HEADERS),
        ERR_INVALID_INSTALLATION_STATE,
    )
    validate_error(
        api.retire_installation(world.rig_id, OPS_HEADERS),
        ERR_INVALID_INSTALLATION_STATE,
    )

    read_back = validate_success(api.get_installation(world.rig_id, ENGINEER_HEADERS))
    assert read_back["status"] == INSTALLATION_RETIRED
    assert read_back["calibration_run_count"] == 1
    assert read_back["drift_flag_count"] == 0

    venue = validate_success(api.get_venue(world.venue_id, OPS_HEADERS))
    assert venue["data_posture"] == POSTURE_UNCERTIFIED
    assert venue["active_installation_count"] == 0
    assert_installation_census(
        venue, certified=0, recalibrating=0, uncertified=0, retired=1
    )


# ---------------------------------------------------------------------------
# Withdrawal is deliberately not idempotent
# ---------------------------------------------------------------------------

def test_a_second_withdrawal_is_refused_and_the_first_stamp_survives(api, clock):
    """PRD §2.10: "Consent lifecycle: `PENDING` for ratification and `ACTIVE` for
    withdrawal — otherwise `ERR_INVALID_CONSENT_STATE`."
    PRD §3.3: "Both `WITHDRAWN` and `EXPIRED` are terminal: neither record can be
    revived, and a club that wants consent back must file a fresh record, which the
    uniqueness rule now permits because no live record remains for the scope."

    Withdrawing an already-withdrawn record is a state error, not a no-op.

    Design: Corner/state_machines/second_withdraw_on_withdrawn_consent_rejected
    """
    club = get_success_data(api.create_club(fac.club_payload(), OPS_HEADERS))
    player = fx.register_player(api, club["id"])
    officer = make_club_data_officer_headers(club["id"])
    record = fx.granted_biometric_consent(api, player["id"], club["id"])
    validate_success(api.withdraw_consent_record(record["id"], officer))

    validate_error(
        api.withdraw_consent_record(record["id"], officer), ERR_INVALID_CONSENT_STATE
    )

    rows, meta = validate_paginated(api.list_consent_records(player["id"], OPS_HEADERS))
    assert meta["total_count"] == 1
    assert rows[0]["status"] == CONSENT_WITHDRAWN
    assert rows[0]["terminated_at_utc"] == CLOCK_NOON

    read_back = validate_success(api.get_player(player["id"], OPS_HEADERS))
    assert read_back["biometric_release_state"] == RELEASE_WITHDRAWN
    assert read_back["active_consent_record_id"] is None
    assert read_back["masked_tag_count"] == 0


# ---------------------------------------------------------------------------
# Closing collection reaches into the delivery aggregate
# ---------------------------------------------------------------------------

def test_closing_collection_suspends_the_realtime_feed_for_the_client(api, clock):
    """PRD §3.4: "Every feed session on the game in `ACTIVE` status whose `delivery_mode`
    is `REALTIME` moves to `SUSPENDED` with `halt_reason` of `CLIENT_REQUEST`, since
    there is no longer a live stream to consume; post-game sessions are untouched."
    PRD §3.7: "Since `active_feed_session_count` tracks the sessions under the window
    that are `ACTIVE` or `SUSPENDED`, it falls to zero."
    PRD §3.8: "Settlement then moves the licensee's ledger in four coordinated steps:
    `reserved_units` falls by the session's `reserved_units`, `consumed_units` rises by
    the session's metered units rounded up to a whole unit, `available_units` rises by
    the session's `refunded_units`, and the licensee's `settled_charge_cents` rises by
    the session's `settled_charge_cents`."

    The live stream is gone, so the session halts for CLIENT_REQUEST.

    The halt is not a settlement: the reservation stands untouched on both the
    session and the licensee ledger, and the window keeps counting the session.

    Design: Corner/state_machines/close_collection_suspends_realtime_session_with_client_request
    """
    world = fx.active_session_world(
        api,
        licensee_overrides={"licensee_class": "COMMERCIAL_LICENSEE"},
        window_overrides={"max_latency_ms": 400},
    )

    closed = validate_success(api.close_collection(world.game_id, OPS_HEADERS))
    assert_game_dimensions(closed, COLLECTION_COLLECTED, CERTIFICATION_PENDING)
    assert_quality_index(closed, 0.0)

    session = validate_success(api.get_feed_session(world.session_id, OPS_HEADERS))
    assert session["status"] == SESSION_SUSPENDED
    assert session["halt_reason"] == HALT_CLIENT_REQUEST
    assert session["reserved_units"] == 900
    assert session["metered_units"] == 0
    assert session["settled_charge_cents"] == 0
    assert session["refunded_units"] == 0

    licensee = validate_success(api.get_licensee(world.licensee_id, OPS_HEADERS))
    assert_unit_ledger(licensee, available=4100, reserved=900, consumed=0)

    windows, _ = validate_paginated(
        api.list_rights_windows(world.game_id, OPS_HEADERS)
    )
    assert len(windows) == 1
    assert windows[0]["status"] == WINDOW_ACTIVE
    assert windows[0]["active_feed_session_count"] == 1


# ---------------------------------------------------------------------------
# An official game is locked on both dimensions
# ---------------------------------------------------------------------------

def test_an_archived_game_refuses_reopening_and_reports_the_official_lock(api, clock):
    """PRD §2.10: "Collection transition source: `SCHEDULED` for opening collection,
    `SUSPENDED_COLLECTION` for resuming collection, `LIVE` for closing collection —
    otherwise `ERR_INVALID_GAME_COLLECTION_STATE`."
    PRD §2.10: "Not already official: the game's `certification_status` is not
    `OFFICIAL` — otherwise `ERR_GAME_ALREADY_OFFICIAL`."
    PRD §2.10: "`ARCHIVED` is accepted on certification on purpose: the first passage to
    `OFFICIAL` archives the game, so every later re-certification cycle necessarily runs
    against an already-`ARCHIVED` row, and an already-official game must be allowed to
    reach rank 14 rather than being deflected here."

    Two collection calls fail on the transition source; certify fails later.

    A second certification passes the archived-tolerant closed-collection gate on
    purpose, so it must surface the already-official refusal rather than the
    not-yet-collected one.

    Design: Corner/state_machines/archived_game_refuses_reopen_and_second_certification
    """
    world = fx.official_game_world(api, reviewer=REVIEWER_QA_HEADERS)
    assert_game_dimensions(world.game, COLLECTION_ARCHIVED, CERTIFICATION_OFFICIAL)
    assert_quality_index(world.game, 0.8000)

    validate_error(
        api.open_collection(world.game_id, OPS_HEADERS),
        ERR_INVALID_GAME_COLLECTION_STATE,
    )
    validate_error(
        api.close_collection(world.game_id, OPS_HEADERS),
        ERR_INVALID_GAME_COLLECTION_STATE,
    )
    validate_error(api.certify_game(world.game_id, OPS_HEADERS), ERR_GAME_ALREADY_OFFICIAL)

    read_back = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_game_dimensions(read_back, COLLECTION_ARCHIVED, CERTIFICATION_OFFICIAL)
    assert read_back["certified_at_utc"] == CLOCK_NOON
    assert_quality_index(read_back, 0.8000)
    assert_quality_index(read_back, expected_quality_index([ACCEPTED_TAG_CONFIDENCE], 0, 0, 1))


# ---------------------------------------------------------------------------
# Supersession, and the two refusals it leaves behind
# ---------------------------------------------------------------------------

def _superseding_pair(api: ApiClient, second_tagger) -> fx.World:
    """Two tags on one (game, tag_type, clock_ms) key, the second retiring the first."""
    world = fx.live_game_world(api)
    world.extra["first"] = fx.create_tag(
        api,
        world.game_id,
        world.player["id"],
        world.game_version,
        STATISTICIAN_HEADERS,
        confidence=FIRST_TAG_CONFIDENCE,
    )
    current = validate_success(api.get_game(world.game_id, STATISTICIAN_HEADERS))
    world.extra["second"] = fx.create_tag(
        api,
        world.game_id,
        world.player["id"],
        current["version"],
        second_tagger,
        confidence=SECOND_TAG_CONFIDENCE,
    )
    return world


def test_a_newer_tag_on_the_same_key_retires_the_draft_it_replaces(api, clock):
    """PRD §3.5: "The triple of `game_id`, `tag_type` and `clock_ms` identifies one event,
    and a new tag on a triple that an existing non-superseded tag already occupies
    **supersedes** that existing tag."
    PRD §3.5: "Supersession is permitted out of `DRAFT`, `SUBMITTED` or `ACCEPTED`: the
    older tag moves to `SUPERSEDED`, its `superseded_by_tag_id` is set to the new tag's
    id, and the game's census moves that row out of whichever bucket held it and into
    `superseded_tag_count`, leaving `total_tag_count` unchanged for the superseded row."

    The old row is kept and re-bucketed, so the total counts both tags.

    Design: Corner/state_machines/newer_tag_on_same_key_supersedes_the_draft_tag
    """
    world = _superseding_pair(api, STATISTICIAN_ALT_HEADERS)
    first = world.extra["first"]
    second = world.extra["second"]

    assert second["review_status"] == TAG_DRAFT
    assert second["tagged_by_user_id"] == STATISTICIAN_SECONDARY
    assert second["game_version_at_tag"] == 4

    superseded = validate_success(api.get_event_tag(first["id"], STATISTICIAN_HEADERS))
    assert superseded["review_status"] == TAG_SUPERSEDED
    assert superseded["superseded_by_tag_id"] == second["id"]

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_tag_census(
        game, draft=1, submitted=0, accepted=0, under_correction=0, superseded=1, total=2
    )
    assert game["version"] == 4
    assert_quality_index(game, 0.0)


def test_a_superseded_tag_refuses_submission_and_a_draft_tag_refuses_acceptance(api, clock):
    """PRD §2.10: "Tag lifecycle: the tag's `review_status` is in the requested
    transition's allowed source set — `DRAFT` for submission, `SUBMITTED` for
    acceptance, `ACCEPTED` for opening a correction — otherwise `ERR_INVALID_TAG_STATE`,
    which is also what any attempt to act on a `SUPERSEDED` tag returns."
    PRD §3.5: "`SUPERSEDED` is terminal: no submission, acceptance or correction may be
    attempted against such a tag, and any attempt is refused with
    `ERR_INVALID_TAG_STATE`."

    Two different source states meet the same tag-lifecycle refusal.

    Submission is legal only out of DRAFT and acceptance only out of SUBMITTED, so
    the retired row and the surviving row each fail on the same gate.

    Design: Corner/state_machines/superseded_tag_refuses_submit_and_draft_tag_refuses_accept
    """
    world = _superseding_pair(api, STATISTICIAN_HEADERS)
    first = world.extra["first"]
    second = world.extra["second"]

    validate_error(
        api.submit_event_tag(first["id"], STATISTICIAN_HEADERS), ERR_INVALID_TAG_STATE
    )
    validate_error(
        api.accept_event_tag(second["id"], REVIEWER_QA_HEADERS), ERR_INVALID_TAG_STATE
    )

    retired = validate_success(api.get_event_tag(first["id"], STATISTICIAN_HEADERS))
    assert retired["review_status"] == TAG_SUPERSEDED
    survivor = validate_success(api.get_event_tag(second["id"], STATISTICIAN_HEADERS))
    assert survivor["review_status"] == TAG_DRAFT
    assert survivor["reviewed_by_user_id"] is None

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_tag_census(
        game, draft=1, submitted=0, accepted=0, under_correction=0, superseded=1, total=2
    )
    assert game["version"] == 4


# ---------------------------------------------------------------------------
# The two forks of a resolved dispute
# ---------------------------------------------------------------------------

def _disputed_world(api: ApiClient) -> fx.World:
    """An OFFICIAL game whose only accepted tag is under an open clock dispute."""
    world = fx.official_game_world(api, reviewer=REVIEWER_QA_HEADERS)
    world.correction = fx.open_correction(api, world.tag_id, STATISTICIAN_HEADERS)
    return world


def test_approving_a_dispute_rewrites_the_tag_and_demands_recertification(api, clock):
    """PRD §3.6: "The tag moves `UNDER_CORRECTION → ACCEPTED` with the corrected values
    applied — a `WRONG_CLOCK` approval writes the request's `proposed_clock_ms` into the
    tag's `corrected_clock_ms`, and a `WRONG_PLAYER` approval overwrites the tag's
    `player_id` with the request's `proposed_player_id` — and the tag's
    `correction_count` rises by one."
    PRD §3.6: "Finally the certification dimension moves `DISPUTED → PROVISIONAL`: the
    official record has been altered, so the game must be certified again from scratch."
    PRD §3.6: "Beyond that, three substantive conditions apply, evaluated in the order
    §2.10 fixes: no correction may be open, so `under_correction_tag_count` must be zero
    or the attempt is refused with `ERR_OPEN_CORRECTIONS`; `accepted_tag_count` must be
    at least 1; and `quality_index` must be at least 0.8000 inclusive, or the attempt is
    refused with `ERR_QUALITY_INDEX_BELOW_THRESHOLD`."

    The corrected clock is written beside the original, not over it.

    An upheld dispute carries the full correction penalty, which drops the index
    below the certification floor, so the game cannot simply be certified again.

    Design: Corner/state_machines/correction_approve_rewrites_tag_and_returns_game_to_provisional
    """
    world = _disputed_world(api)

    approved = validate_success(
        api.approve_correction(world.correction["id"], REVIEWER_QA_HEADERS)
    )
    assert approved["status"] == CORRECTION_APPROVED
    assert approved["reviewed_by_user_id"] == REVIEWER_QA
    assert approved["resolved_at_utc"] == CLOCK_NOON

    tag = validate_success(api.get_event_tag(world.tag_id, STATISTICIAN_HEADERS))
    assert tag["review_status"] == TAG_ACCEPTED
    assert tag["clock_ms"] == 120000
    assert tag["corrected_clock_ms"] == 121000
    assert tag["correction_count"] == 1

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert_game_dimensions(game, COLLECTION_ARCHIVED, CERTIFICATION_PROVISIONAL)
    assert game["approved_correction_count"] == 1
    assert game["rejected_correction_count"] == 0
    assert_tag_census(
        game, draft=0, submitted=0, accepted=1, under_correction=0, superseded=0, total=1
    )
    assert_quality_index(game, 0.5000)
    assert_quality_index(game, expected_quality_index([ACCEPTED_TAG_CONFIDENCE], 1, 0, 1))

    validate_error(
        api.certify_game(world.game_id, OPS_HEADERS), ERR_QUALITY_INDEX_BELOW_THRESHOLD
    )


def test_rejecting_a_dispute_restores_the_official_record_untouched(api, clock):
    """PRD §3.6: "The request moves `SUBMITTED → REJECTED` with the same
    `reviewed_by_user_id` and `resolved_at_utc` stamps, and the tag moves
    `UNDER_CORRECTION → ACCEPTED` with every field unchanged and `correction_count`
    unchanged."
    PRD §3.6: "The certification dimension moves `DISPUTED → OFFICIAL` directly,
    provided the game's `under_correction_tag_count` is zero once the tag has returned
    to `ACCEPTED`, and the game's existing `certified_at_utc` is preserved untouched."
    PRD §2.10: "Correction lifecycle: the correction request's `status` is `SUBMITTED` —
    otherwise `ERR_CORRECTION_ALREADY_RESOLVED`."

    The same starting state, the lighter penalty, and no recertification.

    The tag returns with nothing rewritten, the game walks straight back to
    OFFICIAL keeping its original certification instant, and a repeat resolution
    of the same request is refused.

    Design: Corner/state_machines/correction_reject_restores_official_with_lighter_penalty
    """
    world = _disputed_world(api)

    rejected = validate_success(
        api.reject_correction(world.correction["id"], REVIEWER_QA_HEADERS)
    )
    assert rejected["status"] == CORRECTION_REJECTED
    assert rejected["reviewed_by_user_id"] == REVIEWER_QA
    assert rejected["resolved_at_utc"] == CLOCK_NOON

    tag = validate_success(api.get_event_tag(world.tag_id, STATISTICIAN_HEADERS))
    assert tag["review_status"] == TAG_ACCEPTED
    assert tag["clock_ms"] == 120000
    assert tag["corrected_clock_ms"] is None
    assert tag["correction_count"] == 0

    game = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert game["certification_status"] == CERTIFICATION_OFFICIAL
    assert game["certified_at_utc"] == CLOCK_NOON
    assert game["rejected_correction_count"] == 1
    assert game["approved_correction_count"] == 0
    assert_quality_index(game, 0.7250)
    assert_quality_index(game, expected_quality_index([ACCEPTED_TAG_CONFIDENCE], 0, 1, 1))

    validate_error(
        api.reject_correction(world.correction["id"], REVIEWER_QA_HEADERS),
        ERR_CORRECTION_ALREADY_RESOLVED,
    )

    unchanged = validate_success(api.get_game(world.game_id, OPS_HEADERS))
    assert unchanged["rejected_correction_count"] == 1
    assert unchanged["approved_correction_count"] == 0
    assert unchanged["certification_status"] == CERTIFICATION_OFFICIAL
