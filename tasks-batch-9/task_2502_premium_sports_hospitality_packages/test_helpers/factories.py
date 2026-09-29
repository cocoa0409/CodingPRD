"""Payload builders for every create/action endpoint.

Each builder emits a valid body with the canonical fixture values and accepts
keyword overrides, so a test that probes one field states only that field.
"""

from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------
# Canonical fixture values, shared by both test families
# --------------------------------------------------------------------------
CANONICAL_EVENT_NAME = "Continental Cup Final"
CANONICAL_SPORT = "FOOTBALL"
CANONICAL_VENUE = "Meridian Stadium"
CANONICAL_ZONES = ["ZONE_A", "ZONE_B"]
CANONICAL_EVENT_DATE = "2027-02-01T15:00:00.000Z"

CANONICAL_RIGHTS_HOLDER = "Meridian FC"
CANONICAL_HOST_NAME = "Alina Petrova"
CANONICAL_HOST_LANGUAGES = ["EN", "IT"]

CORPORATE_CLIENT_NAME = "Northbridge Capital"
PARTNER_CLIENT_NAME = "Aventine Travel Group"
LARGE_CREDIT_LIMIT = 50000000


def event_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": CANONICAL_EVENT_NAME,
        "sport": CANONICAL_SPORT,
        "venue_name": CANONICAL_VENUE,
        "hospitality_zone_codes": list(CANONICAL_ZONES),
        "event_date": CANONICAL_EVENT_DATE,
    }
    payload.update(overrides)
    return payload


def rights_deal_payload(event_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_id": event_id,
        "rights_holder_name": CANONICAL_RIGHTS_HOLDER,
        "inventory_type": "TICKET",
        "contracted_units": 60,
        "guaranteed_minimum_units": 40,
        "unit_cost_cents": 8000,
    }
    payload.update(overrides)
    return payload


def release_tranche_payload(rights_deal_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "rights_deal_id": rights_deal_id,
        "promised_units": 60,
        "promised_release_at": "2026-10-01T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def confirm_tranche_payload(expected_rights_deal_version: int, confirmed_units: int) -> Dict[str, Any]:
    return {
        "confirmed_units": confirmed_units,
        "expected_rights_deal_version": expected_rights_deal_version,
    }


def allocation_block_payload(rights_deal_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "rights_deal_id": rights_deal_id,
        "channel": "CORPORATE",
        "target_units": 40,
        "priority_rank": 1,
    }
    payload.update(overrides)
    return payload


def package_product_payload(event_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_id": event_id,
        "name": "Gold Hospitality",
        "tier": "GOLD",
        "tickets_per_package": 2,
        "hotel_nights": 4,
        "transport_included": True,
        "min_margin_pct": 0.1000,
    }
    payload.update(overrides)
    return payload


def bronze_package_payload(event_id: str, **overrides: Any) -> Dict[str, Any]:
    """The round-numbered BRONZE skeleton used by the breadth probes."""
    payload: Dict[str, Any] = {
        "event_id": event_id,
        "name": "Bronze Hospitality",
        "tier": "BRONZE",
        "tickets_per_package": 2,
        "min_margin_pct": 0.1000,
    }
    payload.update(overrides)
    return payload


def package_component_payload(package_product_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "package_product_id": package_product_id,
        "component_type": "TICKET",
        "descriptor": "Category 1 seat pair",
        "quantity": 2,
        "unit_cost_cents": 50000,
        "markup_pct": 0.2000,
        "sequence_no": 1,
    }
    payload.update(overrides)
    return payload


def publish_payload(expected_package_product_version: int) -> Dict[str, Any]:
    return {"expected_package_product_version": expected_package_product_version}


def client_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": CORPORATE_CLIENT_NAME,
        "client_type": "CORPORATE",
        "credit_limit_cents": LARGE_CREDIT_LIMIT,
    }
    payload.update(overrides)
    return payload


def booking_payload(client_id: str, package_product_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "package_product_id": package_product_id,
        "channel": "CORPORATE",
        "units": 10,
    }
    payload.update(overrides)
    return payload


def allocate_payload(allocation_block_id: str, expected_allocation_block_version: int) -> Dict[str, Any]:
    return {
        "allocation_block_id": allocation_block_id,
        "expected_allocation_block_version": expected_allocation_block_version,
    }


def rebook_payload(target_package_product_id: str) -> Dict[str, Any]:
    return {"target_package_product_id": target_package_product_id}


def pay_payload(amount_cents_paid: int) -> Dict[str, Any]:
    return {"amount_cents_paid": amount_cents_paid}


def hospitality_build_payload(event_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_id": event_id,
        "zone_code": "ZONE_A",
        "service_window_start": "2027-02-01T09:00:00.000Z",
        "service_window_end": "2027-02-01T20:00:00.000Z",
        "space_units": 40,
        "catering_covers": 24,
        "staff_count": 6,
        "build_cost_cents": 120000,
        "catering_cost_cents": 60000,
        "staffing_cost_cents": 40000,
    }
    payload.update(overrides)
    return payload


def on_site_host_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": CANONICAL_HOST_NAME,
        "languages": list(CANONICAL_HOST_LANGUAGES),
    }
    payload.update(overrides)
    return payload


def host_assignment_payload(
    on_site_host_id: str,
    booking_id: str,
    hospitality_build_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "on_site_host_id": on_site_host_id,
        "booking_id": booking_id,
        "hospitality_build_id": hospitality_build_id,
        "shift_start": "2027-02-01T10:00:00.000Z",
        "shift_end": "2027-02-01T18:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# --------------------------------------------------------------------------
# The canonical GOLD component set used by the depth probes (§3.4 pricing).
# sequence_no ASC is the order the pricing pass rounds the lines in.
# --------------------------------------------------------------------------
GOLD_COMPONENT_SPECS: List[Dict[str, Any]] = [
    {
        "component_type": "TICKET",
        "descriptor": "Category 1 seat pair",
        "quantity": 2,
        "unit_cost_cents": 24990,
        "markup_pct": 0.1750,
        "sequence_no": 1,
    },
    {
        "component_type": "HOTEL",
        "descriptor": "Five-star room night",
        "quantity": 4,
        "unit_cost_cents": 13745,
        "markup_pct": 0.0750,
        "sequence_no": 2,
    },
    {
        "component_type": "TRANSPORT",
        "descriptor": "Chauffeured transfer",
        "quantity": 1,
        "unit_cost_cents": 7772,
        "markup_pct": 0.1250,
        "sequence_no": 3,
    },
    {
        "component_type": "EXPERIENCE",
        "descriptor": "Pitch-side pre-match access",
        "quantity": 1,
        "unit_cost_cents": 12340,
        "markup_pct": 0.2250,
        "sequence_no": 4,
    },
]

# The single round-numbered BRONZE line used by the breadth probes.
BRONZE_COMPONENT_SPEC: Dict[str, Any] = {
    "component_type": "TICKET",
    "descriptor": "Category 1 seat pair",
    "quantity": 2,
    "unit_cost_cents": 50000,
    "markup_pct": 0.2000,
    "sequence_no": 1,
}


def gold_component_payloads(package_product_id: str) -> List[Dict[str, Any]]:
    return [dict(spec, package_product_id=package_product_id) for spec in GOLD_COMPONENT_SPECS]


def bronze_component_payload(package_product_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = dict(BRONZE_COMPONENT_SPEC, package_product_id=package_product_id)
    payload.update(overrides)
    return payload


def margin_report_params(variant: Optional[str] = None) -> Optional[Dict[str, Any]]:
    return {"variant": variant} if variant is not None else None
