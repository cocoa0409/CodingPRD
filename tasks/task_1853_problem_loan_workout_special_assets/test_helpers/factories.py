"""Payload factories — one per entity, input fields only."""

_COUNTER = {"n": 0}


def _next() -> int:
    _COUNTER["n"] += 1
    return _COUNTER["n"]


DEFAULTS = {
    "LEGAL_NAME": "Test Borrower LLC",
    "NAICS_CODE": "541110",
    "RISK_RATING": 7,
    "ORIGINAL_PRINCIPAL": 50_000_000,
    "RATE_BPS": 1000,
    "DAYS_PAST_DUE": 65,
    "FUTURE_DATE": "2027-01-01T00:00:00Z",
    "PAST_DATE": "2026-07-01T00:00:00Z",
    "STATUTE_DEADLINE": "2028-01-01T00:00:00Z",
}


def create_borrower_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "legal_name": f"{DEFAULTS['LEGAL_NAME']} {n}",
        "tax_id": f"55-{n:07d}",
        "naics_code": DEFAULTS["NAICS_CODE"],
        "internal_risk_rating": DEFAULTS["RISK_RATING"],
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(borrower_id: str, **overrides) -> dict:
    n = _next()
    defaults = {
        "borrower_id": borrower_id,
        "loan_number": f"LN-{n:05d}",
        "original_principal_cents": DEFAULTS["ORIGINAL_PRINCIPAL"],
        "contractual_rate_bps": DEFAULTS["RATE_BPS"],
        "days_past_due": DEFAULTS["DAYS_PAST_DUE"],
    }
    defaults.update(overrides)
    return defaults


def create_workout_case_payload(**overrides) -> dict:
    defaults = {
        "entry_trigger": "DELINQUENCY_60",
        "risk_rating_at_entry": 7,
        "case_officer_id": "officer-1",
    }
    defaults.update(overrides)
    return defaults


def create_action_plan_payload(expected_case_version: int, **overrides) -> dict:
    defaults = {
        "plan_text": "Workout strategy",
        "target_resolution_date": DEFAULTS["FUTURE_DATE"],
        "milestone_count": 1,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_proposal_payload(expected_case_version: int, **overrides) -> dict:
    defaults = {
        "proposal_kind": "MODIFICATION",
        "concession_rate_bps": 500,
        "term_extension_months": 6,
        "principal_forgiveness_cents": 0,
        "borrower_concession_cents": 0,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_counter_payload(**overrides) -> dict:
    defaults = {
        "concession_rate_bps": 450,
        "term_extension_months": 9,
        "principal_forgiveness_cents": 0,
        "borrower_concession_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_collateral_payload(**overrides) -> dict:
    defaults = {
        "collateral_type": "CRE_REAL_ESTATE",
        "description": "Collateral asset",
        "liquidation_discount_bps": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_appraisal_payload(expected_collateral_version: int, **overrides) -> dict:
    defaults = {
        "appraised_value_cents": 40_000_000,
        "effective_date": DEFAULTS["PAST_DATE"],
        "appraiser_id": "appraiser-1",
        "expected_collateral_version": expected_collateral_version,
    }
    defaults.update(overrides)
    return defaults


def create_impairment_cecl_payload(**overrides) -> dict:
    defaults = {
        "method": "CECL",
        "probability_of_default_bps": 2500,
        "loss_given_default_bps": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_impairment_tdr_dcf_payload(**overrides) -> dict:
    defaults = {
        "method": "TDR_DCF",
        "probability_of_default_bps": 2500,
        "loss_given_default_bps": 4000,
        "expected_cash_flows": [{"period_index": 12, "amount_cents": 10_000_000}],
    }
    defaults.update(overrides)
    return defaults


def create_legal_referral_payload(**overrides) -> dict:
    defaults = {
        "referral_kind": "NOTE_SALE_PREP",
        "demand_amount_cents": 0,
        "statute_deadline": DEFAULTS["STATUTE_DEADLINE"],
        "decision_rationale": "Value-maximizing path",
    }
    defaults.update(overrides)
    return defaults


def create_charge_off_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 1_000_000,
        "reason_code": "CONFIRMED_LOSS",
    }
    defaults.update(overrides)
    return defaults


def create_recovery_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 1_000_000,
        "recovery_source": "NOTE_SALE_PROCEEDS",
        "allocation_mode": "CHRONOLOGICAL",
    }
    defaults.update(overrides)
    return defaults


def create_exit_decision_payload(**overrides) -> dict:
    defaults = {
        "chosen_path": "NOTE_SALE",
        "npv_foreclosure_cents": 1_000_000,
        "npv_deed_in_lieu_cents": 900_000,
        "override_justification": "Analyst override with documented rationale",
    }
    defaults.update(overrides)
    return defaults
