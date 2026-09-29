"""Rating appeals: filing with pinned snapshots, review, and the two decision branches."""

from decimal import Decimal

from flask import Blueprint

import committee
import derive
from auth import authenticate
from errors import ApiError
from response import object_response
from routes_common import CHAIR_ONLY, found, listing, reference
from store import db, insert, new_id, now_iso, public, touch
from validation import (body, check_level, level_out, opt_string, reject_unknown, req_enum,
                        req_numeric, req_string, to_level)

bp = Blueprint("appeal", __name__)

APPEAL_READ_ROLES = ("SectionAdmin", "LeagueCoordinator", "Player", "CommitteeMember",
                     "CommitteeChair")
DIRECTIONS = ("UP", "DOWN")
OPEN_APPEAL_STATUSES = ("SUBMITTED", "UNDER_REVIEW")
STEP = Decimal("0.5")


@bp.post("/rating-appeals")
def file_appeal():
    actor = authenticate(("Player",))
    payload = body()

    raw_player = payload.get("player_id")
    if isinstance(raw_player, str) and raw_player.strip():
        if raw_player.strip() != actor.user_id:
            raise ApiError("ERR_NOT_SELF")
        player = reference("players", raw_player.strip())
    else:
        player = None

    reject_unknown(payload, {"player_id", "direction", "requested_level", "reason"})
    req_string(payload, "player_id", 1)
    direction = req_enum(payload, "direction", DIRECTIONS)
    requested = req_numeric(payload, "requested_level")
    reason = req_string(payload, "reason", 1)
    if player is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    check_level(requested)
    level = to_level(player.get("rating_level"))
    if level is None:
        raise ApiError("ERR_INVALID_RATING_LEVEL")
    expected = level + STEP if direction == "UP" else level - STEP
    if requested != expected:
        raise ApiError("ERR_INVALID_RATING_LEVEL")

    for other in db.rating_appeals.values():
        if other.get("player_id") == player["id"] and other.get("status") in OPEN_APPEAL_STATUSES:
            raise ApiError("ERR_APPEAL_ALREADY_OPEN")

    pinned_dynamic = player.get("dynamic_rating")
    record = {
        "id": new_id(),
        "player_id": player["id"],
        "direction": direction,
        "requested_level": float(requested),
        "reason": reason,
        "status": "SUBMITTED",
        "rating_level_at_filing": float(level),
        "dynamic_rating_at_filing": pinned_dynamic,
        "verified_match_count_at_filing": int(player.get("verified_match_count") or 0),
        "strike_count_at_filing": int(player.get("strike_count") or 0),
        "auto_grant_eligible": False,
        "support_vote_count": 0,
        "oppose_vote_count": 0,
        "decided_by_chair_player_id": None,
        "decided_at": None,
        "decision_note": None,
        "granted_level": None,
    }
    record["auto_grant_eligible"] = committee.auto_grant_evaluation(
        direction, requested, player.get("rating_type"), record["rating_level_at_filing"],
        record["dynamic_rating_at_filing"], record["verified_match_count_at_filing"],
        record["strike_count_at_filing"])
    insert("rating_appeals", record)
    return object_response(public(record), 201)


@bp.get("/rating-appeals/<appeal_id>")
def get_appeal(appeal_id):
    authenticate(APPEAL_READ_ROLES)
    return object_response(public(found("rating_appeals", appeal_id)))


@bp.get("/rating-appeals")
def list_appeals():
    authenticate(APPEAL_READ_ROLES)
    spec = {"player_id": ("player_id", "str"),
            "decided_by_chair_player_id": ("decided_by_chair_player_id", "str"),
            "direction": ("direction", "str"), "status": ("status", "str"),
            "auto_grant_eligible": ("auto_grant_eligible", "bool")}
    return listing(db.rating_appeals.values(), spec)


@bp.post("/rating-appeals/<appeal_id>/start-review")
def start_appeal_review(appeal_id):
    authenticate(CHAIR_ONLY)
    appeal = found("rating_appeals", appeal_id)
    reject_unknown(body(), set())

    if appeal.get("status") != "SUBMITTED":
        raise ApiError("ERR_APPEAL_STATE_FORBIDS_ACTION")
    player = db.players.get(appeal.get("player_id")) or {}
    section = db.sections.get(player.get("section_id")) or {}
    if section.get("rating_period_status") not in ("OPEN_SEASON", "RECALC_IN_PROGRESS"):
        raise ApiError("ERR_RATING_PERIOD_CLOSED")

    appeal["status"] = "UNDER_REVIEW"
    touch(appeal)
    return object_response(public(appeal))


@bp.post("/rating-appeals/<appeal_id>/decide")
def decide_appeal(appeal_id):
    actor = authenticate(CHAIR_ONLY)
    appeal = found("rating_appeals", appeal_id)
    if committee.chair_voted("RATING_APPEAL", appeal["id"], actor.user_id):
        raise ApiError("ERR_CHAIR_VOTED_ON_SUBJECT")
    payload = body()
    reject_unknown(payload, {"outcome", "decision_note"})
    outcome = req_enum(payload, "outcome", ("GRANT", "DENY"))
    note = opt_string(payload, "decision_note", None, 1)

    if appeal.get("status") != "UNDER_REVIEW":
        raise ApiError("ERR_APPEAL_STATE_FORBIDS_ACTION")

    player = db.players.get(appeal.get("player_id")) or {}
    section = db.sections.get(player.get("section_id")) or {}
    auto = bool(appeal.get("auto_grant_eligible"))

    if outcome == "GRANT":
        if section.get("rating_period_status") != "OPEN_SEASON":
            raise ApiError("ERR_RATING_PERIOD_CLOSED")
        if not auto and not committee.quorum_met(appeal):
            raise ApiError("ERR_QUORUM_NOT_MET")
        live = to_level(player.get("rating_level"))
        pinned = to_level(appeal.get("rating_level_at_filing"))
        if live is None or pinned is None or live != pinned:
            raise ApiError("ERR_APPEAL_BASELINE_STALE")
    elif auto:
        raise ApiError("ERR_AUTO_GRANT_MUST_BE_GRANTED")

    stamp = now_iso()
    appeal["decided_by_chair_player_id"] = actor.user_id
    appeal["decided_at"] = stamp
    appeal["decision_note"] = note

    if outcome == "DENY":
        appeal["status"] = "DENIED"
        touch(appeal)
        return object_response(public(appeal))

    granted = to_level(appeal.get("requested_level"))
    appeal["status"] = "GRANTED"
    appeal["granted_level"] = level_out(granted)
    touch(appeal)

    player["rating_level"] = level_out(granted)
    player["rating_type"] = "APPEAL_GRANTED"
    derive.append_rating_history(player, "APPEAL", granted, player.get("dynamic_rating"),
                                section.get("season_year"), stamp)
    touch(player)

    if appeal.get("direction") == "UP":
        def below_band(team):
            league = db.leagues.get(team.get("league_id")) or {}
            band = to_level(league.get("ntrp_level"))
            return band is not None and band < granted

        derive.suspend_roster_spots(player, "APPEAL_GRANTED", None, below_band)
    return object_response(public(appeal))
