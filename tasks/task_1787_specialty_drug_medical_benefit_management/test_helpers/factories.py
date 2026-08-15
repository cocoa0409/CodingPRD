"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import DEFAULTS

# Auto-unique J-code / name sequences so multiple creates inside one test never
# collide on the catalog-wide j_code uniqueness rule (PRD §3.1).
_jcode_seq = itertools.count(9000)
_name_seq = itertools.count(1)
_member_seq = itertools.count(100)


def next_j_code() -> str:
    return f"J{next(_jcode_seq)}"


def create_drug_payload(**overrides) -> dict:
    """Registration payload for a specialty drug (PRD §3.1)."""
    defaults = {
        "j_code": next_j_code(),
        "drug_name": "TestDrug",
        "billing_unit_mg": 10,
        "vial_size_mg": 100,
        "single_dose_vial": True,
        "sourcing_rule": "EITHER",
        "dose_rounding_mode": "VIAL",
        "max_single_dose_mg": 2000,
        "site_of_care_eligible": False,
    }
    defaults.update(overrides)
    return defaults


def create_asp_schedule_payload(drug_id, **overrides) -> dict:
    """ASP rate publication payload (PRD §3.3)."""
    defaults = {
        "drug_id": drug_id,
        "effective_start": DEFAULTS["RATE_EFFECTIVE_START"],
        "asp_rate_cents": DEFAULTS["ASP_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_clinical_policy_payload(drug_id, expected_drug_version, **overrides) -> dict:
    """Policy version payload with the OCC field (PRD §2.7, §3.2)."""
    defaults = {
        "drug_id": drug_id,
        "status": "ACTIVE",
        "expected_drug_version": expected_drug_version,
        "covered_diagnoses": [DEFAULTS["DIAGNOSIS"]],
        "step_therapy_required": False,
        "requires_site_of_care_redirection": False,
        "biosimilar_substitution": "DISABLED",
    }
    defaults.update(overrides)
    return defaults


def create_provider_account_payload(**overrides) -> dict:
    """Provider registration payload (PRD §3.3)."""
    defaults = {"name": f"Provider {next(_name_seq)}"}
    defaults.update(overrides)
    return defaults


def create_auth_payload(drug_id, member_id=None, **overrides) -> dict:
    """Prior-authorization submission payload (PRD §3.4)."""
    if member_id is None:
        member_id = f"MEM-{next(_member_seq)}"
    defaults = {
        "drug_id": drug_id,
        "member_id": member_id,
        "diagnosis_code": DEFAULTS["DIAGNOSIS"],
        "requested_start_date": DEFAULTS["AUTH_START_DATE"],
        "requested_dose_mg": 100,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(auth_id, drug_id, j_code_billed, **overrides) -> dict:
    """Infusion claim payload (PRD §3.6)."""
    defaults = {
        "auth_id": auth_id,
        "drug_id": drug_id,
        "service_date": DEFAULTS["SERVICE_DATE"],
        "site_of_care": "OFFICE",
        "sourcing_path": "BUY_AND_BILL",
        "j_code_billed": j_code_billed,
        "billed_units": 10,
    }
    defaults.update(overrides)
    return defaults


def create_biosimilar_policy_payload(reference_drug_id, biosimilar_drug_id, **overrides) -> dict:
    """Biosimilar substitution policy payload (PRD §3.7)."""
    defaults = {
        "reference_drug_id": reference_drug_id,
        "biosimilar_drug_id": biosimilar_drug_id,
        "provider_incentive_addon_pct": 0.02,
        "member_copay_waiver_pct": 0.5,
        "effective_start": "2026-08-01",
        "effective_end": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_pipeline_drug_payload(**overrides) -> dict:
    """Pipeline registry payload (PRD §3.8)."""
    defaults = {
        "drug_name": f"PipelineDrug {next(_name_seq)}",
        "expected_approval_date": "2027-01-15",
        "prevalence_per_100k": 50,
        "projected_annual_cost_cents": 1200000,
        "year1_uptake_pct": 0.30,
        "steady_state_uptake_pct": 0.60,
        "biosimilar_erosion_pct": 0.25,
    }
    defaults.update(overrides)
    return defaults


def create_spend_forecast_payload(**overrides) -> dict:
    """Forecast run payload (PRD §3.8)."""
    defaults = {
        "variant": "BASELINE",
        "horizon_years": 1,
        "enrollment_projection": 500000,
    }
    defaults.update(overrides)
    return defaults
