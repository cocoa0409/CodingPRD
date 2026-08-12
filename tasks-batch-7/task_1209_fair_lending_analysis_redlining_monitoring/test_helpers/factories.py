"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import (
    APPLICATION_DEFAULT,
    BRANCH_DEFAULT,
    MARKET_DEFAULT,
    OFFICER_DEFAULT,
    Q1_2026_END,
    Q1_2026_START,
)

# Monotonic seed so repeated payloads within a test carry distinct descriptive
# fields (credit_score, dates) where the recipe varies them row by row.
_seed = itertools.count(1)


def create_market_payload(**overrides) -> dict:
    defaults = dict(MARKET_DEFAULT)
    defaults.update(overrides)
    return defaults


def create_branch_payload(**overrides) -> dict:
    defaults = dict(BRANCH_DEFAULT)
    defaults.update(overrides)
    return defaults


def create_loan_officer_payload(**overrides) -> dict:
    defaults = dict(OFFICER_DEFAULT)
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = dict(APPLICATION_DEFAULT)
    defaults.update(overrides)
    return defaults


def create_pricing_exception_payload(**overrides) -> dict:
    defaults = {
        "kind": "FEE_WAIVER",
        "requested_rate_bps": 700,
        "justification": "fee concession",
    }
    defaults.update(overrides)
    return defaults


def create_underwriting_override_payload(**overrides) -> dict:
    defaults = {
        "original_decision": "DENY",
        "overridden_decision": "APPROVE",
        "justification": "compensating factors",
    }
    defaults.update(overrides)
    return defaults


def create_peer_benchmark_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-04-01",
        "period_end": "2026-07-01",
        "peer_protected_origination_rate": 0.625,
        "peer_origination_count": 5000,
        "source": "HMDA aggregate 2026",
    }
    defaults.update(overrides)
    return defaults


def create_analysis_run_payload(**overrides) -> dict:
    defaults = {
        "product_type": "CONVENTIONAL",
        "prohibited_basis": "RACE",
        "period_start": Q1_2026_START,
        "period_end": Q1_2026_END,
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(**overrides) -> dict:
    defaults = {"kind": "PRICING_DISPARITY", "notes": "manual"}
    defaults.update(overrides)
    return defaults


def create_matched_pair_review_payload(**overrides) -> dict:
    return dict(overrides)


def create_corrective_action_plan_payload(**overrides) -> dict:
    defaults = {
        "title": "remediation",
        "pool_cents": 10_000,
        "due_date": "2026-06-30",
    }
    defaults.update(overrides)
    return defaults


def create_remediation_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": 100}
    defaults.update(overrides)
    return defaults


def create_self_test_payload(**overrides) -> dict:
    defaults = {"window_start": "2026-01-01", "window_end": "2026-03-31"}
    defaults.update(overrides)
    return defaults


def create_board_report_payload(**overrides) -> dict:
    defaults = {"period_start": Q1_2026_START, "period_end": Q1_2026_END}
    defaults.update(overrides)
    return defaults
