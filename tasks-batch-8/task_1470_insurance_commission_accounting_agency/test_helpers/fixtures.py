"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the book to be in a specific state that takes
5-15 API calls to reach (producer -> carrier -> product -> schedule -> policy
-> disclosure delivery -> bind -> ...). These helpers encapsulate those chains
so tests can focus on assertions. All helpers use the lenient get_success_data
validator so setup failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_POLICY_EFFECTIVE_DATE,
    DEFAULT_SCHEDULE_EFFECTIVE_FROM,
    DEFAULT_STATEMENT_PERIOD_END,
    DEFAULT_STATEMENT_PERIOD_START,
)
from .factories import (
    create_carrier_payload,
    create_policy_payload,
    create_producer_payload,
    create_product_payload,
    create_schedule_payload,
    create_statement_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]


# --- Single-resource creators ---------------------------------------------

def create_producer(**overrides) -> dict:
    """Create a producer. Returns the Producer resource."""
    return get_success_data(
        api_client.create_producer(create_producer_payload(**overrides), ADMIN)
    )


def create_carrier(**overrides) -> dict:
    """Create a carrier. Returns the Carrier resource."""
    return get_success_data(
        api_client.create_carrier(create_carrier_payload(**overrides), ADMIN)
    )


def create_product(carrier_id: str, **overrides) -> dict:
    """Create a product under a carrier. Returns the Product resource."""
    return get_success_data(
        api_client.create_product(create_product_payload(carrier_id, **overrides), ADMIN)
    )


def get_product_version(product_id: str) -> int:
    """Current Product.version via a fresh read (OCC inputs must be current)."""
    return get_success_data(api_client.get_product(product_id, ADMIN))["version"]


def create_schedule(
    product_id: str,
    *,
    expected_product_version=None,
    headers=None,
    **overrides,
) -> dict:
    """Create a commission schedule. When expected_product_version is omitted,
    the product is re-read so the OCC field is current."""
    if expected_product_version is None:
        expected_product_version = get_product_version(product_id)
    payload = create_schedule_payload(
        expected_product_version=expected_product_version, **overrides
    )
    return get_success_data(
        api_client.create_commission_schedule(product_id, payload, headers or ADMIN)
    )


def create_policy(product_id: str, producer_id: str, **overrides) -> dict:
    """Create a policy in QUOTED status (auto-generates its disclosure)."""
    return get_success_data(
        api_client.create_policy(
            create_policy_payload(product_id, producer_id, **overrides), ADMIN
        )
    )


def create_statement(carrier_id: str, lines: list, **overrides) -> dict:
    """Import a carrier statement. Returns the CarrierStatement resource."""
    return get_success_data(
        api_client.create_carrier_statement(
            create_statement_payload(carrier_id, lines, **overrides), ADMIN
        )
    )


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (AgencyAdmin-only; fires the delinquency sweep)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


# --- Disclosure / bind chain (PRD §3.3) ------------------------------------

def get_policy_disclosure(policy_id: str) -> dict:
    """Return the (single) auto-generated disclosure for a policy."""
    data = get_success_data(
        api_client.list_disclosures(ADMIN, params={"policy_id": policy_id})
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one disclosure for policy {policy_id}, got {data!r}"
    )
    return data[0]


def deliver_policy_disclosure(policy_id: str) -> dict:
    """Deliver the policy's disclosure (GENERATED -> DELIVERED)."""
    disclosure = get_policy_disclosure(policy_id)
    return get_success_data(api_client.deliver_disclosure(disclosure["id"], ADMIN))


def bind_policy(policy_id: str) -> dict:
    """Bind a QUOTED policy. Returns the bound (ACTIVE) Policy."""
    return get_success_data(api_client.bind_policy(policy_id, ADMIN))


def setup_bound_policy(
    *,
    billing_type: str = "DIRECT_BILL",
    premium_annual_cents: int = 2400000,
    commission_rate_bps: int = 5000,
    override_rate_bps: int = 0,
    advance_months: int = 12,
    tier: str = "STANDARD",
    effective_date: str = DEFAULT_POLICY_EFFECTIVE_DATE,
    schedule_effective_from: str = DEFAULT_SCHEDULE_EFFECTIVE_FROM,
    producer_overrides=None,
    policy_number=None,
) -> dict:
    """Full bind-ready chain: producer -> carrier -> product -> schedule ->
    policy -> disclosure DELIVERED -> bind.

    Returns a bundle dict with keys: producer, carrier, product, schedule,
    policy (the post-bind ACTIVE policy), disclosure.
    """
    producer = create_producer(tier=tier, **(producer_overrides or {}))
    carrier = create_carrier()
    product = create_product(carrier["id"])
    schedule = create_schedule(
        product["id"],
        tier=tier,
        commission_rate_bps=commission_rate_bps,
        override_rate_bps=override_rate_bps,
        advance_months=advance_months,
        effective_from=schedule_effective_from,
    )
    policy = create_policy(
        product["id"],
        producer["id"],
        billing_type=billing_type,
        premium_annual_cents=premium_annual_cents,
        effective_date=effective_date,
        policy_number=policy_number,
    )
    disclosure = deliver_policy_disclosure(policy["id"])
    bound = bind_policy(policy["id"])
    return {
        "producer": producer,
        "carrier": carrier,
        "product": product,
        "schedule": schedule,
        "policy": bound,
        "disclosure": disclosure,
    }


# --- Ledger reads -----------------------------------------------------------

def list_entries(**filters) -> list:
    """List commission entries matching the given filters."""
    data = get_success_data(
        api_client.list_commission_entries(
            ADMIN, params={k: v for k, v in filters.items() if v is not None}
        )
    )
    assert isinstance(data, list), f"expected entry list, got {data!r}"
    return data


def get_single_entry(policy_id: str, entry_type=None) -> dict:
    """Return the single entry of the given type for a policy."""
    entries = list_entries(policy_id=policy_id, entry_type=entry_type)
    assert len(entries) == 1, (
        f"expected exactly one {entry_type} entry for policy {policy_id}, "
        f"got {len(entries)}"
    )
    return entries[0]


def list_chargebacks(**filters) -> list:
    """List chargebacks matching the given filters."""
    data = get_success_data(
        api_client.list_chargebacks(
            ADMIN, params={k: v for k, v in filters.items() if v is not None}
        )
    )
    assert isinstance(data, list), f"expected chargeback list, got {data!r}"
    return data


def get_single_chargeback(**filters) -> dict:
    """Return the single chargeback matching the given filters."""
    chargebacks = list_chargebacks(**filters)
    assert len(chargebacks) == 1, (
        f"expected exactly one chargeback for {filters}, got {len(chargebacks)}"
    )
    return chargebacks[0]


def get_policy_invoice(policy_id: str) -> dict:
    """Return the single premium invoice of a bound AGENCY_BILL policy."""
    data = get_success_data(api_client.list_policy_invoices(policy_id, ADMIN))
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one invoice for policy {policy_id}, got {data!r}"
    )
    return data[0]


def get_producer(producer_id: str) -> dict:
    """Fresh read of a producer."""
    return get_success_data(api_client.get_producer(producer_id, ADMIN))


def get_carrier(carrier_id: str) -> dict:
    """Fresh read of a carrier."""
    return get_success_data(api_client.get_carrier(carrier_id, ADMIN))


def get_policy(policy_id: str) -> dict:
    """Fresh read of a policy."""
    return get_success_data(api_client.get_policy(policy_id, ADMIN))


def fresh_producer_version(producer_id: str) -> int:
    """Current Producer.version via a fresh read (OCC inputs must be current)."""
    return get_producer(producer_id)["version"]


# --- Payouts (PRD §3.8) -----------------------------------------------------

def create_payout_fresh_version(producer_id: str, amount_cents: int) -> dict:
    """Create a payout using the producer's current version. Returns the payout."""
    version = fresh_producer_version(producer_id)
    return get_success_data(
        api_client.create_payout(
            producer_id,
            {"amount_cents": amount_cents, "expected_producer_version": version},
            ADMIN,
        )
    )


def create_and_mark_payout_paid(producer_id: str, amount_cents: int) -> dict:
    """Create a payout and mark it PAID. Returns the PAID payout."""
    payout = create_payout_fresh_version(producer_id, amount_cents)
    return get_success_data(api_client.mark_payout_paid(payout["id"], ADMIN))


# --- Cancellation / chargeback chains (PRD §3.6) ----------------------------

def cancel_policy(policy_id: str, cancel_effective_date: str) -> dict:
    """Voluntarily cancel a policy. Returns the cancelled Policy."""
    return get_success_data(
        api_client.cancel_policy(
            policy_id, {"cancel_effective_date": cancel_effective_date}, ADMIN
        )
    )


def setup_cancelled_policy(
    *,
    premium_annual_cents: int = 2400000,
    commission_rate_bps: int = 5000,
    cancel_effective_date: str = "2027-02-01",
    **kwargs,
) -> dict:
    """Bound DIRECT_BILL policy cancelled voluntarily. Returns the bound-policy
    bundle plus keys: cancelled_policy, chargebacks, entries."""
    bundle = setup_bound_policy(
        premium_annual_cents=premium_annual_cents,
        commission_rate_bps=commission_rate_bps,
        **kwargs,
    )
    cancelled = cancel_policy(bundle["policy"]["id"], cancel_effective_date)
    bundle["cancelled_policy"] = cancelled
    bundle["chargebacks"] = list_chargebacks(policy_id=bundle["policy"]["id"])
    bundle["entries"] = list_entries(policy_id=bundle["policy"]["id"])
    return bundle


# --- Statement / reconciliation chains (PRD §3.7) ---------------------------

def setup_reconciling_statement(
    *,
    premium_annual_cents: int = 12000000,
    commission_rate_bps: int = 5000,
    reported_amount_cents: int,
    policy_number=None,
    period_start: str = DEFAULT_STATEMENT_PERIOD_START,
    period_end: str = DEFAULT_STATEMENT_PERIOD_END,
) -> dict:
    """Bound DIRECT_BILL policy plus a carrier statement reporting
    reported_amount_cents for that policy, moved to RECONCILING.

    Returns the bound-policy bundle plus keys: statement (post-start), entry.
    """
    bundle = setup_bound_policy(
        premium_annual_cents=premium_annual_cents,
        commission_rate_bps=commission_rate_bps,
        policy_number=policy_number,
    )
    statement = create_statement(
        bundle["carrier"]["id"],
        [
            {
                "line_ref": bundle["policy"]["policy_number"],
                "reported_amount_cents": reported_amount_cents,
            }
        ],
        period_start=period_start,
        period_end=period_end,
    )
    started = get_success_data(api_client.start_reconciliation(statement["id"], ADMIN))
    bundle["statement"] = started
    bundle["entry"] = get_single_entry(bundle["policy"]["id"], "BASE")
    return bundle
