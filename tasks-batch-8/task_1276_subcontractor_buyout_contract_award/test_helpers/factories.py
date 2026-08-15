"""Payload factories — one per entity, input fields only.

Defaults match the PRD's rules: the project logical clock starts at
2026-05-01T00:00:00Z, so bid_due_at defaults strictly after it and
bid_received_at defaults before it.
"""
from .constants import TEST_DEFAULTS


UNLIMITED_OM_TIERS = [
    {"max_value_cents": -1, "max_cumulative_pct": -1, "roles": ["OperationsManager"]},
]


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Project",
        "project_number": "TP-0001",
        "estimated_budget_cents": TEST_DEFAULTS["PROJECT_BUDGET_CENTS"],
        "buyout_target_savings_pct": 0.05,
    }
    defaults.update(overrides)
    return defaults


def create_trade_package_payload(expected_project_version, **overrides) -> dict:
    defaults = {
        "trade_code": "26-ELEC",
        "title": "Electrical",
        "estimated_budget_cents": TEST_DEFAULTS["PACKAGE_BUDGET_CENTS"],
        "budgeted_contingency_cents": 0,
        "spec_section": "26 00 00",
        "bid_due_at": TEST_DEFAULTS["BID_DUE_AT"],
        "bonding_policy": "WAIVED",
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(**overrides) -> dict:
    defaults = {
        "bidder_name": "Acme Electric",
        "contact_email": "bids@acme.example.com",
        "base_bid_cents": 9_000_000,
        "bid_received_at": TEST_DEFAULTS["BID_RECEIVED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_gap_payload(**overrides) -> dict:
    defaults = {
        "category": "SCOPE",
        "description": "gap discovered during leveling",
        "estimated_impact_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_subcontract_payload(source_bid_id, **overrides) -> dict:
    defaults = {
        "subcontractor_name": "Acme Electric",
        "source_bid_id": source_bid_id,
        "flow_down_terms": "prime contract flow-downs v1",
        "payment_terms": {"retainage_pct": 0.10, "pay_if_paid": True},
        "change_authority_limits": [dict(t) for t in UNLIMITED_OM_TIERS],
    }
    defaults.update(overrides)
    return defaults


def recommend_award_payload(**overrides) -> dict:
    defaults = {"contract_value_cents": 9_000_000}
    defaults.update(overrides)
    return defaults


def create_insurance_certificate_payload(**overrides) -> dict:
    """Fully compliant certificate under the default requirements snapshot."""
    defaults = {
        "certificate_number": "CERT-0001",
        "gl_occurrence_cents": 1_000_000,
        "gl_aggregate_cents": 2_000_000,
        "auto_cents": 1_000_000,
        "umbrella_cents": 5_000_000,
        "workers_comp": "STATUTORY",
        "ai_endorsed": True,
        "wos_endorsed": True,
        "ptd_endorsed": True,
        "pollution_cents": 0,
        "expires_on": TEST_DEFAULTS["CERT_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_bond_decision_payload(**overrides) -> dict:
    defaults = {"trade_history": "CLEAN"}
    defaults.update(overrides)
    return defaults


def create_sov_payload(**overrides) -> dict:
    defaults = {
        "lines": [{"wbs_code": "01", "description": "All work", "weight_numerator": 1}],
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(**overrides) -> dict:
    defaults = {"description": "change order", "amount_cents": 100_000}
    defaults.update(overrides)
    return defaults
