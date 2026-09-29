"""Entity assertions and domain invariant checkers."""

from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """Identity, audit timestamps and the optimistic-concurrency counter."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """Append-only rows expose only id and created_at — never updated_at or version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "append-only rows must not expose updated_at"
    assert "version" not in data, "append-only rows must not expose a version field"


def _assert_enum(data: Dict[str, Any], field: str, allowed) -> None:
    assert data.get(field) in allowed, f"{field} must be one of {list(allowed)}, got {data.get(field)!r}"


def _assert_non_negative_int(data: Dict[str, Any], field: str) -> None:
    value = data.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), f"{field} must be an integer, got {value!r}"
    assert value >= 0, f"{field} must be non-negative, got {value}"


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
def assert_season(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 16
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["planned_episode_count"] >= 1
    assert data["target_xp_total"] >= 1
    assert data["pass_price_minor"] >= 0
    _assert_enum(data, "status", ("PLANNED", "LIVE", "CONCLUDED", "ARCHIVED"))
    _assert_enum(data, "economy_health", ("HEALTHY", "WATCH", "INFLATED"))
    _assert_enum(data, "content_posture", ("ON_TRACK", "BEHIND"))
    for field in (
        "scheduled_episode_count",
        "released_episode_count",
        "cadence_debt_days",
        "gross_faucet_minor",
        "gross_sink_minor",
        "lifetime_ratio_bp",
        "pending_revenue_minor",
        "settled_revenue_minor",
        "live_offer_count",
        "effective_sink_rate_bp",
        "active_tuning_count",
        "tuning_stage_epoch",
    ):
        _assert_non_negative_int(data, field)


def assert_episode(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["season_id"])
    assert data["sequence_no"] >= 1
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert is_iso8601_timestamp(data["planned_release_at"])
    if data.get("actual_release_at") is not None:
        assert is_iso8601_timestamp(data["actual_release_at"])
    _assert_non_negative_int(data, "xp_grant")
    _assert_non_negative_int(data, "soft_currency_grant_minor")
    _assert_enum(data, "status", ("DRAFT", "SCHEDULED", "LIVE", "CONCLUDED", "ROLLED_BACK"))
    _assert_non_negative_int(data, "rollback_count")
    _assert_non_negative_int(data, "grant_batch_size")


def assert_capacity_cluster(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    _assert_enum(data, "region_code", ("NA", "EU", "LATAM", "APAC"))
    assert data["ccu_capacity"] >= 1
    assert 0 <= data["maintenance_buffer_minutes"] <= 240
    _assert_enum(data, "status", ("ACTIVE", "DRAINING", "RETIRED"))
    _assert_non_negative_int(data, "reserved_ccu")


def assert_live_event(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["season_id"])
    assert is_valid_uuid(data["capacity_cluster_id"])
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["forecast_ccu"] >= 1
    _assert_enum(
        data,
        "status",
        ("PLANNED", "APPROVED", "RUNNING", "COMPLETED", "ROLLED_BACK", "CANCELLED"),
    )
    _assert_non_negative_int(data, "reserved_ccu_at_approval")


def assert_player(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["handle"], str) and len(data["handle"]) > 0
    _assert_enum(data, "region_code", ("NA", "EU", "LATAM", "APAC"))
    assert is_valid_uuid(data["active_season_id"])
    assert isinstance(data["is_minor"], bool)
    assert isinstance(data["guardian_verified"], bool)
    _assert_enum(data, "spend_state", ("UNRESTRICTED", "COOLDOWN", "LOCKED"))
    _assert_enum(data, "retention_band", ("HEALTHY", "AT_RISK", "CHURN_RISK"))
    for field in (
        "season_xp_total",
        "session_count",
        "pacing_bp_realized",
        "spend_30d_minor",
        "pending_spend_minor",
        "lifetime_spend_minor",
    ):
        _assert_non_negative_int(data, field)
    if data.get("last_active_at") is not None:
        assert is_iso8601_timestamp(data["last_active_at"])


def assert_currency_account(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["player_id"])
    _assert_enum(data, "currency_code", ("HARD_GEM", "SOFT_COIN", "EVENT_TOKEN"))
    for field in ("balance_minor", "lifetime_faucet_minor", "lifetime_sink_minor"):
        _assert_non_negative_int(data, field)
    _assert_enum(data, "status", ("ACTIVE", "FROZEN"))
    assert data["balance_minor"] == data["lifetime_faucet_minor"] - data["lifetime_sink_minor"], (
        "balance_minor must equal lifetime_faucet_minor minus lifetime_sink_minor, got "
        f"{data['balance_minor']} vs {data['lifetime_faucet_minor']} - {data['lifetime_sink_minor']}"
    )


def assert_ledger_entry(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["currency_account_id"])
    assert is_valid_uuid(data["season_id"])
    _assert_enum(data, "direction", ("FAUCET", "SINK"))
    assert data["amount_minor"] >= 1
    _assert_enum(
        data,
        "source_kind",
        (
            "EPISODE_GRANT",
            "PURCHASE_GRANT",
            "OFFER_SPEND",
            "EVENT_REWARD",
            "ADMIN_ADJUSTMENT",
            "REFUND_REVERSAL",
            "EPISODE_ROLLBACK_REVERSAL",
        ),
    )
    assert is_iso8601_timestamp(data["occurred_at"])


def assert_offer(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["season_id"])
    _assert_enum(data, "offer_type", ("BATTLE_PASS", "BUNDLE", "LIMITED_TIME", "LOOT_BOX"))
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    _assert_enum(data, "price_tier", ("T1", "T2", "T3", "T4"))
    assert data["list_price_minor"] >= 1
    assert isinstance(data["line_items"], list) and 1 <= len(data["line_items"]) <= 8
    assert 0 <= data["personalization_discount_bp"] <= 2000
    assert isinstance(data["minor_purchasable"], bool)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    _assert_enum(data, "approval_status", ("DRAFT", "IN_REVIEW", "APPROVED"))
    _assert_enum(data, "availability_status", ("OFFLINE", "LIVE", "SUSPENDED", "WITHDRAWN"))
    _assert_enum(data, "disclosure_state", ("NOT_REQUIRED", "REQUIRED_MISSING", "PUBLISHED"))
    for field in ("fairness_index_bp", "units_sold", "pending_purchase_count", "revision_count"):
        _assert_non_negative_int(data, field)


def assert_probability_disclosure(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["offer_id"])
    assert isinstance(data["entries"], list) and 1 <= len(data["entries"]) <= 20
    _assert_non_negative_int(data, "total_probability_bp")
    _assert_non_negative_int(data, "expected_value_minor")
    _assert_enum(data, "status", ("DRAFT", "PUBLISHED", "SUPERSEDED"))


def assert_purchase(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["player_id"])
    assert is_valid_uuid(data["offer_id"])
    for field in (
        "quoted_price_minor",
        "applied_personalization_bp",
        "price_paid_minor",
        "granted_total_minor",
        "granted_consumed_minor",
    ):
        _assert_non_negative_int(data, field)
    assert isinstance(data["is_minor_purchase"], bool)
    _assert_enum(data, "status", ("PENDING", "SETTLED", "DENIED", "REFUNDED"))


def assert_refund_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["purchase_id"])
    _assert_enum(
        data,
        "reason_code",
        ("ACCIDENTAL", "MINOR_UNAUTHORIZED", "DISSATISFIED", "TECHNICAL_FAILURE"),
    )
    _assert_enum(data, "status", ("SUBMITTED", "APPROVED", "DENIED", "EXECUTED"))
    for field in (
        "consumed_ratio_bp",
        "refund_base_minor",
        "restock_fee_minor",
        "refund_amount_minor",
        "goodwill_credit_minor",
    ):
        _assert_non_negative_int(data, field)


def assert_balance_change(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["season_id"])
    _assert_enum(data, "target_kind", ("SINK_RATE", "FAUCET_RATE", "DROP_RATE", "PRICE"))
    assert -3000 <= data["delta_bp"] <= 3000 and data["delta_bp"] != 0
    assert isinstance(data["rationale"], str) and len(data["rationale"]) > 0
    assert 1 <= data["canary_cohort_pct"] <= 50
    _assert_enum(data, "stage", ("DRAFT", "SHADOW", "CANARY", "LIVE", "REVERTED", "RETIRED"))
    _assert_enum(data, "comms_state", ("MISSING", "DRAFTED", "PUBLISHED"))


def assert_comms_notice(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["balance_change_id"])
    _assert_enum(data, "channel", ("PATCH_NOTES", "IN_GAME", "SOCIAL"))
    assert isinstance(data["headline"], str) and len(data["headline"]) > 0
    assert isinstance(data["body"], str) and len(data["body"]) > 0
    _assert_enum(data, "status", ("DRAFT", "PUBLISHED"))


def assert_monitoring_run(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["season_id"])
    assert data["epoch_no"] >= 1
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    for field in ("gross_faucet_minor", "gross_sink_minor", "suspended_offer_count", "denied_purchase_count"):
        _assert_non_negative_int(data, field)
    _assert_enum(data, "status", ("OPEN", "COMPUTED", "CERTIFIED", "VOIDED"))
    if data.get("resulting_health") is not None:
        _assert_enum(data, "resulting_health", ("HEALTHY", "WATCH", "INFLATED"))


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_health_band(ratio_bp: int, band: str) -> None:
    """The band follows the ratio: HEALTHY at or above 6000, WATCH at or above 4000, else INFLATED."""
    if ratio_bp >= 6000:
        expected = "HEALTHY"
    elif ratio_bp >= 4000:
        expected = "WATCH"
    else:
        expected = "INFLATED"
    assert band == expected, f"ratio {ratio_bp} bp should band as {expected}, got {band}"


def assert_retention_band(pacing_bp: int, band: str) -> None:
    """HEALTHY at or above 9000, AT_RISK at or above 6000, else CHURN_RISK."""
    if pacing_bp >= 9000:
        expected = "HEALTHY"
    elif pacing_bp >= 6000:
        expected = "AT_RISK"
    else:
        expected = "CHURN_RISK"
    assert band == expected, f"pacing {pacing_bp} bp should band as {expected}, got {band}"


def assert_account_conserved(account: Dict[str, Any], faucet: int, sink: int) -> None:
    """Lifetime totals and balance after a compensating cascade."""
    assert account["lifetime_faucet_minor"] == faucet, (
        f"Expected lifetime_faucet_minor {faucet}, got {account['lifetime_faucet_minor']}"
    )
    assert account["lifetime_sink_minor"] == sink, (
        f"Expected lifetime_sink_minor {sink}, got {account['lifetime_sink_minor']}"
    )
    assert account["balance_minor"] == faucet - sink, (
        f"Expected balance_minor {faucet - sink}, got {account['balance_minor']}"
    )


def assert_season_ledger_totals(season: Dict[str, Any], gross_faucet: int, gross_sink: int) -> None:
    assert season["gross_faucet_minor"] == gross_faucet, (
        f"Expected gross_faucet_minor {gross_faucet}, got {season['gross_faucet_minor']}"
    )
    assert season["gross_sink_minor"] == gross_sink, (
        f"Expected gross_sink_minor {gross_sink}, got {season['gross_sink_minor']}"
    )


def assert_version_is(data: Dict[str, Any], expected: int) -> None:
    assert data["version"] == expected, f"Expected version {expected}, got {data['version']}"
