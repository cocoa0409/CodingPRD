"""Payload factories — one per entity, input fields only (PRD §3).

Every factory returns a dict of exactly the caller-suppliable fields named in
the PRD narrative for that resource; computed/system fields are never sent.
"""

DEFAULTS = {
    "SCENARIO_NAME": "Scenario",
    "TIER": "BASELINE",
    "DEPOSIT_RUNOFF_PCT": 5,
    "WHOLESALE_RENEWAL_PCT": 80,
    "LEVEL2_ADDON_BPS": 0,
    "HORIZON_DAYS": 30,
    "ASSET_CLASS": "LEVEL_1",
    "REFERENCE": "REF-1",
    "MARKET_VALUE_CENTS": 1_000_000,
    "COUNTERPARTY_NAME": "Counterparty",
    "CHANNEL": "RETAIL_DEPOSIT",
    "BALANCE_CENTS": 1_000_000,
    "METRIC_CODE": "M",
    "METRIC_NAME": "metric",
    "UNIT": "PCT_BPS",
    "DIRECTION": "ABOVE_BREACHES",
    "AMBER_THRESHOLD": 1000,
    "RED_THRESHOLD": 5000,
    "PLAYBOOK_NAME": "Playbook",
    "MIN_ACTIVATION_POSTURE": "NORMAL",
    "TARGET_CAPACITY_CENTS": 1_000_000,
    "ACTION_KIND": "LINE_DRAWDOWN",
    "SEQUENCE_NO": 1,
    "ESTIMATED_PROCEEDS_CENTS": 1_000_000,
    "SETTLEMENT_LAG_DAYS": 0,
    "PROVIDER_NAME": "Provider",
    "LINE_TYPE": "FED_DISCOUNT_WINDOW",
    "TOTAL_CAPACITY_CENTS": 100_000_000,
    "ADVANCE_RATE_BPS": 10_000,
    "LIMIT_SUBJECT": "WHOLESALE_RELIANCE_PCT",
    "LIMIT_VALUE": 4000,
    "SEVERITY": "BOARD",
    "AMOUNT_CENTS": 1_000_000,
    "BUSINESS_DATE": "2026-08-01",
    "SNAPSHOT_AT": "2026-08-01T09:00:00Z",
    "OPENING_BALANCE_CENTS": 100_000_000,
    "AS_OF_DATE": "2026-08-01",
}


def create_scenario_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SCENARIO_NAME"],
        "tier": DEFAULTS["TIER"],
        "deposit_runoff_pct": DEFAULTS["DEPOSIT_RUNOFF_PCT"],
        "wholesale_renewal_pct": DEFAULTS["WHOLESALE_RENEWAL_PCT"],
        "level2_addon_bps": DEFAULTS["LEVEL2_ADDON_BPS"],
        "horizon_days": DEFAULTS["HORIZON_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_projection_run_payload(**overrides) -> dict:
    defaults = {
        "model_variant": "CONTRACTUAL",
        "as_of_date": DEFAULTS["AS_OF_DATE"],
        # expected_scenario_version is required (PRD §2.7); callers must supply it.
    }
    defaults.update(overrides)
    return defaults


def create_liquid_asset_payload(**overrides) -> dict:
    defaults = {
        "asset_class": DEFAULTS["ASSET_CLASS"],
        "reference": DEFAULTS["REFERENCE"],
        "market_value_cents": DEFAULTS["MARKET_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def reprice_asset_payload(**overrides) -> dict:
    defaults = {"market_value_cents": DEFAULTS["MARKET_VALUE_CENTS"]}
    defaults.update(overrides)
    return defaults


def create_funding_source_payload(**overrides) -> dict:
    defaults = {
        "counterparty_name": DEFAULTS["COUNTERPARTY_NAME"],
        "channel": DEFAULTS["CHANNEL"],
        "balance_cents": DEFAULTS["BALANCE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_ewi_metric_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["METRIC_CODE"],
        "name": DEFAULTS["METRIC_NAME"],
        "unit": DEFAULTS["UNIT"],
        "direction": DEFAULTS["DIRECTION"],
        "amber_threshold": DEFAULTS["AMBER_THRESHOLD"],
        "red_threshold": DEFAULTS["RED_THRESHOLD"],
        "min_reading_interval_hours": 0,
    }
    defaults.update(overrides)
    return defaults


def create_reading_payload(**overrides) -> dict:
    defaults = {
        "observed_at": "2026-08-01T00:00:00Z",
        "value": 100,
    }
    defaults.update(overrides)
    return defaults


def create_playbook_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PLAYBOOK_NAME"],
        "min_activation_posture": DEFAULTS["MIN_ACTIVATION_POSTURE"],
        "target_capacity_cents": DEFAULTS["TARGET_CAPACITY_CENTS"],
        # scenario_id is required; callers must supply it.
    }
    defaults.update(overrides)
    return defaults


def patch_playbook_payload(**overrides) -> dict:
    # expected_playbook_version is required (PRD §2.7); callers must supply it.
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def create_action_payload(**overrides) -> dict:
    defaults = {
        "kind": DEFAULTS["ACTION_KIND"],
        "sequence_no": DEFAULTS["SEQUENCE_NO"],
        "estimated_proceeds_cents": DEFAULTS["ESTIMATED_PROCEEDS_CENTS"],
        "settlement_lag_days": DEFAULTS["SETTLEMENT_LAG_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_borrowing_line_payload(**overrides) -> dict:
    defaults = {
        "provider_name": DEFAULTS["PROVIDER_NAME"],
        "line_type": DEFAULTS["LINE_TYPE"],
        "total_capacity_cents": DEFAULTS["TOTAL_CAPACITY_CENTS"],
        "advance_rate_bps": DEFAULTS["ADVANCE_RATE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def draw_payload(**overrides) -> dict:
    defaults = {"amount_cents": DEFAULTS["AMOUNT_CENTS"]}
    defaults.update(overrides)
    return defaults


def repay_payload(**overrides) -> dict:
    defaults = {"amount_cents": DEFAULTS["AMOUNT_CENTS"]}
    defaults.update(overrides)
    return defaults


def create_pledge_payload(**overrides) -> dict:
    # asset_id and line_id are required; callers must supply them.
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def create_board_limit_payload(**overrides) -> dict:
    defaults = {
        "subject": DEFAULTS["LIMIT_SUBJECT"],
        "direction": DEFAULTS["DIRECTION"],
        "limit_value": DEFAULTS["LIMIT_VALUE"],
        "severity": DEFAULTS["SEVERITY"],
    }
    defaults.update(overrides)
    return defaults


def remediate_payload(**overrides) -> dict:
    defaults = {"remediation_note": "remediated"}
    defaults.update(overrides)
    return defaults


def create_intraday_snapshot_payload(**overrides) -> dict:
    defaults = {
        "business_date": DEFAULTS["BUSINESS_DATE"],
        "snapshot_at": DEFAULTS["SNAPSHOT_AT"],
        "opening_balance_cents": DEFAULTS["OPENING_BALANCE_CENTS"],
        "payments_received_cents": 0,
        "payments_sent_cents": 0,
    }
    defaults.update(overrides)
    return defaults
