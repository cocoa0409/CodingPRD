"""Business-logic services shared across routes: pricing, accrual, cascades."""
import db
import calculations as calc
from helpers import loyalty_tier


def assigned_assignments(subscription_id):
    return [
        sa
        for sa in db.seat_assignments.values()
        if sa["subscription_id"] == subscription_id and sa["status"] == "ASSIGNED"
    ]


def season_window_of_subscription(subscription_id):
    """Return (start, end) of the subscription's season window from its first
    ASSIGNED seat assignment's seat, or None if there is none."""
    for sa in assigned_assignments(subscription_id):
        seat = db.seats.get(sa["seat_id"])
        if seat:
            return seat["season_start_date"], seat["season_end_date"]
    return None


def windows_overlap(a_start, a_end, b_start, b_end):
    """Closed-interval overlap: adjacency (shared endpoint) counts as overlap."""
    return a_start <= b_end and b_start <= a_end


def reprice_subscription(sub):
    """renewal_price over ASSIGNED assignments; set assigned_price_cents and
    locked_price_cents. Touches each repriced assignment."""
    account = db.accounts[sub["account_id"]]
    plan = db.season_plans[sub["season_plan_id"]]
    tier = loyalty_tier(account["priority_points"])
    total = 0
    for sa in assigned_assignments(sub["id"]):
        seat = db.seats[sa["seat_id"]]
        section = db.sections[seat["section_id"]]
        price = calc.seat_price(
            section["base_price_cents"], plan["price_multiplier_bps"], tier
        )
        sa["assigned_price_cents"] = price
        db.touch(sa)
        total += price
    sub["locked_price_cents"] = total
    return total


def accrue_points(sub):
    """priority_points_accrual onto Account; recompute tier; record granted."""
    account = db.accounts[sub["account_id"]]
    plan = db.season_plans[sub["season_plan_id"]]
    seat_count = len(assigned_assignments(sub["id"]))
    earned = calc.points_accrual(
        seat_count, account["consecutive_seasons"], plan["includes_playoffs"]
    )
    account["priority_points"] += earned
    db.touch(account)
    db.points_granted[sub["id"]] = db.points_granted.get(sub["id"], 0) + earned
    return earned


def set_seat_count(sub):
    sub["seat_count"] = len(assigned_assignments(sub["id"]))


def cancel_payment_plans_for_subscription(sub_id):
    """ACTIVE PaymentPlan -> CANCELLED; its SCHEDULED Installments -> VOID."""
    for plan in db.payment_plans.values():
        if plan["subscription_id"] == sub_id and plan["status"] == "ACTIVE":
            plan["status"] = "CANCELLED"
            db.touch(plan)
            for inst in db.installments.values():
                if (
                    inst["payment_plan_id"] == plan["id"]
                    and inst["status"] == "SCHEDULED"
                ):
                    inst["status"] = "VOID"
                    db.touch(inst)
            yield plan


def active_payment_plan(sub_id):
    for plan in db.payment_plans.values():
        if plan["subscription_id"] == sub_id and plan["status"] == "ACTIVE":
            return plan
    return None
