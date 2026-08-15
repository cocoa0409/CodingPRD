"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

COURSE_STATUSES = [
    "CONSULT", "SIMULATION_SCHEDULED", "SIMULATED", "CONTOURING", "PLANNING",
    "PHYSICS_REVIEW", "TREATMENT_READY", "ON_TREATMENT", "ADAPTATION_REQUIRED",
    "REPLANNING", "COMPLETED", "DISCONTINUED",
]
SIM_STATUSES = ["SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW"]
CONTOUR_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "RETURNED"]
PLAN_STATUSES = [
    "DRAFT", "PENDING_PRIMARY_CHECK", "PENDING_SECOND_CHECK",
    "APPROVED_FOR_DELIVERY", "ACTIVE", "CHECK_FAILED", "SUPERSEDED", "COMPLETED",
]
SESSION_STATUSES = ["SCHEDULED", "DELIVERED", "CANCELLED", "NO_SHOW"]
CLAIM_STATUSES = ["DRAFT", "FINALIZED", "SUBMITTED"]
INTERRUPTION_STATUSES = ["OPEN", "COMPENSATED"]
MACHINE_STATUSES = ["OPERATIONAL", "DOWN"]
CHARGE_CODES = [
    "SIMULATION", "PLANNING", "PHYSICS_CHECK", "FRACTION_DELIVERY",
    "IGRT", "FIRST_FRACTION_SETUP", "NO_SHOW_FEE",
]


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an int"


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]


def assert_course(data: dict):
    _assert_common(data)
    assert data["status"] in COURSE_STATUSES
    assert data["technique"] in ["THREE_DCRT", "IMRT", "SBRT"]
    assert isinstance(data["prescribed_total_dose_cGy"], int)
    assert isinstance(data["planned_fractions"], int)
    assert isinstance(data["dose_per_fraction_cGy"], int)
    assert isinstance(data["delivered_fractions"], int)
    assert isinstance(data["delivered_dose_cGy"], int)
    assert isinstance(data["fractions_since_chart_review"], int)
    assert isinstance(data["weekend_makeup_allowance"], int)
    assert isinstance(data["open_interruption_count"], int)
    # BED figures are expressed with three decimal places (rounded half up)
    for k in ("bed_nominal_gy", "bed_actual_gy"):
        v = data[k]
        assert isinstance(v, (int, float)), f"{k} must be numeric"
        assert abs(v * 1000 - round(v * 1000)) < 1e-6, f"{k} must carry 3-decimal precision"


def assert_simulation(data: dict):
    _assert_common(data)
    assert data["status"] in SIM_STATUSES
    assert data["immobilization_device"] in ["NONE", "THERMOPLASTIC_MASK", "VACUUM_CRADLE", "BODY_FRAME"]
    assert is_iso8601_timestamp(data["start_time"])
    assert is_iso8601_timestamp(data["end_time"])


def assert_contour_set(data: dict):
    _assert_common(data)
    assert data["status"] in CONTOUR_STATUSES
    assert isinstance(data["target_volumes"], list)
    assert isinstance(data["oar_structures"], list)
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_plan(data: dict):
    _assert_common(data)
    assert data["status"] in PLAN_STATUSES
    assert isinstance(data["plan_version"], int) and data["plan_version"] >= 1
    assert isinstance(data["target_total_dose_cGy"], int)
    assert isinstance(data["planned_fractions"], int)
    assert isinstance(data["dose_per_fraction_cGy"], int)
    assert isinstance(data["pinned_contour_version"], int)
    assert isinstance(data["planner_id"], str)


def assert_dose_constraint(data: dict):
    _assert_common(data)
    assert data["constraint_type"] in ["MAX_DOSE", "MEAN_DOSE"]
    assert isinstance(data["limit_cGy"], int) and data["limit_cGy"] > 0
    assert isinstance(data["evaluated_value_cGy"], int) and data["evaluated_value_cGy"] >= 0
    assert isinstance(data["satisfied"], bool)
    assert data["satisfied"] == (data["evaluated_value_cGy"] <= data["limit_cGy"])


def assert_machine(data: dict):
    _assert_common(data)
    assert data["machine_type"] in ["CT_SIMULATOR", "LINAC"]
    assert data["status"] in MACHINE_STATUSES


def assert_fraction_session(data: dict):
    _assert_common(data)
    assert data["status"] in SESSION_STATUSES
    assert isinstance(data["fraction_number"], int) and data["fraction_number"] >= 1
    assert isinstance(data["is_first_fraction"], bool)
    assert isinstance(data["is_weekend"], bool)
    assert data["is_first_fraction"] == (data["fraction_number"] == 1)


def assert_interruption(data: dict):
    _assert_common(data)
    assert data["status"] in INTERRUPTION_STATUSES
    assert data["reason"] in ["MACHINE_DOWN", "PATIENT_ILLNESS", "OTHER"]
    assert isinstance(data["missed_count"], int) and data["missed_count"] >= 1
    assert isinstance(data["gap_days"], int) and data["gap_days"] >= 1


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in CLAIM_STATUSES
    for k in ("provisional_total_cents", "gross_total_cents", "discount_cents", "final_total_cents"):
        assert isinstance(data[k], int), f"{k} must be integer cents"


def assert_physics_check(data: dict):
    """Append-only record: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not expose version"
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert data["check_type"] in ["PRIMARY", "SECOND"]
    assert data["outcome"] in ["PASS", "FAIL"]
    assert isinstance(data["checker_id"], str) and data["checker_id"]


def assert_chart_review(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not expose version"
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert data["outcome"] in ["PASS", "FAIL"]
    assert isinstance(data["reviewer_id"], str) and data["reviewer_id"]
    assert isinstance(data["delivered_fractions_at_review"], int)


def assert_charge_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not expose version"
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert data["code"] in CHARGE_CODES
    assert data["quantity"] == 1
    assert isinstance(data["unit_charge_cents"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] == data["quantity"] * data["unit_charge_cents"]
