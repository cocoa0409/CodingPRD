"""Cross-entity cascades (PRD 2.11, 3.5, 3.6, 3.9).

Every hop refreshes `updated_at` and increments `version` by exactly 1 on each
row it mutates, and every hop lands synchronously inside the triggering request.
"""

from decimal import Decimal

import calc
import serializers
from db import clock_ym, db, next_seq, new_id, now_iso, stamp_new, touch


# --------------------------------------------------------------------------
# derived PSA posture
# --------------------------------------------------------------------------
def recompute_psa_status(psa):
    if psa["curative_status"] == "CURATIVE_TERMINATED":
        psa["psa_status"] = "TERMINATED"
    elif (psa["curative_status"] == "CURATIVE_CLOSED"
          and psa["funding_status"] == "FUNDED"
          and psa["recorded_book_page"] is not None):
        psa["psa_status"] = "CLOSED"
    else:
        psa["psa_status"] = "EXECUTED"
    return psa["psa_status"]


# --------------------------------------------------------------------------
# curative termination: PSA -> MineralInterest -> (OfferLetter, Valuation)
# --------------------------------------------------------------------------
def curative_termination_cascade(psa):
    interest = db.mineral_interests.get(psa["mineral_interest_id"])
    if interest is None:
        return
    # hop 2
    interest["interest_status"] = "PROSPECT"
    touch(interest)
    # hop 3, caused by hop 2 rather than by the close itself
    for offer in db.offer_letters.values():
        if offer["mineral_interest_id"] != interest["id"]:
            continue
        if offer["offer_status"] == "ACCEPTED":
            offer["offer_status"] = "VOIDED"
            touch(offer)
    for valuation in db.valuations.values():
        if valuation["mineral_interest_id"] != interest["id"]:
            continue
        if valuation["valuation_status"] == "CURRENT":
            valuation["valuation_status"] = "STALE"
            touch(valuation)
    if interest["current_valuation_id"] is not None:
        live = db.valuations.get(interest["current_valuation_id"])
        if live is not None and live["valuation_status"] != "CURRENT":
            pass  # the pointer is a convenience only and is left in place


# --------------------------------------------------------------------------
# suspense upsert, keyed on (division_order_id, royalty_owner_id)
# --------------------------------------------------------------------------
def find_suspense(order):
    for account in db.suspense_accounts.values():
        if (account["division_order_id"] == order["id"]
                and account["royalty_owner_id"] == order["royalty_owner_id"]):
            return account
    return None


def upsert_suspense(order, reason, first_month):
    """`suspense_reason` is written once by whichever cascade opened the account
    and is never rewritten afterwards (PRD 3.6)."""
    account = find_suspense(order)
    if account is None:
        account = {
            "division_order_id": order["id"],
            "royalty_owner_id": order["royalty_owner_id"],
            "suspense_reason": reason,
            "accrued_amount": Decimal("0.00"),
            "held_detail_count": 0,
            "first_suspended_month": first_month,
            "months_held": 0,
            "interest_accrued": Decimal("0.00"),
            "release_amount": Decimal("0.00"),
            "suspense_status": "ACCRUING",
            "escheat_state_code": None,
            "released_by_user_id": None,
        }
        stamp_new(account)
        db.suspense_accounts[account["id"]] = account
        serializers.refresh_suspense(account)
        return account
    account["suspense_status"] = "ACCRUING"
    serializers.refresh_suspense(account)
    touch(account)
    return account


# --------------------------------------------------------------------------
# deed recording: PSA -> MineralInterest -> DivisionOrder -> SuspenseAccount
# --------------------------------------------------------------------------
def recording_cascade(psa):
    interest = db.mineral_interests.get(psa["mineral_interest_id"])
    if interest is None:
        return
    # hop 2
    interest["interest_status"] = "ACQUIRED"
    interest["acquiring_deed_book_page"] = psa["recorded_book_page"]
    touch(interest)
    # hop 3, caused by hop 2
    orders = [o for o in db.division_orders.values()
              if o["mineral_interest_id"] == interest["id"]
              and o["do_status"] in ("SENT", "EXECUTED")]
    orders.sort(key=lambda o: o["_seq"])
    for order in orders:
        order["do_status"] = "DISPUTED"
        order["dispute_reason"] = "OWNERSHIP_CHANGE"
        unit = db.units.get(order["unit_id"])
        if unit is not None:
            fresh, allocation = calc.try_compute_expected_decimal(interest, unit)
            if fresh is not None:
                order["expected_decimal"] = fresh
                order["allocation_id"] = allocation["id"]
        touch(order)
        # hop 4, caused by hop 3
        upsert_suspense(order, "OWNERSHIP_TRANSFER", clock_ym())


# --------------------------------------------------------------------------
# revenue routing (PRD 3.9)
# --------------------------------------------------------------------------
def route_revenue_detail(order, detail, owner):
    if owner is not None and owner["contact_status"] != "LOCATED":
        detail["check_status"] = "VARIANCE_HELD"
        reason = "UNLOCATABLE_OWNER"
    elif detail["variance_amount"] != Decimal("0.00"):
        detail["check_status"] = "VARIANCE_HELD"
        reason = "DECIMAL_VARIANCE"
    else:
        detail["check_status"] = "PAID"
        order["paid_net_total"] = calc.q2(order["paid_net_total"] + detail["net_amount"])
        return None
    # two-hop cascade on a held line
    order["do_status"] = "SUSPENDED"
    order["cumulative_variance_amount"] = calc.q2(
        order["cumulative_variance_amount"] + detail["variance_amount"])
    return reason


# --------------------------------------------------------------------------
# suspense release (PRD 3.9)
# --------------------------------------------------------------------------
def release_cascade(account, order, user_id):
    serializers.refresh_suspense(account)
    released = account["accrued_amount"]
    account["suspense_status"] = "RELEASED"
    account["released_by_user_id"] = user_id
    account["accrued_amount"] = Decimal("0.00")
    account["held_detail_count"] = 0
    touch(account)
    if order is None:
        return released
    details = [d for d in db.revenue_details.values()
               if d["division_order_id"] == order["id"]
               and d["check_status"] == "VARIANCE_HELD"]
    details.sort(key=lambda d: d["_seq"])
    for detail in details:
        detail["check_status"] = "PAID"
        touch(detail)
    order["paid_net_total"] = calc.q2(order["paid_net_total"] + released)
    order["cumulative_variance_amount"] = Decimal("0.00")
    order["do_status"] = "EXECUTED"
    touch(order)
    return released
