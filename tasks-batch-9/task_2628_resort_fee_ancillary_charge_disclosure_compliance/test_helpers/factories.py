"""Payload factories — one per creatable resource, input fields only."""
from .constants import (
    ARRIVAL_DATE,
    BASE_ROOM_RATE_CENTS,
    DESTINATION_AMOUNT_CENTS,
    DESTINATION_OPT_OUT_WINDOW_HOURS,
    FEE_PROGRAM_EFFECTIVE_FROM,
    FEE_PROGRAM_EFFECTIVE_TO,
    OCCUPANCY_TAX_RATE_BPS,
    PROFILE_DEPLOYED_FROM,
    PROFILE_DEPLOYED_TO,
    RESORT_PERCENT_BPS,
    STAY_GUESTS,
    STAY_NIGHTS,
    WIFI_PREMIUM_AMOUNT_CENTS,
)


def create_jurisdiction_payload(**overrides) -> dict:
    payload = {
        "code": "US-NV-CLARK",
        "name": "Clark County, Nevada",
        "occupancy_tax_rate_bps": OCCUPANCY_TAX_RATE_BPS,
        "first_quote_total_required": True,
        "itemization_required_on_folio": True,
        "mandatory_fee_ban": False,
        "opt_out_mandate": True,
    }
    payload.update(overrides)
    return payload


def create_taxability_rule_payload(jurisdiction_id, fee_code, **overrides) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "fee_code": fee_code,
        "taxability": "TAXABLE",
        "tax_rate_bps": OCCUPANCY_TAX_RATE_BPS,
    }
    payload.update(overrides)
    return payload


def create_property_payload(jurisdiction_id, **overrides) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "name": "Mirage Sands Resort",
        "brand_code": "MSR",
        "base_room_rate_cents": BASE_ROOM_RATE_CENTS,
    }
    payload.update(overrides)
    return payload


def create_channel_payload(**overrides) -> dict:
    payload = {
        "name": "Sandcastle OTA",
        "channel_type": "OTA",
        "supports_total_price_display": True,
        "supports_itemization": True,
    }
    payload.update(overrides)
    return payload


def create_fee_program_payload(property_id, expected_property_version, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "version_label": "FY26-Q4",
        "effective_from": FEE_PROGRAM_EFFECTIVE_FROM,
        "effective_to": FEE_PROGRAM_EFFECTIVE_TO,
        "expected_property_version": expected_property_version,
    }
    payload.update(overrides)
    return payload


def create_resort_fee_payload(**overrides) -> dict:
    """A mandatory percent-of-room resort fee."""
    payload = {
        "code": "RESORT",
        "label": "Resort Fee",
        "classification": "MANDATORY",
        "basis": "PERCENT_OF_ROOM",
        "percent_bps": RESORT_PERCENT_BPS,
        "disclosure_text": "A mandatory nightly resort fee applies to this rate.",
    }
    payload.update(overrides)
    return payload


def create_destination_fee_payload(**overrides) -> dict:
    """A mandatory per-night destination fee that the guest may opt out of."""
    payload = {
        "code": "DESTINATION",
        "label": "Destination Amenity Fee",
        "classification": "MANDATORY",
        "basis": "PER_NIGHT",
        "amount_cents": DESTINATION_AMOUNT_CENTS,
        "avoidable": True,
        "opt_out_window_hours": DESTINATION_OPT_OUT_WINDOW_HOURS,
        "disclosure_text": "A nightly destination amenity fee applies and may be waived.",
    }
    payload.update(overrides)
    return payload


def create_wifi_fee_payload(**overrides) -> dict:
    """A mandatory per-person-per-night premium wifi fee."""
    payload = {
        "code": "WIFI_PREMIUM",
        "label": "Premium Wi-Fi",
        "classification": "MANDATORY",
        "basis": "PER_PERSON_PER_NIGHT",
        "amount_cents": WIFI_PREMIUM_AMOUNT_CENTS,
        "disclosure_text": "Premium in-room Wi-Fi is charged per guest per night.",
    }
    payload.update(overrides)
    return payload


def create_fee_inclusion_payload(**overrides) -> dict:
    payload = {
        "service_code": "POOL_ACCESS",
        "service_label": "Pool and cabana access",
        "retail_value_cents": 1500,
        "units": 1,
    }
    payload.update(overrides)
    return payload


def create_profile_payload(
    property_id, channel_id, fee_program_id, expected_fee_program_version, **overrides
) -> dict:
    payload = {
        "property_id": property_id,
        "channel_id": channel_id,
        "fee_program_id": fee_program_id,
        "first_quote_shows_total": True,
        "itemized_at_first_quote": True,
        "disclosure_placement": "FIRST_QUOTE",
        "deployed_from": PROFILE_DEPLOYED_FROM,
        "deployed_to": PROFILE_DEPLOYED_TO,
        "expected_fee_program_version": expected_fee_program_version,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(
    property_id, channel_id, channel_disclosure_profile_id, **overrides
) -> dict:
    payload = {
        "property_id": property_id,
        "channel_id": channel_id,
        "channel_disclosure_profile_id": channel_disclosure_profile_id,
        "arrival_date": ARRIVAL_DATE,
        "nights": STAY_NIGHTS,
        "guests": STAY_GUESTS,
        "room_rate_cents": BASE_ROOM_RATE_CENTS,
    }
    payload.update(overrides)
    return payload


def create_guest_complaint_payload(folio_line_id, **overrides) -> dict:
    payload = {
        "folio_line_id": folio_line_id,
        "complaint_reason": "NOT_DISCLOSED",
        "narrative": "The resort fee was never shown to me before I paid for the stay.",
    }
    payload.update(overrides)
    return payload


def create_regulator_inquiry_payload(jurisdiction_id, property_id, **overrides) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "property_id": property_id,
        "docket_number": "NV-2026-0091",
        "channel_scope": ["OTA"],
        "response_due_at": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_revenue_impact_model_payload(property_id, fee_program_id, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "fee_program_id": fee_program_id,
        "scenario": "PARTIAL_ROLL_IN",
        "variant": "RATE_PARITY",
        "roll_in_fee_codes": ["DESTINATION", "WIFI_PREMIUM"],
    }
    payload.update(overrides)
    return payload


def create_remediation_payload(**overrides) -> dict:
    payload = {
        "first_quote_shows_total": True,
        "itemized_at_first_quote": True,
        "disclosure_placement": "FIRST_QUOTE",
    }
    payload.update(overrides)
    return payload
