"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3).

Assert helpers validate the fields the PRD guarantees on each resource.
Append-only event types (metric readings, posture snapshots, intraday
snapshots) MUST NOT carry updated_at or version (PRD §2.5).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import HAIRCUT_BPS, POSTURE_ORDINAL


# ---------------------------------------------------------------------------
# Shared field helpers
# ---------------------------------------------------------------------------

def _assert_common_fields(data: dict):
    """PRD §2.5: id (server-minted UUID), created_at, updated_at, integer version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"version must be int, got {data.get('version')!r}"


def _assert_event_fields(data: dict):
    """PRD §2.5: append-only event types carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only event must not carry updated_at"
    assert "version" not in data, "append-only event must not carry version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_stress_scenario(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["tier"] in ("BASELINE", "MODERATE", "SEVERE")
    assert isinstance(data["deposit_runoff_pct"], int)
    assert isinstance(data["wholesale_renewal_pct"], int)
    assert isinstance(data["level2_addon_bps"], int)
    assert isinstance(data["horizon_days"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["run_count"], int) and data["run_count"] >= 0


def assert_projection_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("scenario_id", ""))
    assert data["model_variant"] in ("CONTRACTUAL", "BEHAVIORAL")
    assert isinstance(data["as_of_date"], str)
    assert isinstance(data["horizon_days"], int)
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED", "DISCARDED")
    assert isinstance(data["total_inflows_cents"], int)
    assert isinstance(data["total_outflows_cents"], int)
    assert isinstance(data["net_cumulative_gap_cents"], int)
    assert isinstance(data["hqla_available_cents"], int)
    assert isinstance(data["survival_days"], int)
    if data["status"] == "FINALIZED":
        assert data.get("finalized_at") is not None, "FINALIZED run must carry finalized_at"
        assert is_iso8601_timestamp(data["finalized_at"])


def assert_liquid_asset(data: dict):
    _assert_common_fields(data)
    assert data["asset_class"] in ("LEVEL_1", "LEVEL_2A", "LEVEL_2B")
    assert isinstance(data["reference"], str) and data["reference"]
    assert isinstance(data["market_value_cents"], int) and data["market_value_cents"] > 0
    # PRD §3.3: class haircut 0 / 1500 / 2500 bps.
    assert data["haircut_bps"] == HAIRCUT_BPS[data["asset_class"]]
    assert data["encumbrance_status"] in ("UNENCUMBERED", "PLEDGED", "SOLD")


def assert_funding_source(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["counterparty_name"], str) and data["counterparty_name"]
    assert data["channel"] in (
        "RETAIL_DEPOSIT", "WHOLESALE_UNSECURED", "WHOLESALE_SECURED", "BROKERED",
    )
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] > 0
    if data.get("matures_in_days") is not None:
        assert isinstance(data["matures_in_days"], int) and data["matures_in_days"] >= 0


def assert_ewi_metric(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["unit"] in ("PCT_BPS", "DAYS", "CENTS")
    assert data["direction"] in ("ABOVE_BREACHES", "BELOW_BREACHES")
    assert isinstance(data["amber_threshold"], int)
    assert isinstance(data["red_threshold"], int)
    assert isinstance(data["min_reading_interval_hours"], int)
    assert data["current_band"] in ("GREEN", "AMBER", "RED")
    if data.get("last_reading_at") is not None:
        assert is_iso8601_timestamp(data["last_reading_at"])


def assert_metric_reading(data: dict):
    _assert_event_fields(data)
    assert is_valid_uuid(data.get("metric_id", ""))
    assert is_iso8601_timestamp(data.get("observed_at", ""))
    assert isinstance(data["value"], int)
    assert data["band"] in ("GREEN", "AMBER", "RED")


def assert_posture_snapshot(data: dict):
    _assert_event_fields(data)
    assert isinstance(data["snapshot_seq"], int)
    assert data["level"] in POSTURE_ORDINAL
    assert data["prior_level"] in POSTURE_ORDINAL
    assert isinstance(data["red_count"], int) and data["red_count"] >= 0
    assert isinstance(data["amber_count"], int) and data["amber_count"] >= 0
    assert isinstance(data["open_breach_count"], int) and data["open_breach_count"] >= 0
    assert data["trigger"] in ("READING_AUTO", "MANUAL_EVALUATION")
    assert isinstance(data.get("evaluated_by_user_id"), str)


def assert_playbook(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data.get("scenario_id", ""))
    assert data["min_activation_posture"] in POSTURE_ORDINAL
    assert isinstance(data["target_capacity_cents"], int) and data["target_capacity_cents"] > 0
    assert data["status"] in (
        "DRAFT", "TESTED", "APPROVED", "ACTIVATED", "EXECUTING", "COMPLETED", "STOOD_DOWN",
    )
    assert isinstance(data.get("created_by_user_id"), str)
    if data.get("tested_at") is not None:
        assert is_iso8601_timestamp(data["tested_at"])
    if data.get("activated_at") is not None:
        assert is_iso8601_timestamp(data["activated_at"])


def assert_playbook_action(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("playbook_id", ""))
    assert data["kind"] in ("ASSET_SALE", "LINE_DRAWDOWN")
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] > 0
    assert isinstance(data["estimated_proceeds_cents"], int) and data["estimated_proceeds_cents"] > 0
    assert isinstance(data["settlement_lag_days"], int) and data["settlement_lag_days"] >= 0
    assert data["status"] in (
        "PENDING", "READY", "BLOCKED", "EXECUTING", "SETTLED", "FAILED", "SKIPPED",
    )
    if data.get("executed_at") is not None:
        assert is_iso8601_timestamp(data["executed_at"])


def assert_borrowing_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["provider_name"], str) and data["provider_name"]
    assert data["line_type"] in ("FED_DISCOUNT_WINDOW", "FHLB", "REPO")
    assert isinstance(data["total_capacity_cents"], int) and data["total_capacity_cents"] > 0
    assert isinstance(data["advance_rate_bps"], int)
    assert 1 <= data["advance_rate_bps"] <= 10000
    assert isinstance(data["pledged_value_cents"], int)
    assert isinstance(data["drawn_cents"], int)
    assert isinstance(data["borrowing_power_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_borrowing_power_invariants(data: dict):
    """PRD §3.4 pinned evaluation order: power = max(0, min(capacity, floor(pledged*rate/10000)) - drawn)."""
    cap = data["pledged_value_cents"] * data["advance_rate_bps"] // 10000
    expected = max(0, min(data["total_capacity_cents"], cap) - data["drawn_cents"])
    assert data["borrowing_power_cents"] == expected, (
        f"borrowing_power_cents {data['borrowing_power_cents']} != pinned value {expected} "
        f"(pledged={data['pledged_value_cents']}, rate={data['advance_rate_bps']}, "
        f"capacity={data['total_capacity_cents']}, drawn={data['drawn_cents']})"
    )


def assert_collateral_pledge(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("asset_id", ""))
    assert is_valid_uuid(data.get("line_id", ""))
    assert isinstance(data["pledged_value_cents"], int)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_board_limit(data: dict):
    _assert_common_fields(data)
    assert data["subject"] in (
        "EWI_METRIC", "WHOLESALE_RELIANCE_PCT", "TOP_COUNTERPARTY_PCT",
        "SURVIVAL_DAYS", "INTRADAY_NET_POSITION",
    )
    assert data["direction"] in ("ABOVE_BREACHES", "BELOW_BREACHES")
    assert isinstance(data["limit_value"], int)
    assert data["severity"] in ("BOARD", "REGULATORY")


def assert_limit_breach(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("limit_id", ""))
    assert data["subject"] in (
        "EWI_METRIC", "WHOLESALE_RELIANCE_PCT", "TOP_COUNTERPARTY_PCT",
        "SURVIVAL_DAYS", "INTRADAY_NET_POSITION",
    )
    assert isinstance(data["detected_value"], int)
    assert isinstance(data["limit_value"], int)
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "ESCALATED", "REMEDIATED")
    assert data["source_type"] in (
        "METRIC_READING", "FUNDING_EVALUATION", "PROJECTION_FINALIZE", "INTRADAY_SNAPSHOT",
    )


def assert_intraday_snapshot(data: dict):
    _assert_event_fields(data)
    assert isinstance(data["business_date"], str)
    assert is_iso8601_timestamp(data.get("snapshot_at", ""))
    assert isinstance(data["opening_balance_cents"], int)
    assert isinstance(data["payments_received_cents"], int) and data["payments_received_cents"] >= 0
    assert isinstance(data["payments_sent_cents"], int) and data["payments_sent_cents"] >= 0
    assert isinstance(data["net_position_cents"], int)


def assert_net_position_invariant(data: dict):
    """PRD §3.7: net = opening + received - sent."""
    expected = (
        data["opening_balance_cents"] + data["payments_received_cents"]
        - data["payments_sent_cents"]
    )
    assert data["net_position_cents"] == expected, (
        f"net_position_cents {data['net_position_cents']} != {expected}"
    )
