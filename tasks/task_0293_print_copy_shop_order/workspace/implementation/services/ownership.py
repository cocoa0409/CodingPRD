"""Customer ownership checks (PRD §2.1, §3.9 precedence rung 4).

When X-User-Role is Customer, X-User-ID is the acting Customer.id; a customer
acting on an order/proof/line must own the order (order.customer_id == X-User-ID),
else ERR_NOT_ORDER_OWNER (403). ShopStaff/ProductionOperator are opaque — no check.
Ownership is checked AFTER existence (404) and BEFORE state (409).
"""

from flask import g

import errors
from errors import err


def require_order_owner(order):
    """If the caller is a Customer, enforce order ownership."""
    if g.user_role == "Customer" and order["customer_id"] != g.user_id:
        raise err(errors.ERR_NOT_ORDER_OWNER,
                  "Customer is not the owner of this order")
