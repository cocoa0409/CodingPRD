"""Payload factories — one per creatable entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_program_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "program_code": f"PRG-T{n}",
        "peril_type": "RAINFALL_DEFICIT",
        "regulatory_classification": "ADMITTED_INSURANCE",
        "contract_wording_version": f"CW-T{n}",
        "exposure_limit_cents": TEST_DEFAULTS["EXPOSURE_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_index_definition_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "index_code": f"IDX-T{n}",
        "measurement_unit": "mm",
        "aggregation_window_days": 30,
        "data_source_agreement_ref": f"DSA-T{n}",
        "source_priority_mode": "STATION_PRIMARY",
        "trigger_thresholds": [
            {"tier": 1, "threshold_value": 50, "payout_fraction": 0.25}
        ],
        "strike_direction": "BELOW",
        "historical_breach_frequency": TEST_DEFAULTS["BREACH_FREQUENCY"],
        "expected_loss_ratio": TEST_DEFAULTS["LOSS_RATIO"],
    }
    defaults.update(overrides)
    return defaults


def create_station_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "station_code": f"ST-T{n}",
        "station_kind": "PHYSICAL_STATION",
        "reliability_weight": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_observation_payload(**overrides) -> dict:
    defaults = {
        "station_id": "",  # caller must supply
        "window_end_date": TEST_DEFAULTS["WINDOW_END_DATE"],
        "measured_value": 40,
    }
    defaults.update(overrides)
    return defaults


def create_policyholder_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "legal_name": f"Holder T{n}",
        "tax_id": f"T-T{n}",
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    defaults = {
        "index_definition_id": "",  # caller must supply
        "sum_insured_cents": TEST_DEFAULTS["SUM_INSURED"],
        "policy_start_date": TEST_DEFAULTS["POLICY_START_DATE"],
        "policy_end_date": TEST_DEFAULTS["POLICY_END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_treaty_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "treaty_name": f"TREATY-T{n}",
        "ceded_percentage": 25,
        "attachment_point_cents": 0,
        "treaty_limit_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": TEST_DEFAULTS["ADMITTED_INVOICE_CENTS"]}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {"dispute_reason": "BASIS_RISK_MISMATCH", "claimed_tier": 2}
    defaults.update(overrides)
    return defaults
