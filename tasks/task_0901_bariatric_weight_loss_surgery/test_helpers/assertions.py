"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["mrn"], str) and len(data["mrn"]) > 0
    assert data["sex"] in ("MALE", "FEMALE")
    assert data["height_cm"] > 0 and data["baseline_weight_kg"] > 0


def assert_insurance_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_name"], str)
    assert isinstance(data["required_supervised_diet_months"], int)
    assert isinstance(data["qualifying_comorbidities"], list)


def assert_operating_room(data: dict):
    _assert_common(data)
    assert isinstance(data["room_code"], str)
    assert isinstance(data["turnover_buffer_minutes"], int)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_surgeon(data: dict):
    _assert_common(data)
    assert isinstance(data["credentialed_procedures"], list)


def assert_program(data: dict):
    _assert_common(data)
    assert data["payment_pathway"] in ("INSURANCE", "SELF_PAY")
    assert data["status"] in (
        "SCREENING", "CANDIDACY_REVIEW", "ELIGIBLE", "INELIGIBLE",
        "CLEARANCE_IN_PROGRESS", "CLEARED", "SURGERY_SCHEDULED",
        "POST_OP", "READMITTED", "COMPLETED",
    )
    assert data["candidacy_status"] in ("UNDETERMINED", "QUALIFIED", "NOT_QUALIFIED")
    assert isinstance(data["baseline_bmi"], (int, float))
    assert isinstance(data["readmission_count"], int)
    assert isinstance(data["active_complication_count"], int)


def assert_program_money_conserved(data: dict):
    """Money invariant (PRD §3.5): refunded + forfeited == collected."""
    assert data["amount_refunded_cents"] + data["amount_forfeited_cents"] == data["amount_collected_cents"], (
        f"refunded {data['amount_refunded_cents']} + forfeited {data['amount_forfeited_cents']} "
        f"!= collected {data['amount_collected_cents']}"
    )


def assert_surgery_case(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert data["procedure_type"] in ("SLEEVE_GASTRECTOMY", "GASTRIC_BYPASS", "ADJUSTABLE_BAND")


def assert_psych_evaluation(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "CLEARED", "DEFERRED")
    assert isinstance(data["reevaluation_count"], int)


def assert_nutrition_clearance(data: dict):
    _assert_common(data)
    assert data["decision"] in ("CLEARED", "NOT_CLEARED")


def assert_education_milestone(data: dict):
    _assert_common(data)
    assert data["milestone_code"] in (
        "NUTRITION_CLASS", "EXERCISE_ORIENTATION", "SURGERY_RISKS_CONSENT", "POST_OP_DIET_EDUCATION",
    )


def assert_complication(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "RESOLVED")


def assert_follow_up_visit(data: dict):
    _assert_common(data)
    assert data["interval_code"] in ("WEEK_2", "WEEK_6", "MONTH_3", "MONTH_6", "MONTH_12")
    assert data["status"] in ("SCHEDULED", "COMPLETED")


def assert_financing_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
