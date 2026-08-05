"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_program_payload(**overrides) -> dict:
    """IncentiveProgram create body (§3.1). Defaults to a GRANT program.
    but_for_pass_threshold and disclosure_threshold_cents are omitted so the
    server defaults (60 and 0) apply unless a test overrides them."""
    defaults = {
        "program_name": "Test Program",
        "incentive_type": "GRANT",
        "total_budget_cents": TEST_DEFAULTS["PROGRAM_BUDGET_CENTS"],
        "min_jobs_required": TEST_DEFAULTS["MIN_JOBS_REQUIRED"],
        "min_investment_cents": TEST_DEFAULTS["MIN_INVESTMENT_CENTS"],
        "max_term_years": TEST_DEFAULTS["MAX_TERM_YEARS"],
        "abatement_rate_pct": 0,
        "grant_per_job_cents": TEST_DEFAULTS["GRANT_PER_JOB_CENTS"],
        "tif_capture_pct": 0,
    }
    defaults.update(overrides)
    return defaults


def create_parcel_payload(**overrides) -> dict:
    """Parcel create body (§3.1)."""
    defaults = {
        "parcel_identifier": "APN-1",
        "jurisdiction": "City",
        "base_assessed_value_cents": 0,
        "current_assessed_value_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(program_id, **overrides) -> dict:
    """Application create body (§3.2). Optional but_for_attested / distress_zone are
    omitted by default so the server defaults (false) apply unless overridden."""
    defaults = {
        "program_id": program_id,
        "applicant_user_id": "applicant-1",
        "applicant_name": "Acme",
        "proposed_jobs": 100,
        "proposed_investment_cents": 150_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(application_id, parcel_id, **overrides) -> dict:
    """Agreement execution body (§3.3)."""
    defaults = {
        "application_id": application_id,
        "parcel_id": parcel_id,
        "term_years": 5,
        "awarded_jobs": 100,
        "awarded_investment_cents": 150_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_covenant_payload(**overrides) -> dict:
    """Covenant create body (§3.4). cure_period_days omitted -> defaults to 0."""
    defaults = {
        "covenant_type": "JOBS",
        "target_value": 100,
        "measurement_start_date": "2027-01-01T00:00:00.000Z",
        "measurement_end_date": "2027-12-31T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_compliance_report_payload(**overrides) -> dict:
    """ComplianceReport submission body (§3.5). attestation omitted -> defaults to false."""
    defaults = {
        "reporting_year": 2027,
        "period_start_date": "2027-01-01T00:00:00.000Z",
        "period_end_date": "2028-01-01T00:00:00.000Z",
        "actual_jobs": 100,
        "actual_investment_cents": 150_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(agreement_id, compliance_report_id, expected_agreement_version, **overrides) -> dict:
    """Disbursement create body (§3.6). expected_agreement_version is required (OCC)."""
    defaults = {
        "agreement_id": agreement_id,
        "compliance_report_id": compliance_report_id,
        "expected_agreement_version": expected_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_payload(disclosure_year=2027, **overrides) -> dict:
    """TransparencyDisclosure create body (§3.8)."""
    defaults = {"disclosure_year": disclosure_year}
    defaults.update(overrides)
    return defaults
