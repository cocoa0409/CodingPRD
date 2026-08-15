"""Reconciliation break endpoints: record, get, list, resolve, reopen, sweep."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, filter_arg, ok, paginate
from services import navmath
from services.navmath import D
from validation import parse_body, require_fk, require_path_entity

bp = Blueprint("breaks", __name__)

BREAK_SCHEMA = {
    "fund_id": ("string", True, None),
    "position_id": ("string", True, None),
    "break_type": ("enum", True, ["CUSTODIAN_POSITION", "BROKER_POSITION"]),
    "break_date": ("date", True, None),
    "counterparty_quantity": ("nonnegnumber", True, None),
}

RESOLVE_SCHEMA = {
    "resolution_type": ("enum", True, ["NO_CHANGE", "ADJUST_POSITION"]),
}

ESCALATION_DAYS = 5


@bp.post("/reconciliation-breaks")
def create_break():
    get_context()
    require_roles(["FundAccountant"])
    body = parse_body(BREAK_SCHEMA)
    fund = require_fk(store.funds, body["fund_id"], "fund_id")
    position = require_fk(store.positions, body["position_id"], "position_id")

    book = D(position["quantity"])
    variance = D(body["counterparty_quantity"]) - book
    if variance == 0:
        raise ApiError("ERR_NO_VARIANCE", 422,
                       "counterparty_quantity equals the book quantity")
    brk = {
        "id": db.new_id(),
        "fund_id": fund["id"],
        "position_id": position["id"],
        "break_type": body["break_type"],
        "break_date": body["break_date"],
        "counterparty_quantity": D(body["counterparty_quantity"]),
        "book_quantity": book,
        "variance": variance,
        "resolution_type": None,
        "prior_book_quantity": None,
        "status": "OPEN",
    }
    db.new_common(brk)
    store.reconciliation_breaks[brk["id"]] = brk
    return created(brk)


@bp.get("/reconciliation-breaks/<reconciliation_break_id>")
def get_break(reconciliation_break_id):
    get_context()
    brk = require_path_entity(store.reconciliation_breaks, reconciliation_break_id)
    require_roles(ALL_ROLES)
    return ok(brk)


@bp.get("/reconciliation-breaks")
def list_breaks():
    get_context()
    require_roles(ALL_ROLES)
    rows = list(store.reconciliation_breaks.values())
    rows = filter_arg(rows, "fund_id")
    rows = filter_arg(rows, "position_id")
    rows = filter_arg(rows, "status")
    page, meta = paginate(rows)
    return ok(page, rtype="array", pagination=meta)


@bp.post("/reconciliation-breaks/escalate-overdue")
def escalate_overdue():
    get_context()
    require_roles(["FundController"])
    parse_body({})
    today = db.clock_today()
    count = 0
    for brk in store.reconciliation_breaks.values():
        if brk["status"] != "OPEN":
            continue
        # Escalate only when the break is MORE than 5 days old; exactly five
        # days old is not escalated.
        if (today - navmath.date_of(brk["break_date"])).days > ESCALATION_DAYS:
            brk["status"] = "ESCALATED"
            db.touch(brk)
            count += 1
    return ok({"escalated_count": count})


@bp.post("/reconciliation-breaks/<reconciliation_break_id>/resolve")
def resolve_break(reconciliation_break_id):
    get_context()
    brk = require_path_entity(store.reconciliation_breaks, reconciliation_break_id)
    require_roles(["FundController"])
    body = parse_body(RESOLVE_SCHEMA)

    if brk["status"] not in ("OPEN", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an OPEN or ESCALATED break can be resolved")
    resolution = body["resolution_type"]
    if resolution == "ADJUST_POSITION":
        position = store.positions[brk["position_id"]]
        brk["prior_book_quantity"] = D(position["quantity"])
        position["quantity"] = D(brk["counterparty_quantity"])
        if position["quantity"] == 0:
            position["status"] = "CLOSED"  # auto-close at exactly zero
        db.touch(position)
        # The position mutation rebuilds the class's latest ESTIMATED record.
        navmath.recompute_latest_estimated(position["share_class_id"])
    brk["resolution_type"] = resolution
    brk["status"] = "RESOLVED"
    db.touch(brk)
    return ok(brk)


@bp.post("/reconciliation-breaks/<reconciliation_break_id>/reopen")
def reopen_break(reconciliation_break_id):
    get_context()
    brk = require_path_entity(store.reconciliation_breaks, reconciliation_break_id)
    require_roles(["FundController"])
    parse_body({})

    if brk["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a RESOLVED break can be reopened")
    if brk["resolution_type"] == "ADJUST_POSITION":
        # Full compensation: restore the pre-resolution quantity exactly.
        position = store.positions[brk["position_id"]]
        position["quantity"] = D(brk["prior_book_quantity"])
        if position["status"] == "CLOSED" and position["quantity"] > 0:
            position["status"] = "OPEN"
        db.touch(position)
        navmath.recompute_latest_estimated(position["share_class_id"])
    brk["resolution_type"] = None
    brk["status"] = "OPEN"
    db.touch(brk)
    return ok(brk)
