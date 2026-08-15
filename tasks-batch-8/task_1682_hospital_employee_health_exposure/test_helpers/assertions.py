"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def instant(value: str) -> str:
    """Normalize an ISO 8601 timestamp to its second-precision prefix
    (YYYY-MM-DDTHH:MM:SS) so tests compare the pinned instant regardless of
    fractional-second formatting."""
    assert isinstance(value, str), f"Expected timestamp string, got {value!r}"
    assert len(value) >= 19, f"Timestamp too short: {value!r}"
    return value[:19]


def assert_instant(actual: str, expected_prefix: str):
    """Assert the timestamp identifies the exact expected second."""
    assert instant(actual) == expected_prefix, (
        f"Expected instant {expected_prefix}, got {actual!r}"
    )


def assert_employee(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert isinstance(data.get("employee_ref"), str) and data["employee_ref"]
    assert data.get("job_category") in {"NURSE", "PHYSICIAN", "TECH", "HOUSEKEEPING", "OTHER"}
    assert isinstance(data.get("department"), str) and data["department"]
    assert isinstance(data.get("requires_respirator"), bool)
    assert data.get("status") in {"PREPLACEMENT", "ACTIVE", "SUSPENDED"}
    assert data.get("compliance_posture") in {
        "CLEAR", "ON_HOLD", "WORK_EXCLUDED", "RESTRICTED_DUTY",
    }
    assert isinstance(data.get("active_hold_count"), int)
    assert isinstance(data.get("open_restriction_count"), int)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_screening(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert data.get("status") in {"IN_PROGRESS", "CLEARED", "FAILED", "VOID"}
    for field in ("physical_completed_at", "tb_baseline_completed_at", "med_eval_completed_at"):
        assert field in data, f"{field} must be present (null until completed)"
    for field in ("decided_by_user_id", "decided_at"):
        assert field in data, f"{field} must be present (null until decided)"
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_titer_result(data: dict):
    """Append-only record: id + created_at only; no updated_at / version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert data.get("disease") in {"HEP_B", "MEASLES", "MUMPS", "RUBELLA", "VARICELLA"}
    assert data.get("assay_type") in {"QUANTITATIVE", "QUALITATIVE"}
    assert data.get("immunity_status") in {"IMMUNE", "NON_IMMUNE", "EQUIVOCAL"}
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_cycle(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert isinstance(data.get("cycle_year"), int)
    assert data.get("cycle_mode") in {"CALENDAR_YEAR", "ROLLING_ANNIVERSARY"}
    assert data.get("status") in {"OPEN", "OVERDUE", "SATISFIED"}
    assert "tb_due_date" in data and data["tb_due_date"]
    assert "fit_test_due_date" in data, "fit_test_due_date present (null when not required)"
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_hold(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert data.get("reason") in {"TB_OVERDUE", "FIT_TEST_OVERDUE", "CAMPAIGN_DELINQUENT"}
    assert data.get("status") in {"ACTIVE", "RELEASED"}
    assert "cycle_id" in data and "participation_id" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_exposure_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert data.get("exposure_type") in {"PERCUTANEOUS", "MUCOUS_MEMBRANE", "SKIN_CONTACT", "BITE"}
    assert data.get("body_fluid") in {"BLOOD", "OTHER_POTENTIALLY_INFECTIOUS", "NON_INFECTIOUS"}
    assert isinstance(data.get("source_known"), bool)
    assert data.get("risk_classification") in {"HIGH", "MEDIUM", "LOW"}
    assert data.get("case_status") in {
        "REPORTED", "EVALUATION", "MANAGEMENT", "CLOSED", "SEROCONVERTED",
    }
    assert data.get("source_test_status") in {
        "NOT_REQUIRED", "CONSENT_PENDING", "CONSENT_GRANTED",
        "RESULTED", "CONSENT_DECLINED", "WAIVED_UNABLE",
    }
    assert isinstance(data.get("pep_required"), bool)
    assert isinstance(data.get("recorded_by_user_id"), str)
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_pep_regimen(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert data.get("medication") in {"HIV_3DRUG", "HBV_HBIG", "HBV_VACCINE_SERIES"}
    assert data.get("status") in {
        "RECOMMENDED", "STARTED", "COMPLETED", "DECLINED", "WINDOW_EXPIRED",
    }
    assert "window_deadline" in data and data["window_deadline"]
    assert "started_at" in data, "started_at present (null until started)"
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_serology_followup(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert data.get("milestone") in {"BASELINE", "WEEK_6", "WEEK_12", "MONTH_6"}
    assert data.get("status") in {"SCHEDULED", "DUE", "OVERDUE", "RESULTED", "WAIVED"}
    for field in ("scheduled_date", "window_open", "window_close"):
        assert field in data and data[field], f"{field} must be present"
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_work_restriction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert data.get("restriction_type") in {
        "NO_PATIENT_CONTACT", "NO_PROCEDURES", "MODIFIED_DUTY", "FULL_EXCLUSION",
    }
    assert data.get("status") in {"ACTIVE", "LIFTED", "EXPIRED"}
    assert data.get("origin") in {"MANUAL", "SEROCONVERSION", "CONTACT_CONVERSION"}
    assert "start_date" in data and "end_date" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_clearance(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert data.get("status") in {"PENDING", "CLEARED", "DENIED"}
    assert isinstance(data.get("requested_by_user_id"), str)
    assert "decided_by_user_id" in data and "decided_at" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_communicable_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert data.get("disease") in {"COVID", "INFLUENZA", "PERTUSSIS", "NOROVIRUS", "MEASLES"}
    assert data.get("status") in {"OPEN", "TRACING", "MONITORING", "ESCALATED", "CLOSED"}
    assert "infectious_start" in data and "monitoring_window_days" in data
    assert isinstance(data.get("monitoring_window_days"), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_exposure_contact(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert data.get("status") in {
        "MONITORING", "CLEARED", "CONVERTED_TO_CASE", "LOST_TO_FOLLOWUP",
    }
    assert isinstance(data.get("symptom_onset_reported"), bool)
    assert "monitoring_start" in data and "monitoring_end" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_injury_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert data.get("injury_type") in {"NEEDLESTICK", "SPLASH", "FALL", "LIFT", "OTHER"}
    assert data.get("origin") in {"MANUAL", "PEP_LINKAGE"}
    assert data.get("status") in {
        "FILED", "WC_SUBMITTED", "WC_ACCEPTED", "WC_DENIED", "APPEALED",
    }
    assert isinstance(data.get("osha_recordable"), bool)
    assert "wc_claim_number" in data, "wc_claim_number present (null until submitted)"
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_campaign(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert data.get("vaccine_type") in {"INFLUENZA", "COVID", "HEP_B", "TDAP"}
    assert data.get("status") in {"PLANNED", "OPEN", "CLOSED"}
    assert isinstance(data.get("department_scope"), list)
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_participation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert data.get("status") in {
        "PENDING", "ADMINISTERED", "DECLINED", "EXEMPTED", "DELINQUENT",
    }
    for field in ("administered_at", "declined_at", "declination_reason", "exemption_type"):
        assert field in data, f"{field} must be present (null until its outcome)"
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_employee_hold_invariants(employee: dict, active_holds: list):
    """PRD §3.1: active_hold_count counts the employee's ACTIVE holds and the
    status axis derives from it (SUSPENDED exactly while the count > 0)."""
    assert employee["active_hold_count"] == len(active_holds), (
        f"active_hold_count {employee['active_hold_count']} != "
        f"actual ACTIVE holds {len(active_holds)}"
    )
    if employee["status"] in {"ACTIVE", "SUSPENDED"}:
        expected = "SUSPENDED" if active_holds else "ACTIVE"
        assert employee["status"] == expected, (
            f"status {employee['status']} inconsistent with {len(active_holds)} active holds"
        )
