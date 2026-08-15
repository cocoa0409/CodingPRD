"""Subcontractor chargeback lifecycle (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint, request

from clock import CLOCK
from db import db, new_entity, sorted_items
from errors import (
    raise_error,
    ERR_ALREADY_TERMINAL,
    ERR_CHARGEBACK_NOT_FOUND,
    ERR_CONTEST_WINDOW_CLOSED,
    ERR_DUPLICATE_CHARGEBACK,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_CHARGEBACKABLE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_OVERPAYMENT,
    ERR_WORK_ORDER_NOT_FOUND,
)
from middleware import get_caller, require_role
from response import success_list, success_object
from services.calc import CONTEST_WINDOW_DAYS, chargeback_amount
from services.reserve import (
    nonvoid_chargeback_for_work_order,
    post_entry,
    recompute_partner_outstanding,
    refresh_chargeback_amounts,
    reserve_for_home,
    touch,
)
from util import serialize
from validate import (
    apply_page,
    get_body,
    pagination_params,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("chargebacks", __name__)

RESOLVE_OUTCOMES = {"UPHELD", "REDUCED", "WAIVED"}
CB_TERMINAL = {"PAID", "WAIVED", "VOID"}
PAYABLE_STATUSES = {"APPROVED", "UPHELD", "REDUCED"}
READ_ROLES = {"WarrantyManager", "WarrantyRep", "TradePartner", "FinanceAdmin"}


def _get_chargeback_or_404(rid):
    cb = db["chargebacks"].get(rid)
    if cb is None:
        raise_error(ERR_CHARGEBACK_NOT_FOUND, f"chargeback id does not resolve: {rid}")
    return cb


def _recompute_partner(cb):
    partner = db["trade_partners"].get(cb["trade_partner_id"])
    if partner is not None:
        recompute_partner_outstanding(partner)
        touch(partner)


@bp.post("/chargebacks")
def create_chargeback():
    _uid, role = get_caller()
    require_role(role, {"WarrantyRep"})
    body = get_body()
    # Identifier resolution (precedence 4).
    wo_ref = body.get("work_order_id")
    wo = db["work_orders"].get(wo_ref) if isinstance(wo_ref, str) else None
    if isinstance(wo_ref, str) and wo_ref.strip() != "" and wo is None:
        raise_error(ERR_WORK_ORDER_NOT_FOUND, f"work order id does not resolve: {wo_ref}")
    req_str(body, "work_order_id")
    # Business rules (precedence 8): uniqueness fires BEFORE eligibility.
    if nonvoid_chargeback_for_work_order(wo["id"]) is not None:
        raise_error(ERR_DUPLICATE_CHARGEBACK,
                    "a non-VOID chargeback already exists for this work order")
    if wo["defect_responsibility"] != "SUBCONTRACTOR" or wo["status"] != "SCHEDULED":
        raise_error(ERR_NOT_CHARGEBACKABLE,
                    "chargebacks require defect_responsibility SUBCONTRACTOR and a "
                    "SCHEDULED work order")

    now = CLOCK.now()
    provisional = chargeback_amount(wo["estimated_cost_cents"])
    cb = new_entity()
    cb.update({
        "work_order_id": wo["id"],
        "trade_partner_id": wo["trade_partner_id"],  # denormalized at issuance
        "status": "ISSUED",
        "provisional_amount_cents": provisional,
        "final_amount_cents": None,
        "amount_basis": "PROVISIONAL",
        "payable_amount_cents": provisional,
        "collected_cents": 0,
        "outstanding_cents": provisional,
        "issued_at": now,
        "contest_deadline_at": now + timedelta(days=CONTEST_WINDOW_DAYS),
        "contest_reason": None,
        "resolution_notes": None,
    })
    # A cost at or under the deductible yields zero: the chargeback voids itself
    # rather than stand for nothing.
    if provisional == 0:
        cb["status"] = "VOID"
        cb["outstanding_cents"] = 0
    db["chargebacks"][cb["id"]] = cb
    _recompute_partner(cb)
    return success_object(serialize(cb), 201)


@bp.get("/chargebacks/<rid>")
def fetch_chargeback(rid):
    _uid, role = get_caller()
    require_role(role, READ_ROLES)
    return success_object(serialize(_get_chargeback_or_404(rid)))


@bp.get("/chargebacks")
def list_chargebacks():
    _uid, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    work_order_id = request.args.get("work_order_id")
    trade_partner_id = request.args.get("trade_partner_id")
    status = request.args.get("status")
    items = sorted_items("chargebacks")
    if work_order_id is not None:
        items = [c for c in items if c["work_order_id"] == work_order_id]
    if trade_partner_id is not None:
        items = [c for c in items if c["trade_partner_id"] == trade_partner_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = apply_page(items, limit, offset)
    return success_list([serialize(c) for c in page], total, limit, offset)


@bp.post("/chargebacks/<rid>/approve")
def approve_chargeback(rid):
    _uid, role = get_caller()
    require_role(role, {"WarrantyManager"})
    cb = _get_chargeback_or_404(rid)
    get_body()
    if cb["status"] in CB_TERMINAL:
        raise_error(ERR_ALREADY_TERMINAL, f"chargeback is {cb['status']}")
    if cb["status"] != "ISSUED":
        raise_error(ERR_INVALID_STATE,
                    f"approve is not defined from status {cb['status']}")
    cb["status"] = "APPROVED"
    touch(cb)
    return success_object(serialize(cb))


@bp.post("/chargebacks/<rid>/contest")
def contest_chargeback(rid):
    uid, role = get_caller()
    require_role(role, {"TradePartner"})
    cb = db["chargebacks"].get(rid)
    # Ownership (precedence 3): only the charged partner may contest.
    if cb is not None and cb["trade_partner_id"] != uid:
        raise_error(ERR_NOT_RESOURCE_OWNER,
                    "a trade partner may contest only chargebacks issued against it")
    if cb is None:
        raise_error(ERR_CHARGEBACK_NOT_FOUND, f"chargeback id does not resolve: {rid}")
    body = get_body()
    contest_reason = req_str(body, "contest_reason")
    if cb["status"] in CB_TERMINAL:
        raise_error(ERR_ALREADY_TERMINAL, f"chargeback is {cb['status']}")
    if cb["status"] != "ISSUED":
        raise_error(ERR_INVALID_STATE,
                    f"contest is not defined from status {cb['status']}")
    # The contest window is INCLUSIVE: exactly at the deadline is accepted.
    if CLOCK.now() > cb["contest_deadline_at"]:
        raise_error(ERR_CONTEST_WINDOW_CLOSED, "the 10-day contest window has closed")
    cb["contest_reason"] = contest_reason
    cb["status"] = "CONTESTED"
    touch(cb)
    return success_object(serialize(cb))


@bp.post("/chargebacks/<rid>/resolve")
def resolve_chargeback(rid):
    _uid, role = get_caller()
    require_role(role, {"WarrantyManager"})
    cb = _get_chargeback_or_404(rid)
    body = get_body()
    outcome = req_enum(body, "outcome", RESOLVE_OUTCOMES)
    resolution_notes = req_str(body, "resolution_notes")
    reduced_amount_cents = None
    if outcome == "REDUCED":
        reduced_amount_cents = req_int(body, "reduced_amount_cents")
    if cb["status"] in CB_TERMINAL:
        raise_error(ERR_ALREADY_TERMINAL, f"chargeback is {cb['status']}")
    if cb["status"] != "CONTESTED":
        raise_error(ERR_INVALID_STATE,
                    f"resolve is not defined from status {cb['status']}")

    cb["resolution_notes"] = resolution_notes
    if outcome == "UPHELD":
        cb["status"] = "UPHELD"
    elif outcome == "REDUCED":
        # The reduced figure must be positive and strictly below the current payable.
        if reduced_amount_cents <= 0 or reduced_amount_cents >= cb["payable_amount_cents"]:
            raise_error(ERR_INVALID_REQUEST,
                        "reduced_amount_cents must be positive and strictly below the "
                        "current payable amount")
        cb["status"] = "REDUCED"
        cb["final_amount_cents"] = reduced_amount_cents
        cb["amount_basis"] = "FINAL"
        refresh_chargeback_amounts(cb)
        touch(cb)
        _recompute_partner(cb)
        return success_object(serialize(cb))
    else:  # WAIVED — pure compensation: no reserve entry is posted.
        cb["status"] = "WAIVED"
        refresh_chargeback_amounts(cb)  # WAIVED forces outstanding to zero
        touch(cb)
        _recompute_partner(cb)
        return success_object(serialize(cb))
    touch(cb)
    return success_object(serialize(cb))


@bp.post("/chargebacks/<rid>/payments")
def record_payment(rid):
    _uid, role = get_caller()
    require_role(role, {"FinanceAdmin"})
    cb = _get_chargeback_or_404(rid)
    body = get_body()
    amount_cents = req_int(body, "amount_cents")
    if cb["status"] in CB_TERMINAL:
        raise_error(ERR_ALREADY_TERMINAL, f"chargeback is {cb['status']}")
    if cb["status"] not in PAYABLE_STATUSES:
        raise_error(ERR_INVALID_STATE,
                    f"payments are not defined from status {cb['status']}")
    # Payment bounds: positive and no more than the outstanding balance.
    if amount_cents <= 0 or amount_cents > cb["outstanding_cents"]:
        raise_error(ERR_OVERPAYMENT,
                    "payment must be positive and no more than the outstanding balance")

    cb["collected_cents"] += amount_cents
    refresh_chargeback_amounts(cb)
    settles = cb["outstanding_cents"] == 0
    if settles:
        cb["status"] = "PAID"
        # The settling payment credits the home's reserve with a RECOVERY entry.
        wo = db["work_orders"].get(cb["work_order_id"])
        sr = db["service_requests"].get(wo["service_request_id"]) if wo is not None else None
        reserve = reserve_for_home(sr["home_id"]) if sr is not None else None
        if reserve is not None:
            post_entry(reserve, "RECOVERY", amount_cents, chargeback_ref=cb["id"])
    touch(cb)
    _recompute_partner(cb)
    return success_object(serialize(cb))
