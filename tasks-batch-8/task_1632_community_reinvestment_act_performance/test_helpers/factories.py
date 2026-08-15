"""Payload factories — one per creatable resource, input fields only (PRD §3, §4)."""
import itertools

_code_counter = itertools.count(1)


def _next(prefix: str) -> str:
    return f"{prefix}-{next(_code_counter):04d}"


def create_assessment_area_payload(**overrides) -> dict:
    """Required inputs per PRD §3.1."""
    defaults = {
        "area_code": _next("AA"),
        "name": "Test Assessment Area",
        "msa_code": "10180",
        "state_code": "CA",
        "census_tracts": ["T1"],
        "effective_start_date": "2023-01-01",
        "annual_cd_budget_cents": 10_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_demographic_profile_payload(expected_assessment_area_version: int,
                                       **overrides) -> dict:
    """Required inputs per PRD §3.2 plus the OCC field of PRD §2.7."""
    defaults = {
        "expected_assessment_area_version": expected_assessment_area_version,
        "data_year": 2020,
        "total_tracts": 10,
        "low_income_tracts": 2,
        "moderate_income_tracts": 2,
        "total_population": 10_000,
        "lmi_population": 4_500,
        "median_family_income": 60_000,
    }
    defaults.update(overrides)
    return defaults


def create_loan_record_payload(assessment_area_id: str, **overrides) -> dict:
    """Required inputs per PRD §3.3."""
    defaults = {
        "assessment_area_id": assessment_area_id,
        "loan_type": "SMALL_BUSINESS",
        "loan_amount_cents": 100_000,
        "borrower_gross_annual_revenue_cents": 1_000_000,
        "action_date": "2025-01-10",
        "census_tract": "T1",
        "tract_income_level": "LOW",
    }
    defaults.update(overrides)
    return defaults


def create_cd_activity_payload(assessment_area_id: str, **overrides) -> dict:
    """Required inputs per PRD §3.4."""
    defaults = {
        "assessment_area_id": assessment_area_id,
        "activity_type": "CD_LOAN",
        "amount_cents": 100_000,
        "primary_purpose_category": "ECONOMIC_DEVELOPMENT",
        "lmi_benefit_pct": 0.60,
        "activity_date": "2026-01-10",
    }
    defaults.update(overrides)
    return defaults


def review_decision_payload(decision: str, **overrides) -> dict:
    """PRD §3.4: decision QUALIFY|DISQUALIFY; allocation_method / disqualify_reason."""
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_branch_payload(assessment_area_id: str, **overrides) -> dict:
    """Required inputs per PRD §3.5."""
    defaults = {
        "branch_code": _next("BR"),
        "assessment_area_id": assessment_area_id,
        "census_tract": "T1",
        "tract_income_level": "LOW",
    }
    defaults.update(overrides)
    return defaults


def create_public_comment_payload(**overrides) -> dict:
    """Required inputs per PRD §3.6."""
    defaults = {
        "commenter_name": "Jane Public",
        "channel": "EMAIL",
        "subject_area": "LENDING",
        "content": "Please lend more in our neighborhood.",
    }
    defaults.update(overrides)
    return defaults


def create_public_file_payload(**overrides) -> dict:
    """Required inputs per PRD §3.6."""
    defaults = {"bank_name": "First Test Bank"}
    defaults.update(overrides)
    return defaults


def create_exam_cycle_payload(**overrides) -> dict:
    """Required inputs per PRD §3.7."""
    defaults = {
        "exam_type": "LARGE_BANK",
        "evaluation_window_start": "2024-01-01",
        "evaluation_window_end": "2024-12-31",
    }
    defaults.update(overrides)
    return defaults


def assign_rating_payload(lending: str, investment: str, service: str) -> dict:
    """PRD §3.7: the three test ratings supplied at assign-preliminary-rating."""
    return {
        "lending_test_rating": lending,
        "investment_test_rating": investment,
        "service_test_rating": service,
    }


def create_expansion_application_payload(target_assessment_area_id: str,
                                         **overrides) -> dict:
    """Required inputs per PRD §3.8 (branch_* only for BRANCH_OPENING)."""
    defaults = {
        "application_type": "MERGER",
        "target_assessment_area_id": target_assessment_area_id,
    }
    defaults.update(overrides)
    return defaults
