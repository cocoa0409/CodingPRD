"""Composite setup builders.

The server is restarted with an empty store before every individual test, so
every precondition has to be built through declared endpoints.  The builders
below are layered: each tier calls the tier beneath it, so a test that needs
a converted referral placement does not have to re-key a whole concierge
network by hand.

Each builder returns the created rows so that ownership-gated calls can be
made with the right identity.  A `FeedIntegrator`, `Resident`,
`ProviderAgent` or `PartnerAgent` header must always be built from the
returned row's `id` with the matching `make_*_headers` helper.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_STARTUP_DEFAULT
from .test_users import (
    make_compliance_headers,
    make_gateway_headers,
    make_move_ops_headers,
    make_partner_agent_headers,
    make_platform_admin_headers,
    make_provider_agent_headers,
)
from .types import ConsentScope, UtilityType


# ---------------------------------------------------------------------------
# Tier 0 — the logical clock
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, to_iso8601: str) -> str:
    """Move the logical clock and return the new `current_utc`."""
    data = get_success_data(
        api.set_clock(f.clock_payload(to_iso8601), make_platform_admin_headers())
    )
    return data["current_utc"]


def reset_clock(api: ApiClient) -> str:
    """Pin the clock at the mandatory startup default of 2026-08-01T00:00:00Z."""
    return set_clock(api, CLOCK_STARTUP_DEFAULT)


# ---------------------------------------------------------------------------
# Tier 1 — individual reference rows (PRD 3.1)
# ---------------------------------------------------------------------------
def create_feed_source(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register one feed source entitled to push move records."""
    return get_success_data(
        api.create_feed_source(f.feed_source_payload(**overrides), make_platform_admin_headers())
    )


def create_resident(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create the resident who is moving."""
    return get_success_data(
        api.create_resident(f.resident_payload(**overrides), make_platform_admin_headers())
    )


def create_second_resident(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create a second resident sharing no identity signal with the first."""
    return get_success_data(
        api.create_resident(f.second_resident_payload(**overrides), make_platform_admin_headers())
    )


def create_address(api: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create one service address from an explicit payload."""
    return get_success_data(api.create_service_address(payload, make_platform_admin_headers()))


def create_origin_address(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create the address being vacated."""
    return create_address(api, f.origin_address_payload(**overrides))


def create_destination_address(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create the address being occupied."""
    return create_address(api, f.destination_address_payload(**overrides))


def create_provider(api: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Register one utility provider from an explicit payload."""
    return get_success_data(api.create_utility_provider(payload, make_platform_admin_headers()))


def create_territory(api: ApiClient, provider_id: str, **overrides: Any) -> Dict[str, Any]:
    """Declare that a provider serves a postal code over an effective interval."""
    return get_success_data(
        api.create_territory(f.territory_payload(provider_id, **overrides), make_platform_admin_headers())
    )


def create_partner(api: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Register one referral partner from an explicit payload."""
    return get_success_data(api.create_referral_partner(payload, make_platform_admin_headers()))


# ---------------------------------------------------------------------------
# Tier 2 — a configured concierge network
# ---------------------------------------------------------------------------
def build_network(
    api: ApiClient,
    clock: Optional[str] = CLOCK_STARTUP_DEFAULT,
    feed_overrides: Optional[Dict[str, Any]] = None,
    resident_overrides: Optional[Dict[str, Any]] = None,
    destination_overrides: Optional[Dict[str, Any]] = None,
    origin_overrides: Optional[Dict[str, Any]] = None,
    electric_overrides: Optional[Dict[str, Any]] = None,
    water_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Register the reference data a move needs before it can be ingested.

    Creates one feed source, one resident, an origin and a destination
    address, an ELECTRIC provider on a CREDIT_SCORE_BASED policy and a WATER
    provider needing no credit check, and a default-carrier territory row for
    each of them covering the destination postal code.
    """
    if clock is not None:
        set_clock(api, clock)
    feed = create_feed_source(api, **(feed_overrides or {}))
    resident = create_resident(api, **(resident_overrides or {}))
    origin = create_origin_address(api, **(origin_overrides or {}))
    destination = create_destination_address(api, **(destination_overrides or {}))
    electric = create_provider(api, f.electric_provider_payload(**(electric_overrides or {})))
    water = create_provider(api, f.water_provider_payload(**(water_overrides or {})))
    electric_territory = create_territory(
        api, electric["id"], postal_code=destination["postal_code"], state_code=destination["state_code"]
    )
    water_territory = create_territory(
        api, water["id"], postal_code=destination["postal_code"], state_code=destination["state_code"]
    )
    return {
        "feed_source": feed,
        "resident": resident,
        "origin_address": origin,
        "destination_address": destination,
        "electric_provider": electric,
        "water_provider": water,
        "electric_territory": electric_territory,
        "water_territory": water_territory,
    }


def add_internet_partner(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Add the REV_SHARE_PCT internet partner to an existing network."""
    return create_partner(api, f.internet_partner_payload(**overrides))


def add_insurance_partner(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Add the FLAT_BOUNTY insurance partner to an existing network."""
    return create_partner(api, f.insurance_partner_payload(**overrides))


# ---------------------------------------------------------------------------
# Tier 3 — a move at a chosen point in its lifecycle
# ---------------------------------------------------------------------------
def ingest_move(
    api: ApiClient,
    network: Dict[str, Any],
    move_date: str = "2026-08-20",
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Ingest a move record against a built network; it lands in INTAKE."""
    payload = f.move_payload(
        network["resident"]["id"],
        network["feed_source"]["id"],
        network["origin_address"]["id"],
        network["destination_address"]["id"],
        move_date=move_date,
        **overrides,
    )
    return get_success_data(api.create_move(payload, headers or make_move_ops_headers()))


def grant_consent(
    api: ApiClient,
    resident_id: str,
    scope: str,
    expected_resident_version: int,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record one GRANTED consent record for a scope, under resident OCC."""
    payload = f.consent_payload(scope, expected_resident_version, **overrides)
    return get_success_data(
        api.create_consent_record(resident_id, payload, headers or make_move_ops_headers())
    )


def grant_consents(
    api: ApiClient,
    resident_id: str,
    scopes: List[str],
    starting_version: int = 1,
) -> Dict[str, Dict[str, Any]]:
    """Grant several consent scopes in sequence, threading the resident version.

    Each create increments the resident's `version` by one, which is why the
    expected version has to advance between calls.
    """
    granted: Dict[str, Dict[str, Any]] = {}
    version = starting_version
    for scope in scopes:
        granted[scope] = grant_consent(api, resident_id, scope, version)
        version += 1
    return granted


def full_consent_move(
    api: ApiClient,
    network: Optional[Dict[str, Any]] = None,
    move_date: str = "2026-08-20",
    scopes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Ingest a move whose resident holds every consent scope the flow needs."""
    net = network if network is not None else build_network(api)
    scopes = scopes or [
        ConsentScope.UTILITY_SETUP.value,
        ConsentScope.USPS_FILING.value,
        ConsentScope.PARTNER_MARKETING.value,
    ]
    consents = grant_consents(api, net["resident"]["id"], scopes)
    move = ingest_move(api, net, move_date=move_date)
    return {**net, "move": move, "consents": consents}


def pass_identity_by_kba(
    api: ApiClient, move_id: str, score: int = 720
) -> Dict[str, Any]:
    """Open a KBA attempt and have the vendor answer with a passing score.

    The passing bar is 700, and a pass advances the move to VERIFIED.
    """
    verification = get_success_data(
        api.create_identity_verification(move_id, f.kba_attempt_payload(), make_move_ops_headers())
    )
    return get_success_data(
        api.post_kba_result(
            verification["id"], f.kba_result_payload(score=score), make_gateway_headers()
        )
    )


def pass_identity_by_override(
    api: ApiClient, move_id: str, reviewer_user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Record a compliance manual override, stamping `reviewer_user_id`."""
    headers = (
        make_compliance_headers(reviewer_user_id) if reviewer_user_id else make_compliance_headers()
    )
    return get_success_data(
        api.create_identity_verification(move_id, f.manual_override_payload(), headers)
    )


def verified_move(
    api: ApiClient,
    network: Optional[Dict[str, Any]] = None,
    move_date: str = "2026-08-20",
    scopes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """A move that has cleared identity through the vendor and sits in VERIFIED."""
    bundle = full_consent_move(api, network=network, move_date=move_date, scopes=scopes)
    verification = pass_identity_by_kba(api, bundle["move"]["id"])
    move = get_success_data(api.get_move(bundle["move"]["id"], make_move_ops_headers()))
    return {**bundle, "move": move, "verification": verification}


# ---------------------------------------------------------------------------
# Tier 4 — service orders (PRD 3.5, 3.6)
# ---------------------------------------------------------------------------
def run_mapping(
    api: ApiClient,
    move_id: str,
    utility_types: Optional[List[str]] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Run provider mapping, which creates one order per covered pairing."""
    payload = f.mapping_payload(
        utility_types or [UtilityType.ELECTRIC.value, UtilityType.WATER.value], **overrides
    )
    return get_success_data(
        api.run_provider_mapping(move_id, payload, headers or make_move_ops_headers())
    )


def orders_for_move(api: ApiClient, move_id: str, **filters: Any) -> List[Dict[str, Any]]:
    """List a move's service orders in created_at ascending order."""
    response = api.list_utility_orders(make_move_ops_headers(), move_id=move_id, **filters)
    return get_success_data(response)


def order_of_type(api: ApiClient, move_id: str, utility_type: str) -> Dict[str, Any]:
    """Return the move's single service order for one utility type."""
    rows = orders_for_move(api, move_id, utility_type=utility_type)
    assert rows, f"no service order was created for {utility_type}"
    return rows[0]


def mapped_move(
    api: ApiClient,
    network: Optional[Dict[str, Any]] = None,
    move_date: str = "2026-08-20",
    utility_types: Optional[List[str]] = None,
    scopes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """A VERIFIED move driven to SCHEDULING with its service orders created."""
    bundle = verified_move(api, network=network, move_date=move_date, scopes=scopes)
    move = run_mapping(api, bundle["move"]["id"], utility_types=utility_types)
    orders = orders_for_move(api, bundle["move"]["id"])
    by_type = {order["utility_type"]: order for order in orders}
    return {**bundle, "move": move, "orders": orders, "orders_by_type": by_type}


def schedule_order(
    api: ApiClient,
    order_id: str,
    requested_service_date: str = "2026-08-05",
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Commit a service window on a DRAFT order and record the account data."""
    payload = f.schedule_payload(requested_service_date=requested_service_date, **overrides)
    return get_success_data(api.schedule_order(order_id, payload, headers or make_move_ops_headers()))


def dispatch_credit_check(
    api: ApiClient, order_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Dispatch a credit-check handoff, freezing the order's readiness snapshot."""
    return get_success_data(
        api.create_credit_check(order_id, f.credit_check_payload(**overrides), headers or make_move_ops_headers())
    )


def answer_bureau(api: ApiClient, handoff_id: str, score: int) -> Dict[str, Any]:
    """Have the bureau answer an open handoff with a score."""
    return get_success_data(
        api.post_bureau_response(handoff_id, f.bureau_response_payload(score), make_gateway_headers())
    )


def order_with_bureau_score(
    api: ApiClient,
    score: int,
    network: Optional[Dict[str, Any]] = None,
    utility_type: str = UtilityType.ELECTRIC.value,
    bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A mapped move whose credit-checked order has received a bureau score.

    A score of 640 or above clears the order, 580 through 639 leaves a deposit
    due, and 579 or below declines it.
    """
    base = bundle if bundle is not None else mapped_move(api, network=network)
    order = base["orders_by_type"][utility_type]
    handoff = dispatch_credit_check(api, order["id"])
    handoff = answer_bureau(api, handoff["id"], score)
    order = get_success_data(api.get_utility_order(order["id"], make_move_ops_headers()))
    move = get_success_data(api.get_move(base["move"]["id"], make_move_ops_headers()))
    return {**base, "move": move, "handoff": handoff, "order": order}


def active_order(
    api: ApiClient,
    network: Optional[Dict[str, Any]] = None,
    utility_type: str = UtilityType.WATER.value,
    requested_service_date: str = "2026-08-05",
    activation_instant: str = "2026-08-05T09:00:00Z",
) -> Dict[str, Any]:
    """An order scheduled and then activated by its own provider's agent.

    Activation needs the logical clock to have reached `scheduled_window_start`
    and needs a credit posture of NOT_REQUIRED, CLEARED or DEPOSIT_PAID.
    """
    base = mapped_move(api, network=network)
    order = base["orders_by_type"][utility_type]
    schedule_order(api, order["id"], requested_service_date=requested_service_date)
    set_clock(api, activation_instant)
    activated = get_success_data(
        api.activate_order(
            order["id"], f.activation_payload(), make_provider_agent_headers(order["provider_id"])
        )
    )
    move = get_success_data(api.get_move(base["move"]["id"], make_move_ops_headers()))
    return {**base, "move": move, "order": activated}


def attention_required_move(
    api: ApiClient,
    network: Optional[Dict[str, Any]] = None,
    utility_type: str = UtilityType.WATER.value,
    requested_service_date: str = "2026-08-05",
) -> Dict[str, Any]:
    """A move parked in ATTENTION_REQUIRED by a reported provision failure."""
    base = mapped_move(api, network=network)
    order = base["orders_by_type"][utility_type]
    schedule_order(api, order["id"], requested_service_date=requested_service_date)
    failed = get_success_data(
        api.report_provision_failure(
            order["id"], f.provision_failure_payload(), make_provider_agent_headers(order["provider_id"])
        )
    )
    move = get_success_data(api.get_move(base["move"]["id"], make_move_ops_headers()))
    return {**base, "move": move, "failed_order": failed}


# ---------------------------------------------------------------------------
# Tier 5 — filings, placements and the ledger (PRD 3.7, 3.8)
# ---------------------------------------------------------------------------
def draft_filing(
    api: ApiClient,
    move_id: str,
    forward_start_date: str = "2026-08-20",
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft a postal change-of-address filing against a verified move."""
    payload = f.filing_payload(forward_start_date=forward_start_date, **overrides)
    return get_success_data(api.create_filing(move_id, payload, headers or make_move_ops_headers()))


def submit_filing(
    api: ApiClient, filing_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Submit or resubmit a filing to the postal service."""
    return get_success_data(api.submit_filing(filing_id, {}, headers or make_move_ops_headers()))


def submitted_filing(
    api: ApiClient,
    bundle: Optional[Dict[str, Any]] = None,
    forward_start_date: str = "2026-08-01",
) -> Dict[str, Any]:
    """A filing that has reached SUBMITTED, lifting the readiness filing component."""
    base = bundle if bundle is not None else verified_move(api)
    filing = draft_filing(api, base["move"]["id"], forward_start_date=forward_start_date)
    filing = submit_filing(api, filing["id"])
    return {**base, "filing": filing}


def confirmed_filing(
    api: ApiClient,
    bundle: Optional[Dict[str, Any]] = None,
    forward_start_date: str = "2026-08-01",
) -> Dict[str, Any]:
    """A filing the postal service has confirmed, with a confirmation code."""
    base = submitted_filing(api, bundle=bundle, forward_start_date=forward_start_date)
    filing = get_success_data(
        api.post_usps_response(
            base["filing"]["id"], f.usps_confirmation_payload(), make_gateway_headers()
        )
    )
    return {**base, "filing": filing}


def rejected_filing(
    api: ApiClient,
    bundle: Optional[Dict[str, Any]] = None,
    forward_start_date: str = "2026-08-01",
) -> Dict[str, Any]:
    """A filing the postal service has rejected, parking the move for attention."""
    base = submitted_filing(api, bundle=bundle, forward_start_date=forward_start_date)
    filing = get_success_data(
        api.post_usps_response(
            base["filing"]["id"], f.usps_rejection_payload(), make_gateway_headers()
        )
    )
    return {**base, "filing": filing}


def place_referral(
    api: ApiClient,
    move_id: str,
    partner_id: str,
    expected_move_version: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Place a partner referral against a move under move OCC."""
    payload = f.placement_payload(partner_id, expected_move_version)
    return get_success_data(api.create_placement(move_id, payload, headers or make_move_ops_headers()))


def placed_referral(
    api: ApiClient,
    bundle: Optional[Dict[str, Any]] = None,
    partner: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A move carrying one referral placement in PLACED."""
    base = bundle if bundle is not None else verified_move(api)
    prt = partner if partner is not None else add_internet_partner(api)
    move = get_success_data(api.get_move(base["move"]["id"], make_move_ops_headers()))
    placement = place_referral(api, move["id"], prt["id"], move["version"])
    return {**base, "move": move, "partner": prt, "placement": placement}


def accepted_referral(
    api: ApiClient,
    bundle: Optional[Dict[str, Any]] = None,
    partner: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A referral the owning partner has accepted, setting the acceptance anchor."""
    base = placed_referral(api, bundle=bundle, partner=partner)
    placement = get_success_data(
        api.accept_placement(
            base["placement"]["id"], {}, make_partner_agent_headers(base["partner"]["id"])
        )
    )
    return {**base, "placement": placement}


def converted_referral(
    api: ApiClient,
    gross_revenue_cents: int = 100000,
    bundle: Optional[Dict[str, Any]] = None,
    partner: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A converted referral, which posts the provisional accrual and feed share."""
    base = accepted_referral(api, bundle=bundle, partner=partner)
    placement = get_success_data(
        api.convert_placement(
            base["placement"]["id"],
            f.conversion_payload(gross_revenue_cents),
            make_partner_agent_headers(base["partner"]["id"]),
        )
    )
    return {**base, "placement": placement}


def ledger_for_placement(api: ApiClient, placement_id: str) -> List[Dict[str, Any]]:
    """List a placement's ledger entries in posting sequence."""
    return get_success_data(
        api.list_ledger_entries(make_platform_admin_headers(), placement_id=placement_id)
    )


def read_feed_source(api: ApiClient, feed_source_id: str) -> Dict[str, Any]:
    """Re-read a feed source, including its recomputed accrued share."""
    return get_success_data(api.get_feed_source(feed_source_id, make_platform_admin_headers()))


def read_move(api: ApiClient, move_id: str) -> Dict[str, Any]:
    """Re-read a move and all of its derived fields."""
    return get_success_data(api.get_move(move_id, make_move_ops_headers()))


def read_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    """Re-read a service order and both of its state dimensions."""
    return get_success_data(api.get_utility_order(order_id, make_move_ops_headers()))


def read_resident(api: ApiClient, resident_id: str) -> Dict[str, Any]:
    """Re-read a resident, including the version that guards consent creation."""
    return get_success_data(api.get_resident(resident_id, make_platform_admin_headers()))


def read_readiness(api: ApiClient, move_id: str, **params: Any) -> Dict[str, Any]:
    """Read the computed readiness breakdown for a move."""
    return get_success_data(api.get_move_readiness(move_id, make_move_ops_headers(), **params))
