"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


def create_park_payload(**overrides) -> dict:
    """POST /park. Only `name` is required; tunable knobs are optional with defaults."""
    defaults = {"name": "Sky Park"}
    defaults.update(overrides)
    return defaults


def create_slot_payload(park_id: str, **overrides) -> dict:
    """POST /park/slots. starts_at/ends_at/jump_capacity/base_price_cents required."""
    defaults = {
        "park_id": park_id,
        "starts_at": "2026-06-20T10:00:00Z",
        "ends_at": "2026-06-20T12:00:00Z",
        "jump_capacity": 10,
        "base_price_cents": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(park_id: str, **overrides) -> dict:
    """POST /park/participants. full_name/birthdate required; guardian/member optional."""
    defaults = {
        "park_id": park_id,
        "full_name": "Adult Jumper",
        "birthdate": "1990-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(participant_id: str, signed_by_participant_id: str,
                          **overrides) -> dict:
    """POST /park/waivers."""
    defaults = {
        "participant_id": participant_id,
        "signed_by_participant_id": signed_by_participant_id,
        "signature_text": "Adult Jumper",
    }
    defaults.update(overrides)
    return defaults


def create_jump_pass_payload(slot_id: str, participant_id: str, expected_slot_version: int,
                             **overrides) -> dict:
    """POST /park/jump-passes. channel required; sock_count defaults to 1; member_id optional."""
    defaults = {
        "slot_id": slot_id,
        "participant_id": participant_id,
        "channel": "RESERVATION",
        "sock_count": 1,
        "expected_slot_version": expected_slot_version,
    }
    defaults.update(overrides)
    return defaults


def create_add_on_payload(sku: str, quantity: int = 1, **overrides) -> dict:
    """POST /park/jump-passes/{id}/add-ons."""
    defaults = {"sku": sku, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_member_payload(park_id: str, **overrides) -> dict:
    """POST /park/members. email must be unique per park."""
    defaults = {
        "park_id": park_id,
        "email": "m1@x.com",
        "full_name": "Member One",
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(member_id: str, tier: str = "GOLD",
                              cycle_anchor_at: str = "2026-06-01T00:00:00Z",
                              **overrides) -> dict:
    """POST /park/memberships."""
    defaults = {
        "member_id": member_id,
        "tier": tier,
        "cycle_anchor_at": cycle_anchor_at,
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(park_id: str, **overrides) -> dict:
    """POST /park/rooms. turnover_buffer_minutes optional (default 30)."""
    defaults = {
        "park_id": park_id,
        "name": "Room A",
        "room_capacity": 30,
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(park_id: str, **overrides) -> dict:
    """POST /park/packages."""
    defaults = {
        "park_id": park_id,
        "name": "Basic",
        "per_guest_cents": 1500,
        "base_room_fee_cents": 10000,
        "min_guests": 4,
    }
    defaults.update(overrides)
    return defaults


def create_party_booking_payload(package_id: str, room_id: str, slot_id: str,
                                 guest_count: int = 6, **overrides) -> dict:
    """POST /park/party-bookings. host_member_id optional."""
    defaults = {
        "package_id": package_id,
        "room_id": room_id,
        "slot_id": slot_id,
        "guest_count": guest_count,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(park_id: str, jump_pass_id: str, severity: str = "MINOR",
                            **overrides) -> dict:
    """POST /park/incidents."""
    defaults = {
        "park_id": park_id,
        "jump_pass_id": jump_pass_id,
        "severity": severity,
        "narrative": "Incident narrative.",
    }
    defaults.update(overrides)
    return defaults
