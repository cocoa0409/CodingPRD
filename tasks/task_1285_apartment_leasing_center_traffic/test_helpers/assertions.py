"""Entity assertions and domain invariant checkers."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_same_instant(actual: str, expected_iso: str, label: str = "timestamp") -> None:
    """Compare two ISO 8601 UTC instants, tolerant of fractional-second formatting
    (the PRD pins the instant, not the number of trailing fractional digits)."""
    assert is_iso8601_timestamp(actual), f"{label} must be ISO 8601 UTC, got {actual!r}"
    a = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    e = datetime.fromisoformat(expected_iso.replace("Z", "+00:00"))
    assert a == e, f"{label}: expected instant {expected_iso}, got {actual}"


def _assert_common(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_property(data: dict) -> None:
    _assert_common(data, "Property")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["response_time_target_minutes"], int)
    assert isinstance(data["tour_buffer_minutes"], int)
    assert isinstance(data["self_guided_window_minutes"], int)
    assert isinstance(data["max_moveins_per_day"], int)
    assert isinstance(data["utility_transfer_required"], bool)
    assert data["prorate_method"] in ("CALENDAR", "FIXED_30")
    assert isinstance(data["required_addenda"], list)


def assert_agent(data: dict) -> None:
    _assert_common(data, "Agent")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["max_concurrent_tours"], int)
    assert isinstance(data["active"], bool)


def assert_floorplan(data: dict) -> None:
    _assert_common(data, "Floorplan")
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["bedrooms"], int)
    assert isinstance(data["base_rent_cents"], int)
    assert isinstance(data["total_units"], int)
    assert isinstance(data["committed_units"], int)
    assert isinstance(data["available_units"], int)
    assert_floorplan_availability_invariants(data)


def assert_floorplan_availability_invariants(data: dict) -> None:
    """Availability ledger invariant: available == total - committed, never negative."""
    assert data["available_units"] == data["total_units"] - data["committed_units"], (
        f"available_units {data['available_units']} != total_units {data['total_units']} "
        f"- committed_units {data['committed_units']}"
    )
    assert data["committed_units"] >= 0
    assert data["available_units"] >= 0


def assert_pricing_offer(data: dict) -> None:
    _assert_common(data, "PricingOffer")
    assert is_valid_uuid(data["property_id"])
    assert is_valid_uuid(data["floorplan_id"])
    assert isinstance(data["base_rent_cents"], int)
    assert data["concession_type"] in ("NONE", "FLAT_AMOUNT", "PERCENT_OFF", "FREE_MONTHS")
    assert isinstance(data["effective_monthly_rent_cents"], int)
    assert data["effective_monthly_rent_cents"] >= 0
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED", "EXPIRED")
    assert is_iso8601_timestamp(data["effective_start"])
    assert is_iso8601_timestamp(data["expires_at"])


def assert_inquiry(data: dict) -> None:
    _assert_common(data, "Inquiry")
    assert is_valid_uuid(data["property_id"])
    assert data["source"] in ("WALK_IN", "PHONE", "WEB_FORM", "ILS_LISTING", "REFERRAL")
    assert data["status"] in ("NEW", "CONTACTED", "TOUR_SCHEDULED", "CONVERTED", "LOST")
    assert data.get("assigned_agent_id") is None or is_valid_uuid(data["assigned_agent_id"])
    assert data.get("first_responded_at") is None \
        or is_iso8601_timestamp(data["first_responded_at"])
    assert data.get("response_met_target") is None \
        or isinstance(data["response_met_target"], bool)


def assert_tour(data: dict) -> None:
    _assert_common(data, "Tour")
    assert is_valid_uuid(data["inquiry_id"])
    assert data["tour_type"] in ("GUIDED", "SELF_GUIDED")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data.get("agent_id") is None or is_valid_uuid(data["agent_id"])


def assert_waitlist_entry(data: dict) -> None:
    _assert_common(data, "WaitlistEntry")
    assert is_valid_uuid(data["floorplan_id"])
    assert isinstance(data["position"], int) and data["position"] >= 1
    assert data["status"] in ("WAITING", "OFFERED", "CONVERTED", "CANCELLED")
    assert data.get("offer_expires_at") is None \
        or is_iso8601_timestamp(data["offer_expires_at"])
    assert data.get("linked_application_id") is None \
        or is_valid_uuid(data["linked_application_id"])


def assert_application(data: dict) -> None:
    _assert_common(data, "Application")
    assert is_valid_uuid(data["floorplan_id"])
    assert isinstance(data["annual_income_cents"], int)
    assert isinstance(data["credit_score"], int)
    assert isinstance(data["monthly_rent_snapshot_cents"], int)
    assert data["recommendation"] in ("APPROVE", "CONDITION", "DENY")
    assert data.get("required_deposit_cents") is None \
        or isinstance(data["required_deposit_cents"], int)
    assert isinstance(data["deposit_paid_cents"], int)
    assert data["status"] in ("SCREENING", "APPROVED", "APPROVED_WITH_CONDITIONS",
                              "CONDITIONS_CLEARED", "DENIED", "WITHDRAWN", "LEASED")


def assert_lease(data: dict) -> None:
    _assert_common(data, "Lease")
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["floorplan_id"])
    assert isinstance(data["monthly_rent_cents"], int)
    assert isinstance(data["deposit_cents"], int)
    assert isinstance(data["addenda_codes"], list)
    assert is_iso8601_timestamp(data["signing_deadline"])
    assert data.get("signed_at") is None or is_iso8601_timestamp(data["signed_at"])
    assert data.get("executed_at") is None or is_iso8601_timestamp(data["executed_at"])
    assert data.get("superseded_by_id") is None or is_valid_uuid(data["superseded_by_id"])
    assert data["status"] in ("ISSUED", "SIGNED_BY_APPLICANT", "EXECUTED",
                              "SUPERSEDED", "EXPIRED", "CANCELLED")


def assert_move_in(data: dict) -> None:
    _assert_common(data, "MoveIn")
    assert is_valid_uuid(data["lease_id"])
    assert is_iso8601_timestamp(data["scheduled_date"])
    assert isinstance(data["utility_confirmed"], bool)
    assert isinstance(data["prorated_rent_cents"], int)
    assert data["status"] in ("SCHEDULED", "READY", "COMPLETED", "CANCELLED")
