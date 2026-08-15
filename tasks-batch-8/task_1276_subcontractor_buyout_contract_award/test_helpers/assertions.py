"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            f"{entity}.updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_project(data: dict):
    _assert_common_fields(data, "Project")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["project_number"], str) and data["project_number"]
    assert isinstance(data["estimated_budget_cents"], int)
    assert isinstance(data["buyout_target_savings_pct"], (int, float))
    assert data["status"] in ["SETUP", "BUYOUT_OPEN", "BUYOUT_COMPLETE"]
    assert is_iso8601_timestamp(data.get("current_time_utc", "")), \
        "current_time_utc must be ISO 8601"


def assert_trade_package(data: dict):
    _assert_common_fields(data, "TradePackage")
    assert isinstance(data["trade_code"], str) and data["trade_code"]
    assert isinstance(data["estimated_budget_cents"], int)
    assert isinstance(data["budgeted_contingency_cents"], int)
    assert data["bonding_policy"] in ["REQUIRED", "PER_TRADE_RISK", "WAIVED"]
    assert data["status"] in [
        "DRAFT", "PUBLISHED", "UNDER_LEVELING", "BUYOUT_IN_PROGRESS", "AWARDED",
    ]
    assert isinstance(data["awarded_value_cents"], int)
    assert isinstance(data["buyout_savings_cents"], int)
    assert data["buyout_posture"] in ["FAVORABLE", "NEUTRAL", "UNFAVORABLE"]


def assert_bid(data: dict):
    _assert_common_fields(data, "Bid")
    assert isinstance(data["bidder_name"], str) and data["bidder_name"]
    assert isinstance(data["base_bid_cents"], int)
    assert isinstance(data["leveled_value_cents"], int)
    assert data["status"] in ["RECEIVED", "PLACED", "WITHDRAWN", "AWARDED"]


def assert_scope_gap(data: dict):
    _assert_common_fields(data, "ScopeGap")
    assert data["category"] in [
        "SCOPE", "ALLOWANCE", "ALTERNATE", "INSURANCE_EXCLUSION", "LIFE_SAFETY",
    ]
    assert data["status"] in ["OPEN", "RESOLVED", "DEFERRED"]


def assert_subcontract(data: dict):
    _assert_common_fields(data, "Subcontract")
    assert isinstance(data["subcontractor_name"], str) and data["subcontractor_name"]
    assert isinstance(data["contract_value_cents"], int)
    assert isinstance(data["cumulative_co_cents"], int)
    assert isinstance(data["negotiation_round"], int)
    assert data["insurance_status"] in [
        "MISSING", "COMPLIANT", "NON_COMPLIANT", "EXPIRED_CERT_ONLY",
    ]
    assert data["bonding_requirement"] in [
        "NOT_REQUIRED", "SURETY_BOND", "SUBGUARD", "PENDING_DECISION",
    ]
    assert data["sov_status"] in ["DRAFT", "BALANCED", "APPROVED", "REJECTED"]
    assert data["status"] in [
        "DRAFT", "PENDING_AWARD", "AWARDED", "ISSUED", "EXECUTED",
        "DEFAULTED", "REPLACED", "TERMINATED",
    ]


def assert_negotiation_round(data: dict):
    """Append-only record: id + created_at, and no updated_at/version keys."""
    assert is_valid_uuid(data.get("id", "")), "NegotiationRound.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "NegotiationRound.created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"
    assert isinstance(data["round_index"], int)
    assert isinstance(data["proposed_value_cents"], int)


def assert_insurance_certificate(data: dict):
    _assert_common_fields(data, "InsuranceCertificate")
    assert isinstance(data["certificate_number"], str) and data["certificate_number"]
    assert data["workers_comp"] in ["STATUTORY", "EXCESS_LIMIT"]
    assert data["compliance_verdict"] in [
        "COMPLIANT", "NON_COMPLIANT", "COMPLIANT_BY_GAP_ANALYSIS",
    ]
    assert data["status"] in ["ISSUED", "EXPIRED", "SUPERSEDED"]


def assert_bond_decision(data: dict):
    _assert_common_fields(data, "BondDecision")
    assert isinstance(data["trade_risk_score"], int)
    assert data["trade_history"] in ["CLEAN", "CLAIMS"]
    assert data["decision"] in ["SURETY_BOND", "SUBGUARD", "NOT_REQUIRED"]
    assert isinstance(data["premium_cents"], int)


def assert_sov(data: dict):
    _assert_common_fields(data, "ScheduleOfValues")
    assert isinstance(data["revision_number"], int)
    assert isinstance(data["lines"], list)
    assert data["status"] in ["DRAFT", "BALANCED", "REJECTED", "REVISED", "APPROVED"]


def assert_change_order(data: dict):
    _assert_common_fields(data, "ChangeOrder")
    assert isinstance(data["description"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in [
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "VOIDED",
    ]


def assert_sov_lines_balance(sov: dict, contract_value_cents: int):
    """The per-line allocated amounts must sum exactly to the contract value."""
    total = sum(line["allocated_amount_cents"] for line in sov["lines"])
    assert total == contract_value_cents, (
        f"SOV allocation must balance to contract value: "
        f"lines sum to {total}, expected {contract_value_cents}"
    )
