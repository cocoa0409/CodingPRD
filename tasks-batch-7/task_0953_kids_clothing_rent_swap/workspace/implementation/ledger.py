"""The two ledgers, delinquency standing and its cascades (PRD 3.1 / 3.11)."""

import calc
import constants as K
import derive
import store
import timeutil


# ---------- charges ------------------------------------------------------

def new_charge(member, charge_type, amount_cents, cycle_id=None):
    charge = store.insert("charge_entries", {
        "member_id": member["id"],
        "cycle_id": cycle_id,
        "charge_type": charge_type,
        "amount_cents": amount_cents,
        "credit_applied_cents": 0,
        "net_due_cents": max(0, amount_cents),
        "status": "ASSESSED",
        "waive_reason": None,
    })
    refresh_standing(member)
    return charge


def recompute_charge(charge):
    charge["net_due_cents"] = max(0, charge["amount_cents"] - charge["credit_applied_cents"])
    if charge["status"] == "WAIVED":
        return charge
    if charge["net_due_cents"] == 0:
        charge["status"] = "SETTLED"
    elif charge["credit_applied_cents"] > 0:
        charge["status"] = "PARTIALLY_SETTLED"
    else:
        charge["status"] = "ASSESSED"
    return charge


def waive_charge(charge, member, reason):
    charge["status"] = "WAIVED"
    charge["waive_reason"] = reason
    charge["net_due_cents"] = 0
    store.touch(charge)
    refresh_standing(member)
    return charge


# ---------- credits ------------------------------------------------------

def credit_expires_at(entry):
    return timeutil.add_days(
        timeutil.add_days(entry["granted_at"], K.CREDIT_EXPIRY_DAYS),
        entry["paused_days_extension"],
    )


def new_credit(member, amount_cents, source_submission_id=None):
    granted_at = timeutil.now()
    entry = store.insert("credit_entries", {
        "member_id": member["id"],
        "source_submission_id": source_submission_id,
        "amount_cents": amount_cents,
        "remaining_cents": amount_cents,
        "status": "AVAILABLE",
        "granted_at": granted_at,
        "expires_at": timeutil.add_days(granted_at, K.CREDIT_EXPIRY_DAYS),
        "paused_days_extension": 0,
        "revoke_reason": None,
    })
    return entry


# ---------- the credit application waterfall -----------------------------

def _charge_sort_key(charge):
    try:
        bucket = K.CREDIT_APPLICATION_ORDER.index(charge["charge_type"])
    except ValueError:
        bucket = len(K.CREDIT_APPLICATION_ORDER)
    return (bucket, store.order_key(charge))


def apply_credit_waterfall(member, only_charge=None):
    """Charges in CREDIT_APPLICATION_ORDER, credits oldest-expiry-first.

    `only_charge` narrows the charge side to the single addressed entry: PRD 4
    describes `POST /kidswear/members/{member_id}/credit-applications` as
    "Apply banked credit to one open charge under the declared
    CREDIT_APPLICATION_ORDER waterfall", while trade-in finalisation "applies
    the new credit immediately to the member's open charges under the standing
    waterfall" (PRD 3.9) and therefore passes no narrowing.
    """
    clock = timeutil.now()
    if only_charge is not None:
        charges = [only_charge]
    else:
        charges = [c for c in derive.member_charges(member["id"])
                   if c["status"] in ("ASSESSED", "PARTIALLY_SETTLED")]
    charges.sort(key=_charge_sort_key)
    credits = [e for e in derive.member_credits(member["id"])
               if e["status"] in ("AVAILABLE", "PARTIALLY_APPLIED") and clock < e["expires_at"]]
    credits.sort(key=lambda e: (e["expires_at"], store.order_key(e)))

    touched_charges = set()
    touched_credits = set()
    for charge in charges:
        for entry in credits:
            if charge["net_due_cents"] <= 0:
                break
            if entry["remaining_cents"] <= 0:
                continue
            take = min(entry["remaining_cents"], charge["net_due_cents"])
            if take <= 0:
                continue
            entry["remaining_cents"] -= take
            charge["credit_applied_cents"] += take
            charge["net_due_cents"] = max(0, charge["amount_cents"] - charge["credit_applied_cents"])
            entry["status"] = "APPLIED" if entry["remaining_cents"] == 0 else "PARTIALLY_APPLIED"
            touched_charges.add(charge["id"])
            touched_credits.add(entry["id"])
        if charge["id"] in touched_charges:
            recompute_charge(charge)
    for charge in charges:
        if charge["id"] in touched_charges:
            store.touch(charge)
    for entry in credits:
        if entry["id"] in touched_credits:
            store.touch(entry)
    refresh_standing(member)


# ---------- delinquency standing and its cascade -------------------------

def refresh_standing(member):
    balance = derive.member_outstanding_balance(member["id"])
    if member["status"] == "ACTIVE" and balance >= K.DELINQUENCY_THRESHOLD_CENTS:
        _fall_delinquent(member)
    elif member["status"] == "DELINQUENT" and balance < K.DELINQUENCY_THRESHOLD_CENTS:
        _recover_active(member)


def _fall_delinquent(member):
    member["status"] = "DELINQUENT"
    for cycle in store.all_rows("cycles"):
        if cycle["member_id"] == member["id"] and cycle["status"] in ("OPEN", "SWAP_CLOSED"):
            cycle["status"] = "HELD"
            store.touch(cycle)
    for box in store.all_rows("boxes"):
        if box["member_id"] != member["id"]:
            continue
        for item in derive.box_items(box["id"]):
            if item["fulfillment_status"] == "ALLOCATED":
                cancel_box_item(item)
        if box["status"] == "DRAFT":
            box["status"] = "CANCELLED"
            store.touch(box)
    store.touch(member)


def _recover_active(member):
    member["status"] = "ACTIVE"
    clock = timeutil.now()
    for cycle in store.all_rows("cycles"):
        if cycle["member_id"] == member["id"] and cycle["status"] == "HELD":
            cycle["status"] = calc.cycle_status_from_clock(cycle, clock)
            store.touch(cycle)
    store.touch(member)


def cancel_box_item(item):
    """BoxItem ALLOCATED -> CANCELLED: the reserved unit goes back to stock."""
    item["fulfillment_status"] = "CANCELLED"
    item["settlement_status"] = "SETTLED"
    item["damage_fee_cents"] = 0
    store.touch(item)
    unit = store.get("units", item["unit_id"])
    if unit is not None and unit["state"] == "RESERVED":
        unit["state"] = "IN_STOCK"
        store.touch(unit)
