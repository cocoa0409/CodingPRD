"""Payload builders.

Each builder returns a complete, valid request body and accepts keyword
overrides, so a test states only the field it cares about.  Identifier-bearing
fields that must be unique across a run (product sku, family code, channel code,
record locator, flight number) get a short random suffix unless the caller pins
them explicitly.
"""

import uuid
from typing import Any, Dict, List, Optional


def unique_suffix(width: int = 6) -> str:
    """A short uppercase token, unique enough for one test run."""
    return uuid.uuid4().hex[:width].upper()


# ---------------------------------------------------------------------------
# Catalog products
# ---------------------------------------------------------------------------
def ancillary_product_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "sku": f"BAG_CHECKED_{unique_suffix(4)}",
        "name": "First checked bag",
        "category": "BAGGAGE",
        "list_price_cents": 3500,
        "tax_treatment": "TAXABLE_SERVICE",
        "revenue_class": "NON_AIR",
        "revenue_account_code": "4100",
        "refundable": False,
        "disclosable_fee": True,
        "product_state": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def checked_bag_product_payload(**overrides) -> Dict[str, Any]:
    """The BAG_CHECKED_1 catalog entry: BAGGAGE, 3500 cents, taxable service."""
    return ancillary_product_payload(
        **{
            "sku": "BAG_CHECKED_1",
            "name": "First checked bag",
            "category": "BAGGAGE",
            "list_price_cents": 3500,
            "tax_treatment": "TAXABLE_SERVICE",
            "revenue_class": "NON_AIR",
            "revenue_account_code": "4100",
            "refundable": False,
            "disclosable_fee": True,
            **overrides,
        }
    )


def standard_seat_product_payload(**overrides) -> Dict[str, Any]:
    """The SEAT_STANDARD catalog entry: SEAT, 1900 cents, refundable."""
    return ancillary_product_payload(
        **{
            "sku": "SEAT_STANDARD",
            "name": "Standard seat",
            "category": "SEAT",
            "list_price_cents": 1900,
            "tax_treatment": "TAXABLE_SERVICE",
            "revenue_class": "NON_AIR",
            "revenue_account_code": "4200",
            "refundable": True,
            "disclosable_fee": True,
            **overrides,
        }
    )


def extra_legroom_seat_product_payload(**overrides) -> Dict[str, Any]:
    """The SEAT_EXTRA_LEGROOM catalog entry: SEAT, 4200 cents, refundable."""
    return ancillary_product_payload(
        **{
            "sku": "SEAT_EXTRA_LEGROOM",
            "name": "Extra legroom seat",
            "category": "SEAT",
            "list_price_cents": 4200,
            "tax_treatment": "TAXABLE_SERVICE",
            "revenue_class": "NON_AIR",
            "revenue_account_code": "4200",
            "refundable": True,
            "disclosable_fee": True,
            **overrides,
        }
    )


def priority_boarding_product_payload(**overrides) -> Dict[str, Any]:
    """The PRIORITY_BOARDING catalog entry: BOARDING, 1250 cents."""
    return ancillary_product_payload(
        **{
            "sku": "PRIORITY_BOARDING",
            "name": "Priority boarding",
            "category": "BOARDING",
            "list_price_cents": 1250,
            "tax_treatment": "TAXABLE_SERVICE",
            "revenue_class": "NON_AIR",
            "revenue_account_code": "4400",
            "refundable": False,
            "disclosable_fee": True,
            **overrides,
        }
    )


def wifi_product_payload(**overrides) -> Dict[str, Any]:
    """The WIFI_FULL_FLIGHT catalog entry: ONBOARD, 750 cents."""
    return ancillary_product_payload(
        **{
            "sku": "WIFI_FULL_FLIGHT",
            "name": "Full flight wifi",
            "category": "ONBOARD",
            "list_price_cents": 750,
            "tax_treatment": "TAXABLE_SERVICE",
            "revenue_class": "NON_AIR",
            "revenue_account_code": "4500",
            "refundable": False,
            "disclosable_fee": True,
            **overrides,
        }
    )


def change_flex_product_payload(**overrides) -> Dict[str, Any]:
    """The CHANGE_FLEX catalog entry: CHANGE, 7500 cents, taxable transport."""
    return ancillary_product_payload(
        **{
            "sku": "CHANGE_FLEX",
            "name": "Flexible change",
            "category": "CHANGE",
            "list_price_cents": 7500,
            "tax_treatment": "TAXABLE_TRANSPORT",
            "revenue_class": "AIR_TRANSPORT_RELATED",
            "revenue_account_code": "4300",
            "refundable": False,
            "disclosable_fee": True,
            **overrides,
        }
    )


# ---------------------------------------------------------------------------
# Fare families and their attributes
# ---------------------------------------------------------------------------
def fare_family_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "code": f"ECO_{unique_suffix(5)}",
        "name": "Economy Lite",
        "cabin_class": "ECONOMY",
        "base_fare_cents": 12000,
        "bundle_price_cents": 14000,
        "refundability": "NON_REFUNDABLE",
        "change_fee_cents": 7500,
        "boarding_priority_tier": 4,
    }
    payload.update(overrides)
    return payload


def eco_lite_family_payload(**overrides) -> Dict[str, Any]:
    """ECO_LITE: ECONOMY, base 12000, bundle 14000, change fee 7500."""
    return fare_family_payload(
        **{
            "code": "ECO_LITE",
            "name": "Economy Lite",
            "cabin_class": "ECONOMY",
            "base_fare_cents": 12000,
            "bundle_price_cents": 14000,
            "refundability": "NON_REFUNDABLE",
            "change_fee_cents": 7500,
            "boarding_priority_tier": 4,
            **overrides,
        }
    )


def family_attribute_payload(ancillary_product_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "ancillary_product_id": ancillary_product_id,
        "inclusion": "INCLUDED",
        "included_quantity": 1,
    }
    payload.update(overrides)
    return payload


def review_decision_payload(decision: str = "APPROVE", **overrides) -> Dict[str, Any]:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def status_change_payload(target_status: str, reason: str = "Commercial decision", **overrides) -> Dict[str, Any]:
    payload = {"target_status": target_status, "reason": reason}
    payload.update(overrides)
    return payload


def phase_advance_payload(target_phase: str, **overrides) -> Dict[str, Any]:
    payload = {"target_phase": target_phase}
    payload.update(overrides)
    return payload


def change_settle_payload(resolution: str = "CONFIRM", **overrides) -> Dict[str, Any]:
    payload = {"resolution": resolution}
    payload.update(overrides)
    return payload


def cancel_payload(cancel_reason: str = "Passenger request", **overrides) -> Dict[str, Any]:
    payload = {"cancel_reason": cancel_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Flights, the demand feed and the seat map
# ---------------------------------------------------------------------------
def flight_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "flight_no": f"AA{unique_suffix(4)}",
        "origin": "JFK",
        "destination": "LAX",
        "scheduled_departure_utc": "2026-09-15T14:00:00Z",
        "cabin_seat_total": 180,
    }
    payload.update(overrides)
    return payload


def demand_snapshot_payload(
    booked_load_factor_pct: int = 75, demand_index_bp: int = 1200, **overrides
) -> Dict[str, Any]:
    payload = {
        "booked_load_factor_pct": booked_load_factor_pct,
        "demand_index_bp": demand_index_bp,
    }
    payload.update(overrides)
    return payload


def seat_segment_payload(
    flight_id: str, ancillary_product_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "flight_id": flight_id,
        "ancillary_product_id": ancillary_product_id,
        "zone": "MID",
        "row_start": 16,
        "row_end": 18,
        "seat_letters": ["A", "B", "C"],
        "base_price_cents": 2000,
    }
    payload.update(overrides)
    return payload


def seat_assignment_payload(
    seat_inventory_segment_id: str, row: int, seat_letter: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "seat_inventory_segment_id": seat_inventory_segment_id,
        "row": row,
        "seat_letter": seat_letter,
    }
    payload.update(overrides)
    return payload


def seat_release_payload(release_reason: str = "PASSENGER_RELEASE", **overrides) -> Dict[str, Any]:
    payload = {"release_reason": release_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------
def distribution_channel_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "channel_code": f"CH_{unique_suffix(6)}",
        "channel_type": "DIRECT",
        "commission_bp": 0,
        "markup_bp": 0,
        "max_ancillary_price_cents": 20000,
        "supported_categories": ["BAGGAGE", "SEAT", "CHANGE", "BOARDING", "ONBOARD"],
        "parity_required": True,
    }
    payload.update(overrides)
    return payload


def direct_web_channel_payload(**overrides) -> Dict[str, Any]:
    """DIRECT_WEB: no commission, no markup, every category supported."""
    return distribution_channel_payload(
        **{
            "channel_code": "DIRECT_WEB",
            "channel_type": "DIRECT",
            "commission_bp": 0,
            "markup_bp": 0,
            "max_ancillary_price_cents": 20000,
            "supported_categories": ["BAGGAGE", "SEAT", "CHANGE", "BOARDING", "ONBOARD"],
            "parity_required": True,
            **overrides,
        }
    )


def channel_publication_payload(
    fare_family_id: str, distribution_channel_id: str, expected_fare_family_version, **overrides
) -> Dict[str, Any]:
    payload = {
        "fare_family_id": fare_family_id,
        "distribution_channel_id": distribution_channel_id,
        "expected_fare_family_version": expected_fare_family_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Bookings and merchandising
# ---------------------------------------------------------------------------
def booking_payload(
    flight_id: str, fare_family_id: str, distribution_channel_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "record_locator": unique_suffix(6),
        "flight_id": flight_id,
        "fare_family_id": fare_family_id,
        "distribution_channel_id": distribution_channel_id,
        "passenger_name": "Test Passenger",
    }
    payload.update(overrides)
    return payload


def offer_session_payload(
    touchpoint: str = "BOOKING", requested_product_ids: Optional[List[str]] = None, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"touchpoint": touchpoint}
    if requested_product_ids is not None:
        payload["requested_product_ids"] = requested_product_ids
    payload.update(overrides)
    return payload


def offer_accept_payload(expected_booking_version, **overrides) -> Dict[str, Any]:
    payload = {"expected_booking_version": expected_booking_version}
    payload.update(overrides)
    return payload


def disclosure_ack_payload(acknowledged_fee_fingerprint: str, **overrides) -> Dict[str, Any]:
    payload = {"acknowledged_fee_fingerprint": acknowledged_fee_fingerprint}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Irregular operations
# ---------------------------------------------------------------------------
def irops_waiver_payload(
    event_type: str = "DELAY",
    delay_minutes: int = 240,
    waiver_scope: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "event_type": event_type,
        "delay_minutes": delay_minutes,
        "waiver_scope": waiver_scope if waiver_scope is not None else ["CHANGE"],
    }
    payload.update(overrides)
    return payload


def waiver_rescind_payload(rescind_reason: str = "Operations recovered", **overrides) -> Dict[str, Any]:
    payload = {"rescind_reason": rescind_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def clock_payload(to_iso8601: str, **overrides) -> Dict[str, Any]:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
