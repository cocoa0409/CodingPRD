"""CalibrationSession routes."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES,
    ERR_DISTRIBUTION_OUT_OF_TOLERANCE,
)
from middleware import get_caller, require_role
from response import ok_object, ok_array
from services.common import init_common, touch, public, paginate, get_body, require_fields
from services.calibration import (
    in_scope_reviews, band_for_score, compute_actual, assign_final_ratings,
    ordered_bands,
)

bp = Blueprint("calibration", __name__)


def session_view(s):
    return public(s)


@bp.route("/calibration-sessions", methods=["POST"])
def create_session():
    _, role = get_caller()
    require_role(role, {"HrbpPartner"})
    body = get_body()
    require_fields(body, ["cycle_id", "department", "facilitator_id"])
    if body["cycle_id"] not in db.cycles:
        raise err(ERR_NOT_FOUND, "cycle_id not found")
    if body["facilitator_id"] not in db.employees:
        raise err(ERR_NOT_FOUND, "facilitator_id not found")

    s = {
        "cycle_id": body["cycle_id"],
        "department": body["department"],
        "facilitator_id": body["facilitator_id"],
        "status": "OPEN",
        "bell_curve_actual": None,
        "review_count": 0,
    }
    init_common(s)
    db.calibration_sessions[s["id"]] = s
    return ok_object(session_view(s), 201)


@bp.route("/calibration-sessions", methods=["GET"])
def list_sessions():
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner"})
    cycle_id = request.args.get("cycle_id")
    facilitator_id = request.args.get("facilitator_id")
    items = [
        s for s in db.calibration_sessions.values()
        if (cycle_id is None or s["cycle_id"] == cycle_id)
        and (facilitator_id is None or s["facilitator_id"] == facilitator_id)
    ]
    page, limit, offset, total, has_more = paginate(items)
    return ok_array([session_view(s) for s in page], limit, offset, total, has_more)


@bp.route("/calibration-sessions/<sid>", methods=["GET"])
def get_session(sid):
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner"})
    s = db.calibration_sessions.get(sid)
    if not s:
        raise err(ERR_NOT_FOUND, "Calibration session not found")
    return ok_object(session_view(s))


@bp.route("/calibration-sessions/<sid>/balance", methods=["POST"])
def balance_session(sid):
    _, role = get_caller()
    require_role(role, {"HrbpPartner"})
    s = db.calibration_sessions.get(sid)
    if not s:
        raise err(ERR_NOT_FOUND, "Calibration session not found")
    if s["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Session is not OPEN")
    cycle = db.cycles.get(s["cycle_id"])
    if not cycle or cycle["status"] != "CALIBRATION":
        raise err(ERR_INVALID_STATE, "Parent cycle must be in CALIBRATION")

    reviews = in_scope_reviews(s["cycle_id"], s["department"])
    ratings = {r["id"]: band_for_score(s["cycle_id"], r["composite_score"])
               for r in reviews}
    actual = compute_actual(s["cycle_id"], reviews, ratings)
    target = cycle["bell_curve_target"]
    tolerance = cycle["distribution_tolerance"]
    for b in ordered_bands(s["cycle_id"]):
        lbl = b["label"]
        if abs(actual.get(lbl, 0.0) - target.get(lbl, 0)) > tolerance:
            raise err(ERR_DISTRIBUTION_OUT_OF_TOLERANCE,
                      f"Band {lbl} deviates beyond tolerance")
    s["bell_curve_actual"] = actual
    s["review_count"] = len(reviews)
    s["status"] = "BALANCED"
    touch(s)
    return ok_object(session_view(s))


@bp.route("/calibration-sessions/<sid>/finalize", methods=["POST"])
def finalize_session(sid):
    user_id, role = get_caller()
    require_role(role, {"HrbpPartner"})
    s = db.calibration_sessions.get(sid)
    if not s:
        raise err(ERR_NOT_FOUND, "Calibration session not found")
    if s["status"] != "BALANCED":
        raise err(ERR_INVALID_STATE, "Session is not BALANCED")
    if user_id != s["facilitator_id"]:
        raise err(ERR_INVALID_STATE, "Acting employee must be the facilitator")

    reviews = in_scope_reviews(s["cycle_id"], s["department"])
    # Segregation: facilitator must not be the reviewer of any in-scope review.
    for r in reviews:
        if r["reviewer_id"] == user_id:
            raise err(ERR_SEGREGATION_OF_DUTIES,
                      "Facilitator must not be reviewer of in-scope reviews")

    final_ratings = assign_final_ratings(s["cycle_id"], reviews)
    # Map band labels to band records for pip_eligible lookup.
    band_by_label = {b["label"]: b for b in ordered_bands(s["cycle_id"])}
    for r in reviews:
        label = final_ratings[r["id"]]
        r["final_rating"] = label
        r["status"] = "CALIBRATED"
        touch(r)
        band = band_by_label.get(label)
        if band and band.get("pip_eligible"):
            _create_pip_case(r)

    s["bell_curve_actual"] = compute_actual(
        s["cycle_id"], reviews,
        {r["id"]: final_ratings[r["id"]] for r in reviews})
    s["review_count"] = len(reviews)
    s["status"] = "FINALIZED"
    touch(s)
    return ok_object(session_view(s))


def _create_pip_case(review):
    p = {
        "review_id": review["id"],
        "employee_id": review["employee_id"],
        "duration_days": None,
        "target_score": None,
        "outcome_score": None,
        "status": "OPEN",
    }
    init_common(p)
    db.pip_cases[p["id"]] = p
    return p
