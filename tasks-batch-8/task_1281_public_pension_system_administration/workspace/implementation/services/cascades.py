"""Cascading side effects (scaffold §1.2 / PRD §3.4, §3.5, §3.7).

Each cascaded child resource gets its own version increment and timestamp
refresh via db.touch().
"""

from db import store, touch, now, make_entity
from services import calcs

OPEN_PURCHASE_STATES = ("REQUESTED", "QUOTED", "PLAN_ACTIVE")
NONTERMINAL_RETIREMENT_STATES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "RETURNED_FOR_CORRECTION",
)


def purchase_payments(purchase_id):
    out = [p for p in store.payments.values() if p["purchase_id"] == purchase_id]
    out.sort(key=lambda p: p["_seq"])
    return out


def cancel_purchase(purchase):
    """REQUESTED/QUOTED/PLAN_ACTIVE -> CANCELLED. A plan-active purchase runs
    the refund cascade: APPLIED payments -> REFUNDED, refunded_total_cents set
    to the sum of those amounts, balance zeroed."""
    if purchase["status"] == "PLAN_ACTIVE":
        refunded = 0
        for pay in purchase_payments(purchase["id"]):
            if pay["status"] == "APPLIED":
                pay["status"] = "REFUNDED"
                touch(pay)
                refunded += pay["amount_cents"]
        purchase["refunded_total_cents"] = refunded
    purchase["balance_due_cents"] = 0
    purchase["status"] = "CANCELLED"
    touch(purchase)


def cancel_open_purchases(member_id):
    for p in calcs.member_purchases(member_id, OPEN_PURCHASE_STATES):
        cancel_purchase(p)


def cancel_nonterminal_retirement_apps(member_id, except_id=None):
    for app in calcs.member_retirement_apps(member_id):
        if app["id"] == except_id:
            continue
        if app["status"] in NONTERMINAL_RETIREMENT_STATES:
            app["status"] = "CANCELLED"
            touch(app)


def death_cascade(member):
    """Member -> DECEASED consequences: every Benefit in ACTIVE or SUSPENDED
    -> TERMINATED; every ServicePurchase in REQUESTED/QUOTED/PLAN_ACTIVE ->
    CANCELLED (with the refund cascade on plan-active purchases)."""
    for benefit in calcs.member_benefits(member["id"]):
        if benefit["status"] in ("ACTIVE", "SUSPENDED"):
            benefit["status"] = "TERMINATED"
            touch(benefit)
    cancel_open_purchases(member["id"])


def create_benefit(member, benefit_kind, monthly_amount_cents, origin_option=None,
                   origin_app_id=None):
    """Benefits are born ACTIVE from an approval, effective the first day of
    the approval month on the logical clock."""
    benefit = make_entity(
        {
            "member_id": member["id"],
            "benefit_kind": benefit_kind,
            "monthly_amount_cents": monthly_amount_cents,
            "status": "ACTIVE",
            "effective_date": calcs.first_of_month(now()).isoformat(),
            "cola_applied_count": 0,
            "rtw_calendar_year": None,
            "rtw_ytd_earnings_cents": 0,
            "_effective_date": calcs.first_of_month(now()),
            "_origin_option": origin_option,
            "_origin_app_id": origin_app_id,
        }
    )
    store.benefits[benefit["id"]] = benefit
    return benefit


def retire_member(member):
    """Member ACTIVE -> RETIRED on an approval, with the shared cascades:
    other non-terminal retirement applications cancelled; open purchases
    cancelled with refunds."""
    member["status"] = "RETIRED"
    touch(member)
    cancel_nonterminal_retirement_apps(member["id"])
    cancel_open_purchases(member["id"])
