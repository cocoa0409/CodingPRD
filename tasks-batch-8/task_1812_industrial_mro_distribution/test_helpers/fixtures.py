"""
Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

All helpers use get_success_data() (lenient) so a failed setup step surfaces a
clear "Setup step failed" error instead of a confusing assertion failure.

Identity threading: ownership-gated calls by entity-backed roles (CustomerBuyer,
CustomerApprover) always go through make_buyer_headers / make_approver_headers
with the actual CustomerAccount.id — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_cart_payload,
    create_customer_payload,
    create_item_payload,
    create_location_payload,
    create_order_payload,
    create_price_rule_payload,
    create_rebate_agreement_payload,
    create_return_payload,
)
from .test_users import TEST_USERS, make_approver_headers, make_buyer_headers

ADMIN = TEST_USERS["admin_headers"]
BRANCH_MANAGER = TEST_USERS["branch_manager_headers"]
VENDOR_REP = TEST_USERS["vendor_rep_headers"]


# ─── Tier 1: single-resource creators ─────────────────


def create_customer(**overrides) -> dict:
    """Create a CustomerAccount (born ACTIVE, counters zero)."""
    res = api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_national_customer(**overrides) -> dict:
    """Create a CustomerAccount flagged is_national_account=true (PRD §3.9 gate)."""
    overrides.setdefault("is_national_account", True)
    return create_customer(**overrides)


def create_item(**overrides) -> dict:
    res = api_client.create_item(create_item_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_branch(**overrides) -> dict:
    overrides.setdefault("location_type", "BRANCH")
    res = api_client.create_location(create_location_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_central(**overrides) -> dict:
    overrides["location_type"] = "CENTRAL"
    res = api_client.create_location(create_location_payload(**overrides), ADMIN)
    return get_success_data(res)


def restock(location_id: str, item_id: str, qty: int) -> dict:
    """Add on-hand stock; creates the StockBalance lazily on first use (PRD §3.3)."""
    res = api_client.restock_location(
        location_id, {"item_id": item_id, "qty": qty}, ADMIN
    )
    return get_success_data(res)


def set_clock(to_iso8601: str) -> dict:
    res = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(res)


# ─── Price matrix helpers (PRD §3.2) ──────────────────


def create_price_rule(**overrides) -> dict:
    res = api_client.create_price_rule(create_price_rule_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_active_price_rule(**overrides) -> dict:
    """Create a DRAFT rule and activate it (overlap gate fires at activation)."""
    rule = create_price_rule(**overrides)
    res = api_client.activate_price_rule(rule["id"], ADMIN)
    return get_success_data(res)


# ─── Rebate helpers (PRD §3.9) ────────────────────────


def create_rebate_agreement(customer_id: str, **overrides) -> dict:
    res = api_client.create_rebate_agreement(
        customer_id, create_rebate_agreement_payload(**overrides), ADMIN
    )
    return get_success_data(res)


def create_active_rebate_agreement(customer_id: str, **overrides) -> dict:
    """Create a DRAFT agreement and activate it (clock date must be <= period_end)."""
    agreement = create_rebate_agreement(customer_id, **overrides)
    res = api_client.activate_rebate_agreement(agreement["id"], ADMIN)
    return get_success_data(res)


def get_rebate_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_rebate_agreement(agreement_id, ADMIN))


# ─── Cart helpers (PRD §3.4) ──────────────────────────


def create_cart(customer_id: str, lines, **overrides) -> dict:
    """Create a cart as the owning buyer (entity-backed identity threading)."""
    res = api_client.create_cart(
        create_cart_payload(customer_id, lines, **overrides),
        make_buyer_headers(customer_id),
    )
    return get_success_data(res)


def submit_cart(cart_id: str, customer_id: str) -> dict:
    res = api_client.submit_cart(cart_id, make_buyer_headers(customer_id))
    return get_success_data(res)


def revise_cart(cart_id: str, customer_id: str, lines) -> dict:
    res = api_client.update_cart(
        cart_id, {"lines": lines}, make_buyer_headers(customer_id)
    )
    return get_success_data(res)


def approve_cart(cart_id: str, customer_id: str) -> dict:
    res = api_client.approve_cart(cart_id, make_approver_headers(customer_id))
    return get_success_data(res)


def reject_cart(cart_id: str, customer_id: str, reason: str = "declined") -> dict:
    res = api_client.reject_cart(
        cart_id, {"reason": reason}, make_approver_headers(customer_id)
    )
    return get_success_data(res)


def create_submitted_cart(customer_id: str, lines, **overrides) -> dict:
    """Cart created and submitted; lands PENDING_APPROVAL or APPROVED by threshold."""
    cart = create_cart(customer_id, lines, **overrides)
    return submit_cart(cart["id"], customer_id)


def create_approved_cart(customer_id: str, lines, **overrides) -> dict:
    """Cart driven to APPROVED (auto-approve fork; set a high threshold)."""
    cart = create_submitted_cart(customer_id, lines, **overrides)
    if cart["status"] == "PENDING_APPROVAL":
        cart = approve_cart(cart["id"], customer_id)
    return cart


# ─── Order lifecycle helpers (PRD §3.5–§3.7) ──────────


def place_order(
    customer_id: str,
    branch_id: str,
    lines=None,
    fulfillment_method: str = "WILL_CALL",
    as_buyer: bool = False,
    **overrides,
) -> dict:
    """Create a SalesOrder (born SUBMITTED / UNALLOCATED)."""
    headers = make_buyer_headers(customer_id) if as_buyer else ADMIN
    res = api_client.create_order(
        create_order_payload(
            customer_id, branch_id, lines,
            fulfillment_method=fulfillment_method, **overrides,
        ),
        headers,
    )
    return get_success_data(res)


def confirm_order(order_id: str) -> dict:
    return get_success_data(api_client.confirm_order(order_id, ADMIN))


def cancel_order(order_id: str, customer_id: str = None) -> dict:
    headers = make_buyer_headers(customer_id) if customer_id else ADMIN
    return get_success_data(api_client.cancel_order(order_id, headers))


def mark_ready(order_id: str) -> dict:
    return get_success_data(api_client.mark_order_ready(order_id, BRANCH_MANAGER))


def vendor_confirm(order_id: str, actual_costs) -> dict:
    return get_success_data(
        api_client.vendor_confirm_order(order_id, {"actual_costs": actual_costs},
                                        VENDOR_REP)
    )


def mark_fulfilled(order_id: str) -> dict:
    return get_success_data(api_client.mark_order_fulfilled(order_id, BRANCH_MANAGER))


def complete_order(order_id: str) -> dict:
    return get_success_data(api_client.complete_order(order_id, ADMIN))


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, ADMIN))


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def get_order_lines(order_id: str) -> list:
    """Order lines in creation order (PRD §3.5)."""
    data, _meta = _paginated(api_client.list_order_lines(order_id, ADMIN))
    return data


def _paginated(response):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)


def get_location_balance(location_id: str, item_id: str) -> dict:
    """Fetch the StockBalance for (location, item) via the location listing."""
    data, _meta = _paginated(api_client.list_location_stock_balances(location_id, ADMIN))
    for balance in data:
        if balance["item_id"] == item_id:
            return balance
    raise AssertionError(
        f"Setup: no StockBalance for item {item_id} at location {location_id}"
    )


# ─── Tier 3/5 composite: order walked to a late stage ─


def setup_order_scenario(
    line_specs,
    customer_overrides=None,
    branch_overrides=None,
    fulfillment_method: str = "WILL_CALL",
    restock_qtys=None,
    as_buyer: bool = False,
) -> dict:
    """
    Customer + one item per spec + branch + optional restock + SUBMITTED order.

    line_specs: list of dicts with item field overrides plus "qty" for the line,
        e.g. [{"qty": 2, "list_price_cents": 1000, "item_class": "STOCKED"}].
    restock_qtys: parallel list of branch restock quantities (None = no restock).
    Returns {"customer", "items", "branch", "order"}.
    """
    customer = create_customer(**(customer_overrides or {}))
    branch = create_branch(**(branch_overrides or {}))
    items = []
    for spec in line_specs:
        spec = dict(spec)
        spec.pop("qty", None)
        items.append(create_item(**spec))
    if restock_qtys:
        for item, qty in zip(items, restock_qtys):
            if qty:
                restock(branch["id"], item["id"], qty)
    lines = [
        {"item_id": item["id"], "qty": spec["qty"]}
        for item, spec in zip(items, line_specs)
    ]
    order = place_order(
        customer["id"], branch["id"], lines,
        fulfillment_method=fulfillment_method, as_buyer=as_buyer,
    )
    return {"customer": customer, "items": items, "branch": branch, "order": order}


def setup_confirmed_order(
    line_specs,
    customer_overrides=None,
    branch_overrides=None,
    fulfillment_method: str = "WILL_CALL",
    restock_qtys=None,
) -> dict:
    """setup_order_scenario + confirm. Adds "lines" (creation order) to the dict."""
    scenario = setup_order_scenario(
        line_specs,
        customer_overrides=customer_overrides,
        branch_overrides=branch_overrides,
        fulfillment_method=fulfillment_method,
        restock_qtys=restock_qtys,
    )
    scenario["order"] = confirm_order(scenario["order"]["id"])
    scenario["lines"] = get_order_lines(scenario["order"]["id"])
    return scenario


def setup_fulfilled_order(
    line_specs,
    customer_overrides=None,
    branch_overrides=None,
    fulfillment_method: str = "WILL_CALL",
    restock_qtys=None,
) -> dict:
    """Confirmed + mark-ready + mark-fulfilled (FULFILLED; returnable per PRD §3.8)."""
    scenario = setup_confirmed_order(
        line_specs,
        customer_overrides=customer_overrides,
        branch_overrides=branch_overrides,
        fulfillment_method=fulfillment_method,
        restock_qtys=restock_qtys,
    )
    mark_ready(scenario["order"]["id"])
    scenario["order"] = mark_fulfilled(scenario["order"]["id"])
    return scenario


def setup_completed_order(
    line_specs,
    customer_overrides=None,
    branch_overrides=None,
    fulfillment_method: str = "WILL_CALL",
    restock_qtys=None,
) -> dict:
    """Full lifecycle through COMPLETED (terminal)."""
    scenario = setup_fulfilled_order(
        line_specs,
        customer_overrides=customer_overrides,
        branch_overrides=branch_overrides,
        fulfillment_method=fulfillment_method,
        restock_qtys=restock_qtys,
    )
    scenario["order"] = complete_order(scenario["order"]["id"])
    return scenario


# ─── Returns helpers (PRD §3.8) ───────────────────────


def create_return(order_id: str, lines, **overrides) -> dict:
    """Create a ReturnAuthorization as DistributionAdmin (born REQUESTED)."""
    res = api_client.create_return(
        create_return_payload(order_id, lines, **overrides), ADMIN
    )
    return get_success_data(res)


def walk_return_to_received(return_id: str) -> dict:
    """REQUESTED -> APPROVED -> RECEIVED."""
    api_client.approve_return(return_id, ADMIN)
    res = api_client.receive_return(return_id, BRANCH_MANAGER)
    return get_success_data(res)
