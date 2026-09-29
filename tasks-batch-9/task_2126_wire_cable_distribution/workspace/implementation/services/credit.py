"""Customer credit posture and its cascades (PRD Section 3.9).

The posture rule is one rule with several triggers: delivery invoicing, a reel
return, and a CreditManager adjustment.  Going on hold voids the customer's
ISSUED quotes and holds their PENDING_ALLOCATION orders; coming off hold returns
their HELD orders to PENDING_ALLOCATION.  Quotes voided for CREDIT_HOLD are not
un-voided.
"""
import clock
import db
import calculations as calc
from services import lookup


def apply_posture(customer):
    """Re-evaluate credit posture after a balance or limit change and cascade."""
    target = calc.posture_transition(customer)
    if target is None:
        return None
    customer["credit_status"] = target
    db.touch(customer)
    if target == "CREDIT_HOLD":
        _on_hold(customer)
    else:
        _released(customer)
    return target


def _on_hold(customer):
    """Every ISSUED quote is voided for CREDIT_HOLD; every PENDING_ALLOCATION
    order moves to HELD.  A PARTIALLY_ALLOCATED order keeps its reservations and
    its status and is stopped later by ERR_CUSTOMER_CREDIT_HOLD."""
    for quote in lookup.quotes_of_customer(customer["id"]):
        if quote["status"] == "ISSUED":
            quote["status"] = "VOIDED"
            quote["void_reason"] = "CREDIT_HOLD"
            db.touch(quote)
    for order in lookup.orders_of_customer(customer["id"]):
        if order["fulfillment_status"] == "PENDING_ALLOCATION":
            order["fulfillment_status"] = "HELD"
            db.touch(order)


def _released(customer):
    """Every HELD order becomes allocatable again."""
    for order in lookup.orders_of_customer(customer["id"]):
        if order["fulfillment_status"] == "HELD":
            order["fulfillment_status"] = "PENDING_ALLOCATION"
            db.touch(order)
