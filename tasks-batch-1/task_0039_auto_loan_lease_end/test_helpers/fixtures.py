"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "setup failed" errors, not confusing assertion failures.

Identity threading: a Borrower is entity_backed:Customer, so every ownership-gated
call (payments, payoff, lease-end settlements) uses make_borrower_headers(customer_id)
with the real Customer.id — never the shared fallback constant.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_rate_card_payload, create_customer_payload, create_vehicle_payload,
    create_loan_payload, create_lease_payload, record_payment_payload,
    create_settlement_payload,
)
from .test_users import TEST_USERS, make_borrower_headers

FM = TEST_USERS["finance_manager_headers"]

# Unique-value generators so each fixture invocation uses a fresh email/vin.
# (Each test runs against a fresh DB, but within a single test multiple entities
# may be created, so uniqueness within a process is enough.)
_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


# ─── Tier 0: Reference data ───────────────────────────────────────────────

def create_active_rate_card(**overrides) -> dict:
    """Create a rate card and activate it. Returns the activated card."""
    rc = get_success_data(api_client.create_rate_card(
        create_rate_card_payload(name=overrides.pop("name", _uniq("RC")), **overrides), FM))
    activated = get_success_data(api_client.activate_rate_card(rc["id"], FM))
    return activated


def create_customer(fico_score: int = 760, **overrides) -> dict:
    """Create a customer with a fresh email."""
    payload = create_customer_payload(
        email=overrides.pop("email", f"{_uniq('cust')}@x.com"),
        fico_score=fico_score, **overrides)
    return get_success_data(api_client.create_customer(payload, FM))


def create_vehicle(**overrides) -> dict:
    """Create a vehicle with a fresh vin."""
    payload = create_vehicle_payload(vin=overrides.pop("vin", _uniq("VIN")), **overrides)
    return get_success_data(api_client.create_vehicle(payload, FM))


# ─── Tier 1: Loan origination & state progression ─────────────────────────

def setup_loan(fico_score: int = 760, loan_overrides=None, vehicle_overrides=None):
    """Active rate card + customer + vehicle + originated CURRENT loan.

    Returns (customer, vehicle, loan). The loan is in CURRENT state.
    """
    create_active_rate_card()
    customer = create_customer(fico_score=fico_score)
    vehicle = create_vehicle(**(vehicle_overrides or {}))
    loan = get_success_data(api_client.create_loan(
        create_loan_payload(customer["id"], vehicle["id"], **(loan_overrides or {})), FM))
    return customer, vehicle, loan


def post_scheduled_payments(loan_id: str, customer_id: str, amount_cents: int, count: int):
    """Post `count` scheduled payments as the owning Borrower. Returns nothing."""
    headers = make_borrower_headers(customer_id)
    for _ in range(count):
        get_success_data(api_client.record_payment(
            loan_id, record_payment_payload(amount_cents, "SCHEDULED"), headers))


def setup_loan_with_payments(num_payments: int, fico_score: int = 760,
                             loan_overrides=None, vehicle_overrides=None):
    """Originated loan with `num_payments` posted scheduled payments.

    Returns (customer, vehicle, loan_at_origination). Caller re-reads loan for fresh fields.
    """
    customer, vehicle, loan = setup_loan(fico_score, loan_overrides, vehicle_overrides)
    post_scheduled_payments(loan["id"], customer["id"], loan["monthly_payment_cents"], num_payments)
    return customer, vehicle, loan


def setup_delinquent_loan(num_missed: int, fico_score: int = 760,
                          loan_overrides=None):
    """Originated loan driven to DELINQUENT via `num_missed` miss-payment calls.

    Returns (customer, vehicle, loan_at_origination).
    """
    customer, vehicle, loan = setup_loan(fico_score, loan_overrides)
    for _ in range(num_missed):
        get_success_data(api_client.miss_payment(loan["id"], FM))
    return customer, vehicle, loan


def setup_paid_off_loan(fico_score: int = 760):
    """Originated loan paid off early (terminal PAID_OFF). Returns (customer, vehicle, loan).

    The loan has no payments, so the actuarial payoff equals financed_principal_cents.
    """
    customer, vehicle, loan = setup_loan(fico_score)
    payoff_amount = loan["financed_principal_cents"]
    headers = make_borrower_headers(customer["id"])
    get_success_data(api_client.payoff_loan(
        loan["id"],
        {"amount_cents": payoff_amount, "expected_loan_version": loan["version"]},
        headers))
    return customer, vehicle, loan


# ─── Tier 2: Lease origination & maturity ─────────────────────────────────

def setup_lease(fico_score: int = 760, lease_overrides=None, vehicle_overrides=None):
    """Active rate card + customer + vehicle + originated ACTIVE lease.

    Returns (customer, vehicle, lease).
    """
    create_active_rate_card()
    customer = create_customer(fico_score=fico_score)
    vehicle = create_vehicle(
        sale_price_cents=3_200_000, residual_value_cents=1_850_000,
        **(vehicle_overrides or {}))
    lease = get_success_data(api_client.create_lease(
        create_lease_payload(customer["id"], vehicle["id"], **(lease_overrides or {})), FM))
    return customer, vehicle, lease


def setup_matured_lease(fico_score: int = 760, lease_overrides=None, vehicle_overrides=None):
    """ACTIVE lease advanced to MATURING. Returns (customer, vehicle, matured_lease).

    matured_lease carries the post-mature version for the expected_lease_version field.
    """
    customer, vehicle, lease = setup_lease(fico_score, lease_overrides, vehicle_overrides)
    matured = get_success_data(api_client.mature_lease(lease["id"], FM))
    return customer, vehicle, matured


def elect_lease_end(lease_id: str, customer_id: str, election: str, odometer_miles: int,
                    expected_lease_version: int, **extra):
    """Create a lease-end settlement as the owning Borrower. Returns the settlement."""
    headers = make_borrower_headers(customer_id)
    payload = create_settlement_payload(
        lease_id, election, odometer_miles, expected_lease_version, **extra)
    return get_success_data(api_client.create_settlement(payload, headers))


def setup_returned_lease(fico_score: int = 760, per_year_excess_miles=None,
                         odometer_miles: int = 36000):
    """Matured lease taken through a RETURN settlement (lease -> SETTLED).

    Returns (customer, vehicle, matured_lease, settlement).
    """
    customer, vehicle, matured = setup_matured_lease(fico_score)
    settlement = elect_lease_end(
        matured["id"], customer["id"], "RETURN", odometer_miles, matured["version"],
        per_year_excess_miles=(per_year_excess_miles
                               if per_year_excess_miles is not None else [0, 0, 0]))
    return customer, vehicle, matured, settlement
