"""Rungs 15-19: the two global write gates, the cutoff, window state, and the
source-state rung -- plus the rung-19 home for every non-state transition
precondition.

Adjudication of friction 2: ERR_INVALID_STATE (409).  The preconditions PRD
2.6's final paragraph lists (window temporal gates, the aggregate gates, the
retire/route/lot/club gates) carry no declared code.  They are routed to rung
19 with ERR_INVALID_STATE rather than to ERR_VALIDATION (400) because:
  * they are all preconditions on a REQUESTED TRANSITION whose source state is
    itself admissible, which is exactly what rung 19 owns; and
  * routing them to ERR_VALIDATION would place them at rung 4/13, i.e. BEFORE
    the two global write gates, which would make ERR_PERMIT_NOT_ACTIVE (rung
    15) and ERR_WINDOW_LOCKED (rung 16) unreportable on any call that also
    misses a temporal gate -- e.g. advancing a DRAFT window to OPEN before
    `opens_at` under a PENDING permit would report ERR_VALIDATION and the
    permit gate would never be evaluated.  Rung 19 keeps both gates reachable.
"""

import config
from db import DB
from errors import ApiError
from tsutil import lt


def permit_gate(baker):
    """Rung 15.  Applies to exactly the twelve operations PRD 2.6 names."""
    if baker is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "The owning operator is unknown.")
    if baker.get("permit_status") != "ACTIVE":
        raise ApiError("ERR_PERMIT_NOT_ACTIVE",
                       "The operator's permit is %s." % baker.get("permit_status"))


def window_locked_gate(window):
    """Rung 16.  Applies to exactly the nine order-mutating operations."""
    if window is not None and window.get("window_status") == "LOCKED":
        raise ApiError("ERR_WINDOW_LOCKED", "The offer window is LOCKED.")


def cutoff_gate(window, now):
    """Rung 17.  Strictly before order_cutoff_at; equality is already past."""
    cutoff = window.get("order_cutoff_at")
    if cutoff is None or not lt(now, cutoff):
        raise ApiError("ERR_CUTOFF_PASSED", "The order cutoff has passed.")


def window_open_gate(window):
    """Rung 18."""
    if window.get("window_status") != "OPEN":
        raise ApiError("ERR_WINDOW_NOT_OPEN",
                       "The offer window is %s." % window.get("window_status"))


def invalid_state(message):
    """Rung 19."""
    return ApiError("ERR_INVALID_STATE", message)


def require_state(current, allowed, label):
    """Rung 19 source-state check."""
    if current not in allowed:
        raise invalid_state("%s is %s; expected one of %s."
                            % (label, current, ", ".join(allowed)))


def baker_of_window(window):
    return DB.get("bakers", window.get("baker_id"))


def baker_of_customer(customer):
    return DB.get("bakers", customer.get("baker_id"))


def baker_of_order(order):
    window = DB.get("offer_windows", order.get("offer_window_id"))
    if window is not None:
        return DB.get("bakers", window.get("baker_id"))
    cust = DB.get("customers", order.get("customer_id"))
    return DB.get("bakers", cust.get("baker_id")) if cust else None


def active_payment(order_id):
    """The payment that governs an order's money axis."""
    pays = [p for p in DB.values("payments") if p.get("order_id") == order_id]
    if not pays:
        return None
    for state in ("CAPTURED", "SETTLED", "AUTHORIZED", "INITIATED",
                  "VOIDED", "DECLINED"):
        for pay in reversed(pays):
            if pay.get("payment_state") == state:
                return pay
    return pays[-1]


def dtc_gate(channel):
    """Rung 24."""
    if channel != "DTC":
        raise ApiError("ERR_WHOLESALE_NOT_PERMITTED",
                       "Wholesale is not permitted to a cottage-food operation.")


def product_class_gate(menu_item):
    """Rung 25."""
    if menu_item.get("product_class") != config.DTC_ELIGIBLE_PRODUCT_CLASS:
        raise ApiError("ERR_PRODUCT_CLASS_NOT_DTC_ELIGIBLE",
                       "Only %s product may be sold direct."
                       % config.DTC_ELIGIBLE_PRODUCT_CLASS)


def recipe_published_gate(recipe):
    """Rung 26."""
    if recipe is None or recipe.get("recipe_status") != "PUBLISHED":
        raise ApiError("ERR_RECIPE_NOT_PUBLISHED",
                       "The backing recipe is not PUBLISHED.")
