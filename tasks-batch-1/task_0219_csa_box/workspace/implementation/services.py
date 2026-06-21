"""Core business services: ledger, balances, derived counters, box dates,
fulfillment bubble-up, and clock-driven system transitions.

Each helper traces to a PRD §3 workflow (cited inline).
"""
from datetime import timedelta

import db
import calc
from models import stamp_new, touch, parse_iso

NON_TERMINAL_BOX_STATES = {"SCHEDULED", "HELD", "PACKED"}
TERMINAL_BOX_STATES = {"DELIVERED", "SKIPPED"}


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------
def post_ledger(subscription_id, entry_type, amount_cents, memo=""):
    """Append an immutable LedgerEntry (PRD §3.4). Append-only: id + created_at
    only, no updated_at/version (PRD §2.4)."""
    rec = {
        "subscription_id": subscription_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "memo": memo if memo is not None else "",
    }
    stamp_new(rec, with_version=False)
    db.ledger_entries[rec["id"]] = rec
    return rec


def ledger_for(subscription_id):
    return [e for e in db.ledger_entries.values()
            if e["subscription_id"] == subscription_id]


# --------------------------------------------------------------------------
# Outstanding balance (PRD §3.4 / §1.3 outstanding_balance)
# --------------------------------------------------------------------------
def recompute_balance(sub):
    """Recompute outstanding_balance_cents from the subscription's full ledger
    and the owning member's wallet credit. Fixed evaluation order (PRD §3.4)."""
    entries = ledger_for(sub["id"])
    member = db.members.get(sub["member_id"])
    wallet = member["wallet_credit_cents"] if member else 0

    gross_charges = sum(
        e["amount_cents"] for e in entries
        if e["entry_type"] in ("CHARGE_SEASON", "CHARGE_ADDON", "CHARGE_SURCHARGE")
    )
    non_wallet_credits = -sum(
        e["amount_cents"] for e in entries
        if e["entry_type"] == "CREDIT_HOLD_REFUND"
    )
    net_after_refunds = gross_charges - non_wallet_credits
    wallet_applied = min(wallet, max(net_after_refunds, 0))
    payments = -sum(
        e["amount_cents"] for e in entries if e["entry_type"] == "PAYMENT"
    )
    sub["outstanding_balance_cents"] = max(
        net_after_refunds - wallet_applied - payments, 0
    )
    touch(sub)


# --------------------------------------------------------------------------
# Derived counters (PRD §2.8) — recomputed, never set directly
# --------------------------------------------------------------------------
def recompute_season_confirmed_count(season):
    """Season.confirmed_share_count = count of Subscriptions for this season
    whose billing_status IN {CONFIRMED, ACTIVE} (§1.1)."""
    count = sum(
        1 for s in db.subscriptions.values()
        if s["season_id"] == season["id"]
        and s["billing_status"] in ("CONFIRMED", "ACTIVE")
    )
    season["confirmed_share_count"] = count
    touch(season)


def recompute_site_active_count(site):
    """PickupSite.active_subscription_count = count of Subscriptions whose
    current_site_id == this site and billing_status IN {CONFIRMED, ACTIVE}."""
    count = sum(
        1 for s in db.subscriptions.values()
        if s["current_site_id"] == site["id"]
        and s["billing_status"] in ("CONFIRMED", "ACTIVE")
    )
    site["active_subscription_count"] = count
    touch(site)


def recompute_addon_committed_count(add_on):
    """AddOn.committed_count = count of SubscriptionAddOn rows with status
    ATTACHED referencing this add-on (§1.1)."""
    count = sum(
        1 for sa in db.subscription_add_ons.values()
        if sa["add_on_id"] == add_on["id"] and sa["status"] == "ATTACHED"
    )
    add_on["committed_count"] = count
    touch(add_on)


# --------------------------------------------------------------------------
# Weekly box delivery date (PRD §3.7)
# --------------------------------------------------------------------------
def box_delivery_date(season, week_index):
    """first_delivery_date + 7 days × (week_index - 1)."""
    base = parse_iso(season["first_delivery_date"])
    if base is None:
        return None
    return base + timedelta(days=7 * (week_index - 1))


def boxes_for(subscription_id):
    return [b for b in db.weekly_boxes.values()
            if b["subscription_id"] == subscription_id]


# --------------------------------------------------------------------------
# Fulfillment bubble-up (PRD §3.6)
# --------------------------------------------------------------------------
def maybe_complete_fulfillment(sub):
    """If every WeeklyBox of the subscription is terminal, advance
    fulfillment_status IN_SEASON→COMPLETED (bubble-up). No ledger change."""
    boxes = boxes_for(sub["id"])
    if not boxes:
        return
    non_terminal = [b for b in boxes if b["status"] not in TERMINAL_BOX_STATES]
    if len(non_terminal) == 0 and sub["fulfillment_status"] == "IN_SEASON":
        sub["fulfillment_status"] = "COMPLETED"
        touch(sub)


# --------------------------------------------------------------------------
# Clock-driven system transitions (PRD §3.11)
# --------------------------------------------------------------------------
def run_clock_transitions():
    """Fire every clock-driven transition that the current clock makes due:
      - HELD box past its delivery date (hold still ACTIVE) -> SKIPPED, hold CONSUMED
      - OFFERED waitlist entry past offer_expires_at -> EXPIRED
    """
    now = db.get_clock()

    # HELD boxes past delivery date -> SKIPPED, hold -> CONSUMED
    for box in list(db.weekly_boxes.values()):
        if box["status"] != "HELD":
            continue
        sub = db.subscriptions.get(box["subscription_id"])
        if sub is None:
            continue
        season = db.seasons.get(sub["season_id"])
        if season is None:
            continue
        deliver_dt = box_delivery_date(season, box["week_index"])
        if deliver_dt is None:
            continue
        if now >= deliver_dt:
            # find the ACTIVE hold covering this box
            hold = next(
                (h for h in db.vacation_holds.values()
                 if h["held_box_id"] == box["id"] and h["status"] == "ACTIVE"),
                None,
            )
            box["status"] = "SKIPPED"
            box["item_count"] = 0
            touch(box)
            if hold is not None:
                hold["status"] = "CONSUMED"
                touch(hold)
            # bubble-up fulfillment completion
            maybe_complete_fulfillment(sub)

    # OFFERED waitlist entries past offer_expires_at -> EXPIRED
    for entry in list(db.waitlist_entries.values()):
        if entry["status"] != "OFFERED":
            continue
        exp = parse_iso(entry["offer_expires_at"])
        if exp is None:
            continue
        if now > exp:
            entry["status"] = "EXPIRED"
            touch(entry)
