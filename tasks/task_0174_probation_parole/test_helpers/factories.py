"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Only `source: input` fields are emitted; computed
and system fields (status, points, balances, snapshot, ...) are never sent.
"""
from .constants import LSI_R_DOMAINS, TEST_DEFAULTS


# ─── LSI-R domain-score helpers ──────────────────────────────────────────
def domain_scores_uniform(value: int = 1) -> dict:
    """All ten LSI-R domains set to the same value. Sum == 10 * value."""
    return {d: value for d in LSI_R_DOMAINS}


def domain_scores_for_total(total: int) -> dict:
    """Build a valid ten-domain map (all values >= 0) summing to exactly `total`.

    Distributes `total` across the ten domains starting from the first key.
    """
    if total < 0:
        raise ValueError("total must be >= 0")
    scores = {d: 0 for d in LSI_R_DOMAINS}
    remaining = total
    i = 0
    while remaining > 0:
        d = LSI_R_DOMAINS[i % len(LSI_R_DOMAINS)]
        scores[d] += 1
        remaining -= 1
        i += 1
    return scores


# ─── Officer ─────────────────────────────────────────────────────────────
def create_officer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Officer",
        "badge_number": "B-0001",
        "role_type": "PROBATION",
    }
    defaults.update(overrides)
    return defaults


# ─── Supervisee ──────────────────────────────────────────────────────────
def create_supervisee_payload(assigned_officer_id: str, **overrides) -> dict:
    defaults = {
        "full_name": "Test Supervisee",
        "docket_number": "DK-0001",
        "supervision_type": "PROBATION",
        "assigned_officer_id": assigned_officer_id,
        "sentence_state_code": TEST_DEFAULTS["SENTENCE_STATE_CODE"],
        "ordered_term_months": TEST_DEFAULTS["ORDERED_TERM_MONTHS"],
        "supervision_start_date": TEST_DEFAULTS["SUPERVISION_START_DATE"],
    }
    defaults.update(overrides)
    return defaults


# ─── RiskAssessment ──────────────────────────────────────────────────────
def create_risk_assessment_payload(domain_scores: dict = None, **overrides) -> dict:
    defaults = {
        "domain_scores": domain_scores if domain_scores is not None
        else domain_scores_uniform(1),
    }
    defaults.update(overrides)
    return defaults


# ─── SupervisionCondition ────────────────────────────────────────────────
def create_condition_payload(condition_type: str = "CURFEW", **overrides) -> dict:
    defaults = {
        "condition_type": condition_type,
        "description": "Test condition",
    }
    defaults.update(overrides)
    return defaults


# ─── CheckIn ─────────────────────────────────────────────────────────────
def create_check_in_payload(scheduled_for: str, **overrides) -> dict:
    defaults = {
        "scheduled_for": scheduled_for,
    }
    defaults.update(overrides)
    return defaults


# ─── DrugTest ────────────────────────────────────────────────────────────
def create_drug_test_payload(result: str = "NEGATIVE", **overrides) -> dict:
    defaults = {
        "result": result,
    }
    defaults.update(overrides)
    return defaults


# ─── Violation ───────────────────────────────────────────────────────────
def create_violation_payload(violation_class: str, filed_by_officer_id: str,
                             **overrides) -> dict:
    defaults = {
        "violation_class": violation_class,
        "filed_by_officer_id": filed_by_officer_id,
    }
    defaults.update(overrides)
    return defaults


# ─── FinancialObligation ─────────────────────────────────────────────────
def create_obligation_payload(obligation_type: str, principal_cents: int,
                              **overrides) -> dict:
    defaults = {
        "obligation_type": obligation_type,
        "principal_cents": principal_cents,
    }
    defaults.update(overrides)
    return defaults


# ─── Payment ─────────────────────────────────────────────────────────────
def create_payment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


# ─── CourtReport ─────────────────────────────────────────────────────────
def create_court_report_payload(report_type: str = "PROGRESS",
                                as_of_date: str = "2026-01-01T00:00:00.000Z",
                                **overrides) -> dict:
    defaults = {
        "report_type": report_type,
        "as_of_date": as_of_date,
    }
    defaults.update(overrides)
    return defaults


# ─── InterstateTransfer ──────────────────────────────────────────────────
def create_transfer_payload(receiving_state_code: str,
                            expected_supervisee_version: int, **overrides) -> dict:
    defaults = {
        "receiving_state_code": receiving_state_code,
        "expected_supervisee_version": expected_supervisee_version,
    }
    defaults.update(overrides)
    return defaults


# ─── EarlyTermination ────────────────────────────────────────────────────
def create_early_termination_payload(requested_on: str, **overrides) -> dict:
    defaults = {
        "requested_on": requested_on,
    }
    defaults.update(overrides)
    return defaults
