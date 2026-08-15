"""Payload factories — input fields only (PRD §3, §4)."""

DEFAULTS = {
    "PLAN_NAME": "Test Plan",
    "EFFECTIVE_DATE": "2026-01-01",
    "EVENTS_ALL": ["SEPARATION", "DEATH", "DISABILITY", "FIXED_TIME",
                   "UNFORESEEABLE_EMERGENCY", "CHANGE_IN_CONTROL"],
    "OFFICER_COMP_THRESHOLD_CENTS": 20000000,
    "EMPLOYEE_REF": "EMP-1",
    "HIRE_DATE": "2023-08-03",
    "ELIGIBILITY_DATE": "2026-01-05",
    "ANNUAL_COMP_CENTS": 30000000,
    "TICKER": "FIX5",
    "CREDITING_MODE": "FIXED_RATE",
    "ANNUAL_RATE_BP": 500,
    "PLAN_YEAR": 2027,
    "GENERAL_OPEN": "2026-10-01",
    "GENERAL_CLOSE": "2026-12-31",
    "DEFERRAL_PCT_BP": 5000,
    "ALLEGED_SEPARATION_DATE": "2027-03-15",
    "TRIGGER_REASON": "TERMINATION",
    "FUNDING_TARGET_BP": 10000,
}


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PLAN_NAME"],
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "distribution_events_allowed": list(DEFAULTS["EVENTS_ALL"]),
        "officer_comp_threshold_cents": DEFAULTS["OFFICER_COMP_THRESHOLD_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(plan_id: str, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "employee_ref": DEFAULTS["EMPLOYEE_REF"],
        "hire_date": DEFAULTS["HIRE_DATE"],
        "initial_eligibility_date": DEFAULTS["ELIGIBILITY_DATE"],
        "annual_compensation_cents": DEFAULTS["ANNUAL_COMP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_notional_fund_payload(plan_id: str, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "ticker": DEFAULTS["TICKER"],
        "crediting_mode": DEFAULTS["CREDITING_MODE"],
        "annual_rate_bp": DEFAULTS["ANNUAL_RATE_BP"],
    }
    defaults.update(overrides)
    return defaults


def create_election_window_payload(plan_id: str, expected_plan_version: int, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "plan_year": DEFAULTS["PLAN_YEAR"],
        "general_open_date": DEFAULTS["GENERAL_OPEN"],
        "general_close_date": DEFAULTS["GENERAL_CLOSE"],
        "expected_plan_version": expected_plan_version,
    }
    defaults.update(overrides)
    return defaults


def create_deferral_election_payload(participant_id: str, window_id: str, fund_id: str,
                                     **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "election_window_id": window_id,
        "notional_fund_id": fund_id,
        "election_type": "GENERAL",
        "deferral_percent_bp": DEFAULTS["DEFERRAL_PCT_BP"],
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(participant_id: str, plan_id: str, **overrides) -> dict:
    defaults = {"participant_id": participant_id, "plan_id": plan_id}
    defaults.update(overrides)
    return defaults


def post_deferral_payload(amount_cents: int, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "service_period_start": "2027-01-01",
        "service_period_end": "2027-01-31",
    }
    defaults.update(overrides)
    return defaults


def create_crediting_run_payload(plan_id: str, expected_plan_version: int, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "period_start": "2028-03-01",
        "period_end": "2028-04-01",
        "expected_plan_version": expected_plan_version,
    }
    defaults.update(overrides)
    return defaults


def create_rabbi_trust_payload(plan_id: str, **overrides) -> dict:
    defaults = {"plan_id": plan_id, "funding_target_bp": DEFAULTS["FUNDING_TARGET_BP"]}
    defaults.update(overrides)
    return defaults


def funding_event_payload(event_type: str, amount_cents: int, **overrides) -> dict:
    defaults = {"event_type": event_type, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_separation_case_payload(participant_id: str, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "alleged_separation_date": DEFAULTS["ALLEGED_SEPARATION_DATE"],
        "trigger_reason": DEFAULTS["TRIGGER_REASON"],
    }
    defaults.update(overrides)
    return defaults


def service_record_payload(period_start: str, period_end: str, service_fraction_bp: int,
                           **overrides) -> dict:
    defaults = {
        "period_start": period_start,
        "period_end": period_end,
        "service_fraction_bp": service_fraction_bp,
    }
    defaults.update(overrides)
    return defaults


def determination_payload(outcome: str) -> dict:
    return {"outcome": outcome}


def create_specified_list_payload(plan_id: str, expected_plan_version: int, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "identification_date": "2026-12-31",
        "effective_date": "2027-04-01",
        "expected_plan_version": expected_plan_version,
    }
    defaults.update(overrides)
    return defaults


def add_member_payload(participant_id: str, basis: str, annual_compensation_cents: int,
                       **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "basis": basis,
        "annual_compensation_cents": annual_compensation_cents,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_request_payload(account_id: str, event_type: str, **overrides) -> dict:
    defaults = {"account_id": account_id, "event_type": event_type}
    defaults.update(overrides)
    return defaults


def create_cic_event_payload(plan_id: str, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "event_type": "OWNERSHIP_CHANGE",
        "effective_date": "2027-02-01",
        "stake_change_bp": 5000,
    }
    defaults.update(overrides)
    return defaults


def cic_adjudication_payload(outcome: str) -> dict:
    return {"outcome": outcome}


def create_operational_failure_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "failure_type": "EARLY_PAYMENT",
        "failure_date": "2027-01-15",
        "amount_cents": 500000,
        "description": "operational failure under test",
    }
    defaults.update(overrides)
    return defaults


def quantify_payload(correction_credit_cents: int = 0) -> dict:
    return {"correction_credit_cents": correction_credit_cents}


def create_document_finding_payload(plan_id: str, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "description": "Documentary failure under test",
        "failure_year": 2026,
    }
    defaults.update(overrides)
    return defaults


def file_correction_payload(correction_text: str = "Amendment curing the failure") -> dict:
    return {"correction_text": correction_text}


def finding_adjudication_payload(outcome: str) -> dict:
    return {"outcome": outcome}
