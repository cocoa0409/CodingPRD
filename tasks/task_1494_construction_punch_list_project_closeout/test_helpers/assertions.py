"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

PROJECT_STATUSES = [
    "MOBILIZED", "PUNCH_ACTIVE", "SC_REVIEW", "SUBSTANTIALLY_COMPLETE",
    "CLOSEOUT_IN_PROGRESS", "FINAL_RELEASE_PENDING", "CLOSED",
]
TRADE_NAMES = [
    "ELECTRICAL", "PLUMBING", "HVAC", "DRYWALL", "FLOORING", "ROOFING", "PAINTING", "CONCRETE",
]


def _assert_common_fields(data: dict):
    """PRD §2.5: all eight resources share id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_nullable_ts(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{field} must be null or ISO 8601 UTC, got {value!r}"
    )


def assert_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contract_value_cents"], int) and data["contract_value_cents"] >= 1000
    assert 0 < data["retainage_pct"] <= 0.25
    assert data["reduction_policy"] in ("STANDARD", "ADJUSTED")
    assert data["warranty_sla_mode"] in ("CALENDAR", "BUSINESS")
    assert data["status"] in PROJECT_STATUSES
    for field in ("open_life_safety_count", "open_major_count", "open_minor_count"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["sc_eligible"], bool)
    assert isinstance(data["beneficial_occupancy_registered"], bool)
    for field in ("retainage_held_cents", "retainage_paid_cents", "retainage_outstanding_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["sc_rejection_count"], int) and data["sc_rejection_count"] >= 0
    _assert_nullable_ts(data, "substantial_completion_date")
    _assert_nullable_ts(data, "warranty_start_date")
    _assert_nullable_ts(data, "beneficial_occupancy_date")
    _assert_nullable_ts(data, "closed_at")


def assert_trade_package(data: dict):
    _assert_common_fields(data)
    assert data["trade_name"] in TRADE_NAMES
    assert data["responsible_type"] in ("SUBCONTRACTOR", "SELF_PERFORMED")
    assert isinstance(data["has_completed_walk"], bool)
    assert isinstance(data["open_item_count"], int) and data["open_item_count"] >= 0
    for field in ("om_doc_approved", "warranty_doc_approved", "asbuilt_doc_approved",
                  "has_conducted_training", "closeout_ready"):
        assert isinstance(data[field], bool)
    assert data["lien_waiver_status"] in ("NONE", "SUBMITTED", "ACCEPTED", "REJECTED")


def assert_punch_walk(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lead_inspector_id"], str) and data["lead_inspector_id"]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in ("SCHEDULED", "COMPLETED")


def assert_punch_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["severity"] in ("LIFE_SAFETY", "MAJOR", "MINOR")
    for field in ("location_building", "location_floor", "location_area", "photo_ref"):
        assert isinstance(data[field], str) and data[field]
    assert data["status"] in ("OPEN", "READY_FOR_REVIEW", "VERIFIED", "VOIDED")
    assert isinstance(data["rejection_count"], int) and data["rejection_count"] >= 0


def assert_closeout_document(data: dict):
    _assert_common_fields(data)
    assert data["doc_type"] in ("OM_MANUAL", "WARRANTY_DOC", "AS_BUILT")
    assert isinstance(data["file_ref"], str) and data["file_ref"]
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED")


def assert_training_session(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["system_name"], str) and data["system_name"]
    assert isinstance(data["location_room"], str) and data["location_room"]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert isinstance(data["reschedule_count"], int) and data["reschedule_count"] >= 0
    assert data["status"] in ("SCHEDULED", "CONDUCTED")


def assert_retainage_release(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in ("REDUCTION", "FINAL")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("REQUESTED", "PAID", "VOIDED")


def assert_warranty_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["severity"] in ("CRITICAL", "MAJOR", "MINOR")
    assert isinstance(data["description"], str)
    assert is_iso8601_timestamp(data["reported_at"])
    assert data["status"] in ("REPORTED", "TRIAGED", "RESOLVED", "DENIED")
    _assert_nullable_ts(data, "sla_due_at")


def assert_retainage_ledger_conserved(project: dict, expected_held: int):
    """PRD §2.6: outstanding is always held minus paid; held is frozen at creation."""
    assert project["retainage_held_cents"] == expected_held
    assert project["retainage_paid_cents"] + project["retainage_outstanding_cents"] == expected_held, (
        f"ledger not conserved: paid {project['retainage_paid_cents']} + "
        f"outstanding {project['retainage_outstanding_cents']} != held {expected_held}"
    )
    assert project["retainage_paid_cents"] >= 0
    assert project["retainage_outstanding_cents"] >= 0


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating optional fractional digits."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


def assert_timestamp_instant_equals(actual: str, expected_iso8601: str):
    """Compare two timestamps by instant, not by rendering.

    The PRD pins the logical instant stamped from the server clock but leaves
    fractional-digit rendering open, so compare parsed instants.
    """
    assert _parse_instant(actual) == _parse_instant(expected_iso8601), (
        f"Expected instant {expected_iso8601}, got {actual}"
    )
