"""Payload factories — one per entity, input fields only."""

# Default datetime anchors. PRD §3.2 requires ready_by_utc to be strictly after the current
# time and no later than event_date_utc, so the wedding (event_date) sits LATE in the day and
# the ready-by deadline sits earlier (noon), with on-location windows running 08:00–10:00.
DEFAULTS = {
    "EVENT_DATE_UTC": "2026-07-15T20:00:00Z",
    "READY_BY_UTC": "2026-07-15T12:00:00Z",
    "VENUE_DISTANCE_KM": 10,
}


def create_artist_payload(**overrides) -> dict:
    """Input fields for POST /artists. can_assist is optional (defaults false server-side)."""
    defaults = {
        "display_name": "L1",
        "skill_tier": "LEAD",
        "hair_rate_per_face_cents": 20000,
        "makeup_rate_per_face_cents": 25000,
        "travel_rate_per_km_cents": 600,
        "max_faces_per_hour": 2,
    }
    defaults.update(overrides)
    return defaults


def create_portfolio_payload(**overrides) -> dict:
    defaults = {"look_name": "Soft Glam", "category": "MAKEUP"}
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    """Input fields for POST /events. trial_required is optional (defaults true server-side)."""
    defaults = {
        "client_id": "client-1",
        "event_date_utc": DEFAULTS["EVENT_DATE_UTC"],
        "ready_by_utc": DEFAULTS["READY_BY_UTC"],
        "venue_distance_km": DEFAULTS["VENUE_DISTANCE_KM"],
        "trial_required": False,
    }
    defaults.update(overrides)
    return defaults


def create_face_payload(**overrides) -> dict:
    """Input fields for POST /events/{id}/faces. is_bride is optional (defaults false)."""
    defaults = {"person_label": "BRIDE", "service_type": "HAIR"}
    defaults.update(overrides)
    return defaults


def create_trial_payload(**overrides) -> dict:
    defaults = {
        "event_id": None,
        "artist_id": None,
        "start_utc": "2026-06-10T09:00:00Z",
        "end_utc": "2026-06-10T10:00:00Z",
        "trial_fee_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {"event_id": None, "lead_artist_id": None, "expected_event_version": None}
    defaults.update(overrides)
    return defaults


def create_assignment_payload(**overrides) -> dict:
    """assistant_artist_id is optional (null = solo)."""
    defaults = {
        "event_id": None,
        "artist_id": None,
        "window_start_utc": "2026-07-15T08:00:00Z",
        "window_end_utc": "2026-07-15T10:00:00Z",
        "expected_event_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_addon_payload(**overrides) -> dict:
    defaults = {"addon_type": "TOUCH_UP", "quantity": 1}
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {"applies_to": "DEPOSIT", "amount_cents": 0}
    defaults.update(overrides)
    return defaults
