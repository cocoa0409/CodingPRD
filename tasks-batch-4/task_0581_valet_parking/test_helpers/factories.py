"""Payload factories — one per create endpoint, input fields only (PRD §3, §4)."""

# Default operating window for events (ISO 8601 UTC).
DEFAULT_WINDOW_START = "2026-06-01T08:00:00Z"
DEFAULT_WINDOW_END = "2026-06-01T23:00:00Z"


def create_venue_payload(**overrides) -> dict:
    """Venue inputs: name, address, currency? (defaults USD server-side)."""
    payload = {"name": "Grand Hall", "address": "1 Main St"}
    payload.update(overrides)
    return payload


def create_event_payload(venue_id: str, **overrides) -> dict:
    """Event inputs: venue_id, name, window_start, window_end, and optional rate-card
    fields (free_grace_minutes, hourly_rate_cents, daily_max_cents, event_surcharge_cents,
    overflow_surcharge_cents, tip_split_mode)."""
    payload = {
        "venue_id": venue_id,
        "name": "Gala Night",
        "window_start": DEFAULT_WINDOW_START,
        "window_end": DEFAULT_WINDOW_END,
    }
    payload.update(overrides)
    return payload


def create_lot_payload(venue_id: str, capacity: int = 5, **overrides) -> dict:
    """Lot inputs: venue_id, name, capacity, overflow_lot_id?, is_overflow?."""
    payload = {"venue_id": venue_id, "name": "L1", "capacity": capacity}
    payload.update(overrides)
    return payload


def create_lane_assignment_payload(venue_id: str, event_id: str, lane_code: str = "A1",
                                   window_start: str = "2026-06-01T10:00:00Z",
                                   window_end: str = "2026-06-01T12:00:00Z",
                                   **overrides) -> dict:
    """LaneAssignment inputs: venue_id, event_id, lane_code, window_start, window_end."""
    payload = {
        "venue_id": venue_id,
        "event_id": event_id,
        "lane_code": lane_code,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_attendant_payload(venue_id: str, name: str = "Ana", **overrides) -> dict:
    """Attendant inputs: venue_id, name."""
    payload = {"venue_id": venue_id, "name": name}
    payload.update(overrides)
    return payload


def create_shift_payload(attendant_id: str, start_at: str, end_at: str, **overrides) -> dict:
    """Shift inputs: attendant_id, event_id? (null for non-event shift), start_at, end_at."""
    payload = {"attendant_id": attendant_id, "start_at": start_at, "end_at": end_at}
    payload.update(overrides)
    return payload


def create_ticket_payload(event_id: str, lot_id: str, attendant_id: str,
                          expected_lot_version: int,
                          checkin_at: str = "2026-06-01T10:00:00Z",
                          estimated_departure_at: str = "2026-06-01T12:00:00Z",
                          license_plate: str = "ABC1", key_tag: str = "K1",
                          **overrides) -> dict:
    """Ticket (check-in) inputs: event_id, lot_id, attendant_id, license_plate, key_tag,
    checkin_at, estimated_departure_at, expected_lot_version (OCC guard, §2.6)."""
    payload = {
        "event_id": event_id,
        "lot_id": lot_id,
        "attendant_id": attendant_id,
        "license_plate": license_plate,
        "key_tag": key_tag,
        "checkin_at": checkin_at,
        "estimated_departure_at": estimated_departure_at,
        "expected_lot_version": expected_lot_version,
    }
    payload.update(overrides)
    return payload


def create_damage_claim_payload(ticket_id: str, description: str = "scratch",
                                claimed_amount_cents: int = 500, **overrides) -> dict:
    """DamageClaim inputs: ticket_id, attendant_id? (defaults to ticket.attendant_id),
    description, claimed_amount_cents."""
    payload = {
        "ticket_id": ticket_id,
        "description": description,
        "claimed_amount_cents": claimed_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_retrieval_request_payload(ticket_id: str,
                                     requested_at: str = "2026-06-01T11:30:00Z",
                                     **overrides) -> dict:
    """RetrievalRequest inputs: ticket_id, requested_at."""
    payload = {"ticket_id": ticket_id, "requested_at": requested_at}
    payload.update(overrides)
    return payload


def create_validation_payload(grant_type: str, **overrides) -> dict:
    """ValidationGrant inputs: grant_type (PERCENT|FLAT|FULL_COMP), value? (default 0)."""
    payload = {"grant_type": grant_type}
    payload.update(overrides)
    return payload
