"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(the test runner restarts the server before every test, so each test starts
against an empty database, with the logical clock at the 2026-08-01 default).
Setup calls use the lenient get_success_data() validator so failures surface
as clear "Setup step failed" errors.

Identity threading: after creating an Account, every Account-role call that is
ownership-gated uses make_account_headers(account["id"]) — never the shared
TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client as _default_api
from .constants import DEFAULT_PICKUP_SLOT, TIER_ELITE_CENTS, TIER_PREMIER_CENTS
from .factories import (
    create_account_payload,
    create_branch_payload,
    create_order_payload,
    create_product_payload,
    create_rma_payload,
    create_seasonal_commitment_payload,
    create_seasonal_program_payload,
    create_service_center_payload,
    create_stock_lot_payload,
    create_warranty_claim_payload,
    order_line,
)
from .test_users import TEST_USERS, make_account_headers

MGR = TEST_USERS["branch_manager_headers"]
COUNTER = TEST_USERS["counter_rep_headers"]
ROUTE = TEST_USERS["route_dispatcher_headers"]
WAREHOUSE = TEST_USERS["warehouse_lead_headers"]


def _api(api):
    return api or _default_api


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601, api=None):
    api = _api(api)
    resp = api.set_clock({"to_iso8601": to_iso8601}, MGR)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 0: single-entity creators (return parsed response data)
# ---------------------------------------------------------------------------

def make_branch(api=None, **overrides):
    api = _api(api)
    resp = api.create_branch(create_branch_payload(**overrides), MGR)
    return get_success_data(resp)


def make_account(api=None, **overrides):
    api = _api(api)
    resp = api.create_account(create_account_payload(**overrides), MGR)
    return get_success_data(resp)


def make_product(api=None, **overrides):
    api = _api(api)
    resp = api.create_product(create_product_payload(**overrides), MGR)
    return get_success_data(resp)


def make_lot(api=None, branch_id=None, product_id=None, **overrides):
    api = _api(api)
    resp = api.create_stock_lot(
        create_stock_lot_payload(branch_id, product_id, **overrides), WAREHOUSE
    )
    return get_success_data(resp)


def make_program(api=None, branch_id=None, **overrides):
    """Create a seasonal program in DRAFT."""
    api = _api(api)
    resp = api.create_seasonal_program(
        create_seasonal_program_payload(branch_id, **overrides), MGR
    )
    return get_success_data(resp)


def open_program(program_id, api=None):
    """DRAFT -> OPEN. Returns the opened program (with its new version)."""
    api = _api(api)
    resp = api.open_seasonal_program(program_id, MGR)
    return get_success_data(resp)


def program_version(program_id, api=None) -> int:
    api = _api(api)
    return get_success_data(api.get_seasonal_program(program_id, MGR))["version"]


def make_commitment(program_id, account_id, committed_units,
                    expected_program_version=None, api=None):
    """Create a COMMITTED commitment; reads the program version fresh when the
    caller does not pin one."""
    api = _api(api)
    if expected_program_version is None:
        expected_program_version = program_version(program_id, api)
    resp = api.create_seasonal_commitment(
        create_seasonal_commitment_payload(
            program_id, account_id, committed_units, expected_program_version
        ),
        MGR,
    )
    return get_success_data(resp)


def make_open_program_with_commitment(branch_id, account_id, committed_units,
                                      api=None, **program_overrides):
    """Program created + opened + one commitment recorded. Returns (program, commitment)."""
    api = _api(api)
    program = make_program(api, branch_id=branch_id, **program_overrides)
    program = open_program(program["id"], api)
    commitment = make_commitment(program["id"], account_id, committed_units, api=api)
    return program, commitment


def make_service_center(api=None, **overrides):
    api = _api(api)
    resp = api.create_service_center(create_service_center_payload(**overrides), MGR)
    return get_success_data(resp)


def make_claim(api=None, account_id=None, product_id=None, **overrides):
    api = _api(api)
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(account_id, product_id, **overrides), MGR
    )
    return get_success_data(resp)


def make_claim_under_review(api=None, account_id=None, product_id=None, **overrides):
    """Claim submitted then moved SUBMITTED -> UNDER_REVIEW."""
    api = _api(api)
    claim = make_claim(api, account_id=account_id, product_id=product_id, **overrides)
    resp = api.start_claim_review(claim["id"], MGR)
    return get_success_data(resp)


def make_rma(api=None, account_id=None, order_id=None, product_id=None,
             lot_id=None, qty=1, reason="OVERSTOCK", **overrides):
    api = _api(api)
    resp = api.create_return_authorization(
        create_rma_payload(account_id, order_id, product_id, lot_id, qty, reason, **overrides),
        MGR,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: catalog quartet + draft orders
# ---------------------------------------------------------------------------

def setup_branch_account_product_lot(api=None, branch_over=None, account_over=None,
                                     product_over=None, lot_over=None):
    """Branch + account + product + one stock lot. Returns the four dicts."""
    api = _api(api)
    branch = make_branch(api, **(branch_over or {}))
    account = make_account(api, **(account_over or {}))
    product = make_product(api, **(product_over or {}))
    lot = make_lot(api, branch_id=branch["id"], product_id=product["id"], **(lot_over or {}))
    return branch, account, product, lot


def make_order(api=None, branch_id=None, account_id=None, channel="WILL_CALL",
               lines=None, headers=None, **overrides):
    """Create a DRAFT order with embedded lines. Default actor follows the
    channel (CounterRep for WILL_CALL, RouteDispatcher for ROUTE_DELIVERY)."""
    api = _api(api)
    if headers is None:
        headers = COUNTER if channel == "WILL_CALL" else ROUTE
    resp = api.create_order(
        create_order_payload(branch_id, account_id, channel=channel, lines=lines, **overrides),
        headers,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: order lifecycle
# ---------------------------------------------------------------------------

def branch_version(branch_id, api=None) -> int:
    api = _api(api)
    return get_success_data(api.get_branch(branch_id, MGR))["version"]


def confirm_order(order_id, branch_id, api=None, headers=None):
    """Confirm a DRAFT order against the branch's current version (OCC)."""
    api = _api(api)
    version = branch_version(branch_id, api)
    if headers is None:
        order = get_success_data(api.get_order(order_id, MGR))
        headers = COUNTER if order["channel"] == "WILL_CALL" else ROUTE
    resp = api.confirm_order(order_id, {"expected_branch_version": version}, headers)
    return get_success_data(resp)


def create_confirmed_order(api=None, branch_id=None, account_id=None,
                           channel="WILL_CALL", lines=None, headers=None, **overrides):
    """Draft + confirm. Returns the CONFIRMED order."""
    api = _api(api)
    order = make_order(api, branch_id=branch_id, account_id=account_id,
                       channel=channel, lines=lines, headers=headers, **overrides)
    return confirm_order(order["id"], branch_id, api, headers)


def invoice_order(order_id, api=None):
    api = _api(api)
    return get_success_data(api.invoice_order(order_id, MGR))


def mark_loaded(order_id, api=None):
    api = _api(api)
    return get_success_data(api.mark_order_loaded(order_id, WAREHOUSE))


def pay_order(order_id, api=None, headers=None):
    api = _api(api)
    return get_success_data(api.pay_order(order_id, headers or MGR))


def complete_order(order_id, channel="WILL_CALL", api=None):
    api = _api(api)
    headers = COUNTER if channel == "WILL_CALL" else ROUTE
    return get_success_data(api.complete_order(order_id, headers))


def complete_order_fully(order_id, channel="WILL_CALL", api=None):
    """CONFIRMED -> invoice -> mark-loaded -> pay -> complete. Returns final order."""
    api = _api(api)
    invoice_order(order_id, api)
    mark_loaded(order_id, api)
    pay_order(order_id, api)
    return complete_order(order_id, channel, api)


def create_completed_order(api=None, branch_id=None, account_id=None,
                           channel="WILL_CALL", lines=None, **overrides):
    """Full lifecycle to COMPLETED/PAID. Returns the completed order."""
    api = _api(api)
    order = create_confirmed_order(api, branch_id=branch_id, account_id=account_id,
                                   channel=channel, lines=lines, **overrides)
    return complete_order_fully(order["id"], channel, api)


# ---------------------------------------------------------------------------
# Tier 3: tier seeding (account volume ledger)
# ---------------------------------------------------------------------------

def seed_account_tier(account_id, branch_id, target_tier="PREMIER", api=None,
                      pickup_slot=DEFAULT_PICKUP_SLOT):
    """Drive an account to a tier by confirming + invoicing one order whose
    subtotal lands exactly on the tier threshold (PRO-tier pricing: the account
    starts at PRO, so the seed subtotal equals the product base price)."""
    api = _api(api)
    amount = TIER_PREMIER_CENTS if target_tier == "PREMIER" else TIER_ELITE_CENTS
    seed_product = make_product(api, product_family="EQUIPMENT", base_price_cents=amount)
    make_lot(api, branch_id=branch_id, product_id=seed_product["id"], qty_on_hand=1)
    seed_order = make_order(api, branch_id=branch_id, account_id=account_id,
                            channel="WILL_CALL",
                            lines=[order_line(seed_product["id"], 1)],
                            requested_pickup_slot=pickup_slot)
    confirm_order(seed_order["id"], branch_id, api)
    invoice_order(seed_order["id"], api)
    return seed_order


# ---------------------------------------------------------------------------
# Tier 4: backorder scenarios
# ---------------------------------------------------------------------------

def list_backorders(api=None, **params):
    api = _api(api)
    data, _meta = validate_paginated(api.list_backorder_requests(WAREHOUSE, params=params))
    return data


def get_single_backorder(branch_id, product_id=None, status="OPEN", api=None):
    """Fetch the single backorder matching the filters; asserts exactly one."""
    api = _api(api)
    params = {"branch_id": branch_id, "status": status}
    if product_id is not None:
        params["product_id"] = product_id
    rows = list_backorders(api, **params)
    assert len(rows) == 1, f"expected exactly one {status} backorder, got {len(rows)}"
    return rows[0]


def confirm_short_order(api=None, branch_id=None, account_id=None, product_id=None,
                        qty=1, channel="WILL_CALL", headers=None, **overrides):
    """Confirm an order whose line cannot be fully covered, birthing an OPEN
    backorder. Returns (order, backorder)."""
    api = _api(api)
    order = create_confirmed_order(api, branch_id=branch_id, account_id=account_id,
                                   channel=channel,
                                   lines=[order_line(product_id, qty)],
                                   headers=headers, **overrides)
    backorder = get_single_backorder(branch_id, product_id, "OPEN", api)
    return order, backorder


def lot_version(lot_id, api=None) -> int:
    api = _api(api)
    return get_success_data(api.get_stock_lot(lot_id, WAREHOUSE))["version"]


def get_order_lines(order_id, api=None, headers=None):
    api = _api(api)
    data, _meta = validate_paginated(api.list_order_lines(order_id, headers or COUNTER))
    return data
