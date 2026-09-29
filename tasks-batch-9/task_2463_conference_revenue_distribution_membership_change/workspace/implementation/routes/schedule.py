"""Protected rivalries and the competitive schedule (PRD section 3.4)."""

from datetime import timedelta

from flask import Blueprint

import calc
import response
import serializers
import validation
from db import base_record, db, touch
from errors import ApiError
from middleware import api, raw_body
from routes import common
from services import compliance

bp = Blueprint("schedule", __name__)

RIVALRY_READ_ROLES = (
    "Commissioner",
    "ScheduleCoordinator",
    "ComplianceOfficer",
    "Auditor",
    "PlatformAdmin",
    "MemberRepresentative",
)

GAME_READ_ROLES = (
    "Commissioner",
    "ScheduleCoordinator",
    "ComplianceOfficer",
    "FinanceOfficer",
    "Auditor",
    "PlatformAdmin",
    "MemberRepresentative",
)

BLOCKED_PARTICIPANT_STATUSES = ("DEPARTED", "ADMISSION_DENIED")
PLAYABLE_MEMBER_STATUSES = ("ADMITTED_PHASING", "FULL_SHARE", "WITHDRAWAL_NOTICED")


# ---------------------------------------------------------------------------
# Protected rivalries
# ---------------------------------------------------------------------------


@bp.route("/protected-rivalries", methods=["POST"])
@api(("ScheduleCoordinator", "Commissioner"))
def create_rivalry():
    body = raw_body()
    conference_id = validation.get_id(body, "conference_id")
    member_a_id = validation.get_id(body, "member_a_id")
    member_b_id = validation.get_id(body, "member_b_id")
    required_annual_meetings = validation.get_int(
        body, "required_annual_meetings", required=False, default=1, minimum=1
    )
    label = validation.get_optional_str(body, "label")

    common.get_member(member_a_id)
    common.get_member(member_b_id)

    if member_a_id == member_b_id:
        raise ApiError("ERR_MEMBER_PAIR_INVALID")

    pair = frozenset((member_a_id, member_b_id))
    for existing in db.protected_rivalries.values():
        if existing["conference_id"] != conference_id:
            continue
        if frozenset((existing["member_a_id"], existing["member_b_id"])) == pair:
            raise ApiError("ERR_DUPLICATE_RIVALRY")

    rivalry = base_record()
    rivalry.update(
        {
            "conference_id": conference_id,
            "member_a_id": member_a_id,
            "member_b_id": member_b_id,
            "required_annual_meetings": required_annual_meetings,
            "label": label,
            "status": "ACTIVE",
        }
    )
    db.protected_rivalries[rivalry["id"]] = rivalry
    return response.single(serializers.protected_rivalry(rivalry), 201)


@bp.route("/protected-rivalries/<rivalry_id>", methods=["GET"])
@api(RIVALRY_READ_ROLES)
def read_rivalry(rivalry_id):
    return response.single(
        serializers.protected_rivalry(common.get_rivalry(rivalry_id))
    )


@bp.route("/protected-rivalries", methods=["GET"])
@api(RIVALRY_READ_ROLES)
def list_rivalries():
    criteria = {
        "conference_id": common.string_filter("conference_id"),
        "member_a_id": common.string_filter("member_a_id"),
        "member_b_id": common.string_filter("member_b_id"),
        "status": common.string_filter("status"),
    }
    return common.listing(
        list(db.protected_rivalries.values()),
        serializers.protected_rivalry,
        criteria=criteria,
    )


# ---------------------------------------------------------------------------
# Schedule games
# ---------------------------------------------------------------------------


@bp.route("/schedule-games", methods=["POST"])
@api(("ScheduleCoordinator",))
def create_game():
    body = raw_body()
    conference_id = validation.get_id(body, "conference_id")
    home_member_id = validation.get_id(body, "home_member_id")
    away_member_id = validation.get_id(body, "away_member_id")
    venue_id = validation.get_id(body, "venue_id")
    game_date = validation.get_instant(body, "game_date")
    fiscal_year = validation.get_int(body, "fiscal_year", minimum=None)
    media_designated = validation.get_bool(
        body, "media_designated", required=False, default=False
    )
    protected_rivalry_id = validation.get_nullable_id(body, "protected_rivalry_id")

    home = common.get_member(home_member_id)
    away = common.get_member(away_member_id)
    common.get_venue(venue_id)
    if protected_rivalry_id is not None:
        common.get_rivalry(protected_rivalry_id)

    if home_member_id == away_member_id:
        raise ApiError("ERR_MEMBER_PAIR_INVALID")
    for participant in (home, away):
        if participant["status"] in BLOCKED_PARTICIPANT_STATUSES:
            raise ApiError("ERR_MEMBER_STATE_INVALID")

    _assert_rest_buffer((home_member_id, away_member_id), game_date)

    if home["home_venue_id"] != venue_id:
        raise ApiError("ERR_VENUE_NOT_HOME_VENUE")

    game = base_record()
    game.update(
        {
            "conference_id": conference_id,
            "fiscal_year": fiscal_year,
            "home_member_id": home_member_id,
            "away_member_id": away_member_id,
            "venue_id": venue_id,
            "protected_rivalry_id": protected_rivalry_id,
            "game_date": game_date,
            "media_designated": media_designated,
            "status": "SCHEDULED",
        }
    )
    db.schedule_games[game["id"]] = game

    compliance.recompute_many([home, away])
    return response.single(serializers.schedule_game(game), 201)


def _assert_rest_buffer(member_ids, game_date):
    """Neither participant may already play inside the six-day rest buffer."""
    buffer_span = timedelta(days=calc.REST_BUFFER_DAYS)
    for existing in db.schedule_games.values():
        if existing["status"] not in compliance.COUNTED_GAME_STATUSES:
            continue
        participants = (existing["home_member_id"], existing["away_member_id"])
        if not any(member_id in participants for member_id in member_ids):
            continue
        delta = existing["game_date"] - game_date
        if delta < timedelta(0):
            delta = -delta
        if delta < buffer_span:
            raise ApiError("ERR_MEMBER_REST_BUFFER_VIOLATION")


@bp.route("/schedule-games/<game_id>", methods=["GET"])
@api(GAME_READ_ROLES)
def read_game(game_id):
    return response.single(serializers.schedule_game(common.get_game(game_id)))


@bp.route("/schedule-games", methods=["GET"])
@api(GAME_READ_ROLES)
def list_games():
    criteria = {
        "conference_id": common.string_filter("conference_id"),
        "home_member_id": common.string_filter("home_member_id"),
        "away_member_id": common.string_filter("away_member_id"),
        "venue_id": common.string_filter("venue_id"),
        "protected_rivalry_id": common.string_filter("protected_rivalry_id"),
        "fiscal_year": common.int_filter("fiscal_year"),
        "media_designated": common.bool_filter("media_designated"),
        "status": common.string_filter("status"),
    }
    return common.listing(
        list(db.schedule_games.values()), serializers.schedule_game, criteria=criteria
    )


@bp.route("/schedule-games/<game_id>/play", methods=["POST"])
@api(("ScheduleCoordinator", "ComplianceOfficer"))
def play_game(game_id):
    game = common.get_game(game_id)
    if game["status"] != "SCHEDULED":
        raise ApiError("ERR_GAME_STATE_INVALID")

    participants = [
        db.members.get(game["home_member_id"]),
        db.members.get(game["away_member_id"]),
    ]
    for participant in participants:
        if participant is None or participant["status"] not in PLAYABLE_MEMBER_STATUSES:
            raise ApiError("ERR_MEMBER_STATE_INVALID")

    game["status"] = "PLAYED"
    touch(game)
    compliance.recompute_many(participants)
    return response.single(serializers.schedule_game(game))


@bp.route("/schedule-games/<game_id>/cancel", methods=["POST"])
@api(("ScheduleCoordinator", "Commissioner"))
def cancel_game(game_id):
    game = common.get_game(game_id)
    body = raw_body()
    validation.get_optional_str(body, "reason")

    if game["status"] != "SCHEDULED":
        raise ApiError("ERR_GAME_STATE_INVALID")

    game["status"] = "CANCELLED"
    touch(game)

    affected = [
        db.members.get(game["home_member_id"]),
        db.members.get(game["away_member_id"]),
    ]
    rivalry_id = game.get("protected_rivalry_id")
    if rivalry_id:
        rivalry = db.protected_rivalries.get(rivalry_id)
        if rivalry is not None and compliance.lapse_rivalry_if_unmet(rivalry):
            affected.extend(compliance.counterparts(rivalry))

    compliance.recompute_many(affected)
    return response.single(serializers.schedule_game(game))
