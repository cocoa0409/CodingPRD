"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

DEPARTMENTS = [
    "EMERGENCY", "ICU", "SURGERY", "NURSING", "PHARMACY", "LOGISTICS", "ADMINISTRATION",
]
COMMAND_ROLES = [
    "INCIDENT_COMMANDER", "PLANNING_CHIEF", "LOGISTICS_CHIEF",
    "PUBLIC_INFORMATION_OFFICER", "LIAISON_OFFICER", "SAFETY_OFFICER",
    "MEDICAL_BRANCH_DIRECTOR",
]
HAZARD_CATEGORIES = ["NATURAL", "TECHNOLOGICAL", "HUMAN", "HAZMAT"]
INCIDENT_TYPES = ["NATURAL", "TECHNOLOGICAL", "HUMAN", "HAZMAT", "INFECTIOUS"]
TRIAGE_CATEGORIES = ["IMMEDIATE", "DELAYED", "MINOR", "EXPECTANT"]
SURGE_TIERS = ["GREEN", "YELLOW", "ORANGE", "RED"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_optional_ts(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{field} must be null or ISO 8601, got {value!r}"
    )


def assert_timestamp_instant(value: str, expected_iso: str):
    """Assert two ISO 8601 timestamps denote the same UTC instant, regardless of
    fractional-digit spelling."""
    def _parse(s: str) -> datetime:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    assert _parse(value) == _parse(expected_iso), (
        f"expected instant {expected_iso}, got {value!r}"
    )


def assert_staff_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["badge_number"], str) and data["badge_number"]
    assert data["department"] in DEPARTMENTS
    assert isinstance(data["role_qualifications"], list)
    for role in data["role_qualifications"]:
        assert role in COMMAND_ROLES
    assert isinstance(data["is_active"], bool)
    assert isinstance(data["callback_eligible"], bool)
    assert isinstance(data["callback_seniority_score"], int)


def assert_hazard_assessment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fiscal_year"], str)
    assert data["scoring_model"] in ["TWO_FACTOR", "THREE_FACTOR_MITIGATION"]
    assert isinstance(data["hazard_entries"], list)
    for entry in data["hazard_entries"]:
        assert entry["category"] in HAZARD_CATEGORIES
        assert 0 <= entry["probability"] <= 3
        assert 0 <= entry["severity"] <= 3
        assert 0 <= entry["preparedness"] <= 3
        assert isinstance(entry["risk_score"], int)
    assert isinstance(data["max_risk_score"], int)
    assert isinstance(data["plan_review_triggered"], bool)
    assert data["status"] in ["DRAFT", "FINALIZED"]


def assert_plan_revision(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["revision_label"], str)
    assert data["status"] in ["DRAFT", "IN_REVIEW", "APPROVED", "SUPERSEDED"]
    assert isinstance(data["created_by_id"], str)
    assert data.get("approved_by_id") is None or isinstance(data["approved_by_id"], str)
    _assert_optional_ts(data, "approved_at")


def assert_exercise_event(data: dict):
    _assert_common_fields(data)
    assert data["exercise_type"] in ["TABLETOP", "FUNCTIONAL", "FULL_SCALE"]
    assert data["scenario_category"] in HAZARD_CATEGORIES
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
    _assert_optional_ts(data, "started_at")
    _assert_optional_ts(data, "completed_at")


def assert_after_action_report(data: dict):
    _assert_common_fields(data)
    assert data["subject_type"] in ["EXERCISE", "INCIDENT"]
    assert isinstance(data["subject_id"], str)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED"]
    assert isinstance(data["created_by_id"], str)
    _assert_optional_ts(data, "submitted_at")
    _assert_optional_ts(data, "approved_at")


def assert_improvement_task(data: dict):
    _assert_common_fields(data)
    assert data["priority"] in ["HIGH", "MEDIUM", "LOW"]
    assert data["assigned_department"] in DEPARTMENTS
    assert data["status"] in ["OPEN", "IN_PROGRESS", "OVERDUE", "VERIFIED_COMPLETE"]


def assert_incident_event(data: dict):
    _assert_common_fields(data)
    assert data["incident_type"] in INCIDENT_TYPES
    assert data["status"] in ["ACTIVATED", "DEACTIVATED"]
    assert isinstance(data["activation_count"], int) and data["activation_count"] >= 1
    _assert_optional_ts(data, "activated_at")
    _assert_optional_ts(data, "deactivated_at")
    assert data.get("staffed_bed_count") is None or isinstance(data["staffed_bed_count"], int)
    assert data.get("projected_census") is None or isinstance(data["projected_census"], int)
    assert data.get("licensed_surge_capacity") is None or isinstance(
        data["licensed_surge_capacity"], int
    )
    assert data.get("operational_surge_capacity") is None or isinstance(
        data["operational_surge_capacity"], int
    )
    assert data.get("current_surge_tier") is None or data["current_surge_tier"] in SURGE_TIERS
    assert isinstance(data["committed_staff_count"], int)


def assert_command_role_assignment(data: dict):
    _assert_common_fields(data)
    assert data["command_role"] in COMMAND_ROLES
    assert data["status"] in ["ACTIVE", "RELIEVED"]
    assert is_iso8601_timestamp(data["assigned_at"])


def assert_callback_request(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "PENDING", "ACCEPTED", "DECLINED", "EXPIRED", "CANCELLED", "COMPLETED",
    ]
    assert isinstance(data["response_window_hours"], int)
    assert is_iso8601_timestamp(data["expires_at"])
    _assert_optional_ts(data, "responded_at")


def assert_supply_item(data: dict):
    _assert_common_fields(data)
    assert data["category"] in ["PPE", "MEDICATION", "OXYGEN", "OTHER_SUPPLY"]
    assert isinstance(data["quantity_on_hand"], int)
    assert isinstance(data["observed_daily_burn_rate"], (int, float))
    assert isinstance(data["projected_daily_burn_rate"], (int, float))
    assert data.get("days_of_supply") is None or isinstance(data["days_of_supply"], int)
    assert isinstance(data["below_reorder_level"], bool)
    assert isinstance(data["reorder_min_days"], int)


def assert_stock_transaction(data: dict):
    """Append-only ledger entry: id + created_at only; updated_at and version
    must be absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger entries must not carry updated_at"
    assert "version" not in data, "ledger entries must not carry version"
    assert data["transaction_type"] in ["RECEIVE", "ISSUE", "RETURN", "ADJUST"]
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert is_iso8601_timestamp(data["occurred_at"])


def assert_alternate_care_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bed_capacity"], int) and data["bed_capacity"] > 0
    assert data["status"] in ["STANDBY", "COMMITTED", "ACTIVATED", "DEMOBILIZED"]
    assert isinstance(data["commitments"], list)
    for c in data["commitments"]:
        assert isinstance(c["incident_id"], str)
        assert is_iso8601_timestamp(c["window_start"])
        assert is_iso8601_timestamp(c["window_end"])
    assert data.get("activated_incident_id") is None or isinstance(
        data["activated_incident_id"], str
    )
    assert isinstance(data["current_census"], int)


def assert_patient_track_record(data: dict):
    _assert_common_fields(data)
    assert data["triage_category"] in TRIAGE_CATEGORIES
    assert data["status"] in ["TRACKED", "TRANSFERRED", "DISCHARGED"]
    assert data.get("transfer_site_id") is None or isinstance(data["transfer_site_id"], str)
    _assert_optional_ts(data, "transferred_at")
    _assert_optional_ts(data, "discharged_at")
    assert isinstance(data["reunified"], bool)


def assert_family_inquiry(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["OPEN", "MATCHED", "REUNITED", "CLOSED_NO_MATCH"]
    assert data.get("matched_patient_record_id") is None or isinstance(
        data["matched_patient_record_id"], str
    )
    _assert_optional_ts(data, "matched_at")
    _assert_optional_ts(data, "reunited_at")


def assert_external_report(data: dict):
    _assert_common_fields(data)
    assert data["audience"] in ["REGIONAL_COALITION", "STATE_DOH", "CMS", "LOCAL_EMA"]
    assert data["report_type"] in ["SITREP", "SURGE_CAPACITY", "AAR_SUMMARY", "RESOURCE_REQUEST"]
    assert data["status"] in ["DRAFT", "SUBMITTED"]
    assert is_iso8601_timestamp(data["due_at"])
    _assert_optional_ts(data, "submitted_at")
    assert data.get("submitted_late") is None or isinstance(data["submitted_late"], bool)
    assert data.get("hours_late") is None or isinstance(data["hours_late"], (int, float))


def assert_incident_surge_invariants(data: dict):
    """Domain invariants linking the two capacity variants and the tier (PRD §3.4)."""
    if data.get("licensed_surge_capacity") is not None:
        assert data["licensed_surge_capacity"] == data["staffed_bed_count"]
    if data.get("operational_surge_capacity") is not None:
        assert data["operational_surge_capacity"] >= data["licensed_surge_capacity"]
