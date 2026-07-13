"""Lookups, state gates, cascades and compensating actions (PRD 2.8, 2.9, section 3)."""
from flask import g

import calc
import db
from errors import ApiError

# --- versioning -------------------------------------------------------------
def touch(obj):
    """Refresh updated_at and increment version by exactly 1 (PRD 2.4).

    A resource mutated by a single request — directly or as a cascade
    consequence — moves exactly one version, no matter how many hops of that
    request's cascade chain wrote to it.
    """
    seen = getattr(g, "touched", None)
    if seen is None:
        seen = set()
        g.touched = seen
    if obj["id"] in seen:
        return
    seen.add(obj["id"])
    obj["version"] += 1
    obj["updated_at"] = db.iso_now()


# --- existence (validation priorities 5 and 6) ------------------------------
_COLLECTIONS = {
    "client": (db.CLIENTS, "ERR_CLIENT_NOT_FOUND"),
    "rate_card": (db.RATE_CARDS, "ERR_RATE_CARD_NOT_FOUND"),
    "staff": (db.STAFF, "ERR_STAFF_MEMBER_NOT_FOUND"),
    "placement": (db.PLACEMENTS, "ERR_MEDIA_PLACEMENT_NOT_FOUND"),
    "retainer": (db.RETAINERS, "ERR_RETAINER_NOT_FOUND"),
    "sow": (db.SOWS, "ERR_SOW_NOT_FOUND"),
    "campaign": (db.CAMPAIGNS, "ERR_CAMPAIGN_NOT_FOUND"),
    "deliverable": (db.DELIVERABLES, "ERR_DELIVERABLE_NOT_FOUND"),
    "time_entry": (db.TIME_ENTRIES, "ERR_TIME_ENTRY_NOT_FOUND"),
    "vendor_cost": (db.VENDOR_COSTS, "ERR_VENDOR_COST_NOT_FOUND"),
    "media_plan": (db.MEDIA_PLANS, "ERR_MEDIA_PLAN_NOT_FOUND"),
    "insertion_order": (db.INSERTION_ORDERS, "ERR_INSERTION_ORDER_NOT_FOUND"),
    "invoice": (db.INVOICES, "ERR_INVOICE_NOT_FOUND"),
}


def must(kind, ident):
    store, err = _COLLECTIONS[kind]
    obj = store.get(ident) if isinstance(ident, str) else None
    if obj is None:
        raise ApiError(err)
    return obj


# --- ownership (validation priority 7) --------------------------------------
def must_own_client(client_id):
    if g.user_id != client_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


# --- cross-entity state gates (priorities 11 and 12) ------------------------
def campaign_gate(campaign):
    if campaign["status"] == "IN_FLIGHT":
        return
    if campaign["status"] == "ON_HOLD":
        raise ApiError("ERR_CAMPAIGN_ON_HOLD")
    raise ApiError("ERR_INVALID_STATE")


def sow_gate(sow):
    if sow["status"] == "COUNTERSIGNED":
        return
    if sow["status"] == "DRAFT":
        raise ApiError("ERR_SOW_NOT_COUNTERSIGNED")
    raise ApiError("ERR_SOW_EXPIRED")


# --- reverse lookups --------------------------------------------------------
def campaigns_of_client(client_id):
    return [c for c in db.ordered(db.CAMPAIGNS) if c["client_id"] == client_id]


def retainers_of_client(client_id):
    return [r for r in db.ordered(db.RETAINERS) if r["client_id"] == client_id]


def deliverables_of_campaign(campaign_id):
    return [d for d in db.ordered(db.DELIVERABLES) if d["campaign_id"] == campaign_id]


def plans_of_campaign(campaign_id):
    return [p for p in db.ordered(db.MEDIA_PLANS) if p["campaign_id"] == campaign_id]


def orders_of_plan(plan_id):
    return [o for o in db.ordered(db.INSERTION_ORDERS) if o["media_plan_id"] == plan_id]


def orders_of_campaign(campaign_id):
    plan_ids = {p["id"] for p in plans_of_campaign(campaign_id)}
    return [o for o in db.ordered(db.INSERTION_ORDERS) if o["media_plan_id"] in plan_ids]


def time_entries_of_campaign(campaign_id):
    return [t for t in db.ordered(db.TIME_ENTRIES) if t["campaign_id"] == campaign_id]


def vendor_costs_of_campaign(campaign_id):
    return [v for v in db.ordered(db.VENDOR_COSTS) if v["campaign_id"] == campaign_id]


# --- retainer / client / campaign cascade chain (PRD 3.1, 3.8) -------------
def retainer_status_recompute(retainer):
    """Retainer.status follows balance_cents mechanically, and drags the
    advertiser and its campaigns along with it."""
    client = db.CLIENTS.get(retainer["client_id"])
    if retainer["balance_cents"] == 0 and retainer["status"] == "ACTIVE":
        retainer["status"] = "DEPLETED"
        touch(retainer)
        if client is not None:
            client_hold(client)
    elif retainer["balance_cents"] > 0 and retainer["status"] == "DEPLETED":
        retainer["status"] = "ACTIVE"
        touch(retainer)
        if client is not None:
            client_release(client)


def client_hold(client):
    """Hop 3: any DEPLETED retainer puts the advertiser on credit hold.
    Hop 4: every IN_FLIGHT campaign of that advertiser freezes."""
    if client["status"] != "ACTIVE":
        return
    if not any(r["status"] == "DEPLETED" for r in retainers_of_client(client["id"])):
        return
    client["status"] = "CREDIT_HOLD"
    touch(client)
    for campaign in campaigns_of_client(client["id"]):
        if campaign["status"] == "IN_FLIGHT":
            campaign["status"] = "ON_HOLD"
            touch(campaign)


def client_release(client):
    """The exact inverse: only when EVERY retainer of the advertiser is ACTIVE."""
    if client["status"] != "CREDIT_HOLD":
        return
    retainers = retainers_of_client(client["id"])
    if not all(r["status"] == "ACTIVE" for r in retainers):
        return
    client["status"] = "ACTIVE"
    touch(client)
    for campaign in campaigns_of_client(client["id"]):
        if campaign["status"] == "ON_HOLD":
            campaign["status"] = "IN_FLIGHT"
            touch(campaign)


# --- creative wrap-up cascade (PRD 3.4) ------------------------------------
def wrap_up_cascade(campaign):
    """Hop 1: all deliverables APPROVED -> campaign WRAP_UP.
    Hop 2: that campaign's APPROVED media plans -> LOCKED.
    Hop 3: those plans' RESERVED orders -> CANCELLED, budget released.
    PLACED and DELIVERED orders are real publisher commitments and survive."""
    if campaign["status"] != "IN_FLIGHT":
        return
    deliverables = deliverables_of_campaign(campaign["id"])
    if not deliverables:
        return
    if not all(d["status"] == "APPROVED" for d in deliverables):
        return
    campaign["status"] = "WRAP_UP"
    touch(campaign)
    for plan in plans_of_campaign(campaign["id"]):
        if plan["status"] != "APPROVED":
            continue
        plan["status"] = "LOCKED"
        touch(plan)
        for order in orders_of_plan(plan["id"]):
            if order["status"] != "RESERVED":
                continue
            order["status"] = "CANCELLED"
            touch(order)
            plan["uncommitted_cents"] += order["gross_cents"]
            touch(plan)


def close_campaign_if_wrapped(campaign):
    if campaign is not None and campaign["status"] == "WRAP_UP":
        campaign["status"] = "CLOSED"
        touch(campaign)


# --- SOW labour ledger (PRD 3.5) -------------------------------------------
def recompute_sow_consumed_labor(sow):
    campaign_ids = {c["id"] for c in db.CAMPAIGNS.values() if c["sow_id"] == sow["id"]}
    total = sum(
        t["estimated_amount_cents"]
        for t in db.TIME_ENTRIES.values()
        if t["campaign_id"] in campaign_ids
        and t["status"] in ("SUBMITTED", "APPROVED", "BILLED")
    )
    if total != sow["consumed_labor_cents"]:
        sow["consumed_labor_cents"] = total
        touch(sow)


# --- invoice line assembly (PRD 3.8) ---------------------------------------
def assemble_invoice_lines(campaign, sow, billing_mode, period_start, period_end):
    """Returns (money dict, included ids). The period window is half-open."""
    if billing_mode == "PROVISIONAL":
        te_statuses = ("SUBMITTED", "APPROVED")
        vc_statuses = ("SUBMITTED", "APPROVED")
        io_statuses = ("RESERVED", "PLACED", "DELIVERED")
    else:
        te_statuses = ("APPROVED",)
        vc_statuses = ("APPROVED",)
        io_statuses = ("PLACED", "DELIVERED")

    tes = [
        t
        for t in time_entries_of_campaign(campaign["id"])
        if t["status"] in te_statuses and period_start <= t["_work_date"] < period_end
    ]
    vcs = [
        v
        for v in vendor_costs_of_campaign(campaign["id"])
        if v["status"] in vc_statuses and period_start <= v["_incurred_on"] < period_end
    ]
    ios = [
        o
        for o in orders_of_campaign(campaign["id"])
        if o["status"] in io_statuses and period_start <= o["_flight_start"] < period_end
    ]

    if billing_mode == "PROVISIONAL":
        labor = sum(t["estimated_amount_cents"] for t in tes)
        bases = [v["estimated_amount_cents"] for v in vcs]
    else:
        labor = sum(t["billable_amount_cents"] for t in tes)
        bases = [v["actual_amount_cents"] or 0 for v in vcs]

    vendor_base, vendor_marked_up = calc.markup_lines(bases, sow["markup_pct"])
    media_gross = sum(o["gross_cents"] for o in ios)
    commission = calc.media_commission(media_gross)
    line_count = len(tes) + len(vcs) + (1 if media_gross > 0 else 0)

    money = {
        "line_count": line_count,
        "labor_cents": labor,
        "vendor_base_cents": vendor_base,
        "vendor_marked_up_cents": vendor_marked_up,
        "media_gross_cents": media_gross,
        "media_commission_cents": commission,
    }
    money.update(calc.invoice_total(labor, vendor_marked_up, commission))
    ids = {
        "_time_entry_ids": [t["id"] for t in tes],
        "_vendor_cost_ids": [v["id"] for v in vcs],
        "_insertion_order_ids": [o["id"] for o in ios],
    }
    return money, ids
