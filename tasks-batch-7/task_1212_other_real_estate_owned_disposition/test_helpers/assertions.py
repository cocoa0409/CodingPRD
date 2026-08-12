"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_money(value, field: str):
    assert isinstance(value, (int, float)) and not isinstance(
        value, bool
    ), f"{field} must be numeric, got {type(value).__name__}"
    # two-decimal precision
    rounded = round(float(value) + 0.0, 2)
    assert (
        abs(float(value) - rounded) < 1e-9
    ), f"{field} must be at 2dp precision, got {value!r}"


def _assert_uuid(value, field: str):
    assert is_valid_uuid(value), f"{field} must be a valid UUID, got {value!r}"


def _assert_iso(value, field: str):
    assert is_iso8601_timestamp(value), f"{field} must be ISO 8601, got {value!r}"


def assert_oreo_property(data: dict):
    _assert_uuid(data.get("id", ""), "id")
    _assert_iso(data.get("created_at", ""), "created_at")
    _assert_iso(data.get("updated_at", ""), "updated_at")
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["county"], str) and data["county"]
    assert data["property_type"] in [
        "RESIDENTIAL",
        "COMMERCIAL",
        "INDUSTRIAL",
        "LAND",
    ]
    _assert_money(data["bpo_value"], "bpo_value")
    _assert_money(data["foreclosure_debt"], "foreclosure_debt")
    _assert_money(data["fair_value_at_acquisition"], "fair_value_at_acquisition")
    _assert_money(data["acquisition_basis"], "acquisition_basis")
    _assert_money(data["carrying_value"], "carrying_value")
    _assert_money(data["capitalized_cost_total"], "capitalized_cost_total")
    _assert_money(data["expensed_cost_total"], "expensed_cost_total")
    if data.get("current_fair_value") is not None:
        _assert_money(data["current_fair_value"], "current_fair_value")
    if data.get("net_realizable_value") is not None:
        _assert_money(data["net_realizable_value"], "net_realizable_value")
    _assert_money(data["recognized_gain_loss_total"], "recognized_gain_loss_total")
    assert data["lifecycle_status"] in [
        "HELD",
        "MARKETED",
        "UNDER_CONTRACT",
        "DISPOSED",
        "CHARGED_OFF",
    ]
    assert data["appraisal_status"] in [
        "UNAPPRAISED",
        "CURRENT",
        "DUE_SOON",
        "OVERDUE",
    ]
    assert isinstance(data["active_listing_count"], int)
    assert isinstance(data["open_environmental_issue_count"], int)
    assert isinstance(data["open_title_issue_count"], int)
    assert isinstance(data["pending_write_down_count"], int)
    assert isinstance(data["extension_days_approved"], int)


def assert_appraiser(data: dict):
    _assert_uuid(data.get("id", ""), "id")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["coverage_states"], list)
    for st in data["coverage_states"]:
        assert isinstance(st, str) and len(st) == 2
    _assert_money(data["fee_flat"], "fee_flat")
    assert isinstance(data["version"], int)


def assert_broker(data: dict):
    _assert_uuid(data.get("id", ""), "id")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["coverage_states"], list)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    # performance_score may be null (no settled closings) or a 4dp-rounded ratio
    if data.get("performance_score") is not None:
        score = data["performance_score"]
        assert isinstance(score, (int, float))
        rounded = round(float(score), 4)
        assert (
            abs(float(score) - rounded) < 1e-9
        ), f"performance_score must be 4dp, got {score!r}"
    assert isinstance(data["version"], int)


def assert_carrying_cost(data: dict):
    _assert_uuid(data.get("id", ""), "id")
    _assert_uuid(data.get("property_id", ""), "property_id")
    assert data["cost_type"] in [
        "TAXES",
        "INSURANCE",
        "MAINTENANCE",
        "UTILITIES",
        "HOA",
        "CAPITAL_IMPROVEMENT",
    ]
    _assert_money(data["amount"], "amount")
    _assert_iso(data.get("created_at", ""), "created_at")
    # append-only rows: no version, no updated_at
    assert "version" not in data, "CarryingCost must not expose version"
    assert "updated_at" not in data, "CarryingCost must not expose updated_at"


def assert_appraisal(data: dict):
    _assert_uuid(data.get("id", ""), "id")
    _assert_uuid(data.get("property_id", ""), "property_id")
    _assert_uuid(data.get("appraiser_id", ""), "appraiser_id")
    _assert_money(data["appraised_value"], "appraised_value")
    assert data["status"] in ["DRAFT", "SUBMITTED", "CERTIFIED"]
    assert isinstance(data["version"], int)


def assert_write_down(data: dict):
    _assert_uuid(data.get("id", ""), "id")
    _assert_uuid(data.get("property_id", ""), "property_id")
    _assert_money(data["amount"], "amount")
    assert data["reason"] in [
        "MARKET_DECLINE",
        "MEASUREMENT_PERIOD_ADJUSTMENT",
        "REGULATORY_CHARGE_OFF",
    ]
    assert data["status"] in ["PROPOSED", "POSTED", "REJECTED"]
    assert isinstance(data["auto_generated"], bool)
    assert isinstance(data["proposed_by_user_id"], str)
    assert isinstance(data["version"], int)


def assert_listing_agreement(data: dict):
    _assert_uuid(data.get("id", ""), "id")
    _assert_uuid(data.get("property_id", ""), "property_id")
    _assert_uuid(data.get("broker_id", ""), "broker_id")
    _assert_money(data["listing_price"], "listing_price")
    assert data["status"] in ["DRAFT", "ACTIVE", "TERMINATED", "EXPIRED"]
    if data.get("termination_reason") is not None:
        assert data["termination_reason"] in ["MANUAL", "UNDER_CONTRACT", "CHARGE_OFF"]
    assert isinstance(data["version"], int)


def assert_offer(data: dict):
    _assert_uuid(data.get("id", ""), "id")
    _assert_uuid(data.get("property_id", ""), "property_id")
    assert isinstance(data["buyer_name"], str) and data["buyer_name"]
    _assert_money(data["offer_price"], "offer_price")
    _assert_money(data["current_price"], "current_price")
    assert data["financing_type"] in ["CASH", "SELLER_FINANCED"]
    _assert_money(data["earnest_money"], "earnest_money")
    assert data["status"] in [
        "RECEIVED",
        "UNDER_REVIEW",
        "COUNTERED",
        "ACCEPTED",
        "REJECTED",
        "WITHDRAWN",
        "RESCINDED",
        "CLOSED",
    ]
    assert isinstance(data["counter_round"], int)
    assert isinstance(data["version"], int)


def assert_issue_case(data: dict):
    _assert_uuid(data.get("id", ""), "id")
    _assert_uuid(data.get("property_id", ""), "property_id")
    assert data["issue_type"] in ["ENVIRONMENTAL", "TITLE"]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH"]
    assert isinstance(data["description"], str)
    assert data["status"] in ["OPEN", "IN_REMEDIATION", "RESOLVED", "WAIVED"]
    assert isinstance(data["version"], int)


def assert_closing_statement(data: dict):
    _assert_uuid(data.get("id", ""), "id")
    _assert_uuid(data.get("offer_id", ""), "offer_id")
    _assert_uuid(data.get("property_id", ""), "property_id")
    _assert_money(data["contract_price"], "contract_price")
    _assert_money(data["commission_total"], "commission_total")
    _assert_money(data["listing_broker_share"], "listing_broker_share")
    _assert_money(data["selling_broker_share"], "selling_broker_share")
    _assert_money(data["closing_cost_flat"], "closing_cost_flat")
    _assert_money(data["net_proceeds"], "net_proceeds")
    _assert_money(data["carrying_value_at_closing"], "carrying_value_at_closing")
    _assert_money(data["gain_loss"], "gain_loss")
    _assert_money(
        data["recognized_gain_at_settlement"], "recognized_gain_at_settlement"
    )
    _assert_money(data["deferred_gain"], "deferred_gain")
    assert data["status"] in ["DRAFT", "SETTLED", "VOID"]
    assert isinstance(data["version"], int)


def assert_extension_request(data: dict):
    _assert_uuid(data.get("id", ""), "id")
    _assert_uuid(data.get("property_id", ""), "property_id")
    assert isinstance(data["requested_extension_days"], int)
    assert isinstance(data["justification"], str) and data["justification"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "DENIED"]
    assert isinstance(data["version"], int)


def assert_ledger_entry(data: dict):
    _assert_uuid(data.get("id", ""), "id")
    _assert_uuid(data.get("property_id", ""), "property_id")
    assert data["entry_type"] in [
        "ACQUISITION",
        "CARRYING_COST",
        "WRITE_DOWN",
        "CHARGE_OFF",
        "PROCEEDS",
        "GAIN_RECOGNIZED",
        "LOSS_RECOGNIZED",
    ]
    _assert_money(data["amount"], "amount")
    _assert_iso(data.get("created_at", ""), "created_at")
    # append-only rows: no version, no updated_at
    assert "version" not in data, "LedgerEntry must not expose version"
    assert "updated_at" not in data, "LedgerEntry must not expose updated_at"


def assert_approval_tier(data: dict):
    _assert_uuid(data.get("id", ""), "id")
    assert isinstance(data["name"], str) and data["name"]
    _assert_money(data["min_net_proceeds"], "min_net_proceeds")
    if data.get("max_net_proceeds") is not None:
        _assert_money(data["max_net_proceeds"], "max_net_proceeds")
    assert data["required_role"] in ["OREOSpecialist", "CreditOfficer", "OREOCommittee"]
    assert data["required_rank"] in [1, 2, 3]


def assert_property_summary_invariants(data: dict):
    """The carrying-value identity must hold at all times (PRD §3.1, §3.12)."""
    carrying = float(data["carrying_value"])
    basis = float(data["acquisition_basis"])
    cap = float(data["capitalized_cost_total"])
    posted = float(data["posted_write_down_total"])
    assert (
        abs(carrying - (basis + cap - posted)) < 0.01
    ), (
        f"carrying_value identity broken: {carrying} != {basis} + {cap} - {posted}"
    )
    assert isinstance(data["extension_days_approved"], int)
    assert isinstance(data["active_listing_count"], int)
    assert isinstance(data["open_environmental_issue_count"], int)
    assert isinstance(data["open_title_issue_count"], int)
    assert isinstance(data["pending_write_down_count"], int)


def assert_closing_split_consistency(data: dict):
    """listing + selling shares must sum to commission_total (PRD §3.7)."""
    total = float(data["commission_total"])
    listing = float(data["listing_broker_share"])
    selling = float(data["selling_broker_share"])
    assert abs((listing + selling) - total) < 0.005, (
        f"commission split does not sum: {listing} + {selling} != {total}"
    )
