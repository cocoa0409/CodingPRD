"""Composite setup helpers.

Each test runs against a freshly-restarted, empty server, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Fixtures use
get_success_data() (lenient) so setup failures surface as clear "Setup failed".

Role/identity threading: the only entity-backed role is Customer, used solely in
RBAC tests, so fixtures route every mutating call through the opaque operator
headers below per the role ownership rules in PRD §2.1.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_dealership_payload,
    create_customer_payload,
    create_unit_payload,
    create_deal_payload,
    appraise_trade_payload,
    create_pdi_inspection_payload,
    create_service_bay_payload,
    create_service_order_payload,
    create_part_item_payload,
    create_part_reservation_payload,
    create_warranty_plan_payload,
    create_appointment_payload,
    create_storage_slot_payload,
    create_recall_campaign_payload,
)

MGR = TEST_USERS["dealer_manager_headers"]
SALES = TEST_USERS["sales_agent_headers"]
SVC = TEST_USERS["service_advisor_headers"]

# Module-level counters so independently-created entities never collide on the
# per-dealership unique fields (vin / email / sku / campaign_code).
_vin_seq = itertools.count(1)
_email_seq = itertools.count(1)
_sku_seq = itertools.count(1)
_campaign_seq = itertools.count(1)


def _uniq_vin():
    return f"VIN-{next(_vin_seq):06d}"


def _uniq_email():
    return f"user{next(_email_seq):06d}@x.com"


def _uniq_sku():
    return f"SKU-{next(_sku_seq):06d}"


def _uniq_campaign():
    return f"RC-{next(_campaign_seq):06d}"


# ===========================================================================
# Tier 0: primitives
# ===========================================================================
def create_dealership(**overrides):
    """Create a dealership. Returns the dealership dict."""
    return get_success_data(
        api_client.create_dealership(create_dealership_payload(**overrides), MGR)
    )


def create_customer(dealership_id, **overrides):
    """Create a customer. Auto-assigns a unique email unless one is given."""
    overrides.setdefault("email", _uniq_email())
    return get_success_data(
        api_client.create_customer(create_customer_payload(dealership_id, **overrides), SALES)
    )


def create_unit(dealership_id, **overrides):
    """Create a unit. Auto-assigns a unique vin unless one is given."""
    overrides.setdefault("vin", _uniq_vin())
    return get_success_data(
        api_client.create_unit(create_unit_payload(dealership_id, **overrides), SALES)
    )


def create_part_item(dealership_id, **overrides):
    """Create a part item. Auto-assigns a unique sku unless one is given."""
    overrides.setdefault("sku", _uniq_sku())
    return get_success_data(
        api_client.create_part_item(create_part_item_payload(dealership_id, **overrides), SVC)
    )


def create_service_bay(dealership_id, **overrides):
    """Create a service bay. Returns the bay dict."""
    return get_success_data(
        api_client.create_service_bay(create_service_bay_payload(dealership_id, **overrides), SVC)
    )


def create_warranty_plan(dealership_id, unit_id, customer_id, **overrides):
    """Create a warranty plan. Returns the plan dict."""
    return get_success_data(
        api_client.create_warranty_plan(
            create_warranty_plan_payload(dealership_id, unit_id, customer_id, **overrides), SALES
        )
    )


def create_recall_campaign(dealership_id, **overrides):
    """Open a recall campaign. Auto-assigns a unique campaign_code unless given."""
    overrides.setdefault("campaign_code", _uniq_campaign())
    return get_success_data(
        api_client.create_recall_campaign(
            create_recall_campaign_payload(dealership_id, **overrides), MGR
        )
    )


# ===========================================================================
# Tier 1: base sales setup (dealership + customer + stock unit)
# ===========================================================================
def setup_dealership_customer_unit(dealer_overrides=None, customer_overrides=None,
                                   unit_overrides=None):
    """Active base: one dealership, one customer, one STOCK unit.
    Returns (dealership, customer, unit). Unit is freshly read so its version is
    the value to pass as expected_unit_version on the first deal/storage write."""
    dealer = create_dealership(**(dealer_overrides or {}))
    customer = create_customer(dealer["id"], **(customer_overrides or {}))
    unit = create_unit(dealer["id"], **(unit_overrides or {}))
    return dealer, customer, unit


# ===========================================================================
# Tier 2: deal lifecycle progression
# ===========================================================================
def create_deal_on_unit(dealership, customer, unit, sale_price_cents=None, **deal_overrides):
    """Create a deal placing a hold on `unit` (AVAILABLE->HELD). Returns the deal."""
    price = sale_price_cents if sale_price_cents is not None else unit["list_price_cents"]
    payload = create_deal_payload(
        dealership["id"], unit["id"], customer["id"], price, unit["version"], **deal_overrides
    )
    return get_success_data(api_client.create_deal(payload, SALES))


def setup_held_deal(dealer_overrides=None, customer_overrides=None, unit_overrides=None,
                    sale_price_cents=None, **deal_overrides):
    """Dealership + customer + unit + one DRAFT deal holding the unit.
    Returns (dealership, customer, unit, deal)."""
    dealer, customer, unit = setup_dealership_customer_unit(
        dealer_overrides, customer_overrides, unit_overrides
    )
    deal = create_deal_on_unit(dealer, customer, unit, sale_price_cents, **deal_overrides)
    return dealer, customer, unit, deal


def setup_quoted_deal(dealer_overrides=None, customer_overrides=None, unit_overrides=None,
                      sale_price_cents=None, **deal_overrides):
    """A deal advanced to QUOTED. Returns (dealership, customer, unit, deal_after_quote)."""
    dealer, customer, unit, deal = setup_held_deal(
        dealer_overrides, customer_overrides, unit_overrides, sale_price_cents, **deal_overrides
    )
    quoted = get_success_data(api_client.quote_deal(deal["id"], SALES))
    return dealer, customer, unit, quoted


def setup_deal_in_walkthrough(dealer_overrides=None, customer_overrides=None,
                              unit_overrides=None, sale_price_cents=None, **deal_overrides):
    """A cash deal driven to WALKTHROUGH with a passing PDI.
    Path: create -> quote (CASH) -> start-pdi -> pdi PASS -> WALKTHROUGH.
    Returns (dealership, customer, unit, deal_in_walkthrough)."""
    dealer, customer, unit, quoted = setup_quoted_deal(
        dealer_overrides, customer_overrides, unit_overrides, sale_price_cents, **deal_overrides
    )
    deal_id = quoted["id"]
    get_success_data(api_client.start_pdi(deal_id, SALES))
    get_success_data(
        api_client.create_pdi_inspection(
            create_pdi_inspection_payload(dealer["id"], deal_id, 0), SVC
        )
    )
    walk = get_success_data(api_client.get_deal(deal_id, SALES))
    return dealer, customer, unit, walk


# ===========================================================================
# Tier 3: service order lifecycle
# ===========================================================================
def create_service_order(dealership, unit, customer, **overrides):
    """Open a service order (OPEN). Returns the order dict."""
    payload = create_service_order_payload(dealership["id"], unit["id"], customer["id"], **overrides)
    return get_success_data(api_client.create_service_order(payload, SVC))


def setup_started_service_order(dealer_overrides=None, so_overrides=None):
    """Dealership + customer + unit + a service order started to IN_PROGRESS.
    Returns (dealership, customer, unit, service_order)."""
    dealer, customer, unit = setup_dealership_customer_unit(dealer_overrides)
    so = create_service_order(dealer, unit, customer, **(so_overrides or {}))
    started = get_success_data(api_client.start_service_order(so["id"], SVC))
    return dealer, customer, unit, started


def reserve_part(service_order_id, part_item_id, quantity):
    """Reserve `quantity` of a part against the order. Returns the reservation dict."""
    return get_success_data(
        api_client.create_part_reservation(
            create_part_reservation_payload(service_order_id, part_item_id, quantity), SVC
        )
    )


def setup_warranty_so_in_progress(plan_cap_cents, deductible_cents, labor_hours, labor_rate_cents,
                                  part_price_cents, part_qty_on_hand, reserve_qty):
    """EXTENDED warranty plan + IN_PROGRESS warranty SO with one part reserved.
    Returns (dealership, customer, unit, plan, part, service_order)."""
    dealer, customer, unit = setup_dealership_customer_unit()
    plan = create_warranty_plan(
        dealer["id"], unit["id"], customer["id"],
        plan_kind="EXTENDED", coverage_cap_cents=plan_cap_cents, deductible_cents=deductible_cents,
    )
    part = create_part_item(dealer["id"], unit_price_cents=part_price_cents, qty_on_hand=part_qty_on_hand)
    so = create_service_order(
        dealer, unit, customer,
        labor_hours=labor_hours, labor_rate_cents=labor_rate_cents,
        is_warranty=True, warranty_plan_id=plan["id"],
    )
    get_success_data(api_client.start_service_order(so["id"], SVC))
    reserve_part(so["id"], part["id"], reserve_qty)
    return dealer, customer, unit, plan, part, so


def setup_nonwarranty_so_in_progress(labor_hours, labor_rate_cents, part_price_cents,
                                     part_qty_on_hand, reserve_qty):
    """Non-warranty IN_PROGRESS SO with one part reserved.
    Returns (dealership, customer, unit, part, service_order)."""
    dealer, customer, unit = setup_dealership_customer_unit(
        dealer_overrides={"sales_tax_rate_bps": 0}
    )
    part = create_part_item(dealer["id"], unit_price_cents=part_price_cents, qty_on_hand=part_qty_on_hand)
    so = create_service_order(
        dealer, unit, customer, labor_hours=labor_hours, labor_rate_cents=labor_rate_cents
    )
    get_success_data(api_client.start_service_order(so["id"], SVC))
    reserve_part(so["id"], part["id"], reserve_qty)
    return dealer, customer, unit, part, so


# ===========================================================================
# Tier 4: financing progression
# ===========================================================================
def setup_finance_requested_deal(credit_tier, list_price_cents, sale_price_cents,
                                 term_months, down_payment_cents=0):
    """Deal quoted then finance REQUESTED (decision pending).
    Returns (dealership, customer, unit, deal_id)."""
    dealer, customer, unit = setup_dealership_customer_unit(
        customer_overrides={"credit_tier": credit_tier},
        unit_overrides={"list_price_cents": list_price_cents},
    )
    deal = create_deal_on_unit(
        dealer, customer, unit, sale_price_cents,
        down_payment_cents=down_payment_cents, term_months=term_months,
    )
    get_success_data(api_client.quote_deal(deal["id"], SALES))
    get_success_data(api_client.request_finance(deal["id"], SALES))
    return dealer, customer, unit, deal["id"]


# ===========================================================================
# Tier 5: storage progression
# ===========================================================================
def book_storage_slot(dealership, unit, customer, start_utc, end_utc, expected_unit_version,
                      **overrides):
    """Book a storage slot for `unit`. Returns the slot dict."""
    payload = create_storage_slot_payload(
        dealership["id"], unit["id"], customer["id"], start_utc, end_utc, expected_unit_version,
        **overrides
    )
    return get_success_data(api_client.create_storage_slot(payload, SVC))


def setup_active_storage_slot(start_utc, end_utc, daily_rate_cents, winterized=False):
    """A storage slot booked then activated (ACTIVE).
    Returns (dealership, customer, unit, slot)."""
    dealer, customer, unit = setup_dealership_customer_unit()
    slot = book_storage_slot(
        dealer, unit, customer, start_utc, end_utc, unit["version"],
        daily_rate_cents=daily_rate_cents, winterized=winterized,
    )
    active = get_success_data(api_client.activate_storage_slot(slot["id"], SVC))
    return dealer, customer, unit, active
