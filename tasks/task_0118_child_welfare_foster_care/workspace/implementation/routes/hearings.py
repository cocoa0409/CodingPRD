"""Hearing routes (PRD §3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import errors
import helpers
import middleware
import response
from services import compute, serialize

bp = Blueprint("hearings", __name__)

HEARING_TYPES = {"SHELTER", "ADJUDICATION", "DISPOSITION", "REVIEW", "PERMANENCY", "TPR"}
RULINGS = {"CONTINUE_PLACEMENT", "RETURN_HOME", "CHANGE_GOAL_ADOPTION", "TERMINATE_RIGHTS"}


@bp.route("/hearings", methods=["POST"])
def create_hearing():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker", "Judge"})
    body = helpers.get_body()
    case_id = helpers.require_str(body, "case_id")
    hearing_type = helpers.require_enum(body, "hearing_type", HEARING_TYPES)
    scheduled_at = helpers.require_dt(body, "scheduled_at")
    case = db.cases.get(case_id)
    if case is None:
        raise errors.not_found("Case not found.")

    # Docket buffer: reject a new SCHEDULED hearing within +/- 30 min (inclusive)
    # of an existing SCHEDULED hearing on the same case.
    buffer = timedelta(minutes=compute.HEARING_BUFFER_MINUTES)
    for h in db.hearings.values():
        if h["case_id"] == case_id and h["status"] == "SCHEDULED":
            existing = helpers.parse_dt(h["scheduled_at"], "scheduled_at")
            if abs((scheduled_at - existing).total_seconds()) <= buffer.total_seconds():
                raise errors.hearing_overlap()

    record = {
        "case_id": case_id,
        "hearing_type": hearing_type,
        "status": "SCHEDULED",
        "scheduled_at": clock.iso(scheduled_at),
        "ruling": None,
    }
    db.stamp_create(record)
    db.hearings[record["id"]] = record
    return response.success(serialize.hearing(record), 201)


@bp.route("/hearings/<hid>", methods=["GET"])
def get_hearing(hid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "Caseworker", "Judge"})
    record = db.hearings.get(hid)
    if record is None:
        raise errors.not_found("Hearing not found.")
    return response.success(serialize.hearing(record), 200)


@bp.route("/hearings", methods=["GET"])
def list_hearings():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "Caseworker", "Judge"})
    limit, offset = helpers.pagination()
    case_id = request.args.get("case_id")
    hearing_type = request.args.get("hearing_type")
    status = request.args.get("status")
    records = list(db.hearings.values())
    if case_id is not None:
        records = [r for r in records if r["case_id"] == case_id]
    if hearing_type is not None:
        records = [r for r in records if r["hearing_type"] == hearing_type]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = helpers.paginate(records, limit, offset)
    return response.list_success([serialize.hearing(r) for r in page], limit, offset, total)


@bp.route("/hearings/<hid>/hold", methods=["POST"])
def hold_hearing(hid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Judge"})
    record = db.hearings.get(hid)
    if record is None:
        raise errors.not_found("Hearing not found.")
    body = helpers.get_body()
    ruling = helpers.require_enum(body, "ruling", RULINGS)
    if record["status"] != "SCHEDULED":
        raise errors.invalid_state("Hearing is not SCHEDULED.")
    sched = helpers.parse_dt(record["scheduled_at"], "scheduled_at")
    if clock.now() < sched:
        raise errors.invalid_state("Current clock has not reached scheduled_at.")
    record["status"] = "HELD"
    record["ruling"] = ruling
    db.bump(record)
    # Cross-entity effect: CHANGE_GOAL_ADOPTION sets the case goal to ADOPTION.
    if ruling == "CHANGE_GOAL_ADOPTION":
        case = db.cases.get(record["case_id"])
        if case is not None:
            case["permanency_goal"] = "ADOPTION"
            db.bump(case)
    # RETURN_HOME on a PERMANENCY_PLANNING case keeps the goal at REUNIFICATION
    # (no change needed; default goal is already REUNIFICATION).
    return response.success(serialize.hearing(record), 200)


@bp.route("/hearings/<hid>/continue", methods=["POST"])
def continue_hearing(hid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Judge"})
    record = db.hearings.get(hid)
    if record is None:
        raise errors.not_found("Hearing not found.")
    if record["status"] != "SCHEDULED":
        raise errors.invalid_state("Hearing is not SCHEDULED.")
    record["status"] = "CONTINUED"
    db.bump(record)
    return response.success(serialize.hearing(record), 200)


@bp.route("/hearings/<hid>/reschedule", methods=["POST"])
def reschedule_hearing(hid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Judge"})
    record = db.hearings.get(hid)
    if record is None:
        raise errors.not_found("Hearing not found.")
    body = helpers.get_body()
    scheduled_at = helpers.require_dt(body, "scheduled_at")
    if record["status"] != "CONTINUED":
        raise errors.invalid_state("Hearing is not CONTINUED.")
    record["status"] = "SCHEDULED"
    record["scheduled_at"] = clock.iso(scheduled_at)
    db.bump(record)
    return response.success(serialize.hearing(record), 200)


@bp.route("/hearings/<hid>/vacate", methods=["POST"])
def vacate_hearing(hid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Judge"})
    record = db.hearings.get(hid)
    if record is None:
        raise errors.not_found("Hearing not found.")
    if record["status"] != "SCHEDULED":
        raise errors.invalid_state("Hearing is not SCHEDULED.")
    record["status"] = "VACATED"
    db.bump(record)
    return response.success(serialize.hearing(record), 200)
