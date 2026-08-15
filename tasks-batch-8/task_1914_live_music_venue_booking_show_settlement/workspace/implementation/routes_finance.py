"""Settlement lifecycle, wire transfers, cancellation and postponement
(PRD 3.7, 3.8, 3.9)."""

from decimal import Decimal

from flask import Blueprint, g, request

import store
from domain import (TERMINAL_SUPPORT, cancellation_figures,
                    compute_settlement_fields, low_sales_threshold,
                    recompute_draft_settlement, refund_sale, rhu)
from envelope import created, ok
from errors import (already_terminal, biz, invalid_request, invalid_state,
                    not_found, stale_version)
from helpers import (body, filter_eq, get_child, get_show, list_response,
                     lookup, opt_int, opt_str, req_date, req_dt, req_enum,
                     req_expected_show_version, req_int, require_roles,
                     ser_cancellation, ser_settlement, ser_show, ser_wire)
from routes_production import _make_wire, _settlement_for_show
from routes_roster import _create_show

bp = Blueprint("finance", __name__)

SETTLEMENT_READ = ("VenueManager", "Promoter", "Accountant", "BookingAgent")
WIRE_READ = ("VenueManager", "Promoter", "Accountant")
SHOW_TERMINAL = {"SETTLED", "CANCELLED"}
PURPOSES = ("ARTIST_DEPOSIT", "ARTIST_BALANCE", "SUPPORT_FEE", "SUPPORT_BUYOUT", "REFUND_TO_VENUE")
REASONS = ("ARTIST", "VENUE", "FORCE_MAJEURE", "LOW_TICKET_SALES")
SETTLEMENT_WIRE_PURPOSES = {"ARTIST_BALANCE", "SUPPORT_FEE", "SUPPORT_BUYOUT"}


def _show_terminal_or(show, msg):
    if show["status"] in SHOW_TERMINAL:
        raise already_terminal("Show is already in a terminal state")
    raise invalid_state(msg)


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------
@bp.get("/settlements/<sid>")
def get_settlement_top(sid):
    require_roles(*SETTLEMENT_READ)
    return ok(ser_settlement(lookup(store.settlements, sid, "Settlement")))


@bp.get("/settlements")
def list_settlements():
    require_roles(*SETTLEMENT_READ)
    items = list(store.settlements.values())
    items = filter_eq(items, "show_id", request.args.get("show_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    return list_response(items, ser_settlement)


@bp.post("/shows/<sid>/settlement")
def create_settlement(sid):
    require_roles("Promoter")
    show = get_show(sid)
    if _settlement_for_show(show) is not None:
        raise invalid_state("Each show has exactly one settlement")
    if not show.get("deal_id"):
        raise invalid_state("A settlement requires an accepted deal")
    fields = compute_settlement_fields(show)
    st = store.new_common({
        "show_id": show["id"],
        "status": "DRAFT",
        "submitted_at_utc": None,
        "approved_by_user_id": None,
        "submitted_by_user_id": None,
        **fields,
    })
    store.settlements[st["id"]] = st
    return created(ser_settlement(st))


@bp.get("/shows/<sid>/settlement")
def get_show_settlement(sid):
    require_roles(*SETTLEMENT_READ)
    show = get_show(sid)
    st = _settlement_for_show(show)
    if st is None:
        raise not_found("Show has no settlement")
    return ok(ser_settlement(st))


@bp.post("/shows/<sid>/settlement/submit")
def submit_settlement(sid):
    require_roles("Promoter")
    show = get_show(sid)
    st = _settlement_for_show(show)
    if st is None:
        raise not_found("Show has no settlement")
    if st["status"] != "DRAFT":
        if st["status"] == "PAID":
            raise already_terminal("Settlement is already PAID")
        raise invalid_state("Only a DRAFT settlement can be submitted")
    if show["status"] != "SHOW_NIGHT":
        _show_terminal_or(show, "Settlement can only be submitted on SHOW_NIGHT")
    # OCC (rule 6) precedes readiness (rule 18)
    expected = req_expected_show_version(body())
    if expected != show["version"]:
        raise stale_version()
    pending_receipts = any(r["show_id"] == show["id"] and r["status"] == "PENDING"
                           for r in store.expense_receipts.values())
    open_supports = any(a["show_id"] == show["id"] and a["status"] not in TERMINAL_SUPPORT
                        for a in store.support_acts.values())
    if pending_receipts or open_supports:
        raise biz("ERR_SETTLEMENT_NOT_READY",
                  "All expense receipts and support acts must be in a terminal state")
    st["submitted_at_utc"] = store.mint_stamp()
    st["submitted_by_user_id"] = g.user_id
    st["status"] = "SUBMITTED"
    store.touch(st)
    store.bump_show(show)
    return ok(ser_settlement(st))


@bp.post("/shows/<sid>/settlement/approve")
def approve_settlement(sid):
    require_roles("Accountant")
    show = get_show(sid)
    st = _settlement_for_show(show)
    if st is None:
        raise not_found("Show has no settlement")
    if st["status"] != "SUBMITTED":
        if st["status"] == "PAID":
            raise already_terminal("Settlement is already PAID")
        raise invalid_state("Only a SUBMITTED settlement can be approved")
    # Rule 19: segregation of duties
    if g.user_id == st.get("submitted_by_user_id"):
        raise biz("ERR_SEGREGATION_OF_DUTIES",
                  "The settlement approver must differ from its submitter")
    st["approved_by_user_id"] = g.user_id
    st["status"] = "APPROVED"
    store.touch(st)
    if st["artist_total_due_cents"] > 0:
        _make_wire(show, "ARTIST_BALANCE", st["artist_total_due_cents"],
                   recipient_artist_id=show["artist_id"], settlement_id=st["id"])
    return ok(ser_settlement(st))


@bp.post("/shows/<sid>/settlement/dispute")
def dispute_settlement(sid):
    require_roles("BookingAgent")
    show = get_show(sid)
    st = _settlement_for_show(show)
    if st is None:
        raise not_found("Show has no settlement")
    if st["status"] != "SUBMITTED":
        if st["status"] == "PAID":
            raise already_terminal("Settlement is already PAID")
        raise invalid_state("Only a SUBMITTED settlement can be disputed")
    st["status"] = "DISPUTED"
    store.touch(st)
    return ok(ser_settlement(st))


@bp.post("/shows/<sid>/settlement/return-to-draft")
def return_settlement_to_draft(sid):
    require_roles("Promoter")
    show = get_show(sid)
    st = _settlement_for_show(show)
    if st is None:
        raise not_found("Show has no settlement")
    if st["status"] != "DISPUTED":
        if st["status"] == "PAID":
            raise already_terminal("Settlement is already PAID")
        raise invalid_state("Only a DISPUTED settlement can return to draft")
    st["status"] = "DRAFT"
    st.update(compute_settlement_fields(show))
    store.touch(st)
    return ok(ser_settlement(st))


# ---------------------------------------------------------------------------
# Wire transfers
# ---------------------------------------------------------------------------
@bp.get("/wire-transfers/<wid>")
def get_wire_top(wid):
    require_roles(*WIRE_READ)
    return ok(ser_wire(lookup(store.wire_transfers, wid, "WireTransfer")))


@bp.get("/wire-transfers")
def list_wires_top():
    require_roles(*WIRE_READ)
    items = list(store.wire_transfers.values())
    items = filter_eq(items, "show_id", request.args.get("show_id"))
    items = filter_eq(items, "purpose", request.args.get("purpose"))
    items = filter_eq(items, "status", request.args.get("status"))
    items = filter_eq(items, "recipient_artist_id", request.args.get("recipient_artist_id"))
    items = filter_eq(items, "support_act_id", request.args.get("support_act_id"))
    items = filter_eq(items, "settlement_id", request.args.get("settlement_id"))
    return list_response(items, ser_wire)


@bp.post("/shows/<sid>/wire-transfers")
def create_wire(sid):
    require_roles("Accountant")
    show = get_show(sid)
    b = body()
    purpose = req_enum(b, "purpose", PURPOSES)
    amount = req_int(b, "amount_cents")
    recipient_artist_id = opt_str(b, "recipient_artist_id")
    support_act_id = opt_str(b, "support_act_id")
    settlement_id = opt_str(b, "settlement_id")

    # Reference shape per purpose (PRD 3.8)
    if purpose in ("ARTIST_DEPOSIT", "ARTIST_BALANCE"):
        if recipient_artist_id is None:
            raise invalid_request("recipient_artist_id is required for artist-bound wires")
        if support_act_id is not None:
            raise invalid_request("support_act_id must be null for artist-bound wires")
    elif purpose in ("SUPPORT_FEE", "SUPPORT_BUYOUT"):
        if support_act_id is None:
            raise invalid_request("support_act_id is required for support wires")
        if recipient_artist_id is not None:
            raise invalid_request("recipient_artist_id must be null for support wires")
    if purpose == "ARTIST_BALANCE":
        if settlement_id is None:
            raise invalid_request("settlement_id is required for ARTIST_BALANCE wires")
    elif settlement_id is not None:
        raise invalid_request("settlement_id must be null unless purpose is ARTIST_BALANCE")

    # Body-referenced FK existence (pipeline step 4)
    if recipient_artist_id is not None:
        lookup(store.artists, recipient_artist_id, "Artist")
    act = None
    if support_act_id is not None:
        act = get_child(store.support_acts, show, support_act_id, "SupportAct")
    st = None
    if settlement_id is not None:
        st = store.settlements.get(settlement_id)
        if st is None or st["show_id"] != show["id"]:
            raise not_found("Settlement not found")

    # Rule 17: canonical amounts
    if amount <= 0:
        raise biz("ERR_WIRE_AMOUNT_MISMATCH", "amount_cents must be strictly positive")
    if purpose == "ARTIST_BALANCE" and amount != st["artist_total_due_cents"]:
        raise biz("ERR_WIRE_AMOUNT_MISMATCH",
                  "ARTIST_BALANCE wire must equal the settlement's artist_total_due_cents")
    if purpose == "SUPPORT_FEE" and amount != act["agreed_fee_cents"]:
        raise biz("ERR_WIRE_AMOUNT_MISMATCH",
                  "SUPPORT_FEE wire must equal the act's agreed_fee_cents")
    if purpose == "SUPPORT_BUYOUT" and amount != act["buyout_fee_cents"]:
        raise biz("ERR_WIRE_AMOUNT_MISMATCH",
                  "SUPPORT_BUYOUT wire must equal the act's buyout_fee_cents")

    w = _make_wire(show, purpose, amount, recipient_artist_id=recipient_artist_id,
                   support_act_id=support_act_id, settlement_id=settlement_id)
    return created(ser_wire(w))


@bp.get("/shows/<sid>/wire-transfers")
def list_wires(sid):
    require_roles(*WIRE_READ)
    show = get_show(sid)
    items = [w for w in store.wire_transfers.values() if w["show_id"] == show["id"]]
    items = filter_eq(items, "purpose", request.args.get("purpose"))
    items = filter_eq(items, "status", request.args.get("status"))
    return list_response(items, ser_wire)


@bp.get("/shows/<sid>/wire-transfers/<wid>")
def get_wire(sid, wid):
    require_roles(*WIRE_READ)
    show = get_show(sid)
    return ok(ser_wire(get_child(store.wire_transfers, show, wid, "WireTransfer")))


def _wire_state(wire, action, valid_from):
    if wire["status"] not in valid_from:
        if wire["status"] in ("COMPLETED", "FAILED", "RETURNED"):
            raise already_terminal("WireTransfer is already in a terminal state")
        raise invalid_state("WireTransfer is not in a valid from-state for %s" % action)


def _maybe_settle_show(show):
    """SHOW_NIGHT -> SETTLED once settlement is PAID and every payout wire is
    COMPLETED."""
    if show["status"] != "SHOW_NIGHT":
        return
    st = _settlement_for_show(show)
    if st is None or st["status"] != "PAID":
        return
    wires = [w for w in store.wire_transfers.values()
             if w["show_id"] == show["id"] and w["purpose"] in SETTLEMENT_WIRE_PURPOSES]
    if all(w["status"] == "COMPLETED" for w in wires):
        show["status"] = "SETTLED"
        store.bump_show(show)


@bp.post("/shows/<sid>/wire-transfers/<wid>/complete")
def complete_wire(sid, wid):
    require_roles("Accountant")
    show = get_show(sid)
    wire = get_child(store.wire_transfers, show, wid, "WireTransfer")
    _wire_state(wire, "complete", ("INITIATED",))
    wire["status"] = "COMPLETED"
    wire["completed_at_utc"] = store.mint_stamp()
    store.touch(wire)
    purpose = wire["purpose"]
    if purpose == "ARTIST_DEPOSIT":
        show["deposit_paid_cents"] += wire["amount_cents"]
        store.bump_show(show)
    elif purpose == "ARTIST_BALANCE":
        st = store.settlements.get(wire.get("settlement_id")) if wire.get("settlement_id") else None
        if st is not None and st["status"] == "APPROVED":
            st["status"] = "PAID"
            store.touch(st)
        _maybe_settle_show(show)
    elif purpose in ("SUPPORT_FEE", "SUPPORT_BUYOUT"):
        act = store.support_acts.get(wire.get("support_act_id")) if wire.get("support_act_id") else None
        if act is not None:
            act["paid_cents"] += wire["amount_cents"]
            store.touch(act)
        _maybe_settle_show(show)
    return ok(ser_wire(wire))


@bp.post("/shows/<sid>/wire-transfers/<wid>/fail")
def fail_wire(sid, wid):
    require_roles("Accountant")
    show = get_show(sid)
    wire = get_child(store.wire_transfers, show, wid, "WireTransfer")
    _wire_state(wire, "fail", ("INITIATED",))
    reason = None
    b = body()
    if "failure_reason" not in b or not isinstance(b["failure_reason"], str) or not b["failure_reason"]:
        raise invalid_request("failure_reason is required")
    reason = b["failure_reason"]
    wire["status"] = "FAILED"
    wire["failure_reason"] = reason
    store.touch(wire)
    return ok(ser_wire(wire))


@bp.post("/shows/<sid>/wire-transfers/<wid>/retry")
def retry_wire(sid, wid):
    require_roles("Accountant")
    show = get_show(sid)
    wire = get_child(store.wire_transfers, show, wid, "WireTransfer")
    _wire_state(wire, "retry", ("FAILED",))
    wire["status"] = "INITIATED"
    wire["failure_reason"] = None
    store.touch(wire)
    return ok(ser_wire(wire))


@bp.post("/shows/<sid>/wire-transfers/<wid>/mark-returned")
def return_wire(sid, wid):
    require_roles("Accountant")
    show = get_show(sid)
    wire = get_child(store.wire_transfers, show, wid, "WireTransfer")
    _wire_state(wire, "mark-returned", ("COMPLETED",))
    if show["status"] != "CANCELLED" or wire["purpose"] != "ARTIST_DEPOSIT":
        raise invalid_state("Only a COMPLETED ARTIST_DEPOSIT wire on a CANCELLED show can be returned")
    wire["status"] = "RETURNED"
    store.touch(wire)
    show["deposit_paid_cents"] -= wire["amount_cents"]
    store.bump_show(show)
    return ok(ser_wire(wire))


# ---------------------------------------------------------------------------
# Cancellation / postponement
# ---------------------------------------------------------------------------
@bp.post("/shows/<sid>/cancel")
def cancel_show(sid):
    require_roles("BookingAgent", "VenueManager", "Promoter")
    show = get_show(sid)
    if show["status"] == "POSTPONED":
        # POSTPONED -> CANCELLED belongs to the VenueManager alone
        if g.user_role != "VenueManager":
            from errors import forbidden
            raise forbidden("Only a VenueManager may cancel a POSTPONED show")
    elif show["status"] not in ("CONFIRMED", "ON_SALE", "ADVANCED"):
        _show_terminal_or(show, "Show cannot be cancelled from its current state")
    b = body()
    reason = req_enum(b, "reason", REASONS)
    # Rule 7: the low-sales gate, before the cascade
    if reason == "LOW_TICKET_SALES":
        if show["status"] != "ON_SALE" \
                or show["tickets_sold"] >= low_sales_threshold(show["total_capacity"]):
            raise biz("ERR_LOW_SALES_THRESHOLD_NOT_MET",
                      "LOW_TICKET_SALES requires ON_SALE and tickets_sold below 30% of capacity")

    deal = store.deals.get(show["deal_id"]) if show.get("deal_id") else None
    confirmed_supports = [a for a in store.support_acts.values()
                          if a["show_id"] == show["id"] and a["status"] == "CONFIRMED"]
    figs = cancellation_figures(show, reason, deal, confirmed_supports)

    role_map = {"BookingAgent": "BOOKING_AGENT", "VenueManager": "VENUE_MANAGER",
                "Promoter": "PROMOTER"}
    event = store.new_ledger({
        "show_id": show["id"],
        "reason": reason,
        "declared_by_role": role_map[g.user_role],
        "declared_at_utc": store.mint_stamp(),
        **figs,
    })
    store.cancellation_events[event["id"]] = event

    # Cascade: refund outstanding tickets (a postponed show already refunded them)
    for sale in [s for s in store.ticket_sales.values()
                 if s["show_id"] == show["id"] and s["refund_status"] == "NONE"]:
        sale["refund_status"] = "REFUNDED"
        for tier_id, qty in sale["_alloc"].items():
            tier = store.ticket_tiers.get(tier_id)
            if tier is not None:
                tier["sold_count"] -= qty
                tier["refund_count"] += qty
                store.touch(tier)
    from domain import recompute_show_ticket_counters
    recompute_show_ticket_counters(show)

    # Support acts: CONFIRMED -> CANCELLED with kill-fee wires per policy
    if reason in ("ARTIST", "VENUE", "LOW_TICKET_SALES"):
        for act in confirmed_supports:
            act["status"] = "CANCELLED"
            store.touch(act)
            _make_wire(show, "SUPPORT_BUYOUT",
                       rhu(Decimal(act["agreed_fee_cents"]) * Decimal("0.5")),
                       support_act_id=act["id"])
    else:
        for act in confirmed_supports:
            act["status"] = "CANCELLED"
            store.touch(act)

    # Deposit refund wire (only when there is a positive refundable amount)
    if figs["deposit_refundable_cents"] > 0 and show["deposit_paid_cents"] > 0 \
            and reason in ("ARTIST", "FORCE_MAJEURE"):
        _make_wire(show, "REFUND_TO_VENUE", figs["deposit_refundable_cents"])

    if deal is not None:
        deal["status"] = "VOID"
        store.touch(deal)
    if reason == "FORCE_MAJEURE":
        show["weather_or_emergency_flag"] = True
    show["cancellation_reason"] = reason
    show["status"] = "CANCELLED"
    store.bump_show(show)
    return created(ser_cancellation(event))


@bp.get("/shows/<sid>/cancellation-events")
def list_cancellations(sid):
    require_roles("VenueManager", "BookingAgent", "Promoter", "Accountant")
    show = get_show(sid)
    items = [c for c in store.cancellation_events.values() if c["show_id"] == show["id"]]
    return list_response(items, ser_cancellation)


@bp.post("/shows/<sid>/postpone")
def postpone_show(sid):
    require_roles("VenueManager")
    show = get_show(sid)
    if show["status"] not in ("CONFIRMED", "ON_SALE"):
        _show_terminal_or(show, "Only a CONFIRMED or ON_SALE show can be postponed")
    b = body()
    new_date = req_date(b, "new_show_date")
    new_doors = req_dt(b, "new_doors_at_utc")
    new_curfew = req_dt(b, "new_curfew_at_utc")
    if new_date <= show["_show_date_obj"]:
        raise biz("ERR_INVALID_SHOW_SCHEDULE", "new_show_date must be strictly later than show_date")
    if new_curfew <= new_doors:
        raise biz("ERR_INVALID_SHOW_SCHEDULE", "new_curfew_at_utc must be strictly later than new_doors_at_utc")
    if new_doors.date() != new_date:
        raise biz("ERR_INVALID_SHOW_SCHEDULE", "new_doors_at_utc must fall on new_show_date")

    # Tickets are refunded at postpone time, never transferred
    for sale in [s for s in store.ticket_sales.values()
                 if s["show_id"] == show["id"] and s["refund_status"] == "NONE"]:
        sale["refund_status"] = "REFUNDED"
        for tier_id, qty in sale["_alloc"].items():
            tier = store.ticket_tiers.get(tier_id)
            if tier is not None:
                tier["sold_count"] -= qty
                tier["refund_count"] += qty
                store.touch(tier)
    from domain import recompute_show_ticket_counters
    recompute_show_ticket_counters(show)

    show["status"] = "POSTPONED"
    store.bump_show(show)
    successor = _create_show(show["artist_id"], show["room"], new_date, new_doors,
                             new_curfew, show["total_capacity"], show["on_sale_at_utc"])
    return created(ser_show(successor))
