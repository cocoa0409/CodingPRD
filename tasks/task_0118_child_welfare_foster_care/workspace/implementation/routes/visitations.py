"""Visitation routes (PRD §3.8)."""
from flask import Blueprint, request

import clock
import db
import errors
import helpers
import middleware
import response
from services import serialize

bp = Blueprint("visitations", __name__)

SUPERVISION = {"SUPERVISED", "UNSUPERVISED"}


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap. Touching endpoints do NOT overlap."""
    return a_start < b_end and b_start < a_end


@bp.route("/visitations", methods=["POST"])
def create_visitation():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    body = helpers.get_body()
    case_plan_id = helpers.require_str(body, "case_plan_id")
    child_id = helpers.require_str(body, "child_id")
    supervision = helpers.require_enum(body, "supervision", SUPERVISION)
    window_start = helpers.require_dt(body, "window_start")
    window_end = helpers.require_dt(body, "window_end")

    # Existence (left-to-right body FK order): case_plan, then child.
    plan = db.case_plans.get(case_plan_id)
    if plan is None:
        raise errors.not_found("Case plan not found.")
    child = db.children.get(child_id)
    if child is None:
        raise errors.not_found("Child not found.")

    # window_end strictly after window_start.
    if not (window_end > window_start):
        raise errors.invalid_window()

    # Overlap: against existing SCHEDULED visits for the SAME child.
    for v in db.visitations.values():
        if v["child_id"] == child_id and v["status"] == "SCHEDULED":
            vs = helpers.parse_dt(v["window_start"], "window_start")
            ve = helpers.parse_dt(v["window_end"], "window_end")
            if _overlaps(window_start, window_end, vs, ve):
                raise errors.visit_overlap()

    record = {
        "case_plan_id": case_plan_id,
        "child_id": child_id,
        "status": "SCHEDULED",
        "supervision": supervision,
        "window_start": clock.iso(window_start),
        "window_end": clock.iso(window_end),
    }
    db.stamp_create(record)
    db.visitations[record["id"]] = record
    return response.success(serialize.visitation(record), 201)


@bp.route("/visitations/<vid>", methods=["GET"])
def get_visitation(vid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "Caseworker"})
    record = db.visitations.get(vid)
    if record is None:
        raise errors.not_found("Visitation not found.")
    return response.success(serialize.visitation(record), 200)


@bp.route("/visitations", methods=["GET"])
def list_visitations():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "Caseworker"})
    limit, offset = helpers.pagination()
    case_plan_id = request.args.get("case_plan_id")
    child_id = request.args.get("child_id")
    status = request.args.get("status")
    records = list(db.visitations.values())
    if case_plan_id is not None:
        records = [r for r in records if r["case_plan_id"] == case_plan_id]
    if child_id is not None:
        records = [r for r in records if r["child_id"] == child_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = helpers.paginate(records, limit, offset)
    return response.list_success([serialize.visitation(r) for r in page], limit, offset, total)


@bp.route("/visitations/<vid>/mark-occurred", methods=["POST"])
def mark_occurred(vid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.visitations.get(vid)
    if record is None:
        raise errors.not_found("Visitation not found.")
    if record["status"] != "SCHEDULED":
        raise errors.invalid_state("Visitation is not SCHEDULED.")
    ws = helpers.parse_dt(record["window_start"], "window_start")
    if clock.now() < ws:
        raise errors.invalid_state("Current clock has not reached window_start.")
    record["status"] = "OCCURRED"
    db.bump(record)
    return response.success(serialize.visitation(record), 200)


@bp.route("/visitations/<vid>/mark-missed", methods=["POST"])
def mark_missed(vid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.visitations.get(vid)
    if record is None:
        raise errors.not_found("Visitation not found.")
    if record["status"] != "SCHEDULED":
        raise errors.invalid_state("Visitation is not SCHEDULED.")
    we = helpers.parse_dt(record["window_end"], "window_end")
    if clock.now() < we:
        raise errors.invalid_state("Current clock has not reached window_end.")
    record["status"] = "MISSED"
    db.bump(record)
    return response.success(serialize.visitation(record), 200)


@bp.route("/visitations/<vid>/cancel", methods=["POST"])
def cancel_visit(vid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.visitations.get(vid)
    if record is None:
        raise errors.not_found("Visitation not found.")
    if record["status"] != "SCHEDULED":
        raise errors.invalid_state("Visitation is not SCHEDULED.")
    ws = helpers.parse_dt(record["window_start"], "window_start")
    if not (clock.now() < ws):
        raise errors.invalid_state("Cancellation requires the clock to be strictly before window_start.")
    record["status"] = "CANCELLED"
    db.bump(record)
    return response.success(serialize.visitation(record), 200)
