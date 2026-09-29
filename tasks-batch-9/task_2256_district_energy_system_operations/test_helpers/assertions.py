"""Domain assertions for the District Energy API.

These wrap the generic framework helpers with the rounding discipline and the
envelope rules the PRD states: 2 decimal places for kW, money, percentages and
pressure drops; 3 for MWh and cubic metres per hour; 4 for the fuel
concentration index.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import ENERGY_TOLERANCE, HHI_TOLERANCE, MONEY_TOLERANCE

# ─── Numeric comparisons at the declared precision ──────────────────────────


def assert_money(actual: Any, expected: float, label: str = "amount") -> None:
    """Compare a monetary amount, kW figure, percentage or pressure drop (2 dp)."""
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


assert_kw = assert_money
assert_pct = assert_money


def assert_energy(actual: Any, expected: float, label: str = "energy_mwh") -> None:
    """Compare an MWh energy quantity or a cubic-metres-per-hour flow (3 dp)."""
    assert actual == pytest.approx(expected, abs=ENERGY_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_hhi(actual: Any, expected: float, label: str = "fuel_diversity_hhi") -> None:
    """Compare the fuel concentration index (4 dp)."""
    assert actual == pytest.approx(expected, abs=HHI_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


# ─── Envelope and identity ──────────────────────────────────────────────────


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """The request id starts with ``req_`` and the timestamp is ISO 8601 UTC."""
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp not ISO 8601 UTC: {meta['api_request_timestamp']!r}"
    )


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A living entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at not ISO 8601 UTC: {entity.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at not ISO 8601 UTC: {entity.get('updated_at')!r}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_record(record: Dict[str, Any]) -> None:
    """An append-only record carries only id and created_at — no updated_at, no version."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record.get('id')!r}"
    assert is_iso8601_timestamp(record["created_at"]), (
        f"created_at not ISO 8601 UTC: {record.get('created_at')!r}"
    )
    assert "updated_at" not in record, "append-only record must not carry updated_at"
    assert "version" not in record, "append-only record must not carry version"


# ─── Pagination and ordering ────────────────────────────────────────────────


def assert_pagination_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    """Every list response carries limit, offset, total_count and has_more."""
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"list meta must carry {key}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more: expected {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit
    if offset is not None:
        assert meta["offset"] == offset


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """List results are ordered by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows not in created_at ascending order: {stamps}"


def assert_read_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """The per-meter register-read collection is returned in read_at ascending order."""
    stamps = [row["read_at"] for row in rows]
    assert stamps == sorted(stamps), f"readings not in read_at ascending order: {stamps}"


# ─── Loop posture and counters ──────────────────────────────────────────────


def assert_loop_state(
    loop: Dict[str, Any],
    posture: Optional[str] = None,
    committed_reserved_kw: Optional[float] = None,
    open_isolation_count: Optional[int] = None,
    suspect_segment_count: Optional[int] = None,
    version: Optional[int] = None,
) -> None:
    """Check a loop's posture and its three computed counters."""
    if posture is not None:
        assert loop["posture"] == posture, (
            f"posture: expected {posture}, got {loop['posture']}"
        )
    if committed_reserved_kw is not None:
        assert_money(loop["committed_reserved_kw"], committed_reserved_kw, "committed_reserved_kw")
    if open_isolation_count is not None:
        assert loop["open_isolation_count"] == open_isolation_count, (
            f"open_isolation_count: expected {open_isolation_count}, "
            f"got {loop['open_isolation_count']}"
        )
    if suspect_segment_count is not None:
        assert loop["suspect_segment_count"] == suspect_segment_count, (
            f"suspect_segment_count: expected {suspect_segment_count}, "
            f"got {loop['suspect_segment_count']}"
        )
    if version is not None:
        assert loop["version"] == version, (
            f"loop version: expected {version}, got {loop['version']}"
        )


# ─── Forecast, plan and order ───────────────────────────────────────────────


def assert_forecast_projection(
    forecast: Dict[str, Any],
    coincident_demand_kw: Optional[float] = None,
    projected_energy_mwh: Optional[float] = None,
    contributing_agreement_count: Optional[int] = None,
    forecast_state: Optional[str] = None,
    variant_applied: Optional[str] = None,
) -> None:
    """Check a published forecast's determinants."""
    if coincident_demand_kw is not None:
        assert_money(forecast["coincident_demand_kw"], coincident_demand_kw, "coincident_demand_kw")
    if projected_energy_mwh is not None:
        assert_energy(forecast["projected_energy_mwh"], projected_energy_mwh, "projected_energy_mwh")
    if contributing_agreement_count is not None:
        assert forecast["contributing_agreement_count"] == contributing_agreement_count, (
            f"contributing_agreement_count: expected {contributing_agreement_count}, "
            f"got {forecast['contributing_agreement_count']}"
        )
    if forecast_state is not None:
        assert forecast["forecast_state"] == forecast_state
    if variant_applied is not None:
        assert forecast["variant_applied"] == variant_applied


def assert_plan_metrics(
    plan: Dict[str, Any],
    plan_state: Optional[str] = None,
    allocated_capacity_kw: Optional[float] = None,
    unserved_demand_kw: Optional[float] = None,
    total_dispatch_cost: Optional[float] = None,
    total_emissions_kg: Optional[float] = None,
    reserve_margin_pct: Optional[float] = None,
    fuel_diversity_hhi: Optional[float] = None,
    reviewed_by_user_id: Any = "__unset__",
) -> None:
    """Check a dispatch plan's lifecycle state, roll-ups and resilience metrics."""
    if plan_state is not None:
        assert plan["plan_state"] == plan_state, (
            f"plan_state: expected {plan_state}, got {plan['plan_state']}"
        )
    if allocated_capacity_kw is not None:
        assert_money(plan["allocated_capacity_kw"], allocated_capacity_kw, "allocated_capacity_kw")
    if unserved_demand_kw is not None:
        assert_money(plan["unserved_demand_kw"], unserved_demand_kw, "unserved_demand_kw")
    if total_dispatch_cost is not None:
        assert_money(plan["total_dispatch_cost"], total_dispatch_cost, "total_dispatch_cost")
    if total_emissions_kg is not None:
        assert_money(plan["total_emissions_kg"], total_emissions_kg, "total_emissions_kg")
    if reserve_margin_pct is not None:
        assert_money(plan["reserve_margin_pct"], reserve_margin_pct, "reserve_margin_pct")
    if fuel_diversity_hhi is not None:
        assert_hhi(plan["fuel_diversity_hhi"], fuel_diversity_hhi)
    if reviewed_by_user_id != "__unset__":
        assert plan["reviewed_by_user_id"] == reviewed_by_user_id, (
            f"reviewed_by_user_id: expected {reviewed_by_user_id!r}, "
            f"got {plan['reviewed_by_user_id']!r}"
        )


def assert_dispatch_order(
    order: Dict[str, Any],
    asset_id: Optional[str] = None,
    merit_rank: Optional[int] = None,
    allocated_kw: Optional[float] = None,
    block_energy_mwh: Optional[float] = None,
    discharged_kwh: Optional[float] = None,
    order_cost: Optional[float] = None,
    order_emissions_kg: Optional[float] = None,
) -> None:
    """Check one dispatch order's rank, allocation and energy figures."""
    if asset_id is not None:
        assert order["asset_id"] == asset_id, (
            f"asset_id: expected {asset_id}, got {order['asset_id']}"
        )
    if merit_rank is not None:
        assert order["merit_rank"] == merit_rank, (
            f"merit_rank: expected {merit_rank}, got {order['merit_rank']}"
        )
    if allocated_kw is not None:
        assert_money(order["allocated_kw"], allocated_kw, "allocated_kw")
    if block_energy_mwh is not None:
        assert_energy(order["block_energy_mwh"], block_energy_mwh, "block_energy_mwh")
    if discharged_kwh is not None:
        assert_money(order["discharged_kwh"], discharged_kwh, "discharged_kwh")
    if order_cost is not None:
        assert_money(order["order_cost"], order_cost, "order_cost")
    if order_emissions_kg is not None:
        assert_money(order["order_emissions_kg"], order_emissions_kg, "order_emissions_kg")


def orders_by_rank(orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort a plan's dispatch orders into merit-rank order."""
    return sorted(orders, key=lambda o: o["merit_rank"])


# ─── Segment condition ──────────────────────────────────────────────────────


def assert_segment_condition(
    segment: Dict[str, Any],
    condition: Optional[str] = None,
    leak_risk_score: Optional[float] = None,
    makeup_water_ratio: Optional[float] = None,
    historical_leak_count: Optional[int] = None,
) -> None:
    """Check a buried segment's band, score and revised survey inputs."""
    if condition is not None:
        assert segment["condition"] == condition, (
            f"condition: expected {condition}, got {segment['condition']}"
        )
    if leak_risk_score is not None:
        assert_money(segment["leak_risk_score"], leak_risk_score, "leak_risk_score")
    if makeup_water_ratio is not None:
        assert segment["makeup_water_ratio"] == pytest.approx(makeup_water_ratio, abs=1e-9), (
            f"makeup_water_ratio: expected {makeup_water_ratio}, "
            f"got {segment['makeup_water_ratio']}"
        )
    if historical_leak_count is not None:
        assert segment["historical_leak_count"] == historical_leak_count, (
            f"historical_leak_count: expected {historical_leak_count}, "
            f"got {segment['historical_leak_count']}"
        )


# ─── Agreement and invoice ledgers ──────────────────────────────────────────


def assert_agreement_state(
    agreement: Dict[str, Any],
    contract_state: Optional[str] = None,
    billing_state: Optional[str] = None,
    balance_due: Optional[float] = None,
    billed_demand_ratchet_kw: Optional[float] = None,
) -> None:
    """Check both of an agreement's independent state dimensions and its ledger."""
    if contract_state is not None:
        assert agreement["contract_state"] == contract_state, (
            f"contract_state: expected {contract_state}, got {agreement['contract_state']}"
        )
    if billing_state is not None:
        assert agreement["billing_state"] == billing_state, (
            f"billing_state: expected {billing_state}, got {agreement['billing_state']}"
        )
    if balance_due is not None:
        assert_money(agreement["balance_due"], balance_due, "balance_due")
    if billed_demand_ratchet_kw is not None:
        assert_money(
            agreement["billed_demand_ratchet_kw"],
            billed_demand_ratchet_kw,
            "billed_demand_ratchet_kw",
        )


def assert_invoice_determinants(
    invoice: Dict[str, Any],
    billed_energy_mwh: Optional[float] = None,
    billed_demand_kw: Optional[float] = None,
    load_factor_pct: Optional[float] = None,
    energy_charge: Optional[float] = None,
    demand_charge: Optional[float] = None,
    fixed_charge: Optional[float] = None,
    total_amount: Optional[float] = None,
    minimum_bill_applied: Optional[bool] = None,
    variant_applied: Optional[str] = None,
    invoice_state: Optional[str] = None,
    paid_amount: Optional[float] = None,
) -> None:
    """Check every billing determinant stored on an invoice."""
    if billed_energy_mwh is not None:
        assert_energy(invoice["billed_energy_mwh"], billed_energy_mwh, "billed_energy_mwh")
    if billed_demand_kw is not None:
        assert_money(invoice["billed_demand_kw"], billed_demand_kw, "billed_demand_kw")
    if load_factor_pct is not None:
        assert_money(invoice["load_factor_pct"], load_factor_pct, "load_factor_pct")
    if energy_charge is not None:
        assert_money(invoice["energy_charge"], energy_charge, "energy_charge")
    if demand_charge is not None:
        assert_money(invoice["demand_charge"], demand_charge, "demand_charge")
    if fixed_charge is not None:
        assert_money(invoice["fixed_charge"], fixed_charge, "fixed_charge")
    if total_amount is not None:
        assert_money(invoice["total_amount"], total_amount, "total_amount")
    if minimum_bill_applied is not None:
        assert invoice["minimum_bill_applied"] is minimum_bill_applied, (
            f"minimum_bill_applied: expected {minimum_bill_applied}, "
            f"got {invoice['minimum_bill_applied']}"
        )
    if variant_applied is not None:
        assert invoice["variant_applied"] == variant_applied, (
            f"variant_applied: expected {variant_applied}, got {invoice['variant_applied']}"
        )
    if invoice_state is not None:
        assert invoice["invoice_state"] == invoice_state, (
            f"invoice_state: expected {invoice_state}, got {invoice['invoice_state']}"
        )
    if paid_amount is not None:
        assert_money(invoice["paid_amount"], paid_amount, "paid_amount")


# ─── Expansion economics and climate reporting ──────────────────────────────


def assert_project_economics(
    project: Dict[str, Any],
    project_state: Optional[str] = None,
    selected_diameter_mm: Any = "__unset__",
    design_flow_m3_per_h: Optional[float] = None,
    estimated_capex: Optional[float] = None,
    annual_net_margin: Optional[float] = None,
    npv: Optional[float] = None,
) -> None:
    """Check an expansion project's sizing outputs and twenty-year valuation."""
    if project_state is not None:
        assert project["project_state"] == project_state, (
            f"project_state: expected {project_state}, got {project['project_state']}"
        )
    if selected_diameter_mm != "__unset__":
        if selected_diameter_mm is None:
            assert project["selected_diameter_mm"] is None, (
                f"selected_diameter_mm should be null, got {project['selected_diameter_mm']}"
            )
        else:
            assert float(project["selected_diameter_mm"]) == pytest.approx(
                float(selected_diameter_mm)
            ), (
                f"selected_diameter_mm: expected {selected_diameter_mm}, "
                f"got {project['selected_diameter_mm']}"
            )
    if design_flow_m3_per_h is not None:
        assert_energy(project["design_flow_m3_per_h"], design_flow_m3_per_h, "design_flow_m3_per_h")
    if estimated_capex is not None:
        assert_money(project["estimated_capex"], estimated_capex, "estimated_capex")
    if annual_net_margin is not None:
        assert_money(project["annual_net_margin"], annual_net_margin, "annual_net_margin")
    if npv is not None:
        assert_money(project["npv"], npv, "npv")


def assert_emissions_summary(
    summary: Dict[str, Any],
    contributing_plan_count: Optional[int] = None,
    total_energy_mwh: Optional[float] = None,
    total_emissions_kg: Optional[float] = None,
    delivered_energy_mwh: Optional[float] = None,
    system_efficiency_pct: Optional[float] = None,
    emissions_intensity_kg_per_mwh: Optional[float] = None,
    target_gap_kg_per_mwh: Optional[float] = None,
    climate_goal_status: Optional[str] = None,
) -> None:
    """Check the loop's emissions and efficiency position against the city target."""
    if contributing_plan_count is not None:
        assert summary["contributing_plan_count"] == contributing_plan_count, (
            f"contributing_plan_count: expected {contributing_plan_count}, "
            f"got {summary['contributing_plan_count']}"
        )
    if total_energy_mwh is not None:
        assert_energy(summary["total_energy_mwh"], total_energy_mwh, "total_energy_mwh")
    if total_emissions_kg is not None:
        assert_money(summary["total_emissions_kg"], total_emissions_kg, "total_emissions_kg")
    if delivered_energy_mwh is not None:
        assert_energy(summary["delivered_energy_mwh"], delivered_energy_mwh, "delivered_energy_mwh")
    if system_efficiency_pct is not None:
        assert_money(summary["system_efficiency_pct"], system_efficiency_pct, "system_efficiency_pct")
    if emissions_intensity_kg_per_mwh is not None:
        assert_money(
            summary["emissions_intensity_kg_per_mwh"],
            emissions_intensity_kg_per_mwh,
            "emissions_intensity_kg_per_mwh",
        )
    if target_gap_kg_per_mwh is not None:
        assert_money(
            summary["target_gap_kg_per_mwh"], target_gap_kg_per_mwh, "target_gap_kg_per_mwh"
        )
    if climate_goal_status is not None:
        assert summary["climate_goal_status"] == climate_goal_status, (
            f"climate_goal_status: expected {climate_goal_status}, "
            f"got {summary['climate_goal_status']}"
        )


__all__ = [
    "assert_money",
    "assert_kw",
    "assert_pct",
    "assert_energy",
    "assert_hhi",
    "assert_envelope_meta",
    "assert_common_fields",
    "assert_append_only_record",
    "assert_pagination_meta",
    "assert_created_at_ascending",
    "assert_read_at_ascending",
    "assert_loop_state",
    "assert_forecast_projection",
    "assert_plan_metrics",
    "assert_dispatch_order",
    "orders_by_rank",
    "assert_segment_condition",
    "assert_agreement_state",
    "assert_invoice_determinants",
    "assert_project_economics",
    "assert_emissions_summary",
]
