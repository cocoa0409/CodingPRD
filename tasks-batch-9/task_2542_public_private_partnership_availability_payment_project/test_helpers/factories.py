"""Payload factories — one per write endpoint, input fields only."""
from .constants import TEST_DEFAULTS


def create_concessionaire_payload(**overrides) -> dict:
    payload = {
        "legal_name": TEST_DEFAULTS["CONCESSIONAIRE_LEGAL_NAME"],
        "sponsor_equity_commitment_cents": TEST_DEFAULTS[
            "SPONSOR_EQUITY_COMMITMENT_CENTS"
        ],
    }
    payload.update(overrides)
    return payload


def create_concession_payload(concessionaire_id: str, **overrides) -> dict:
    payload = {
        "concessionaire_id": concessionaire_id,
        "project_name": TEST_DEFAULTS["PROJECT_NAME"],
        "masp_cents": TEST_DEFAULTS["MASP_CENTS"],
        "indexation_pct": TEST_DEFAULTS["INDEXATION_PCT"],
        "deduction_cap_pct": TEST_DEFAULTS["DEDUCTION_CAP_PCT"],
        "total_project_cost_cents": TEST_DEFAULTS["TOTAL_PROJECT_COST_CENTS"],
        "senior_debt_committed_cents": TEST_DEFAULTS["SENIOR_DEBT_COMMITTED_CENTS"],
        "equity_committed_cents": TEST_DEFAULTS["EQUITY_COMMITTED_CENTS"],
        "base_case_equity_irr_bps": TEST_DEFAULTS["BASE_CASE_EQUITY_IRR_BPS"],
        "scheduled_service_commencement": TEST_DEFAULTS[
            "SCHEDULED_SERVICE_COMMENCEMENT"
        ],
        "ld_daily_rate_cents": TEST_DEFAULTS["LD_DAILY_RATE_CENTS"],
        "ld_cap_cents": TEST_DEFAULTS["LD_CAP_CENTS"],
        "lifecycle_reserve_target_cents": TEST_DEFAULTS[
            "LIFECYCLE_RESERVE_TARGET_CENTS"
        ],
    }
    payload.update(overrides)
    return payload


def amend_concession_payload(**fields) -> dict:
    """A partial amendment body: only the commercial parameters the caller names."""
    return dict(fields)


def financial_close_payload(close_date: str, **overrides) -> dict:
    payload = {"close_date": close_date}
    payload.update(overrides)
    return payload


def create_drawdown_milestone_payload(
    milestone_name: str, requested_amount_cents: int, expected_concession_version, **overrides
) -> dict:
    payload = {
        "milestone_name": milestone_name,
        "requested_amount_cents": requested_amount_cents,
        "expected_concession_version": expected_concession_version,
    }
    payload.update(overrides)
    return payload


def approve_milestone_payload(certified_cost_cents: int, **overrides) -> dict:
    payload = {"certified_cost_cents": certified_cost_cents}
    payload.update(overrides)
    return payload


def reject_milestone_payload(rejection_reason: str, **overrides) -> dict:
    payload = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


def certify_service_commencement_payload(actual_commencement_date: str, **overrides) -> dict:
    payload = {"actual_commencement_date": actual_commencement_date}
    payload.update(overrides)
    return payload


def create_service_period_payload(
    period_index: int, period_start: str, period_end: str, **overrides
) -> dict:
    payload = {
        "period_index": period_index,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def create_performance_report_payload(
    unavailable_minutes: int,
    category_a_failures: int,
    category_b_failures: int,
    expected_service_period_version,
    **overrides,
) -> dict:
    payload = {
        "unavailable_minutes": unavailable_minutes,
        "category_a_failures": category_a_failures,
        "category_b_failures": category_b_failures,
        "expected_service_period_version": expected_service_period_version,
    }
    payload.update(overrides)
    return payload


def reject_performance_report_payload(rejection_reason: str, **overrides) -> dict:
    payload = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


def verify_service_period_payload(
    verified_unavailable_minutes: int,
    verified_category_a_failures: int,
    verified_category_b_failures: int,
    **overrides,
) -> dict:
    payload = {
        "verified_unavailable_minutes": verified_unavailable_minutes,
        "verified_category_a_failures": verified_category_a_failures,
        "verified_category_b_failures": verified_category_b_failures,
    }
    payload.update(overrides)
    return payload


def create_deduction_event_payload(deduction_type: str, points: int, **overrides) -> dict:
    payload = {"deduction_type": deduction_type, "points": points}
    payload.update(overrides)
    return payload


def withdraw_deduction_event_payload(withdrawal_reason: str, **overrides) -> dict:
    payload = {"withdrawal_reason": withdrawal_reason}
    payload.update(overrides)
    return payload


def create_dispute_payload(grounds: str, **overrides) -> dict:
    payload = {"grounds": grounds}
    payload.update(overrides)
    return payload


def refer_back_dispute_payload(referred_back_reason: str, **overrides) -> dict:
    payload = {"referred_back_reason": referred_back_reason}
    payload.update(overrides)
    return payload


def resubmit_dispute_payload(grounds: str, **overrides) -> dict:
    payload = {"grounds": grounds}
    payload.update(overrides)
    return payload


def adjudicate_dispute_payload(decision: str, outcome_note: str, **overrides) -> dict:
    payload = {"decision": decision, "outcome_note": outcome_note}
    payload.update(overrides)
    return payload


def pay_service_period_payload(payment_reference: str, **overrides) -> dict:
    payload = {"payment_reference": payment_reference}
    payload.update(overrides)
    return payload


def create_relief_claim_payload(
    claim_type: str,
    event_start: str,
    event_end: str,
    claimed_relief_days: int,
    claimed_cost_cents: int,
    **overrides,
) -> dict:
    payload = {
        "claim_type": claim_type,
        "event_start": event_start,
        "event_end": event_end,
        "claimed_relief_days": claimed_relief_days,
        "claimed_cost_cents": claimed_cost_cents,
    }
    payload.update(overrides)
    return payload


def determine_relief_claim_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_reserve_transaction_payload(
    txn_type: str, amount_cents: int, reason: str, **overrides
) -> dict:
    payload = {"txn_type": txn_type, "amount_cents": amount_cents, "reason": reason}
    payload.update(overrides)
    return payload


def reverse_reserve_transaction_payload(reason: str, **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def handback_survey_payload(
    handback_survey_date: str, handback_rectification_cost_cents: int, **overrides
) -> dict:
    payload = {
        "handback_survey_date": handback_survey_date,
        "handback_rectification_cost_cents": handback_rectification_cost_cents,
    }
    payload.update(overrides)
    return payload


def create_refinancing_event_payload(
    refinancing_date: str,
    new_senior_debt_cents: int,
    outstanding_senior_debt_cents: int,
    refinancing_cost_cents: int,
    **overrides,
) -> dict:
    payload = {
        "refinancing_date": refinancing_date,
        "new_senior_debt_cents": new_senior_debt_cents,
        "outstanding_senior_debt_cents": outstanding_senior_debt_cents,
        "refinancing_cost_cents": refinancing_cost_cents,
    }
    payload.update(overrides)
    return payload


def consent_refinancing_payload(decision: str, expected_concession_version, **overrides) -> dict:
    payload = {
        "decision": decision,
        "expected_concession_version": expected_concession_version,
    }
    payload.update(overrides)
    return payload


def create_enforcement_action_payload(
    action_type: str, trigger_reason: str, effective_date: str, **overrides
) -> dict:
    payload = {
        "action_type": action_type,
        "trigger_reason": trigger_reason,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def cure_enforcement_action_payload(cure_note: str, **overrides) -> dict:
    payload = {"cure_note": cure_note}
    payload.update(overrides)
    return payload


def calculate_compensation_payload(
    termination_date: str, outstanding_senior_debt_cents: int, **overrides
) -> dict:
    payload = {
        "termination_date": termination_date,
        "outstanding_senior_debt_cents": outstanding_senior_debt_cents,
    }
    payload.update(overrides)
    return payload


def settle_enforcement_action_payload(settlement_reference: str, **overrides) -> dict:
    payload = {"settlement_reference": settlement_reference}
    payload.update(overrides)
    return payload
