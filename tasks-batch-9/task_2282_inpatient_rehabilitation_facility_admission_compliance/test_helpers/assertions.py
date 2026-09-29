"""Entity assertions and domain invariant checkers for the IRF API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

FACILITY_POSTURES = ["OPEN", "THRESHOLD_WATCH", "ADMISSION_FREEZE"]
CLINICIAN_CREDENTIALS = [
    "REHAB_PHYSICIAN", "NURSE", "THERAPIST_PT", "THERAPIST_OT",
    "THERAPIST_SLP", "CODER",
]
SCREENING_STATUSES = [
    "DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "PHYSICIAN_CONCURRED",
    "ON_HOLD", "EXPIRED",
]
STAY_STATUSES = ["PENDING", "ADMITTED", "DISCHARGED", "ADMISSION_DENIED"]
PAYMENT_STATUSES = ["NOT_PRICED", "PRICED", "CONSOLIDATED", "REOPENED"]
DOCUMENTATION_STATUSES = ["INCOMPLETE", "POC_SIGNED", "PAI_TRANSMITTED"]
COMPLIANCE_CLASSES = [
    "PENDING_EVALUATION", "QUALIFYING", "NON_QUALIFYING", "EXCLUDED",
]
CMG_TIERS = ["TIER_A", "TIER_B", "TIER_C"]
DISCHARGE_DESTINATIONS = [
    "COMMUNITY", "SNF", "ACUTE_CARE", "LTCH", "ANOTHER_IRF", "EXPIRED",
    "AGAINST_MEDICAL_ADVICE",
]
THERAPY_WEEK_STATUSES = ["OPEN", "MET", "NOT_MET", "EXCEPTION_GRANTED"]
THERAPY_SESSION_STATUSES = ["SCHEDULED", "DELIVERED", "VOIDED"]
ASSESSMENT_STATUSES = [
    "DRAFT", "COMPLETED", "TRANSMITTED", "LATE_TRANSMITTED", "MISSED",
]
REVIEW_STATUSES = ["DRAFT", "COMPUTED", "STALE", "CERTIFIED"]


# --------------------------------------------------------------------------- #
# Shared system-managed properties (PRD §2.4)
# --------------------------------------------------------------------------- #
def assert_common_fields(data: dict, entity_name: str = "resource"):
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1, "
        f"got {data.get('version')!r}"
    )


def assert_two_decimals(value, field_name: str = "percentage"):
    """Percentages carry exactly two decimal places (PRD §2.6)."""
    assert value is not None, f"{field_name} must not be null"
    assert round(float(value), 2) == float(value), (
        f"{field_name} must carry at most two decimal places, got {value!r}"
    )


def assert_whole_cents(value, field_name: str = "amount_cents"):
    """Money is integer cents (PRD §2.6)."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field_name} must be an integer number of cents, got {value!r}"
    )


# --------------------------------------------------------------------------- #
# Per-entity assertions
# --------------------------------------------------------------------------- #
def assert_facility(data: dict):
    assert_common_fields(data, "facility")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["cms_ccn"], str) and data["cms_ccn"].isdigit()
    assert len(data["cms_ccn"]) == 6, "cms_ccn must be exactly six digits"
    assert isinstance(data["review_period_start"], str)
    assert isinstance(data["review_period_end"], str)
    assert data["review_period_end"] >= data["review_period_start"]
    assert_two_decimals(data["compliance_threshold_pct"], "compliance_threshold_pct")
    assert isinstance(data["daily_therapy_cap_minutes"], int)
    assert isinstance(data["cohort_total_count"], int)
    assert isinstance(data["cohort_qualifying_count"], int)
    assert data["cohort_qualifying_count"] <= data["cohort_total_count"]
    assert_two_decimals(data["provisional_compliance_pct"],
                        "provisional_compliance_pct")
    if data.get("certified_compliance_pct") is not None:
        assert_two_decimals(data["certified_compliance_pct"],
                            "certified_compliance_pct")
    assert_whole_cents(data["settled_payment_cents"], "settled_payment_cents")
    assert data["posture"] in FACILITY_POSTURES
    assert_two_decimals(data["active_qrp_penalty_pct"], "active_qrp_penalty_pct")


def assert_clinician(data: dict):
    assert_common_fields(data, "clinician")
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["credential"] in CLINICIAN_CREDENTIALS
    assert isinstance(data["npi"], str) and data["npi"].isdigit()
    assert len(data["npi"]) == 10, "npi must be exactly ten digits"
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_patient(data: dict):
    assert_common_fields(data, "patient")
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["mrn"], str) and len(data["mrn"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["birth_date"], str)
    assert isinstance(data["impairment_group_code"], str)
    assert isinstance(data["etiologic_diagnosis_code"], str)
    assert data["comorbidity_tier"] in ["NONE", "TIER_3", "TIER_2", "TIER_1"]


def assert_screening(data: dict):
    assert_common_fields(data, "screening")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["conducted_by_clinician_id"])
    assert is_iso8601_timestamp(data["conducted_at"])
    assert isinstance(data["expected_admission_at"], str)
    for flag in (
        "intensive_therapy_documented",
        "expected_functional_improvement_documented",
        "prior_functional_level_documented",
        "medical_supervision_documented",
    ):
        assert isinstance(data[flag], bool), f"{flag} must be a boolean"
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["status"] in SCREENING_STATUSES


def assert_admission(data: dict):
    assert_common_fields(data, "admission")
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["screening_id"])
    assert data["stay_status"] in STAY_STATUSES
    assert data["payment_status"] in PAYMENT_STATUSES
    assert data["documentation_status"] in DOCUMENTATION_STATUSES
    assert data["compliance_class"] in COMPLIANCE_CLASSES
    assert isinstance(data["interrupted_stay_flag"], bool)
    assert_whole_cents(data["total_payment_cents"], "total_payment_cents")
    assert_two_decimals(data["qrp_penalty_pct_snapshot"], "qrp_penalty_pct_snapshot")
    assert isinstance(data["screening_compliant"], bool)
    assert isinstance(data["poc_signed_within_deadline"], bool)
    assert isinstance(data["therapy_weeks_satisfied"], bool)
    assert isinstance(data["conference_compliant"], bool)
    assert isinstance(data["total_credited_minutes"], int)
    if data.get("cmg_tier") is not None:
        assert data["cmg_tier"] in CMG_TIERS
    if data.get("discharge_destination") is not None:
        assert data["discharge_destination"] in DISCHARGE_DESTINATIONS
    if data.get("screening_window_hours") is not None:
        assert_two_decimals(data["screening_window_hours"], "screening_window_hours")


def assert_plan_of_care(data: dict):
    assert_common_fields(data, "plan_of_care")
    assert is_valid_uuid(data["admission_id"])
    assert is_valid_uuid(data["authored_by_clinician_id"])
    assert isinstance(data["target_los_days"], int)
    assert 1 <= data["target_los_days"] <= 120
    assert isinstance(data["weekly_minutes_target"], int)
    assert 60 <= data["weekly_minutes_target"] <= 2400
    assert isinstance(data["disciplines"], list) and len(data["disciplines"]) >= 1
    assert len(set(data["disciplines"])) == len(data["disciplines"])
    assert set(data["disciplines"]).issubset({"PT", "OT", "SLP"})
    assert data["three_hour_rule_mode"] in ["DAILY_3HR", "WEEKLY_15HR"]
    assert is_iso8601_timestamp(data["signed_at"])
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]


def assert_therapy_week(data: dict):
    assert_common_fields(data, "therapy_week")
    assert is_valid_uuid(data["admission_id"])
    assert isinstance(data["week_index"], int) and 1 <= data["week_index"] <= 26
    assert isinstance(data["week_start_date"], str)
    assert isinstance(data["week_end_date"], str)
    assert data["week_end_date"] > data["week_start_date"]
    assert data["evaluation_mode"] in ["DAILY_3HR", "WEEKLY_15HR"]
    assert isinstance(data["delivered_credited_minutes"], int)
    assert data["delivered_credited_minutes"] >= 0
    assert isinstance(data["qualifying_days_count"], int)
    assert 0 <= data["qualifying_days_count"] <= 7
    assert data["status"] in THERAPY_WEEK_STATUSES


def assert_therapy_session(data: dict):
    assert_common_fields(data, "therapy_session")
    assert is_valid_uuid(data["admission_id"])
    assert is_valid_uuid(data["clinician_id"])
    assert data["discipline"] in ["PT", "OT", "SLP"]
    assert data["modality"] in ["INDIVIDUAL", "CONCURRENT", "GROUP"]
    assert isinstance(data["group_size"], int) and data["group_size"] >= 1
    assert isinstance(data["start_at"], str)
    assert isinstance(data["end_at"], str)
    assert isinstance(data["session_date"], str)
    assert isinstance(data["raw_minutes"], int) and data["raw_minutes"] >= 1
    assert isinstance(data["credited_minutes"], int)
    assert data["credited_minutes"] >= 0
    assert data["credited_minutes"] <= data["raw_minutes"]
    assert data["status"] in THERAPY_SESSION_STATUSES


def assert_team_conference(data: dict):
    assert_common_fields(data, "team_conference")
    assert is_valid_uuid(data["admission_id"])
    assert is_valid_uuid(data["therapy_week_id"])
    assert is_valid_uuid(data["led_by_clinician_id"])
    assert isinstance(data["participant_clinician_ids"], list)
    assert 1 <= len(data["participant_clinician_ids"]) <= 12
    assert len(set(data["participant_clinician_ids"])) == len(
        data["participant_clinician_ids"]
    )
    assert isinstance(data["held_at"], str)
    assert data["status"] in ["RECORDED", "LATE_RECORDED"]


def assert_assessment(data: dict):
    assert_common_fields(data, "assessment")
    assert is_valid_uuid(data["admission_id"])
    assert is_valid_uuid(data["coder_clinician_id"])
    assert data["assessment_type"] in ["ADMISSION", "DISCHARGE"]
    assert isinstance(data["assessment_reference_date"], str)
    assert is_iso8601_timestamp(data["completion_deadline_at"])
    assert is_iso8601_timestamp(data["transmission_deadline_at"])
    assert data["transmission_deadline_at"] > data["completion_deadline_at"]
    assert isinstance(data["completion_late"], bool)
    assert isinstance(data["late_days"], int) and data["late_days"] >= 0
    assert data["status"] in ASSESSMENT_STATUSES


def assert_compliance_review(data: dict):
    assert_common_fields(data, "compliance_review")
    assert is_valid_uuid(data["facility_id"])
    assert data["method"] in ["PRESUMPTIVE", "MEDICAL_REVIEW"]
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["period_end"] >= data["period_start"]
    assert isinstance(data["created_by_user_id"], str)
    assert isinstance(data["total_cases"], int) and data["total_cases"] >= 0
    assert isinstance(data["qualifying_cases"], int)
    assert data["qualifying_cases"] <= data["total_cases"]
    if data.get("compliance_pct") is not None:
        assert_two_decimals(data["compliance_pct"], "compliance_pct")
    if data.get("outcome") is not None:
        assert data["outcome"] in ["PASS", "FAIL"]
    assert data["status"] in REVIEW_STATUSES


def assert_qrp_assessment(data: dict):
    assert_common_fields(data, "qrp_assessment")
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["fiscal_year"], int)
    assert 2020 <= data["fiscal_year"] <= 2100
    assert isinstance(data["reporting_period_start"], str)
    assert isinstance(data["reporting_period_end"], str)
    assert isinstance(data["cohort_count"], int) and data["cohort_count"] >= 0
    assert isinstance(data["timely_count"], int)
    assert data["timely_count"] <= data["cohort_count"]
    assert_two_decimals(data["data_completeness_pct"], "data_completeness_pct")
    assert_two_decimals(data["penalty_pct"], "penalty_pct")
    assert data["status"] in ["DRAFT", "FINALIZED"]


# --------------------------------------------------------------------------- #
# Domain invariant checkers
# --------------------------------------------------------------------------- #
def assert_clock_state(data: dict):
    assert isinstance(data["current_utc"], str)
    assert isinstance(data["expired_screening_count"], int)
    assert data["expired_screening_count"] >= 0
    assert isinstance(data["missed_assessment_count"], int)
    assert data["missed_assessment_count"] >= 0


def assert_admission_dimensions(data: dict, stay_status: str = None,
                                payment_status: str = None,
                                documentation_status: str = None,
                                compliance_class: str = None):
    """The admission's independent status dimensions (PRD §3.3)."""
    if stay_status is not None:
        assert data["stay_status"] == stay_status, (
            f"Expected stay_status {stay_status}, got {data['stay_status']}"
        )
    if payment_status is not None:
        assert data["payment_status"] == payment_status, (
            f"Expected payment_status {payment_status}, got {data['payment_status']}"
        )
    if documentation_status is not None:
        assert data["documentation_status"] == documentation_status, (
            f"Expected documentation_status {documentation_status}, "
            f"got {data['documentation_status']}"
        )
    if compliance_class is not None:
        assert data["compliance_class"] == compliance_class, (
            f"Expected compliance_class {compliance_class}, "
            f"got {data['compliance_class']}"
        )


def assert_facility_cohort(data: dict, cohort_total_count: int,
                           cohort_qualifying_count: int,
                           provisional_compliance_pct: float,
                           posture: str = None):
    """The facility's provisional cohort figures and posture (PRD §3.8, §2.8)."""
    assert data["cohort_total_count"] == cohort_total_count, (
        f"Expected cohort_total_count {cohort_total_count}, "
        f"got {data['cohort_total_count']}"
    )
    assert data["cohort_qualifying_count"] == cohort_qualifying_count, (
        f"Expected cohort_qualifying_count {cohort_qualifying_count}, "
        f"got {data['cohort_qualifying_count']}"
    )
    assert float(data["provisional_compliance_pct"]) == float(
        provisional_compliance_pct
    ), (
        f"Expected provisional_compliance_pct {provisional_compliance_pct}, "
        f"got {data['provisional_compliance_pct']}"
    )
    if posture is not None:
        assert data["posture"] == posture, (
            f"Expected posture {posture}, got {data['posture']}"
        )


def assert_week_counters(data: dict, delivered_credited_minutes: int,
                         qualifying_days_count: int, status: str = None):
    """A therapy week's refreshed counters (PRD §3.6)."""
    assert data["delivered_credited_minutes"] == delivered_credited_minutes, (
        f"Expected delivered_credited_minutes {delivered_credited_minutes}, "
        f"got {data['delivered_credited_minutes']}"
    )
    assert data["qualifying_days_count"] == qualifying_days_count, (
        f"Expected qualifying_days_count {qualifying_days_count}, "
        f"got {data['qualifying_days_count']}"
    )
    if status is not None:
        assert data["status"] == status, (
            f"Expected therapy week status {status}, got {data['status']}"
        )


def assert_payment(data: dict, effective_los_days, total_payment_cents: int,
                   payment_status: str = None):
    """A priced stay's payment figures (PRD §3.8)."""
    assert data["effective_los_days"] == effective_los_days, (
        f"Expected effective_los_days {effective_los_days}, "
        f"got {data['effective_los_days']}"
    )
    assert_whole_cents(data["total_payment_cents"], "total_payment_cents")
    assert data["total_payment_cents"] == total_payment_cents, (
        f"Expected total_payment_cents {total_payment_cents}, "
        f"got {data['total_payment_cents']}"
    )
    if payment_status is not None:
        assert data["payment_status"] == payment_status, (
            f"Expected payment_status {payment_status}, got {data['payment_status']}"
        )
