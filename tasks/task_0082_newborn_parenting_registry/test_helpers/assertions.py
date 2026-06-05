"""Entity assertions and domain invariant checkers.

These validate the response shape declared by the PRD for each resource, using the
framework's generic validators internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """The four system-managed properties present on every lifecycle resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_insurance_policy(data: dict):
    _assert_common(data)
    assert data["plan_type"] in ("EMPLOYER_GROUP", "MARKETPLACE", "MEDICAID")
    assert isinstance(data["dependent_slots_max"], int) and data["dependent_slots_max"] >= 1
    assert isinstance(data["dependents_added_count"], int) and data["dependents_added_count"] >= 0


def assert_registration(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "ADMITTED", "BIRTH_RECORDED", "CLOSED", "CANCELLED")
    assert isinstance(data["newborn_count"], int) and data["newborn_count"] >= 0


def assert_newborn(data: dict):
    _assert_common(data)
    assert data["clinical_status"] in (
        "BORN", "ROOMING_IN", "NICU_ADMITTED", "STEP_DOWN", "DISCHARGE_READY", "DISCHARGED")
    assert data["care_location"] in (
        "WELL_BABY_NURSERY", "MOTHER_ROOM", "NICU", "STEP_DOWN_UNIT", "RELEASED")
    assert isinstance(data["discharge_readiness_score"], int)
    assert 0 <= data["discharge_readiness_score"] <= 100


def assert_lactation_consult(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "FEEDING_AT_RISK", "CANCELLED")
    assert isinstance(data["feeding_adequate"], bool)


def assert_nicu_bed(data: dict):
    _assert_common(data)
    assert data["acuity_level"] in ("LEVEL_2", "LEVEL_3", "LEVEL_4")
    assert data["occupancy_status"] in ("VACANT", "OCCUPIED", "OUT_OF_SERVICE")


def assert_nicu_stay(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING_BED", "ACTIVE", "STEPPED_DOWN", "CLOSED", "CANCELLED")
    assert data["required_level"] in ("LEVEL_2", "LEVEL_3", "LEVEL_4")


def assert_discharge_bag(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ASSEMBLED", "ISSUED", "RECALLED")
    assert isinstance(data["total_value_cents"], int) and data["total_value_cents"] >= 0
    assert isinstance(data["requires_pharmacy_signoff"], bool)


def assert_follow_up_task(data: dict):
    _assert_common(data)
    assert data["task_type"] in ("WEIGHT_CHECK", "JAUNDICE_CHECK", "FEEDING_CHECK", "SAFETY_CALL")
    assert data["status"] in (
        "OPEN", "ATTEMPTED", "COMPLETED", "ESCALATED", "MISSED", "CANCELLED")
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_dependent_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ENROLLED", "SEP_EXPIRED", "DENIED", "TERMINATED")


def assert_government_filing(data: dict):
    _assert_common(data)
    assert data["filing_type"] in ("BIRTH_CERTIFICATE", "SSN_APPLICATION")
    assert data["status"] in (
        "PENDING", "SUBMITTED", "ACCEPTED", "REJECTED", "LATE_FLAGGED", "CANCELLED")


def assert_audit_event(data: dict):
    """Immutable record (PRD §2.4): id + created_at only; no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "audit event id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "audit event must NOT carry updated_at"
    assert "version" not in data, "audit event must NOT carry version"


# --- Domain invariant checkers ---

def assert_dependent_slots_invariant(policy: dict, expected_enrolled_count: int):
    """PRD §3.10: dependents_added_count is the number of enrollments currently in
    ENROLLED, recomputed as enrollments come and go."""
    assert policy["dependents_added_count"] == expected_enrolled_count, (
        f"dependents_added_count should be {expected_enrolled_count}, "
        f"got {policy['dependents_added_count']}")
    assert policy["dependents_added_count"] <= policy["dependent_slots_max"]


def assert_bed_vacated(bed: dict):
    """PRD §3.4: a freed bed has occupancy_status VACANT and a null current_stay_id."""
    assert bed["occupancy_status"] == "VACANT", f"bed should be VACANT, got {bed['occupancy_status']}"
    assert bed["current_stay_id"] is None, (
        f"freed bed current_stay_id should be null, got {bed['current_stay_id']!r}")


def assert_bed_occupied_by(bed: dict, stay_id: str):
    """PRD §3.4: an occupied bed points its current_stay_id at the occupying stay."""
    assert bed["occupancy_status"] == "OCCUPIED", (
        f"bed should be OCCUPIED, got {bed['occupancy_status']}")
    assert bed["current_stay_id"] == stay_id, (
        f"bed current_stay_id should be {stay_id}, got {bed['current_stay_id']}")
