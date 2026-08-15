"""Advance checklist, support acts, expense receipts, ancillary revenue
(PRD 3.5, 3.6)."""

from flask import Blueprint, g, request

import store
from domain import check_support_budget, recompute_draft_settlement
from envelope import created, ok
from errors import (already_terminal, biz, invalid_request, invalid_state,
                    not_found)
from helpers import (body, filter_eq, get_child, get_show, list_response,
                     lookup, opt_bool, req_enum, req_int, req_str,
                     require_roles, ser_ancillary, ser_checklist, ser_receipt,
                     ser_show, ser_support)

bp = Blueprint("production", __name__)

CHECKLIST_READ = ("VenueManager", "ProductionManager", "Promoter")
SUPPORT_READ = ("VenueManager", "Promoter", "Accountant", "BookingAgent")
LEDGER_READ = ("VenueManager", "Promoter", "Accountant")
SHOW_TERMINAL = {"SETTLED", "CANCELLED"}

ITEM_FIELDS = {
    "hospitality": "hospitality_done",
    "tech": "tech_done",
    "backline": "backline_done",
    "production_requirements": "production_requirements_done",
    "insurance_cert": "insurance_cert_received",
    "w9": "w9_received",
}

CATEGORIES = ("SOUND", "LIGHTS", "BACKLINE", "HOSPITALITY", "SECURITY", "MARKETING", "MISC")


def _checklist_for(show):
    for c in store.advance_checklists.values():
        if c["show_id"] == show["id"]:
            return c
    raise not_found("AdvanceChecklist not found")


def _recompute_all_complete(c):
    c["all_complete"] = all(c[f] for f in ITEM_FIELDS.values())


# ---------------------------------------------------------------------------
# Advance checklist
# ---------------------------------------------------------------------------
@bp.get("/advance-checklists/<cid>")
def get_checklist_top(cid):
    require_roles(*CHECKLIST_READ)
    return ok(ser_checklist(lookup(store.advance_checklists, cid, "AdvanceChecklist")))


@bp.get("/advance-checklists")
def list_checklists():
    require_roles(*CHECKLIST_READ)
    items = list(store.advance_checklists.values())
    items = filter_eq(items, "show_id", request.args.get("show_id"))
    return list_response(items, ser_checklist)


@bp.get("/shows/<sid>/advance")
def get_show_advance(sid):
    require_roles(*CHECKLIST_READ)
    show = get_show(sid)
    return ok(ser_checklist(_checklist_for(show)))


def _toggle_item(sid, item_name, value):
    require_roles("ProductionManager")
    show = get_show(sid)
    # item_name resolves as part of path existence (PRD 2.9)
    field = ITEM_FIELDS.get(item_name)
    if field is None:
        raise not_found("Advance item not found")
    cl = _checklist_for(show)
    if show["status"] not in ("CONFIRMED", "ON_SALE"):
        if show["status"] in SHOW_TERMINAL:
            raise already_terminal("Show is already in a terminal state")
        raise invalid_state("Advance items can only be toggled while CONFIRMED or ON_SALE")
    if cl[field] != value:
        cl[field] = value
        _recompute_all_complete(cl)
        store.touch(cl)
    return ok(ser_checklist(cl))


@bp.post("/shows/<sid>/advance/items/<item_name>/complete")
def complete_item(sid, item_name):
    return _toggle_item(sid, item_name, True)


@bp.post("/shows/<sid>/advance/items/<item_name>/uncomplete")
def uncomplete_item(sid, item_name):
    return _toggle_item(sid, item_name, False)


@bp.post("/shows/<sid>/advance/complete")
def complete_advance(sid):
    require_roles("ProductionManager")
    show = get_show(sid)
    cl = _checklist_for(show)
    if show["status"] != "ON_SALE":
        if show["status"] in SHOW_TERMINAL:
            raise already_terminal("Show is already in a terminal state")
        raise invalid_state("Only an ON_SALE show can complete the advance")
    if not cl["all_complete"]:
        raise invalid_state("Advance checklist is not fully complete")
    show["status"] = "ADVANCED"
    store.bump_show(show)
    return ok(ser_show(show))


# ---------------------------------------------------------------------------
# Support acts
# ---------------------------------------------------------------------------
@bp.post("/shows/<sid>/support-acts")
def create_support(sid):
    require_roles("Promoter")
    show = get_show(sid)
    b = body()
    name = req_str(b, "artist_name")
    agreed = req_int(b, "agreed_fee_cents")
    buyout = req_int(b, "buyout_fee_cents")
    if agreed <= 0:
        raise biz("ERR_SUPPORT_BUDGET_EXCEEDED", "agreed_fee_cents must be strictly positive")
    # Fee band: [0.5 x agreed, agreed]
    if buyout * 2 < agreed or buyout > agreed:
        raise biz("ERR_SUPPORT_BUDGET_EXCEEDED",
                  "buyout_fee_cents must sit within [0.5 x agreed_fee_cents, agreed_fee_cents]")
    check_support_budget(show, extra_confirmed=agreed)
    a = store.new_common({
        "show_id": show["id"],
        "artist_name": name,
        "agreed_fee_cents": agreed,
        "buyout_fee_cents": buyout,
        "status": "CONFIRMED",
        "paid_cents": 0,
    })
    store.support_acts[a["id"]] = a
    return created(ser_support(a))


@bp.get("/shows/<sid>/support-acts")
def list_support(sid):
    require_roles(*SUPPORT_READ)
    show = get_show(sid)
    items = [a for a in store.support_acts.values() if a["show_id"] == show["id"]]
    items = filter_eq(items, "status", request.args.get("status"))
    return list_response(items, ser_support)


@bp.get("/shows/<sid>/support-acts/<aid>")
def get_support(sid, aid):
    require_roles(*SUPPORT_READ)
    show = get_show(sid)
    return ok(ser_support(get_child(store.support_acts, show, aid, "SupportAct")))


def _make_wire(show, purpose, amount, recipient_artist_id=None, support_act_id=None,
               settlement_id=None):
    w = store.new_common({
        "show_id": show["id"],
        "purpose": purpose,
        "amount_cents": amount,
        "recipient_artist_id": recipient_artist_id,
        "support_act_id": support_act_id,
        "status": "INITIATED",
        "initiated_by_role": "ACCOUNTANT",
        "initiated_at_utc": store.mint_stamp(),
        "completed_at_utc": None,
        "failure_reason": None,
        "settlement_id": settlement_id,
    })
    store.wire_transfers[w["id"]] = w
    return w


@bp.post("/shows/<sid>/support-acts/<aid>/buyout")
def buyout_support(sid, aid):
    require_roles("Promoter")
    show = get_show(sid)
    act = get_child(store.support_acts, show, aid, "SupportAct")
    if act["status"] != "CONFIRMED":
        raise already_terminal("SupportAct is already in a terminal state")
    if show["status"] not in ("CONFIRMED", "ON_SALE", "ADVANCED"):
        if show["status"] in SHOW_TERMINAL:
            raise already_terminal("Show is already in a terminal state")
        raise invalid_state("Buyout requires the show to be CONFIRMED, ON_SALE, or ADVANCED")
    # Budget check evaluated with this act moved into the BOUGHT_OUT column
    deal = store.deals.get(show["deal_id"]) if show.get("deal_id") else None
    if deal is not None and deal.get("support_budget_cents") is not None:
        act["status"] = "BOUGHT_OUT"  # provisionally, for the usage sum
        try:
            check_support_budget(show)
        finally:
            act["status"] = "CONFIRMED"
    act["status"] = "BOUGHT_OUT"
    store.touch(act)
    store.bump_show(show)
    _make_wire(show, "SUPPORT_BUYOUT", act["buyout_fee_cents"], support_act_id=act["id"])
    return ok(ser_support(act))


@bp.post("/shows/<sid>/support-acts/<aid>/mark-performed")
def perform_support(sid, aid):
    require_roles("Promoter")
    show = get_show(sid)
    act = get_child(store.support_acts, show, aid, "SupportAct")
    if act["status"] != "CONFIRMED":
        raise already_terminal("SupportAct is already in a terminal state")
    if show["status"] != "SHOW_NIGHT":
        if show["status"] in SHOW_TERMINAL:
            raise already_terminal("Show is already in a terminal state")
        raise invalid_state("Support acts can only be marked performed on SHOW_NIGHT")
    act["status"] = "PERFORMED"
    store.touch(act)
    store.bump_show(show)
    _make_wire(show, "SUPPORT_FEE", act["agreed_fee_cents"], support_act_id=act["id"])
    return ok(ser_support(act))


# ---------------------------------------------------------------------------
# Expense receipts
# ---------------------------------------------------------------------------
@bp.post("/shows/<sid>/expense-receipts")
def create_receipt(sid):
    require_roles("Promoter", "VenueManager")
    show = get_show(sid)
    b = body()
    category = req_enum(b, "category", CATEGORIES)
    amount = req_int(b, "amount_cents")
    if amount <= 0:
        raise invalid_request("amount_cents must be strictly positive")
    reference = req_str(b, "receipt_reference")
    recoupable = opt_bool(b, "is_recoupable", True)
    r = store.new_common({
        "show_id": show["id"],
        "category": category,
        "amount_cents": amount,
        "receipt_reference": reference,
        "submitted_by_role": "PROMOTER" if g.user_role == "Promoter" else "VENUE_MANAGER",
        "status": "PENDING",
        "rejection_reason": None,
        "is_recoupable": recoupable,
    })
    store.expense_receipts[r["id"]] = r
    return created(ser_receipt(r))


@bp.get("/shows/<sid>/expense-receipts")
def list_receipts(sid):
    require_roles(*LEDGER_READ)
    show = get_show(sid)
    items = [r for r in store.expense_receipts.values() if r["show_id"] == show["id"]]
    items = filter_eq(items, "status", request.args.get("status"))
    items = filter_eq(items, "category", request.args.get("category"))
    return list_response(items, ser_receipt)


@bp.get("/shows/<sid>/expense-receipts/<rid>")
def get_receipt(sid, rid):
    require_roles(*LEDGER_READ)
    show = get_show(sid)
    return ok(ser_receipt(get_child(store.expense_receipts, show, rid, "ExpenseReceipt")))


def _settlement_for_show(show):
    for s in store.settlements.values():
        if s["show_id"] == show["id"]:
            return s
    return None


@bp.post("/shows/<sid>/expense-receipts/<rid>/approve")
def approve_receipt(sid, rid):
    require_roles("VenueManager")
    show = get_show(sid)
    receipt = get_child(store.expense_receipts, show, rid, "ExpenseReceipt")
    if receipt["status"] != "PENDING":
        raise already_terminal("ExpenseReceipt is already in a terminal state")
    if show["status"] not in ("CONFIRMED", "ON_SALE", "ADVANCED", "SHOW_NIGHT"):
        if show["status"] in SHOW_TERMINAL:
            raise already_terminal("Show is already in a terminal state")
        raise invalid_state("Receipts can only be approved while the show is active")
    receipt["status"] = "APPROVED"
    store.touch(receipt)
    store.bump_show(show)
    settlement = _settlement_for_show(show)
    if settlement is not None and settlement["status"] == "DRAFT":
        recompute_draft_settlement(settlement)
    return ok(ser_receipt(receipt))


@bp.post("/shows/<sid>/expense-receipts/<rid>/reject")
def reject_receipt(sid, rid):
    require_roles("VenueManager")
    show = get_show(sid)
    receipt = get_child(store.expense_receipts, show, rid, "ExpenseReceipt")
    if receipt["status"] != "PENDING":
        raise already_terminal("ExpenseReceipt is already in a terminal state")
    reason = req_str(body(), "rejection_reason")
    receipt["status"] = "REJECTED"
    receipt["rejection_reason"] = reason
    store.touch(receipt)
    return ok(ser_receipt(receipt))


# ---------------------------------------------------------------------------
# Ancillary revenue
# ---------------------------------------------------------------------------
@bp.post("/shows/<sid>/ancillary-revenues")
def create_ancillary(sid):
    require_roles("Promoter", "VenueManager")
    show = get_show(sid)
    b = body()
    kind = req_enum(b, "kind", ("BAR", "MERCH"))
    gross = req_int(b, "gross_cents")
    if gross <= 0:
        raise invalid_request("gross_cents must be strictly positive")
    cost = req_int(b, "cost_cents")
    if cost < 0:
        raise invalid_request("cost_cents must be non-negative")
    a = store.new_ledger({
        "show_id": show["id"],
        "kind": kind,
        "gross_cents": gross,
        "cost_cents": cost,
        "recorded_by_role": "PROMOTER" if g.user_role == "Promoter" else "VENUE_MANAGER",
        "recorded_at_utc": store.mint_stamp(),
    })
    store.ancillary_revenues[a["id"]] = a
    return created(ser_ancillary(a))


@bp.get("/shows/<sid>/ancillary-revenues")
def list_ancillary(sid):
    require_roles(*LEDGER_READ)
    show = get_show(sid)
    items = [a for a in store.ancillary_revenues.values() if a["show_id"] == show["id"]]
    items = filter_eq(items, "kind", request.args.get("kind"))
    return list_response(items, ser_ancillary)
