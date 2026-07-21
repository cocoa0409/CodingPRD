"""Composite setup helpers.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the harness restarts the server, so the database is empty before every test).
Setup runs as StoreManager, the superset operator that is exempt from ownership
checks (PRD 2.1), so fixtures never trip an ownership gate while staging state.
Ownership/RBAC tests thread the real Member/Fitter id via the per-instance
header builders in test_users.py.

All calls use get_success_data() so a setup failure raises a clear "Setup step
failed" error instead of a confusing downstream assertion.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import store_manager_headers
from . import factories as f

SM = store_manager_headers()


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, SM))


# --------------------------------------------------------------------------
# Primitive creators
# --------------------------------------------------------------------------
def create_member(**overrides) -> dict:
    return get_success_data(api_client.create_member(f.create_member_payload(**overrides), SM))


def grant_points(member_id: str, delta: int, reason: str = "seed points") -> dict:
    return get_success_data(
        api_client.adjust_loyalty(
            member_id, {"points_delta": delta, "reason": reason}, SM
        )
    )


def create_product(**overrides) -> dict:
    return get_success_data(api_client.create_product(f.create_product_payload(**overrides), SM))


def create_subscription(member_id: str, plan: str = "BASIC") -> dict:
    return get_success_data(
        api_client.create_subscription(f.create_subscription_payload(member_id, plan), SM)
    )


def create_fitter(full_name: str = "Test Fitter") -> dict:
    return get_success_data(api_client.create_fitter({"full_name": full_name}, SM))


def create_order(member_id: str, lines: list, promo_code=None) -> dict:
    return get_success_data(
        api_client.create_order(f.create_order_payload(member_id, lines, promo_code), SM)
    )


def create_single_line_order(member_id: str, product_id: str, quantity: int = 1, promo_code=None) -> dict:
    return create_order(member_id, [f.line(product_id, quantity)], promo_code)


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, SM))


def get_member(member_id: str) -> dict:
    return get_success_data(api_client.get_member(member_id, SM))


def get_product(product_id: str) -> dict:
    return get_success_data(api_client.get_product(product_id, SM))


def get_first_order_line(order_id: str, product_id: str = None) -> dict:
    params = {"order_id": order_id}
    if product_id is not None:
        params["product_id"] = product_id
    lines = get_success_data(api_client.list_order_lines(SM, params=params))
    assert lines, f"No order lines found for order {order_id}"
    return lines[0]


def get_first_shoe(source_order_id: str = None, member_id: str = None) -> dict:
    params = {}
    if source_order_id is not None:
        params["source_order_id"] = source_order_id
    if member_id is not None:
        params["member_id"] = member_id
    shoes = get_success_data(api_client.list_running_shoes(SM, params=params))
    assert shoes, f"No running shoes found for {params}"
    return shoes[0]


# --------------------------------------------------------------------------
# Order lifecycle shortcuts
# --------------------------------------------------------------------------
def create_paid_order(member_id: str, product_id: str, quantity: int = 1) -> dict:
    """Create -> authorize -> capture. Returns the order (payment PAID, fulfillment PENDING)."""
    order = create_single_line_order(member_id, product_id, quantity)
    oid = order["id"]
    get_success_data(api_client.authorize_payment(oid, SM))
    return get_success_data(api_client.capture_payment(oid, SM))


def create_reserved_order(member_id: str, product_id: str, quantity: int = 1, pay: bool = True) -> dict:
    """Create -> (authorize+capture) -> reserve. Returns the order (RESERVED)."""
    order = create_single_line_order(member_id, product_id, quantity)
    oid = order["id"]
    if pay:
        get_success_data(api_client.authorize_payment(oid, SM))
        get_success_data(api_client.capture_payment(oid, SM))
    return get_success_data(api_client.reserve_order(oid, SM))


def create_fulfilled_order(member_id: str, lines: list) -> dict:
    """Create -> authorize -> capture -> reserve -> fulfill. Returns the order (FULFILLED, PAID)."""
    order = create_order(member_id, lines)
    oid = order["id"]
    get_success_data(api_client.authorize_payment(oid, SM))
    get_success_data(api_client.capture_payment(oid, SM))
    get_success_data(api_client.reserve_order(oid, SM))
    return get_success_data(api_client.fulfill_order(oid, SM))


def fulfill_single_shoe_order(member_id: str, product_id: str, quantity: int = 1) -> dict:
    """Fully fulfill a one-product order. Returns the FULFILLED order."""
    return create_fulfilled_order(member_id, [f.line(product_id, quantity)])


def setup_fulfilled_shoe(member=None, mileage_life_miles: int = None, price_cents: int = 10000):
    """Member + SHOE product + fully fulfilled order + minted RunningShoe.

    Returns (member, product, order, shoe).
    """
    if member is None:
        member = create_member()
    prod_kwargs = dict(category="SHOE", unit_price_cents=price_cents, initial_stock=3)
    if mileage_life_miles is not None:
        prod_kwargs["mileage_life_miles"] = mileage_life_miles
    product = create_product(**prod_kwargs)
    order = fulfill_single_shoe_order(member["id"], product["id"])
    shoe = get_first_shoe(source_order_id=order["id"])
    return member, product, order, shoe


# --------------------------------------------------------------------------
# Return lifecycle shortcuts
# --------------------------------------------------------------------------
def open_return(order_line_id: str, reason: str = "wear test failed") -> dict:
    return get_success_data(
        api_client.create_return(f.create_return_payload(order_line_id, reason), SM)
    )


def open_inspected_return(order_line_id: str, reason: str = "wear test failed") -> dict:
    """Open a return and move it to UNDER_INSPECTION. Returns the WearReturn."""
    ret = open_return(order_line_id, reason)
    return get_success_data(api_client.start_inspection(ret["id"], SM))


def setup_return_under_inspection(price_cents: int = 10000):
    """Member + fulfilled SHOE order + WearReturn in UNDER_INSPECTION.

    Returns (member, product, order, line, ret).
    """
    member, product, order, _shoe = setup_fulfilled_shoe(price_cents=price_cents)
    line = get_first_order_line(order["id"])
    ret = open_inspected_return(line["id"])
    return member, product, order, line, ret


# --------------------------------------------------------------------------
# Subscription / training helpers
# --------------------------------------------------------------------------
def create_training_session(start_time: str, end_time: str, capacity: int = 5, title: str = "Group Run", fitter_id=None) -> dict:
    payload = f.create_training_session_payload(
        title=title, start_time=start_time, end_time=end_time, capacity=capacity
    )
    if fitter_id is not None:
        payload["fitter_id"] = fitter_id
    return get_success_data(api_client.create_training_session(payload, SM))


def book_training(session_id: str, member_id: str) -> dict:
    return get_success_data(
        api_client.create_training_booking(
            f.create_training_booking_payload(session_id, member_id), SM
        )
    )


def setup_member_with_active_subscription(plan: str = "BASIC"):
    """Member + ACTIVE subscription. Returns (member, subscription)."""
    member = create_member()
    sub = create_subscription(member["id"], plan)
    return member, sub


# --------------------------------------------------------------------------
# Fitment helpers
# --------------------------------------------------------------------------
def create_fitment(member_id: str, fitter_id: str, start: str, end: str) -> dict:
    return get_success_data(
        api_client.create_fitment_session(
            f.create_fitment_session_payload(member_id, fitter_id, start, end), SM
        )
    )
