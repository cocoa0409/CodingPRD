"""Courier-leg helpers shared by the decision, abandonment and cancellation paths."""
import clock
import store
from services import lookup


def highest_leg_index(order):
    highest = 0
    for leg in lookup.legs_of(order):
        if leg["leg_index"] > highest:
            highest = leg["leg_index"]
    return highest


def create_return_leg(order):
    """AGENCY -> SERVICE return hop, leg_index one above the highest existing hop,
    scheduled_date equal to the calendar date of the logical clock."""
    return store.insert("courier_legs", {
        "order_id": order["id"],
        "leg_index": highest_leg_index(order) + 1,
        "from_holder": "AGENCY",
        "to_holder": "SERVICE",
        "scheduled_date": clock.now().date(),
        "leg_status": "CREATED",
        "attempt_count": 0,
    })
