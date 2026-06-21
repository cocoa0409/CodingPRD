"""Accrual endpoints: book + reverse (PRD §3.8).

An accrual occupies the closed interval [period_start, period_end]. Booking must
not overlap an existing BOOKED accrual on the same PO (closed interval => shared
endpoint counts as overlap). estimated_cents and final_cents both derive from
max(0, received - matched), evaluated at booking and at reversal respectively.
"""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint

import db
from errors import (
    APIError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_ACCRUAL_PERIOD_OVERLAP,
)
from middleware import auth_required, ALL_ROLES
from response import ok_object
from routes._helpers import get_body, require_fields, serialize, is_str
from services.calculations import accrual_amount
from services.common import new_common_fields, touch

bp = Blueprint("accruals", __name__)


def _parse_date(value: str):
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise APIError(ERR_INVALID_REQUEST, 400, "period_start/period_end must be ISO 8601 dates")


@bp.post("/ap/accruals")
def book_accrual():
    auth_required({"APManager"})()
    body = get_body()
    require_fields(body, ["po_id", "period_label", "period_start", "period_end"])

    po_id = body["po_id"]
    po = db.purchase_orders.get(po_id)
    if po is None:
        raise APIError(ERR_NOT_FOUND, 404, "Purchase order not found")

    if not is_str(body["period_label"]) or not body["period_label"]:
        raise APIError(ERR_INVALID_REQUEST, 400, "period_label must be a non-empty string")
    for f in ("period_start", "period_end"):
        if not is_str(body[f]):
            raise APIError(ERR_INVALID_REQUEST, 400, f"{f} must be a string")

    p_start = _parse_date(body["period_start"])
    p_end = _parse_date(body["period_end"])
    if p_end < p_start:
        raise APIError(ERR_INVALID_REQUEST, 400, "period_end must be on or after period_start")

    # business_temporal: closed interval must not overlap any BOOKED accrual on
    # the same PO (shared endpoint counts as overlap) (409).
    for other in db.accruals.values():
        if other["po_id"] != po_id or other["status"] != "BOOKED":
            continue
        o_start = _parse_date(other["period_start"])
        o_end = _parse_date(other["period_end"])
        if p_start <= o_end and o_start <= p_end:  # closed-interval overlap
            raise APIError(ERR_ACCRUAL_PERIOD_OVERLAP, 409,
                           "Accrual period overlaps an existing BOOKED accrual on this PO")

    accrual = {
        **new_common_fields(),
        "po_id": po_id,
        "period_label": body["period_label"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "estimated_cents": accrual_amount(po),  # ESTIMATE at booking time
        "final_cents": 0,
        "status": "BOOKED",
    }
    db.accruals[accrual["id"]] = accrual
    return ok_object(serialize(accrual), http_status=201)


@bp.get("/ap/accruals/<aid>")
def get_accrual(aid):
    auth_required(ALL_ROLES)()
    a = db.accruals.get(aid)
    if a is None:
        raise APIError(ERR_NOT_FOUND, 404, "Accrual not found")
    return ok_object(serialize(a))


@bp.post("/ap/accruals/<aid>/reverse")
def reverse_accrual(aid):
    auth_required({"APManager"})()
    a = db.accruals.get(aid)
    if a is None:
        raise APIError(ERR_NOT_FOUND, 404, "Accrual not found")
    if a["status"] != "BOOKED":
        raise APIError(ERR_INVALID_STATE, 409, "Accrual is not BOOKED")
    po = db.purchase_orders.get(a["po_id"])
    if po is None:
        raise APIError(ERR_NOT_FOUND, 404, "Purchase order not found")

    a["final_cents"] = accrual_amount(po)  # FINAL true-up at reversal time
    a["status"] = "REVERSED"
    touch(a)
    return ok_object(serialize(a))
