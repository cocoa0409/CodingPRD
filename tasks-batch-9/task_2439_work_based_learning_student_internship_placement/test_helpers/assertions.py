"""Entity assertions and domain invariant checkers for the Work-Based Learning API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import SAFETY_SCORE_MAX, SAFETY_SCORE_MIN


def assert_system_fields(data: dict, expected_version: int = None):
    """Every resource carries a server-minted UUID `id` and an ISO 8601 `created_at`,
    plus `updated_at` and a `version` that starts at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected version {expected_version}, got {data['version']}"
        )


def assert_employer_partner(data: dict):
    assert_system_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["naics_code"], str) and len(data["naics_code"]) == 6
    assert data["industry_sector"] in [
        "MANUFACTURING",
        "HEALTHCARE",
        "CONSTRUCTION",
        "INFORMATION_TECHNOLOGY",
        "HOSPITALITY",
        "PUBLIC_ADMINISTRATION",
    ]
    assert isinstance(data["workers_comp_carrier"], str)
    assert isinstance(data["workers_comp_policy_no"], str)
    assert_date_format(data["workers_comp_expires_on"])
    assert_safety_score_clamped(data["safety_score"])
    assert data["posture"] in ["PROSPECT", "ELIGIBLE", "PROBATION", "SUSPENDED"]
    for counter in (
        "substantiated_minor_count",
        "substantiated_moderate_count",
        "substantiated_critical_count",
        "wage_liability_cents",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
        assert data[counter] >= 0, f"{counter} must never go negative"


def assert_worksite(data: dict):
    assert_system_fields(data)
    assert is_valid_uuid(data["employer_partner_id"])
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert isinstance(data["address_line"], str) and data["address_line"]
    assert data["hazard_class"] in ["NON_HAZARDOUS", "LIMITED_HAZARD", "PROHIBITED_HAZARD"]
    assert isinstance(data["has_power_machinery"], bool)
    assert isinstance(data["displaces_paid_employee"], bool)
    assert isinstance(data["max_concurrent_students"], int)
    assert data["max_concurrent_students"] >= 1
    assert data["safety_status"] in ["UNREVIEWED", "APPROVED", "CONDITIONAL", "FAILED"]
    assert isinstance(data["slots_committed"], int) and data["slots_committed"] >= 0


def assert_safety_review(data: dict):
    assert_system_fields(data)
    assert is_valid_uuid(data["worksite_id"])
    assert isinstance(data["reviewer_user_id"], str) and data["reviewer_user_id"]
    assert isinstance(data["machinery_guarding_ok"], bool)
    assert isinstance(data["hazard_findings_count"], int) and data["hazard_findings_count"] >= 0
    assert isinstance(data["orientation_documented"], bool)
    assert isinstance(data["emergency_plan_on_file"], bool)
    assert data["status"] in ["SUBMITTED", "APPROVED", "CONDITIONAL", "FAILED", "SUPERSEDED"]


def assert_supervisor(data: dict):
    assert_system_fields(data)
    assert is_valid_uuid(data["worksite_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert_date_format(data["training_completed_on"])
    assert isinstance(data["max_student_load"], int) and data["max_student_load"] >= 1
    assert isinstance(data["active_student_load"], int) and data["active_student_load"] >= 0


def assert_agreement(data: dict):
    assert_system_fields(data)
    assert is_valid_uuid(data["employer_partner_id"])
    assert is_valid_uuid(data["worksite_id"])
    assert is_valid_uuid(data["employer_signer_supervisor_id"])
    assert_date_format(data["effective_on"])
    assert_date_format(data["expires_on"])
    assert data["expires_on"] > data["effective_on"], "expires_on must be strictly after effective_on"
    assert isinstance(data["insurance_rider"], bool)
    assert data["status"] in [
        "PENDING_EMPLOYER",
        "PENDING_DISTRICT",
        "EXECUTED",
        "TERMINATED",
        "EXPIRED",
    ]
    assert isinstance(data["revision_round"], int) and 0 <= data["revision_round"] <= 3
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_student(data: dict):
    assert_system_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert_date_format(data["birth_date"])
    assert isinstance(data["grade_level"], int) and 9 <= data["grade_level"] <= 12
    assert 0.00 <= float(data["gpa"]) <= 4.00
    assert 0.00 <= float(data["attendance_rate"]) <= 1.00
    assert isinstance(data["student_learner_certificate"], bool)
    assert isinstance(data["guardian_consent_on_file"], bool)
    assert data["eligibility_status"] in [
        "ELIGIBLE",
        "INELIGIBLE_GRADE",
        "INELIGIBLE_ACADEMIC",
        "INELIGIBLE_ATTENDANCE",
    ]
    assert float(data["ytd_wbl_hours"]) >= 0.0
    assert float(data["credits_earned_wbl"]) >= 0.0
    assert isinstance(data["active_placement_count"], int) and data["active_placement_count"] >= 0


def assert_work_permit(data: dict):
    assert_system_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["permit_class"] in ["MINOR_14_15", "MINOR_16_17", "ADULT_18_PLUS"]
    assert isinstance(data["hazardous_endorsement"], bool)
    assert data["status"] in ["REQUESTED", "ISSUED", "REVOKED", "EXPIRED"]


def assert_placement(data: dict):
    assert_system_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["worksite_id"])
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["supervisor_id"])
    assert float(data["scheduled_weekly_hours"]) > 0.00
    assert_date_format(data["start_on"])
    assert_date_format(data["end_on"])
    assert data["end_on"] > data["start_on"], "end_on must be strictly after start_on"
    assert data["pay_classification"] in ["PAID", "UNPAID", "STIPEND"]
    assert isinstance(data["hourly_wage_cents"], int) and data["hourly_wage_cents"] >= 0
    assert isinstance(data["stipend_total_cents"], int) and data["stipend_total_cents"] >= 0
    assert 0.50 <= float(data["credit_target_credits"]) <= 2.00
    assert data["credit_award_mode"] in ["HOURS_BASED", "COMPETENCY_BASED"]
    assert 1 <= int(data["required_evaluation_cycles"]) <= 4
    assert data["transportation_mode"] in ["DISTRICT_BUS", "PUBLIC_TRANSIT", "SELF", "GUARDIAN"]
    assert float(data["commute_round_trip_miles"]) >= 0.00
    assert isinstance(data["student_age_at_start"], int)
    assert data["permit_class_at_start"] in ["MINOR_14_15", "MINOR_16_17", "ADULT_18_PLUS"]
    assert data["lifecycle_status"] in ["PROPOSED", "ACTIVE", "COMPLETED", "TERMINATED"]
    assert data["compliance_status"] in ["PENDING_REVIEW", "CLEARED", "FLAGGED", "BLOCKED"]
    assert float(data["total_verified_hours"]) >= 0.00
    assert isinstance(data["closed_cycle_count"], int) and data["closed_cycle_count"] >= 0
    assert isinstance(data["credit_eligible"], bool)
    assert data["wage_settlement_mode"] in ["NONE", "PROVISIONAL", "FINAL"]


def assert_training_plan(data: dict):
    assert_system_fields(data)
    assert is_valid_uuid(data["placement_id"])
    assert isinstance(data["course_code"], str) and data["course_code"]
    assert float(data["credit_hours_target"]) > 0.00
    assert data["status"] in ["DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "SUPERSEDED"]
    assert isinstance(data["revision_round"], int) and 0 <= data["revision_round"] <= 3
    assert isinstance(data["objective_count"], int) and data["objective_count"] >= 0
    assert isinstance(data["aligned_objective_count"], int)
    assert data["aligned_objective_count"] <= data["objective_count"], (
        "aligned_objective_count can never exceed objective_count"
    )


def assert_learning_objective(data: dict):
    """A learning objective is an append-only record: the PRD gives it only
    `id` and `created_at`, with no `updated_at` and no `version`."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "a learning objective has no updated_at"
    assert "version" not in data, "a learning objective has no version"
    assert is_valid_uuid(data["training_plan_id"])
    assert isinstance(data["competency_code"], str) and data["competency_code"]
    assert isinstance(data["description"], str) and data["description"]
    assert isinstance(data["aligned_course_code"], str) and data["aligned_course_code"]
    assert data["assessment_method"] in ["SUPERVISOR_RATING", "PORTFOLIO", "EXAM", "REFLECTION"]


def assert_timesheet_entry(data: dict):
    assert_system_fields(data)
    assert is_valid_uuid(data["placement_id"])
    assert_date_format(data["work_date"])
    assert_clock_time_format(data["start_time"])
    assert_clock_time_format(data["end_time"])
    assert data["end_time"] > data["start_time"], "end_time must be strictly after start_time"
    assert isinstance(data["break_minutes"], int) and data["break_minutes"] >= 0
    assert isinstance(data["is_school_day"], bool)
    assert float(data["hours_worked"]) > 0.00
    assert data["status"] in ["LOGGED", "VOIDED"]


def assert_evaluation_cycle(data: dict):
    assert_system_fields(data)
    assert is_valid_uuid(data["placement_id"])
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert_date_format(data["window_start"])
    assert_date_format(data["window_end"])
    assert data["supervisor_eval_status"] in ["PENDING", "SUBMITTED"]
    assert data["reflection_status"] in ["PENDING", "SUBMITTED", "ACCEPTED", "RETURNED"]
    assert data["cycle_status"] in ["OPEN", "PARTIAL", "CLOSED", "SUSPENDED", "CANCELLED"]


def assert_incident_report(data: dict):
    assert_system_fields(data)
    assert is_valid_uuid(data["placement_id"])
    assert is_valid_uuid(data["worksite_id"])
    assert isinstance(data["reported_by_user_id"], str) and data["reported_by_user_id"]
    assert is_iso8601_timestamp(data["occurred_at"])
    assert data["severity"] in ["MINOR", "MODERATE", "CRITICAL"]
    assert isinstance(data["description"], str) and data["description"]
    assert data["injury_type"] in [
        "NONE",
        "LACERATION",
        "FRACTURE",
        "BURN",
        "STRAIN",
        "EXPOSURE",
    ]
    assert data["status"] in ["REPORTED", "SUBSTANTIATED", "UNSUBSTANTIATED", "CLOSED"]
    assert data["coverage_determination"] in [
        "PENDING",
        "WORKERS_COMP",
        "DISTRICT_LIABILITY",
        "EMPLOYER_LIABILITY_UNINSURED",
        "NOT_COVERED",
    ]
    assert isinstance(data["osha_recordable"], bool)


def assert_placement_outcome(data: dict):
    assert_system_fields(data)
    assert is_valid_uuid(data["placement_id"])
    assert data["outcome_type"] in [
        "EMPLOYED_FULL_TIME",
        "EMPLOYED_PART_TIME",
        "POSTSECONDARY_ENROLLED",
        "APPRENTICESHIP",
        "MILITARY",
        "NOT_ENGAGED",
        "UNKNOWN",
    ]
    assert data["verification_source"] in [
        "EMPLOYER_LETTER",
        "ENROLLMENT_RECORD",
        "STUDENT_ATTESTATION",
    ]
    assert data["status"] in ["RECORDED", "VERIFIED", "LATE_UNVERIFIABLE"]
    assert_date_format(data["recorded_on"])
    assert isinstance(data["counts_positive"], bool)


# --------------------------------------------------------------------------
# Format and invariant helpers
# --------------------------------------------------------------------------


def assert_date_format(value: str):
    """`YYYY-MM-DD` dates."""
    assert isinstance(value, str), f"expected a YYYY-MM-DD string, got {value!r}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"expected YYYY-MM-DD, got {value!r}"
    )
    year, month, day = value.split("-")
    assert year.isdigit() and month.isdigit() and day.isdigit(), f"expected YYYY-MM-DD, got {value!r}"


def assert_clock_time_format(value: str):
    """`HH:MM` on a 24-hour dial."""
    assert isinstance(value, str), f"expected an HH:MM string, got {value!r}"
    assert len(value) == 5 and value[2] == ":", f"expected HH:MM, got {value!r}"
    hh, mm = value.split(":")
    assert hh.isdigit() and mm.isdigit(), f"expected HH:MM, got {value!r}"
    assert 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59, f"expected a 24-hour dial time, got {value!r}"


def assert_cents(value, label="amount"):
    """Money is carried as an integer number of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_two_decimal_places(value, label="value"):
    """Hours, credits and competency scores are two-decimal figures."""
    scaled = round(float(value) * 100)
    assert abs(float(value) * 100 - scaled) < 1e-6, (
        f"{label} must carry at most two decimal places, got {value!r}"
    )


def assert_safety_score_clamped(score):
    assert isinstance(score, int), f"safety_score must be an integer, got {score!r}"
    assert SAFETY_SCORE_MIN <= score <= SAFETY_SCORE_MAX, (
        f"safety_score must be clamped into 0 through 100, got {score}"
    )


def assert_placement_counters(placement: dict):
    """Counters the PRD keeps non-negative on a placement."""
    assert float(placement["total_verified_hours"]) >= 0.00
    assert placement["closed_cycle_count"] >= 0
    assert_cents(placement["provisional_wage_cents"], "provisional_wage_cents")
    assert_cents(placement["final_wage_cents"], "final_wage_cents")
    assert_cents(placement["settled_wage_cents"], "settled_wage_cents")


def assert_no_learning_objective_version(objective: dict):
    assert "version" not in objective, "a learning objective has no version field"
    assert "updated_at" not in objective, "a learning objective has no updated_at field"
