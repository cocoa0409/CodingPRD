"""Payload factories — one per creatable resource, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "ANALYST_NAME": "Ann Analyst",
    "CAPACITY_MAX_CASES": 10,
    "CUSTOMER_NAME": "Carl Customer",
    "COUNTRY_CODE": "US",
    "COUNTRY_RISK": "LOW",
    "SCENARIO_CODE": "STRUCT-CASH-7D",
    "SCENARIO_NAME": "Structuring cash 7d",
    "THRESHOLD_AMOUNT_CENTS": 1_000_000,
    "LOOKBACK_DAYS": 7,
    "MIN_TRANSACTION_COUNT": 3,
    "EFFECTIVE_FROM": "2026-04-01T00:00:00Z",
    "TUNING_RATIONALE": "Initial calibration",
    "BACKTEST_PRECISION": 0.7,
    "BACKTEST_RECALL": 0.6,
    "AGENCY_NAME": "FBI",
    "PURPOSE_NOTE": "Coordinate on suspected structuring",
    "CERTIFIED_AT": "2026-01-01T00:00:00Z",
}


def create_analyst_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["ANALYST_NAME"],
        "capacity_max_cases": DEFAULTS["CAPACITY_MAX_CASES"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CUSTOMER_NAME"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
        "country_risk": DEFAULTS["COUNTRY_RISK"],
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    defaults = {"account_number": "ACC-0001"}
    defaults.update(overrides)
    return defaults


def create_transaction_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 400_000,
        "txn_type": "CASH_DEPOSIT",
        "direction": "CREDIT",
        "counterparty_country": "US",
        "posted_at": "2026-04-28T10:00:00Z",
        "channel": "BRANCH",
    }
    defaults.update(overrides)
    return defaults


def create_scenario_payload(**overrides) -> dict:
    defaults = {
        "scenario_code": DEFAULTS["SCENARIO_CODE"],
        "name": DEFAULTS["SCENARIO_NAME"],
        "applies_to_txn_types": ["CASH_DEPOSIT"],
        "direction_filter": "CREDIT",
    }
    defaults.update(overrides)
    return defaults


def propose_threshold_payload(expected_scenario_version, **overrides) -> dict:
    defaults = {
        "expected_scenario_version": expected_scenario_version,
        "threshold_amount_cents": DEFAULTS["THRESHOLD_AMOUNT_CENTS"],
        "lookback_days": DEFAULTS["LOOKBACK_DAYS"],
        "min_transaction_count": DEFAULTS["MIN_TRANSACTION_COUNT"],
        "weight_amount": 0.5,
        "weight_velocity": 0.3,
        "weight_geo": 0.2,
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "tuning_rationale": DEFAULTS["TUNING_RATIONALE"],
        "backtest_precision": DEFAULTS["BACKTEST_PRECISION"],
        "backtest_recall": DEFAULTS["BACKTEST_RECALL"],
    }
    defaults.update(overrides)
    return defaults


def evaluate_payload(account_id, evaluated_at=None) -> dict:
    payload = {"account_id": account_id}
    if evaluated_at is not None:
        payload["evaluated_at"] = evaluated_at
    return payload


def dismiss_alert_payload(**overrides) -> dict:
    defaults = {"dismissal_rationale": "Matches known payroll pattern"}
    defaults.update(overrides)
    return defaults


def link_alert_payload(case_id) -> dict:
    return {"case_id": case_id}


def create_case_payload(customer_id, **overrides) -> dict:
    defaults = {"customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def assign_case_payload(analyst_id) -> dict:
    return {"analyst_id": analyst_id}


def sar_decision_payload(decision, expected_case_version, **overrides) -> dict:
    defaults = {
        "decision": decision,
        "decision_rationale": "Unexplained structuring pattern",
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def case_qa_review_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_sar_payload(activity_start_date="2026-03-10",
                       activity_end_date="2026-04-10", **overrides) -> dict:
    defaults = {
        "activity_start_date": activity_start_date,
        "activity_end_date": activity_end_date,
    }
    defaults.update(overrides)
    return defaults


def update_narrative_payload(expected_sar_version, **overrides) -> dict:
    defaults = {"expected_sar_version": expected_sar_version}
    defaults.update(overrides)
    return defaults


def sar_qa_review_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def complete_review_payload(outcome) -> dict:
    return {"outcome": outcome}


def create_le_inquiry_payload(subject_customer_id, **overrides) -> dict:
    defaults = {
        "agency_name": DEFAULTS["AGENCY_NAME"],
        "inquiry_reference": "LE-1",
        "subject_customer_id": subject_customer_id,
    }
    defaults.update(overrides)
    return defaults


def link_inquiry_payload(case_id) -> dict:
    return {"case_id": case_id}


def respond_inquiry_payload(**overrides) -> dict:
    defaults = {"response_summary": "Provided account records for the review period"}
    defaults.update(overrides)
    return defaults


def create_info_share_payload(subject_customer_id, **overrides) -> dict:
    defaults = {
        "direction": "OUTBOUND",
        "counterparty_institution_id": "INST-9",
        "subject_customer_id": subject_customer_id,
        "certified_at": DEFAULTS["CERTIFIED_AT"],
        "purpose_note": DEFAULTS["PURPOSE_NOTE"],
    }
    defaults.update(overrides)
    return defaults


def propose_decision_payload(**overrides) -> dict:
    defaults = {
        "decision": "EXIT",
        "rationale": "Confirmed structuring; relationship not retainable",
    }
    defaults.update(overrides)
    return defaults


def reverse_decision_payload(**overrides) -> dict:
    defaults = {"rationale": "Approval withdrawn before execution"}
    defaults.update(overrides)
    return defaults


def create_qa_review_payload(**overrides) -> dict:
    return dict(overrides)


def complete_qa_review_payload(**overrides) -> dict:
    defaults = {"outcome": "PASS", "defect_count": 0}
    defaults.update(overrides)
    return defaults
