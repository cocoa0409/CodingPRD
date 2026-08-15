"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def assert_market_participant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("company_name"), str) and len(data["company_name"]) > 0
    assert data["credit_rating_tier"] in ["INVESTMENT_GRADE", "BELOW_INVESTMENT_GRADE"]
    assert data["status"] in ["ACTIVE", "MARGIN_CALL", "SUSPENDED"]
    assert isinstance(data["posted_collateral_cents"], int)
    assert isinstance(data["collateral_requirement_cents"], int)
    assert isinstance(data["unsecured_allowance_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int)


def assert_generator_asset(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("market_participant_id", "")), "market_participant_id must be UUID"
    assert isinstance(data.get("unit_name"), str) and len(data["unit_name"]) > 0
    assert isinstance(data.get("pricing_node"), str) and len(data["pricing_node"]) > 0
    assert isinstance(data["capacity_mw"], (int, float)) and data["capacity_mw"] > 0
    assert isinstance(data["availability_mw"], (int, float))
    assert data["status"] in ["AVAILABLE", "ON_OUTAGE", "DECOMMISSIONED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_operating_day(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("market_date"), str)
    assert data["status"] in ["DA_OPEN", "DA_GATED", "RT_COMPLETE", "PRELIM_SETTLED", "FINAL_SETTLED", "CLOSED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_price_node(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("operating_day_id", ""))
    assert isinstance(data.get("node_name"), str) and len(data["node_name"]) > 0


def assert_day_ahead_offer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("operating_day_id", ""))
    assert is_valid_uuid(data.get("generator_asset_id", ""))
    assert isinstance(data["offered_mw"], (int, float)) and data["offered_mw"] > 0
    assert isinstance(data["offer_price_cents_per_mwh"], int)
    assert data["status"] in ["DRAFT", "SUBMITTED", "SUPERSEDED", "EXPIRED", "CLEARED", "NOT_CLEARED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_telemetry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("generator_asset_id", ""))
    assert is_valid_uuid(data.get("operating_day_id", ""))
    assert isinstance(data["interval_index"], int)
    assert isinstance(data["actual_mw"], (int, float))
    assert data["status"] in ["RECORDED", "SUPERSEDED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_outage_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("generator_asset_id", ""))
    assert data["outage_type"] in ["FULL", "PARTIAL"]
    assert isinstance(data["derate_pct"], int)
    assert isinstance(data["start_at"], str)
    assert isinstance(data["end_at"], str)
    assert isinstance(data["reason"], str)
    assert data["status"] in ["SUBMITTED", "ACKNOWLEDGED", "APPROVED", "DENIED", "CANCELLED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_settlement_statement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("market_participant_id", ""))
    assert is_valid_uuid(data.get("operating_day_id", ""))
    assert data["run_type"] in ["PRELIMINARY", "FINAL", "RESETTLEMENT"]
    assert data["status"] in ["ISSUED", "UNDER_DISPUTE", "SUPERSEDED", "CLOSED", "PAID"]
    assert isinstance(data["da_energy_credit_cents"], int)
    assert isinstance(data["imbalance_charge_cents"], int)
    assert isinstance(data["congestion_charge_cents"], int)
    assert isinstance(data["loss_charge_cents"], int)
    assert isinstance(data["ancillary_revenue_cents"], int)
    assert isinstance(data["capacity_charge_cents"], int)
    assert isinstance(data["net_amount_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_settlement_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("settlement_statement_id", ""))
    assert is_valid_uuid(data.get("generator_asset_id", ""))
    assert data["charge_type"] in ["DA_ENERGY_CREDIT", "RT_IMBALANCE", "CONGESTION", "LOSSES", "ANCILLARY", "CAPACITY"]
    assert isinstance(data["mw_quantity"], (int, float))
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_settlement_dispute(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("settlement_statement_id", ""))
    assert is_valid_uuid(data.get("market_participant_id", ""))
    assert data["dispute_reason"] in ["PRICE_ERROR", "METER_DATA_ERROR", "CALCULATION_ERROR", "MISSING_ANCILLARY_CREDIT"]
    assert isinstance(data["disputed_line_ids"], list)
    assert data["status"] in ["FILED", "UNDER_REVIEW", "UPHELD", "REJECTED", "WITHDRAWN"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_ancillary_award(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("generator_asset_id", ""))
    assert is_valid_uuid(data.get("operating_day_id", ""))
    assert data["service_type"] in ["REGULATION", "SYNC_RESERVE", "SUPPLEMENTAL_RESERVE"]
    assert isinstance(data["awarded_mw"], (int, float)) and data["awarded_mw"] > 0
    assert isinstance(data["capacity_price_cents"], int)
    assert isinstance(data["start_interval"], int)
    assert isinstance(data["end_interval"], int)
    assert data["status"] in ["AWARDED", "SETTLED", "CANCELLED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_capacity_obligation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("generator_asset_id", ""))
    assert isinstance(data.get("delivery_period"), str)
    assert isinstance(data["obligated_mw"], (int, float)) and data["obligated_mw"] > 0
    assert isinstance(data["capacity_rate_cents_per_mw"], int)
    assert isinstance(data["accrued_penalty_cents"], int)
    assert isinstance(data["accrued_bonus_cents"], int)
    assert data["status"] in ["ACTIVE", "AT_RISK", "CLOSED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_capacity_performance_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("operating_day_id", ""))
    assert isinstance(data["start_interval"], int)
    assert isinstance(data["end_interval"], int)
    assert isinstance(data["penalties_collected_cents"], int)
    assert isinstance(data["bonuses_paid_cents"], int)
    assert data["status"] in ["DECLARED", "ACTIVE", "COMPLETED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_collateral_posting(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("market_participant_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["instrument_type"] in ["CASH", "LETTER_OF_CREDIT"]
    assert data["status"] in ["POSTED", "RELEASED", "DRAWN"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_margin_call(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("market_participant_id", ""))
    assert isinstance(data["required_additional_cents"], int)
    assert isinstance(data["due_at"], str)
    assert data["status"] in ["OPEN", "CURED", "DEFAULTED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_participant_credit_invariants(data: dict):
    """Domain invariants that must hold on a MarketParticipant."""
    assert data["posted_collateral_cents"] >= 0, "posted_collateral_cents must be non-negative"
    assert data["collateral_requirement_cents"] >= 0, "collateral_requirement_cents must be non-negative"
    if data["credit_rating_tier"] == "INVESTMENT_GRADE":
        assert data["unsecured_allowance_cents"] == 100000
    else:
        assert data["unsecured_allowance_cents"] == 0


def assert_statement_net_invariant(data: dict):
    """net_amount_cents == congestion + loss + imbalance + capacity - da_credit - ancillary."""
    expected = (
        data["congestion_charge_cents"]
        + data["loss_charge_cents"]
        + data["imbalance_charge_cents"]
        + data["capacity_charge_cents"]
        - data["da_energy_credit_cents"]
        - data["ancillary_revenue_cents"]
    )
    assert data["net_amount_cents"] == expected, (
        f"net_amount_cents {data['net_amount_cents']} != computed {expected}"
    )
