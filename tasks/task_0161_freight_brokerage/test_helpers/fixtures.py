"""Composite setup helpers for multi-step test prerequisites.

Most interesting PRD claims need 5–15 sequential API calls to put the
system into the testable state. Centralising those sequences here keeps
the test_suite files small and focused on the actual assertion the
test exists to check.

Identity threading (PRD §2.1, see test_users.py docstring):

    Every ownership-gated ShipperUser call mints headers with the real
    Shipper.id via `make_shipper_headers(shipper["id"])`. Every
    ownership-gated CarrierUser call mints headers via
    `make_carrier_headers(carrier["id"])`. Using the shared placeholders
    for ownership-gated calls would fail every ownership check
    universally and is therefore forbidden inside fixtures.

Fixtures use `get_success_data()` (lenient 2xx validator) so that a
setup-side failure surfaces as a clear "setup failed" message rather
than a confusing assertion error inside a test body.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_DETENTION_FREE_MINUTES,
    DEFAULT_DETENTION_RATE_CENTS_PER_15MIN,
    SPOT_BASE_CENTS_PER_EQUIPMENT,
    SPOT_PER_UNIT_CENTS,
)
from .factories import (
    add_days,
    add_minutes,
    clock_advance_payload,
    counter_dispute_claim_payload,
    create_accessorial_charge_payload,
    create_brokerage_payload,
    create_carrier_payload,
    create_dispute_claim_payload,
    create_load_payload,
    create_quote_request_payload,
    create_rate_contract_payload,
    create_shipper_payload,
    deliver_load_payload,
    iso_utc,
    parse_iso,
    resolve_dispute_claim_payload,
    utcnow,
)
from .test_users import (
    TEST_USERS,
    make_carrier_headers,
    make_shipper_headers,
)


# ===========================================================================
# Tier 0 — primitive operations (one API call each, returning the body).
# These wrap api_client + get_success_data + the right role headers; tests
# rarely call them directly but the higher-tier composites compose them.
# ===========================================================================
def create_brokerage(**overrides: Any) -> Dict[str, Any]:
    res = api_client.create_brokerage(
        create_brokerage_payload(**overrides),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


def get_brokerage(brokerage_id: str) -> Dict[str, Any]:
    res = api_client.get_brokerage(
        brokerage_id, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


def advance_clock_to_iso(brokerage_id: str, to_iso: str) -> Dict[str, Any]:
    res = api_client.clock_advance(
        brokerage_id, clock_advance_payload(to_iso),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


def advance_clock_by_minutes(brokerage_id: str, minutes: int) -> Dict[str, Any]:
    brokerage = get_brokerage(brokerage_id)
    new_clock = iso_utc(add_minutes(parse_iso(brokerage["clock_now_iso"]),
                                    minutes))
    return advance_clock_to_iso(brokerage_id, new_clock)


def advance_clock_by_days(brokerage_id: str, days: int) -> Dict[str, Any]:
    brokerage = get_brokerage(brokerage_id)
    new_clock = iso_utc(add_days(parse_iso(brokerage["clock_now_iso"]),
                                 days))
    return advance_clock_to_iso(brokerage_id, new_clock)


def sweep_expire_quotes(brokerage_id: str) -> Any:
    res = api_client.sweep_expire_quotes(
        brokerage_id, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


# --- Shippers ---
def create_shipper(brokerage_id: str, **overrides: Any) -> Dict[str, Any]:
    res = api_client.create_shipper(
        brokerage_id, create_shipper_payload(**overrides),
        TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


def get_shipper(brokerage_id: str, shipper_id: str) -> Dict[str, Any]:
    res = api_client.get_shipper(
        brokerage_id, shipper_id, TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


def suspend_shipper(brokerage_id: str, shipper_id: str) -> Dict[str, Any]:
    res = api_client.suspend_shipper(
        brokerage_id, shipper_id, TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


# --- Carriers ---
def create_carrier(brokerage_id: str, **overrides: Any) -> Dict[str, Any]:
    res = api_client.create_carrier(
        brokerage_id, create_carrier_payload(**overrides),
        TEST_USERS["carrier_ops_headers"],
    )
    return get_success_data(res)


def get_carrier(brokerage_id: str, carrier_id: str) -> Dict[str, Any]:
    res = api_client.get_carrier(
        brokerage_id, carrier_id, TEST_USERS["carrier_ops_headers"],
    )
    return get_success_data(res)


def qualify_carrier(brokerage_id: str, carrier_id: str) -> Dict[str, Any]:
    res = api_client.qualify_carrier(
        brokerage_id, carrier_id, TEST_USERS["carrier_ops_headers"],
    )
    return get_success_data(res)


def suspend_carrier(brokerage_id: str, carrier_id: str) -> Dict[str, Any]:
    res = api_client.suspend_carrier(
        brokerage_id, carrier_id, TEST_USERS["carrier_ops_headers"],
    )
    return get_success_data(res)


def requalify_carrier(brokerage_id: str, carrier_id: str) -> Dict[str, Any]:
    res = api_client.requalify_carrier(
        brokerage_id, carrier_id, TEST_USERS["carrier_ops_headers"],
    )
    return get_success_data(res)


def revoke_carrier(brokerage_id: str, carrier_id: str) -> Dict[str, Any]:
    res = api_client.revoke_carrier(
        brokerage_id, carrier_id, TEST_USERS["carrier_ops_headers"],
    )
    return get_success_data(res)


# --- RateContracts ---
def create_rate_contract(brokerage_id: str, shipper_id: str,
                         **overrides: Any) -> Dict[str, Any]:
    res = api_client.create_rate_contract(
        brokerage_id, create_rate_contract_payload(shipper_id, **overrides),
        TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


def terminate_rate_contract(brokerage_id: str,
                            contract_id: str) -> Dict[str, Any]:
    res = api_client.terminate_rate_contract(
        brokerage_id, contract_id, TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 1 — qualified carriers and active shippers (state progression).
# ===========================================================================
def create_qualified_carrier(brokerage_id: str,
                             **overrides: Any) -> Dict[str, Any]:
    """Carrier created and advanced to QUALIFIED.

    Insurance defaults to one year in the future (well past clock_now_iso)
    so the qualify-side insurance check passes.
    """
    carrier = create_carrier(brokerage_id, **overrides)
    return qualify_carrier(brokerage_id, carrier["id"])


# ===========================================================================
# Tier 2 — quote requests, accepted quotes.
# ===========================================================================
def create_quote_request(brokerage_id: str, shipper_id: str,
                         **overrides: Any) -> Dict[str, Any]:
    """ShipperUser-scoped — ownership headers minted from shipper_id."""
    res = api_client.create_quote_request(
        brokerage_id, shipper_id,
        create_quote_request_payload(**overrides),
        make_shipper_headers(shipper_id),
    )
    return get_success_data(res)


def quote_quote_request(brokerage_id: str, shipper_id: str,
                        quote_id: str) -> Dict[str, Any]:
    res = api_client.quote_quote_request(
        brokerage_id, shipper_id, quote_id,
        TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


def accept_quote_request(brokerage_id: str, shipper_id: str,
                         quote_id: str) -> Dict[str, Any]:
    """ShipperUser-scoped — ownership headers minted from shipper_id."""
    res = api_client.accept_quote_request(
        brokerage_id, shipper_id, quote_id,
        make_shipper_headers(shipper_id),
    )
    return get_success_data(res)


def reject_quote_request(brokerage_id: str, shipper_id: str,
                         quote_id: str) -> Dict[str, Any]:
    res = api_client.reject_quote_request(
        brokerage_id, shipper_id, quote_id,
        make_shipper_headers(shipper_id),
    )
    return get_success_data(res)


def create_accepted_quote(brokerage_id: str, shipper_id: str,
                          **overrides: Any) -> Dict[str, Any]:
    """Quote walked OPEN → QUOTED → ACCEPTED. Returns the ACCEPTED quote."""
    quote = create_quote_request(brokerage_id, shipper_id, **overrides)
    quoted = quote_quote_request(brokerage_id, shipper_id, quote["id"])
    return accept_quote_request(brokerage_id, shipper_id, quoted["id"])


# ===========================================================================
# Tier 3 — loads through every state.
# ===========================================================================
def tender_load(brokerage_id: str, shipper_id: str, quote_id: str,
                carrier_id: str) -> Dict[str, Any]:
    res = api_client.create_load(
        brokerage_id, shipper_id,
        create_load_payload(quote_id, carrier_id),
        TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


def carrier_accept_load(brokerage_id: str, shipper_id: str, load_id: str,
                        carrier_id: str) -> Dict[str, Any]:
    """CarrierUser-scoped — ownership headers minted from carrier_id."""
    res = api_client.carrier_accept_load(
        brokerage_id, shipper_id, load_id,
        make_carrier_headers(carrier_id),
    )
    return get_success_data(res)


def depart_load(brokerage_id: str, shipper_id: str, load_id: str,
                carrier_id: str) -> Dict[str, Any]:
    res = api_client.depart_load(
        brokerage_id, shipper_id, load_id,
        make_carrier_headers(carrier_id),
    )
    return get_success_data(res)


def deliver_load(brokerage_id: str, shipper_id: str, load_id: str,
                 carrier_id: str, actual_arrive_at: str,
                 actual_depart_at: str) -> Dict[str, Any]:
    res = api_client.deliver_load(
        brokerage_id, shipper_id, load_id,
        deliver_load_payload(actual_arrive_at, actual_depart_at),
        make_carrier_headers(carrier_id),
    )
    return get_success_data(res)


def invoice_load(brokerage_id: str, shipper_id: str,
                 load_id: str) -> Dict[str, Any]:
    res = api_client.invoice_load(
        brokerage_id, shipper_id, load_id,
        TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


def cancel_load_as_broker(brokerage_id: str, shipper_id: str,
                          load_id: str) -> Dict[str, Any]:
    res = api_client.cancel_load(
        brokerage_id, shipper_id, load_id,
        TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


def get_load(brokerage_id: str, shipper_id: str,
             load_id: str) -> Dict[str, Any]:
    res = api_client.get_load(
        brokerage_id, shipper_id, load_id,
        TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 4 — accessorial charges.
# ===========================================================================
def create_accessorial(brokerage_id: str, shipper_id: str, load_id: str,
                       carrier_id: str, **overrides: Any) -> Dict[str, Any]:
    res = api_client.create_accessorial_charge(
        brokerage_id, shipper_id, load_id,
        create_accessorial_charge_payload(**overrides),
        make_carrier_headers(carrier_id),
    )
    return get_success_data(res)


def approve_accessorial(brokerage_id: str,
                        charge_id: str) -> Dict[str, Any]:
    res = api_client.approve_accessorial_charge(
        brokerage_id, charge_id, TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


def deny_accessorial(brokerage_id: str,
                     charge_id: str) -> Dict[str, Any]:
    res = api_client.deny_accessorial_charge(
        brokerage_id, charge_id, TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 5 — invoices, factoring, disputes.
# ===========================================================================
def get_invoice(brokerage_id: str, invoice_id: str) -> Dict[str, Any]:
    res = api_client.get_invoice(
        brokerage_id, invoice_id, TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


def factor_invoice(brokerage_id: str, invoice_id: str) -> Dict[str, Any]:
    res = api_client.factor_invoice(
        brokerage_id, invoice_id, TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


def write_off_invoice(brokerage_id: str, invoice_id: str) -> Dict[str, Any]:
    res = api_client.write_off_invoice(
        brokerage_id, invoice_id, TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


def file_dispute(brokerage_id: str, shipper_id: str, invoice_id: str,
                 **overrides: Any) -> Dict[str, Any]:
    """ShipperUser-scoped — ownership headers minted from shipper_id."""
    res = api_client.create_dispute_claim(
        brokerage_id, invoice_id,
        create_dispute_claim_payload(**overrides),
        make_shipper_headers(shipper_id),
    )
    return get_success_data(res)


def start_review_dispute(brokerage_id: str, claim_id: str) -> Dict[str, Any]:
    res = api_client.start_review_dispute_claim(
        brokerage_id, claim_id, TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


def counter_dispute(brokerage_id: str, claim_id: str,
                    counter_offer_cents: int) -> Dict[str, Any]:
    res = api_client.counter_dispute_claim(
        brokerage_id, claim_id,
        counter_dispute_claim_payload(counter_offer_cents),
        TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


def accept_counter_dispute(brokerage_id: str, shipper_id: str,
                           claim_id: str) -> Dict[str, Any]:
    res = api_client.accept_counter_dispute_claim(
        brokerage_id, claim_id, make_shipper_headers(shipper_id),
    )
    return get_success_data(res)


def reject_counter_dispute(brokerage_id: str, shipper_id: str,
                           claim_id: str) -> Dict[str, Any]:
    res = api_client.reject_counter_dispute_claim(
        brokerage_id, claim_id, make_shipper_headers(shipper_id),
    )
    return get_success_data(res)


def resolve_dispute(brokerage_id: str, claim_id: str,
                    settled_credit_cents: int) -> Dict[str, Any]:
    res = api_client.resolve_dispute_claim(
        brokerage_id, claim_id,
        resolve_dispute_claim_payload(settled_credit_cents),
        TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


def escalate_dispute(brokerage_id: str, claim_id: str) -> Dict[str, Any]:
    res = api_client.escalate_dispute_claim(
        brokerage_id, claim_id, TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


def withdraw_dispute(brokerage_id: str, shipper_id: str,
                     claim_id: str) -> Dict[str, Any]:
    res = api_client.withdraw_dispute_claim(
        brokerage_id, claim_id, make_shipper_headers(shipper_id),
    )
    return get_success_data(res)


def get_dispute_claim(brokerage_id: str, claim_id: str) -> Dict[str, Any]:
    res = api_client.get_dispute_claim(
        brokerage_id, claim_id, TEST_USERS["broker_ops_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 6 — Composite scenarios. These are the workhorses that the
# test_suite imports.
# ===========================================================================
def setup_brokerage_with_shipper(
    factoring_reserve_pct: float = 5.00,
    detention_free_minutes: int = DEFAULT_DETENTION_FREE_MINUTES,
    detention_rate_cents_per_15min: int = (
        DEFAULT_DETENTION_RATE_CENTS_PER_15MIN
    ),
    smartway_required: bool = False,
    credit_limit_cents: int = 10_000_000,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Active brokerage + active shipper. Returns (brokerage, shipper)."""
    brokerage = create_brokerage(
        factoring_reserve_pct=factoring_reserve_pct,
        detention_free_minutes=detention_free_minutes,
        detention_rate_cents_per_15min=detention_rate_cents_per_15min,
    )
    shipper = create_shipper(
        brokerage["id"],
        smartway_required=smartway_required,
        credit_limit_cents=credit_limit_cents,
    )
    return brokerage, shipper


def setup_brokerage_shipper_qualified_carrier(
    smartway_required: bool = False,
    smartway_certified: bool = True,
    credit_limit_cents: int = 10_000_000,
    **brokerage_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Brokerage + Shipper + QUALIFIED Carrier."""
    brokerage, shipper = setup_brokerage_with_shipper(
        smartway_required=smartway_required,
        credit_limit_cents=credit_limit_cents,
        **brokerage_overrides,
    )
    carrier = create_qualified_carrier(
        brokerage["id"], smartway_certified=smartway_certified,
    )
    return brokerage, shipper, carrier


def setup_quoted_quote_request(
    origin_zip: str = "10001",
    destination_zip: str = "20002",
    equipment_type: str = "DRY_VAN",
    **shipper_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Brokerage + Shipper + QuoteRequest walked to QUOTED.

    Returns (brokerage, shipper, quote_request). Spot pricing.
    """
    brokerage, shipper = setup_brokerage_with_shipper(**shipper_overrides)
    quote = create_quote_request(
        brokerage["id"], shipper["id"],
        origin_zip=origin_zip, destination_zip=destination_zip,
        equipment_type=equipment_type,
    )
    quoted = quote_quote_request(brokerage["id"], shipper["id"], quote["id"])
    return brokerage, shipper, quoted


def setup_accepted_quote(
    origin_zip: str = "10001",
    destination_zip: str = "20002",
    equipment_type: str = "DRY_VAN",
    **shipper_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Brokerage + Shipper + ACCEPTED quote. Spot pricing by default."""
    brokerage, shipper, quoted = setup_quoted_quote_request(
        origin_zip=origin_zip, destination_zip=destination_zip,
        equipment_type=equipment_type, **shipper_overrides,
    )
    accepted = accept_quote_request(brokerage["id"], shipper["id"],
                                    quoted["id"])
    return brokerage, shipper, accepted


def setup_tendered_load(
    origin_zip: str = "10001",
    destination_zip: str = "20002",
    equipment_type: str = "DRY_VAN",
    smartway_required: bool = False,
    smartway_certified: bool = True,
    credit_limit_cents: int = 10_000_000,
    **brokerage_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Full preamble up to a TENDERED load.

    Returns (brokerage, shipper, carrier, accepted_quote, load).
    """
    brokerage, shipper, carrier = setup_brokerage_shipper_qualified_carrier(
        smartway_required=smartway_required,
        smartway_certified=smartway_certified,
        credit_limit_cents=credit_limit_cents,
        **brokerage_overrides,
    )
    quote = create_quote_request(
        brokerage["id"], shipper["id"],
        origin_zip=origin_zip, destination_zip=destination_zip,
        equipment_type=equipment_type,
    )
    quoted = quote_quote_request(brokerage["id"], shipper["id"], quote["id"])
    accepted = accept_quote_request(brokerage["id"], shipper["id"],
                                    quoted["id"])
    load = tender_load(brokerage["id"], shipper["id"], accepted["id"],
                       carrier["id"])
    return brokerage, shipper, carrier, accepted, load


def setup_accepted_load(**overrides: Any) -> Tuple[Dict[str, Any], ...]:
    """Walk through to Load.status == ACCEPTED."""
    brokerage, shipper, carrier, quote, load = setup_tendered_load(**overrides)
    load = carrier_accept_load(brokerage["id"], shipper["id"], load["id"],
                               carrier["id"])
    return brokerage, shipper, carrier, quote, load


def setup_in_transit_load(**overrides: Any) -> Tuple[Dict[str, Any], ...]:
    """Walk through to Load.status == IN_TRANSIT."""
    brokerage, shipper, carrier, quote, load = setup_accepted_load(**overrides)
    load = depart_load(brokerage["id"], shipper["id"], load["id"],
                       carrier["id"])
    return brokerage, shipper, carrier, quote, load


def setup_delivered_load(
    detention_minutes: int = 0,
    origin_zip: str = "10001",
    destination_zip: str = "20002",
    equipment_type: str = "DRY_VAN",
    smartway_required: bool = False,
    smartway_certified: bool = True,
    credit_limit_cents: int = 10_000_000,
    detention_free_minutes: int = DEFAULT_DETENTION_FREE_MINUTES,
    detention_rate_cents_per_15min: int = (
        DEFAULT_DETENTION_RATE_CENTS_PER_15MIN
    ),
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Walk through to DELIVERED with controllable detention.

    `detention_minutes` is the total elapsed minutes between
    actual_arrive_at and actual_depart_at. The free window is
    detention_free_minutes; any excess is the chargeable portion.
    """
    brokerage, shipper, carrier, quote, load = setup_in_transit_load(
        origin_zip=origin_zip, destination_zip=destination_zip,
        equipment_type=equipment_type,
        smartway_required=smartway_required,
        smartway_certified=smartway_certified,
        credit_limit_cents=credit_limit_cents,
        detention_free_minutes=detention_free_minutes,
        detention_rate_cents_per_15min=detention_rate_cents_per_15min,
    )
    # Use the brokerage clock as the deliver baseline so that future-time
    # checks elsewhere remain consistent.
    brokerage = get_brokerage(brokerage["id"])
    arrive = parse_iso(brokerage["clock_now_iso"])
    depart = add_minutes(arrive, detention_minutes)
    load = deliver_load(
        brokerage["id"], shipper["id"], load["id"], carrier["id"],
        actual_arrive_at=iso_utc(arrive),
        actual_depart_at=iso_utc(depart),
    )
    return brokerage, shipper, carrier, quote, load


def setup_invoiced_load(
    detention_minutes: int = 0,
    origin_zip: str = "10001",
    destination_zip: str = "20002",
    equipment_type: str = "DRY_VAN",
    smartway_required: bool = False,
    smartway_certified: bool = True,
    credit_limit_cents: int = 10_000_000,
    accessorials: Optional[List[Tuple[str, int, bool]]] = None,
    detention_free_minutes: int = DEFAULT_DETENTION_FREE_MINUTES,
    detention_rate_cents_per_15min: int = (
        DEFAULT_DETENTION_RATE_CENTS_PER_15MIN
    ),
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Walk through to INVOICED with controllable detention + accessorials.

    `accessorials` is a list of (charge_type, amount_cents, approve)
    tuples that are filed against the load while it is IN_TRANSIT (PRD
    §3.7 permits filing between ACCEPTED and DELIVERED — we file while
    still in transit which is within range) — wait: PRD says "between
    ACCEPTED and DELIVERED" inclusive; we file BEFORE /deliver.

    Returns (brokerage, shipper, carrier, accepted_quote, load, invoice).
    """
    # Walk to IN_TRANSIT, then file accessorials, then deliver, then invoice.
    brokerage, shipper, carrier, quote, load = setup_in_transit_load(
        origin_zip=origin_zip, destination_zip=destination_zip,
        equipment_type=equipment_type,
        smartway_required=smartway_required,
        smartway_certified=smartway_certified,
        credit_limit_cents=credit_limit_cents,
        detention_free_minutes=detention_free_minutes,
        detention_rate_cents_per_15min=detention_rate_cents_per_15min,
    )
    # File and approve/deny accessorials while still IN_TRANSIT.
    if accessorials:
        for charge_type, amount, approve in accessorials:
            charge = create_accessorial(
                brokerage["id"], shipper["id"], load["id"], carrier["id"],
                charge_type=charge_type, amount_cents=amount,
            )
            if approve:
                approve_accessorial(brokerage["id"], charge["id"])
            else:
                deny_accessorial(brokerage["id"], charge["id"])

    # Deliver with the specified detention.
    brokerage = get_brokerage(brokerage["id"])
    arrive = parse_iso(brokerage["clock_now_iso"])
    depart = add_minutes(arrive, detention_minutes)
    load = deliver_load(
        brokerage["id"], shipper["id"], load["id"], carrier["id"],
        actual_arrive_at=iso_utc(arrive),
        actual_depart_at=iso_utc(depart),
    )
    invoice = invoice_load(brokerage["id"], shipper["id"], load["id"])
    return brokerage, shipper, carrier, quote, load, invoice


def setup_invoice_in_review_dispute(
    claim_type: str = "DAMAGE",
    claimed_cents: int = 1_000,
    **invoice_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Walk to INVOICED, then file a dispute and move it to IN_REVIEW.

    Returns (brokerage, shipper, carrier, accepted_quote, load, invoice,
    claim).
    """
    brokerage, shipper, carrier, quote, load, invoice = setup_invoiced_load(
        **invoice_overrides
    )
    claim = file_dispute(
        brokerage["id"], shipper["id"], invoice["id"],
        claim_type=claim_type, claimed_cents=claimed_cents,
    )
    claim = start_review_dispute(brokerage["id"], claim["id"])
    return brokerage, shipper, carrier, quote, load, invoice, claim


def setup_factored_invoice(
    **invoice_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Invoice walked to factoring_status == FACTORED.

    Returns (brokerage, shipper, carrier, accepted_quote, load, invoice,
    factoring_advance).
    """
    brokerage, shipper, carrier, quote, load, invoice = setup_invoiced_load(
        **invoice_overrides
    )
    advance = factor_invoice(brokerage["id"], invoice["id"])
    invoice = get_invoice(brokerage["id"], invoice["id"])
    return brokerage, shipper, carrier, quote, load, invoice, advance


# ===========================================================================
# Tier 7 — Targeted boundary fixtures for difficulty-design instances.
# ===========================================================================
def spot_linehaul_cents(equipment_type: str, origin_zip: str,
                        destination_zip: str) -> int:
    """Pure-arithmetic helper mirroring PRD §3.4 spot formula.

    Lets tests compute the exact expected cents they should see in
    QuoteRequest.quoted_linehaul_cents on a SPOT quote.
    """
    base = SPOT_BASE_CENTS_PER_EQUIPMENT[equipment_type]
    distance_units = abs(int(destination_zip) - int(origin_zip))
    return base + distance_units * SPOT_PER_UNIT_CENTS[equipment_type]


def detention_cents(elapsed_minutes: int, free_minutes: int,
                    rate_cents_per_15min: int) -> int:
    """Pure-arithmetic mirror of PRD §3.7 provisional/final formula.

    Pinned rounding order: ceil-to-15-minute-increment FIRST, then
    multiply by per-increment rate.
    """
    chargeable = max(0, elapsed_minutes - free_minutes)
    if chargeable == 0:
        return 0
    increments = (chargeable + 14) // 15  # ceil
    return increments * rate_cents_per_15min


def setup_load_for_factor_total(invoice_total_cents: int = 600_000
                                 ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Invoiced load whose Invoice.invoice_total_cents is exactly
    `invoice_total_cents`. Built via spot pricing — DRY_VAN base of
    30,000 + per-unit of 10 cents/unit means a ZIP-difference of
    (invoice_total_cents - 30_000) / 10 yields the desired total.

    Returns (brokerage, invoice). Used to land the Tier C of the
    factoring tier table without juggling detention or accessorials.
    """
    base = SPOT_BASE_CENTS_PER_EQUIPMENT["DRY_VAN"]    # 30_000
    per_unit = SPOT_PER_UNIT_CENTS["DRY_VAN"]          # 10
    assert (invoice_total_cents - base) % per_unit == 0, (
        f"invoice_total_cents={invoice_total_cents} is not reachable "
        f"with DRY_VAN spot math"
    )
    distance = (invoice_total_cents - base) // per_unit
    origin = "00000"
    destination = f"{distance:05d}"
    brokerage, shipper, carrier, quote, load, invoice = setup_invoiced_load(
        origin_zip=origin, destination_zip=destination,
        equipment_type="DRY_VAN",
        detention_minutes=0,
        accessorials=None,
        credit_limit_cents=invoice_total_cents * 4,
    )
    return brokerage, invoice


def setup_contract_quote_at_total(
    flat_rate_cents: int,
    origin_zip: str = "10001",
    destination_zip: str = "20002",
    equipment_type: str = "DRY_VAN",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Brokerage + Shipper + active RateContract + QUOTED quote that
    resolved via CONTRACT path.

    Returns (brokerage, shipper, contract, quoted_quote).
    """
    brokerage, shipper = setup_brokerage_with_shipper(
        credit_limit_cents=10_000_000,
    )
    contract = create_rate_contract(
        brokerage["id"], shipper["id"],
        lane_origin_zip=origin_zip,
        lane_destination_zip=destination_zip,
        equipment_type=equipment_type,
        flat_rate_cents=flat_rate_cents,
    )
    quote = create_quote_request(
        brokerage["id"], shipper["id"],
        origin_zip=origin_zip, destination_zip=destination_zip,
        equipment_type=equipment_type,
        rate_contract_id=contract["id"],
    )
    quoted = quote_quote_request(brokerage["id"], shipper["id"], quote["id"])
    return brokerage, shipper, contract, quoted


def setup_shipper_with_outstanding(
    outstanding_target_cents: int,
    credit_limit_cents: int,
    smartway_required: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Shipper whose outstanding_invoiced_cents has been driven to
    `outstanding_target_cents` by issuing one fully-priced invoice.

    The invoice is built from a SPOT DRY_VAN quote whose ZIP-difference
    yields exactly `outstanding_target_cents - 30_000` (so the linehaul
    is `outstanding_target_cents`, detention is 0, accessorials are 0,
    invoice_total == outstanding_target_cents).

    Returns (brokerage, shipper, invoice).
    """
    base = SPOT_BASE_CENTS_PER_EQUIPMENT["DRY_VAN"]
    per_unit = SPOT_PER_UNIT_CENTS["DRY_VAN"]
    assert (outstanding_target_cents - base) % per_unit == 0, (
        f"outstanding_target_cents={outstanding_target_cents} is not "
        f"reachable with DRY_VAN spot math"
    )
    distance = (outstanding_target_cents - base) // per_unit
    origin = "00000"
    destination = f"{distance:05d}"
    brokerage, shipper, carrier, quote, load, invoice = setup_invoiced_load(
        origin_zip=origin, destination_zip=destination,
        equipment_type="DRY_VAN",
        detention_minutes=0,
        accessorials=None,
        smartway_required=smartway_required,
        smartway_certified=True,
        credit_limit_cents=credit_limit_cents,
    )
    return brokerage, shipper, invoice


def setup_carrier_with_safety_score(
    target_score: int,
    smartway_required: bool = False,
    smartway_certified: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Drive a QUALIFIED carrier's safety_score down to `target_score`
    via cycles of {invoice + dispute resolution}. Each DAMAGE resolution
    on this carrier deducts 100 points; cycles continue until
    safety_score <= target_score.

    Returns (brokerage, shipper, carrier). The carrier may be in
    QUALIFIED or SUSPENDED depending on `target_score` (auto-suspend at
    < 600 per PRD §3.9).

    Note: this builds many loads and is therefore not cheap; call only
    from tests that need a specific safety_score.
    """
    brokerage, shipper, carrier = setup_brokerage_shipper_qualified_carrier(
        smartway_required=smartway_required,
        smartway_certified=smartway_certified,
        credit_limit_cents=10_000_000,
    )
    # Each cycle: build INVOICED load → dispute DAMAGE → resolve full credit.
    # DAMAGE deducts 100 base + 50 if smartway breach.
    deduction = 100 + (
        50 if (smartway_required and not smartway_certified) else 0
    )
    current_score = carrier["safety_score"]
    while current_score > target_score:
        invoice_total = 100_000  # arbitrary small total
        base = SPOT_BASE_CENTS_PER_EQUIPMENT["DRY_VAN"]
        per_unit = SPOT_PER_UNIT_CENTS["DRY_VAN"]
        distance = (invoice_total - base) // per_unit
        destination = f"{distance:05d}"
        # Build a fresh quote + load + invoice on this same carrier.
        quote = create_quote_request(
            brokerage["id"], shipper["id"],
            origin_zip="00000", destination_zip=destination,
            equipment_type="DRY_VAN",
        )
        quoted = quote_quote_request(brokerage["id"], shipper["id"],
                                     quote["id"])
        accepted = accept_quote_request(brokerage["id"], shipper["id"],
                                        quoted["id"])
        load = tender_load(brokerage["id"], shipper["id"], accepted["id"],
                           carrier["id"])
        load = carrier_accept_load(brokerage["id"], shipper["id"],
                                   load["id"], carrier["id"])
        load = depart_load(brokerage["id"], shipper["id"], load["id"],
                           carrier["id"])
        brokerage_now = get_brokerage(brokerage["id"])
        arrive = parse_iso(brokerage_now["clock_now_iso"])
        depart = add_minutes(arrive, 0)
        load = deliver_load(brokerage["id"], shipper["id"], load["id"],
                            carrier["id"],
                            actual_arrive_at=iso_utc(arrive),
                            actual_depart_at=iso_utc(depart))
        inv = invoice_load(brokerage["id"], shipper["id"], load["id"])
        # File full-balance DAMAGE dispute, then start-review, then resolve.
        claim = file_dispute(brokerage["id"], shipper["id"], inv["id"],
                             claim_type="DAMAGE",
                             claimed_cents=inv["invoice_total_cents"])
        claim = start_review_dispute(brokerage["id"], claim["id"])
        resolve_dispute(brokerage["id"], claim["id"],
                        inv["invoice_total_cents"])
        # Re-read carrier.
        carrier_now = get_carrier(brokerage["id"], carrier["id"])
        # If carrier was auto-suspended mid-loop, we may need to /requalify
        # via clock-bypass — but the test scenarios that drive into the
        # < 600 zone are about observing the suspension, not driving past
        # it, so we break out as soon as we hit the target.
        current_score = carrier_now["safety_score"]
        if current_score == 0:
            break  # safety floor reached; cannot go lower
        # If auto-SUSPENDED, future tenders fail; abort the loop so caller
        # observes the post-suspension state.
        if carrier_now["status"] == "SUSPENDED":
            return brokerage, shipper, carrier_now
    return brokerage, shipper, get_carrier(brokerage["id"], carrier["id"])


__all__ = [
    # Tier 0
    "create_brokerage", "get_brokerage",
    "advance_clock_to_iso", "advance_clock_by_minutes",
    "advance_clock_by_days", "sweep_expire_quotes",
    "create_shipper", "get_shipper", "suspend_shipper",
    "create_carrier", "get_carrier", "qualify_carrier",
    "suspend_carrier", "requalify_carrier", "revoke_carrier",
    "create_rate_contract", "terminate_rate_contract",
    # Tier 1
    "create_qualified_carrier",
    # Tier 2
    "create_quote_request", "quote_quote_request",
    "accept_quote_request", "reject_quote_request",
    "create_accepted_quote",
    # Tier 3
    "tender_load", "carrier_accept_load", "depart_load",
    "deliver_load", "invoice_load", "cancel_load_as_broker", "get_load",
    # Tier 4
    "create_accessorial", "approve_accessorial", "deny_accessorial",
    # Tier 5
    "get_invoice", "factor_invoice", "write_off_invoice",
    "file_dispute", "start_review_dispute", "counter_dispute",
    "accept_counter_dispute", "reject_counter_dispute",
    "resolve_dispute", "escalate_dispute", "withdraw_dispute",
    "get_dispute_claim",
    # Tier 6
    "setup_brokerage_with_shipper",
    "setup_brokerage_shipper_qualified_carrier",
    "setup_quoted_quote_request",
    "setup_accepted_quote",
    "setup_tendered_load",
    "setup_accepted_load",
    "setup_in_transit_load",
    "setup_delivered_load",
    "setup_invoiced_load",
    "setup_invoice_in_review_dispute",
    "setup_factored_invoice",
    # Tier 7
    "spot_linehaul_cents",
    "detention_cents",
    "setup_load_for_factor_total",
    "setup_contract_quote_at_total",
    "setup_shipper_with_outstanding",
    "setup_carrier_with_safety_score",
]
