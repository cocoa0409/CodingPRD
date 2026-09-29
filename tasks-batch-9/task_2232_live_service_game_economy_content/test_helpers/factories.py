"""Payload factories — one per entity, client-supplied input fields only."""

from typing import Any, Dict, List

from .constants import TEST_DEFAULTS


def create_season_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "code": TEST_DEFAULTS["SEASON_CODE"],
        "title": TEST_DEFAULTS["SEASON_TITLE"],
        "starts_at": TEST_DEFAULTS["SEASON_STARTS_AT"],
        "ends_at": TEST_DEFAULTS["SEASON_ENDS_AT"],
        "planned_episode_count": TEST_DEFAULTS["SEASON_PLANNED_EPISODE_COUNT"],
        "target_xp_total": TEST_DEFAULTS["SEASON_TARGET_XP_TOTAL"],
        "pass_price_minor": TEST_DEFAULTS["SEASON_PASS_PRICE_MINOR"],
    }
    payload.update(overrides)
    return payload


def create_episode_payload(season_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "season_id": season_id,
        "sequence_no": 1,
        "title": "E1 Tidefall",
        "planned_release_at": "2026-08-02T00:00:00Z",
        "xp_grant": 600,
        "soft_currency_grant_minor": 1200,
    }
    payload.update(overrides)
    return payload


def create_cluster_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": "Cluster NA-1",
        "region_code": "NA",
        "ccu_capacity": 10000,
    }
    payload.update(overrides)
    return payload


def create_live_event_payload(season_id: str, cluster_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "season_id": season_id,
        "capacity_cluster_id": cluster_id,
        "code": "EVT_A",
        "window_start": "2026-08-10T10:00:00Z",
        "window_end": "2026-08-10T14:00:00Z",
        "forecast_ccu": 6000,
    }
    payload.update(overrides)
    return payload


def create_player_payload(season_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "handle": "tide_p1",
        "region_code": "NA",
        "active_season_id": season_id,
    }
    payload.update(overrides)
    return payload


def create_currency_account_payload(**overrides) -> Dict[str, Any]:
    payload = {"currency_code": "SOFT_COIN"}
    payload.update(overrides)
    return payload


def create_adjustment_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "direction": "FAUCET",
        "amount_minor": 1000,
        "source_kind": "ADMIN_ADJUSTMENT",
    }
    payload.update(overrides)
    return payload


def offer_line_item(
    sku: str = "COIN_PACK",
    base_price_minor: int = 499,
    declared_value_minor: int = 700,
    granted_currency_code: str = "SOFT_COIN",
    granted_amount_minor: int = 600,
) -> Dict[str, Any]:
    return {
        "sku": sku,
        "base_price_minor": base_price_minor,
        "declared_value_minor": declared_value_minor,
        "granted_currency_code": granted_currency_code,
        "granted_amount_minor": granted_amount_minor,
    }


def create_offer_payload(season_id: str, **overrides) -> Dict[str, Any]:
    """Default offer: a BUNDLE at tier T3 with two line items summing to 1798 minor units."""
    line_items: List[Dict[str, Any]] = [
        offer_line_item("COIN_PACK", 499, 700, "EVENT_TOKEN", 600),
        offer_line_item("SKIN_A", 1299, 1700, "EVENT_TOKEN", 600),
    ]
    payload = {
        "season_id": season_id,
        "offer_type": "BUNDLE",
        "sku": "AUG_BUNDLE",
        "price_tier": "T3",
        "list_price_minor": 1798,
        "line_items": line_items,
        "personalization_discount_bp": 0,
        "minor_purchasable": False,
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def single_line_offer_payload(
    season_id: str,
    sku: str,
    base_price_minor: int,
    declared_value_minor: int,
    granted_currency_code: str = "HARD_GEM",
    granted_amount_minor: int = 0,
    **overrides,
) -> Dict[str, Any]:
    """An offer whose list price is exactly one line item's base price."""
    payload = {
        "season_id": season_id,
        "offer_type": "LIMITED_TIME",
        "sku": sku,
        "price_tier": "T1",
        "list_price_minor": base_price_minor,
        "line_items": [
            offer_line_item(
                f"{sku}_ITEM",
                base_price_minor,
                declared_value_minor,
                granted_currency_code,
                granted_amount_minor or base_price_minor,
            )
        ],
        "personalization_discount_bp": 0,
        "minor_purchasable": False,
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def disclosure_entry(
    item_sku: str,
    probability_bp: int,
    item_value_minor: int,
    is_rare: bool = False,
) -> Dict[str, Any]:
    return {
        "item_sku": item_sku,
        "probability_bp": probability_bp,
        "item_value_minor": item_value_minor,
        "is_rare": is_rare,
    }


def create_disclosure_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "entries": [
            disclosure_entry("COMMON_SKIN", 9000, 100, False),
            disclosure_entry("RARE_SKIN", 1000, 5000, True),
        ]
    }
    payload.update(overrides)
    return payload


def create_purchase_payload(player_id: str, offer_id: str, expected_offer_version: int, **overrides) -> Dict[str, Any]:
    payload = {
        "player_id": player_id,
        "offer_id": offer_id,
        "expected_offer_version": expected_offer_version,
    }
    payload.update(overrides)
    return payload


def create_refund_request_payload(purchase_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "purchase_id": purchase_id,
        "reason_code": "ACCIDENTAL",
    }
    payload.update(overrides)
    return payload


def create_balance_change_payload(season_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "season_id": season_id,
        "target_kind": "SINK_RATE",
        "delta_bp": 500,
        "rationale": "Soft-coin sinks are draining too slowly at the current rate",
    }
    payload.update(overrides)
    return payload


def create_comms_notice_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "channel": "PATCH_NOTES",
        "headline": "Sink rate tuning for August",
        "body": "We are increasing soft-coin sink pressure by five percent this month.",
    }
    payload.update(overrides)
    return payload


def create_monitoring_run_payload(season_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "season_id": season_id,
        "epoch_no": 1,
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-03T00:00:00Z",
    }
    payload.update(overrides)
    return payload
