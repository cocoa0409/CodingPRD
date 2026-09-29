"""Domain assertion helpers.

These wrap the repetitive multi-field checks the suite makes over and over:
the four bookkeeping fields, the forecasting chain on one interval plan, the
coverage picture, the outsourcing picture, the two shift state axes, the agent
coaching rollup, the cycle ledgers and the three settlement amounts.

Ratio-scaled fields are compared with a tolerance tighter than the fourth
decimal place; hour- and full-time-equivalent-scaled fields with a tolerance
tighter than the second.
"""

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import COMMON_FIELDS, COVERAGE_SUMMARY_FIELDS

RATIO_TOLERANCE = 1e-9
HOURS_TOLERANCE = 1e-9


# ─── Structural ───────────────────────────────────────

def assert_declared_fields(data, field_names):
    """Assert every field name in the inventory is present in the payload."""
    missing = [name for name in field_names if name not in data]
    assert not missing, f"Response is missing declared fields: {missing}"


def assert_common_fields(data):
    """Assert the id, both timestamps and the version counter are well formed."""
    assert_declared_fields(data, COMMON_FIELDS)
    assert is_valid_uuid(data["id"]), f"id is not a bare UUID: {data['id']!r}"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at is not an ISO 8601 UTC timestamp: {data['created_at']!r}"
    )
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at is not an ISO 8601 UTC timestamp: {data['updated_at']!r}"
    )
    assert isinstance(data["version"], int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_no_bookkeeping_fields(data):
    """Assert a derived view carries none of the persisted-row fields."""
    for name in COMMON_FIELDS:
        assert name not in data, (
            f"A derived view must not carry the persisted field {name!r}"
        )


def assert_coverage_summary_shape(data):
    """Assert the cycle rollup carries exactly its ten declared keys."""
    assert_declared_fields(data, COVERAGE_SUMMARY_FIELDS)
    assert_no_bookkeeping_fields(data)
    assert set(data.keys()) == set(COVERAGE_SUMMARY_FIELDS), (
        f"Unexpected keys on the rollup: "
        f"{sorted(set(data.keys()) ^ set(COVERAGE_SUMMARY_FIELDS))}"
    )


# ─── Scale-aware numeric comparison ───────────────────

def assert_ratio(actual, expected, label="ratio"):
    """Compare a four-decimal ratio, rate, percentage or multiplier."""
    assert actual == pytest.approx(expected, abs=RATIO_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_hours(actual, expected, label="hours"):
    """Compare a two-decimal hour or full-time-equivalent quantity."""
    assert actual == pytest.approx(expected, abs=HOURS_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_cents(actual, expected, label="cents"):
    """Compare an integer monetary amount in cents."""
    assert isinstance(actual, int), f"{label} must be an integer number of cents"
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


# ─── Interval plan ────────────────────────────────────

def assert_interval_forecast(
    interval,
    volume_forecast=None,
    aht_forecast_seconds=None,
    applied_event_uplift_pct=None,
    required_service_level=None,
    required_occupancy_capped=None,
    required_agents=None,
):
    """Assert the forecasting and requirement chain on one interval plan."""
    if volume_forecast is not None:
        assert interval["volume_forecast"] == volume_forecast, (
            f"volume_forecast: expected {volume_forecast}, "
            f"got {interval['volume_forecast']}"
        )
    if aht_forecast_seconds is not None:
        assert interval["aht_forecast_seconds"] == aht_forecast_seconds, (
            f"aht_forecast_seconds: expected {aht_forecast_seconds}, "
            f"got {interval['aht_forecast_seconds']}"
        )
    if applied_event_uplift_pct is not None:
        assert_ratio(
            interval["applied_event_uplift_pct"],
            applied_event_uplift_pct,
            "applied_event_uplift_pct",
        )
    if required_service_level is not None:
        assert interval["required_service_level"] == required_service_level, (
            f"required_service_level: expected {required_service_level}, "
            f"got {interval['required_service_level']}"
        )
    if required_occupancy_capped is not None:
        assert interval["required_occupancy_capped"] == required_occupancy_capped, (
            f"required_occupancy_capped: expected {required_occupancy_capped}, "
            f"got {interval['required_occupancy_capped']}"
        )
    if required_agents is not None:
        assert interval["required_agents"] == required_agents, (
            f"required_agents: expected {required_agents}, "
            f"got {interval['required_agents']}"
        )


def assert_interval_coverage(
    interval,
    scheduled_agents=None,
    routing_inflow_agents=None,
    routing_outflow_agents=None,
    effective_scheduled_agents=None,
    coverage_gap=None,
    coverage_state=None,
):
    """Assert the supply-side coverage picture on one interval plan."""
    for field, expected in (
        ("scheduled_agents", scheduled_agents),
        ("routing_inflow_agents", routing_inflow_agents),
        ("routing_outflow_agents", routing_outflow_agents),
        ("effective_scheduled_agents", effective_scheduled_agents),
        ("coverage_gap", coverage_gap),
        ("coverage_state", coverage_state),
    ):
        if expected is not None:
            assert interval[field] == expected, (
                f"{field}: expected {expected}, got {interval[field]}"
            )


def assert_interval_outsourcing(
    interval,
    internal_capacity_volume=None,
    allocatable_volume=None,
    partner_committed_volume=None,
    unserved_volume=None,
):
    """Assert the absorbable-and-unserved volume picture on one interval plan."""
    for field, expected in (
        ("internal_capacity_volume", internal_capacity_volume),
        ("allocatable_volume", allocatable_volume),
        ("partner_committed_volume", partner_committed_volume),
        ("unserved_volume", unserved_volume),
    ):
        if expected is not None:
            assert interval[field] == expected, (
                f"{field}: expected {expected}, got {interval[field]}"
            )


# ─── Schedule shift ───────────────────────────────────

def assert_shift_axes(shift, publication_status=None, adherence_status=None):
    """Assert the observable state of a shift: the pair of its two axes."""
    if publication_status is not None:
        assert shift["publication_status"] == publication_status, (
            f"publication_status: expected {publication_status}, "
            f"got {shift['publication_status']}"
        )
    if adherence_status is not None:
        assert shift["adherence_status"] == adherence_status, (
            f"adherence_status: expected {adherence_status}, "
            f"got {shift['adherence_status']}"
        )


def assert_shift_hours(
    shift,
    scheduled_seconds=None,
    paid_hours=None,
    ot_hours=None,
    vto_hours=None,
    end_at=None,
):
    """Assert a shift's span, its paid hours and its two hour rollups."""
    if scheduled_seconds is not None:
        assert shift["scheduled_seconds"] == scheduled_seconds, (
            f"scheduled_seconds: expected {scheduled_seconds}, "
            f"got {shift['scheduled_seconds']}"
        )
    if paid_hours is not None:
        assert_hours(shift["paid_hours"], paid_hours, "paid_hours")
    if ot_hours is not None:
        assert_hours(shift["ot_hours"], ot_hours, "ot_hours")
    if vto_hours is not None:
        assert_hours(shift["vto_hours"], vto_hours, "vto_hours")
    if end_at is not None:
        assert_instant_equals(shift["end_at"], end_at, "end_at")


def assert_shift_adherence(
    shift,
    out_of_adherence_seconds=None,
    excused_seconds=None,
    adherence_pct=None,
    flagged_by_user_id=...,
):
    """Assert a shift's adherence arithmetic and its stored flagging identity."""
    if out_of_adherence_seconds is not None:
        assert shift["out_of_adherence_seconds"] == out_of_adherence_seconds, (
            f"out_of_adherence_seconds: expected {out_of_adherence_seconds}, "
            f"got {shift['out_of_adherence_seconds']}"
        )
    if excused_seconds is not None:
        assert shift["excused_seconds"] == excused_seconds, (
            f"excused_seconds: expected {excused_seconds}, "
            f"got {shift['excused_seconds']}"
        )
    if adherence_pct is not None:
        assert_ratio(shift["adherence_pct"], adherence_pct, "shift adherence_pct")
    if flagged_by_user_id is not ...:
        assert shift["flagged_by_user_id"] == flagged_by_user_id, (
            f"flagged_by_user_id: expected {flagged_by_user_id}, "
            f"got {shift['flagged_by_user_id']}"
        )


# ─── Agent ────────────────────────────────────────────

def assert_agent_coaching(
    agent, adherence_pct=None, coaching_flag_count=None, coaching_status=None
):
    """Assert the agent-level adherence rollup and the coaching ratchet."""
    if adherence_pct is not None:
        assert_ratio(agent["adherence_pct"], adherence_pct, "agent adherence_pct")
    if coaching_flag_count is not None:
        assert agent["coaching_flag_count"] == coaching_flag_count, (
            f"coaching_flag_count: expected {coaching_flag_count}, "
            f"got {agent['coaching_flag_count']}"
        )
    if coaching_status is not None:
        assert agent["coaching_status"] == coaching_status, (
            f"coaching_status: expected {coaching_status}, "
            f"got {agent['coaching_status']}"
        )


def assert_agent_hours(agent, scheduled_hours_committed):
    """Assert the agent's committed scheduled-hours ledger."""
    assert_hours(
        agent["scheduled_hours_committed"],
        scheduled_hours_committed,
        "scheduled_hours_committed",
    )


# ─── Planning cycle ───────────────────────────────────

def assert_cycle_ledgers(
    cycle,
    posture=None,
    short_interval_count=None,
    total_scheduled_hours=None,
    ot_spend_committed_cents=None,
    ot_hours_committed=None,
    headcount_active=None,
    pipeline_fte=None,
    reforecast_generation=None,
    version=None,
):
    """Assert the cycle's posture and every derived aggregate under test."""
    if posture is not None:
        assert cycle["posture"] == posture, (
            f"posture: expected {posture}, got {cycle['posture']}"
        )
    if short_interval_count is not None:
        assert cycle["short_interval_count"] == short_interval_count, (
            f"short_interval_count: expected {short_interval_count}, "
            f"got {cycle['short_interval_count']}"
        )
    if total_scheduled_hours is not None:
        assert_hours(
            cycle["total_scheduled_hours"], total_scheduled_hours, "total_scheduled_hours"
        )
    if ot_spend_committed_cents is not None:
        assert_cents(
            cycle["ot_spend_committed_cents"],
            ot_spend_committed_cents,
            "ot_spend_committed_cents",
        )
    if ot_hours_committed is not None:
        assert_hours(
            cycle["ot_hours_committed"], ot_hours_committed, "ot_hours_committed"
        )
    if headcount_active is not None:
        assert cycle["headcount_active"] == headcount_active, (
            f"headcount_active: expected {headcount_active}, "
            f"got {cycle['headcount_active']}"
        )
    if pipeline_fte is not None:
        assert_hours(cycle["pipeline_fte"], pipeline_fte, "pipeline_fte")
    if reforecast_generation is not None:
        assert cycle["reforecast_generation"] == reforecast_generation, (
            f"reforecast_generation: expected {reforecast_generation}, "
            f"got {cycle['reforecast_generation']}"
        )
    if version is not None:
        assert cycle["version"] == version, (
            f"cycle version: expected {version}, got {cycle['version']}"
        )


# ─── Outsourced partner and allocation ────────────────

def assert_partner_ledgers(
    partner,
    status=None,
    rolling_sl_attainment_pct=...,
    consecutive_breach_count=None,
    committed_volume_outstanding=None,
    invoice_total_cents=None,
    performance_report_count=None,
    version=None,
):
    """Assert the partner's eligibility ladder and its two ledgers."""
    if status is not None:
        assert partner["status"] == status, (
            f"partner status: expected {status}, got {partner['status']}"
        )
    if rolling_sl_attainment_pct is not ...:
        if rolling_sl_attainment_pct is None:
            assert partner["rolling_sl_attainment_pct"] is None, (
                "rolling_sl_attainment_pct should still be null"
            )
        else:
            assert_ratio(
                partner["rolling_sl_attainment_pct"],
                rolling_sl_attainment_pct,
                "rolling_sl_attainment_pct",
            )
    if consecutive_breach_count is not None:
        assert partner["consecutive_breach_count"] == consecutive_breach_count, (
            f"consecutive_breach_count: expected {consecutive_breach_count}, "
            f"got {partner['consecutive_breach_count']}"
        )
    if committed_volume_outstanding is not None:
        assert partner["committed_volume_outstanding"] == committed_volume_outstanding, (
            f"committed_volume_outstanding: expected {committed_volume_outstanding}, "
            f"got {partner['committed_volume_outstanding']}"
        )
    if invoice_total_cents is not None:
        assert_cents(
            partner["invoice_total_cents"], invoice_total_cents, "invoice_total_cents"
        )
    if performance_report_count is not None:
        assert partner["performance_report_count"] == performance_report_count, (
            f"performance_report_count: expected {performance_report_count}, "
            f"got {partner['performance_report_count']}"
        )
    if version is not None:
        assert partner["version"] == version, (
            f"partner version: expected {version}, got {partner['version']}"
        )


def assert_settlement_amounts(
    allocation,
    settlement_floor_cents=None,
    settlement_delivered_cents=None,
    shortfall_penalty_cents=None,
    settlement_amount_cents=None,
):
    """Assert all three computed amounts plus the authoritative payable."""
    for field, expected in (
        ("settlement_floor_cents", settlement_floor_cents),
        ("settlement_delivered_cents", settlement_delivered_cents),
        ("shortfall_penalty_cents", shortfall_penalty_cents),
        ("settlement_amount_cents", settlement_amount_cents),
    ):
        if expected is not None:
            assert_cents(allocation[field], expected, field)


def assert_settlement_fields_null(allocation):
    """Assert an unsettled allocation carries no settlement figures at all."""
    for field in (
        "delivered_volume",
        "settlement_floor_cents",
        "settlement_delivered_cents",
        "shortfall_penalty_cents",
        "settlement_amount_cents",
    ):
        assert allocation[field] is None, f"{field} should still be null"


# ─── Instant comparison ───────────────────────────────

def normalize_instant(value):
    """Normalise an ISO 8601 UTC instant so fractional seconds do not matter."""
    assert isinstance(value, str), f"Expected an ISO 8601 instant, got {value!r}"
    text = value[:-1] if value.endswith("Z") else value
    if "." in text:
        head, frac = text.split(".", 1)
        frac = frac.rstrip("0")
        text = head if not frac else f"{head}.{frac}"
    return text


def assert_instant_equals(actual, expected, label="instant"):
    """Assert two ISO 8601 UTC instants name the same moment."""
    assert is_iso8601_timestamp(actual), (
        f"{label} is not an ISO 8601 UTC timestamp: {actual!r}"
    )
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )
