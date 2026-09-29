"""Scorecards: submission, the line legality rules, review and amendment."""

from flask import Blueprint

import credit
import derive
from auth import authenticate, require_match_captain
from errors import ApiError
from response import object_response
from routes_common import ALL_ROLES, CAPTAIN_ONLY, found, listing, reference
from store import db, add_hours, insert, new_id, now, now_iso, parse_instant, public, touch
from validation import bad, body, opt_string, present, reject_unknown, req_enum

bp = Blueprint("scorecard", __name__)

OPEN_SCORECARD_STATUSES = ("SUBMITTED", "DISPUTED", "AMENDED")
LINE_FIELDS = {"line_number", "home_player_ids", "away_player_ids", "set_scores", "default_side"}
SET_FIELDS = {"home_games", "away_games"}


def line_invalid(message=None):
    raise ApiError("ERR_SCORECARD_LINE_INVALID", message)


def _validate_set(entry, is_third):
    if not isinstance(entry, dict):
        bad("Each set score must be an object.")
    for key in entry:
        if key not in SET_FIELDS:
            bad("Unknown field in set score: %s." % key)
    for key in SET_FIELDS:
        if key not in entry or isinstance(entry[key], bool) or not isinstance(entry[key], int):
            bad("Each set score requires integer 'home_games' and 'away_games'.")
    home = entry["home_games"]
    away = entry["away_games"]
    if home < 0 or away < 0:
        line_invalid("Set game counts must not be negative.")
    winner, loser = (home, away) if home > away else (away, home)
    if home == away:
        line_invalid("A set must have a winner.")
    if is_third and winner == 1 and loser == 0:
        return
    if winner == 6 and loser <= 4:
        return
    if winner == 7 and loser in (5, 6):
        return
    line_invalid("Illegal set score %d-%d." % (home, away))


def validate_lines(payload, league):
    raw = payload.get("lines")
    if not isinstance(raw, list):
        bad("Field 'lines' must be an array of line objects.")
    for line in raw:
        if not isinstance(line, dict):
            bad("Each line must be an object.")
        for key in line:
            if key not in LINE_FIELDS:
                bad("Unknown field in line: %s." % key)
        if "line_number" not in line or isinstance(line["line_number"], bool) \
                or not isinstance(line["line_number"], int):
            bad("Each line requires an integer 'line_number'.")
        for side in ("home_player_ids", "away_player_ids"):
            ids = line.get(side)
            if not isinstance(ids, list) or not all(isinstance(i, str) and i for i in ids):
                bad("Field '%s' must be an array of player identifier strings." % side)
        default_side = line.get("default_side")
        if default_side is not None and default_side not in ("HOME", "AWAY"):
            bad("Field 'default_side' must be 'HOME', 'AWAY' or null.")
        sets = line.get("set_scores")
        if sets is not None and not isinstance(sets, list):
            bad("Field 'set_scores' must be an array.")

    count = int(league.get("lines_per_match") or 3)
    if len(raw) != count:
        line_invalid("Exactly %d lines are required." % count)
    numbers = [line["line_number"] for line in raw]
    if len(set(numbers)) != len(numbers):
        line_invalid("Duplicate line_number values.")
    for number in numbers:
        if number < 1 or number > count:
            line_invalid("line_number must run from 1 to %d." % count)
    for line in raw:
        for side in ("home_player_ids", "away_player_ids"):
            ids = line.get(side) or []
            if len(ids) != 2 or ids[0] == ids[1]:
                line_invalid("Each side of a line must name two distinct players.")
        sets = line.get("set_scores") or []
        if line.get("default_side") is not None:
            if sets:
                line_invalid("A defaulted line carries no set scores.")
            continue
        if not sets:
            line_invalid("A played line must carry set scores.")
        if len(sets) < 2 or len(sets) > 3:
            line_invalid("A line is best of three sets.")
        for index, entry in enumerate(sets):
            _validate_set(entry, index == 2)
        home_sets = sum(1 for s in sets if s["home_games"] > s["away_games"])
        away_sets = len(sets) - home_sets
        if max(home_sets, away_sets) != 2 or min(home_sets, away_sets) > 1:
            line_invalid("A line must be won two sets to nil or two sets to one.")
    return sorted(raw, key=lambda line: line["line_number"])


def validate_lineup(match, league, lines):
    seen = set()
    for line in lines:
        for side, team_id in (("home_player_ids", match.get("home_team_id")),
                              ("away_player_ids", match.get("away_team_id"))):
            for player_id in line.get(side) or []:
                player = db.players.get(player_id)
                if player is None:
                    raise ApiError("ERR_INELIGIBLE_LINEUP")
                if player.get("status") in ("STRIKE_SUSPENDED", "DISQUALIFIED"):
                    raise ApiError("ERR_PLAYER_NOT_PLAYABLE")
    if league.get("format") == "MIXED_DOUBLES":
        for line in lines:
            for side in ("home_player_ids", "away_player_ids"):
                genders = sorted((db.players.get(pid) or {}).get("gender")
                                 for pid in line.get(side) or [])
                if genders != ["F", "M"]:
                    raise ApiError("ERR_FORMAT_GENDER_MISMATCH")
    for line in lines:
        for side, team_id in (("home_player_ids", match.get("home_team_id")),
                              ("away_player_ids", match.get("away_team_id"))):
            for player_id in line.get(side) or []:
                if player_id in seen:
                    raise ApiError("ERR_INELIGIBLE_LINEUP")
                seen.add(player_id)
                if not _has_active_spot(player_id, team_id):
                    raise ApiError("ERR_INELIGIBLE_LINEUP")


def _has_active_spot(player_id, team_id):
    for spot in db.roster_spots.values():
        if (spot.get("player_id") == player_id and spot.get("team_id") == team_id
                and spot.get("status") == "ACTIVE"):
            return True
    return False


@bp.post("/scorecards")
def submit_scorecard():
    actor = authenticate(CAPTAIN_ONLY)
    payload = body()
    raw_match = payload.get("match_id")
    match = None
    if isinstance(raw_match, str) and raw_match.strip():
        match = reference("matches", raw_match.strip())
        acting_team = require_match_captain(actor, match)
    reject_unknown(payload, {"match_id", "lines"})
    if not isinstance(raw_match, str) or not raw_match.strip():
        bad("Field 'match_id' is required.")
    if "lines" not in payload:
        bad("Field 'lines' is required.")
    if match is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    league = db.leagues.get(match.get("league_id")) or {}
    lines = validate_lines(payload, league)

    if match.get("schedule_status") != "PLAYED":
        raise ApiError("ERR_MATCH_SCHEDULE_STATE_INVALID")
    if match.get("result_status") != "PENDING":
        raise ApiError("ERR_MATCH_RESULT_STATE_INVALID")

    validate_lineup(match, league, lines)

    for card in db.scorecards.values():
        if card.get("match_id") == match["id"] and card.get("status") in OPEN_SCORECARD_STATUSES:
            raise ApiError("ERR_SCORECARD_ALREADY_OPEN")

    section = db.sections.get(league.get("section_id")) or {}
    deadline = add_hours(parse_instant(match.get("scheduled_end_at")),
                         int(section.get("scorecard_submission_window_hours") or 0))
    if now() > deadline:
        raise ApiError("ERR_SCORECARD_WINDOW_EXPIRED")

    record = {
        "id": new_id(),
        "match_id": match["id"],
        "submitted_by_captain_player_id": actor.user_id,
        "submitted_by_team_id": acting_team["id"] if acting_team else None,
        "verified_by_captain_player_id": None,
        "status": "SUBMITTED",
        "lines": lines,
        "amendment_count": 0,
        "dispute_reason": None,
        "disputed_line_numbers": [],
        "verified_at": None,
    }
    insert("scorecards", record)
    match["result_status"] = "REPORTED"
    touch(match)
    return object_response(public(record), 201)


@bp.get("/scorecards/<scorecard_id>")
def get_scorecard(scorecard_id):
    authenticate(ALL_ROLES)
    return object_response(public(found("scorecards", scorecard_id)))


@bp.get("/scorecards")
def list_scorecards():
    authenticate(ALL_ROLES)
    spec = {"match_id": ("match_id", "str"),
            "submitted_by_team_id": ("submitted_by_team_id", "str"),
            "submitted_by_captain_player_id": ("submitted_by_captain_player_id", "str"),
            "verified_by_captain_player_id": ("verified_by_captain_player_id", "str"),
            "status": ("status", "str")}
    return listing(db.scorecards.values(), spec)


@bp.post("/scorecards/<scorecard_id>/review")
def review_scorecard(scorecard_id):
    actor = authenticate(CAPTAIN_ONLY)
    card = found("scorecards", scorecard_id)
    match = db.matches.get(card.get("match_id"))
    require_match_captain(actor, match)
    payload = body()
    reject_unknown(payload, {"decision", "dispute_reason", "disputed_line_numbers"})
    decision = req_enum(payload, "decision", ("VERIFY", "DISPUTE"))
    dispute_reason = opt_string(payload, "dispute_reason", None, 1)
    reported = [line["line_number"] for line in card.get("lines") or []]
    disputed = None
    if decision == "DISPUTE":
        if present(payload, "disputed_line_numbers"):
            disputed = payload["disputed_line_numbers"]
            if not isinstance(disputed, list) or not disputed:
                bad("Field 'disputed_line_numbers' must be a non-empty array.")
            for number in disputed:
                if isinstance(number, bool) or not isinstance(number, int) or number not in reported:
                    bad("disputed_line_numbers must be a subset of the reported line numbers.")

    if card.get("status") not in ("SUBMITTED", "AMENDED"):
        raise ApiError("ERR_SCORECARD_STATE_FORBIDS_ACTION")
    if card.get("submitted_by_captain_player_id") == actor.user_id:
        raise ApiError("ERR_SELF_VERIFICATION_FORBIDDEN")

    league = db.leagues.get(match.get("league_id")) or {}
    section = db.sections.get(league.get("section_id")) or {}

    if decision == "DISPUTE":
        deadline = add_hours(parse_instant(card.get("updated_at")),
                            int(section.get("scorecard_dispute_window_hours") or 0))
        if now() > deadline:
            raise ApiError("ERR_DISPUTE_WINDOW_EXPIRED")
        card["status"] = "DISPUTED"
        card["dispute_reason"] = dispute_reason
        if disputed is not None:
            card["disputed_line_numbers"] = list(disputed)
        touch(card)
        match["result_status"] = "DISPUTED"
        touch(match)
        return object_response(public(card))

    card["status"] = "VERIFIED"
    card["verified_by_captain_player_id"] = actor.user_id
    stamp = now_iso()
    card["verified_at"] = stamp
    touch(card)

    totals = credit.resolve_credit(league, match.get("home_team_id"), match.get("away_team_id"),
                                   card.get("lines") or [])
    match.update(totals)
    match["result_status"] = "VERIFIED"
    match["verified_at"] = stamp
    touch(match)
    derive.cascade_result_change(match)
    return object_response(public(card))


@bp.post("/scorecards/<scorecard_id>/amend")
def amend_scorecard(scorecard_id):
    actor = authenticate(CAPTAIN_ONLY)
    card = found("scorecards", scorecard_id)
    match = db.matches.get(card.get("match_id"))
    require_match_captain(actor, match)
    payload = body()
    reject_unknown(payload, {"lines"})
    if "lines" not in payload:
        bad("Field 'lines' is required.")
    league = db.leagues.get(match.get("league_id")) or {}
    lines = validate_lines(payload, league)

    if card.get("status") != "DISPUTED":
        # Amendment is declared only from DISPUTED; rank 20 outranks rank 26.
        raise ApiError("ERR_INVALID_STATE")
    if int(card.get("amendment_count") or 0) >= 2:
        raise ApiError("ERR_AMENDMENT_LIMIT_REACHED")
    if card.get("submitted_by_captain_player_id") != actor.user_id:
        raise ApiError("ERR_SELF_VERIFICATION_FORBIDDEN")

    validate_lineup(match, league, lines)

    card["lines"] = lines
    card["amendment_count"] = int(card.get("amendment_count") or 0) + 1
    card["status"] = "AMENDED"
    touch(card)
    match["result_status"] = "REPORTED"
    touch(match)
    return object_response(public(card))
