"""Stipend disbursements: draft assembly and payment lifecycle."""

import re
from decimal import Decimal

from flask import Blueprint

import calc
import domain
from auth import ADMIN, MENTOR, actor, guard, own_mentor, scope_rows
from envelope import list_response, pagination, row_response
from errors import ApiError
from store import db, iso, new_row, now, parse_iso, sorted_rows, touch
from validators import (apply_filters, body, datetime_field, enum_field, fk,
                        int_field, path_row, str_field)

bp = Blueprint("stipends", __name__)

PERIOD_RE = re.compile(r"^[0-9]{4}-Q[1-4]$")


def _eligible_logs(mentor, start, end):
    rows = []
    for log in domain.logs_of_mentor(mentor["id"]):
        if log.get("verification_status") != "VERIFIED":
            continue
        verified_at = parse_iso(log.get("verified_at"))
        if verified_at is None or not (start <= verified_at <= end):
            continue
        rows.append(log)
    return rows


@bp.post("/stipend-disbursements")
@guard([ADMIN])
def create_disbursement():
    data = body()
    mentor = fk("mentors", data, "mentor_id")
    str_field(data, "mentor_id", 1, None)
    period_code = str_field(data, "period_code", 1, 20)
    if not PERIOD_RE.match(period_code):
        raise ApiError("ERR_INVALID_REQUEST", "period_code must look like 2026-Q1.")
    start = datetime_field(data, "period_start")
    end = datetime_field(data, "period_end")
    expected = int_field(data, "expected_mentor_version")
    adjustment = int_field(data, "adjustment_cents", -500000, 500000,
                           required=False, default=0)

    if int(mentor.get("version") or 0) != expected:
        raise ApiError("ERR_STALE_PARENT_VERSION")
    if end <= start:
        raise ApiError("ERR_INVALID_WINDOW")
    if not end < now():
        raise ApiError("ERR_PERIOD_NOT_CLOSED")

    existing_drafts = []
    for row in domain.disbursements_of_mentor(mentor["id"]):
        if row.get("period_code") != period_code:
            continue
        if row.get("status") in ("APPROVED", "PAID"):
            raise ApiError("ERR_DUPLICATE_DISBURSEMENT_PERIOD")
        if row.get("status") == "DRAFT":
            existing_drafts.append(row)

    logs = _eligible_logs(mentor, start, end)
    if not logs:
        raise ApiError("ERR_NO_ELIGIBLE_ACTIVITY")
    gross = 0
    for log in logs:
        multiplier = Decimal(str(log.get("cert_multiplier_at_verification") or 1.0))
        gross += calc.stipend_cents(log.get("credited_minutes") or 0,
                                    log.get("rate_tier_at_verification"), multiplier)
    if adjustment < 0 and abs(adjustment) > gross:
        raise ApiError("ERR_ADJUSTMENT_EXCEEDS_GROSS")
    net = gross + adjustment
    if net <= 0:
        raise ApiError("ERR_NON_POSITIVE_NET_STIPEND")

    row = new_row({
        "mentor_id": mentor["id"],
        "period_code": period_code,
        "period_start": iso(start),
        "period_end": iso(end),
        "gross_cents": gross,
        "adjustment_cents": adjustment,
        "net_cents": net,
        "eligible_log_count": len(logs),
        "status": "DRAFT",
        "prepared_by_user_id": actor(),
        "approved_by_user_id": None,
        "paid_at": None,
        "payment_reference": None,
        "clawed_back_at": None,
        "clawback_reason": None,
        "superseded_by_id": None,
    })
    db.disbursements[row["id"]] = row
    for draft in existing_drafts:
        draft["status"] = "SUPERSEDED"
        draft["superseded_by_id"] = row["id"]
        touch(draft)
    touch(mentor)
    return row_response(row, 201)


@bp.get("/stipend-disbursements")
@guard([ADMIN, MENTOR])
def list_disbursements():
    rows = sorted_rows(list(db.disbursements.values()))
    rows = scope_rows(rows, mentor_getter=lambda r: r.get("mentor_id"))
    rows = apply_filters(rows, {"mentor_id": ("mentor_id", "str"),
                                "status": ("status", "str"),
                                "period_code": ("period_code", "str")})
    limit, offset = pagination()
    return list_response(rows, limit, offset)


@bp.get("/stipend-disbursements/<row_id>")
@guard([ADMIN, MENTOR])
def get_disbursement(row_id):
    row = path_row("disbursements", row_id)
    own_mentor(row.get("mentor_id"))
    return row_response(row)


@bp.post("/stipend-disbursements/<row_id>/status")
@guard([ADMIN])
def set_disbursement_status(row_id):
    row = path_row("disbursements", row_id)
    data = body()
    status = enum_field(data, "status", ("APPROVED", "PAID", "CLAWED_BACK"))
    payment_reference = str_field(data, "payment_reference", 1, 120,
                                  required=status == "PAID")
    clawback_reason = str_field(data, "clawback_reason", 1, 1000,
                                required=status == "CLAWED_BACK")
    mentor = db.mentors.get(row.get("mentor_id"))

    needed = {"APPROVED": "DRAFT", "PAID": "APPROVED", "CLAWED_BACK": "PAID"}[status]
    if row.get("status") != needed:
        raise ApiError("ERR_DISBURSEMENT_STATE_INVALID")
    if status == "APPROVED":
        if actor() is not None and actor() == row.get("prepared_by_user_id"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        if int(row.get("net_cents") or 0) <= 0:
            raise ApiError("ERR_NON_POSITIVE_NET_STIPEND")
        row["status"] = "APPROVED"
        row["approved_by_user_id"] = actor()
        touch(row)
    elif status == "PAID":
        row["status"] = "PAID"
        row["paid_at"] = iso(now())
        row["payment_reference"] = payment_reference
        touch(row)
        if mentor is not None:
            mentor["stipend_paid_cents"] = int(
                mentor.get("stipend_paid_cents") or 0) + int(row.get("net_cents") or 0)
            touch(mentor)
    else:
        row["status"] = "CLAWED_BACK"
        row["clawed_back_at"] = iso(now())
        row["clawback_reason"] = clawback_reason
        touch(row)
        if mentor is not None:
            net = int(row.get("net_cents") or 0)
            mentor["stipend_paid_cents"] = int(mentor.get("stipend_paid_cents") or 0) - net
            mentor["stipend_clawed_back_cents"] = int(
                mentor.get("stipend_clawed_back_cents") or 0) + net
            touch(mentor)
    return row_response(row)
