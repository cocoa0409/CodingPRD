"""Discipline domain: strikes, the compensating rescission and committee votes."""

from flask import Blueprint

import committee
import derive
from auth import authenticate
from errors import ApiError
from response import object_response
from routes_common import ALL_ROLES, CHAIR_ONLY, MEMBER_ONLY, found, listing, reference
from store import db, insert, new_id, public, touch
from validation import body, present, reject_unknown, req_enum, req_string, to_level

import routes_appeal as appeal_routes
import routes_grievance as grievance_routes

bp = Blueprint("discipline", __name__, url_prefix="/tennis")
bp.register_blueprint(appeal_routes.bp)
bp.register_blueprint(grievance_routes.bp)

STRIKE_ISSUE_ROLES = ("LeagueCoordinator", "CommitteeChair")
STRIKE_KINDS = ("SELF_RATE_VIOLATION", "INELIGIBLE_LINEUP", "NO_SHOW_DEFAULT",
                "SCORECARD_FALSIFICATION")
VOTE_READ_ROLES = ("SectionAdmin", "CommitteeChair", "CommitteeMember")
VOTES = ("SUPPORT", "OPPOSE", "ABSTAIN")


# ------------------------------------------------------------------ strikes ---

@bp.post("/strikes")
def issue_strike():
    authenticate(STRIKE_ISSUE_ROLES)
    payload = body()

    player = _ref(payload, "player_id", "players")
    match = _ref(payload, "match_id", "matches")
    if player is not None and match is not None:
        league = db.leagues.get(match.get("league_id")) or {}
        if player.get("section_id") != league.get("section_id"):
            raise ApiError("ERR_SECTION_SCOPE_MISMATCH")

    reject_unknown(payload, {"player_id", "match_id", "kind", "reason"})
    req_string(payload, "player_id", 1)
    if payload.get("match_id") is not None:
        req_string(payload, "match_id", 1)
    kind = req_enum(payload, "kind", STRIKE_KINDS)
    reason = req_string(payload, "reason", 1)
    if player is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    if payload.get("match_id") is not None and match is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    record = {
        "id": new_id(),
        "player_id": player["id"],
        "match_id": match["id"] if match else None,
        "source_grievance_id": None,
        "kind": kind,
        "weight": derive.STRIKE_WEIGHTS[kind],
        "status": "ACTIVE",
        "reason": reason,
        "rescinded_reason": None,
    }
    insert("strikes", record)
    derive.recompute_strike_ledger(player, record["id"])
    return object_response(public(record), 201)


def _ref(payload, field, collection):
    raw = payload.get(field)
    if isinstance(raw, str) and raw.strip():
        return reference(collection, raw.strip())
    return None


@bp.get("/strikes/<strike_id>")
def get_strike(strike_id):
    authenticate(ALL_ROLES)
    return object_response(public(found("strikes", strike_id)))


@bp.get("/strikes")
def list_strikes():
    authenticate(ALL_ROLES)
    spec = {"player_id": ("player_id", "str"), "match_id": ("match_id", "str"),
            "source_grievance_id": ("source_grievance_id", "str"),
            "kind": ("kind", "str"), "status": ("status", "str")}
    return listing(db.strikes.values(), spec)


@bp.post("/strikes/<strike_id>/rescind")
def rescind_strike(strike_id):
    authenticate(CHAIR_ONLY)
    strike = found("strikes", strike_id)
    payload = body()
    reject_unknown(payload, {"rescinded_reason"})
    rescinded_reason = req_string(payload, "rescinded_reason", 1)

    if strike.get("status") != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    player = db.players.get(strike.get("player_id")) or {}
    section = db.sections.get(player.get("section_id")) or {}
    if player.get("status") == "DISQUALIFIED":
        remaining = sum(int(s.get("weight") or 0) for s in db.strikes.values()
                        if s.get("player_id") == player.get("id")
                        and s.get("status") == "ACTIVE" and s["id"] != strike["id"])
        if remaining < int(section.get("disqualification_strike_limit") or 6):
            raise ApiError("ERR_PLAYER_DISQUALIFIED_PERMANENT")

    strike["status"] = "RESCINDED"
    strike["rescinded_reason"] = rescinded_reason
    touch(strike)
    derive.recompute_strike_ledger(player)
    _restore_spots(player, strike["id"])
    return object_response(public(strike))


def _restore_spots(player, strike_id):
    if player.get("status") != "ACTIVE":
        return
    level = to_level(player.get("rating_level"))
    teams = {}
    for spot in db.roster_spots.values():
        if (spot.get("player_id") != player.get("id") or spot.get("status") != "INELIGIBLE"
                or spot.get("ineligible_reason") != "PLAYER_SUSPENDED"
                or spot.get("source_strike_id") != strike_id):
            continue
        team = db.teams.get(spot.get("team_id"))
        if team is None:
            continue
        league = db.leagues.get(team.get("league_id")) or {}
        band = to_level(league.get("ntrp_level"))
        if level is not None and band is not None and level > band:
            continue
        spot["status"] = "ACTIVE"
        spot["ineligible_reason"] = None
        spot["source_strike_id"] = None
        touch(spot)
        teams[team["id"]] = team
    leagues = {}
    for team in teams.values():
        derive.recompute_team_roster(team)
        league = db.leagues.get(team.get("league_id"))
        if league is not None:
            leagues[league["id"]] = league
    for league in leagues.values():
        derive.recompute_league_counters(league)


# ---------------------------------------------------------- committee votes ---

@bp.post("/committee-votes")
def cast_vote():
    actor = authenticate(MEMBER_ONLY)
    payload = body()

    raw_type = payload.get("subject_type")
    raw_id = payload.get("subject_id")
    subject = None
    if raw_type in committee.SUBJECT_TYPES and isinstance(raw_id, str) and raw_id.strip():
        subject = committee.resolve_subject(raw_type, raw_id.strip())
        if subject is not None and _interested(raw_type, subject, actor.user_id):
            raise ApiError("ERR_SOD_INTERESTED_PARTY")

    reject_unknown(payload, {"subject_type", "subject_id", "vote", "note"})
    subject_type = req_enum(payload, "subject_type", committee.SUBJECT_TYPES)
    subject_id = req_string(payload, "subject_id", 1)
    vote = req_enum(payload, "vote", VOTES)
    note = None
    if present(payload, "note"):
        note = req_string(payload, "note", 1)

    if subject is not None and subject.get("status") != "UNDER_REVIEW":
        raise ApiError("ERR_SUBJECT_NOT_UNDER_REVIEW")
    if subject is None:
        raise ApiError("ERR_SUBJECT_TYPE_MISMATCH")

    for existing in committee.votes_for(subject_type, subject_id):
        if existing.get("voter_player_id") == actor.user_id:
            raise ApiError("ERR_DUPLICATE_VOTE")

    record = {
        "id": new_id(),
        "subject_type": subject_type,
        "subject_id": subject["id"],
        "voter_player_id": actor.user_id,
        "vote": vote,
        "note": note,
    }
    insert("committee_votes", record, versioned=False)
    committee.recount_votes(subject_type, subject)
    return object_response(public(record), 201)


def _interested(subject_type, subject, member_id):
    if subject_type == "RATING_APPEAL":
        return subject.get("player_id") == member_id
    if subject.get("filed_by_captain_player_id") == member_id:
        return True
    if subject.get("remedy_target_player_id") == member_id:
        return True
    team = db.teams.get(subject.get("against_team_id")) or {}
    return team.get("captain_player_id") == member_id


@bp.get("/committee-votes/<vote_id>")
def get_vote(vote_id):
    authenticate(VOTE_READ_ROLES)
    return object_response(public(found("committee_votes", vote_id)))
