"""Composite setup helpers for the Musical Instrument Store API.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the database is empty before each test). Fixtures use the lenient
``get_success_data`` validator internally so a setup failure surfaces clearly.

Identity threading: the Customer role is entity-backed. After a customer is
created, every ownership-gated call performed *as that customer* uses
``make_customer_headers(customer["id"])`` — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_luthier_headers,
)
from . import factories as f

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


# --- Tier 1: primitives ------------------------------------------------------

def create_customer(credit_score: int = 700, headers=None, **overrides) -> dict:
    """Create a Customer (default actor: SalesAssociate). Returns the customer dict."""
    headers = headers if headers is not None else SA
    resp = api_client.create_customer(
        f.create_customer_payload(credit_score=credit_score, **overrides), headers
    )
    return get_success_data(resp)


def create_unit(headers=None, **overrides) -> dict:
    """Create an AVAILABLE InventoryUnit (version 1). Returns the unit dict."""
    headers = headers if headers is not None else SA
    resp = api_client.create_unit(f.create_unit_payload(**overrides), headers)
    return get_success_data(resp)


def create_reserved_unit(customer_id: str, **unit_overrides):
    """Create an AVAILABLE unit, then reserve it for ``customer_id``.

    Returns (unit_after_reserve, reserved_version).
    """
    unit = create_unit(**unit_overrides)
    resp = api_client.reserve_unit(
        unit["id"],
        f.reserve_unit_payload(customer_id, unit["version"]),
        SA,
    )
    reserved = get_success_data(resp)
    return reserved, reserved["version"]


# --- Tier 2 / 3: rental agreements ------------------------------------------

def create_active_agreement(customer_id: str, plan: str = "RENTAL",
                            unit_overrides: dict = None, agreement_overrides: dict = None):
    """Create customer-reserved unit + open an ACTIVE RentalAgreement on it.

    Returns (agreement, unit). ``plan`` is RENTAL or RENT_TO_OWN.
    """
    unit_overrides = unit_overrides or {}
    agreement_overrides = agreement_overrides or {}
    reserved, _ = create_reserved_unit(customer_id, **unit_overrides)
    resp = api_client.create_agreement(
        f.create_agreement_payload(customer_id, reserved["id"], plan=plan, **agreement_overrides),
        SA,
    )
    agreement = get_success_data(resp)
    return agreement, reserved


def setup_customer_and_active_agreement(plan: str = "RENTAL", credit_score: int = 700,
                                        unit_overrides: dict = None,
                                        agreement_overrides: dict = None):
    """Customer + reserved unit + ACTIVE agreement. Returns (customer, agreement, unit)."""
    customer = create_customer(credit_score=credit_score)
    agreement, unit = create_active_agreement(
        customer["id"], plan=plan,
        unit_overrides=unit_overrides, agreement_overrides=agreement_overrides,
    )
    return customer, agreement, unit


def post_rent_payments(agreement_id: str, customer_id: str, cycles):
    """Post one POSTED RENT payment per cycle index in ``cycles`` (as the customer)."""
    headers = make_customer_headers(customer_id)
    for cycle in cycles:
        get_success_data(
            api_client.post_rent_payment(agreement_id, f.rent_payment_payload(cycle), headers)
        )


def setup_rto_with_n_paid_months(num_months: int = 3, credit_score: int = 700,
                                 list_price_cents: int = 120000,
                                 monthly_rent_cents: int = 10000,
                                 equity_rate_pct: float = 0.50):
    """RENT_TO_OWN agreement on a reserved unit, with ``num_months`` POSTED rent
    payments (cycles 1..num_months). Returns (customer, agreement, unit).

    With the defaults (list 120000, rent 10000, equity 0.50) and 3 months paid:
    accrued_equity_cents = 15000, payoff_quote_cents = 110000.
    """
    customer = create_customer(credit_score=credit_score)
    agreement, unit = create_active_agreement(
        customer["id"], plan="RENT_TO_OWN",
        unit_overrides={
            "list_price_cents": list_price_cents,
            "monthly_rent_cents": monthly_rent_cents,
        },
        agreement_overrides={"equity_rate_pct": equity_rate_pct},
    )
    if num_months:
        post_rent_payments(agreement["id"], customer["id"], range(1, num_months + 1))
    return customer, agreement, unit


def read_agreement(agreement_id: str, customer_id: str = None) -> dict:
    """GET an agreement (recomputes derived figures). Reads as SalesAssociate by
    default; pass customer_id to read as the owning customer."""
    headers = make_customer_headers(customer_id) if customer_id else SA
    return get_success_data(api_client.get_agreement(agreement_id, headers))


def advance_cycles(agreement_id: str, cycles):
    """Advance the agreement once per cycle index in ``cycles`` (as StoreManager).
    Returns the last advance response data."""
    last = None
    for cycle in cycles:
        last = get_success_data(
            api_client.advance_cycle(agreement_id, f.advance_cycle_payload(cycle), SM)
        )
    return last


# --- Tier 2 / 4: layaway -----------------------------------------------------

def setup_open_layaway(list_price_cents: int = 60000, deposit_cents: int = 5000,
                       installments=None, restock_fee_pct: float = None,
                       credit_score: int = 700):
    """Customer + reserved unit + OPEN LayawayPlan with optional installments.

    ``installments`` is an iterable of positive amounts posted as the customer.
    Returns (customer, plan, unit).
    """
    customer = create_customer(credit_score=credit_score)
    reserved, _ = create_reserved_unit(customer["id"], list_price_cents=list_price_cents)
    overrides = {}
    if restock_fee_pct is not None:
        overrides["restock_fee_pct"] = restock_fee_pct
    resp = api_client.create_layaway(
        f.create_layaway_payload(customer["id"], reserved["id"],
                                 deposit_cents=deposit_cents, **overrides),
        SA,
    )
    plan = get_success_data(resp)
    if installments:
        cust_headers = make_customer_headers(customer["id"])
        for amount in installments:
            get_success_data(
                api_client.post_layaway_payment(plan["id"], f.layaway_payment_payload(amount), cust_headers)
            )
    return customer, plan, reserved


# --- Tier 2 / 3: repair tickets ---------------------------------------------

def create_repair_ticket(customer_id: str = None, **overrides) -> dict:
    """Open a RepairTicket (INTAKE) for a customer. Creates a customer if none given.
    Returns the ticket dict."""
    if customer_id is None:
        customer_id = create_customer()["id"]
    resp = api_client.create_ticket(f.create_ticket_payload(customer_id, **overrides), SA)
    return get_success_data(resp)


def setup_ticket_in_progress(luthier_id: str = "luthier-1", **ticket_overrides):
    """RepairTicket claimed by ``luthier_id`` -> IN_PROGRESS. Returns the ticket dict."""
    ticket = create_repair_ticket(**ticket_overrides)
    get_success_data(api_client.claim_ticket(ticket["id"], make_luthier_headers(luthier_id)))
    return get_success_data(api_client.get_ticket(ticket["id"], make_luthier_headers(luthier_id)))


def setup_ticket_awaiting_parts(luthier_id: str = "luthier-1", **ticket_overrides):
    """RepairTicket claimed and moved to AWAITING_PARTS. Returns the ticket dict."""
    ticket = setup_ticket_in_progress(luthier_id=luthier_id, **ticket_overrides)
    get_success_data(api_client.await_parts_ticket(ticket["id"], make_luthier_headers(luthier_id)))
    return get_success_data(api_client.get_ticket(ticket["id"], make_luthier_headers(luthier_id)))


def setup_ticket_ready(luthier_id: str = "luthier-1", **ticket_overrides):
    """RepairTicket claimed -> IN_PROGRESS -> READY. Returns the ticket dict."""
    ticket = setup_ticket_in_progress(luthier_id=luthier_id, **ticket_overrides)
    get_success_data(api_client.ready_ticket(ticket["id"], make_luthier_headers(luthier_id)))
    return get_success_data(api_client.get_ticket(ticket["id"], make_luthier_headers(luthier_id)))


# --- Tier 2: consignment -----------------------------------------------------

def setup_listed_consignment(ask_price_cents: int = 150000, commission_pct: float = None,
                             credit_score: int = 700):
    """Consignor customer + LISTED ConsignmentListing (mints a CONSIGNED unit).
    Returns (consignor, listing)."""
    consignor = create_customer(credit_score=credit_score)
    overrides = {}
    if commission_pct is not None:
        overrides["commission_pct"] = commission_pct
    resp = api_client.create_consignment(
        f.create_consignment_payload(consignor["id"], ask_price_cents=ask_price_cents, **overrides),
        SA,
    )
    listing = get_success_data(resp)
    return consignor, listing


# --- Tier 2: trade-in --------------------------------------------------------

def setup_offered_trade_in(condition: str = "USED", appraised_value_cents: int = 50000,
                           credit_score: int = 700):
    """Customer + OFFERED TradeIn (created by StoreManager). Returns (customer, trade_in)."""
    customer = create_customer(credit_score=credit_score, headers=SM)
    resp = api_client.create_trade_in(
        f.create_trade_in_payload(customer["id"], condition=condition,
                                  appraised_value_cents=appraised_value_cents),
        SM,
    )
    trade_in = get_success_data(resp)
    return customer, trade_in


# --- Tier 2 / 3: special orders ---------------------------------------------

def setup_quoted_special_order(quoted_price_cents: int = 200000, deposit_pct: float = None,
                               credit_score: int = 700):
    """Customer + QUOTED SpecialOrder. Returns (customer, order)."""
    customer = create_customer(credit_score=credit_score)
    overrides = {}
    if deposit_pct is not None:
        overrides["deposit_pct"] = deposit_pct
    resp = api_client.create_special_order(
        f.create_special_order_payload(customer["id"], quoted_price_cents=quoted_price_cents, **overrides),
        SA,
    )
    order = get_success_data(resp)
    return customer, order


def setup_deposited_special_order(quoted_price_cents: int = 200000, deposit_amount: int = 50000,
                                  credit_score: int = 700):
    """Customer + SpecialOrder advanced to DEPOSITED. Returns (customer, order)."""
    customer, order = setup_quoted_special_order(
        quoted_price_cents=quoted_price_cents, credit_score=credit_score
    )
    get_success_data(
        api_client.pay_deposit(order["id"], f.pay_deposit_payload(deposit_amount),
                               make_customer_headers(customer["id"]))
    )
    order = get_success_data(api_client.get_special_order(order["id"], SA))
    return customer, order


def setup_arrived_special_order(quoted_price_cents: int = 200000, deposit_amount: int = 50000,
                                credit_score: int = 700):
    """Customer + SpecialOrder DEPOSITED -> ORDERED -> ARRIVED (mints a RESERVED unit).
    Returns (customer, order)."""
    customer, order = setup_deposited_special_order(
        quoted_price_cents=quoted_price_cents, deposit_amount=deposit_amount, credit_score=credit_score
    )
    get_success_data(api_client.place_special_order(order["id"], SA))
    get_success_data(
        api_client.receive_special_order(order["id"], f.receive_special_order_payload(), SA)
    )
    order = get_success_data(api_client.get_special_order(order["id"], SA))
    return customer, order


# --- Tier 2: financing -------------------------------------------------------

def setup_submitted_financing(credit_score: int = 740, principal_cents: int = 240000,
                              term_months: int = 12, special_order_id: str = None):
    """Customer (with given credit_score) + SUBMITTED FinancingApplication.
    Returns (customer, application)."""
    customer = create_customer(credit_score=credit_score)
    overrides = {}
    if special_order_id is not None:
        overrides["special_order_id"] = special_order_id
    resp = api_client.create_financing(
        f.create_financing_payload(customer["id"], principal_cents=principal_cents,
                                   term_months=term_months, **overrides),
        SA,
    )
    application = get_success_data(resp)
    return customer, application


# --- Tier 2: lesson enrollments ---------------------------------------------

def setup_enrollment_linked_to_active_agreement(sessions_per_month: int = 8,
                                                base_rate_cents: int = 5000,
                                                instrument_family: str = "ORCHESTRA"):
    """Customer + reserved unit + ACTIVE RENTAL agreement + LessonEnrollment
    linked to it. Returns (customer, agreement, enrollment)."""
    customer, agreement, _ = setup_customer_and_active_agreement(plan="RENTAL")
    resp = api_client.create_enrollment(
        f.create_enrollment_payload(
            customer["id"], instrument_family=instrument_family,
            sessions_per_month=sessions_per_month, base_rate_cents=base_rate_cents,
            rental_agreement_id=agreement["id"],
        ),
        SA,
    )
    enrollment = get_success_data(resp)
    return customer, agreement, enrollment
