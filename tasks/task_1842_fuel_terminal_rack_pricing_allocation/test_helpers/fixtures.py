"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server with an empty database).
Lenient get_success_data is used internally so setup failures surface as
clear "Setup failed" errors instead of confusing assertion failures.

All roles use opaque operator ids (PRD §2.1), so the shared TEST_USERS
constants are threaded everywhere; no ownership-gated calls exist.
"""
from typing import Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_CLOCK_ISO, TEST_DEFAULTS, TEST_EFFECTIVE_DATE
from .factories import (
    create_allocation_notice_payload,
    create_customer_payload,
    create_exchange_agreement_payload,
    create_lifting_right_payload,
    create_lifting_ticket_payload,
    create_price_schedule_payload,
    create_product_payload,
    create_supply_contract_payload,
    create_tax_rule_payload,
    create_terminal_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
PRICE = TEST_USERS["rack_price_analyst_headers"]
ALLOC = TEST_USERS["allocation_manager_headers"]
OPER = TEST_USERS["terminal_operator_headers"]
EXCH = TEST_USERS["exchange_coordinator_headers"]
CREDIT = TEST_USERS["credit_analyst_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
CONTRACT = TEST_USERS["contract_admin_headers"]

HIGH_CREDIT = TEST_DEFAULTS["CREDIT_LIMIT_CENTS"]


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = TEST_CLOCK_ISO) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------

def create_terminal(**overrides) -> dict:
    return get_success_data(
        api_client.create_terminal(create_terminal_payload(**overrides), ADMIN),
        201,
    )


def get_terminal(terminal_id: str) -> dict:
    return get_success_data(api_client.get_terminal(terminal_id, ADMIN))


def create_product(**overrides) -> dict:
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), ADMIN),
        201,
    )


def create_customer(credit_limit_cents: int = HIGH_CREDIT, **overrides) -> dict:
    payload = create_customer_payload(
        credit_limit_cents=credit_limit_cents, **overrides,
    )
    return get_success_data(api_client.create_customer(payload, ADMIN), 201)


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, CREDIT))


def create_tax_rule(level: str, code: str, family: str, rate: int,
                    **overrides) -> dict:
    payload = create_tax_rule_payload(level, code, family, rate, **overrides)
    return get_success_data(api_client.create_tax_rule(payload, ADMIN), 201)


def adjust_inventory(terminal_id: str, delta_gallons: int,
                     reason: str = "init") -> dict:
    return get_success_data(
        api_client.adjust_inventory(
            terminal_id, {"delta_gallons": delta_gallons, "reason": reason}, OPER,
        )
    )


# ---------------------------------------------------------------------------
# Contracts and lifting rights
# ---------------------------------------------------------------------------

def create_active_contract(customer_id: str, **overrides) -> dict:
    payload = create_supply_contract_payload(customer_id, **overrides)
    contract = get_success_data(
        api_client.create_supply_contract(payload, CONTRACT), 201,
    )
    return get_success_data(
        api_client.activate_supply_contract(contract["id"], CONTRACT)
    )


def get_supply_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_supply_contract(contract_id, CONTRACT))


def create_lifting_right(customer_id: str, terminal_id: str, product_id: str,
                         contract_id: str, **overrides) -> dict:
    payload = create_lifting_right_payload(
        customer_id, terminal_id, product_id, contract_id, **overrides,
    )
    return get_success_data(api_client.create_lifting_right(payload, ALLOC), 201)


def get_lifting_right(right_id: str) -> dict:
    return get_success_data(api_client.get_lifting_right(right_id, ALLOC))


# ---------------------------------------------------------------------------
# Price schedules (OCC-guarded publish, PRD §2.7 / §3.3)
# ---------------------------------------------------------------------------

def create_draft_schedule(terminal_id: str, product_id: str, **overrides) -> dict:
    payload = create_price_schedule_payload(terminal_id, product_id, **overrides)
    return get_success_data(api_client.create_price_schedule(payload, PRICE), 201)


def publish_schedule(schedule_id: str, expected_terminal_version: int) -> dict:
    return get_success_data(
        api_client.publish_price_schedule(
            schedule_id,
            {"expected_terminal_version": expected_terminal_version},
            PRICE,
        )
    )


def create_published_schedule(terminal_id: str, product_id: str,
                              posted_rack_cents_per_gal: int,
                              branded_premium_cents_per_gal: int = 0,
                              effective_date: str = TEST_EFFECTIVE_DATE,
                              ) -> dict:
    """Create a DRAFT schedule and publish it against the terminal's current
    version (read fresh so the OCC guard passes). Returns the PUBLISHED row."""
    schedule = create_draft_schedule(
        terminal_id, product_id,
        effective_date=effective_date,
        posted_rack_cents_per_gal=posted_rack_cents_per_gal,
        branded_premium_cents_per_gal=branded_premium_cents_per_gal,
    )
    version = get_terminal(terminal_id)["version"]
    return publish_schedule(schedule["id"], version)


# ---------------------------------------------------------------------------
# Allocation notices (OCC-guarded publish, PRD §2.7 / §3.4)
# ---------------------------------------------------------------------------

def create_draft_notice(terminal_id: str, **overrides) -> dict:
    payload = create_allocation_notice_payload(terminal_id, **overrides)
    return get_success_data(
        api_client.create_allocation_notice(payload, ALLOC), 201,
    )


def publish_notice(notice_id: str, expected_terminal_version: int) -> dict:
    return get_success_data(
        api_client.publish_allocation_notice(
            notice_id,
            {"expected_terminal_version": expected_terminal_version},
            ALLOC,
        )
    )


def create_published_notice(terminal_id: str, total_pool_gallons: int,
                            allocation_method: str = "PRO_RATA",
                            effective_date: str = TEST_EFFECTIVE_DATE,
                            ) -> dict:
    """Create a DRAFT notice and publish it against the terminal's current
    version. Returns the PUBLISHED notice."""
    notice = create_draft_notice(
        terminal_id,
        effective_date=effective_date,
        total_pool_gallons=total_pool_gallons,
        allocation_method=allocation_method,
    )
    version = get_terminal(terminal_id)["version"]
    return publish_notice(notice["id"], version)


# ---------------------------------------------------------------------------
# Lifting tickets
# ---------------------------------------------------------------------------

def reserve_ticket(lifting_right_id: str, requested_gallons: int,
                   branded: bool = False,
                   additive_package_code: Optional[str] = None) -> dict:
    payload = create_lifting_ticket_payload(
        lifting_right_id, requested_gallons,
        branded=branded, additive_package_code=additive_package_code,
    )
    return get_success_data(api_client.create_lifting_ticket(payload, OPER), 201)


def get_lifting_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.get_lifting_ticket(ticket_id, OPER))


def post_bol(ticket_id: str) -> dict:
    return get_success_data(api_client.post_bol(ticket_id, OPER))


def create_posted_ticket(lifting_right_id: str, requested_gallons: int,
                         branded: bool = False,
                         additive_package_code: Optional[str] = None) -> dict:
    """Reserve then post a ticket straight through to BOL_ISSUED."""
    ticket = reserve_ticket(
        lifting_right_id, requested_gallons,
        branded=branded, additive_package_code=additive_package_code,
    )
    return post_bol(ticket["id"])


# ---------------------------------------------------------------------------
# Composite scenario builders
# ---------------------------------------------------------------------------

def setup_liftable_right(
    state_code: str = "TX",
    county_code: str = "48201",
    city_code: str = "HOU",
    terminal_code: str = "T-01",
    product_family: str = "DIESEL",
    product_code: str = "ULSD",
    is_brandable: bool = False,
    credit_limit_cents: int = HIGH_CREDIT,
    pricing_tier: str = "RACK",
    volume_commitment_gallons: int = TEST_DEFAULTS["VOLUME_COMMITMENT_GALLONS"],
    daily_ratable_gallons: int = TEST_DEFAULTS["DAILY_RATABLE_GALLONS"],
    inventory_gallons: Optional[int] = None,
    tax_rules: Sequence[Tuple[str, str, str, int]] = (),
    posted_rack_cents_per_gal: Optional[int] = None,
    branded_premium_cents_per_gal: int = 0,
    effective_date: str = TEST_EFFECTIVE_DATE,
    clock_iso: str = TEST_CLOCK_ISO,
) -> Dict:
    """Full liftable scenario: logical clock set, terminal, product, customer,
    an ACTIVE supply contract, an ACTIVE lifting right, optional tax rules,
    optional starting inventory, and an optional PUBLISHED price schedule for
    the effective date.

    `tax_rules` entries are (jurisdiction_level, jurisdiction_code,
    product_family, rate_cents_per_gal) tuples.
    Returns a dict keyed by entity name.
    """
    set_clock(clock_iso)
    terminal = create_terminal(
        terminal_code=terminal_code, state_code=state_code,
        county_code=county_code, city_code=city_code,
    )
    product = create_product(
        product_code=product_code, product_family=product_family,
        is_brandable=is_brandable,
    )
    customer = create_customer(credit_limit_cents=credit_limit_cents)
    contract = create_active_contract(
        customer["id"],
        pricing_tier=pricing_tier,
        volume_commitment_gallons=volume_commitment_gallons,
    )
    right = create_lifting_right(
        customer["id"], terminal["id"], product["id"], contract["id"],
        daily_ratable_gallons=daily_ratable_gallons,
    )
    rules = [
        create_tax_rule(level, code, family, rate)
        for (level, code, family, rate) in tax_rules
    ]
    if inventory_gallons is not None:
        terminal = adjust_inventory(terminal["id"], inventory_gallons)
    schedule = None
    if posted_rack_cents_per_gal is not None:
        schedule = create_published_schedule(
            terminal["id"], product["id"], posted_rack_cents_per_gal,
            branded_premium_cents_per_gal=branded_premium_cents_per_gal,
            effective_date=effective_date,
        )
        terminal = get_terminal(terminal["id"])
    return {
        "terminal": terminal,
        "product": product,
        "customer": customer,
        "contract": contract,
        "right": right,
        "tax_rules": rules,
        "schedule": schedule,
    }


def setup_terminal_with_rights(
    ratables: Sequence[int],
    state_code: str = "TX",
    county_code: str = "48201",
    city_code: str = "HOU",
    terminal_code: str = "T-01",
    product_family: str = "DIESEL",
    product_code: str = "ULSD",
    credit_limit_cents: int = HIGH_CREDIT,
    clock_iso: str = TEST_CLOCK_ISO,
) -> Dict:
    """Terminal + product + N customers, each with an ACTIVE contract and an
    ACTIVE lifting right at the terminal, created in ratable order so
    created_at ASC matches list position. Returns terminal, product, and the
    parallel lists customers / contracts / rights."""
    set_clock(clock_iso)
    terminal = create_terminal(
        terminal_code=terminal_code, state_code=state_code,
        county_code=county_code, city_code=city_code,
    )
    product = create_product(
        product_code=product_code, product_family=product_family,
        is_brandable=False,
    )
    customers: List[dict] = []
    contracts: List[dict] = []
    rights: List[dict] = []
    for i, ratable in enumerate(ratables):
        customer = create_customer(
            credit_limit_cents=credit_limit_cents,
            customer_code=f"CUST-{i + 1}",
        )
        contract = create_active_contract(customer["id"])
        right = create_lifting_right(
            customer["id"], terminal["id"], product["id"], contract["id"],
            daily_ratable_gallons=ratable,
        )
        customers.append(customer)
        contracts.append(contract)
        rights.append(right)
    return {
        "terminal": terminal,
        "product": product,
        "customers": customers,
        "contracts": contracts,
        "rights": rights,
    }
