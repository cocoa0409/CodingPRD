"""Closing packages, track events, settlement statements, termination."""

from decimal import Decimal

from flask import Blueprint, request

import db
import serializers
from errors import (
    raise_err, ERR_INVALID_AUCTION_STATE, ERR_INVALID_DEPOSIT_STATE,
    ERR_INVALID_CLOSING_STATE, ERR_DISCLOSURE_NOT_ACKNOWLEDGED,
    ERR_CLOSING_DATE_PAST, ERR_DUPLICATE_RECORD, ERR_VALIDATION,
)
from middleware import auth, require_roles, forbid
from response import (
    success_object, success_list, get_body, as_str, as_enum, as_decimal,
    as_datetime, new_common, touch, paginate, fmt_dt,
)
from services import sweeps
from services.settlement import (
    winning_scope_tracts, appraisal_map, commission_calc, closing_costs_final,
    closing_costs_provisional, possession_proration, money,
)
from .clock import get_or_404, new_id

bp = Blueprint("closings", __name__)

READ_ROLES = {"BrokerAgent", "Seller", "PlatformAdmin"}
AXES = ("TITLE", "SURVEY", "FUNDING")

# axis transition tables: current_status -> {event: next_status}
TITLE_EVENTS = {
    "NOT_ORDERED": {"ORDER": "ORDERED", "ORDER_COMMITMENT": "ORDERED"},
    "ORDERED": {
        "RECEIVE_COMMITMENT": "COMMITMENT_RECEIVED",
        "COMMITMENT_RECEIVED": "COMMITMENT_RECEIVED",
        "RAISE_EXCEPTION": "EXCEPTION_RAISED",
        "EXCEPTION_RAISED": "EXCEPTION_RAISED",
    },
    "COMMITMENT_RECEIVED": {
        "CLEAR": "CLEARED",
        "CLEARED": "CLEARED",
        "RAISE_EXCEPTION": "EXCEPTION_RAISED",
        "EXCEPTION_RAISED": "EXCEPTION_RAISED",
    },
    "EXCEPTION_RAISED": {
        "CURE": "COMMITMENT_RECEIVED",
        "CURE_EXCEPTION": "COMMITMENT_RECEIVED",
    },
}
SURVEY_EVENTS = {
    "NOT_ORDERED": {"ORDER": "ORDERED", "WAIVE": "WAIVED"},
    "ORDERED": {"COMPLETE": "COMPLETED", "COMPLETED": "COMPLETED"},
}
FUNDING_EVENTS = {
    "UNFUNDED": {"RECEIVE_FUNDS": "FUNDS_RECEIVED", "FUNDS_RECEIVED": "FUNDS_RECEIVED"},
    "FUNDS_RECEIVED": {"DISBURSE": "DISBURSED"},
}


def _closing_listing(closing):
    auction = db.auctions.get(closing["auction_id"])
    return db.listings.get(auction["listing_id"]) if auction else None


def _read_access(closing, user_id, role):
    if role == "BrokerAgent" or role == "Seller":
        listing = _closing_listing(closing)
        if role == "BrokerAgent" and listing["agent_id"] != user_id:
            forbid("caller is not the listing's agent")
        if role == "Seller" and listing["seller_id"] != user_id:
            forbid("caller is not the listing's seller")


def _derive_overall(c):
    if c["funding_status"] == "DISBURSED":
        return "CLOSED"
    if c["title_status"] == "CLEARED" and c["survey_status"] in ("COMPLETED", "WAIVED"):
        return "READY_TO_CLOSE"
    if (c["title_status"] != "NOT_ORDERED" or c["survey_status"] != "NOT_ORDERED"
            or c["funding_status"] != "UNFUNDED"):
        return "COORDINATION"
    return "INITIATED"


# ---------------------------------------------------------------------------
# Closing creation and reads
# ---------------------------------------------------------------------------

@bp.post("/api/closings")
def create_closing():
    user_id, role = auth()
    require_roles(role, {"BrokerAgent"})
    body = get_body()
    auction_id = body.get("auction_id")
    if auction_id is None:
        raise_err(ERR_VALIDATION, "missing required field: auction_id")
    auction = get_or_404(db.auctions, auction_id, "auction")
    listing = get_or_404(db.listings, auction["listing_id"], "listing")
    if listing["agent_id"] != user_id:
        forbid("caller is not the listing's agent")

    target = as_datetime(body, "target_closing_date")
    payoff = as_decimal(body, "payoff_amount", ge=0)

    # Fixed gate order: auction state, deposit states, disclosures, date, uniqueness.
    if auction["status"] != "AWARDED":
        raise_err(ERR_INVALID_AUCTION_STATE, "closing requires an AWARDED auction")

    winners = [b for b in db.bids.values()
               if b["auction_id"] == auction["id"] and b["status"] == "CONFIRMED_WINNER"]
    for b in winners:
        dep = next((d for d in db.deposits.values() if d["bid_id"] == b["id"]), None)
        if dep is None or dep["status"] != "VERIFIED":
            raise_err(ERR_INVALID_DEPOSIT_STATE,
                      "every winning bid's deposit must be VERIFIED")

    scope_tracts = winning_scope_tracts(auction)
    for t in scope_tracts:
        for d in db.disclosures.values():
            if d["tract_id"] == t["id"] and d["status"] != "ACKNOWLEDGED":
                raise_err(ERR_DISCLOSURE_NOT_ACKNOWLEDGED,
                          "every in-scope lease disclosure must be ACKNOWLEDGED")

    if not (target > db.clock_now()):
        raise_err(ERR_CLOSING_DATE_PAST,
                  "target_closing_date must be strictly after the logical clock")

    if any(c["auction_id"] == auction["id"] for c in db.closings.values()):
        raise_err(ERR_DUPLICATE_RECORD, "auction already has a closing package")

    c = new_common({
        "id": new_id(),
        "auction_id": auction["id"],
        "target_closing_date": fmt_dt(target),
        "_target_dt": target,
        "payoff_amount": payoff,
        "title_status": "NOT_ORDERED",
        "survey_status": "NOT_ORDERED",
        "funding_status": "UNFUNDED",
        "overall_status": "INITIATED",
    })
    db.closings[c["id"]] = c
    return success_object(serializers.closing(c), status=201)


@bp.get("/api/closings/<cid>")
def get_closing(cid):
    user_id, role = auth()
    require_roles(role, READ_ROLES)
    c = get_or_404(db.closings, cid, "closing")
    _read_access(c, user_id, role)
    return success_object(serializers.closing(c))


@bp.get("/api/auctions/<aid>/closings")
def list_auction_closings(aid):
    user_id, role = auth()
    require_roles(role, READ_ROLES)
    auction = get_or_404(db.auctions, aid, "auction")
    listing = get_or_404(db.listings, auction["listing_id"], "listing")
    if role == "BrokerAgent" and listing["agent_id"] != user_id:
        forbid("caller is not the listing's agent")
    if role == "Seller" and listing["seller_id"] != user_id:
        forbid("caller is not the listing's seller")
    items = [c for c in db.closings.values() if c["auction_id"] == auction["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serializers.closing(c) for c in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Track events
# ---------------------------------------------------------------------------

@bp.post("/api/closings/<cid>/track-events")
def track_event(cid):
    user_id, role = auth()
    require_roles(role, {"BrokerAgent", "PlatformAdmin"})
    c = get_or_404(db.closings, cid, "closing")
    listing = _closing_listing(c)
    if role == "BrokerAgent" and listing["agent_id"] != user_id:
        forbid("caller is not the listing's agent")

    body = get_body()
    axis = as_enum(body, "axis", AXES)
    event = as_str(body, "event")
    seller_consent = body.get("seller_consent")

    # Segregation of duties: TITLE/SURVEY are BrokerAgent-only; FUNDING admin-only.
    if axis == "FUNDING" and role != "PlatformAdmin":
        forbid("FUNDING track events are PlatformAdmin-only")
    if axis in ("TITLE", "SURVEY") and role != "BrokerAgent":
        forbid("TITLE and SURVEY track events are BrokerAgent-only")

    # Survey waiver requires explicit seller consent (schema-level failure).
    if axis == "SURVEY" and event == "WAIVE" and seller_consent is not True:
        raise_err(ERR_VALIDATION, "survey WAIVE requires seller_consent: true")

    if c["overall_status"] in ("CLOSED", "TERMINATED"):
        raise_err(ERR_INVALID_CLOSING_STATE,
                  "no track events on a CLOSED or TERMINATED closing")

    field = {"TITLE": "title_status", "SURVEY": "survey_status",
             "FUNDING": "funding_status"}[axis]
    table = {"TITLE": TITLE_EVENTS, "SURVEY": SURVEY_EVENTS,
             "FUNDING": FUNDING_EVENTS}[axis]
    current = c[field]
    nxt = table.get(current, {}).get(event)
    if nxt is None:
        raise_err(ERR_INVALID_CLOSING_STATE,
                  f"event {event} is not valid for {axis} in {current}")

    if axis == "FUNDING" and nxt == "DISBURSED":
        # Disbursement gates: READY_TO_CLOSE and a FINAL statement must exist.
        if c["overall_status"] != "READY_TO_CLOSE":
            raise_err(ERR_INVALID_CLOSING_STATE, "disbursement requires READY_TO_CLOSE")
        final_stmt = next(
            (s for s in db.statements.values()
             if s["closing_id"] == c["id"] and s["variant"] == "FINAL"
             and s["status"] == "FINAL"),
            None,
        )
        if final_stmt is None:
            raise_err(ERR_INVALID_CLOSING_STATE,
                      "disbursement requires a FINAL settlement statement")

    c[field] = nxt
    c["overall_status"] = _derive_overall(c)
    touch(c)

    if axis == "FUNDING" and nxt == "DISBURSED":
        _disburse_cascade(c, listing, final_stmt)

    return success_object(serializers.closing(c))


def _disburse_cascade(closing, listing, final_stmt):
    """Settles the whole sale chain at disbursement."""
    auction = db.auctions.get(closing["auction_id"])

    # Listing UNDER_CONTRACT -> CLOSED.
    if listing is not None and listing["status"] == "UNDER_CONTRACT":
        listing["status"] = "CLOSED"
        touch(listing)

    # VERIFIED deposits of this auction's winning bids -> APPLIED_TO_CLOSING.
    winning_bid_ids = {
        b["id"] for b in db.bids.values()
        if auction is not None and b["auction_id"] == auction["id"]
        and b["status"] == "CONFIRMED_WINNER"
    }
    for dep in db.deposits.values():
        if dep["bid_id"] in winning_bid_ids and dep["status"] == "VERIFIED":
            dep["amount_applied"] = dep["amount_received"]
            dep["status"] = "APPLIED_TO_CLOSING"
            touch(dep)

    # FINAL statement -> PAID.
    final_stmt["status"] = "PAID"
    touch(final_stmt)

    # In-scope ACKNOWLEDGED disclosures -> POSSESSION_TRANSFERRED.
    if auction is not None:
        for t in winning_scope_tracts(auction):
            for d in db.disclosures.values():
                if d["tract_id"] == t["id"] and d["status"] == "ACKNOWLEDGED":
                    d["status"] = "POSSESSION_TRANSFERRED"
                    touch(d)


# ---------------------------------------------------------------------------
# Settlement statements
# ---------------------------------------------------------------------------

@bp.post("/api/statements")
def create_statement():
    user_id, role = auth()
    require_roles(role, {"BrokerAgent"})
    body = get_body()
    closing_id = body.get("closing_id")
    if closing_id is None:
        raise_err(ERR_VALIDATION, "missing required field: closing_id")
    closing = get_or_404(db.closings, closing_id, "closing")
    listing = _closing_listing(closing)
    if listing["agent_id"] != user_id:
        forbid("caller is not the listing's agent")

    variant = as_enum(body, "variant", ("PROVISIONAL", "FINAL"))

    if closing["overall_status"] in ("CLOSED", "TERMINATED"):
        raise_err(ERR_INVALID_CLOSING_STATE,
                  "no statements on a CLOSED or TERMINATED closing")
    if variant == "FINAL" and closing["overall_status"] != "READY_TO_CLOSE":
        raise_err(ERR_INVALID_CLOSING_STATE,
                  "a FINAL statement requires READY_TO_CLOSE")
    if variant == "FINAL" and any(
            s["closing_id"] == closing["id"] and s["variant"] == "FINAL"
            and s["status"] == "FINAL" for s in db.statements.values()):
        raise_err(ERR_DUPLICATE_RECORD, "closing already has a FINAL statement")

    auction = get_or_404(db.auctions, closing["auction_id"], "auction")
    scope_tracts = winning_scope_tracts(auction)
    appraisals = appraisal_map(scope_tracts)

    # Pinned pipeline: gross -> commission -> costs -> rent credit -> net.
    gross = auction["awarded_total"]
    commission = commission_calc(gross, sum(appraisals.values()))
    if variant == "FINAL":
        allocated, tract_allocations = closing_costs_final(gross, scope_tracts, appraisals)
        rent_credit = possession_proration(closing, scope_tracts)
    else:
        allocated = closing_costs_provisional(gross)
        tract_allocations = None
        rent_credit = Decimal("0")
    payoff = closing["payoff_amount"]
    seller_net = money(gross - commission - allocated - payoff - rent_credit)

    # A fresh statement supersedes the standing one of the same family.
    for s in db.statements.values():
        if s["closing_id"] != closing["id"] or s["status"] == "SUPERSEDED":
            continue
        if variant == "PROVISIONAL" and s["status"] == "PROVISIONAL":
            s["status"] = "SUPERSEDED"
            touch(s)
        if variant == "FINAL" and s["status"] == "PROVISIONAL":
            s["status"] = "SUPERSEDED"
            touch(s)

    st = new_common({
        "id": new_id(),
        "closing_id": closing["id"],
        "variant": variant,
        "gross_price": gross,
        "commission_amount": commission,
        "allocated_seller_costs": allocated,
        "tract_allocations": tract_allocations,
        "payoff_amount": payoff,
        "rent_credit": rent_credit,
        "seller_net": seller_net,
        "status": variant,
    })
    db.statements[st["id"]] = st
    return success_object(serializers.statement(st), status=201)


@bp.get("/api/closings/<cid>/statements")
def list_statements(cid):
    user_id, role = auth()
    require_roles(role, READ_ROLES)
    c = get_or_404(db.closings, cid, "closing")
    _read_access(c, user_id, role)
    items = [s for s in db.statements.values() if s["closing_id"] == c["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serializers.statement(s) for s in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Termination
# ---------------------------------------------------------------------------

@bp.post("/api/closings/<cid>/terminate")
def terminate_closing(cid):
    user_id, role = auth()
    require_roles(role, {"BrokerAgent"})
    c = get_or_404(db.closings, cid, "closing")
    listing = _closing_listing(c)
    if listing["agent_id"] != user_id:
        forbid("caller is not the listing's agent")
    if c["overall_status"] not in ("INITIATED", "COORDINATION", "READY_TO_CLOSE"):
        raise_err(ERR_INVALID_CLOSING_STATE,
                  "only a non-CLOSED, non-TERMINATED closing can be terminated")

    auction = db.auctions.get(c["auction_id"])

    # VERIFIED deposits of winning bids -> REFUNDED.
    winning_bids = [b for b in db.bids.values()
                    if auction is not None and b["auction_id"] == auction["id"]
                    and b["status"] == "CONFIRMED_WINNER"]
    winning_bid_ids = {b["id"] for b in winning_bids}
    for dep in db.deposits.values():
        if dep["bid_id"] in winning_bid_ids and dep["status"] == "VERIFIED":
            dep["amount_refunded"] = dep["amount_received"]
            dep["status"] = "REFUNDED"
            touch(dep)

    # Winning bids -> VOIDED; auction AWARDED -> NO_SALE.
    for b in winning_bids:
        b["status"] = "VOIDED"
        touch(b)
    if auction is not None and auction["status"] == "AWARDED":
        auction["status"] = "NO_SALE"
        touch(auction)

    # Listing UNDER_CONTRACT -> MARKETED; tracts SOLD -> OFFERED.
    if listing is not None:
        if listing["status"] == "UNDER_CONTRACT":
            listing["status"] = "MARKETED"
            touch(listing)
        for t in sweeps.listing_tracts(listing["id"]):
            if t["status"] == "SOLD":
                t["status"] = "OFFERED"
                touch(t)
        sweeps.unlock_rights_if_idle(listing)

    # Statements PROVISIONAL/FINAL -> SUPERSEDED.
    for s in db.statements.values():
        if s["closing_id"] == c["id"] and s["status"] in ("PROVISIONAL", "FINAL"):
            s["status"] = "SUPERSEDED"
            touch(s)

    c["overall_status"] = "TERMINATED"
    touch(c)
    return success_object(serializers.closing(c))
