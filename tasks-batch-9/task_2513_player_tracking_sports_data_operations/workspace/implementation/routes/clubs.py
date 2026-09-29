"""Clubs, rosters and the consent chain (PRD §3.3)."""

from flask import Blueprint

import db
from auth import authenticate
from calc import CBA_CURRENT_VERSION, CONSENT_SCOPES
from db import audit_new, new_id, store, touch
from errors import ApiError
from lookups import require_club, require_consent_record, require_player
from response import array_response, object_response
from services.consent import consent_loss_cascade
from util import parse_dt, serialize, serialize_many, sorted_rows
from validation import (field, no_body, paginate, pagination, string_filter,
                        validate_body)

bp = Blueprint("clubs", __name__)

CLUB_SPEC = {
    "name": field("string"),
    "market_code": field("string"),
}

PLAYER_SPEC = {
    "club_id": field("string"),
    "full_name": field("string"),
    "jersey_number": field("integer", minimum=0, maximum=99),
}

CONSENT_SPEC = {
    "scope": field("enum", values=CONSENT_SCOPES),
    "cba_agreement_version": field("string"),
    "effective_from_utc": field("datetime"),
    "expires_at_utc": field("datetime"),
}


# --------------------------------------------------------------------------
# Clubs
# --------------------------------------------------------------------------

@bp.post("/clubs")
def create_club():
    authenticate("LeagueDataOps")
    body = validate_body(CLUB_SPEC)
    club = {
        "id": new_id(),
        "name": body["name"],
        "market_code": body["market_code"],
        "roster_size": 0,
    }
    audit_new(club)
    store.clubs[club["id"]] = club
    return object_response(serialize(club), 201)


@bp.get("/clubs/<club_id>")
def get_club(club_id):
    authenticate("LeagueDataOps", "ClubDataOfficer")
    club = require_club(club_id)
    return object_response(serialize(club))


# --------------------------------------------------------------------------
# Players
# --------------------------------------------------------------------------

@bp.post("/players")
def create_player():
    authenticate("LeagueDataOps", "ClubDataOfficer")
    body = validate_body(PLAYER_SPEC)
    club = require_club(body["club_id"])
    player = {
        "id": new_id(),
        "club_id": body["club_id"],
        "full_name": body["full_name"],
        "jersey_number": body["jersey_number"],
        "biometric_release_state": "NONE",
        "active_consent_record_id": None,
        "masked_tag_count": 0,
    }
    audit_new(player)
    store.players[player["id"]] = player
    club["roster_size"] = club["roster_size"] + 1
    touch(club)
    return object_response(serialize(player), 201)


@bp.get("/players/<player_id>")
def get_player(player_id):
    authenticate("LeagueDataOps", "ClubDataOfficer", "Statistician",
                 "QualityReviewer")
    player = require_player(player_id)
    return object_response(serialize(player))


@bp.get("/players")
def list_players():
    authenticate("LeagueDataOps", "ClubDataOfficer", "Statistician",
                 "QualityReviewer")
    limit, offset = pagination()
    club_id = string_filter("club_id")
    rows = list(store.players.values())
    if club_id is not None:
        rows = [r for r in rows if r["club_id"] == club_id]
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many(page), limit, offset, total)


# --------------------------------------------------------------------------
# Consent records
# --------------------------------------------------------------------------

@bp.post("/players/<player_id>/consent-records")
def create_consent_record(player_id):
    principal = authenticate("ClubDataOfficer")
    player = require_player(player_id)
    body = validate_body(CONSENT_SPEC)

    # rank 6: the filing officer must act for the club holding the registration
    if principal.user_id != player["club_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "A club data officer may only file consent for its own "
                       "players.")

    # rank 22: collective bargaining version
    if body["cba_agreement_version"] != CBA_CURRENT_VERSION:
        raise ApiError("ERR_CBA_VERSION_MISMATCH",
                       "cba_agreement_version must equal %s."
                       % CBA_CURRENT_VERSION)

    # rank 24: consent temporal sanity
    _check_consent_interval(body["effective_from_utc"], body["expires_at_utc"])

    # rank 29: consent uniqueness, per scope
    for existing in db.consent_records_of_player(player_id):
        if existing["scope"] == body["scope"] and existing["status"] in (
                "PENDING", "ACTIVE"):
            raise ApiError("ERR_CONSENT_ALREADY_PENDING",
                           "The player already holds a live consent record for "
                           "this scope.")

    record = {
        "id": new_id(),
        "player_id": player_id,
        "scope": body["scope"],
        "cba_agreement_version": body["cba_agreement_version"],
        "effective_from_utc": body["effective_from_utc"],
        "expires_at_utc": body["expires_at_utc"],
        "status": "PENDING",
        "submitted_by_club_id": principal.user_id,
        "ratified_by_user_id": None,
        "terminated_at_utc": None,
    }
    audit_new(record)
    store.consent_records[record["id"]] = record
    return object_response(serialize(record), 201)


def _check_consent_interval(effective_from, expires_at):
    start = parse_dt(effective_from)
    end = parse_dt(expires_at)
    if start is None or end is None or not (start < end) or not (end > store.clock):
        raise ApiError("ERR_CONSENT_EXPIRY_IN_PAST",
                       "effective_from_utc must precede expires_at_utc and "
                       "expires_at_utc must be later than the logical clock.")


@bp.get("/players/<player_id>/consent-records")
def list_consent_records(player_id):
    authenticate("LeagueDataOps", "ClubDataOfficer")
    require_player(player_id)
    limit, offset = pagination()
    status = string_filter("status")
    rows = db.consent_records_of_player(player_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many(page), limit, offset, total)


@bp.post("/consent-records/<record_id>/ratify")
def ratify_consent_record(record_id):
    principal = authenticate("LeagueDataOps")
    record = require_consent_record(record_id)
    no_body()

    # rank 17: consent lifecycle
    if record["status"] != "PENDING":
        raise ApiError("ERR_INVALID_CONSENT_STATE",
                       "Only a PENDING consent record may be ratified.")

    # rank 22 then rank 24, both re-applied at ratification time
    if record["cba_agreement_version"] != CBA_CURRENT_VERSION:
        raise ApiError("ERR_CBA_VERSION_MISMATCH",
                       "cba_agreement_version must equal %s."
                       % CBA_CURRENT_VERSION)
    _check_consent_interval(record["effective_from_utc"], record["expires_at_utc"])

    record["status"] = "ACTIVE"
    record["ratified_by_user_id"] = principal.user_id
    touch(record)

    player = store.players.get(record["player_id"])
    if player is not None:
        player["active_consent_record_id"] = record["id"]
        if record["scope"] == "BIOMETRIC_TRACKING":
            player["biometric_release_state"] = "GRANTED"
        touch(player)
    return object_response(serialize(record))


@bp.post("/consent-records/<record_id>/withdraw")
def withdraw_consent_record(record_id):
    principal = authenticate("ClubDataOfficer")
    record = require_consent_record(record_id)
    no_body()

    player = store.players.get(record["player_id"])

    # rank 6: ownership
    if player is None or principal.user_id != player["club_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "A club data officer may only withdraw consent for its "
                       "own players.")

    # rank 17: consent lifecycle
    if record["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_CONSENT_STATE",
                       "Only an ACTIVE consent record may be withdrawn.")

    record["status"] = "WITHDRAWN"
    record["terminated_at_utc"] = store.clock_raw
    touch(record)

    if player.get("active_consent_record_id") == record["id"]:
        player["active_consent_record_id"] = None
    consent_loss_cascade(player, "CONSENT_WITHDRAWN", "WITHDRAWN")
    touch(player)
    return object_response(serialize(record))
