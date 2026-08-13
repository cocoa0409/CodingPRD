"""Entity assertions and domain invariant checkers.

Each assert_* function validates the shape of one resource record returned
by the API: identifier and timestamp formats plus the PRD-declared field set
and enum membership.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_community(data: dict):
    _assert_common(data)
    assert isinstance(data.get("name"), str) and data["name"]
    for f in ("holdback_min_cents", "holdback_max_cents",
              "orientation_min_days_before_closing",
              "orientation_max_days_before_closing",
              "appointment_duration_minutes", "appointment_buffer_minutes",
              "survey_window_days"):
        assert isinstance(data.get(f), int), f"{f} must be an integer"
    assert isinstance(data.get("holdback_cost_multiplier"), (int, float))
    assert isinstance(data.get("cosmetic_photo_required"), bool)


def assert_homebuyer(data: dict):
    _assert_common(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and "@" in data["email"]


def assert_rep(data: dict):
    _assert_common(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("active"), bool)
    assert isinstance(data.get("daily_visit_capacity_minutes"), int)


def assert_home(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("community_id", ""))
    assert is_valid_uuid(data.get("primary_buyer_id", ""))
    assert data.get("status") in [
        "UNDER_CONSTRUCTION", "PRE_CLOSE_READY", "ORIENTATION_SCHEDULED",
        "ORIENTED", "ACKNOWLEDGED", "READY_TO_CLOSE", "CLOSED",
    ]
    assert isinstance(data.get("sales_price_cents"), int)
    assert isinstance(data.get("open_before_closing_count"), int)
    assert isinstance(data.get("open_after_closing_count"), int)


def assert_appointment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("home_id", ""))
    assert is_valid_uuid(data.get("rep_id", ""))
    assert data.get("status") in [
        "REQUESTED", "CONFIRMED", "IN_PROGRESS", "COMPLETED",
        "CANCELLED", "NO_SHOW",
    ]
    assert isinstance(data.get("duration_minutes"), int)
    assert isinstance(data.get("reschedule_count"), int)
    for f in ("checklist_total_count", "checklist_demonstrated_count",
              "checklist_pending_count", "checklist_skipped_count"):
        assert isinstance(data.get(f), int), f"{f} must be an integer"


def assert_attendee(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("appointment_id", ""))
    assert data.get("attendee_type") in ["BUYER", "CO_BUYER", "POA_PROXY"]
    assert data.get("verification_status") in ["PENDING", "VERIFIED", "REJECTED"]


def assert_deficiency_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("home_id", ""))
    assert is_valid_uuid(data.get("appointment_id", ""))
    assert data.get("status") in [
        "IDENTIFIED", "CLASSIFIED", "DECIDED", "IN_REPAIR",
        "READY_FOR_REINSPECTION", "VERIFIED", "SIGNED_OFF", "WITHDRAWN",
    ]
    assert isinstance(data.get("title"), str) and data["title"]
    assert isinstance(data.get("holdback_released"), bool)


def assert_reinspection_visit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("home_id", ""))
    assert is_valid_uuid(data.get("rep_id", ""))
    assert data.get("status") in ["SCHEDULED", "COMPLETED"]
    assert isinstance(data.get("duration_minutes"), int)


def assert_escrow_holdback(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("home_id", ""))
    assert data.get("status") in [
        "DRAFT", "ACTIVE", "PARTIALLY_RELEASED", "FULLY_RELEASED", "VOIDED",
    ]
    assert isinstance(data.get("holdback_amount_cents"), int)
    assert isinstance(data.get("funded_amount_cents"), int)
    assert isinstance(data.get("released_amount_cents"), int)
    assert isinstance(data.get("remaining_amount_cents"), int)


def assert_acknowledgment_signature(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("home_id", ""))
    assert is_valid_uuid(data.get("appointment_id", ""))
    assert data.get("status") in ["PENDING", "SIGNED", "DECLINED", "STALE"]


def assert_feedback_survey(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("home_id", ""))
    assert is_valid_uuid(data.get("appointment_id", ""))
    assert data.get("status") in ["ISSUED", "SUBMITTED", "EXPIRED"]


def assert_quality_trend(data: dict):
    assert isinstance(data.get("period_month"), str)
    assert isinstance(data.get("submitted_survey_count"), int)
    assert isinstance(data.get("homes_surveyed_count"), int)
    for f in ("response_weighted_avg_score", "home_weighted_avg_score",
              "avg_warrantable_items_per_home"):
        v = data.get(f)
        assert v is None or isinstance(v, (int, float)), (
            f"{f} must be a number or null, got {v!r}"
        )
