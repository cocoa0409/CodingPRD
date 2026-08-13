"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_program_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "program_code": f"MT-TEST-{n}",
        "tort_name": f"Test Tort {n}",
        "qsf_principal_cents": TEST_DEFAULTS["QSF_PRINCIPAL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_tier_matrix_payload(**overrides) -> dict:
    defaults = {
        "injury_category": "QUALIFYING_CAT_A",
        "severity_score_min": 0,
        "severity_score_max": 100,
        "base_award_cents": TEST_DEFAULTS["BASE_AWARD_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_claimant_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Test Claimant {n}",
        "date_of_birth": TEST_DEFAULTS["DATE_OF_BIRTH"],
        "ssn_last4": f"{n % 10000:04d}",
        "date_of_exposure_start": TEST_DEFAULTS["EXPOSURE_START"],
        "date_of_exposure_end": TEST_DEFAULTS["EXPOSURE_END"],
        "date_of_diagnosis": TEST_DEFAULTS["DIAGNOSIS"],
        "injury_category": "QUALIFYING_CAT_A",
        "represented_by_counsel": False,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(claimant_id: str, **overrides) -> dict:
    defaults = {"claimant_id": claimant_id}
    defaults.update(overrides)
    return defaults


def create_medical_record_payload(**overrides) -> dict:
    defaults = {
        "provider_name": "General Hospital",
        "record_type": "DIAGNOSTIC",
        "severity_score": 70,
        "confirms_qualifying_injury": True,
    }
    defaults.update(overrides)
    return defaults


def create_lien_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "lien_type": "MEDICARE",
        "holder_name": f"Holder {n}",
        "asserted_amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(appealed_tier_matrix_id: str, requested_tier_matrix_id: str, **overrides) -> dict:
    defaults = {
        "appealed_tier_matrix_id": appealed_tier_matrix_id,
        "requested_tier_matrix_id": requested_tier_matrix_id,
        "grounds": "The assigned tier does not reflect the evidence on file.",
    }
    defaults.update(overrides)
    return defaults


def deny_claim_payload(**overrides) -> dict:
    defaults = {"denied_reason": "Does not meet program criteria."}
    defaults.update(overrides)
    return defaults


def waive_lien_payload(**overrides) -> dict:
    defaults = {"resolution_notes": "Holder agreed to waive the lien in full."}
    defaults.update(overrides)
    return defaults


def appeal_rationale_payload(**overrides) -> dict:
    defaults = {"resolution_rationale": "Decision rationale recorded after full review."}
    defaults.update(overrides)
    return defaults
