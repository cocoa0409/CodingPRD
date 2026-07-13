"""Cross-entity gate: paying a ticket depends on its owning drawer's state.

Each test docstring cites the verbatim PRD sentence it asserts and ends with a
Design: traceability tag mapping it to its originating design-index instance.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    make_flavor, make_size, make_batch,
    open_drawer, open_order, add_line,
    api_client, get_success_data,
    TEST_USERS,
)

SCOOP = TEST_USERS["scooper_headers"]
LEAD = TEST_USERS["shift_lead_headers"]


def _order_with_line():
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="SINGLE", scoop_count=1, base_price_cents=350)
    make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer(opening_float_cents=10000)
    order = open_order(drawer["id"])
    add_line(order["id"], size["id"], flavor["id"])
    return drawer, order


def test_pay_rejected_once_drawer_closed(api):
    """PRD 3.8: "Because payment requires an open till, once a drawer is closed no
    further ticket may be paid into it."
    PRD 3.4: "Payment is refused unless the order has at least one `ACTIVE` line
    (`ERR_EMPTY_ORDER`) and the owning drawer is still `OPEN` (`ERR_DRAWER_NOT_OPEN`)."

    Design: Difficulty/cross_entity_state_dependency/pay_requires_drawer_open
    """
    drawer, order = _order_with_line()
    validate_success(api.close_drawer(drawer["id"], {"counted_cash_cents": 10000}, LEAD), 200)
    res = api.pay_order(order["id"], {"payment_method": "CARD"}, SCOOP)
    validate_error(res, "ERR_DRAWER_NOT_OPEN")


def test_pay_succeeds_while_drawer_open(api):
    """PRD 3.4: "A `Scooper` or `ShiftLead` takes payment, moving the order from
    `OPEN` to `PAID`."
    PRD 3.4: "Payment is refused unless the order has at least one `ACTIVE` line
    (`ERR_EMPTY_ORDER`) and the owning drawer is still `OPEN` (`ERR_DRAWER_NOT_OPEN`)."

    Design: Difficulty/cross_entity_state_dependency/pay_requires_drawer_open
    """
    drawer, order = _order_with_line()
    paid = validate_success(api.pay_order(order["id"], {"payment_method": "CARD"}, SCOOP), 200)
    assert paid["status"] == "PAID"
