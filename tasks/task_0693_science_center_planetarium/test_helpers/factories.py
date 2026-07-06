"""Payload factories — one per entity, input fields only."""


def create_venue_payload(**overrides) -> dict:
    """Input fields for POST /venues. turnover_buffer_minutes and accessible_seats
    are optional (have server-side defaults) so they are omitted by default."""
    defaults = {
        "name": "Test Venue",
        "venue_type": "DOME",
        "seated_capacity": 50,
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(**overrides) -> dict:
    """Input fields for POST /memberships. party_size is optional (default 1)."""
    defaults = {
        "primary_member_name": "Test Member",
        "tier": "FAMILY",
        "home_zip": "90210",
    }
    defaults.update(overrides)
    return defaults


def activate_membership_payload(**overrides) -> dict:
    """Input fields for POST /memberships/{id}/activate."""
    defaults = {
        "dues_cents": 12000,
    }
    defaults.update(overrides)
    return defaults


def create_show_payload(**overrides) -> dict:
    """Input fields for POST /shows. feature_surcharge_cents is optional (default 0)."""
    defaults = {
        "venue_id": None,
        "title": "Test Show",
        "starts_at": "2026-04-01T10:00:00Z",
        "ends_at": "2026-04-01T11:00:00Z",
        "base_price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_show_booking_payload(**overrides) -> dict:
    """Input fields for POST /show-bookings. membership_id and
    accessible_seats_requested are optional."""
    defaults = {
        "show_event_id": None,
        "party_size": 1,
        "expected_show_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_group_booking_payload(**overrides) -> dict:
    """Input fields for POST /group-bookings."""
    defaults = {
        "show_event_id": None,
        "organization_name": "Test School",
        "student_count": 10,
        "chaperone_count": 1,
    }
    defaults.update(overrides)
    return defaults


def confirm_group_booking_payload(**overrides) -> dict:
    """Input fields for POST /group-bookings/{id}/confirm."""
    defaults = {
        "actual_student_count": 10,
        "actual_chaperone_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    """Input fields for POST /programs."""
    defaults = {
        "venue_id": None,
        "title": "Test Program",
        "program_kind": "CAMP",
        "min_age": 5,
        "max_age": 99,
        "starts_at": "2026-07-01T09:00:00Z",
        "capacity": 5,
        "tuition_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(**overrides) -> dict:
    """Input fields for POST /registrations. membership_id is optional."""
    defaults = {
        "program_session_id": None,
        "participant_name": "Test Participant",
        "participant_age": 10,
        "expected_session_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_rental_payload(**overrides) -> dict:
    """Input fields for POST /rentals."""
    defaults = {
        "venue_id": None,
        "host_name": "Test Host",
        "starts_at": "2026-05-02T14:00:00Z",
        "ends_at": "2026-05-02T17:00:00Z",
        "guest_count": 10,
        "base_rental_cents": 30000,
    }
    defaults.update(overrides)
    return defaults


def confirm_rental_payload(**overrides) -> dict:
    """Input fields for POST /rentals/{id}/confirm."""
    defaults = {
        "actual_guest_count": 10,
    }
    defaults.update(overrides)
    return defaults


def create_sponsor_payload(**overrides) -> dict:
    """Input fields for POST /sponsors."""
    defaults = {
        "org_name": "Test Sponsor",
        "sponsor_kind": "SPONSOR",
        "pledged_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_contribution_payload(**overrides) -> dict:
    """Input fields for POST /sponsors/{id}/contributions."""
    defaults = {
        "amount_cents": 1000,
        "expected_sponsor_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_accommodation_payload(**overrides) -> dict:
    """Input fields for POST /accommodations. The three subject FKs are optional;
    exactly one must agree with subject_type."""
    defaults = {
        "subject_type": "SHOW_BOOKING",
        "accommodation_kind": "WHEELCHAIR",
    }
    defaults.update(overrides)
    return defaults
