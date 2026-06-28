"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer >= 1"
    )


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["timezone"], str)


def assert_program(data: dict):
    _assert_common(data)
    assert data["level_of_care"] in ["RESIDENTIAL", "PHP", "IOP", "OP"]
    assert isinstance(data["bed_capacity"], int) and data["bed_capacity"] >= 1
    assert isinstance(data["beds_occupied"], int) and data["beds_occupied"] >= 0
    assert isinstance(data["beds_available"], int) and data["beds_available"] >= 0
    assert data["occupancy_posture"] in ["OPEN", "FULL"]
    assert data["status"] in ["OPEN", "CLOSED"]
    assert_program_invariants(data)


def assert_program_invariants(data: dict):
    """beds_available = max(bed_capacity - beds_occupied, 0)."""
    expected_available = max(data["bed_capacity"] - data["beds_occupied"], 0)
    assert data["beds_available"] == expected_available, (
        f"beds_available {data['beds_available']} != "
        f"max(bed_capacity - beds_occupied, 0) = {expected_available}"
    )
    expected_posture = "FULL" if data["beds_occupied"] >= data["bed_capacity"] else "OPEN"
    assert data["occupancy_posture"] == expected_posture, (
        f"occupancy_posture {data['occupancy_posture']} != {expected_posture}"
    )


def assert_cohort(data: dict):
    _assert_common(data)
    assert data["age_band"] in ["ADOLESCENT", "ADULT"]
    assert isinstance(data["slot_capacity"], int) and data["slot_capacity"] >= 1
    assert isinstance(data["slots_filled"], int) and data["slots_filled"] >= 0


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["age_band"] in ["ADOLESCENT", "ADULT"]
    assert data["medical_stability_posture"] in ["STABLE", "GUARDED", "UNSTABLE"]
    assert 0 <= data["nutritional_risk_score"] <= 100
    assert 0 <= data["provisional_nutritional_risk_score"] <= 100


def assert_assessment(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "FINALIZED", "SUPERSEDED"]
    assert 0 <= data["composite_score"] <= 100
    assert data["recommended_level_of_care"] in ["RESIDENTIAL", "PHP", "IOP", "OP"]


def assert_admission(data: dict):
    _assert_common(data)
    assert data["clinical_status"] in [
        "WAITLISTED",
        "PENDING_ADMISSION",
        "ADMITTED",
        "MEDICAL_HOLD",
        "DISCHARGE_PENDING",
        "DISCHARGED",
        "ADMINISTRATIVE_DISCHARGE",
    ]
    if data.get("level_of_care") is not None:
        assert data["level_of_care"] in ["RESIDENTIAL", "PHP", "IOP", "OP"]
    assert isinstance(data["waitlist_promoted"], bool)


def assert_authorization(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "PENDING",
        "APPROVED",
        "DENIED",
        "APPEALED",
        "EXPIRED",
        "EXHAUSTED",
    ]
    assert isinstance(data["days_authorized"], int) and data["days_authorized"] >= 0
    assert isinstance(data["days_consumed"], int) and data["days_consumed"] >= 0
    assert isinstance(data["days_remaining"], int) and data["days_remaining"] >= 0


def assert_days_conservation(data: dict):
    """days_consumed + days_remaining == days_authorized; days_remaining floored at 0."""
    assert data["days_remaining"] == max(
        data["days_authorized"] - data["days_consumed"], 0
    ), "days_remaining must equal max(days_authorized - days_consumed, 0)"


def assert_review(data: dict):
    _assert_common(data)
    assert data["decision"] in ["APPROVE", "DENY"]
    assert isinstance(data["approved_days"], int) and data["approved_days"] >= 0


def assert_treatment_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "ACTIVE", "REVISION", "SUPERSEDED", "CLOSED"]
    assert isinstance(data["therapy_signed"], bool)
    assert isinstance(data["dietitian_signed"], bool)
    assert isinstance(data["medical_signed"], bool)
    assert isinstance(data["goals_total"], int)
    assert isinstance(data["goals_met"], int)
    assert 0 <= data["goals_met"] <= data["goals_total"]


def assert_meal_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "CLOSED"]
    assert data["supervision_level"] in ["FULL", "PARTIAL"]
    assert isinstance(data["meals_logged"], int) and data["meals_logged"] >= 0
    assert 0.0 <= data["meal_compliance_rate"] <= 1.0


def assert_meal_event(data: dict):
    """Append-only log row: id + created_at only; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "created_at must be ISO 8601"
    assert data["meal_type"] in ["BREAKFAST", "LUNCH", "DINNER", "SNACK"]


def assert_family_program(data: dict):
    _assert_common(data)
    assert data["status"] in ["ENROLLED", "COMPLETED", "WAIVED"]
    assert isinstance(data["sessions_required"], int) and data["sessions_required"] >= 0
    assert isinstance(data["sessions_completed"], int)


def assert_discharge_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "FINALIZED"]
    assert data["aftercare_level_of_care"] in ["PHP", "IOP", "OP", "NONE"]
    assert isinstance(data["relapse_plan_complete"], bool)
