"""Injury designations and physical exams (PRD 3.5)."""
from flask import Blueprint

import calc
import domain
import shape
import views
from auth import (
    LEAGUE_OFFICER, TEAM_CAP_ANALYST, TEAM_MEDICAL_OFFICER, endpoint,
    require_team_scope,
)
from envelope import filter_records, paginate, single
from errors import fail
from store import base_record, db, days, touch, values

bp = Blueprint("medical", __name__)

DESIGNATION_TYPES = (
    "INJURED_RESERVE", "INJURED_RESERVE_RETURN_ELIGIBLE", "NON_ROSTER_INJURY",
)
EXAM_TYPES = ("ENTRY_PHYSICAL", "TRADE_PHYSICAL", "RETURN_PHYSICAL")


@bp.route("/injury-designations", methods=["POST"])
@endpoint(TEAM_MEDICAL_OFFICER)
def create_designation(actor):
    body = shape.body()
    raw_team = shape.raw(body, "team_id")
    if isinstance(raw_team, str) and raw_team.strip() != actor.user_id:
        fail("ERR_ACTOR_SCOPE_VIOLATION", "designation belongs to another club")
    player_id = shape.req_ref(body, "player_id")
    team_id = shape.req_ref(body, "team_id")
    require_team_scope(actor, team_id)
    designation_type = shape.req_enum(body, "designation_type", DESIGNATION_TYPES)
    player = domain.get_player(player_id)
    team = domain.get_team(team_id)
    # Rule 13: the player must be on this club's roster and ACTIVE or RESERVE.
    if player["current_team_id"] != team_id:
        fail("ERR_INVALID_DESIGNATION_STATE", "player is not on this club's roster")
    if player["roster_designation"] not in ("ACTIVE", "RESERVE"):
        fail("ERR_INVALID_DESIGNATION_STATE", "player must be ACTIVE or RESERVE")
    # Rule 32: one open designation per player.
    for existing in values(db.injury_designations, lambda d: d["player_id"] == player_id):
        if existing["status"] in domain.OPEN_DESIGNATION_STATUSES:
            fail("ERR_INJURY_DESIGNATION_ALREADY_OPEN", "player already has an open designation")
    record = base_record()
    record.update({
        "player_id": player_id,
        "team_id": team_id,
        "designation_type": designation_type,
        "status": "PENDING_PAPERWORK",
        "paperwork_reference": None,
        "placed_at": db.clock,
        "paperwork_filed_at": None,
        "activated_at": None,
        "minimum_stay_days": calc.MINIMUM_STAY_DAYS[designation_type],
        "return_window_opens_at": None,
        "return_window_closes_at": None,
        "ir_service_credit_days": None,
        "closed_at": None,
    })
    db.injury_designations[record["id"]] = record
    return single(views.injury_designation(record), 201)


@bp.route("/injury-designations/<designation_id>", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST, TEAM_MEDICAL_OFFICER)
def read_designation(actor, designation_id):
    record = domain.get_designation(designation_id)
    return single(views.injury_designation(record))


@bp.route("/injury-designations", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST, TEAM_MEDICAL_OFFICER)
def list_designations(actor):
    records = filter_records(values(db.injury_designations), {
        "player_id": "player_id",
        "team_id": "team_id",
        "designation_type": "designation_type",
        "status": "status",
    })
    return paginate(records, views.injury_designation)


@bp.route("/injury-designations/<designation_id>/file-paperwork", methods=["POST"])
@endpoint(TEAM_MEDICAL_OFFICER)
def file_paperwork(actor, designation_id):
    record = domain.get_designation(designation_id)
    require_team_scope(actor, record["team_id"])
    body = shape.body()
    reference = shape.req_str(body, "paperwork_reference")
    if record["status"] != "PENDING_PAPERWORK":
        fail("ERR_INVALID_DESIGNATION_STATE", "paperwork is already filed")
    record["status"] = "PAPERWORK_FILED"
    record["paperwork_reference"] = reference
    record["paperwork_filed_at"] = db.clock
    touch(record)
    player = db.players.get(record["player_id"])
    if player is not None:
        player["medical_status"] = "REHAB"
        touch(player)
    return single(views.injury_designation(record))


def _window_collision(player_id, start, end, ignore_id=None):
    """Half-open comparison: touching endpoints do not collide."""
    for exam in values(db.physical_exams, lambda e: e["player_id"] == player_id):
        if exam["id"] == ignore_id or exam["status"] != "SCHEDULED":
            continue
        if start < exam["window_end_at"] and exam["window_start_at"] < end:
            return exam
    return None


@bp.route("/physical-exams", methods=["POST"])
@endpoint(TEAM_MEDICAL_OFFICER)
def create_exam(actor):
    body = shape.body()
    raw_team = shape.raw(body, "team_id")
    if isinstance(raw_team, str) and raw_team.strip() != actor.user_id:
        fail("ERR_ACTOR_SCOPE_VIOLATION", "exam belongs to another club")
    player_id = shape.req_ref(body, "player_id")
    team_id = shape.req_ref(body, "team_id")
    require_team_scope(actor, team_id)
    exam_type = shape.req_enum(body, "exam_type", EXAM_TYPES)
    window_start = shape.req_dt(body, "window_start_at")
    window_end = shape.req_dt(body, "window_end_at")
    if window_end <= window_start:
        fail("ERR_INVALID_REQUEST", "window_end_at must be strictly later than window_start_at")
    transaction_id = shape.opt_ref(body, "transaction_id")
    trade_id = shape.opt_ref(body, "trade_id")
    if exam_type == "TRADE_PHYSICAL" and trade_id is None:
        fail("ERR_INVALID_REQUEST", "trade_id is required for a trade physical")
    player = domain.get_player(player_id)
    team = domain.get_team(team_id)
    transaction = domain.get_transaction(transaction_id) if transaction_id else None
    trade = domain.get_trade(trade_id) if trade_id else None
    if exam_type == "TRADE_PHYSICAL":
        if trade["status"] != "MEDICAL_REVIEW" or trade["conditional_clause_type"] != "PHYSICAL_CONTINGENT":
            fail("ERR_INVALID_TRADE_STATE", "trade is not under physical-contingent review")
    if exam_type == "RETURN_PHYSICAL":
        holds = False
        for designation in values(db.injury_designations, lambda d: d["player_id"] == player_id):
            if designation["status"] in ("ACTIVE", "RETURN_WINDOW_OPEN"):
                holds = True
                break
        if not holds:
            fail("ERR_INVALID_DESIGNATION_STATE", "player holds no active injury designation")
    # Rule 30
    if _window_collision(player_id, window_start, window_end) is not None:
        fail("ERR_EXAM_WINDOW_OVERLAP", "an exam window already covers that interval")
    record = base_record()
    record.update({
        "player_id": player_id,
        "team_id": team_id,
        "transaction_id": transaction_id,
        "trade_id": trade_id,
        "exam_type": exam_type,
        "status": "SCHEDULED",
        "window_start_at": window_start,
        "window_end_at": window_end,
        "performed_at": None,
        "result_recorded_at": None,
        "expires_at": None,
    })
    db.physical_exams[record["id"]] = record
    player["medical_status"] = "PHYSICAL_PENDING"
    touch(player)
    return single(views.physical_exam(record), 201)


@bp.route("/physical-exams/<exam_id>", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST, TEAM_MEDICAL_OFFICER)
def read_exam(actor, exam_id):
    record = domain.get_exam(exam_id)
    return single(views.physical_exam(record))


@bp.route("/physical-exams", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST, TEAM_MEDICAL_OFFICER)
def list_exams(actor):
    records = filter_records(values(db.physical_exams), {
        "player_id": "player_id",
        "team_id": "team_id",
        "transaction_id": "transaction_id",
        "trade_id": "trade_id",
        "exam_type": "exam_type",
        "status": "status",
    })
    return paginate(records, views.physical_exam)


@bp.route("/physical-exams/<exam_id>/record-result", methods=["POST"])
@endpoint(TEAM_MEDICAL_OFFICER)
def record_result(actor, exam_id):
    record = domain.get_exam(exam_id)
    require_team_scope(actor, record["team_id"])
    body = shape.body()
    result = shape.req_enum(body, "result", ("PASSED", "FAILED"))
    performed_at = shape.req_dt(body, "performed_at")
    # Rule 13
    if record["status"] != "SCHEDULED":
        fail("ERR_INVALID_EXAM_STATE", "exam result is already recorded")
    # Rule 29: the window is half-open.
    if performed_at < record["window_start_at"] or performed_at >= record["window_end_at"]:
        fail("ERR_RESULT_OUTSIDE_EXAM_WINDOW", "performed_at falls outside the exam window")
    player = domain.get_player(record["player_id"])
    record["performed_at"] = performed_at
    record["result_recorded_at"] = db.clock
    if result == "PASSED":
        record["status"] = "PASSED"
        record["expires_at"] = performed_at + days(calc.PHYSICAL_VALIDITY_DAYS)
        touch(record)
        outstanding = False
        for other in values(db.physical_exams, lambda e: e["player_id"] == player["id"]):
            if other["id"] != record["id"] and other["status"] == "SCHEDULED":
                outstanding = True
                break
        if not outstanding:
            player["medical_status"] = "CLEARED"
        touch(player)
    else:
        record["status"] = "FAILED"
        touch(record)
        player["medical_status"] = "FAILED_PHYSICAL"
        touch(player)
        if record["exam_type"] == "TRADE_PHYSICAL" and record["trade_id"]:
            trade = db.trades.get(record["trade_id"])
            if trade is not None and trade["status"] == "MEDICAL_REVIEW":
                domain.void_trade(trade, "FAILED_PHYSICAL")
    return single(views.physical_exam(record))
