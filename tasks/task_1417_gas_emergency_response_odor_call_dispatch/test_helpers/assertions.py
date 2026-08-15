"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_territory(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    for f in ("p1_threshold_minutes", "p2_threshold_minutes",
              "p3_threshold_minutes", "p4_threshold_minutes",
              "recurrence_window_hours", "repair_budget_cap_cents"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert isinstance(data["repair_reserved_cents"], int)
    assert data["repair_reserved_cents"] >= 0


def assert_technician(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["badge_number"], str) and len(data["badge_number"]) > 0
    assert is_valid_uuid(data.get("home_territory_id", ""))
    assert isinstance(data["hourly_rate_cents"], int)
    assert isinstance(data["is_active"], bool)
    assert isinstance(data["on_shift"], bool)
    assert isinstance(data["active_assignment_count"], int)
    assert data["active_assignment_count"] >= 0
    assert isinstance(data["weighted_load"], int)
    assert data["last_cleared_at"] is None or is_iso8601_timestamp(data["last_cleared_at"])


def assert_shift(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data["shift_start"])
    assert is_iso8601_timestamp(data["shift_end"])
    assert "version" not in data, "shift is an immutable record: no version"
    assert "updated_at" not in data, "shift is an immutable record: no updated_at"


def assert_crew(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["crew_code"], str) and len(data["crew_code"]) > 0
    assert is_valid_uuid(data.get("territory_id", ""))
    assert isinstance(data["hourly_rate_cents"], int)
    assert isinstance(data["is_active"], bool)


def assert_emergency_call(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data["received_at"])
    assert data["implied_priority"] in ("P1", "P2", "P3", "P4")
    assert data["classification"] in ("PRIMARY", "DUPLICATE", "RECURRENCE")
    assert isinstance(data["is_duplicate"], bool)
    assert is_valid_uuid(data.get("incident_id", ""))
    assert "version" not in data, "emergency call is an immutable record: no version"
    assert "updated_at" not in data, "emergency call is an immutable record: no updated_at"


def assert_incident(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["lifecycle_status"] in (
        "NEW", "TRIAGED", "DISPATCHED", "ON_SCENE", "MAKE_SAFE_IN_PROGRESS",
        "MONITORING", "CLOSED", "REOPENED", "MERGED",
    )
    assert data["entry_status"] in (
        "NOT_REQUIRED", "AWAITING_AUTHORIZATION", "AUTHORIZED", "FORCED", "REFUSED",
    )
    assert data["priority"] in ("P1", "P2", "P3", "P4")
    assert data["breach_class"] in ("NONE", "RESPONDED_LATE", "NO_RESPONSE")
    assert isinstance(data["severity_score"], int)
    assert 0 <= data["severity_score"] <= 100
    assert isinstance(data["linked_call_count"], int) and data["linked_call_count"] >= 1
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert isinstance(data["raw_elapsed_seconds"], int)
    assert isinstance(data["adjusted_elapsed_seconds"], int)
    assert data["adjusted_elapsed_seconds"] >= 0
    assert isinstance(data["pause_total_seconds"], int)
    assert isinstance(data["threshold_minutes"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1
    for f in ("awaiting_dispatch", "evacuation_required", "make_safe_completed",
              "leak_confirmed", "gas_flow_stopped", "customer_referral_required",
              "auto_notification_created"):
        assert isinstance(data[f], bool), f"{f} must be bool"


def assert_dispatch(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("incident_id", ""))
    assert is_valid_uuid(data.get("technician_id", ""))
    assert data["status"] in ("EN_ROUTE", "ON_SCENE", "CLEARED", "PREEMPTED", "CANCELLED")
    assert is_iso8601_timestamp(data["dispatched_at"])
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_pause(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("incident_id", ""))
    assert data["reason"] in ("CUSTOMER_NOT_HOME", "ACCESS_BLOCKED")
    assert data["status"] in ("OPEN", "CLOSED")
    assert is_iso8601_timestamp(data["started_at"])
    assert isinstance(data["duration_seconds"], int)
    assert data["duration_seconds"] >= 0


def assert_reading(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("incident_id", ""))
    assert is_valid_uuid(data.get("technician_id", ""))
    assert 0.0 <= float(data["pct_lel"]) <= 100.0
    assert float(data["co_ppm"]) >= 0
    assert data["reading_context"] in ("INSIDE", "OUTSIDE", "CONFINED_SPACE")
    assert is_iso8601_timestamp(data["taken_at"])
    assert "version" not in data, "reading is an immutable record: no version"
    assert "updated_at" not in data, "reading is an immutable record: no updated_at"


def assert_make_safe_action(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["action_type"] in (
        "VENTILATE", "SHUT_APPLIANCE_VALVE", "EVACUATE", "SECURE_AREA", "OTHER",
    )
    assert is_iso8601_timestamp(data["performed_at"])
    assert "version" not in data, "make-safe action is an immutable record: no version"
    assert "updated_at" not in data, "make-safe action is an immutable record: no updated_at"


def assert_entry_authorization(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["method"] in ("CUSTOMER_CONSENT", "EMERGENCY_FORCED", "WARRANT")
    assert isinstance(data["authorized_by_name"], str)
    assert isinstance(data["recorded_by_user_id"], str)
    assert "version" not in data, "entry authorization is an immutable record: no version"
    assert "updated_at" not in data, "entry authorization is an immutable record: no updated_at"


def assert_shutoff_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("incident_id", ""))
    assert data["scope"] in ("METER", "APPLIANCE", "SERVICE_LINE")
    assert isinstance(data["entry_required"], bool)
    assert data["status"] in ("REQUESTED", "AUTHORIZED", "DECLINED", "EXECUTED", "RESTORED")
    assert isinstance(data["requested_by_user_id"], str)


def assert_determination(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("incident_id", ""))
    assert data["responsibility"] in ("INSIDE_CUSTOMER", "OUTSIDE_COMPANY", "SHARED")
    assert data["basis"] in (
        "METER_LOCATION", "BARHOLE_SURVEY", "CUSTOMER_APPLIANCE_TRACE", "EXCAVATION",
    )
    assert data["status"] in ("DRAFT", "FINAL", "SUPERSEDED")
    assert isinstance(data["drafted_by_user_id"], str)


def assert_work_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("incident_id", ""))
    assert data["origin"] in ("AUTO_DETERMINATION", "MANUAL")
    assert data["status"] in (
        "OPEN", "SCHEDULED", "IN_PROGRESS", "ON_HOLD", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["provisional_estimate_cents"], int)
    assert data["provisional_estimate_cents"] >= 0
    assert isinstance(data["current_estimate_cents"], int)
    assert data["current_estimate_cents"] >= 0


def assert_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("territory_id", ""))
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")
    assert isinstance(data["incident_count"], int) and data["incident_count"] >= 0
    assert isinstance(data["determined_count"], int) and data["determined_count"] >= 0
    assert isinstance(data["pending_count"], int) and data["pending_count"] >= 0
    assert isinstance(data["compliant_count_raw"], int)
    assert isinstance(data["compliant_count_adjusted"], int)
    assert isinstance(data["needs_regeneration"], bool)
    assert isinstance(data["regeneration_count"], int)


def assert_notification(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("incident_id", ""))
    assert data["channel"] in ("MEDIA", "PUBLIC_ALERT", "AGENCY_NOTICE")
    assert data["origin"] in ("MANUAL", "AUTO_PRIORITY", "AUTO_SEVERITY")
    assert data["status"] in ("DRAFT", "ISSUED", "RETRACTED", "DISCARDED")


def assert_report_conservation(data: dict):
    """Report counts must reconcile: pending = incident_count - determined_count."""
    assert data["pending_count"] == data["incident_count"] - data["determined_count"]
    assert data["compliant_count_adjusted"] <= data["determined_count"]
    assert data["compliant_count_raw"] <= data["determined_count"]
