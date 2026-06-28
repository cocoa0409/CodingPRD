"""Payload factories — one per entity, input fields only."""
from .constants import PLAN_DEFAULTS


# Canonical face/age tiers and surrender-charge tiers used by the difficulty fixtures.
FULL_FACE_TIERS = [
    {"tier_name": "SMALL", "min_face_cents": 100000, "max_face_cents": 1000000, "tier_load_pct": 0.0},
    {"tier_name": "MID", "min_face_cents": 1000001, "max_face_cents": 2500000, "tier_load_pct": 0.10},
    {"tier_name": "LARGE", "min_face_cents": 2500001, "max_face_cents": 5000000, "tier_load_pct": 0.25},
]

FULL_AGE_BANDS = [
    {"band_name": "A", "min_age": 45, "max_age": 60, "age_factor": 1.0},
    {"band_name": "B", "min_age": 61, "max_age": 75, "age_factor": 1.5},
    {"band_name": "C", "min_age": 76, "max_age": 85, "age_factor": 2.2},
]

FULL_SURRENDER_CHARGE_TIERS = [
    {"min_gross_cents": 0, "max_gross_cents": 50000, "charge_pct": 0.10},
    {"min_gross_cents": 50001, "max_gross_cents": 200000, "charge_pct": 0.05},
    {"min_gross_cents": 200001, "max_gross_cents": 99999999, "charge_pct": 0.0},
]

# A single wide age band that maps every age 45..85 to age_factor 1.0; used by
# corner fixtures that do not exercise the age-band selection logic.
SIMPLE_AGE_BANDS = [
    {"band_name": "A", "min_age": 45, "max_age": 85, "age_factor": 1.0}
]

SIMPLE_FACE_TIERS = [
    {"tier_name": "SMALL", "min_face_cents": 100000, "max_face_cents": 1000000, "tier_load_pct": 0.0}
]

ZERO_SURRENDER_CHARGE_TIERS = [
    {"min_gross_cents": 0, "max_gross_cents": 99999999, "charge_pct": 0.0}
]


def create_product_plan_payload(**overrides) -> dict:
    """Full canonical GRADED plan (the §1.8 fixture). Three face tiers, three
    age bands, three surrender-charge tiers."""
    defaults = {
        "name": "Heritage Graded",
        "benefit_type": "GRADED_BENEFIT",
        "face_tiers": FULL_FACE_TIERS,
        "age_bands": FULL_AGE_BANDS,
        "surrender_charge_tiers": FULL_SURRENDER_CHARGE_TIERS,
    }
    defaults.update(PLAN_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_simple_plan_payload(**overrides) -> dict:
    """Minimal GRADED plan: one face tier, one wide age band, zero surrender
    charge. Used by corner fixtures that do not exercise tier/band selection."""
    defaults = {
        "name": "Heritage Graded",
        "benefit_type": "GRADED_BENEFIT",
        "base_monthly_rate_per_1000_cents": 400,
        "cash_value_factor_per_1000_cents": 1500,
        "cash_value_vesting_years": 3,
        "min_issue_age": 45,
        "max_issue_age": 85,
        "face_tiers": SIMPLE_FACE_TIERS,
        "age_bands": SIMPLE_AGE_BANDS,
        "surrender_charge_tiers": ZERO_SURRENDER_CHARGE_TIERS,
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Mabel Crane",
        "date_of_birth": "1960-06-15",
        "gender": "FEMALE",
        "tobacco_use": False,
        "state_code": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id, product_plan_id, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "product_plan_id": product_plan_id,
        "requested_face_amount_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_questionnaire_payload(**overrides) -> dict:
    defaults = {
        "terminal_illness": False,
        "aids_hiv": False,
        "nursing_home_confined": False,
        "major_condition_last_2y": False,
    }
    defaults.update(overrides)
    return defaults


def create_beneficiary_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Primary Heir",
        "relationship": "CHILD",
        "share_pct": 100,
    }
    defaults.update(overrides)
    return defaults


def create_funeral_home_assignment_payload(**overrides) -> dict:
    defaults = {
        "funeral_home_name": "Restful Pines",
        "assigned_benefit_cents": 300000,
    }
    defaults.update(overrides)
    return defaults


def create_premium_payment_payload(policy_id, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "amount_cents": 6000,
        "coverage_start": "2026-02-01T00:00:00Z",
        "coverage_end": "2026-03-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_policy_loan_payload(policy_id, expected_policy_version, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "expected_policy_version": expected_policy_version,
        "principal_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(policy_id, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "date_of_death": "2026-05-01T00:00:00Z",
        "manner_of_death": "NATURAL",
    }
    defaults.update(overrides)
    return defaults


def create_death_certificate_payload(**overrides) -> dict:
    defaults = {
        "certificate_number": "DC-1",
        "certified_cause": "ILLNESS",
        "verified": True,
    }
    defaults.update(overrides)
    return defaults
