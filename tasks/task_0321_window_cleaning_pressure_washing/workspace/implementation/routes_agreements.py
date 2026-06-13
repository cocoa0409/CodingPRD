"""ServiceAgreement endpoints: convert, list, read, activate, pause, resume,
complete, cancel; plus nested visits/deposits listings."""
from flask import Blueprint, request

import db
from auth import require_roles
from clock import logical_now, parse_iso
from errors import err
from helpers import (
    apply_quote_expiry, body, get_or_404, paginate, pagination_params,
    post_ledger, req_int, req_str, req_enum,
)
from response import success, list_success
from serialize import public, public_list
from visit_ops import (
    cancel_visit_for_cascade, generate_visit, requires_high_rise,
    requires_soft_wash,
)

bp = Blueprint("agreements", __name__)


def _refund_held_deposits(agreement):
    """Refund every HELD deposit for the agreement (PRD §3.2 complete/cancel)."""
    for dep in db.deposits.values():
        if dep["agreement_id"] == agreement["id"] and dep["status"] == "HELD":
            dep["status"] = "REFUNDED"
            db.touch(dep)
            # refund LedgerEntry: signed = -amount_cents
            post_ledger(dep["account_id"], "DEPOSIT", dep["id"], -dep["amount_cents"])


@bp.post("/service-agreements")
def convert_quote():
    require_roles({"Customer", "Billing"})
    data = body()
    quote_id = req_str(data, "quote_id")
    schedule_kind = req_enum(data, "schedule_kind", {"ONE_TIME", "RECURRING"})
    recurrence_interval_days = None
    if schedule_kind == "RECURRING":
        recurrence_interval_days = req_int(data, "recurrence_interval_days")
        if recurrence_interval_days < 7:
            raise err("ERR_INVALID_REQUEST", "recurrence_interval_days must be >= 7 for RECURRING")

    quote = get_or_404(db.quotes, quote_id)
    apply_quote_expiry(quote)
    # Quote-expiry precedes the generic state guard.
    if quote["status"] == "EXPIRED":
        raise err("ERR_QUOTE_EXPIRED", "Quote has expired")
    if quote["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Quote is not in ACCEPTED")
    # Defensive expiry check against the logical clock.
    if logical_now() >= parse_iso(quote["valid_until"]):
        quote["status"] = "EXPIRED"
        db.touch(quote)
        raise err("ERR_QUOTE_EXPIRED", "Quote has expired")

    rec = db.new_record(db.agreements, {
        "account_id": quote["account_id"],
        "property_id": quote["property_id"],
        "quote_id": quote_id,
        "schedule_kind": schedule_kind,
        "recurrence_interval_days": recurrence_interval_days,
        "per_visit_price_cents": quote["quoted_total_cents"],
        "required_deposit_cents": quote["required_deposit_cents"],
        "visits_generated_count": 0,
        "status": "PENDING_DEPOSIT",
    })
    quote["status"] = "CONVERTED"
    db.touch(quote)
    return success(public(rec), status=201)


@bp.get("/service-agreements")
def list_agreements():
    require_roles({"Customer", "Billing", "Dispatcher"})
    limit, offset = pagination_params()
    property_id = request.args.get("property_id")
    quote_id = request.args.get("quote_id")
    rows = list(db.agreements.values())
    if property_id is not None:
        rows = [a for a in rows if a["property_id"] == property_id]
    if quote_id is not None:
        rows = [a for a in rows if a["quote_id"] == quote_id]
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


@bp.get("/service-agreements/<rid>")
def read_agreement(rid):
    require_roles({"Customer", "Billing", "Dispatcher"})
    rec = get_or_404(db.agreements, rid)
    return success(public(rec))


@bp.get("/service-agreements/<rid>/visits")
def list_agreement_visits(rid):
    require_roles({"Customer", "Billing", "Dispatcher"})
    get_or_404(db.agreements, rid)
    limit, offset = pagination_params()
    rows = [v for v in db.visits.values() if v["agreement_id"] == rid]
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


@bp.get("/service-agreements/<rid>/deposits")
def list_agreement_deposits(rid):
    require_roles({"Billing", "Customer"})
    get_or_404(db.agreements, rid)
    limit, offset = pagination_params()
    rows = [d for d in db.deposits.values() if d["agreement_id"] == rid]
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


@bp.post("/service-agreements/<rid>/activate")
def activate_agreement(rid):
    require_roles({"Billing"})
    rec = get_or_404(db.agreements, rid)
    data = body()
    first_planned = req_str(data, "first_visit_planned_date")
    win_start = req_int(data, "first_visit_window_start_min")
    win_end = req_int(data, "first_visit_window_end_min")
    if not (0 <= win_start < win_end <= 1440):
        raise err("ERR_INVALID_REQUEST", "invalid visit window")

    if rec["status"] != "PENDING_DEPOSIT":
        raise err("ERR_INVALID_STATE", "Agreement is not in PENDING_DEPOSIT")
    # Deposit-met check: HELD deposits standing against THIS agreement.
    held = sum(
        d["amount_cents"]
        for d in db.deposits.values()
        if d["agreement_id"] == rid and d["status"] == "HELD"
    )
    if held < rec["required_deposit_cents"]:
        raise err("ERR_DEPOSIT_NOT_MET", "HELD deposits below required_deposit_cents")

    rec["status"] = "ACTIVE"
    # Generate first visit (UNSCHEDULED) using the agreement's property + quote.
    prop = db.properties.get(rec["property_id"])
    quote = db.quotes.get(rec["quote_id"])
    generate_visit(
        rec, first_planned, win_start, win_end,
        requires_soft_wash(quote), requires_high_rise(prop),
    )
    rec["visits_generated_count"] = 1
    db.touch(rec)
    return success(public(rec))


@bp.post("/service-agreements/<rid>/pause")
def pause_agreement(rid):
    require_roles({"Customer"})
    rec = get_or_404(db.agreements, rid)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Agreement is not in ACTIVE")
    rec["status"] = "PAUSED"
    db.touch(rec)
    # Cancel this agreement's SCHEDULED visits, freeing route minutes.
    for v in db.visits.values():
        if v["agreement_id"] == rid and v["schedule_status"] == "SCHEDULED":
            cancel_visit_for_cascade(v)
    return success(public(rec))


@bp.post("/service-agreements/<rid>/resume")
def resume_agreement(rid):
    require_roles({"Customer"})
    rec = get_or_404(db.agreements, rid)
    if rec["status"] != "PAUSED":
        raise err("ERR_INVALID_STATE", "Agreement is not in PAUSED")
    rec["status"] = "ACTIVE"
    db.touch(rec)
    return success(public(rec))


@bp.post("/service-agreements/<rid>/complete")
def complete_agreement(rid):
    require_roles({"Billing"})
    rec = get_or_404(db.agreements, rid)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Agreement is not in ACTIVE")
    visits = [v for v in db.visits.values() if v["agreement_id"] == rid]
    if rec["schedule_kind"] == "ONE_TIME":
        # The single visit must be COMPLETED.
        ok = any(v["schedule_status"] == "COMPLETED" for v in visits)
        open_ones = any(
            v["schedule_status"] in ("SCHEDULED", "DISPATCHED", "IN_PROGRESS")
            for v in visits
        )
        if open_ones or not ok:
            raise err("ERR_OPEN_VISITS_EXIST", "Open visits remain")
    else:  # RECURRING
        open_ones = any(
            v["schedule_status"] in ("SCHEDULED", "DISPATCHED", "IN_PROGRESS")
            for v in visits
        )
        if open_ones:
            raise err("ERR_OPEN_VISITS_EXIST", "Open visits remain")
    rec["status"] = "COMPLETED"
    db.touch(rec)
    _refund_held_deposits(rec)
    return success(public(rec))


@bp.post("/service-agreements/<rid>/cancel")
def cancel_agreement(rid):
    require_roles({"Customer"})
    rec = get_or_404(db.agreements, rid)
    if rec["status"] not in ("PENDING_DEPOSIT", "ACTIVE", "PAUSED"):
        raise err("ERR_INVALID_STATE", "Agreement is not cancellable")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    # Cancel SCHEDULED|UNSCHEDULED visits, freeing route minutes for committed.
    for v in db.visits.values():
        if v["agreement_id"] == rid and v["schedule_status"] in ("SCHEDULED", "UNSCHEDULED"):
            cancel_visit_for_cascade(v)
    _refund_held_deposits(rec)
    return success(public(rec))
