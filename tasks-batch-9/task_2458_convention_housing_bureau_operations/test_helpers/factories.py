"""Payload factories — one per write operation, input fields only."""

from .constants import TEST_DEFAULTS


def create_event_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["EVENT_NAME"],
        "code": TEST_DEFAULTS["EVENT_CODE"],
        "event_start_date": TEST_DEFAULTS["EVENT_START_DATE"],
        "event_end_date": TEST_DEFAULTS["EVENT_END_DATE"],
        "cutoff_date": TEST_DEFAULTS["CUTOFF_DATE"],
        "attrition_deadline_date": TEST_DEFAULTS["ATTRITION_DEADLINE_DATE"],
        "standard_commission_pct": TEST_DEFAULTS["STANDARD_COMMISSION_PCT"],
        "standard_rebate_per_room_night_cents": TEST_DEFAULTS[
            "STANDARD_REBATE_PER_ROOM_NIGHT_CENTS"
        ],
    }
    payload.update(overrides)
    return payload


def create_hotel_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["HOTEL_NAME"],
        "distance_to_venue_miles": TEST_DEFAULTS["DISTANCE_TO_VENUE_MILES"],
        "room_tax_pct": TEST_DEFAULTS["ROOM_TAX_PCT"],
        "total_rooms": TEST_DEFAULTS["TOTAL_ROOMS"],
    }
    payload.update(overrides)
    return payload


def create_hotel_block_payload(event_id: str, hotel_id: str, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "hotel_id": hotel_id,
        "contracted_rooms_per_night": TEST_DEFAULTS["CONTRACTED_ROOMS_PER_NIGHT"],
        "negotiated_nightly_rate_cents": TEST_DEFAULTS["NEGOTIATED_NIGHTLY_RATE_CENTS"],
        "commission_pct": TEST_DEFAULTS["COMMISSION_PCT"],
        "rebate_per_room_night_cents": TEST_DEFAULTS["REBATE_PER_ROOM_NIGHT_CENTS"],
        "cutoff_date": TEST_DEFAULTS["CUTOFF_DATE"],
        "reduction_rights_pct": TEST_DEFAULTS["REDUCTION_RIGHTS_PCT"],
    }
    payload.update(overrides)
    return payload


def block_terms_payload(expected_hotel_block_version: int, **overrides) -> dict:
    payload = {
        "negotiated_nightly_rate_cents": TEST_DEFAULTS["NEGOTIATED_NIGHTLY_RATE_CENTS"],
        "commission_pct": TEST_DEFAULTS["COMMISSION_PCT"],
        "rebate_per_room_night_cents": TEST_DEFAULTS["REBATE_PER_ROOM_NIGHT_CENTS"],
        "cutoff_date": TEST_DEFAULTS["CUTOFF_DATE"],
        "reduction_rights_pct": TEST_DEFAULTS["REDUCTION_RIGHTS_PCT"],
        "expected_hotel_block_version": expected_hotel_block_version,
    }
    payload.update(overrides)
    return payload


def contract_block_payload(**overrides) -> dict:
    payload = {"confirmation_number": TEST_DEFAULTS["CONFIRMATION_NUMBER"]}
    payload.update(overrides)
    return payload


def carve_sub_block_payload(
    segment: str,
    allotted_rooms: int,
    expected_hotel_block_version: int,
    **overrides,
) -> dict:
    payload = {
        "segment": segment,
        "allotted_rooms": allotted_rooms,
        "expected_hotel_block_version": expected_hotel_block_version,
    }
    # PRD §3.3: eligibility_code is required for every segment other than
    # GENERAL and must be absent or null for GENERAL.
    if segment != "GENERAL" and "eligibility_code" not in overrides:
        payload["eligibility_code"] = f"{segment}-GOLD"
    payload.update(overrides)
    return payload


def release_sub_block_payload(rooms: int, **overrides) -> dict:
    payload = {"rooms": rooms}
    payload.update(overrides)
    return payload


def create_attendee_payload(event_id: str, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "email": "a1@example.com",
        "full_name": "Attendee One",
        "registration_id": "REG-1",
        "attendee_type": "GENERAL",
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(
    sub_block_id: str, attendee_id: str, **overrides
) -> dict:
    payload = {
        "sub_block_id": sub_block_id,
        "attendee_id": attendee_id,
        "check_in_date": TEST_DEFAULTS["EVENT_START_DATE"],
        "check_out_date": TEST_DEFAULTS["EVENT_END_DATE"],
        "occupants": 1,
    }
    payload.update(overrides)
    return payload


def rooming_list_payload(transmission_type: str = "INITIAL", **overrides) -> dict:
    payload = {"transmission_type": transmission_type}
    payload.update(overrides)
    return payload


def pickup_report_payload(
    as_of_date: str,
    reported_rooms_picked_up: int,
    reported_room_nights: int,
    reported_gross_revenue_cents: int,
    **overrides,
) -> dict:
    payload = {
        "as_of_date": as_of_date,
        "reported_rooms_picked_up": reported_rooms_picked_up,
        "reported_room_nights": reported_room_nights,
        "reported_gross_revenue_cents": reported_gross_revenue_cents,
    }
    payload.update(overrides)
    return payload


def attrition_reduction_payload(
    hotel_block_id: str, requested_reduction_rooms: int, **overrides
) -> dict:
    payload = {
        "hotel_block_id": hotel_block_id,
        "requested_reduction_rooms": requested_reduction_rooms,
        "effective_date": "2026-08-10",
        "justification_code": "PACE_SHORTFALL",
    }
    payload.update(overrides)
    return payload


def create_rogue_vendor_payload(event_id: str, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "name": "Summit Rooms LLC",
        "contact_domain": "summit-rooms.example",
        "detection_source": "ATTENDEE_REPORT",
    }
    payload.update(overrides)
    return payload


def poaching_incident_payload(
    attendee_id: str,
    contact_channel: str = "EMAIL",
    occurred_at: str = "2026-07-20T10:00:00Z",
    verified: bool = True,
    **overrides,
) -> dict:
    payload = {
        "attendee_id": attendee_id,
        "contact_channel": contact_channel,
        "occurred_at": occurred_at,
        "verified": verified,
    }
    payload.update(overrides)
    return payload


def commission_invoice_payload(basis: str = "BUREAU_CONFIRMED", **overrides) -> dict:
    payload = {"basis": basis}
    payload.update(overrides)
    return payload


def payment_payload(amount_cents: int, reference: str = "WIRE-001", **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "reference": reference}
    payload.update(overrides)
    return payload


def payment_reversal_payload(
    amount_cents: int, reference: str = "WIRE-001-REV", **overrides
) -> dict:
    payload = {"amount_cents": amount_cents, "reference": reference}
    payload.update(overrides)
    return payload


def adjust_invoice_payload(write_off_cents: int, **overrides) -> dict:
    payload = {"write_off_cents": write_off_cents}
    payload.update(overrides)
    return payload


def hotel_standing_payload(standing: str, **overrides) -> dict:
    payload = {"standing": standing}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
