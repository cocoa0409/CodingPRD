"""Event tagging, supersession, quality review and the correction procedure
(PRD §3.5, §3.6)."""

from flask import Blueprint

import db
from auth import authenticate
from calc import REASON_CODES, TAG_TYPES
from db import audit_new, new_id, store, touch
from errors import ApiError
from lookups import (require_correction_request, require_event_tag, require_game,
                     require_player)
from response import array_response, object_response
from services.quality import move_census, recompute_quality_index
from util import serialize, serialize_many, sorted_rows
from validation import (field, no_body, paginate, pagination, string_filter,
                        validate_body)

bp = Blueprint("tags", __name__)

TAG_SPEC = {
    "game_id": field("string"),
    "player_id": field("string"),
    "tag_type": field("enum", values=TAG_TYPES),
    "clock_ms": field("integer", minimum=0),
    "confidence": field("number", minimum=0, maximum=1),
    "biometric_payload_present": field("boolean", required=False, default=False),
    "expected_game_version": field("integer"),
}

CORRECTION_SPEC = {
    "reason_code": field("enum", values=REASON_CODES),
    "proposed_clock_ms": field("integer", required=False, default=None, minimum=0),
    "proposed_player_id": field("string", required=False, default=None),
}

READ_TAG_ROLES = ("LeagueDataOps", "Statistician", "QualityReviewer",
                  "ClubDataOfficer")

SUPERSEDABLE_STATES = ("DRAFT", "SUBMITTED", "ACCEPTED")


# --------------------------------------------------------------------------
# Event tags
# --------------------------------------------------------------------------

@bp.post("/event-tags")
def create_event_tag():
    principal = authenticate("Statistician")
    body = validate_body(TAG_SPEC)

    # rank 5: body reference resolution, left to right
    game = require_game(body["game_id"])
    player = require_player(body["player_id"])

    # rank 8: optimistic concurrency on the game aggregate
    if body["expected_game_version"] != game["version"]:
        raise ApiError("ERR_STALE_GAME_VERSION",
                       "expected_game_version does not match the game's current "
                       "version.")

    # rank 11
    if game["collection_status"] != "LIVE":
        raise ApiError("ERR_GAME_NOT_COLLECTING",
                       "Event tags may only be created while collection is LIVE.")

    # rank 21
    if body["biometric_payload_present"] and player["biometric_release_state"] != "GRANTED":
        raise ApiError("ERR_BIOMETRIC_CONSENT_MISSING",
                       "The attributed player holds no granted biometric release.")

    # rank 40
    if player["club_id"] not in (game["home_club_id"], game["away_club_id"]):
        raise ApiError("ERR_PLAYER_NOT_IN_GAME",
                       "The attributed player is not on either club's roster for "
                       "this game.")

    tag = {
        "id": new_id(),
        "game_id": game["id"],
        "player_id": player["id"],
        "tag_type": body["tag_type"],
        "clock_ms": body["clock_ms"],
        "confidence": body["confidence"],
        "biometric_payload_present": body["biometric_payload_present"],
        "review_status": "DRAFT",
        "tagged_by_user_id": principal.user_id,
        "reviewed_by_user_id": None,
        "correction_count": 0,
        "biometric_masked": False,
        "superseded_by_tag_id": None,
        "game_version_at_tag": None,
        "corrected_clock_ms": None,
    }
    audit_new(tag)
    store.event_tags[tag["id"]] = tag

    game["total_tag_count"] = game["total_tag_count"] + 1
    move_census(game, None, "DRAFT")

    # Supersession: the (game_id, tag_type, clock_ms) triple identifies one event.
    superseded_from_accepted = False
    for existing in sorted_rows(db.tags_of_game(game["id"])):
        if existing["id"] == tag["id"]:
            continue
        if existing["tag_type"] != tag["tag_type"]:
            continue
        if existing["clock_ms"] != tag["clock_ms"]:
            continue
        if existing["review_status"] not in SUPERSEDABLE_STATES:
            continue
        previous = existing["review_status"]
        existing["review_status"] = "SUPERSEDED"
        existing["superseded_by_tag_id"] = tag["id"]
        touch(existing)
        move_census(game, previous, "SUPERSEDED")
        if previous == "ACCEPTED":
            superseded_from_accepted = True

    if superseded_from_accepted:
        # The scored tag population has genuinely changed.
        recompute_quality_index(game)

    touch(game)
    tag["game_version_at_tag"] = game["version"]
    return object_response(serialize(tag), 201)


@bp.get("/event-tags/<tag_id>")
def get_event_tag(tag_id):
    authenticate(*READ_TAG_ROLES)
    tag = require_event_tag(tag_id)
    return object_response(serialize(tag))


@bp.get("/event-tags")
def list_event_tags():
    authenticate(*READ_TAG_ROLES)
    limit, offset = pagination()
    game_id = string_filter("game_id")
    player_id = string_filter("player_id")
    review_status = string_filter("review_status")

    rows = list(store.event_tags.values())
    if game_id is not None:
        rows = [r for r in rows if r["game_id"] == game_id]
    if player_id is not None:
        rows = [r for r in rows if r["player_id"] == player_id]
    if review_status is not None:
        rows = [r for r in rows if r["review_status"] == review_status]
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many(page), limit, offset, total)


@bp.post("/event-tags/<tag_id>/submit")
def submit_event_tag(tag_id):
    principal = authenticate("Statistician")
    tag = require_event_tag(tag_id)
    no_body()

    # rank 6: submission is personal (PRD §3.5)
    if principal.user_id != tag["tagged_by_user_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the tagging statistician may submit this tag.")

    # rank 15
    if tag["review_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_TAG_STATE",
                       "Only a DRAFT tag may be submitted.")

    tag["review_status"] = "SUBMITTED"
    touch(tag)

    game = store.games.get(tag["game_id"])
    if game is not None:
        move_census(game, "DRAFT", "SUBMITTED")
        touch(game)
    return object_response(serialize(tag))


@bp.post("/event-tags/<tag_id>/accept")
def accept_event_tag(tag_id):
    principal = authenticate("QualityReviewer")
    tag = require_event_tag(tag_id)
    no_body()

    # rank 7
    if principal.user_id == tag["tagged_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "A reviewer may not accept their own tagging work.")

    # rank 15
    if tag["review_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_TAG_STATE",
                       "Only a SUBMITTED tag may be accepted.")

    tag["review_status"] = "ACCEPTED"
    tag["reviewed_by_user_id"] = principal.user_id
    touch(tag)

    game = store.games.get(tag["game_id"])
    if game is not None:
        move_census(game, "SUBMITTED", "ACCEPTED")
        recompute_quality_index(game)
        # A game never sits in PENDING with accepted work behind it.
        if game["accepted_tag_count"] >= 1 and game["certification_status"] == "PENDING":
            game["certification_status"] = "PROVISIONAL"
        touch(game)
    return object_response(serialize(tag))


# --------------------------------------------------------------------------
# Correction requests
# --------------------------------------------------------------------------

@bp.post("/event-tags/<tag_id>/correction-requests")
def create_correction_request(tag_id):
    principal = authenticate("Statistician", "ClubDataOfficer")
    tag = require_event_tag(tag_id)
    body = validate_body(CORRECTION_SPEC)

    # rank 4: the reason code fixes exactly which replacement value may appear
    reason = body["reason_code"]
    if reason == "WRONG_CLOCK":
        if body["proposed_clock_ms"] is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "proposed_clock_ms is required when reason_code is "
                           "WRONG_CLOCK.")
    elif body["proposed_clock_ms"] is not None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "proposed_clock_ms must be omitted unless reason_code is "
                       "WRONG_CLOCK.")
    if reason == "WRONG_PLAYER":
        if body["proposed_player_id"] is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "proposed_player_id is required when reason_code is "
                           "WRONG_PLAYER.")
    elif body["proposed_player_id"] is not None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "proposed_player_id must be omitted unless reason_code is "
                       "WRONG_PLAYER.")

    # rank 5
    if body["proposed_player_id"] is not None:
        require_player(body["proposed_player_id"])

    game = store.games.get(tag["game_id"])

    # rank 6: a club may only dispute tags of its own club's games
    if principal.role == "ClubDataOfficer":
        if game is None or principal.user_id not in (game["home_club_id"],
                                                     game["away_club_id"]):
            raise ApiError("ERR_NOT_RESOURCE_OWNER",
                           "A club data officer may only dispute tags of its own "
                           "club's games.")

    # rank 15 — a second correction while the first is unresolved fails here
    if tag["review_status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_TAG_STATE",
                       "A correction may only be opened against an ACCEPTED tag.")

    correction = {
        "id": new_id(),
        "event_tag_id": tag["id"],
        "reason_code": reason,
        "proposed_clock_ms": body["proposed_clock_ms"],
        "proposed_player_id": body["proposed_player_id"],
        "status": "SUBMITTED",
        "submitted_by_user_id": principal.user_id,
        "submitted_by_role": principal.role,
        "reviewed_by_user_id": None,
        "resolved_at_utc": None,
    }
    audit_new(correction)
    store.correction_requests[correction["id"]] = correction

    tag["review_status"] = "UNDER_CORRECTION"
    touch(tag)

    if game is not None:
        move_census(game, "ACCEPTED", "UNDER_CORRECTION")
        recompute_quality_index(game)
        if game["certification_status"] == "OFFICIAL":
            game["certification_status"] = "DISPUTED"
        touch(game)
    return object_response(serialize(correction), 201)


@bp.get("/event-tags/<tag_id>/correction-requests")
def list_correction_requests(tag_id):
    authenticate(*READ_TAG_ROLES)
    require_event_tag(tag_id)
    limit, offset = pagination()
    status = string_filter("status")
    rows = db.corrections_of_tag(tag_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many(page), limit, offset, total)


def _resolution_guards(principal, correction):
    # rank 7 then rank 16
    if principal.user_id == correction["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The author of a correction request may not resolve it.")
    if correction["status"] != "SUBMITTED":
        raise ApiError("ERR_CORRECTION_ALREADY_RESOLVED",
                       "The correction request has already been resolved.")


@bp.post("/correction-requests/<correction_id>/approve")
def approve_correction_request(correction_id):
    principal = authenticate("QualityReviewer")
    correction = require_correction_request(correction_id)
    no_body()
    _resolution_guards(principal, correction)

    tag = store.event_tags.get(correction["event_tag_id"])
    game = store.games.get(tag["game_id"]) if tag is not None else None

    # rank 40: the proposed replacement must itself be eligible
    if correction["reason_code"] == "WRONG_PLAYER":
        proposed = store.players.get(correction["proposed_player_id"])
        if (game is None or proposed is None
                or proposed["club_id"] not in (game["home_club_id"],
                                               game["away_club_id"])):
            raise ApiError("ERR_PLAYER_NOT_IN_GAME",
                           "The proposed replacement player is not on either "
                           "club's roster for this game.")

    correction["status"] = "APPROVED"
    correction["reviewed_by_user_id"] = principal.user_id
    correction["resolved_at_utc"] = store.clock_raw
    touch(correction)

    if tag is not None:
        tag["review_status"] = "ACCEPTED"
        if correction["reason_code"] == "WRONG_CLOCK":
            tag["corrected_clock_ms"] = correction["proposed_clock_ms"]
        elif correction["reason_code"] == "WRONG_PLAYER":
            tag["player_id"] = correction["proposed_player_id"]
        tag["correction_count"] = tag["correction_count"] + 1
        touch(tag)

    if game is not None:
        game["approved_correction_count"] = game["approved_correction_count"] + 1
        move_census(game, "UNDER_CORRECTION", "ACCEPTED")
        recompute_quality_index(game)
        # The official record was altered: certify again from scratch.
        if game["certification_status"] == "DISPUTED":
            game["certification_status"] = "PROVISIONAL"
        touch(game)
    return object_response(serialize(correction))


@bp.post("/correction-requests/<correction_id>/reject")
def reject_correction_request(correction_id):
    principal = authenticate("QualityReviewer")
    correction = require_correction_request(correction_id)
    no_body()
    _resolution_guards(principal, correction)

    correction["status"] = "REJECTED"
    correction["reviewed_by_user_id"] = principal.user_id
    correction["resolved_at_utc"] = store.clock_raw
    touch(correction)

    tag = store.event_tags.get(correction["event_tag_id"])
    game = store.games.get(tag["game_id"]) if tag is not None else None

    if tag is not None:
        # Every field unchanged, correction_count unchanged.
        tag["review_status"] = "ACCEPTED"
        touch(tag)

    if game is not None:
        game["rejected_correction_count"] = game["rejected_correction_count"] + 1
        move_census(game, "UNDER_CORRECTION", "ACCEPTED")
        recompute_quality_index(game)
        # Nothing about the official record changed, so OFFICIAL is restored
        # directly and certified_at_utc is preserved untouched.
        if (game["certification_status"] == "DISPUTED"
                and game["under_correction_tag_count"] == 0):
            game["certification_status"] = "OFFICIAL"
        touch(game)
    return object_response(serialize(correction))
