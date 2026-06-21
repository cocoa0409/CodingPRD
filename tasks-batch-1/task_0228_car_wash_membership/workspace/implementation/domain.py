"""Domain model: entity construction, computed fields, serialization,
state transitions, and cascades (PRD Section 3).
"""
import calc
from db import store, iso_ms

# ---------------------------------------------------------------------------
# System-field stamping (PRD 2.4)
# ---------------------------------------------------------------------------


def _stamp_create(entity, versioned=True):
    now = store.now()
    entity["created_at"] = now
    # Stable insertion-order tiebreak for chronological sorting under a frozen
    # logical clock (PRD 2.3 list ordering, PRD 2.9 ledger ordering).
    entity["_seq"] = store.next_seq()
    if versioned:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version on a mutation/cascade (PRD 2.4)."""
    if "version" in entity:
        entity["updated_at"] = store.now()
        entity["version"] += 1


# ---------------------------------------------------------------------------
# Wallet ledger (PRD 2.9)
# ---------------------------------------------------------------------------


def wallet_balance(account_id):
    return sum(
        t["amount_cents"]
        for t in store.wallet_transactions.values()
        if t["account_id"] == account_id
    )


def write_wallet_txn(account_id, amount_cents, reason, related_invoice_id=None):
    """Append a wallet transaction and stamp balance_after_cents (PRD 2.9).

    Caller is responsible for the no-negative-balance pre-check where required.
    """
    txn = {
        "id": store.new_id(),
        "account_id": account_id,
        "amount_cents": amount_cents,
        "reason": reason,
        "related_invoice_id": related_invoice_id,
    }
    _stamp_create(txn, versioned=False)
    store.wallet_transactions[txn["id"]] = txn
    txn["balance_after_cents"] = wallet_balance(account_id)
    return txn


# ---------------------------------------------------------------------------
# Membership derived fields (PRD 2.5, 3.3)
# ---------------------------------------------------------------------------


def membership_credit_balance(m, plan):
    if plan["tier_type"] == "UNLIMITED":
        return 0
    return m.get("credits_granted", 0) - m.get("credits_consumed", 0)


def membership_freeze_count(membership_id):
    return sum(
        1
        for f in store.freezes.values()
        if f["membership_id"] == membership_id
        and f["status"] in ("SCHEDULED", "ACTIVE", "ENDED")
    )


# ---------------------------------------------------------------------------
# Account derived fields (PRD 2.10)
# ---------------------------------------------------------------------------


def active_vehicle_count(account_id):
    """Vehicles of this account whose membership is ACTIVE/FROZEN/PAST_DUE.

    Per the entity definition: count of Vehicle rows with this account_id whose
    membership has status IN {ACTIVE, FROZEN, PAST_DUE}.
    """
    count = 0
    for v in store.vehicles.values():
        if v["account_id"] != account_id:
            continue
        for m in store.memberships.values():
            if m["vehicle_id"] == v["id"] and m["status"] in ("ACTIVE", "FROZEN", "PAST_DUE"):
                count += 1
                break
    return count


def account_fleet_discount_pct(account):
    return calc.fleet_discount_pct(account["account_type"], active_vehicle_count(account["id"]))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_account(a):
    return {
        "id": a["id"],
        "account_type": a["account_type"],
        "company_name": a.get("company_name"),
        "contact_email": a.get("contact_email"),
        "status": a["status"],
        "wallet_balance_cents": wallet_balance(a["id"]),
        "active_vehicle_count": active_vehicle_count(a["id"]),
        "fleet_discount_pct": float(account_fleet_discount_pct(a)),
        "created_at": iso_ms(a["created_at"]),
        "updated_at": iso_ms(a["updated_at"]),
        "version": a["version"],
    }


def serialize_plan(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "tier_type": p["tier_type"],
        "monthly_fee_cents": p["monthly_fee_cents"],
        "included_credits": p["included_credits"],
        "per_credit_price_cents": p["per_credit_price_cents"],
        "wash_cooldown_hours": p["wash_cooldown_hours"],
        "max_addons": p["max_addons"],
        "status": p["status"],
        "created_at": iso_ms(p["created_at"]),
        "updated_at": iso_ms(p["updated_at"]),
        "version": p["version"],
    }


def serialize_location(loc):
    return {
        "id": loc["id"],
        "name": loc["name"],
        "state_code": loc["state_code"],
        "in_network": loc["in_network"],
        "daily_wash_capacity": loc["daily_wash_capacity"],
        "status": loc["status"],
        "created_at": iso_ms(loc["created_at"]),
        "updated_at": iso_ms(loc["updated_at"]),
        "version": loc["version"],
    }


def serialize_addon(ad):
    return {
        "id": ad["id"],
        "name": ad["name"],
        "recurring_fee_cents": ad["recurring_fee_cents"],
        "status": ad["status"],
        "created_at": iso_ms(ad["created_at"]),
        "updated_at": iso_ms(ad["updated_at"]),
        "version": ad["version"],
    }


def serialize_vehicle(v):
    return {
        "id": v["id"],
        "account_id": v["account_id"],
        "license_plate": v["license_plate"],
        "state_code": v["state_code"],
        "status": v["status"],
        "created_at": iso_ms(v["created_at"]),
        "updated_at": iso_ms(v["updated_at"]),
        "version": v["version"],
    }


def serialize_membership(m):
    plan = store.plans[m["plan_id"]]
    return {
        "id": m["id"],
        "account_id": m["account_id"],
        "vehicle_id": m["vehicle_id"],
        "plan_id": m["plan_id"],
        "status": m["status"],
        "cycle_anchor_utc": iso_ms(m.get("cycle_anchor_utc")),
        "current_cycle_paid_cents": m.get("current_cycle_paid_cents", 0),
        "credit_balance": membership_credit_balance(m, plan),
        "credits_granted": m.get("credits_granted", 0),
        "credits_consumed": m.get("credits_consumed", 0),
        "last_admitted_wash_utc": iso_ms(m.get("last_admitted_wash_utc")),
        "freeze_count": membership_freeze_count(m["id"]),
        "created_at": iso_ms(m["created_at"]),
        "updated_at": iso_ms(m["updated_at"]),
        "version": m["version"],
    }


def serialize_membership_addon(ma):
    return {
        "id": ma["id"],
        "membership_id": ma["membership_id"],
        "addon_id": ma["addon_id"],
        "status": ma["status"],
        "locked_fee_cents": ma["locked_fee_cents"],
        "created_at": iso_ms(ma["created_at"]),
        "updated_at": iso_ms(ma["updated_at"]),
        "version": ma["version"],
    }


def serialize_invoice(inv):
    return {
        "id": inv["id"],
        "account_id": inv["account_id"],
        "membership_id": inv["membership_id"],
        "status": inv["status"],
        "kind": inv["kind"],
        "base_fee_cents": inv["base_fee_cents"],
        "addon_fee_cents": inv["addon_fee_cents"],
        "discount_cents": inv["discount_cents"],
        "total_cents": inv["total_cents"],
        "attempt_count": inv["attempt_count"],
        "created_at": iso_ms(inv["created_at"]),
        "updated_at": iso_ms(inv["updated_at"]),
        "version": inv["version"],
    }


def serialize_wash_event(w):
    return {
        "id": w["id"],
        "membership_id": w.get("membership_id"),
        "vehicle_id": w.get("vehicle_id"),
        "location_id": w["location_id"],
        "license_plate": w["license_plate"],
        "state_code": w["state_code"],
        "status": w["status"],
        "rejection_error_id": w.get("rejection_error_id"),
        "consumed_credit": w.get("consumed_credit", False),
        "admitted_at_utc": iso_ms(w.get("admitted_at_utc")),
        "created_at": iso_ms(w["created_at"]),
    }


def serialize_wallet_txn(t):
    return {
        "id": t["id"],
        "account_id": t["account_id"],
        "amount_cents": t["amount_cents"],
        "reason": t["reason"],
        "related_invoice_id": t.get("related_invoice_id"),
        "balance_after_cents": t["balance_after_cents"],
        "created_at": iso_ms(t["created_at"]),
    }


def serialize_freeze(f):
    return {
        "id": f["id"],
        "membership_id": f["membership_id"],
        "start_utc": iso_ms(f["start_utc"]),
        "end_utc": iso_ms(f["end_utc"]),
        "status": f["status"],
        "refund_cents": f["refund_cents"],
        "created_at": iso_ms(f["created_at"]),
        "updated_at": iso_ms(f["updated_at"]),
        "version": f["version"],
    }


# ---------------------------------------------------------------------------
# Cascade helpers (PRD 3.8, 3.10)
# ---------------------------------------------------------------------------


def membership_active_addons(membership_id, statuses):
    return [
        ma
        for ma in store.membership_addons.values()
        if ma["membership_id"] == membership_id and ma["status"] in statuses
    ]


def freeze_membership(m, create_freeze_row=True):
    """Drive a membership into FROZEN: refund + pause add-ons (PRD 3.8).

    Returns the credited refund amount. Used by direct freeze, scheduled-freeze
    activation, and account-suspend cascade.
    """
    plan = store.plans[m["plan_id"]]
    rem = calc.remaining_days(m["cycle_anchor_utc"], store.now()) if m.get("cycle_anchor_utc") else 0
    refund = calc.freeze_refund_cents(m.get("current_cycle_paid_cents", 0), rem)
    if refund > 0:
        write_wallet_txn(m["account_id"], refund, "FREEZE_REFUND")
    # Pause every currently ACTIVE add-on.
    for ma in membership_active_addons(m["id"], ("ACTIVE",)):
        ma["status"] = "PAUSED"
        touch(ma)
    m["status"] = "FROZEN"
    touch(m)
    if create_freeze_row:
        now = store.now()
        freeze = {
            "id": store.new_id(),
            "membership_id": m["id"],
            "start_utc": now,
            "end_utc": None,
            "status": "ACTIVE",
            "refund_cents": refund,
        }
        _stamp_create(freeze)
        store.freezes[freeze["id"]] = freeze
    return refund


def detach_addons_on_cancel(membership_id):
    for ma in membership_active_addons(membership_id, ("ACTIVE", "PAUSED")):
        ma["status"] = "DETACHED"
        touch(ma)
