"""Disputes and back-wage corrections (3.9)."""

from flask import Blueprint

import cascades
import serial
from auth import ALL_ROLES, authorize, not_owner, scope_rows_by_employee
from envelope import object_response
from errors import ApiError, invalid
from serial import apply_filters, paged, view
from store import db, stamp_new, touch, touch_time_only
from validators import f, parse_body, parse_query

bp = Blueprint("disputes", __name__)

CATEGORIES = {"POOL_SHARE", "TIP_CREDIT", "CC_FEE", "SERVICE_CHARGE"}
DISPUTE_STATUSES = {"OPEN", "UPHELD", "PARTIALLY_UPHELD", "DENIED", "CLOSED"}
RESOLUTIONS = {"UPHELD", "PARTIALLY_UPHELD", "DENIED"}
REASON_CODES = {
    "POOL_SHARE_SHORTFALL",
    "TIP_CREDIT_INVALID",
    "CC_FEE_OVERDEDUCTION",
    "SERVICE_CHARGE_MISCLASSIFIED",
    "SIDE_WORK_OVERAGE",
}
CORRECTION_STATUSES = {"PENDING", "APPLIED", "VOIDED"}

CATEGORY_REASONS = {
    "POOL_SHARE": "POOL_SHARE_SHORTFALL",
    "TIP_CREDIT": "TIP_CREDIT_INVALID",
    "CC_FEE": "CC_FEE_OVERDEDUCTION",
    "SERVICE_CHARGE": "SERVICE_CHARGE_MISCLASSIFIED",
}


def period_of(line):
    return db.pay_periods.get(line["pay_period_id"])


def pending_on_line(pay_line_id):
    for correction in cascades.rows("corrections"):
        if correction["pay_line_id"] == pay_line_id and correction["status"] == "PENDING":
            return correction
    return None


def scope_by_line(actor, rows):
    """Narrow correction rows through the pay line they name."""
    if not (actor.is_employee or actor.is_manager):
        return rows
    out = []
    for row in rows:
        line = db.pay_lines.get(row["pay_line_id"])
        if line is None:
            continue
        if actor.is_employee:
            if line["employee_id"] == actor.user_id:
                out.append(row)
            continue
        unit = actor.scope_location_id()
        employee = db.employees.get(line["employee_id"])
        if unit is not None and employee is not None and employee["location_id"] == unit:
            out.append(row)
    return out


# ---------------------------------------------------------------------------
# POST /disputes
# ---------------------------------------------------------------------------

DISPUTE_SPEC = [
    f("pay_line_id", "id", True),
    f("raised_by_employee_id", "id", True),
    f("category", "enum", True, domain=CATEGORIES),
    f("claimed_amount_cents", "int", True, min=0),
    f("narrative", "str", False),
]


@bp.post("/disputes")
def create_dispute():
    actor = authorize(["Employee"])
    body, _present = parse_body(DISPUTE_SPEC)
    if body["claimed_amount_cents"] <= 0:
        raise invalid("Field 'claimed_amount_cents' must be greater than 0.")

    line = db.pay_lines.get(body["pay_line_id"])                      # rung 5
    if line is None:
        raise ApiError("ERR_PAY_LINE_NOT_FOUND")
    employee = db.employees.get(body["raised_by_employee_id"])
    if employee is None:
        raise ApiError("ERR_EMPLOYEE_NOT_FOUND")

    if (                                                              # rung 6
        body["raised_by_employee_id"] != actor.user_id
        or line["employee_id"] != actor.user_id
    ):
        raise not_owner()
    if line["status"] != "FINAL":                                     # rung 22
        raise ApiError("ERR_PAY_LINE_NOT_FINAL")
    if body["raised_by_employee_id"] != line["employee_id"]:          # rung 32
        raise ApiError("ERR_EMPLOYEE_LOCATION_MISMATCH")
    for other in cascades.rows("disputes"):                           # rung 47
        if (
            other["pay_line_id"] == line["id"]
            and other["category"] == body["category"]
            and other["status"] != "CLOSED"
        ):
            raise ApiError("ERR_DUPLICATE_DISPUTE_CATEGORY")

    record = {
        "pay_line_id": line["id"],
        "raised_by_employee_id": employee["id"],
        "category": body["category"],
        "claimed_amount_cents": body["claimed_amount_cents"],
        "narrative": body["narrative"],
        "status": "OPEN",
        "adjudicated_amount_cents": 0,
        "adjudicated_by_user_id": None,
        "closed_at": None,
    }
    stamp_new(record)
    db.disputes[record["id"]] = record

    line["open_dispute_count"] = line["open_dispute_count"] + 1
    touch_time_only(line)
    return object_response(view(record, serial.DISPUTE), 201)


@bp.get("/disputes/<dispute_id>")
def read_dispute(dispute_id):
    authorize(ALL_ROLES)
    record = db.disputes.get(dispute_id)
    if record is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND")
    return object_response(view(record, serial.DISPUTE))


@bp.get("/disputes")
def list_disputes():
    actor = authorize(ALL_ROLES)
    filters, limit, offset = parse_query(
        [
            f("pay_line_id", "id"),
            f("raised_by_employee_id", "id"),
            f("status", "enum", domain=DISPUTE_STATUSES),
            f("category", "enum", domain=CATEGORIES),
        ]
    )
    rows = apply_filters(cascades.rows("disputes"), filters)
    rows = scope_rows_by_employee(actor, rows, "raised_by_employee_id")
    return paged(rows, serial.DISPUTE, limit, offset)


# ---------------------------------------------------------------------------
# adjudication
# ---------------------------------------------------------------------------

def issue_correction(line, amount, reason_code, issued_by, dispute_id):
    """The four-hop award cascade shared by both award-bearing branches."""
    displaced = pending_on_line(line["id"])
    record = {
        "pay_line_id": line["id"],
        "dispute_id": dispute_id,
        "supersedes_correction_id": displaced["id"] if displaced is not None else None,
        "amount_cents": amount,
        "reason_code": reason_code,
        "status": "PENDING",
        "issued_by_user_id": issued_by,
        "applied_by_user_id": None,
        "applied_at": None,
        "voided_at": None,
    }
    stamp_new(record)
    db.corrections[record["id"]] = record

    if displaced is not None:
        displaced["status"] = "VOIDED"
        displaced["voided_at"] = db.now()
        touch(displaced)

    cascades.recompute_line_corrections(line)
    touch(line)

    period = period_of(line)
    if period is not None:
        cascades.recompute_period_corrections(period)
    return record


ADJUDICATE_SPEC = [
    f("resolution", "enum", True, domain=RESOLUTIONS),
    f("awarded_cents", "int", False, min=0),
    f("reason_code", "enum", False, domain=REASON_CODES),
]


@bp.post("/disputes/<dispute_id>/adjudicate")
def adjudicate_dispute(dispute_id):
    actor = authorize(["ComplianceOfficer"])
    body, present = parse_body(ADJUDICATE_SPEC)
    dispute = db.disputes.get(dispute_id)
    if dispute is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND")
    line = db.pay_lines.get(dispute["pay_line_id"])

    if dispute["status"] != "OPEN":                                    # rung 19
        raise ApiError("ERR_DISPUTE_NOT_OPEN")
    if line is None or line["status"] != "FINAL":                      # rung 22
        raise ApiError("ERR_PAY_LINE_NOT_FINAL")

    resolution = body["resolution"]
    awarded = body["awarded_cents"]
    if resolution == "PARTIALLY_UPHELD":                               # rung 48
        if "awarded_cents" not in present:
            raise ApiError("ERR_PARTIAL_AMOUNT_INVALID")
        if awarded <= 0 or awarded >= dispute["claimed_amount_cents"]:
            raise ApiError("ERR_PARTIAL_AMOUNT_INVALID")
    elif "awarded_cents" in present:
        raise ApiError("ERR_PARTIAL_AMOUNT_INVALID")

    if resolution == "UPHELD":
        amount = dispute["claimed_amount_cents"]
    elif resolution == "PARTIALLY_UPHELD":
        amount = awarded
    else:
        amount = 0

    dispute["status"] = resolution
    dispute["adjudicated_amount_cents"] = amount
    dispute["adjudicated_by_user_id"] = actor.user_id
    touch(dispute)

    if amount > 0:
        reason_code = body["reason_code"] or CATEGORY_REASONS.get(
            dispute["category"], "POOL_SHARE_SHORTFALL"
        )
        issue_correction(line, amount, reason_code, actor.user_id, dispute["id"])
    return object_response(view(dispute, serial.DISPUTE))


@bp.post("/disputes/<dispute_id>/close")
def close_dispute(dispute_id):
    authorize(["ComplianceOfficer"])
    parse_body([])
    dispute = db.disputes.get(dispute_id)
    if dispute is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND")

    if dispute["status"] not in ("UPHELD", "PARTIALLY_UPHELD", "DENIED"):  # rung 20
        raise ApiError("ERR_DISPUTE_NOT_ADJUDICATED")
    if dispute["status"] in ("UPHELD", "PARTIALLY_UPHELD"):
        applied = [
            c
            for c in cascades.rows("corrections")
            if c["dispute_id"] == dispute["id"] and c["status"] == "APPLIED"
        ]
        if not applied:
            raise ApiError("ERR_DISPUTE_NOT_ADJUDICATED")

    dispute["status"] = "CLOSED"
    dispute["closed_at"] = db.now()
    touch(dispute)

    line = db.pay_lines.get(dispute["pay_line_id"])
    if line is not None:
        line["open_dispute_count"] = max(0, line["open_dispute_count"] - 1)
        touch_time_only(line)
    return object_response(view(dispute, serial.DISPUTE))


# ---------------------------------------------------------------------------
# back-wage corrections
# ---------------------------------------------------------------------------

CORRECTION_SPEC = [
    f("pay_line_id", "id", True),
    f("dispute_id", "id", False),
    f("supersedes_correction_id", "id", False),
    f("amount_cents", "int", True, min=0),
    f("reason_code", "enum", True, domain=REASON_CODES),
    f("expected_pay_line_version", "int", True),
]


@bp.post("/back-wage-corrections")
def create_correction():
    actor = authorize(["ComplianceOfficer"])
    body, present = parse_body(CORRECTION_SPEC)

    line = db.pay_lines.get(body["pay_line_id"])                       # rung 5
    if line is None:
        raise ApiError("ERR_PAY_LINE_NOT_FOUND")
    dispute = None
    if "dispute_id" in present:
        dispute = db.disputes.get(body["dispute_id"])
        if dispute is None:
            raise ApiError("ERR_DISPUTE_NOT_FOUND")
    displaced = None
    if "supersedes_correction_id" in present:
        displaced = db.corrections.get(body["supersedes_correction_id"])
        if displaced is None:
            raise ApiError("ERR_CORRECTION_NOT_FOUND")

    if line["status"] != "FINAL":                                      # rung 22
        raise ApiError("ERR_PAY_LINE_NOT_FINAL")
    if body["expected_pay_line_version"] != line["version"]:           # rung 24
        raise ApiError("ERR_STALE_PAY_LINE_VERSION")

    outstanding = pending_on_line(line["id"])                          # rung 37
    if displaced is not None:
        if (
            displaced["status"] != "PENDING"
            or displaced["pay_line_id"] != line["id"]
        ):
            raise ApiError("ERR_SUPERSEDE_TARGET_MISMATCH")
    elif outstanding is not None:
        raise ApiError("ERR_SUPERSEDE_TARGET_MISMATCH")

    if body["amount_cents"] <= 0:                                      # rung 54
        raise ApiError("ERR_CORRECTION_EXCEEDS_CLAIM")
    if dispute is not None and body["amount_cents"] > dispute["adjudicated_amount_cents"]:
        raise ApiError("ERR_CORRECTION_EXCEEDS_CLAIM")

    record = {
        "pay_line_id": line["id"],
        "dispute_id": dispute["id"] if dispute is not None else None,
        "supersedes_correction_id": displaced["id"] if displaced is not None else None,
        "amount_cents": body["amount_cents"],
        "reason_code": body["reason_code"],
        "status": "PENDING",
        "issued_by_user_id": actor.user_id,
        "applied_by_user_id": None,
        "applied_at": None,
        "voided_at": None,
    }
    stamp_new(record)
    db.corrections[record["id"]] = record

    if displaced is not None:
        displaced["status"] = "VOIDED"
        displaced["voided_at"] = db.now()
        touch(displaced)

    cascades.recompute_line_corrections(line)
    touch(line)
    period = period_of(line)
    if period is not None:
        cascades.recompute_period_corrections(period)
    return object_response(view(record, serial.CORRECTION), 201)


@bp.get("/back-wage-corrections/<correction_id>")
def read_correction(correction_id):
    authorize(ALL_ROLES)
    record = db.corrections.get(correction_id)
    if record is None:
        raise ApiError("ERR_CORRECTION_NOT_FOUND")
    return object_response(view(record, serial.CORRECTION))


@bp.get("/back-wage-corrections")
def list_corrections():
    actor = authorize(ALL_ROLES)
    filters, limit, offset = parse_query(
        [
            f("pay_line_id", "id"),
            f("dispute_id", "id"),
            f("supersedes_correction_id", "id"),
            f("status", "enum", domain=CORRECTION_STATUSES),
            f("reason_code", "enum", domain=REASON_CODES),
        ]
    )
    rows = apply_filters(cascades.rows("corrections"), filters)
    rows = scope_by_line(actor, rows)
    return paged(rows, serial.CORRECTION, limit, offset)


@bp.post("/back-wage-corrections/<correction_id>/apply")
def apply_correction(correction_id):
    actor = authorize(["ComplianceOfficer", "PayrollPreparer"])
    parse_body([])
    correction = db.corrections.get(correction_id)
    if correction is None:
        raise ApiError("ERR_CORRECTION_NOT_FOUND")

    if actor.user_id == correction["issued_by_user_id"]:               # rung 7
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if correction["status"] != "PENDING":                              # rung 21
        raise ApiError("ERR_CORRECTION_NOT_PENDING")
    line = db.pay_lines.get(correction["pay_line_id"])
    if line is None or line["status"] != "FINAL":                      # rung 22
        raise ApiError("ERR_PAY_LINE_NOT_FINAL")

    already = sum(
        c["amount_cents"]
        for c in cascades.line_corrections(line["id"])
        if c["status"] == "APPLIED"
    )
    if already + correction["amount_cents"] > line["minimum_wage_obligation_cents"]:
        raise ApiError("ERR_CORRECTION_EXCEEDS_OBLIGATION")           # rung 55

    amount = correction["amount_cents"]
    correction["status"] = "APPLIED"
    correction["applied_at"] = db.now()
    correction["applied_by_user_id"] = actor.user_id
    touch(correction)

    cascades.recompute_line_corrections(line)
    line["total_gross_cents"] = line["total_gross_cents"] + amount
    touch(line)

    period = period_of(line)
    if period is not None:
        cascades.recompute_period_corrections(period)
        if correction["reason_code"] == "TIP_CREDIT_INVALID":
            period["total_topup_cents"] = period["total_topup_cents"] + amount
            touch(period)
    return object_response(view(correction, serial.CORRECTION))
