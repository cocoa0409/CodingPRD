"""Composite setup helpers for the freight-brokerage benchmark.

Every fixture rebuilds its preconditions from scratch via PRD-declared
endpoints. The runner restarts the API server before every individual pytest
test, so each test starts from an empty database — no entities, no clock
state, nothing carried over.

Helpers use `get_success_data()` (the framework's lenient validator) so a
setup failure surfaces as a clear "Setup failed" trace rather than an
opaque assertion deep inside a test.

Identity-threading rule (PRD §2.1): when a fixture creates an entity-backed
caller (Shipper or Carrier), any ownership-gated downstream call uses
`make_shipper_headers(shipper["id"])` / `make_carrier_headers(carrier["id"])`,
never the shared `TEST_USERS` constants.
"""
from typing import List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    activate_contract_rate_payload,
    add_accessorial_payload,
    award_quote_payload,
    create_carrier_payload,
    create_contract_rate_payload,
    create_dispute_claim_payload,
    create_factoring_request_payload,
    create_quote_request_payload,
    create_shipper_payload,
    create_smartway_audit_payload,
    deliver_payload,
    payment_payload,
    pickup_payload,
    resolve_dispute_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_carrier_headers, make_shipper_headers


_BROKER = TEST_USERS["broker_ops_headers"]


# =============================================================================
# Tier 0: Clock control (PRD §3.9)
# =============================================================================


def set_clock(iso8601: str) -> None:
    """Pin the server clock to `iso8601` (PRD §3.9)."""
    res = api_client.set_current_utc(set_clock_payload(iso8601), _BROKER)
    get_success_data(res)


def clock_advance() -> dict:
    """Trigger system-time-driven auto-transitions (PRD §3.9)."""
    res = api_client.clock_advance(_BROKER)
    return get_success_data(res)


# =============================================================================
# Tier 1: Single-entity creation helpers
# =============================================================================


def create_shipper(**overrides) -> dict:
    res = api_client.create_shipper(create_shipper_payload(**overrides), _BROKER)
    return get_success_data(res)


def create_carrier(**overrides) -> dict:
    """Create a Carrier in PENDING (PRD §3.1)."""
    res = api_client.create_carrier(create_carrier_payload(**overrides), _BROKER)
    return get_success_data(res)


def create_qualified_carrier(**overrides) -> dict:
    """Create + qualify a Carrier; returns the post-qualify Carrier (PRD §3.1)."""
    carrier = create_carrier(**overrides)
    res = api_client.qualify_carrier(carrier["id"], _BROKER)
    return get_success_data(res)


def create_active_contract(shipper_id: str, **overrides) -> dict:
    """Create + activate a ContractRate. Returns the ACTIVE row (PRD §3.2)."""
    created = get_success_data(
        api_client.create_contract_rate(
            create_contract_rate_payload(shipper_id, **overrides), _BROKER
        )
    )
    activated = get_success_data(
        api_client.activate_contract_rate(
            created["id"],
            activate_contract_rate_payload(created["version"]),
            _BROKER,
        )
    )
    return activated


# =============================================================================
# Tier 2: Quote → Award pipeline
# =============================================================================


def create_quote(shipper_id: str, **overrides) -> dict:
    """Create an OPEN QuoteRequest (PRD §3.3)."""
    res = api_client.create_quote_request(
        create_quote_request_payload(shipper_id, **overrides), _BROKER
    )
    return get_success_data(res)


def award_quote_to_carrier(quote: dict, carrier_id: str) -> dict:
    """Award an OPEN quote; returns the freshly created Load (PRD §3.4)."""
    res = api_client.award_quote(
        quote["id"],
        award_quote_payload(carrier_id, quote["version"]),
        _BROKER,
    )
    return get_success_data(res)


# =============================================================================
# Tier 3: Full lifecycle to DELIVERED / INVOICED
# =============================================================================


def setup_awarded_load(
    *,
    pickup_window_start_utc: str = "2026-06-10T08:00:00Z",
    pickup_window_end_utc: str = "2026-06-10T18:00:00Z",
    distance_miles: int = 400,
    requested_equipment: str = "DRY_VAN",
    requires_smartway: bool = False,
    contract_overrides: Optional[dict] = None,
    use_contract: bool = True,
    smartway_tier: str = "NONE",
    safety_score: float = 30.0,
    insurance_expiry_utc: str = "2027-12-31T00:00:00Z",
    pin_clock_utc: Optional[str] = "2026-06-01T00:00:00Z",
) -> Tuple[dict, dict, dict, dict, Optional[dict]]:
    """Build a full chain shipper → carrier qualified → (optional contract) →
    OPEN quote → AWARDED load. Returns (shipper, carrier, quote, load, contract).

    Uses the PRD-defined sequence of POSTs and respects identity threading
    on the Carrier role for pickup/deliver callers downstream.

    Pins the server's logical clock to `pin_clock_utc` (default 2026-06-01)
    before activating the contract so PRD §3.2 "effective window must bracket
    current server time at activation" is satisfied for the default contract
    window 2026-01-01 → 2027-01-01. The pinned moment is also strictly earlier
    than the default pickup window 2026-06-10, satisfying PRD §3.3
    "pickup_window_start_utc must be strictly later than the current server
    time". Set `pin_clock_utc=None` to leave the clock alone.
    """
    if pin_clock_utc is not None:
        set_clock(pin_clock_utc)
    shipper = create_shipper()
    carrier = create_qualified_carrier(
        smartway_tier=smartway_tier,
        safety_score=safety_score,
        insurance_expiry_utc=insurance_expiry_utc,
    )
    contract = None
    if use_contract:
        contract = create_active_contract(
            shipper["id"], **(contract_overrides or {})
        )

    quote_payload_overrides = {
        "pickup_window_start_utc": pickup_window_start_utc,
        "pickup_window_end_utc": pickup_window_end_utc,
        "distance_miles": distance_miles,
        "requested_equipment": requested_equipment,
    }
    if requires_smartway:
        quote_payload_overrides["requires_smartway"] = True
    quote = create_quote(shipper["id"], **quote_payload_overrides)
    load = award_quote_to_carrier(quote, carrier["id"])
    # Re-fetch quote so caller can observe AWARDED status if needed.
    return shipper, carrier, quote, load, contract


def deliver_load(load: dict, carrier: dict, *,
                 actual_pickup_at_utc: str = "2026-06-10T09:00:00Z",
                 actual_delivery_at_utc: str = "2026-06-11T09:00:00Z") -> dict:
    """Walk load AWARDED → IN_TRANSIT → DELIVERED (PRD §3.5).

    Uses the carrier-scoped headers so the ownership check passes
    (PRD §2.1).
    """
    headers = make_carrier_headers(carrier["id"])
    get_success_data(
        api_client.pickup_load(load["id"], pickup_payload(actual_pickup_at_utc), headers)
    )
    delivered = get_success_data(
        api_client.deliver_load(
            load["id"], deliver_payload(actual_delivery_at_utc), headers
        )
    )
    return delivered


def setup_delivered_load(**overrides) -> Tuple[dict, dict, dict, dict, Optional[dict]]:
    """Shipper + qualified carrier + optional contract + AWARDED load picked
    up and delivered. Returns (shipper, carrier, quote, load_after_deliver,
    contract)."""
    pickup_at = overrides.pop("actual_pickup_at_utc", "2026-06-10T09:00:00Z")
    deliver_at = overrides.pop("actual_delivery_at_utc", "2026-06-11T09:00:00Z")
    shipper, carrier, quote, load, contract = setup_awarded_load(**overrides)
    load_delivered = deliver_load(
        load, carrier,
        actual_pickup_at_utc=pickup_at,
        actual_delivery_at_utc=deliver_at,
    )
    return shipper, carrier, quote, load_delivered, contract


def invoice_load(load_id: str) -> dict:
    """Transition a DELIVERED load → INVOICED; returns the new Invoice
    (PRD §3.6)."""
    return get_success_data(api_client.invoice_load(load_id, _BROKER))


def setup_invoiced_load(**overrides) -> Tuple[dict, dict, dict, dict, dict, Optional[dict]]:
    """Full pipeline through INVOICED. Returns (shipper, carrier, quote,
    load, invoice, contract)."""
    shipper, carrier, quote, load, contract = setup_delivered_load(**overrides)
    invoice = invoice_load(load["id"])
    # Re-fetch load to observe INVOICED status if needed.
    load_after = get_success_data(api_client.get_load(load["id"], _BROKER))
    return shipper, carrier, quote, load_after, invoice, contract


# =============================================================================
# Tier 4: Factoring lifecycle
# =============================================================================


def open_factoring_request(invoice_id: str, carrier_id: str,
                           factoring_fee_pct: float = 2.0) -> dict:
    """Create a FactoringRequest in REQUESTED (PRD §3.8). Uses the carrier's
    own identity, because PRD §2.1 says POST /factoring-requests is a Carrier
    exclusive operation and the body's carrier_id must match the caller."""
    headers = make_carrier_headers(carrier_id)
    res = api_client.create_factoring_request(
        create_factoring_request_payload(invoice_id, carrier_id, factoring_fee_pct),
        headers,
    )
    return get_success_data(res)


def setup_advanced_factoring(**overrides) -> Tuple[dict, dict, dict, dict, dict, dict, Optional[dict]]:
    """Pipeline through FactoringRequest in ADVANCED — Invoice.factored=true.
    Returns (shipper, carrier, quote, load, invoice, factoring_request, contract).

    Picks a `factoring_fee_pct` that satisfies PRD §3.8's safety-tiered floor
    for the carrier's safety_score so the FactoringRequest creation does not
    trip ERR_FACTORING_FEE_BELOW_MIN. Tests that need to exercise the floor
    explicitly should call `open_factoring_request` directly with a chosen fee.
    """
    shipper, carrier, quote, load, invoice, contract = setup_invoiced_load(**overrides)
    safe = float(carrier.get("safety_score", 30.0))
    fee = _floor_fee_for_safety(safe)
    fr = open_factoring_request(invoice["id"], carrier["id"], factoring_fee_pct=fee)
    get_success_data(api_client.approve_factoring(fr["id"], _BROKER))
    advanced = get_success_data(api_client.advance_factoring(fr["id"], _BROKER))
    return shipper, carrier, quote, load, invoice, advanced, contract


def _floor_fee_for_safety(safety_score: float) -> float:
    """Return the PRD §3.8 safety-tiered minimum factoring_fee_pct for a
    carrier with the given safety_score. Used by setup_advanced_factoring so
    the chain does not trip ERR_FACTORING_FEE_BELOW_MIN under default scoring."""
    if safety_score < 25.0:
        return 2.0
    if safety_score < 50.0:
        return 2.5
    return 3.5


# =============================================================================
# Tier 5: Dispute lifecycle
# =============================================================================


def open_dispute(invoice_id: str, shipper_id: str,
                 claim_type: str = "OVERCHARGE",
                 claimed_amount_cents: int = 5000) -> dict:
    """Open a DisputeClaim against an Invoice (PRD §3.7).

    Uses the Shipper-scoped headers because POST /dispute-claims is a
    Shipper exclusive op (PRD §2.1).
    """
    headers = make_shipper_headers(shipper_id)
    res = api_client.create_dispute_claim(
        create_dispute_claim_payload(invoice_id, claim_type, claimed_amount_cents),
        headers,
    )
    return get_success_data(res)


def resolve_dispute(dispute_id: str, resolution_kind: str,
                    resolution_amount_cents: int) -> dict:
    """Resolve an OPEN dispute (PRD §3.7) — BrokerOps op."""
    res = api_client.resolve_dispute(
        dispute_id,
        resolve_dispute_payload(resolution_kind, resolution_amount_cents),
        _BROKER,
    )
    return get_success_data(res)


def withdraw_dispute(dispute_id: str, shipper_id: str) -> dict:
    """Withdraw a dispute (PRD §3.7) — Shipper op."""
    headers = make_shipper_headers(shipper_id)
    res = api_client.withdraw_dispute(dispute_id, headers)
    return get_success_data(res)


# =============================================================================
# Tier 6: Accessorials & payments
# =============================================================================


def attach_accessorial(load_id: str, code: str, amount_cents: int,
                       note: Optional[str] = None) -> dict:
    """Attach an Accessorial line item to a DELIVERED load (PRD §3.5)."""
    res = api_client.add_accessorial(
        load_id, add_accessorial_payload(code, amount_cents, note), _BROKER
    )
    return get_success_data(res)


def pay_invoice(invoice_id: str, amount_cents: int) -> dict:
    """Apply a cash receipt against an invoice (PRD §3.6)."""
    res = api_client.record_payment(invoice_id, payment_payload(amount_cents), _BROKER)
    return get_success_data(res)


# =============================================================================
# Convenience getters that wrap GETs in the lenient validator (handy when a
# test needs to re-read a row after a cascade).
# =============================================================================


def get_shipper(shipper_id: str) -> dict:
    return get_success_data(api_client.get_shipper(shipper_id, _BROKER))


def get_load(load_id: str) -> dict:
    return get_success_data(api_client.get_load(load_id, _BROKER))


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, _BROKER))


def get_factoring_request(fr_id: str) -> dict:
    return get_success_data(api_client.get_factoring_request(fr_id, _BROKER))


def get_dispute(dc_id: str) -> dict:
    return get_success_data(api_client.get_dispute_claim(dc_id, _BROKER))


def get_quote(quote_id: str) -> dict:
    return get_success_data(api_client.get_quote_request(quote_id, _BROKER))


def get_carrier(carrier_id: str) -> dict:
    return get_success_data(api_client.get_carrier(carrier_id, _BROKER))


def get_contract_rate(cr_id: str) -> dict:
    return get_success_data(api_client.get_contract_rate(cr_id, _BROKER))
