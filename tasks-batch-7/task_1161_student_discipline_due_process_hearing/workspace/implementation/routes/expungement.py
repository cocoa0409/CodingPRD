"""Expungement requests (PRD §3.8)."""
from datetime import timedelta

from flask import Blueprint

from db import db, stamp, touch, serialize, clock
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_EXPUNGEMENT_NOT_ELIGIBLE,
)
from middleware import endpoint
from response import success
from routes.common import get_or_404, guardian_owns, render_list
from services.calc import EXPUNGEMENT_WAIT_DAYS
from services.cascade import expungement_approval_cascade

bp = Blueprint("expungement", __name__)


@bp.post("/expungement-requests")
@endpoint("ParentGuardian")
def create_expungement(ctx):
    student_id = ctx.body.get("student_id")
    # Body-carried FK existence (rung 5) before schema completion (rung 6)
    if isinstance(student_id, str) and student_id not in db.students:
        raise_err(ERR_NOT_FOUND, f"student not found: {student_id}")
    if not isinstance(student_id, str):
        raise_err(ERR_INVALID_REQUEST, "student_id is required")
    student = db.students[student_id]
    guardian_owns(ctx, student)

    # Eligibility (rung 10): >= 1 CLOSED case; every case CLOSED/EXPUNGED;
    # clock >= last_case_closed_at + 730 days (inclusive).
    cases = [c for c in db.cases.values() if c["student_id"] == student_id]
    eligible = (
        any(c["status"] == "CLOSED" for c in cases)
        and all(c["status"] in ("CLOSED", "EXPUNGED") for c in cases)
        and student["last_case_closed_at"] is not None
        and clock() >= student["last_case_closed_at"] + timedelta(days=EXPUNGEMENT_WAIT_DAYS)
    )
    if not eligible:
        raise_err(ERR_EXPUNGEMENT_NOT_ELIGIBLE, "student record is not eligible for expungement")

    req = stamp(
        {
            "student_id": student_id,
            "requested_by": ctx.user_id,
            "status": "SUBMITTED",
            "decided_at": None,
            "decision_rationale": None,
        }
    )
    db.expungements[req["id"]] = req
    return success(serialize(req), 201)


@bp.get("/students/<sid>/expungement-requests")
@endpoint("DistrictAdmin", "ParentGuardian")
def list_expungements(ctx, sid):
    student = get_or_404(db.students, sid, "student")
    guardian_owns(ctx, student)
    reqs = {k: v for k, v in db.expungements.items() if v["student_id"] == sid}
    return render_list(reqs)


@bp.post("/expungement-requests/<eid>/decision")
@endpoint("DistrictAdmin")
def decide_expungement(ctx, eid):
    req = get_or_404(db.expungements, eid, "expungement request")
    b = ctx.body
    outcome = b.get("outcome")
    rationale = b.get("rationale")
    if outcome not in ("APPROVED", "DENIED"):
        raise_err(ERR_INVALID_REQUEST, "outcome must be APPROVED or DENIED")
    if rationale is not None and not isinstance(rationale, str):
        raise_err(ERR_INVALID_REQUEST, "rationale must be a string")
    if req["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "expungement request is not SUBMITTED")

    req["status"] = outcome
    req["decided_at"] = clock()
    req["decision_rationale"] = rationale
    touch(req)
    if outcome == "APPROVED":
        expungement_approval_cascade(db.students[req["student_id"]])
    return success(serialize(req))
