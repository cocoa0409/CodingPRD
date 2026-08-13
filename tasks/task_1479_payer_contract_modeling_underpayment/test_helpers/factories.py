"""Payload factories — one per creatable resource, input fields only (PRD §3/§4)."""
import itertools

from .constants import (
    CONTRACT_EFFECTIVE_DATE,
    CONTRACT_EXPIRATION_DATE,
    DEFAULT_APPEAL_DEADLINE_DAYS,
    DEFAULT_BASE_RATE_CENTS,
    DEFAULT_BILLED_CHARGES_CENTS,
    DEFAULT_CLOCK_DATE,
)

_COUNTER = itertools.count(1)


def _seq() -> int:
    return next(_COUNTER)


def create_payer_payload(**overrides) -> dict:
    defaults = {
        "name": f"Payer {_seq()}",
        "payer_type": "COMMERCIAL",
        "appeal_deadline_days": DEFAULT_APPEAL_DEADLINE_DAYS,
    }
    defaults.update(overrides)
    return defaults


def create_payer_contract_payload(payer_id: str, **overrides) -> dict:
    defaults = {
        "payer_id": payer_id,
        "contract_code": f"C-{_seq()}",
        "effective_date": CONTRACT_EFFECTIVE_DATE,
        "expiration_date": CONTRACT_EXPIRATION_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_contract_term_payload(contract_id: str, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "service_category": "INPATIENT_MEDICAL",
        "rate_model": "PER_DIEM",
    }
    # PRD §3.2: base_rate_cents is required unless the model is
    # PERCENT_OF_CHARGE (which takes percent_of_charge_bp instead); injecting
    # the default for a PERCENT_OF_CHARGE term would be a mismatched
    # rate-field combination (ERR_INVALID_RATE_PARAMETERS).
    if overrides.get("rate_model", defaults["rate_model"]) != "PERCENT_OF_CHARGE":
        defaults["base_rate_cents"] = DEFAULT_BASE_RATE_CENTS
    defaults.update(overrides)
    return defaults


def create_carve_out_provision_payload(contract_id: str, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "carve_type": "IMPLANT",
        "revenue_codes": ["0278"],
        "rate_model": "PERCENT_OF_CHARGE",
        "percent_bp": 8000,
    }
    defaults.update(overrides)
    return defaults


def create_stop_loss_provision_payload(contract_id: str, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "provision_type": "STOP_LOSS",
        "threshold_cents": 500000,
        "rate_bp": 9000,
    }
    defaults.update(overrides)
    return defaults


def create_rate_escalator_payload(contract_id: str, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "effective_date": "2026-09-01",
        "escalator_bp": 1000,
        "compounding": True,
    }
    defaults.update(overrides)
    return defaults


def create_rate_amendment_payload(
    contract_id: str, expected_contract_version: int, **overrides
) -> dict:
    defaults = {
        "contract_id": contract_id,
        "effective_date": "2026-09-01",
        "term_overrides": [
            {"service_category": "INPATIENT_MEDICAL", "base_rate_cents": 110000}
        ],
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def create_network_agreement_payload(payer_id: str, **overrides) -> dict:
    defaults = {
        "payer_id": payer_id,
        "network_name": f"WrapNet-{_seq()}",
        "wrap_rate_bp": 5000,
        "precedence_rank": 1,
        "effective_date": CONTRACT_EFFECTIVE_DATE,
        "expiration_date": CONTRACT_EXPIRATION_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(payer_id: str, **overrides) -> dict:
    defaults = {
        "payer_id": payer_id,
        "claim_number": f"CL-{_seq()}",
        "patient_account_number": f"PA-{_seq()}",
        "service_category": "INPATIENT_MEDICAL",
        "admission_date": "2026-06-01",
        "discharge_date": "2026-06-03",
        "total_billed_charges_cents": DEFAULT_BILLED_CHARGES_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_claim_line_payload(**overrides) -> dict:
    defaults = {
        "revenue_code": "0100",
        "service_date": "2026-06-01",
        "charge_cents": 250000,
        "units": 1,
    }
    defaults.update(overrides)
    return defaults


def create_remittance_payload(claim_id: str, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "paid_amount_cents": 100000,
        "remittance_date": DEFAULT_CLOCK_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(case_id: str, level: int, **overrides) -> dict:
    defaults = {"case_id": case_id, "level": level}
    defaults.update(overrides)
    return defaults


def create_write_off_payload(**overrides) -> dict:
    defaults = {"amount_cents": 0, "reason": "uncollectible"}
    defaults.update(overrides)
    return defaults


def create_record_outcome_payload(outcome: str, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_contract_proposal_payload(
    contract_id: str, expected_contract_version: int, **overrides
) -> dict:
    defaults = {
        "contract_id": contract_id,
        "proposed_terms": [
            {
                "service_category": "OUTPATIENT_SURGERY",
                "rate_model": "CASE_RATE",
                "base_rate_cents": 550000,
            }
        ],
        "projected_volume_mix": [
            {"service_category": "OUTPATIENT_SURGERY", "annual_units": 2}
        ],
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def create_accept_proposal_payload(**overrides) -> dict:
    defaults = {
        "successor_contract_code": f"S-{_seq()}",
        "successor_effective_date": "2027-01-01",
        "successor_expiration_date": "2027-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
