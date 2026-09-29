"""Conserved ledgers, the axis couplings and the restricted-party cascade."""
from decimal import Decimal

import calc
from core import ApiError, dq
from db import ordered, store, touch

D = Decimal
LIVE_BOOKINGS = ("BOOKED", "CONFIRMED", "SHIPPED")
LICENSE_CHARGING_STATES = ("BOOKED", "SHIPPED", "SHORT_SHIPPED", "CLOSED")
LIVE_DISPUTES = ("OPEN", "OFFERED", "COUNTERED", "ESCALATED")
TERMINAL_SETTLEMENT = ("PAID", "INDEMNIFIED", "WRITTEN_OFF")


def order_state_invalid():
    raise ApiError("ERR_ORDER_STATE_INVALID", 409,
                   "the order is not in a state the transition is declared from")


def require_fulfillment(order, allowed):
    if order["fulfillment_status"] not in allowed:
        order_state_invalid()


def require_settlement(order, allowed):
    if order["settlement_status"] not in allowed:
        order_state_invalid()


# =========================================================================
# buyer aggregates
# =========================================================================
def recompute_open_order_count(buyer, bump=True):
    count = sum(1 for o in store.orders.values()
                if o["buyer_id"] == buyer["id"]
                and o["fulfillment_status"] not in ("CLOSED", "CANCELLED"))
    changed = buyer["open_order_count"] != count
    buyer["open_order_count"] = count
    if bump and changed:
        touch(buyer)
    return count


def recompute_buyer_exposure(buyer, bump=True):
    total = D("0.00")
    for policy in store.policies.values():
        if policy["buyer_id"] == buyer["id"] and policy["status"] in ("ACTIVE", "EXHAUSTED"):
            total += policy["utilized_usd"]
    total = dq(total, 2)
    changed = buyer["aggregate_exposure_usd"] != total
    buyer["aggregate_exposure_usd"] = total
    if bump and changed:
        touch(buyer)
    return total


# =========================================================================
# sailing capacity ledger
# =========================================================================
def recompute_sailing(sailing, bump=True):
    before = (sailing["booked_weight_kg"], sailing["status"])
    total = D("0.000")
    for booking in store.bookings.values():
        if booking["vessel_sailing_id"] == sailing["id"] and booking["status"] in LIVE_BOOKINGS:
            total += booking["booked_weight_kg"]
    sailing["booked_weight_kg"] = dq(total, 3)
    if sailing["status"] == "OPEN" and sailing["booked_weight_kg"] >= sailing["capacity_weight_kg"]:
        sailing["status"] = "FULL"
    elif sailing["status"] == "FULL" and sailing["booked_weight_kg"] < sailing["capacity_weight_kg"] \
            and store.clock < sailing["_cutoff_dt"]:
        sailing["status"] = "OPEN"
    if bump and before != (sailing["booked_weight_kg"], sailing["status"]):
        touch(sailing)


# =========================================================================
# export license ledger
# =========================================================================
def license_for_order(order):
    screening = screening_for_order(order["id"])
    if screening is None or not screening.get("export_license_id"):
        return None
    return store.licenses.get(screening["export_license_id"])


def screening_for_order(order_id):
    rows = [s for s in ordered(store.screenings) if s["export_order_id"] == order_id]
    return rows[-1] if rows else None


def recompute_license(license_row, bump=True):
    before = (license_row["consumed_value_usd"], license_row["remaining_value_usd"],
              license_row["status"])
    total = D("0.00")
    for screening in store.screenings.values():
        if screening.get("export_license_id") != license_row["id"]:
            continue
        order = store.orders.get(screening["export_order_id"])
        if order is None:
            continue
        if order["fulfillment_status"] in LICENSE_CHARGING_STATES:
            total += order["licensed_value_allocated_usd"]
    license_row["consumed_value_usd"] = dq(total, 2)
    remaining = dq(license_row["licensed_value_usd"] - license_row["consumed_value_usd"], 2)
    if remaining < 0:
        remaining = D("0.00")
    license_row["remaining_value_usd"] = remaining
    if license_row["status"] in ("ACTIVE", "EXHAUSTED"):
        license_row["status"] = "EXHAUSTED" if remaining == 0 else "ACTIVE"
    elif license_row["status"] == "ISSUED" and remaining == 0:
        license_row["status"] = "EXHAUSTED"
    after = (license_row["consumed_value_usd"], license_row["remaining_value_usd"],
             license_row["status"])
    if bump and before != after:
        touch(license_row)


# =========================================================================
# insurance exposure ledger
# =========================================================================
def recompute_policy(policy, bump=True):
    before = (policy["utilized_usd"], policy["available_limit_usd"], policy["status"])
    total = D("0.00")
    for order in store.orders.values():
        if order.get("_charged_policy_id") == policy["id"]:
            total += order["insured_exposure_usd"]
    policy["utilized_usd"] = dq(total, 2)
    available = dq(policy["credit_limit_usd"] - policy["utilized_usd"], 2)
    if available < 0:
        available = D("0.00")
    policy["available_limit_usd"] = available
    if policy["status"] in ("ACTIVE", "EXHAUSTED"):
        policy["status"] = "EXHAUSTED" if available == 0 else "ACTIVE"
    after = (policy["utilized_usd"], policy["available_limit_usd"], policy["status"])
    if bump and before != after:
        touch(policy)


def charge_exposure(order):
    """PRD 3.8: charge the best candidate policy, or proceed uninsured."""
    required = dq(order["ordered_goods_value_usd"], 2)
    if required <= 0:
        return None
    candidates = []
    for policy in ordered(store.policies):
        if policy["buyer_id"] != order["buyer_id"]:
            continue
        if policy["status"] != "ACTIVE":
            continue
        if not (policy["_from_dt"] <= store.clock <= policy["_to_dt"]):
            continue
        if policy["available_limit_usd"] < required:
            continue
        candidates.append(policy)
    if not candidates:
        order["insured_exposure_usd"] = D("0.00")
        order["_charged_policy_id"] = None
        return None
    candidates.sort(key=lambda p: (-p["available_limit_usd"], p["created_at"], p["_seq"]))
    chosen = candidates[0]
    order["insured_exposure_usd"] = required
    order["_charged_policy_id"] = chosen["id"]
    recompute_policy(chosen)
    buyer = store.buyers.get(order["buyer_id"])
    if buyer is not None:
        recompute_buyer_exposure(buyer)
    return chosen


def release_exposure(order):
    policy_id = order.get("_charged_policy_id")
    order["insured_exposure_usd"] = D("0.00")
    order["_charged_policy_id"] = None
    if not policy_id:
        return None
    policy = store.policies.get(policy_id)
    if policy is None:
        return None
    recompute_policy(policy)
    buyer = store.buyers.get(order["buyer_id"])
    if buyer is not None:
        recompute_buyer_exposure(buyer)
    return policy


# =========================================================================
# receivable and close coupling
# =========================================================================
def recompute_outstanding_receivable(order):
    invoice = None
    for document in ordered(store.documents):
        if document["export_order_id"] == order["id"] \
                and document["doc_type"] == "COMMERCIAL_INVOICE" \
                and document["status"] == "ISSUED":
            invoice = document
    if invoice is None:
        order["outstanding_receivable_usd"] = D("0.00")
        return
    received = D("0.00")
    for presentation in store.presentations.values():
        if presentation["export_order_id"] == order["id"] \
                and presentation["status"] == "HONOURED" \
                and presentation["received_amount_usd"] is not None:
            received += presentation["received_amount_usd"]
    order["outstanding_receivable_usd"] = dq(invoice["declared_total_usd"] - received, 2)


def presentations_of_order(order_id):
    return [p for p in ordered(store.presentations)
            if p["export_order_id"] == order_id]


def has_complying_presentation(order_id):
    """True when the order holds a presentation in COMPLIED or HONOURED."""
    return any(p["status"] in ("COMPLIED", "HONOURED")
               for p in store.presentations.values()
               if p["export_order_id"] == order_id)


def has_live_dispute(order_id):
    return any(d["export_order_id"] == order_id and d["status"] in LIVE_DISPUTES
               for d in store.disputes.values())


def auto_close(order):
    """PRD 2.10: the money axis pulls the goods axis to CLOSED."""
    if order["settlement_status"] not in TERMINAL_SETTLEMENT:
        return False
    state = order["fulfillment_status"]
    if state == "SHIPPED":
        pass
    elif state == "SHORT_SHIPPED":
        if has_live_dispute(order["id"]):
            return False
    else:
        return False
    order["fulfillment_status"] = "CLOSED"
    buyer = store.buyers.get(order["buyer_id"])
    if buyer is not None:
        recompute_open_order_count(buyer)
    license_row = license_for_order(order)
    if license_row is not None:
        recompute_license(license_row)
    return True


# =========================================================================
# the four-link restricted-party cascade (PRD 3.1)
# =========================================================================
def restricted_party_cascade(buyer):
    orders = [o for o in ordered(store.orders) if o["buyer_id"] == buyer["id"]]
    touched_sailings = {}
    touched_licenses = {}
    for order in orders:
        state = order["fulfillment_status"]
        if state not in ("COMPLIANCE_CLEARED", "BOOKED"):
            continue
        was_booked = state == "BOOKED"
        order["fulfillment_status"] = "COMPLIANCE_BLOCKED"

        for booking in ordered(store.bookings):
            if booking["export_order_id"] != order["id"]:
                continue
            if booking["status"] not in ("BOOKED", "CONFIRMED"):
                continue
            booking["status"] = "CANCELLED"
            booking["cancel_reason"] = "RESTRICTED_PARTY_CASCADE"
            touch(booking)
            sailing = store.sailings.get(booking["vessel_sailing_id"])
            if sailing is not None:
                touched_sailings[sailing["id"]] = sailing

        if was_booked:
            license_row = license_for_order(order)
            order["licensed_value_allocated_usd"] = D("0.00")
            if license_row is not None:
                touched_licenses[license_row["id"]] = license_row

        touch(order)

        screening = screening_for_order(order["id"])
        if screening is not None and screening["status"] == "CLEARED":
            screening["status"] = "INITIATED"
            screening["ruleset_version"] = screening["ruleset_version"] + 1
            screening["cleared_at"] = None
            touch(screening)

    for sailing in touched_sailings.values():
        recompute_sailing(sailing)
    for license_row in touched_licenses.values():
        recompute_license(license_row)
