"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PLAN_NAME": "Test Plan",
    "PARTICIPANT_NAME": "Test Participant",
    "VESTED_BALANCE_CENTS": 10_000_000,
    "LOAN_PRINCIPAL_CENTS": 500_000,
    "LOAN_TERM_MONTHS": 12,
    "HARDSHIP_REASON": "MEDICAL",
    "HARDSHIP_AMOUNT_CENTS": 200_000,
    "HARDSHIP_SEMANTICS": "GROSS",
    "DOCUMENT_TYPE": "MEDICAL_BILL",
    "DEFERRAL_PCT": 0.10,
    "DECISION": "APPROVE",
}


def create_plan_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["PLAN_NAME"]}
    defaults.update(overrides)
    return defaults


def create_participant_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PARTICIPANT_NAME"],
        "vested_balance_cents": DEFAULTS["VESTED_BALANCE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def update_participant_payload(**overrides) -> dict:
    """PATCH /participants/{id} body — all fields optional."""
    return dict(overrides)


def create_loan_payload(**overrides) -> dict:
    defaults = {
        "principal_amount_cents": DEFAULTS["LOAN_PRINCIPAL_CENTS"],
        "term_months": DEFAULTS["LOAN_TERM_MONTHS"],
    }
    defaults.update(overrides)
    return defaults


def refinance_loan_payload(**overrides) -> dict:
    defaults = {"cash_out_cents": 0}
    defaults.update(overrides)
    return defaults


def rebuild_schedule_payload(expected_loan_version, term_months=6, **overrides) -> dict:
    defaults = {
        "expected_loan_version": expected_loan_version,
        "term_months": term_months,
    }
    defaults.update(overrides)
    return defaults


def create_remittance_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 85_607,
        "pay_date": "2026-05-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_hardship_request_payload(**overrides) -> dict:
    defaults = {
        "reason_category": DEFAULTS["HARDSHIP_REASON"],
        "amount_cents": DEFAULTS["HARDSHIP_AMOUNT_CENTS"],
        "amount_semantics": DEFAULTS["HARDSHIP_SEMANTICS"],
    }
    defaults.update(overrides)
    return defaults


def upload_hardship_document_payload(**overrides) -> dict:
    defaults = {
        "document_type": DEFAULTS["DOCUMENT_TYPE"],
        "amount_cents": DEFAULTS["HARDSHIP_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def decide_approval_task_payload(**overrides) -> dict:
    defaults = {"decision": DEFAULTS["DECISION"]}
    defaults.update(overrides)
    return defaults


def create_contribution_election_payload(**overrides) -> dict:
    defaults = {"deferral_pct": DEFAULTS["DEFERRAL_PCT"]}
    defaults.update(overrides)
    return defaults


def update_plan_policy_payload(expected_plan_version, **overrides) -> dict:
    defaults = {"expected_plan_version": expected_plan_version}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
