"""Derived-field reconciliation (PRD §2.6) and the calculation rules (PRD §3.5,
§3.8, §3.10, §3.12, §3.13). All computed fields are recomputed the instant a
triggering event lands.

Constants come straight from SCAFFOLD §1.3 calculation tables.
"""

from db import db
from common import pct_of_cents, touch

# ---- Calculation constants ----
LATE_GRACE_MINUTES = 10
LATE_FEE_PER_MIN_CENTS = 100
LATE_FEE_CAP_CENTS = 2500

TIP_DIRECT_PCT_STANDALONE = 0.70
TIP_DIRECT_PCT_EVENT = 0.50

COMMISSION_RATE = {"JUNIOR": 0.35, "SENIOR": 0.45, "MASTER": 0.55}
EVENT_RATE_CAP = 0.40

DEPOSIT_PER_HEAD_CENTS = 2000
BRIDAL_SURCHARGE_CENTS = 10000

STRIKE_SUSPEND_THRESHOLD = 3


# ===========================================================================
# Appointment pricing (calc: appointment_service_pricing, PRD §3.5)
# ===========================================================================
def compute_appointment_pricing(appt):
    """Recompute schedule + pricing fields on an appointment in place.

    Uses the appointment's current attached AppointmentAddOn rows and the
    member's current blowout_credit_balance. Does NOT include late fee (added
    at check-in on top of the base charge).
    """
    service = db.style_services[appt["style_service_id"]]
    member = db.members[appt["member_id"]]
    addons = [a for a in db.appointment_add_ons.values()
              if a["appointment_id"] == appt["id"]]

    # ---- schedule ----
    extra_duration = sum(a["captured_duration_minutes"] for a in addons)
    appt["scheduled_duration_minutes"] = service["base_duration_minutes"] + extra_duration
    appt["end_minute"] = appt["start_minute"] + appt["scheduled_duration_minutes"]

    # ---- list amount ----
    list_amount = service["base_price_cents"] + sum(a["captured_price_cents"] for a in addons)
    appt["list_amount_cents"] = list_amount

    # ---- discount: per line, rounded per line, then summed ----
    plan = None
    if member.get("membership_plan_id"):
        plan = db.membership_plans.get(member["membership_plan_id"])
    if plan is None:
        rate = 0.0
        service_line_discount = 0
        discount_cents = 0
        # reset add-on per-line discounts
        for a in addons:
            a_disc = 0
            if a["discount_applied_cents"] != a_disc:
                a["discount_applied_cents"] = a_disc
                touch(a)
    else:
        rate = plan["member_discount_pct"]
        # service line always discount-eligible
        service_line_discount = pct_of_cents(service["base_price_cents"], rate)
        line_discounts = [service_line_discount]
        for a in addons:
            add_on = db.add_ons.get(a["add_on_id"])
            if add_on is not None and add_on["discount_eligible"]:
                d = pct_of_cents(a["captured_price_cents"], rate)
            else:
                d = 0
            line_discounts.append(d)
            if a["discount_applied_cents"] != d:
                a["discount_applied_cents"] = d
                touch(a)
        discount_cents = sum(line_discounts)
    appt["discount_cents"] = discount_cents

    net_after_discount = list_amount - discount_cents

    # ---- blowout credits cover the discounted SERVICE line only ----
    credit_cost = service["blowout_credit_cost"]
    credits_applied = min(member["blowout_credit_balance"], credit_cost)
    discounted_service_line = service["base_price_cents"] - service_line_discount
    if credits_applied >= credit_cost and credit_cost > 0:
        appt["credits_applied"] = credits_applied
        service_charge = net_after_discount - discounted_service_line
    else:
        appt["credits_applied"] = 0
        service_charge = net_after_discount
    appt["service_charge_cents"] = service_charge


# ===========================================================================
# Late fee (calc: late_fee, PRD §3.7)
# ===========================================================================
def compute_late_fee(arrival_status, late_minutes):
    if arrival_status != "LATE":
        return 0
    if late_minutes <= LATE_GRACE_MINUTES:
        return 0
    billable = late_minutes - LATE_GRACE_MINUTES
    return min(billable * LATE_FEE_PER_MIN_CENTS, LATE_FEE_CAP_CENTS)


# ===========================================================================
# Tip split (calc: tip_split, PRD §3.10)
# ===========================================================================
def compute_tip_split(appt, tip_cents):
    if appt.get("event_block_id") is None:
        stylist_tip = pct_of_cents(tip_cents, TIP_DIRECT_PCT_STANDALONE)
    else:
        stylist_tip = pct_of_cents(tip_cents, TIP_DIRECT_PCT_EVENT)
    tip_pool = tip_cents - stylist_tip
    return stylist_tip, tip_pool


# ===========================================================================
# Commission split (calc: commission_split, PRD §3.10)
# ===========================================================================
def compute_commission_split(appt, stylist):
    base_rate = COMMISSION_RATE[stylist["commission_tier"]]
    if appt.get("event_block_id") is not None:
        effective_rate = min(base_rate, EVENT_RATE_CAP)
    else:
        effective_rate = base_rate
    service_charge = appt["service_charge_cents"]
    commission = pct_of_cents(service_charge, effective_rate)
    house = service_charge - commission
    return commission, house


# ===========================================================================
# Retail commission (calc: retail_commission, PRD §3.12)
# ===========================================================================
def compute_retail_commission(gross_cents, attributed_stylist_id, product):
    if attributed_stylist_id is None:
        return 0
    return pct_of_cents(gross_cents, product["retail_commission_pct"])


# ===========================================================================
# Event block deposit (calc: event_block_deposit, PRD §3.11)
# ===========================================================================
def compute_event_block_deposit(party_size, block_type):
    deposit = party_size * DEPOSIT_PER_HEAD_CENTS
    if block_type == "BRIDAL":
        deposit += BRIDAL_SURCHARGE_CENTS
    return deposit


# ===========================================================================
# Member blowout credit balance (calc: blowout_credit_balance, PRD §3.2)
# ===========================================================================
def recompute_blowout_credit_balance(member):
    granted = 0
    if member.get("membership_plan_id"):
        plan = db.membership_plans.get(member["membership_plan_id"])
        if plan is not None:
            granted += plan["included_blowout_credits"]
    for pkg in db.package_purchases.values():
        if pkg["member_id"] == member["id"] and pkg["status"] == "ACTIVE":
            granted += pkg["credits_purchased"]
    consumed = 0
    for appt in db.appointments.values():
        if appt["member_id"] != member["id"]:
            continue
        if appt["lifecycle_status"] == "CANCELLED":
            continue
        consumed += appt.get("credits_applied", 0)
    balance = granted - consumed
    if balance < 0:
        balance = 0
    return balance


# ===========================================================================
# Member prepay balance (calc: prepay_balance, PRD §3.2)
# ===========================================================================
def recompute_prepay_balance(member):
    total = 0
    for t in db.prepay_topups:
        if t["member_id"] == member["id"]:
            total += t["amount_cents"]
    # minus settled PREPAY appointment charges
    for appt in db.appointments.values():
        if appt["member_id"] != member["id"]:
            continue
        if appt.get("payment_method") == "PREPAY" and appt["settlement_status"] == "SETTLED":
            total -= appt["service_charge_cents"]
    # plus refunds from refunded package purchases
    for pkg in db.package_purchases.values():
        if pkg["member_id"] == member["id"] and pkg["status"] == "REFUNDED":
            total += pkg["price_cents"]
    if total < 0:
        total = 0
    return total


# ===========================================================================
# Member no-show strikes (calc: no_show_strikes, PRD §3.8)
# ===========================================================================
def recompute_no_show_strikes(member):
    count = 0
    for appt in db.appointments.values():
        if appt["member_id"] != member["id"]:
            continue
        if appt["lifecycle_status"] == "NO_SHOW" and appt.get("arrival_status") == "NO_SHOW":
            count += 1
    return count - member.get("_reinstate_resets", 0)


def reconcile_member(member):
    """Recompute all member computed fields and derive status from strikes."""
    member["blowout_credit_balance"] = recompute_blowout_credit_balance(member)
    member["prepay_balance_cents"] = recompute_prepay_balance(member)
    strikes = recompute_no_show_strikes(member)
    if strikes < 0:
        strikes = 0
    member["no_show_strikes"] = strikes
    if strikes >= STRIKE_SUSPEND_THRESHOLD:
        member["status"] = "SUSPENDED"
    # Note: reinstate explicitly returns to ACTIVE; we never auto-un-suspend.


# ===========================================================================
# Product stock (PRD §3.12)
# ===========================================================================
def recompute_product_stock(product):
    sold = 0
    for sale in db.retail_sales.values():
        if sale["product_id"] == product["id"] and sale["status"] != "VOIDED":
            sold += sale["quantity"]
    product["stock_qty"] = product["_initial_and_restock"] - sold


# ===========================================================================
# Stylist earnings (PRD §3.3, §3.10, §3.12)
# ===========================================================================
def recompute_stylist_earnings(stylist):
    commission = 0
    tips = 0
    for appt in db.appointments.values():
        if appt.get("stylist_id") != stylist["id"]:
            continue
        if appt["settlement_status"] == "SETTLED":
            commission += appt.get("commission_amount_cents", 0)
            tips += appt.get("stylist_tip_cents", 0)
    # retail commission from non-voided sales attributed to this stylist
    for sale in db.retail_sales.values():
        if sale.get("attributed_stylist_id") == stylist["id"] and sale["status"] != "VOIDED":
            commission += sale["retail_commission_cents"]
    stylist["earned_commission_cents"] = commission
    stylist["earned_tips_cents"] = tips
