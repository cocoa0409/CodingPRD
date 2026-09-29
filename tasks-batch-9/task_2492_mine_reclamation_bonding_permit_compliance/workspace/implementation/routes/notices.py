"""Violation notices, cessation orders and civil penalties (PRD 3.6)."""

from flask import Blueprint

import calculations as calc
import constants as C
import engine
import serialization as ser
from db import D, ZERO, base_row, days, db, now
from engine import bump, sync_posture
from errors import ApiError
from response import created_response, object_response
from routes._shared import (
    collection_filtered,
    require_assigned_inspector,
    require_permit_operator,
    require_state,
)
from validation import (
    authorize,
    enum_field,
    get_body,
    int_field,
    lookup,
    number_field,
    resolve,
    str_field,
)

bp = Blueprint("notices", __name__)

LIST_FILTERS = [
    ("permit_id", "permit_id", None),
    ("inspection_id", "inspection_id", None),
    ("notice_status", "notice_status", C.NOTICE_STATUSES),
    ("penalty_status", "penalty_status", C.PENALTY_STATUSES),
    ("violation_class", "violation_class", C.VIOLATION_CLASSES),
]

OPEN_NOTICE_STATUSES = ["ISSUED", "CESSATION_ORDERED"]


@bp.post("/mining/violation-notices")
def create_notice():
    user_id, role = authorize([C.ROLE_INSPECTOR])
    body = get_body()
    inspection_id = str_field(body, "inspection_id")
    violation_class = enum_field(body, "violation_class", C.VIOLATION_CLASSES)
    severity_points = int_field(body, "severity_points", ge=0, le=C.SEVERITY_POINTS_MAX)
    negligence_points = int_field(body, "negligence_points", ge=0, le=C.NEGLIGENCE_POINTS_MAX)
    duration_points = int_field(body, "duration_points", ge=0, le=C.DURATION_POINTS_MAX)
    abatement_days = int_field(body, "abatement_days", ge=1)

    # Band 5.
    inspection = resolve(db.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")

    # Band 6 — the issuing inspector must be the one who did the work.
    require_assigned_inspector(role, user_id, inspection)

    # Band 10 — the cited inspection must have found violations.
    if inspection["status"] != "COMPLETED" or inspection["result"] != "VIOLATIONS_FOUND":
        raise ApiError(
            "ERR_INSPECTION_NOT_ELIGIBLE",
            "A violation notice requires a completed inspection that found violations.",
        )

    permit = db.permits[inspection["permit_id"]]
    issued_at = now()
    history_points = calc.violation_history_points(permit["operator_id"])

    row = base_row()
    row.update(
        {
            "inspection_id": inspection_id,
            "permit_id": permit["id"],
            "violation_class": violation_class,
            "severity_points": severity_points,
            "negligence_points": negligence_points,
            "duration_points": duration_points,
            "history_points": history_points,
            "total_points": calc.total_points(
                severity_points, negligence_points, duration_points, history_points
            ),
            "abatement_days": abatement_days,
            "abatement_deadline": issued_at + days(abatement_days),
            "notice_status": "ISSUED",
            "penalty_status": "NONE",
            "good_faith_level": None,
            "penalty_amount": ZERO,
            "penalty_paid_amount": ZERO,
            "issued_at": issued_at,
            "cessation_ordered_at": None,
            "abated_at": None,
            "vacated_at": None,
            "cessation_reason": None,
            "abatement_note": None,
            "vacate_reason": None,
        }
    )
    db.notices[row["id"]] = row

    sync_posture(permit)
    return created_response(ser.notice_out(row))


@bp.get("/mining/violation-notices/<notice_id>")
def get_notice(notice_id):
    authorize(C.ALL_ROLES)
    row = lookup(db.notices, notice_id, "ERR_VIOLATION_NOTICE_NOT_FOUND")
    return object_response(ser.notice_out(row))


@bp.get("/mining/violation-notices")
def list_notices():
    authorize(C.ALL_ROLES)
    return collection_filtered(db.notices.values(), LIST_FILTERS, ser.notice_out)


@bp.post("/mining/violation-notices/<notice_id>/order-cessation")
def order_cessation(notice_id):
    authorize([C.ROLE_INSPECTOR])
    body = get_body()
    cessation_reason = str_field(body, "cessation_reason")

    row = lookup(db.notices, notice_id, "ERR_VIOLATION_NOTICE_NOT_FOUND")

    # Band 9.
    require_state(row, "notice_status", ["ISSUED"], "ERR_NOTICE_STATE_INVALID")

    # Band 11 — at least one of the three escalation criteria must hold.
    criteria = (
        row["total_points"] >= C.CESSATION_POINTS_THRESHOLD
        or now() > row["abatement_deadline"]
        or row["violation_class"] == "IMMINENT_HARM"
    )
    if not criteria:
        raise ApiError(
            "ERR_CESSATION_CRITERIA_NOT_MET",
            "This notice meets none of the criteria for ordering cessation of mining.",
        )

    row["notice_status"] = "CESSATION_ORDERED"
    row["cessation_ordered_at"] = now()
    row["cessation_reason"] = cessation_reason
    bump(row)

    sync_posture(db.permits[row["permit_id"]])
    return object_response(ser.notice_out(row))


@bp.post("/mining/violation-notices/<notice_id>/abate")
def abate(notice_id):
    user_id, role = authorize([C.ROLE_OPERATOR])
    body = get_body()
    abatement_note = str_field(body, "abatement_note")

    row = lookup(db.notices, notice_id, "ERR_VIOLATION_NOTICE_NOT_FOUND")
    permit = db.permits[row["permit_id"]]

    # Band 6, then band 9.
    require_permit_operator(role, user_id, permit)
    require_state(row, "notice_status", OPEN_NOTICE_STATUSES, "ERR_NOTICE_STATE_INVALID")

    row["notice_status"] = "ABATED"
    row["abated_at"] = now()
    row["abatement_note"] = abatement_note
    bump(row)

    sync_posture(permit)
    return object_response(ser.notice_out(row))


@bp.post("/mining/violation-notices/<notice_id>/vacate")
def vacate(notice_id):
    authorize([C.ROLE_PROGRAM_DIRECTOR])
    body = get_body()
    vacate_reason = str_field(body, "vacate_reason")

    row = lookup(db.notices, notice_id, "ERR_VIOLATION_NOTICE_NOT_FOUND")

    # Band 9 — the enforcement dimension first, then the money.
    require_state(row, "notice_status", OPEN_NOTICE_STATUSES, "ERR_NOTICE_STATE_INVALID")
    if row["penalty_status"] == "PAID":
        raise ApiError(
            "ERR_PENALTY_STATE_INVALID",
            "A paid civil penalty is not unwound by vacating the notice.",
        )

    row["notice_status"] = "VACATED"
    row["vacated_at"] = now()
    row["vacate_reason"] = vacate_reason
    if row["penalty_status"] == "ASSESSED":
        row["penalty_status"] = "VACATED"
        row["penalty_amount"] = ZERO
    bump(row)

    sync_posture(db.permits[row["permit_id"]])
    return object_response(ser.notice_out(row))


@bp.post("/mining/violation-notices/<notice_id>/assess-penalty")
def assess_penalty(notice_id):
    authorize([C.ROLE_PROGRAM_DIRECTOR])
    body = get_body()
    good_faith_level = enum_field(body, "good_faith_level", C.GOOD_FAITH_LEVELS)

    row = lookup(db.notices, notice_id, "ERR_VIOLATION_NOTICE_NOT_FOUND")

    # Band 9 — the penalty dimension is checked before the enforcement one.
    require_state(row, "penalty_status", ["NONE"], "ERR_PENALTY_STATE_INVALID")
    require_state(
        row,
        "notice_status",
        ["ISSUED", "CESSATION_ORDERED", "ABATED"],
        "ERR_NOTICE_STATE_INVALID",
    )

    row["good_faith_level"] = good_faith_level
    row["penalty_amount"] = calc.penalty_assessment_amount(row, good_faith_level)
    row["penalty_status"] = "ASSESSED"
    bump(row)
    return object_response(ser.notice_out(row))


@bp.post("/mining/violation-notices/<notice_id>/pay-penalty")
def pay_penalty(notice_id):
    user_id, role = authorize([C.ROLE_OPERATOR])
    body = get_body()
    amount_paid = number_field(body, "amount_paid", ge=0)

    row = lookup(db.notices, notice_id, "ERR_VIOLATION_NOTICE_NOT_FOUND")
    permit = db.permits[row["permit_id"]]

    # Band 6, then band 9, then band 13.
    require_permit_operator(role, user_id, permit)
    require_state(row, "penalty_status", ["ASSESSED"], "ERR_PENALTY_STATE_INVALID")
    if D(amount_paid) != D(row["penalty_amount"]):
        raise ApiError(
            "ERR_PENALTY_AMOUNT_MISMATCH",
            "The amount paid must equal the assessed penalty exactly.",
        )

    row["penalty_paid_amount"] = amount_paid
    row["penalty_status"] = "PAID"
    bump(row)
    return object_response(ser.notice_out(row))
