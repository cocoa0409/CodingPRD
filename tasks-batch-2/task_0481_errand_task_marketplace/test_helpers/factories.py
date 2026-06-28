"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "DEFAULT_HOURLY_RATE_CENTS": 4000,
    "TASKER_HOURLY_RATE_CENTS": 5000,
    "FIXED_PRICE_CENTS": 5000,
    "DEFAULT_DURATION_MINUTES": 60,
}


def create_category_payload(**overrides) -> dict:
    """TaskCategory create (HOURLY by default). PRD §3.1."""
    defaults = {
        "name": "Test Category",
        "pricing_model": "HOURLY",
        "default_hourly_rate_cents": DEFAULTS["DEFAULT_HOURLY_RATE_CENTS"],
        "default_duration_minutes": DEFAULTS["DEFAULT_DURATION_MINUTES"],
        "requires_vetting": False,
    }
    defaults.update(overrides)
    return defaults


def create_fixed_category_payload(**overrides) -> dict:
    """TaskCategory create (FIXED pricing). PRD §3.1."""
    defaults = {
        "name": "Fixed Category",
        "pricing_model": "FIXED",
        "fixed_price_cents": DEFAULTS["FIXED_PRICE_CENTS"],
        "default_duration_minutes": 90,
        "requires_vetting": False,
    }
    defaults.update(overrides)
    return defaults


def create_tasker_payload(**overrides) -> dict:
    """Tasker register. PRD §3.1."""
    defaults = {
        "full_name": "Test Tasker",
        "hourly_rate_cents": DEFAULTS["TASKER_HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    """Client register. PRD §3.1."""
    defaults = {"full_name": "Test Client"}
    defaults.update(overrides)
    return defaults


def create_skill_payload(tasker_id: str, category_id: str, **overrides) -> dict:
    """TaskerSkill declare. PRD §3.1."""
    defaults = {"tasker_id": tasker_id, "category_id": category_id}
    defaults.update(overrides)
    return defaults


def create_window_payload(tasker_id: str, window_start: str, window_end: str,
                          **overrides) -> dict:
    """AvailabilityWindow create. PRD §3.1."""
    defaults = {
        "tasker_id": tasker_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(client_id: str, category_id: str, scheduled_start: str,
                           **overrides) -> dict:
    """Booking create (one-off, DRAFT). PRD §3.2."""
    defaults = {
        "client_id": client_id,
        "category_id": category_id,
        "dispatch_mode": "SCHEDULED",
        "scheduled_start": scheduled_start,
        "estimated_hours": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(tasker_id: str, expected_tasker_version, **overrides) -> dict:
    """Booking claim. PRD §3.3, §2.6."""
    defaults = {
        "tasker_id": tasker_id,
        "expected_tasker_version": expected_tasker_version,
    }
    defaults.update(overrides)
    return defaults


def create_complete_payload(**overrides) -> dict:
    """Booking complete. PRD §3.3."""
    defaults = {"actual_hours": 1.0}
    defaults.update(overrides)
    return defaults


def create_cancel_payload(cancelled_by: str = "CLIENT", **overrides) -> dict:
    """Booking cancel. PRD §3.6."""
    defaults = {"cancelled_by": cancelled_by}
    defaults.update(overrides)
    return defaults


def create_propose_payload(proposed_start: str, **overrides) -> dict:
    """Reschedule propose. PRD §3.6."""
    defaults = {"proposed_start": proposed_start}
    defaults.update(overrides)
    return defaults


def create_accept_payload(expected_tasker_version, **overrides) -> dict:
    """Reschedule accept. PRD §3.6, §2.6."""
    defaults = {"expected_tasker_version": expected_tasker_version}
    defaults.update(overrides)
    return defaults


def create_rebook_payload(scheduled_start: str, **overrides) -> dict:
    """Rebook a completed booking. PRD §3.7."""
    defaults = {
        "scheduled_start": scheduled_start,
        "dispatch_mode": "SCHEDULED",
        "estimated_hours": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_series_payload(client_id: str, category_id: str, tasker_id: str,
                          first_start: str, **overrides) -> dict:
    """RecurringSeries create. PRD §3.6."""
    defaults = {
        "client_id": client_id,
        "category_id": category_id,
        "tasker_id": tasker_id,
        "frequency": "WEEKLY",
        "first_start": first_start,
        "occurrence_count": 3,
        "estimated_hours": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(booking_id: str, rating_value: int = 5, **overrides) -> dict:
    """Review create. PRD §3.7."""
    defaults = {"booking_id": booking_id, "rating_value": rating_value}
    defaults.update(overrides)
    return defaults


def create_incident_payload(tasker_id: str, severity: str = "HIGH", **overrides) -> dict:
    """TrustIncident file. PRD §3.7."""
    defaults = {"tasker_id": tasker_id, "severity": severity}
    defaults.update(overrides)
    return defaults


def create_message_payload(body: str = "Hello", **overrides) -> dict:
    """ChatMessage post. PRD §3.8."""
    defaults = {"body": body}
    defaults.update(overrides)
    return defaults
