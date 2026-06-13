"""Payload factories — one per write entity, input fields only.

Each factory supplies sensible defaults for required input fields and merges
**overrides so a test can control exactly the field under assertion.
"""

DEFAULTS = {
    "TRACK": "FULLSTACK",
    "CAPACITY": 5,
    "TUITION_STICKER_CENTS": 1_500_000,
    "DEPOSIT_CENTS": 200_000,
    "INCOME_SHARE_PCT": 0.17,
    "CAP_CENTS": 3_000_000,
    "TERM_MONTHS": 24,
    "INCOME_THRESHOLD_CENTS": 400_000,
}


def create_cohort_payload(**overrides) -> dict:
    """POST /cohorts body (PRD §3.1)."""
    payload = {
        "name": "Test Cohort",
        "track": DEFAULTS["TRACK"],
        "capacity": DEFAULTS["CAPACITY"],
        "tuition_sticker_cents": DEFAULTS["TUITION_STICKER_CENTS"],
        "start_date": "2026-02-01T00:00:00Z",
        "end_date": "2026-05-01T00:00:00Z",
        "cirr_period_label": "H1-2026",
    }
    payload.update(overrides)
    return payload


def create_applicant_payload(cohort_id, **overrides) -> dict:
    """POST /applicants body (PRD §3.2)."""
    payload = {
        "cohort_id": cohort_id,
        "full_name": "Test Applicant",
        "email": "applicant@example.com",
        "reported_prior_income_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(applicant_id, financing_choice="ISA", **overrides) -> dict:
    """POST /enrollments body (PRD §3.3). ISA terms included only for ISA choice."""
    payload = {
        "applicant_id": applicant_id,
        "financing_choice": financing_choice,
        "deposit_amount_cents": DEFAULTS["DEPOSIT_CENTS"],
    }
    if financing_choice == "ISA":
        payload.update(
            {
                "isa_income_share_pct": DEFAULTS["INCOME_SHARE_PCT"],
                "isa_cap_cents": DEFAULTS["CAP_CENTS"],
                "isa_term_months": DEFAULTS["TERM_MONTHS"],
                "isa_income_threshold_cents": DEFAULTS["INCOME_THRESHOLD_CENTS"],
            }
        )
    payload.update(overrides)
    return payload


def create_attendance_record_payload(enrollment_id, present=True, cumulative_progress_pct=100, **overrides) -> dict:
    """POST /attendance-records body (PRD §3.4)."""
    payload = {
        "enrollment_id": enrollment_id,
        "session_date": "2026-02-02T00:00:00Z",
        "present": present,
        "cumulative_progress_pct": cumulative_progress_pct,
    }
    payload.update(overrides)
    return payload


def create_scholarship_payload(enrollment_id, expected_enrollment_version, kind="MERIT", cap_reduction_pct=0.20, **overrides) -> dict:
    """POST /scholarships body (PRD §3.7 / §2.9). expected_enrollment_version mandatory."""
    payload = {
        "enrollment_id": enrollment_id,
        "kind": kind,
        "cap_reduction_pct": cap_reduction_pct,
        "expected_enrollment_version": expected_enrollment_version,
    }
    payload.update(overrides)
    return payload


def create_income_report_payload(isa_contract_id, period_start, period_end, gross_income_cents, employment_status="EMPLOYED", **overrides) -> dict:
    """POST /income-reports body (PRD §3.8)."""
    payload = {
        "isa_contract_id": isa_contract_id,
        "period_start": period_start,
        "period_end": period_end,
        "gross_income_cents": gross_income_cents,
        "employment_status": employment_status,
    }
    payload.update(overrides)
    return payload


def create_deferment_request_payload(isa_contract_id, reason, period_start, period_end, **overrides) -> dict:
    """POST /deferment-requests body (PRD §3.10)."""
    payload = {
        "isa_contract_id": isa_contract_id,
        "reason": reason,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def create_placement_outcome_payload(enrollment_id, category, reported_at, **overrides) -> dict:
    """POST /placement-outcomes body (PRD §3.12). salary/placement_days optional."""
    payload = {
        "enrollment_id": enrollment_id,
        "category": category,
        "reported_at": reported_at,
    }
    payload.update(overrides)
    return payload


def create_cirr_report_payload(cohort_id, denominator_basis="GRADUATES_ONLY", **overrides) -> dict:
    """POST /cirr-reports body (PRD §3.12)."""
    payload = {
        "cohort_id": cohort_id,
        "denominator_basis": denominator_basis,
    }
    payload.update(overrides)
    return payload
