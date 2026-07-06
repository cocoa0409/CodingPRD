"""Payload factories — one per entity, input fields only (PRD-declared inputs)."""


DEFAULTS = {
    "COUPLE_NAMES": "Alex & Blair",
    "EVENT_DATE": "2026-09-15T00:00:00Z",
    "VENUE_NAME": "Grand Hall",
    "TOTAL_BUDGET_CENTS": 10_000_000,
    "GUEST_COUNT_ESTIMATE": 100,
    "VENDOR_NAME": "Test Vendor",
    "CONTACT_EMAIL": "vendor@example.com",
    "POLICY_NUMBER": "POL-1",
    "COVERAGE_AMOUNT_CENTS": 100_000_000,
    "COVERAGE_EXPIRY_DATE": "2027-01-01T00:00:00Z",
    "COI_EXPIRY_DATE": "2027-01-01T00:00:00Z",
    "SERVICE_DESCRIPTION": "Vendor service",
    "ESTIMATED_COST_CENTS": 1_000_000,
    "GUEST_NAME": "Party Guest",
    "PARTY_SIZE": 2,
    "TABLE_LABEL": "T1",
    "CAPACITY": 8,
    "STAFF_NAME": "Sam Staff",
    "HOURLY_RATE_CENTS": 5_000,
    "TIMELINE_LABEL": "Run-of-show block",
}


def create_event_payload(**overrides) -> dict:
    """PRD §3.1: couple_names, event_date, venue_name, package_type,
    total_budget_cents, guest_count_estimate."""
    payload = {
        "couple_names": DEFAULTS["COUPLE_NAMES"],
        "event_date": DEFAULTS["EVENT_DATE"],
        "venue_name": DEFAULTS["VENUE_NAME"],
        "package_type": "FULL",
        "total_budget_cents": DEFAULTS["TOTAL_BUDGET_CENTS"],
        "guest_count_estimate": DEFAULTS["GUEST_COUNT_ESTIMATE"],
    }
    payload.update(overrides)
    return payload


def create_contract_payload(event_id, expected_event_version, **overrides) -> dict:
    """PRD §2.8 / §3.1: event_id + expected_event_version (OCC token)."""
    payload = {"event_id": event_id, "expected_event_version": expected_event_version}
    payload.update(overrides)
    return payload


def create_vendor_payload(**overrides) -> dict:
    """PRD §3.2: name, category, contact_email."""
    payload = {
        "name": DEFAULTS["VENDOR_NAME"],
        "category": "FLORAL",
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_coi_payload(vendor_id, **overrides) -> dict:
    """PRD §3.2: vendor_id, policy_number, coverage_amount_cents,
    coverage_expiry_date."""
    payload = {
        "vendor_id": vendor_id,
        "policy_number": DEFAULTS["POLICY_NUMBER"],
        "coverage_amount_cents": DEFAULTS["COVERAGE_AMOUNT_CENTS"],
        "coverage_expiry_date": DEFAULTS["COVERAGE_EXPIRY_DATE"],
    }
    payload.update(overrides)
    return payload


def create_vendor_booking_payload(event_id, vendor_id, **overrides) -> dict:
    """PRD §3.3: event_id, vendor_id, service_description, estimated_cost_cents."""
    payload = {
        "event_id": event_id,
        "vendor_id": vendor_id,
        "service_description": DEFAULTS["SERVICE_DESCRIPTION"],
        "estimated_cost_cents": DEFAULTS["ESTIMATED_COST_CENTS"],
    }
    payload.update(overrides)
    return payload


def book_vendor_booking_payload(contracted_cost_cents, **overrides) -> dict:
    """PRD §3.3: contracted_cost_cents supplied on book."""
    payload = {"contracted_cost_cents": contracted_cost_cents}
    payload.update(overrides)
    return payload


def create_guest_payload(event_id, **overrides) -> dict:
    """PRD §3.4: event_id, guest_name, party_size, optional meal_choice."""
    payload = {
        "event_id": event_id,
        "guest_name": DEFAULTS["GUEST_NAME"],
        "party_size": DEFAULTS["PARTY_SIZE"],
    }
    payload.update(overrides)
    return payload


def create_table_payload(event_id, **overrides) -> dict:
    """PRD §3.5: event_id, table_label, capacity."""
    payload = {
        "event_id": event_id,
        "table_label": DEFAULTS["TABLE_LABEL"],
        "capacity": DEFAULTS["CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_seat_assignment_payload(event_id, guest_id, table_id, **overrides) -> dict:
    """PRD §3.5: event_id, guest_id, table_id."""
    payload = {"event_id": event_id, "guest_id": guest_id, "table_id": table_id}
    payload.update(overrides)
    return payload


def create_staff_member_payload(event_id, **overrides) -> dict:
    """PRD §3.7: event_id, staff_name, role_title, hourly_rate_cents."""
    payload = {
        "event_id": event_id,
        "staff_name": DEFAULTS["STAFF_NAME"],
        "role_title": "SERVER",
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_staff_assignment_payload(event_id, staff_member_id, start, end, **overrides) -> dict:
    """PRD §3.7: event_id, staff_member_id, shift_start_offset_min,
    shift_end_offset_min."""
    payload = {
        "event_id": event_id,
        "staff_member_id": staff_member_id,
        "shift_start_offset_min": start,
        "shift_end_offset_min": end,
    }
    payload.update(overrides)
    return payload


def create_timeline_block_payload(event_id, start, end, **overrides) -> dict:
    """PRD §3.6: event_id, label, zone, block_type, start_offset_min,
    end_offset_min."""
    payload = {
        "event_id": event_id,
        "label": DEFAULTS["TIMELINE_LABEL"],
        "zone": "RECEPTION_HALL",
        "block_type": "RECEPTION",
        "start_offset_min": start,
        "end_offset_min": end,
    }
    payload.update(overrides)
    return payload
