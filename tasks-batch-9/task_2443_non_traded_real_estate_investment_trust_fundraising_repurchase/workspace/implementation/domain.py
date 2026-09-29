"""Store-aware domain helpers: derived figures, pricing and cascades.

PRD §2.10 — "Derived figures are never stale ... recomputed synchronously
within the request that disturbs them", and every cascade refreshes the
touched row's updated_at and increments its version exactly as a direct write
would.
"""

import calc
from store import DB, all_rows, by_created, logical_now, sort_key, touch

# --------------------------------------------------------------------------
# Collection helpers
# --------------------------------------------------------------------------

def classes_of(offering_id):
    return by_created([c for c in DB["share_classes"].values()
                       if c["offering_id"] == offering_id])


def subscriptions_of_offering(offering_id):
    return by_created([s for s in DB["subscriptions"].values()
                       if s["offering_id"] == offering_id])


def agreements_of_firm(broker_dealer_id):
    return by_created([a for a in DB["selling_agreements"].values()
                       if a["broker_dealer_id"] == broker_dealer_id])


def periods_of(offering_id):
    return by_created([p for p in DB["repurchase_periods"].values()
                       if p["offering_id"] == offering_id])


def requests_of_period(period_id):
    return by_created([r for r in DB["repurchase_requests"].values()
                       if r["repurchase_period_id"] == period_id])


def open_lots_of(investor_id, share_class_id=None):
    lots = [l for l in DB["share_lots"].values()
            if l["investor_id"] == investor_id and l["status"] == "OPEN"
            and (share_class_id is None or l["share_class_id"] == share_class_id)]
    return by_created(lots)


def lots_fifo(lots):
    """Ascending issued_date, ascending created_at breaking a tie."""
    return sorted(lots, key=lambda l: (l["_issued_at"], l["created_at"], l["_seq"]))


def offering_of_class(cls):
    return DB["offerings"].get(cls["offering_id"])


def set_field(row, name, value):
    if row.get(name) != value:
        row[name] = value
        touch(row)


# --------------------------------------------------------------------------
# Pricing — calculations.transaction_price_selection
# --------------------------------------------------------------------------

def published_records_of(share_class_id):
    return [r for r in DB["nav_records"].values()
            if r["share_class_id"] == share_class_id and r["status"] == "PUBLISHED"]


def latest_published(share_class_id):
    """Greatest period_end_date wins; the earliest created record breaks a tie."""
    best = None
    for record in published_records_of(share_class_id):
        if best is None:
            best = record
            continue
        if record["period_end_date"] > best["period_end_date"]:
            best = record
        elif record["period_end_date"] == best["period_end_date"]:
            if sort_key(record) < sort_key(best):
                best = record
    return best


def transaction_price_cents(cls):
    record = latest_published(cls["id"])
    if record is not None:
        return record["nav_per_share_cents"]
    offering = offering_of_class(cls)
    return offering["initial_offering_price_cents"] if offering else 0


def transaction_price_of_class_id(share_class_id):
    cls = DB["share_classes"].get(share_class_id)
    return transaction_price_cents(cls) if cls else 0


# --------------------------------------------------------------------------
# Derived figures
# --------------------------------------------------------------------------

def sync_derived():
    """Recompute every stored derived aggregate.  Share classes are refreshed
    before offerings because aggregate_nav_cents reads shares_outstanding_e4."""
    lots = list(DB["share_lots"].values())
    subs = list(DB["subscriptions"].values())

    for cls in DB["share_classes"].values():
        total = sum(l["remaining_shares_e4"] for l in lots
                    if l["share_class_id"] == cls["id"] and l["status"] == "OPEN")
        set_field(cls, "shares_outstanding_e4", total)

    for investor in DB["investors"].values():
        held = sum(l["remaining_shares_e4"] for l in lots
                   if l["investor_id"] == investor["id"] and l["status"] == "OPEN")
        set_field(investor, "total_shares_e4", held)
        invested = sum(s["gross_investment_cents"] for s in subs
                       if s["investor_id"] == investor["id"] and s["status"] == "ACCEPTED")
        set_field(investor, "cumulative_invested_cents", invested)
        set_field(investor, "concentration_limit_cents", calc.concentration_limit_cents(
            investor["state_code"], investor["net_worth_cents"],
            investor["annual_income_cents"]))

    for offering in DB["offerings"].values():
        escrowed = sum(s["gross_investment_cents"] for s in subs
                       if s["offering_id"] == offering["id"] and s["status"] == "ESCROWED")
        set_field(offering, "escrow_balance_cents", escrowed)
        accepted = sum(s["gross_investment_cents"] for s in subs
                       if s["offering_id"] == offering["id"] and s["status"] == "ACCEPTED")
        set_field(offering, "gross_proceeds_cents", accepted)
        set_field(offering, "aggregate_nav_cents", aggregate_nav_cents(offering))

    for firm in DB["broker_dealers"].values():
        suspended = sum(1 for a in DB["selling_agreements"].values()
                        if a["broker_dealer_id"] == firm["id"] and a["status"] == "SUSPENDED")
        set_field(firm, "suspended_agreement_count", suspended)


def aggregate_nav_cents(offering):
    """PRD §3.6 — each class's contribution rounded half up on its own, then
    summed."""
    total = 0
    for cls in classes_of(offering["id"]):
        price = transaction_price_cents(cls)
        total += calc.class_nav_contribution_cents(price, cls["shares_outstanding_e4"])
    return total


# --------------------------------------------------------------------------
# Investor status re-evaluation
# --------------------------------------------------------------------------

def reevaluate_suitability(investor):
    """PRD §3.2 — DOCUMENTED becomes FLAGGED once cumulative_invested_cents
    exceeds concentration_limit_cents; a FLAGGED account returns to DOCUMENTED
    once the limit is respected again."""
    if investor is None:
        return
    over = investor["cumulative_invested_cents"] > investor["concentration_limit_cents"]
    if investor["suitability_status"] == "DOCUMENTED" and over:
        set_field(investor, "suitability_status", "FLAGGED")
    elif investor["suitability_status"] == "FLAGGED" and not over:
        set_field(investor, "suitability_status", "DOCUMENTED")


def note_lot_minted(investor):
    """account_status returns to ACTIVE the moment a new lot is minted."""
    if investor is not None and investor["account_status"] == "CLOSED_NO_POSITION":
        set_field(investor, "account_status", "ACTIVE")


def note_position_possibly_closed(investor):
    """account_status becomes CLOSED_NO_POSITION when the holder is left with
    no OPEN lot at all."""
    if investor is None:
        return
    if not open_lots_of(investor["id"]):
        set_field(investor, "account_status", "CLOSED_NO_POSITION")


# --------------------------------------------------------------------------
# Share-lot minting
# --------------------------------------------------------------------------

def mint_lot(subscription, cls):
    """PRD §3.5 — one lot per accepted subscription."""
    from store import fmt_instant, new_row

    now = logical_now()
    cap = calc.floor_div(subscription["gross_investment_cents"] * cls["distribution_fee_cap_bps"],
                         calc.BPS_SCALE)
    lot = new_row("share_lots", {
        "subscription_id": subscription["id"],
        "investor_id": subscription["investor_id"],
        "share_class_id": cls["id"],
        "converted_from_share_class_id": None,
        "issued_date": fmt_instant(now),
        "_issued_at": now,
        "original_shares_e4": subscription["shares_issued_e4"],
        "remaining_shares_e4": subscription["shares_issued_e4"],
        "gross_offering_price_cents": subscription["gross_investment_cents"],
        "cumulative_distribution_fee_cents": 0,
        "distribution_fee_cap_cents": cap,
        "status": "OPEN",
    })
    return lot


def lots_of_subscription(subscription_id):
    return by_created([l for l in DB["share_lots"].values()
                       if l["subscription_id"] == subscription_id])


# --------------------------------------------------------------------------
# Selling-agreement / broker-dealer cascades
# --------------------------------------------------------------------------

def escalate_firm_on_suspension(firm):
    """An agreement suspension escalates an IN_GOOD_STANDING firm."""
    if firm is not None and firm["supervision_status"] == "IN_GOOD_STANDING":
        set_field(firm, "supervision_status", "HEIGHTENED_SUPERVISION")


def reject_pending_subscriptions(agreement, reason):
    for sub in subscriptions_of_agreement(agreement["id"]):
        if sub["status"] == "PENDING":
            sub["status"] = "REJECTED"
            sub["rejection_reason"] = reason
            touch(sub)


def subscriptions_of_agreement(agreement_id):
    return by_created([s for s in DB["subscriptions"].values()
                       if s["selling_agreement_id"] == agreement_id])


# --------------------------------------------------------------------------
# Repurchase-plan cascades — PRD §3.8
# --------------------------------------------------------------------------

def suspend_plan(offering, reason):
    set_field(offering, "repurchase_plan_status", "SUSPENDED")
    offering["repurchase_plan_suspension_reason"] = reason
    touch(offering)
    for period in periods_of(offering["id"]):
        if period["status"] == "OPEN":
            period["status"] = "SUSPENDED"
            touch(period)
            for req in requests_of_period(period["id"]):
                if req["status"] == "QUEUED":
                    req["status"] = "HELD"
                    touch(req)


def resume_plan(offering):
    offering["repurchase_plan_status"] = "ACTIVE"
    offering["repurchase_plan_suspension_reason"] = None
    touch(offering)
    for period in periods_of(offering["id"]):
        if period["status"] == "SUSPENDED":
            period["status"] = "OPEN"
            touch(period)
            for req in requests_of_period(period["id"]):
                if req["status"] == "HELD":
                    req["status"] = "QUEUED"
                    touch(req)


def terminate_plan(offering):
    offering["repurchase_plan_status"] = "TERMINATED"
    touch(offering)
    for period in periods_of(offering["id"]):
        if period["status"] in ("OPEN", "SUSPENDED"):
            period["status"] = "CANCELLED"
            touch(period)
            for req in requests_of_period(period["id"]):
                if req["status"] in ("QUEUED", "HELD"):
                    req["status"] = "REJECTED"
                    touch(req)


def close_active_classes(offering):
    for cls in classes_of(offering["id"]):
        if cls["status"] == "ACTIVE":
            cls["status"] = "CLOSED_TO_NEW"
            touch(cls)


# --------------------------------------------------------------------------
# Declarations
# --------------------------------------------------------------------------

def declarations_of(offering_id):
    return by_created([d for d in DB["distribution_declarations"].values()
                       if d["offering_id"] == offering_id])


def accrued_distribution_payable_cents(offering_id, period_end_date):
    """Sum of total_declared_cents across DECLARED declarations of the class's
    offering whose record_date falls on or before this period's end."""
    total = 0
    for decl in declarations_of(offering_id):
        if decl["status"] == "DECLARED" and decl["record_date"] <= period_end_date:
            total += decl["total_declared_cents"]
    return total


def nav_records_of(share_class_id):
    return by_created([r for r in DB["nav_records"].values()
                       if r["share_class_id"] == share_class_id])


def votes_of_event(liquidity_event_id):
    return by_created([v for v in DB["stockholder_votes"].values()
                       if v["liquidity_event_id"] == liquidity_event_id])


def all_of(collection):
    return all_rows(collection)
