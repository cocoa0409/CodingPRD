"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the test harness restarts the server with an empty database before
every test). All setup calls use the lenient get_success_data() validator so a
broken precondition surfaces as a clear "Setup failed" rather than a confusing
assertion mismatch.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]
INV = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["sales_clerk_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(iso8601: str):
    return get_success_data(api_client.set_clock(iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1/2: base provisioning
# ---------------------------------------------------------------------------
def create_nursery(**overrides) -> dict:
    return get_success_data(api_client.create_nursery(F.create_nursery_payload(**overrides), ADMIN))


def create_account(nursery_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_account(nursery_id, F.create_account_payload(**overrides), CLERK)
    )


def create_product(nursery_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_product(nursery_id, F.create_product_payload(**overrides), INV)
    )


def create_live_plant(nursery_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_product(nursery_id, F.create_live_plant_payload(**overrides), INV)
    )


def create_vehicle(nursery_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_vehicle(nursery_id, F.create_vehicle_payload(**overrides), INV)
    )


def create_lot(product_id, received_qty=10, unit_cost_cents=250) -> dict:
    return get_success_data(
        api_client.create_inventory_lot(
            product_id,
            F.create_inventory_lot_payload(received_qty=received_qty, unit_cost_cents=unit_cost_cents),
            INV,
        )
    )


def create_released_lot(product_id, received_qty=10, unit_cost_cents=250) -> dict:
    """Receive a lot and release it to AVAILABLE. Returns the released lot."""
    lot = create_lot(product_id, received_qty=received_qty, unit_cost_cents=unit_cost_cents)
    get_success_data(api_client.release_lot(lot["id"], INV))
    return get_success_data(api_client.get_inventory_lot(lot["id"], INV))


def create_promotion(nursery_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_promotion(nursery_id, F.create_promotion_payload(**overrides), CLERK)
    )


def create_active_promotion(nursery_id, **overrides) -> dict:
    promo = create_promotion(nursery_id, **overrides)
    return get_success_data(api_client.activate_promotion(promo["id"], CLERK))


# ---------------------------------------------------------------------------
# Orders / lines
# ---------------------------------------------------------------------------
def create_order(account_id) -> dict:
    return get_success_data(api_client.create_order(account_id, CLERK))


def add_line(order_id, product_id, qty=1, **overrides) -> dict:
    return get_success_data(
        api_client.add_line(order_id, F.add_line_payload(product_id, qty=qty, **overrides), CLERK)
    )


def current_order_version(order_id) -> int:
    """Read the order's live version (PRD §2.7 OCC requires the *current* version).

    Adding a line mutates the order, so per PRD §2.5/§2.6 its version advances past
    the value captured at create_order. Setup helpers that walk an order through its
    transitions must therefore re-read the live version before each guarded call.
    """
    return get_success_data(api_client.get_order(order_id, CLERK))["version"]


def confirm(order_id, expected_order_version=None, **overrides) -> dict:
    # Setup helpers always intend a *successful* confirm, so they must supply the
    # order's current version (PRD §2.7). Re-read it rather than trust a stale value
    # captured before lines were added.
    version = current_order_version(order_id)
    return get_success_data(
        api_client.confirm_order(order_id, F.confirm_payload(version, **overrides), CLERK)
    )


def allocate(order_id, expected_order_version) -> dict:
    return get_success_data(
        api_client.allocate_order(order_id, F.version_payload(expected_order_version), INV)
    )


def pay(order_id, expected_order_version) -> dict:
    return get_success_data(
        api_client.pay_order(order_id, F.version_payload(expected_order_version), CLERK)
    )


def charge_account(order_id, expected_order_version) -> dict:
    return get_success_data(
        api_client.charge_account(order_id, F.version_payload(expected_order_version), CLERK)
    )


def fulfill(order_id, expected_order_version) -> dict:
    return get_success_data(
        api_client.fulfill_order(order_id, F.version_payload(expected_order_version), INV)
    )


def setup_nursery_account_product(nursery_overrides=None, account_overrides=None, product_overrides=None):
    """Active nursery + RETAIL account + DRY_GOOD product. Returns (nursery, account, product)."""
    nursery = create_nursery(**(nursery_overrides or {}))
    account = create_account(nursery["id"], **(account_overrides or {}))
    product = create_product(nursery["id"], **(product_overrides or {}))
    return nursery, account, product


def setup_confirmed_order(unit_price_cents=1000, qty=1, account_overrides=None,
                          product_overrides=None, nursery_overrides=None, confirm_overrides=None):
    """Nursery + account + product + released lot + order with one line, confirmed.

    Returns dict with nursery, account, product, lot, order, line, version.
    """
    nursery = create_nursery(**(nursery_overrides or {}))
    account = create_account(nursery["id"], **(account_overrides or {}))
    prod_kwargs = {"unit_price_cents": unit_price_cents}
    prod_kwargs.update(product_overrides or {})
    product = create_product(nursery["id"], **prod_kwargs)
    lot = create_released_lot(product["id"], received_qty=max(qty * 5, 10))
    order = create_order(account["id"])
    line = add_line(order["id"], product["id"], qty=qty)
    confirmed = confirm(order["id"], order["version"], **(confirm_overrides or {}))
    return {
        "nursery": nursery,
        "account": account,
        "product": product,
        "lot": lot,
        "order": confirmed,
        "line": line,
        "version": confirmed["version"],
    }


def setup_allocated_order(unit_price_cents=1000, qty=1, account_overrides=None,
                          product_overrides=None, nursery_overrides=None):
    """A confirmed order then allocated. Returns same dict with order at ALLOCATED."""
    ctx = setup_confirmed_order(
        unit_price_cents=unit_price_cents, qty=qty,
        account_overrides=account_overrides, product_overrides=product_overrides,
        nursery_overrides=nursery_overrides,
    )
    allocated = allocate(ctx["order"]["id"], ctx["version"])
    ctx["order"] = allocated
    ctx["version"] = allocated["version"]
    return ctx


def setup_fulfilled_order(unit_price_cents=1000, qty=1, account_overrides=None,
                          product_overrides=None, nursery_overrides=None, confirm_overrides=None):
    """Walk an order all the way to FULFILLED (confirm -> allocate -> pay -> fulfill).

    Returns dict with nursery, account, product, lot, order (FULFILLED), line, version.
    """
    nursery = create_nursery(**(nursery_overrides or {}))
    account = create_account(nursery["id"], **(account_overrides or {}))
    prod_kwargs = {"unit_price_cents": unit_price_cents}
    prod_kwargs.update(product_overrides or {})
    product = create_product(nursery["id"], **prod_kwargs)
    lot = create_released_lot(product["id"], received_qty=max(qty * 5, 10))
    order = create_order(account["id"])
    line = add_line(order["id"], product["id"], qty=qty)
    c = confirm(order["id"], order["version"], **(confirm_overrides or {}))
    a = allocate(order["id"], c["version"])
    p = pay(order["id"], a["version"])
    f = fulfill(order["id"], p["version"])
    return {
        "nursery": nursery,
        "account": account,
        "product": product,
        "lot": lot,
        "order": f,
        "line": line,
        "version": f["version"],
    }


# ---------------------------------------------------------------------------
# Tier 4: threshold / accumulation targeting
# ---------------------------------------------------------------------------
def setup_account_with_points(target_points, nursery_overrides=None):
    """Create an account and seed it to exactly `target_points` redeemable balance
    via a single fulfilled STANDARD order whose net_total == target_points*100 cents.

    Requires the nursery's gold threshold to be high enough that the account stays
    STANDARD (caller controls via nursery_overrides). Returns dict with nursery,
    account, product, lot.
    """
    nursery = create_nursery(**(nursery_overrides or {"gold_tier_threshold_points": 1000000}))
    account = create_account(nursery["id"])
    # net = target_points dollars -> price the single unit at target_points*100 cents
    product = create_product(nursery["id"], sku="DG-SEED", unit_price_cents=target_points * 100)
    lot = create_released_lot(product["id"], received_qty=10, unit_cost_cents=1000)
    order = create_order(account["id"])
    add_line(order["id"], product["id"], qty=1)
    c = confirm(order["id"], order["version"])
    a = allocate(order["id"], c["version"])
    p = pay(order["id"], a["version"])
    fulfill(order["id"], p["version"])
    return {"nursery": nursery, "account": account, "product": product, "lot": lot}


def setup_b2b_credit_hold(credit_limit_cents=5000, nursery_overrides=None):
    """B2B account driven to CREDIT_HOLD: order #1 (net == credit_limit) confirmed
    then charged on-account so outstanding == credit_limit. Returns dict with
    nursery, account, product, order (the on-account order), order_version.
    """
    nursery = create_nursery(**(nursery_overrides or {}))
    account = create_account(
        nursery["id"], account_type="LANDSCAPER_B2B",
        display_name="Acme Land", credit_limit_cents=credit_limit_cents,
    )
    product = create_product(nursery["id"], sku="DG-CR", unit_price_cents=credit_limit_cents)
    order = create_order(account["id"])
    add_line(order["id"], product["id"], qty=1)
    c = confirm(order["id"], order["version"])
    charged = charge_account(order["id"], c["version"])
    return {
        "nursery": nursery,
        "account": account,
        "product": product,
        "order": charged,
        "order_version": charged["version"],
    }


# ---------------------------------------------------------------------------
# Special orders
# ---------------------------------------------------------------------------
def create_special_order(account_id, product_id, requested_qty=5, quoted_unit_cost_cents=1000) -> dict:
    return get_success_data(
        api_client.create_special_order(
            account_id,
            F.create_special_order_payload(product_id, requested_qty=requested_qty,
                                           quoted_unit_cost_cents=quoted_unit_cost_cents),
            CLERK,
        )
    )


def setup_approved_special_order(requested_qty=5, quoted_unit_cost_cents=1000):
    """B2B account + product + special order approved. Returns dict with
    nursery, account, product, special_order (APPROVED)."""
    nursery = create_nursery()
    account = create_account(
        nursery["id"], account_type="LANDSCAPER_B2B",
        display_name="Acme Land", credit_limit_cents=100000,
    )
    product = create_live_plant(nursery["id"], sku="PL-SO")
    so = create_special_order(account["id"], product["id"],
                              requested_qty=requested_qty, quoted_unit_cost_cents=quoted_unit_cost_cents)
    approved = get_success_data(api_client.approve_special_order(so["id"], INV))
    return {"nursery": nursery, "account": account, "product": product, "special_order": approved}


# ---------------------------------------------------------------------------
# Deliveries
# ---------------------------------------------------------------------------
def book_delivery(order_id, vehicle_id, window_start, window_end) -> dict:
    return get_success_data(
        api_client.create_delivery(
            order_id, F.create_delivery_payload(vehicle_id, window_start, window_end), INV
        )
    )


# ---------------------------------------------------------------------------
# Warranty claims
# ---------------------------------------------------------------------------
def file_claim(line_id, claim_qty=1, resolution="REPLACEMENT") -> dict:
    return get_success_data(
        api_client.create_warranty_claim(
            line_id, F.create_warranty_claim_payload(claim_qty=claim_qty, resolution=resolution), CLERK
        )
    )
