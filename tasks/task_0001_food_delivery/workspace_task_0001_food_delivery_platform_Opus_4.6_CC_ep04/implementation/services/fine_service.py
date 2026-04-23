from models.fine import Fine
from storage import db
from services.rider_metrics import recompute_bonus_tier


def create_late_delivery_fine(rider, minutes_late, final_delivery_fee_cents):
    if minutes_late <= 0:
        return None
    if minutes_late <= 10:
        amount = 200
    elif minutes_late <= 30:
        amount = 500 + 50 * (minutes_late - 10)
    else:
        capped = min(final_delivery_fee_cents, 1500)
        amount = capped + 500

    fine = Fine("RIDER", rider.id, "LATE_DELIVERY", amount)
    db.fines[fine.id] = fine
    rider.wallet_balance_cents -= amount
    recompute_bonus_tier(rider)
    return fine


def create_no_show_fine(rider):
    fine = Fine("RIDER", rider.id, "RIDER_NO_SHOW", 500)
    db.fines[fine.id] = fine
    rider.wallet_balance_cents -= 500
    recompute_bonus_tier(rider)
    return fine


def create_abusive_return_fine(customer, amount_cents):
    fine = Fine("CUSTOMER", customer.id, "ABUSIVE_RETURN", amount_cents)
    db.fines[fine.id] = fine
    return fine


def waive_fine(fine):
    fine.settlement_status = "WAIVED"
    if fine.subject_type == "RIDER":
        rider = db.riders.get(fine.subject_id)
        if rider:
            rider.wallet_balance_cents += fine.amount_cents
            rider.touch()
    elif fine.subject_type == "CUSTOMER":
        customer = db.customers.get(fine.subject_id)
        if customer:
            customer.credit_balance_cents += fine.amount_cents
            customer.touch()
    elif fine.subject_type == "RESTAURANT":
        restaurant = db.restaurants.get(fine.subject_id)
        if restaurant:
            restaurant.pending_settlement_cents += fine.amount_cents
            restaurant.touch()
