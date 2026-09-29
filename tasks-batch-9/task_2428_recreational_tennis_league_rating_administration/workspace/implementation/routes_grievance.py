"""Grievances: filing, review, withdrawal and the three remedy cascade families."""

from decimal import Decimal

from flask import Blueprint

import committee
import credit
import derive
import routes_league_lifecycle as lifecycle
from auth import authenticate
from errors import ApiError
from response import object_response
from routes_common import CAPTAIN_ONLY, CHAIR_ONLY, found, listing, reference
from store import (add_hours, db, insert, new_id, now, now_iso, parse_instant, public, touch)
from validation import body, opt_string, reject_unknown, req_enum, req_string, to_level

bp = Blueprint("grievance", __name__)

GRIEVANCE_READ_ROLES = ("SectionAdmin", "LeagueCoordinator", "Captain", "CommitteeMember",
                        "CommitteeChair")
KINDS = ("INELIGIBLE_LINEUP", "SCORE_FALSIFICATION", "DEFAULT_ABUSE", "RATING_VIOLATION")
MATCH_KINDS = ("INELIGIBLE_LINEUP", "SCORE_FALSIFICATION", "DEFAULT_ABUSE")
REMEDIES = ("MATCH_FORFEIT", "PLAYER_STRIKE", "TEAM_DISQUALIFICATION")
LEVEL_STEP = Decimal("0.5")


def subject_invalid():
    raise ApiError("ERR_GRIEVANCE_SUBJECT_INVALID")


@bp.post("/grievances")
def file_grievance():
    actor = authenticate(CAPTAIN_ONLY)
    payload = body()

    league = _ref(payload, "league_id", "leagues")
    against = _ref(payload, "against_team_id", "teams")
    subject_match = _ref(payload, "subject_match_id", "matches")
    target = _ref(payload, "remedy_target_player_id", "players")

    reject_unknown(payload, {"league_id", "against_team_id", "subject_match_id", "kind",
                            "remedy_target_player_id", "statement"})
    req_string(payload, "league_id", 1)
    req_string(payload, "against_team_id", 1)
    kind = req_enum(payload, "kind", KINDS)
    statement = req_string(payload, "statement", 1)
    if payload.get("subject_match_id") is not None:
        req_string(payload, "subject_match_id", 1)
    if payload.get("remedy_target_player_id") is not None:
        req_string(payload, "remedy_target_player_id", 1)
    if league is None or against is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    if payload.get("subject_match_id") is not None and subject_match is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    if payload.get("remedy_target_player_id") is not None and target is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    if against.get("league_id") != league["id"]:
        subject_invalid()
    if against.get("captain_player_id") == actor.user_id:
        subject_invalid()
    if kind in MATCH_KINDS and subject_match is None:
        subject_invalid()
    if kind == "RATING_VIOLATION" and subject_match is not None:
        subject_invalid()
    if subject_match is not None:
        if subject_match.get("league_id") != league["id"]:
            subject_invalid()
        if against["id"] not in (subject_match.get("home_team_id"),
                                subject_match.get("away_team_id")):
            subject_invalid()
    if target is not None and not _holds_spot(target["id"], against["id"]):
        subject_invalid()

    section = db.sections.get(league.get("section_id")) or {}
    anchor = _window_anchor(kind, subject_match, target)
    if anchor is not None:
        deadline = add_hours(anchor, int(section.get("grievance_window_hours") or 0))
        if now() > deadline:
            raise ApiError("ERR_GRIEVANCE_WINDOW_EXPIRED")

    record = {
        "id": new_id(),
        "league_id": league["id"],
        "filed_by_captain_player_id": actor.user_id,
        "against_team_id": against["id"],
        "subject_match_id": subject_match["id"] if subject_match else None,
        "kind": kind,
        "status": "FILED",
        "remedy": None,
        "remedy_target_player_id": target["id"] if target else None,
        "statement": statement,
        "support_vote_count": 0,
        "oppose_vote_count": 0,
        "decided_by_chair_player_id": None,
        "decided_at": None,
        "decision_note": None,
    }
    insert("grievances", record)
    return object_response(public(record), 201)


def _ref(payload, field, collection):
    raw = payload.get(field)
    if isinstance(raw, str) and raw.strip():
        return reference(collection, raw.strip())
    return None


def _holds_spot(player_id, team_id):
    for spot in db.roster_spots.values():
        if (spot.get("player_id") == player_id and spot.get("team_id") == team_id
                and spot.get("status") in ("ACTIVE", "INELIGIBLE")):
            return True
    return False


def _window_anchor(kind, subject_match, target):
    if kind in MATCH_KINDS:
        start = (subject_match or {}).get("scheduled_start_at")
        return parse_instant(start) if start else None
    latest = None
    for appeal in db.rating_appeals.values():
        if target is not None and appeal.get("player_id") != target["id"]:
            continue
        if target is None:
            continue
        if appeal.get("decided_at") is None:
            continue
        instant = parse_instant(appeal["decided_at"])
        if latest is None or instant > latest:
            latest = instant
    return latest


@bp.get("/grievances/<grievance_id>")
def get_grievance(grievance_id):
    authenticate(GRIEVANCE_READ_ROLES)
    return object_response(public(found("grievances", grievance_id)))


@bp.get("/grievances")
def list_grievances():
    authenticate(GRIEVANCE_READ_ROLES)
    spec = {"league_id": ("league_id", "str"),
            "filed_by_captain_player_id": ("filed_by_captain_player_id", "str"),
            "against_team_id": ("against_team_id", "str"),
            "subject_match_id": ("subject_match_id", "str"),
            "remedy_target_player_id": ("remedy_target_player_id", "str"),
            "decided_by_chair_player_id": ("decided_by_chair_player_id", "str"),
            "kind": ("kind", "str"), "status": ("status", "str")}
    return listing(db.grievances.values(), spec)


@bp.post("/grievances/<grievance_id>/start-review")
def start_grievance_review(grievance_id):
    authenticate(CHAIR_ONLY)
    grievance = found("grievances", grievance_id)
    reject_unknown(body(), set())

    if grievance.get("status") != "FILED":
        raise ApiError("ERR_GRIEVANCE_STATE_FORBIDS_ACTION")
    league = db.leagues.get(grievance.get("league_id")) or {}
    if league.get("status") not in ("IN_PLAY", "PLAYOFFS", "COMPLETED"):
        raise ApiError("ERR_INVALID_STATE")

    grievance["status"] = "UNDER_REVIEW"
    touch(grievance)
    return object_response(public(grievance))


@bp.post("/grievances/<grievance_id>/withdraw")
def withdraw_grievance(grievance_id):
    actor = authenticate(CAPTAIN_ONLY)
    grievance = found("grievances", grievance_id)
    if grievance.get("filed_by_captain_player_id") != actor.user_id:
        raise ApiError("ERR_NOT_TEAM_CAPTAIN")
    reject_unknown(body(), set())

    if grievance.get("status") != "FILED":
        raise ApiError("ERR_GRIEVANCE_STATE_FORBIDS_ACTION")
    grievance["status"] = "WITHDRAWN"
    touch(grievance)
    return object_response(public(grievance))


@bp.post("/grievances/<grievance_id>/decide")
def decide_grievance(grievance_id):
    actor = authenticate(CHAIR_ONLY)
    grievance = found("grievances", grievance_id)
    if committee.chair_voted("GRIEVANCE", grievance["id"], actor.user_id):
        raise ApiError("ERR_CHAIR_VOTED_ON_SUBJECT")
    payload = body()
    reject_unknown(payload, {"outcome", "remedy", "decision_note"})
    outcome = req_enum(payload, "outcome", ("UPHOLD", "DISMISS"))
    remedy = None
    if payload.get("remedy") is not None:
        remedy = req_enum(payload, "remedy", REMEDIES)
    note = opt_string(payload, "decision_note", None, 1)

    if grievance.get("status") != "UNDER_REVIEW":
        raise ApiError("ERR_GRIEVANCE_STATE_FORBIDS_ACTION")

    if outcome == "UPHOLD":
        _check_remedy(grievance, remedy)
        if not committee.quorum_met(grievance):
            raise ApiError("ERR_QUORUM_NOT_MET")
    else:
        support = int(grievance.get("support_vote_count") or 0)
        oppose = int(grievance.get("oppose_vote_count") or 0)
        if not (oppose >= 1 or support < committee.QUORUM_SUPPORT):
            raise ApiError("ERR_QUORUM_NOT_MET")

    grievance["decided_by_chair_player_id"] = actor.user_id
    grievance["decided_at"] = now_iso()
    grievance["decision_note"] = note

    if outcome == "DISMISS":
        grievance["status"] = "DISMISSED"
        touch(grievance)
        return object_response(public(grievance))

    grievance["status"] = "UPHELD"
    grievance["remedy"] = remedy
    touch(grievance)
    if remedy == "MATCH_FORFEIT":
        _apply_match_forfeit(grievance)
    elif remedy == "PLAYER_STRIKE":
        _apply_player_strike(grievance)
    else:
        _apply_team_disqualification(grievance)
    return object_response(public(grievance))


def _check_remedy(grievance, remedy):
    if remedy is None:
        raise ApiError("ERR_REMEDY_NOT_ADMISSIBLE")
    if remedy == "MATCH_FORFEIT":
        match = db.matches.get(grievance.get("subject_match_id"))
        if (grievance.get("kind") not in MATCH_KINDS or match is None
                or match.get("result_status") not in ("VERIFIED", "FINALIZED")):
            raise ApiError("ERR_REMEDY_NOT_ADMISSIBLE")
    elif remedy == "PLAYER_STRIKE":
        if grievance.get("remedy_target_player_id") is None:
            raise ApiError("ERR_REMEDY_NOT_ADMISSIBLE")
    else:
        team = db.teams.get(grievance.get("against_team_id")) or {}
        if (grievance.get("kind") not in ("INELIGIBLE_LINEUP", "SCORE_FALSIFICATION")
                or team.get("status") not in ("ROSTER_LOCKED", "IN_PLAY")):
            raise ApiError("ERR_REMEDY_NOT_ADMISSIBLE")


def _apply_match_forfeit(grievance):
    match = db.matches.get(grievance.get("subject_match_id"))
    league = db.leagues.get(match.get("league_id")) or {}
    was_finalized = match.get("result_status") == "FINALIZED"
    accused = grievance.get("against_team_id")
    aggrieved = (match.get("away_team_id") if accused == match.get("home_team_id")
                 else match.get("home_team_id"))

    totals = credit.forfeit_credit(league, match.get("home_team_id"), match.get("away_team_id"),
                                   aggrieved)
    match.update(totals)
    match["result_status"] = "VOIDED"
    match["default_side"] = "HOME" if accused == match.get("home_team_id") else "AWAY"
    touch(match)

    for card in db.scorecards.values():
        if card.get("match_id") == match["id"] and card.get("status") != "VOIDED":
            card["status"] = "VOIDED"
            touch(card)

    derive.cascade_result_change(match)
    if was_finalized and league.get("status") == "PLAYOFFS":
        lifecycle.reseed_league(league)


def _apply_player_strike(grievance):
    player = db.players.get(grievance.get("remedy_target_player_id"))
    if player is None:
        return
    kind = ("SELF_RATE_VIOLATION" if grievance.get("kind") == "RATING_VIOLATION"
            else "SCORECARD_FALSIFICATION")
    derive.issue_strike(player, kind,
                        "Grievance remedy %s" % grievance["id"], None, grievance["id"])
    if grievance.get("kind") != "RATING_VIOLATION":
        return
    level = to_level(player.get("rating_level"))
    if level is None:
        return
    raised = derive.clamp_level(level + LEVEL_STEP)
    section = db.sections.get(player.get("section_id")) or {}
    player["rating_level"] = float(raised)
    player["rating_type"] = "COMMITTEE_ASSIGNED"
    derive.append_rating_history(player, "COMMITTEE", raised, player.get("dynamic_rating"),
                                 section.get("season_year"), now_iso())
    touch(player)


def _apply_team_disqualification(grievance):
    team = db.teams.get(grievance.get("against_team_id"))
    if team is None:
        return
    team["status"] = "DISQUALIFIED"
    touch(team)
    for spot in db.roster_spots.values():
        if spot.get("team_id") == team["id"] and spot.get("status") == "ACTIVE":
            spot["status"] = "INELIGIBLE"
            spot["ineligible_reason"] = "GRIEVANCE_REMEDY"
            spot["source_strike_id"] = None
            touch(spot)
    for match in db.matches.values():
        if team["id"] not in (match.get("home_team_id"), match.get("away_team_id")):
            continue
        if (match.get("schedule_status") in ("SCHEDULED", "CONFIRMED")
                and match.get("result_status") == "PENDING"):
            match["schedule_status"] = "CANCELLED"
            touch(match)
    derive.recompute_team_roster(team)
    derive.recompute_league_counters(db.leagues.get(team.get("league_id")))
