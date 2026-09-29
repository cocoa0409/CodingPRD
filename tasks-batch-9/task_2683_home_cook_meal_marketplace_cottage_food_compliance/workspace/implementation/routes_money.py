"""Payout statements and refund events."""
from flask import Blueprint

import calc
import services
import validation as v
from auth import (
    COOK,
    FINANCE_OPERATOR,
    PLATFORM_ADMIN,
    SAFETY_OFFICER,
    acting_user,
    guard,
)
from core import ApiError, created, db, new_row, ok, public, touch
from listing import list_rows

bp = Blueprint("money", __name__)

STATEMENT_STATUSES = ["DRAFT", "FINALIZED", "PAID", "REVERSED", "SUPERSEDED"]


def _pair_statements(cook_id, window_id, exclude_id=None):
    rows = []
    for s in db.statements.values():
        if s["cook_id"] != cook_id or s["production_window_id"] != window_id:
            continue
        if exclude_id is not None and s["id"] == exclude_id:
            continue
        rows.append(s)
    return calc._by_creation(rows)


@bp.route("/payout-statements", methods=["POST"])
@guard([FINANCE_OPERATOR, PLATFORM_ADMIN])
def create_statement():
    body = v.body()
    cook_id = v.s_id(body, "cook_id")
    window_id = v.s_id(body, "production_window_id")
    basis = v.s_enum(body, "basis", v.PAYOUT_BASES)
    expected = v.s_int(body, "expected_production_window_version")

    cook = db.cooks.get(cook_id)
    if cook is None:
        raise ApiError("ERR_COOK_NOT_FOUND")
    window = db.windows.get(window_id)
    if window is None:
        raise ApiError("ERR_WINDOW_NOT_FOUND")
    if expected != int(window["version"]):
        raise ApiError("ERR_STALE_WINDOW_VERSION", "expected_production_window_version does not match")
    for existing in _pair_statements(cook_id, window_id):
        if existing["status"] in ("FINALIZED", "PAID"):
            raise ApiError(
                "ERR_DUPLICATE_FINALIZED_STATEMENT",
                "a live statement already exists for this cook and window",
            )

    numbers = calc.payout_numbers(cook, window, basis)
    fields = {
        "cook_id": cook_id,
        "production_window_id": window_id,
        "basis": basis,
        "status": "DRAFT",
        "finalized_at": None,
        "paid_at": None,
        "superseded_at": None,
    }
    fields.update(numbers)
    row = new_row(db.statements, fields)

    for older in _pair_statements(cook_id, window_id, exclude_id=row["id"]):
        if older["status"] == "DRAFT":
            older["status"] = "SUPERSEDED"
            older["superseded_at"] = db.now_iso()
            touch(older)
    touch(window)
    return created(public(row))


@bp.route("/payout-statements/<statement_id>", methods=["GET"])
@guard([COOK, FINANCE_OPERATOR, PLATFORM_ADMIN])
def get_statement(statement_id):
    row = db.statements.get(statement_id)
    if row is None:
        raise ApiError("ERR_STATEMENT_NOT_FOUND")
    return ok(public(row))


@bp.route("/payout-statements", methods=["GET"])
@guard([COOK, FINANCE_OPERATOR, PLATFORM_ADMIN])
def list_statements():
    return list_rows(
        list(db.statements.values()), ["cook_id", "production_window_id", "status", "basis"]
    )


@bp.route("/payout-statements/<statement_id>/advance", methods=["POST"])
@guard([FINANCE_OPERATOR, PLATFORM_ADMIN])
def advance_statement(statement_id):
    body = v.body()
    to_status = v.s_enum(body, "to_status", STATEMENT_STATUSES)
    v.s_str(body, "note", 0, 4000, required=False)

    statement = db.statements.get(statement_id)
    if statement is None:
        raise ApiError("ERR_STATEMENT_NOT_FOUND")
    cook = db.cooks[statement["cook_id"]]
    window = db.windows[statement["production_window_id"]]
    status = statement["status"]

    if to_status == "FINALIZED":
        if status != "DRAFT":
            raise ApiError("ERR_INVALID_STATEMENT_TRANSITION", "FINALIZED is reachable from DRAFT")
        if window["status"] != "CLOSED":
            raise ApiError(
                "ERR_INVALID_STATEMENT_TRANSITION", "the covered window is not CLOSED"
            )
        window_order_ids = set(o["id"] for o in calc.window_orders(window["id"]))
        for incident in calc.cook_incidents(cook["id"]):
            if incident["status"] not in ("INTAKE", "TRIAGED"):
                continue
            if incident["order_id"] in window_order_ids:
                raise ApiError(
                    "ERR_OPEN_INCIDENT_BLOCKS_PAYOUT", "an open investigation covers this window"
                )
        for other in _pair_statements(cook["id"], window["id"], exclude_id=statement_id):
            if other["status"] in ("FINALIZED", "PAID"):
                raise ApiError(
                    "ERR_DUPLICATE_FINALIZED_STATEMENT",
                    "another statement for this pair is already live",
                )
        statement["status"] = "FINALIZED"
        statement["finalized_at"] = db.now_iso()
        touch(statement)
        for refund in calc._by_creation(list(db.refunds.values())):
            if refund["status"] != "PENDING" or refund["order_id"] not in window_order_ids:
                continue
            refund["status"] = "SETTLED"
            refund["settled_at"] = db.now_iso()
            touch(refund)
        services.recompute_cook_money(cook)
        return ok(public(statement))

    if to_status == "PAID":
        if status != "FINALIZED":
            raise ApiError("ERR_INVALID_STATEMENT_TRANSITION", "PAID is reachable from FINALIZED")
        if cook["compliance_standing"] in ("SUSPENDED", "REVOKED"):
            raise ApiError("ERR_PAYOUT_HOLD_ACTIVE", "the cook's standing holds the payout")
        statement["status"] = "PAID"
        statement["paid_at"] = db.now_iso()
        touch(statement)
        services.recompute_cook_money(cook)
        return ok(public(statement))

    if to_status == "REVERSED":
        if status not in ("FINALIZED", "PAID"):
            raise ApiError(
                "ERR_INVALID_STATEMENT_TRANSITION", "REVERSED is reachable from FINALIZED or PAID"
            )
        statement["status"] = "REVERSED"
        touch(statement)
        services.recompute_cook_money(cook)
        return ok(public(statement))

    raise ApiError("ERR_INVALID_STATEMENT_TRANSITION", "%s is not reachable" % to_status)


# ------------------------------------------------------------- refund events
@bp.route("/refund-events", methods=["POST"])
@guard([FINANCE_OPERATOR, PLATFORM_ADMIN])
def create_refund():
    body = v.body()
    order_id = v.s_id(body, "order_id")
    reason = v.s_enum(body, "reason", v.REFUND_REASONS)
    fault_party = v.s_enum(body, "fault_party", v.FAULT_PARTIES)
    amount = v.s_int(body, "refund_amount_cents")
    settle_immediately = v.s_bool(body, "settle_immediately", required=False, default=False)
    incident_id = v.s_id(body, "safety_incident_id", required=(reason == "SAFETY"))

    order = db.orders.get(order_id)
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND")
    if incident_id is not None and incident_id not in db.incidents:
        raise ApiError("ERR_INCIDENT_NOT_FOUND")

    if order["payment_status"] not in ("CAPTURED", "PARTIALLY_REFUNDED"):
        raise ApiError("ERR_ORDER_NOT_REFUNDABLE", "the order's payment status is not refundable")

    remaining = int(order["total_charge_cents"]) - int(order["refunded_cents"])
    if amount < 1 or amount > remaining:
        raise ApiError(
            "ERR_REFUND_EXCEEDS_REMAINING",
            "refund_amount_cents must be between 1 and %d" % remaining,
        )

    cook_part, commission_part, platform_part = calc.refund_split(order, fault_party, amount)
    row = new_row(
        db.refunds,
        {
            "order_id": order_id,
            "safety_incident_id": incident_id,
            "reason": reason,
            "fault_party": fault_party,
            "refund_amount_cents": amount,
            "cook_chargeback_cents": cook_part,
            "commission_reversed_cents": commission_part,
            "platform_absorbed_cents": platform_part,
            "status": "PENDING",
            "settled_at": None,
            "created_by_user_id": acting_user() or "system",
        },
    )
    if settle_immediately:
        row["status"] = "SETTLED"
        row["settled_at"] = db.now_iso()

    order["refunded_cents"] = int(order["refunded_cents"]) + amount
    order["cook_chargeback_cents"] = int(order["cook_chargeback_cents"]) + cook_part
    order["commission_reversed_cents"] = int(order["commission_reversed_cents"]) + commission_part
    order["platform_absorbed_cents"] = int(order["platform_absorbed_cents"]) + platform_part
    if int(order["refunded_cents"]) >= int(order["total_charge_cents"]):
        order["payment_status"] = "REFUNDED"
    else:
        order["payment_status"] = "PARTIALLY_REFUNDED"
    touch(order)

    cook = db.cooks.get(order["cook_id"])
    if cook is not None:
        services.recompute_cook_money(cook)
    return created(public(row))


@bp.route("/refund-events/<refund_id>", methods=["GET"])
@guard([COOK, FINANCE_OPERATOR, PLATFORM_ADMIN])
def get_refund(refund_id):
    row = db.refunds.get(refund_id)
    if row is None:
        raise ApiError("ERR_REFUND_NOT_FOUND")
    return ok(public(row))


@bp.route("/refund-events", methods=["GET"])
@guard([COOK, FINANCE_OPERATOR, SAFETY_OFFICER, PLATFORM_ADMIN])
def list_refunds():
    return list_rows(
        list(db.refunds.values()), ["order_id", "safety_incident_id", "status"]
    )
