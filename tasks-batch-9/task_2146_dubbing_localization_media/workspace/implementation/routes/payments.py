"""Talent payments: accrual and settlement."""
from flask import Blueprint, request

import calc
from auth import ALL_ROLES, auth
from domain import (check_order_open, get_assignment, get_payment, newest_review,
                    rows_where)
from errors import ApiError
from responses import created, ok, paged
from store import TERRITORIES, db, new_row, serialize, touch
from validate import body, v_array

bp = Blueprint("payments", __name__)


@bp.post("/talent-payments")
@auth("PlatformAdmin")
def create_payment():
    data = body()
    assignment = get_assignment(data.get("casting_assignment_id"))     # rung 7
    territory_scope = v_array(data, "territory_scope", non_empty=True,  # rung 8
                              member_enum=TERRITORIES)
    order = db.orders[assignment["order_id"]]
    check_order_open(order)                                            # rung 10

    if assignment["casting_status"] != "RECORDED":                     # rung 11
        raise ApiError("ERR_INVALID_STATE")
    if assignment["payment_status"] not in ("UNBILLED", "VOIDED", "ACCRUED"):
        raise ApiError("ERR_INVALID_STATE")

    talent = db.voice_talents[assignment["talent_id"]]                 # rung 15
    licensed = talent["licensed_territories"]
    if order["territory"] not in licensed:
        raise ApiError("ERR_TERRITORY_NOT_LICENSED")
    for territory in territory_scope:
        if territory not in licensed:
            raise ApiError("ERR_TERRITORY_NOT_LICENSED")
    if order["territory"] not in territory_scope:
        raise ApiError("ERR_TERRITORY_NOT_LICENSED")

    for existing in rows_where(db.payments, casting_assignment_id=assignment["id"]):
        if existing["status"] == "ACCRUED":                            # rung 45
            raise ApiError("ERR_PAYMENT_ALREADY_ACCRUED")

    durations = [s["duration_minutes"] for s in db.sessions.values()
                 if s["casting_assignment_id"] == assignment["id"]
                 and s["status"] == "COMPLETED" and not s["is_retake"]]
    base_fee = calc.base_fee_cents(assignment["agreed_rate_cents_per_hour"], durations)
    variant = assignment["usage_variant"]
    usage_fee = calc.usage_fee_cents(base_fee, variant, territory_scope)

    row = new_row({
        "casting_assignment_id": assignment["id"],
        "talent_id": assignment["talent_id"],
        "variant": variant,
        "territory_scope": list(territory_scope),
        "base_fee_cents": base_fee,
        "usage_fee_cents": usage_fee,
        "total_fee_cents": base_fee + usage_fee,
        "status": "ACCRUED",
        "settled_at": None,
    })
    db.payments[row["id"]] = row
    assignment["payment_status"] = "ACCRUED"
    touch(assignment)
    return created(serialize(row))


@bp.get("/talent-payments/<payment_id>")
@auth(*ALL_ROLES)
def read_payment(payment_id):
    return ok(serialize(get_payment(payment_id)))


@bp.get("/talent-payments")
@auth(*ALL_ROLES)
def list_payments():
    rows = list(db.payments.values())
    for key in ("casting_assignment_id", "talent_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paged(rows, serialize)


@bp.post("/talent-payments/<payment_id>/settle")
@auth("PlatformAdmin")
def settle_payment(payment_id):
    payment = get_payment(payment_id)                                  # rung 6
    assignment = db.assignments[payment["casting_assignment_id"]]
    order = db.orders[assignment["order_id"]]

    if assignment["casting_status"] != "RECORDED":                     # rung 11
        raise ApiError("ERR_INVALID_STATE")
    review = newest_review(order["id"])
    if review is None or review["status"] != "PASSED":
        raise ApiError("ERR_INVALID_STATE")
    if payment["status"] != "ACCRUED":                                 # rung 44
        raise ApiError("ERR_PAYMENT_ALREADY_SETTLED")

    payment["status"] = "SETTLED"
    payment["settled_at"] = db.clock
    touch(payment)
    if assignment["payment_status"] == "ACCRUED":
        assignment["payment_status"] = "SETTLED"
        touch(assignment)
    return ok(serialize(payment))
