"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates response structure against the PRD contract. The
medication administration record is append-only and carries only id + created_at,
so its assertion never demands updated_at or version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["license_number"], str)
    assert isinstance(data["care_point_rate_cents"], int)
    assert data["license_status"] in ("ACTIVE", "CONDITIONAL", "SUSPENDED")
    assert isinstance(data["bed_count"], int) and data["bed_count"] >= 0
    assert isinstance(data["occupied_bed_count"], int) and data["occupied_bed_count"] >= 0
    assert isinstance(data["occupancy_rate_bps"], int) and data["occupancy_rate_bps"] >= 0
    assert isinstance(data["open_deficiency_count"], int) and data["open_deficiency_count"] >= 0


def assert_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["unit_number"], str)
    assert data["wing"] in ("ASSISTED_LIVING", "MEMORY_CARE")
    assert isinstance(data["monthly_base_rent_cents"], int)
    assert data["status"] in ("AVAILABLE", "RESERVED", "OCCUPIED", "CLEANING", "RETIRED")


def assert_resident(data: dict):
    _assert_common(data)
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert data["stay_type"] in ("STANDARD", "RESPITE")
    assert data["status"] in ("PROSPECT", "ASSESSED", "ADMITTED", "DISCHARGE_PENDING", "DISCHARGED")
    assert isinstance(data["current_care_points"], int)
    assert isinstance(data["open_balance_cents"], int)
    assert data["current_care_level"] in (None, "LEVEL_1", "LEVEL_2", "LEVEL_3", "MEMORY_CARE")


def assert_assessment(data: dict):
    _assert_common(data)
    assert isinstance(data["resident_id"], str)
    for f in ("adl_bathing", "adl_dressing", "adl_toileting", "adl_transferring", "adl_eating"):
        assert isinstance(data[f], int) and 0 <= data[f] <= 4
    assert isinstance(data["cognition_score"], int) and 0 <= data["cognition_score"] <= 10
    assert isinstance(data["behavior_flags"], int) and data["behavior_flags"] >= 0
    assert isinstance(data["care_points_total"], int)
    assert data["care_level"] in ("LEVEL_1", "LEVEL_2", "LEVEL_3", "MEMORY_CARE")
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")


def assert_care_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["resident_id"], str)
    assert isinstance(data["source_assessment_id"], str)
    assert isinstance(data["adl_support_items"], list)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED", "ARCHIVED")


def assert_medication_order(data: dict):
    _assert_common(data)
    assert isinstance(data["resident_id"], str)
    assert isinstance(data["drug_name"], str)
    assert isinstance(data["dose"], str)
    assert isinstance(data["schedule_times"], list) and len(data["schedule_times"]) > 0
    assert isinstance(data["is_controlled"], bool)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_administration_record(data: dict):
    """Append-only eMAR event: id + created_at only. NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "eMAR record must NOT carry updated_at"
    assert "version" not in data, "eMAR record must NOT carry version"
    assert isinstance(data["medication_order_id"], str)
    assert isinstance(data["resident_id"], str)
    assert isinstance(data["scheduled_time"], str)
    assert data["outcome"] in ("GIVEN", "REFUSED", "HELD", "MISSED")
    assert isinstance(data["administered_by_user_id"], str)


def assert_move_in_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["resident_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["move_in_date"], str)
    assert isinstance(data["monthly_base_rent_cents"], int)
    assert isinstance(data["community_fee_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "TERMINATED", "CANCELLED")


def assert_billing_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["resident_id"], str)
    assert isinstance(data["period_year"], int)
    assert isinstance(data["period_month"], int) and 1 <= data["period_month"] <= 12
    assert isinstance(data["paid_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "VOID")


def assert_incident_report(data: dict):
    _assert_common(data)
    assert isinstance(data["resident_id"], str)
    assert data["incident_type"] in ("FALL", "MEDICATION_ERROR", "ELOPEMENT", "INJURY", "OTHER")
    assert isinstance(data["occurred_at"], str)
    assert data["severity"] in ("MINOR", "MODERATE", "SEVERE")
    assert isinstance(data["requires_state_report"], bool)
    assert data["status"] in ("REPORTED", "UNDER_INVESTIGATION", "RESOLVED", "ESCALATED")


def assert_survey_deficiency(data: dict):
    _assert_common(data)
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["tag_code"], str)
    assert data["scope_severity"] in (
        "A_C_NO_HARM", "D_F_NO_HARM", "G_I_ACTUAL_HARM", "J_L_IMMEDIATE_JEOPARDY",
    )
    assert isinstance(data["cited_at"], str)
    assert isinstance(data["poc_due_date"], str)
    assert data["status"] in (
        "CITED", "POC_SUBMITTED", "POC_ACCEPTED", "POC_REJECTED", "CORRECTED",
    )
