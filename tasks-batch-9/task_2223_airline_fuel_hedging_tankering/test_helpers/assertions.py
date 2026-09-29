"""Domain assertion helpers.

These wrap the tolerances the PRD's rounding discipline implies — cents for
dollars and percentages, four places for prices and ratios, one tenth of a
gallon for a burn penalty — and bundle the field groups that always travel
together, so a test reads as a statement about the business rule rather than a
list of dictionary lookups.
"""

import re
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

_MILLIS_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

from .constants import (
    GALLON_TENTH_TOLERANCE,
    MONEY_TOLERANCE,
    PCT_TOLERANCE,
    PRICE_TOLERANCE,
    RATIO_TOLERANCE,
    SYSTEM_BREACH_JUSTIFICATION,
)

# ─── Numeric tolerances ───────────────────────────────

def assert_money(actual: Any, expected: float, label: str = "amount") -> None:
    """A US-dollar amount, rounded to two decimal places."""
    assert actual is not None, f"{label} is None, expected {expected}"
    assert float(actual) == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_pct(actual: Any, expected: float, label: str = "percentage") -> None:
    """A percentage, rounded to two decimal places."""
    assert actual is not None, f"{label} is None, expected {expected}"
    assert float(actual) == pytest.approx(expected, abs=PCT_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_price(actual: Any, expected: float, label: str = "price") -> None:
    """A per-gallon price, carried to four decimal places."""
    assert actual is not None, f"{label} is None, expected {expected}"
    assert float(actual) == pytest.approx(expected, abs=PRICE_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_ratio(actual: Any, expected: float, label: str = "ratio") -> None:
    """An effectiveness ratio, rounded to four decimal places."""
    assert actual is not None, f"{label} is None, expected {expected}"
    assert float(actual) == pytest.approx(expected, abs=RATIO_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_gallon_tenths(
    actual: Any, expected: float, label: str = "burn penalty gallons"
) -> None:
    """A burn penalty, rounded to one decimal place."""
    assert actual is not None, f"{label} is None, expected {expected}"
    assert float(actual) == pytest.approx(expected, abs=GALLON_TENTH_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_whole_gallons(actual: Any, expected: int, label: str = "gallons") -> None:
    """A whole-gallon quantity such as a consumption basis."""
    assert actual is not None, f"{label} is None, expected {expected}"
    assert float(actual) == pytest.approx(float(expected), abs=0.5), (
        f"{label}: expected {expected}, got {actual}"
    )


# ─── Identity and audit stamps ────────────────────────

def assert_identity_fields(data: Dict[str, Any], label: str = "resource") -> None:
    """`id` is a bare UUID and `created_at` an ISO 8601 UTC instant."""
    assert is_valid_uuid(data.get("id")), (
        f"{label}.id is not a bare UUID: {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at")), (
        f"{label}.created_at is not ISO 8601 UTC: {data.get('created_at')!r}"
    )


def assert_millisecond_timestamp(value: Any, label: str = "timestamp") -> None:
    """An ISO 8601 UTC instant carried with exactly three fractional digits."""
    assert isinstance(value, str) and _MILLIS_TIMESTAMP_RE.match(value), (
        f"{label} must be ISO 8601 UTC with three fractional digits, got {value!r}"
    )


def assert_versioned_resource(
    data: Dict[str, Any], expected_version: Optional[int] = None, label: str = "resource"
) -> None:
    """A resource that carries the full audit quartet."""
    assert_identity_fields(data, label)
    assert is_iso8601_timestamp(data.get("updated_at")), (
        f"{label}.updated_at is not ISO 8601 UTC: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{label}.version must be an integer, got {data.get('version')!r}"
    )
    assert data["version"] >= 1, f"{label}.version must start at 1"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"{label}.version: expected {expected_version}, got {data['version']}"
        )


def assert_immutable_audit_record(data: Dict[str, Any], label: str = "record") -> None:
    """A row carrying only `id` and `created_at` — no `updated_at`, no `version`."""
    assert_identity_fields(data, label)
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def assert_request_meta(body: Dict[str, Any]) -> None:
    """The envelope's `meta` carries a server-minted `req_`-prefixed id."""
    meta = body.get("meta") or {}
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {request_id!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp")), (
        f"meta.api_request_timestamp is not ISO 8601 UTC: "
        f"{meta.get('api_request_timestamp')!r}"
    )


def assert_pagination_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"meta.total_count: expected {total_count}, got {meta['total_count']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, (
            f"meta.limit: expected {limit}, got {meta['limit']}"
        )
    if offset is not None:
        assert meta["offset"] == offset, (
            f"meta.offset: expected {offset}, got {meta['offset']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"meta.has_more: expected {has_more}, got {meta['has_more']}"
        )


# ─── Station supply ledger ────────────────────────────

def assert_station_supply(
    station: Dict[str, Any],
    inventory_gallons: Optional[float] = None,
    effective_inventory_gallons: Optional[float] = None,
    days_cover: Optional[float] = None,
    supply_posture: Optional[str] = None,
) -> None:
    if inventory_gallons is not None:
        assert_money(
            station["inventory_gallons"], inventory_gallons, "inventory_gallons"
        )
    if effective_inventory_gallons is not None:
        assert_money(
            station["effective_inventory_gallons"],
            effective_inventory_gallons,
            "effective_inventory_gallons",
        )
    if days_cover is not None:
        assert_pct(station["days_cover"], days_cover, "days_cover")
    if supply_posture is not None:
        assert station["supply_posture"] == supply_posture, (
            f"supply_posture: expected {supply_posture}, "
            f"got {station['supply_posture']}"
        )


# ─── Counterparty credit ledger ───────────────────────

def assert_counterparty_credit(
    counterparty: Dict[str, Any],
    utilized_credit_usd: Optional[float] = None,
    posted_collateral_usd: Optional[float] = None,
    utilization_pct: Optional[float] = None,
    credit_posture: Optional[str] = None,
    open_margin_call_count: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    if utilized_credit_usd is not None:
        assert_money(
            counterparty["utilized_credit_usd"],
            utilized_credit_usd,
            "utilized_credit_usd",
        )
    if posted_collateral_usd is not None:
        assert_money(
            counterparty["posted_collateral_usd"],
            posted_collateral_usd,
            "posted_collateral_usd",
        )
    if utilization_pct is not None:
        assert_pct(
            counterparty["utilization_pct"], utilization_pct, "utilization_pct"
        )
    if credit_posture is not None:
        assert counterparty["credit_posture"] == credit_posture, (
            f"credit_posture: expected {credit_posture}, "
            f"got {counterparty['credit_posture']}"
        )
    if open_margin_call_count is not None:
        assert counterparty["open_margin_call_count"] == open_margin_call_count, (
            f"open_margin_call_count: expected {open_margin_call_count}, "
            f"got {counterparty['open_margin_call_count']}"
        )
    if status is not None:
        assert counterparty["status"] == status, (
            f"counterparty status: expected {status}, got {counterparty['status']}"
        )


# ─── Programme ledgers ────────────────────────────────

def assert_program_coverage(
    program: Dict[str, Any],
    consumption_basis_gallons: Optional[int] = None,
    hedged_gallons: Optional[float] = None,
    delta_adjusted_gallons: Optional[float] = None,
    coverage_pct_notional: Optional[float] = None,
    coverage_pct_delta: Optional[float] = None,
    planned_coverage_pct_delta: Optional[float] = None,
    open_instrument_count: Optional[int] = None,
) -> None:
    if consumption_basis_gallons is not None:
        assert_whole_gallons(
            program["consumption_basis_gallons"],
            consumption_basis_gallons,
            "consumption_basis_gallons",
        )
    if hedged_gallons is not None:
        assert_money(program["hedged_gallons"], hedged_gallons, "hedged_gallons")
    if delta_adjusted_gallons is not None:
        assert_money(
            program["delta_adjusted_gallons"],
            delta_adjusted_gallons,
            "delta_adjusted_gallons",
        )
    if coverage_pct_notional is not None:
        assert_pct(
            program["coverage_pct_notional"],
            coverage_pct_notional,
            "coverage_pct_notional",
        )
    if coverage_pct_delta is not None:
        assert_pct(
            program["coverage_pct_delta"], coverage_pct_delta, "coverage_pct_delta"
        )
    if planned_coverage_pct_delta is not None:
        assert_pct(
            program["planned_coverage_pct_delta"],
            planned_coverage_pct_delta,
            "planned_coverage_pct_delta",
        )
    if open_instrument_count is not None:
        assert program["open_instrument_count"] == open_instrument_count, (
            f"open_instrument_count: expected {open_instrument_count}, "
            f"got {program['open_instrument_count']}"
        )


def assert_program_accounting(
    program: Dict[str, Any],
    designated_mtm_usd: Optional[float] = None,
    undesignated_mtm_usd: Optional[float] = None,
    earnings_volatility_usd: Optional[float] = None,
    compliance_posture: Optional[str] = None,
) -> None:
    if designated_mtm_usd is not None:
        assert_money(
            program["designated_mtm_usd"], designated_mtm_usd, "designated_mtm_usd"
        )
    if undesignated_mtm_usd is not None:
        assert_money(
            program["undesignated_mtm_usd"],
            undesignated_mtm_usd,
            "undesignated_mtm_usd",
        )
    if earnings_volatility_usd is not None:
        assert_money(
            program["earnings_volatility_usd"],
            earnings_volatility_usd,
            "earnings_volatility_usd",
        )
    if compliance_posture is not None:
        assert program["compliance_posture"] == compliance_posture, (
            f"compliance_posture: expected {compliance_posture}, "
            f"got {program['compliance_posture']}"
        )


# ─── Instrument dimensions ────────────────────────────

def assert_instrument_status(
    instrument: Dict[str, Any],
    trade_status: Optional[str] = None,
    accounting_status: Optional[str] = None,
) -> None:
    if trade_status is not None:
        assert instrument["trade_status"] == trade_status, (
            f"trade_status: expected {trade_status}, "
            f"got {instrument['trade_status']}"
        )
    if accounting_status is not None:
        assert instrument["accounting_status"] == accounting_status, (
            f"accounting_status: expected {accounting_status}, "
            f"got {instrument['accounting_status']}"
        )


def assert_instrument_ledgers(
    instrument: Dict[str, Any],
    mtm_value_usd: Optional[float] = None,
    margin_requirement_usd: Optional[float] = None,
    collateral_posted_usd: Optional[float] = None,
    delta_factor: Optional[float] = None,
    delta_adjusted_gallons: Optional[float] = None,
    cumulative_hedge_change_usd: Optional[float] = None,
    cumulative_item_change_usd: Optional[float] = None,
) -> None:
    if mtm_value_usd is not None:
        assert_money(instrument["mtm_value_usd"], mtm_value_usd, "mtm_value_usd")
    if margin_requirement_usd is not None:
        assert_money(
            instrument["margin_requirement_usd"],
            margin_requirement_usd,
            "margin_requirement_usd",
        )
    if collateral_posted_usd is not None:
        assert_money(
            instrument["collateral_posted_usd"],
            collateral_posted_usd,
            "collateral_posted_usd",
        )
    if delta_factor is not None:
        assert_pct(instrument["delta_factor"], delta_factor, "delta_factor")
    if delta_adjusted_gallons is not None:
        assert_money(
            instrument["delta_adjusted_gallons"],
            delta_adjusted_gallons,
            "delta_adjusted_gallons",
        )
    if cumulative_hedge_change_usd is not None:
        assert_money(
            instrument["cumulative_hedge_change_usd"],
            cumulative_hedge_change_usd,
            "cumulative_hedge_change_usd",
        )
    if cumulative_item_change_usd is not None:
        assert_money(
            instrument["cumulative_item_change_usd"],
            cumulative_item_change_usd,
            "cumulative_item_change_usd",
        )


# ─── Effectiveness tests ──────────────────────────────

def assert_effectiveness_outcome(
    test: Dict[str, Any],
    period_ratio: float,
    cumulative_ratio: float,
    result: str,
) -> None:
    assert_ratio(test["period_ratio"], period_ratio, "period_ratio")
    assert_ratio(test["cumulative_ratio"], cumulative_ratio, "cumulative_ratio")
    assert test["result"] == result, (
        f"result: expected {result}, got {test['result']}"
    )


# ─── Mark-to-market runs ──────────────────────────────

def assert_mtm_totals(
    run: Dict[str, Any],
    instrument_count: Optional[int] = None,
    total_mtm_usd: Optional[float] = None,
    designated_mtm_usd: Optional[float] = None,
    undesignated_mtm_usd: Optional[float] = None,
    margin_calls_created: Optional[int] = None,
    settled_instrument_count: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    if status is not None:
        assert run["status"] == status, (
            f"run status: expected {status}, got {run['status']}"
        )
    if instrument_count is not None:
        assert run["instrument_count"] == instrument_count, (
            f"instrument_count: expected {instrument_count}, "
            f"got {run['instrument_count']}"
        )
    if total_mtm_usd is not None:
        assert_money(run["total_mtm_usd"], total_mtm_usd, "total_mtm_usd")
    if designated_mtm_usd is not None:
        assert_money(
            run["designated_mtm_usd"], designated_mtm_usd, "designated_mtm_usd"
        )
    if undesignated_mtm_usd is not None:
        assert_money(
            run["undesignated_mtm_usd"], undesignated_mtm_usd, "undesignated_mtm_usd"
        )
    if margin_calls_created is not None:
        assert run["margin_calls_created"] == margin_calls_created, (
            f"margin_calls_created: expected {margin_calls_created}, "
            f"got {run['margin_calls_created']}"
        )
    if settled_instrument_count is not None:
        assert run["settled_instrument_count"] == settled_instrument_count, (
            f"settled_instrument_count: expected {settled_instrument_count}, "
            f"got {run['settled_instrument_count']}"
        )


# ─── Tankering directives ─────────────────────────────

def assert_planned_economics(
    directive: Dict[str, Any],
    planned_burn_penalty_gallons: Optional[float] = None,
    planned_gross_savings_usd: Optional[float] = None,
    planned_penalty_cost_usd: Optional[float] = None,
    planned_net_savings_usd: Optional[float] = None,
) -> None:
    if planned_burn_penalty_gallons is not None:
        assert_gallon_tenths(
            directive["planned_burn_penalty_gallons"],
            planned_burn_penalty_gallons,
            "planned_burn_penalty_gallons",
        )
    if planned_gross_savings_usd is not None:
        assert_money(
            directive["planned_gross_savings_usd"],
            planned_gross_savings_usd,
            "planned_gross_savings_usd",
        )
    if planned_penalty_cost_usd is not None:
        assert_money(
            directive["planned_penalty_cost_usd"],
            planned_penalty_cost_usd,
            "planned_penalty_cost_usd",
        )
    if planned_net_savings_usd is not None:
        assert_money(
            directive["planned_net_savings_usd"],
            planned_net_savings_usd,
            "planned_net_savings_usd",
        )


def assert_reconciled_economics(
    directive: Dict[str, Any],
    reconciled_burn_penalty_gallons: Optional[float] = None,
    reconciled_net_savings_usd: Optional[float] = None,
    savings_variance_usd: Optional[float] = None,
) -> None:
    if reconciled_burn_penalty_gallons is not None:
        assert_gallon_tenths(
            directive["reconciled_burn_penalty_gallons"],
            reconciled_burn_penalty_gallons,
            "reconciled_burn_penalty_gallons",
        )
    if reconciled_net_savings_usd is not None:
        assert_money(
            directive["reconciled_net_savings_usd"],
            reconciled_net_savings_usd,
            "reconciled_net_savings_usd",
        )
    if savings_variance_usd is not None:
        assert_money(
            directive["savings_variance_usd"],
            savings_variance_usd,
            "savings_variance_usd",
        )


def assert_pinned_prices(
    directive: Dict[str, Any],
    pinned_origin_price_usd_per_gal: float,
    pinned_destination_price_usd_per_gal: float,
    pinned_origin_contract_ref: str,
) -> None:
    assert_price(
        directive["pinned_origin_price_usd_per_gal"],
        pinned_origin_price_usd_per_gal,
        "pinned_origin_price_usd_per_gal",
    )
    assert_price(
        directive["pinned_destination_price_usd_per_gal"],
        pinned_destination_price_usd_per_gal,
        "pinned_destination_price_usd_per_gal",
    )
    assert directive["pinned_origin_contract_ref"] == pinned_origin_contract_ref, (
        f"pinned_origin_contract_ref: expected {pinned_origin_contract_ref}, "
        f"got {directive['pinned_origin_contract_ref']}"
    )


def assert_nothing_pinned(directive: Dict[str, Any]) -> None:
    """No price was frozen onto this directive."""
    for field in (
        "pinned_origin_price_usd_per_gal",
        "pinned_destination_price_usd_per_gal",
        "pinned_origin_contract_ref",
    ):
        assert directive[field] is None, (
            f"{field} should be null, got {directive[field]!r}"
        )


def assert_nothing_reconciled(directive: Dict[str, Any]) -> None:
    """No flown-data outcome was written onto this directive."""
    for field in (
        "reconciled_burn_penalty_gallons",
        "reconciled_net_savings_usd",
        "savings_variance_usd",
    ):
        assert directive[field] is None, (
            f"{field} should be null, got {directive[field]!r}"
        )


# ─── Policy exceptions ────────────────────────────────

def assert_system_breach_exception(
    exception: Dict[str, Any],
    hedge_program_id: Optional[str] = None,
    hedge_instrument_id: Optional[str] = None,
) -> None:
    """An auto-raised earnings-volatility exception carries no requester."""
    assert exception["origin"] == "SYSTEM_BREACH", (
        f"origin: expected SYSTEM_BREACH, got {exception['origin']}"
    )
    assert exception["reason_code"] == "EARNINGS_VOLATILITY_BREACH", (
        f"reason_code: expected EARNINGS_VOLATILITY_BREACH, "
        f"got {exception['reason_code']}"
    )
    assert exception["status"] == "REQUESTED", (
        f"status: expected REQUESTED, got {exception['status']}"
    )
    assert exception["requested_by_user_id"] is None, (
        "an auto-raised exception must carry a null requested_by_user_id"
    )
    assert exception["justification"] == SYSTEM_BREACH_JUSTIFICATION, (
        f"justification: expected {SYSTEM_BREACH_JUSTIFICATION!r}, "
        f"got {exception['justification']!r}"
    )
    if hedge_program_id is not None:
        assert exception["hedge_program_id"] == hedge_program_id
    if hedge_instrument_id is not None:
        assert exception["hedge_instrument_id"] == hedge_instrument_id


def assert_undecided_exception(exception: Dict[str, Any]) -> None:
    assert exception["status"] == "REQUESTED", (
        f"status: expected REQUESTED, got {exception['status']}"
    )
    assert exception["decided_by_user_id"] is None, (
        f"decided_by_user_id should be null, got {exception['decided_by_user_id']!r}"
    )
    assert exception["decided_at"] is None, (
        f"decided_at should be null, got {exception['decided_at']!r}"
    )


# ─── Collections ──────────────────────────────────────

def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]
