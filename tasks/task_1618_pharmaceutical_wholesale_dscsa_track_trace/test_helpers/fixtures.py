"""Composite setup helpers.

Multi-step preconditions (licensed customers, confirmed/allocated/shipped
orders, shortage scenarios, quarantined investigations) are built here so tests
focus on assertions. All helpers use the lenient get_success_data() validator
so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CASE_EXPIRY,
    DEFAULT_CLOCK,
    HIGH_CREDIT_LIMIT,
    LICENSE_VALID_FROM,
    LICENSE_VALID_TO,
)
from .factories import (
    create_allocation_policy_payload,
    create_case_payload,
    create_chargeback_claim_payload,
    create_epcis_event_payload,
    create_investigation_payload,
    create_license_payload,
    create_order_line_payload,
    create_product_payload,
    create_purchase_order_payload,
    create_return_authorization_payload,
    create_trading_partner_payload,
    create_unit_payload,
)
from .test_users import TEST_USERS, make_qa_lead_headers

OM = TEST_USERS["order_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
WH = TEST_USERS["warehouse_operator_headers"]
QA = TEST_USERS["qa_lead_headers"]
BC = TEST_USERS["billing_clerk_headers"]
CA_ADMIN = TEST_USERS["contract_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + primitive creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK):
    """Pin the logical clock (PRD §2.5)."""
    resp = api_client.set_logical_clock(to_iso8601, OM)
    return get_success_data(resp)


def create_partner(**overrides):
    payload = create_trading_partner_payload(**overrides)
    resp = api_client.create_trading_partner(payload, OM)
    return get_success_data(resp)


def create_customer(name: str = "Test Customer", credit_limit_cents: int = HIGH_CREDIT_LIMIT,
                    **overrides):
    return create_partner(partner_name=name, partner_kind="CUSTOMER",
                          credit_limit_cents=credit_limit_cents, **overrides)


def create_supplier(name: str = "Test Supplier", **overrides):
    return create_partner(partner_name=name, partner_kind="SUPPLIER",
                          credit_limit_cents=0, **overrides)


def create_license(partner_id: str, state_code: str = "CA", license_scope: str = "FULL",
                   valid_from: str = LICENSE_VALID_FROM, valid_to: str = LICENSE_VALID_TO,
                   **overrides):
    payload = create_license_payload(partner_id, state_code=state_code,
                                     license_scope=license_scope,
                                     valid_from=valid_from, valid_to=valid_to, **overrides)
    resp = api_client.create_partner_state_license(payload, CO)
    return get_success_data(resp)


def setup_customer_with_license(name: str = "Customer",
                                credit_limit_cents: int = HIGH_CREDIT_LIMIT,
                                state_code: str = "CA", license_scope: str = "FULL",
                                **license_overrides):
    """Customer partner + ACTIVE state license. Returns (customer, license)."""
    customer = create_customer(name=name, credit_limit_cents=credit_limit_cents)
    lic = create_license(customer["id"], state_code=state_code, license_scope=license_scope,
                         **license_overrides)
    return customer, lic


def create_product(**overrides):
    payload = create_product_payload(**overrides)
    resp = api_client.create_product(payload, OM)
    return get_success_data(resp)


def declare_shortage(product_id: str):
    resp = api_client.declare_shortage(product_id, OM)
    return get_success_data(resp)


def open_allocation_policy(product_id: str, pool_units: int, policy_mode: str = "PRO_RATA",
                           min_guarantee_units: int = 0):
    payload = create_allocation_policy_payload(
        product_id, pool_units=pool_units, policy_mode=policy_mode,
        min_guarantee_units=min_guarantee_units)
    resp = api_client.create_allocation_policy(payload, OM)
    return get_success_data(resp)


def create_case(product_id: str, expiry_date: str = CASE_EXPIRY, **overrides):
    payload = create_case_payload(product_id, expiry_date=expiry_date, **overrides)
    resp = api_client.create_serialized_case(payload, WH)
    return get_success_data(resp)


def create_unit(case_id: str, **overrides):
    payload = create_unit_payload(case_id, **overrides)
    resp = api_client.create_serialized_unit(payload, WH)
    return get_success_data(resp)


def create_case_with_units(product_id: str, num_units: int = 1, **case_overrides):
    """COMMISSIONED case with N aggregated COMMISSIONED units. Returns (case, units)."""
    case = create_case(product_id, **case_overrides)
    units = [create_unit(case["id"]) for _ in range(num_units)]
    return case, units


# ---------------------------------------------------------------------------
# Tier 1: order lifecycle progression
# ---------------------------------------------------------------------------

def create_order(customer_id: str, ship_to_state: str = "CA", is_340b_order: bool = False):
    payload = create_purchase_order_payload(customer_id, ship_to_state=ship_to_state,
                                            is_340b_order=is_340b_order)
    resp = api_client.create_purchase_order(payload, OM)
    return get_success_data(resp)


def add_line(order_id: str, product_id: str, quantity_requested: int):
    payload = create_order_line_payload(product_id, quantity_requested=quantity_requested)
    resp = api_client.add_order_line(order_id, payload, OM)
    return get_success_data(resp)


def create_order_with_line(customer_id: str, product_id: str, quantity_requested: int,
                           ship_to_state: str = "CA", is_340b_order: bool = False):
    """DRAFT order with a single PENDING line. Returns (order, line)."""
    order = create_order(customer_id, ship_to_state=ship_to_state, is_340b_order=is_340b_order)
    line = add_line(order["id"], product_id, quantity_requested)
    return order, line


def confirm_order(order_id: str):
    """Confirm a DRAFT order. Returns the CONFIRMED order (response body)."""
    resp = api_client.confirm_order(order_id, OM)
    return get_success_data(resp)


def get_order(order_id: str):
    resp = api_client.get_purchase_order(order_id, OM)
    return get_success_data(resp)


def get_partner(partner_id: str):
    resp = api_client.get_trading_partner(partner_id, OM)
    return get_success_data(resp)


def get_policy(policy_id: str):
    resp = api_client.get_allocation_policy(policy_id, OM)
    return get_success_data(resp)


def get_case(case_id: str):
    resp = api_client.get_serialized_case(case_id, OM)
    return get_success_data(resp)


def get_unit(unit_id: str):
    resp = api_client.get_serialized_unit(unit_id, OM)
    return get_success_data(resp)


def get_investigation(investigation_id: str):
    resp = api_client.get_suspect_investigation(investigation_id, OM)
    return get_success_data(resp)


def get_claim(claim_id: str):
    resp = api_client.get_chargeback_claim(claim_id, OM)
    return get_success_data(resp)


def get_return_authorization(return_id: str):
    resp = api_client.get_return_authorization(return_id, OM)
    return get_success_data(resp)


def get_single_line(order_id: str):
    """Fetch the single order line of an order (asserts exactly one)."""
    resp = api_client.list_order_lines(order_id, OM)
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) == 1, f"Setup failed: expected 1 line, got {data}"
    return data[0]


def allocate_order(order_id: str, expected_version: int = None):
    """Run shortage allocation with OCC. When expected_version is None the
    current order version is fetched first. Returns the post-run order."""
    if expected_version is None:
        expected_version = get_order(order_id)["version"]
    resp = api_client.allocate_order(order_id, {"expected_order_version": expected_version}, OM)
    return get_success_data(resp)


def setup_confirmed_order(customer_id: str, product_id: str, quantity_requested: int,
                          is_340b_order: bool = False, ship_to_state: str = "CA"):
    """DRAFT order + one line + confirm. Returns the CONFIRMED order."""
    order, _line = create_order_with_line(customer_id, product_id, quantity_requested,
                                          ship_to_state=ship_to_state,
                                          is_340b_order=is_340b_order)
    return confirm_order(order["id"])


def setup_allocated_order(customer_id: str, product_id: str, quantity_requested: int,
                          is_340b_order: bool = False):
    """Confirmed order + allocation run. Returns the post-allocation order."""
    order = setup_confirmed_order(customer_id, product_id, quantity_requested,
                                  is_340b_order=is_340b_order)
    return allocate_order(order["id"], expected_version=order["version"])


def setup_shipped_order(customer_id: str, product_id: str, quantity_requested: int,
                        segregation_mode: str = "STANDARD", is_340b_order: bool = False):
    """Allocated order + case + ship. Returns (order, case)."""
    order = setup_allocated_order(customer_id, product_id, quantity_requested,
                                  is_340b_order=is_340b_order)
    case = create_case(product_id)
    resp = api_client.ship_order(
        order["id"], {"segregation_mode": segregation_mode, "case_ids": [case["id"]]}, WH)
    shipped = get_success_data(resp)
    return shipped, case


def setup_delivered_order(customer_id: str, product_id: str, quantity_requested: int,
                          segregation_mode: str = "STANDARD", is_340b_order: bool = False):
    """Full lifecycle through DELIVERED. Returns (order, case)."""
    shipped, case = setup_shipped_order(customer_id, product_id, quantity_requested,
                                        segregation_mode=segregation_mode,
                                        is_340b_order=is_340b_order)
    resp = api_client.deliver_order(shipped["id"], WH)
    return get_success_data(resp), case


# ---------------------------------------------------------------------------
# Tier 2: shortage scenarios
# ---------------------------------------------------------------------------

def setup_shortage_product(wac_cents: int = 1000, pool_units: int = 6,
                           policy_mode: str = "PRO_RATA", min_guarantee_units: int = 0,
                           **product_overrides):
    """Product declared SHORTAGE + OPEN allocation policy. Returns (product, policy)."""
    product = create_product(wholesale_acquisition_cost_cents=wac_cents, **product_overrides)
    declare_shortage(product["id"])
    policy = open_allocation_policy(product["id"], pool_units,
                                    policy_mode=policy_mode,
                                    min_guarantee_units=min_guarantee_units)
    return product, policy


def setup_shortage_order(product_id: str, quantity_requested: int,
                         customer_name: str = "Shortage Customer",
                         credit_limit_cents: int = HIGH_CREDIT_LIMIT,
                         is_340b_order: bool = False):
    """Licensed customer + CONFIRMED order with one line for the shortage product.
    Does NOT run allocation. Returns (customer, order) with order in CONFIRMED."""
    customer, _lic = setup_customer_with_license(name=customer_name,
                                                 credit_limit_cents=credit_limit_cents)
    order = setup_confirmed_order(customer["id"], product_id, quantity_requested,
                                  is_340b_order=is_340b_order)
    return customer, order


# ---------------------------------------------------------------------------
# Tier 3: investigations
# ---------------------------------------------------------------------------

def open_investigation(case_id: str, qa_user_id: str = "qa-opener",
                       reason: str = "suspect product"):
    payload = create_investigation_payload(case_id, opened_reason=reason)
    resp = api_client.create_suspect_investigation(payload, make_qa_lead_headers(qa_user_id))
    return get_success_data(resp)


def quarantine_investigation(investigation_id: str, qa_user_id: str):
    resp = api_client.quarantine_investigation(investigation_id, make_qa_lead_headers(qa_user_id))
    return get_success_data(resp)


def clear_investigation(investigation_id: str, qa_user_id: str):
    resp = api_client.clear_investigation(investigation_id, make_qa_lead_headers(qa_user_id))
    return get_success_data(resp)


def reopen_investigation(investigation_id: str, qa_user_id: str):
    resp = api_client.reopen_investigation(investigation_id, make_qa_lead_headers(qa_user_id))
    return get_success_data(resp)


def setup_quarantined_investigation(num_units: int = 0, qa_user_id: str = "qa-quarantine"):
    """Product + case (+N units) + OPEN investigation quarantined by qa_user_id.
    Returns (product, case, units, investigation)."""
    product = create_product()
    case, units = create_case_with_units(product["id"], num_units=num_units)
    inv = open_investigation(case["id"], qa_user_id=qa_user_id)
    inv = quarantine_investigation(inv["id"], qa_user_id)
    return product, case, units, inv


def cycle_investigation(investigation_id: str, quarantine_user: str, clear_user: str,
                        reopen_user: str):
    """One lap QUARANTINED -> CLEARED -> OPEN honoring segregation of duties.
    Assumes the investigation is currently QUARANTINED by quarantine_user.
    Returns the investigation (OPEN after the lap)."""
    clear_investigation(investigation_id, clear_user)
    return reopen_investigation(investigation_id, reopen_user)


# ---------------------------------------------------------------------------
# Tier 4: EPCIS helpers
# ---------------------------------------------------------------------------

def capture_epcis_event(event_type: str, case_id: str, sender_id: str, recipient_id: str,
                        event_time: str, headers=None, **overrides):
    payload = create_epcis_event_payload(
        case_id, sender_id, recipient_id,
        event_type=event_type, event_time=event_time, **overrides)
    resp = api_client.create_epcis_event(payload, headers or WH)
    return get_success_data(resp)


def setup_case_with_counterparties(num_units: int = 1):
    """Product + case (+units) + supplier/customer partners for event capture.
    Returns (product, case, units, supplier, recipient)."""
    product = create_product()
    case, units = create_case_with_units(product["id"], num_units=num_units)
    supplier = create_supplier(name="SupplierCo")
    recipient = create_customer(name="RecipientCo", credit_limit_cents=0)
    return product, case, units, supplier, recipient


# ---------------------------------------------------------------------------
# Tier 5: chargebacks & returns
# ---------------------------------------------------------------------------

def submit_claim(order_id: str, claimed_amount_cents: int):
    payload = create_chargeback_claim_payload(order_id, claimed_amount_cents)
    resp = api_client.create_chargeback_claim(payload, CA_ADMIN)
    return get_success_data(resp)


def lodge_return(order_id: str, product_id: str, quantity_returned: int):
    payload = create_return_authorization_payload(order_id, product_id,
                                                  quantity_returned=quantity_returned)
    resp = api_client.create_return_authorization(payload, OM)
    return get_success_data(resp)


def setup_340b_allocated_order(wac_cents: int = 10000, contract_cents: int = 7000,
                               quantity: int = 10, shortage_pool: int = None):
    """340B-contracted product + licensed customer + order confirmed & allocated.

    shortage_pool=None keeps the product NORMAL (full allocation); a pool value
    declares shortage and opens a PRO_RATA policy (min guarantee 0) of that size.
    Returns (customer, product, order)."""
    product = create_product(wholesale_acquisition_cost_cents=wac_cents,
                             is_340b_contracted=True,
                             contract_340b_price_cents=contract_cents)
    if shortage_pool is not None:
        declare_shortage(product["id"])
        open_allocation_policy(product["id"], shortage_pool,
                               policy_mode="PRO_RATA", min_guarantee_units=0)
    customer, _lic = setup_customer_with_license(name="340B Customer")
    order = setup_confirmed_order(customer["id"], product["id"], quantity, is_340b_order=True)
    order = allocate_order(order["id"], expected_version=order["version"])
    return customer, product, order


def setup_return_received(cold_chain: bool = False, quantity: int = 5,
                          wac_cents: int = 2000, credit_limit_cents: int = HIGH_CREDIT_LIMIT):
    """Delivered order (shipped with the product's segregation mode) + lodged &
    RECEIVED return for `quantity`. Returns (customer, product, order, case, ret)."""
    product = create_product(is_cold_chain=cold_chain,
                             wholesale_acquisition_cost_cents=wac_cents)
    customer, _lic = setup_customer_with_license(name="Return Customer",
                                                 credit_limit_cents=credit_limit_cents)
    segregation = "COLD_CHAIN" if cold_chain else "STANDARD"
    order, case = setup_delivered_order(customer["id"], product["id"], quantity,
                                        segregation_mode=segregation)
    ret = lodge_return(order["id"], product["id"], quantity)
    return customer, product, order, case, ret
