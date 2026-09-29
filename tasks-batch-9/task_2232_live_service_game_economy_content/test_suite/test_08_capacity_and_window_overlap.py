"""Interval arithmetic: cluster concurrency windows and storefront sku cooldown windows."""

from typing import Any, Dict

from test_helpers import (
    DESIGNER,
    LIVEOPS,
    ApiErrorId,
    api_client,
    create_approved_event,
    create_approved_offer,
    create_cluster,
    create_live_season,
    create_planned_event,
    offer_line_item,
    publish_offer,
    read_cluster,
    read_live_event,
    read_offer,
    read_season,
    season_version,
    validate_error,
    validate_success,
)

_SHARED_LINE_SKU = "COIN_PACK"


# ---------------------------------------------------------------------------
# Private setup helpers (each test rebuilds its own world from scratch)
# ---------------------------------------------------------------------------
def _cluster_with_one_approved_event() -> Dict[str, Any]:
    """A 10000-CCU cluster with a 30-minute buffer, one APPROVED 6000-CCU event ending at 02:00,
    and two PLANNED candidates starting at 02:15 — one at 4500 CCU and one at 4000."""
    season = create_live_season()
    cluster = create_cluster(
        name="NA-1", region_code="NA", ccu_capacity=10000, maintenance_buffer_minutes=30
    )
    event_a = create_approved_event(
        season["id"],
        cluster["id"],
        code="EVT_A",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-05T02:00:00Z",
        forecast_ccu=6000,
    )
    event_b = create_planned_event(
        season["id"],
        cluster["id"],
        code="EVT_B",
        window_start="2026-08-05T02:15:00Z",
        window_end="2026-08-05T04:00:00Z",
        forecast_ccu=4500,
    )
    event_c = create_planned_event(
        season["id"],
        cluster["id"],
        code="EVT_C",
        window_start="2026-08-05T02:15:00Z",
        window_end="2026-08-05T04:00:00Z",
        forecast_ccu=4000,
    )
    return {
        "season": season,
        "cluster": cluster,
        "event_a": event_a,
        "event_b": event_b,
        "event_c": event_c,
    }


def _shared_sku_offer_overrides(sku: str, window_start: str, window_end: str) -> Dict[str, Any]:
    """A single-line BUNDLE at 499 minor units whose line sku is shared with its siblings."""
    return {
        "offer_type": "BUNDLE",
        "sku": sku,
        "price_tier": "T1",
        "list_price_minor": 499,
        "line_items": [offer_line_item(_SHARED_LINE_SKU, 499, 700, "SOFT_COIN", 700)],
        "personalization_discount_bp": 0,
        "minor_purchasable": False,
        "window_start": window_start,
        "window_end": window_end,
    }


def _live_offer_plus_two_adjacent_candidates() -> Dict[str, Any]:
    """PACK_A LIVE over 08-01 -> 08-10, plus two APPROVED/OFFLINE candidates sharing its line sku:
    PACK_B starting exactly 24 hours after PACK_A closes, PACK_C one second later."""
    season = create_live_season()
    pack_a = create_approved_offer(
        season["id"],
        **_shared_sku_offer_overrides("PACK_A", "2026-08-01T00:00:00Z", "2026-08-10T00:00:00Z"),
    )
    publish_offer(pack_a["id"], season["id"])
    pack_b = create_approved_offer(
        season["id"],
        **_shared_sku_offer_overrides("PACK_B", "2026-08-11T00:00:00Z", "2026-08-15T00:00:00Z"),
    )
    pack_c = create_approved_offer(
        season["id"],
        **_shared_sku_offer_overrides("PACK_C", "2026-08-11T00:00:01Z", "2026-08-16T00:00:00Z"),
    )
    return {"season": season, "pack_a": pack_a, "pack_b": pack_b, "pack_c": pack_c}


# ---------------------------------------------------------------------------
# Cluster concurrency: half-open windows with an end-only buffer
# ---------------------------------------------------------------------------
class TestClusterOverlapLoadWithEndBuffer:
    def test_aggregate_overlap_load_above_capacity_is_refused(self):
        """PRD §3.3: "The cluster's `maintenance_buffer_minutes` is converted to seconds and appended to the **end** of every event's window and to no other side, so an event effectively occupies the half-open interval from its `window_start` up to but not including its `window_end` plus that buffer."
        PRD §3.3: "Two events overlap when the first one's start is strictly before the second one's buffered end and the second one's start is strictly before the first one's buffered end."
        PRD §3.3: "The overlap load is then the candidate's own `forecast_ccu` plus the sum of the `forecast_ccu` of every one of those neighbours — a pairwise sum against the candidate, deliberately not a true timeline peak, so three neighbours that overlap the candidate but not each other still all count."
        PRD §3.3: "The event is admissible when that load is less than or equal to the cluster's `ccu_capacity`; a load exactly equal to capacity passes, and a load one greater is refused with `ERR_CLUSTER_CAPACITY_EXCEEDED`."
        PRD §3.3: "The event is created in `PLANNED` with `reserved_ccu_at_approval` at 0 and `rollback_reason` null, and no capacity whatsoever is reserved until approval."

        Design: Difficulty/resource_temporal_overlap/cluster_ccu_aggregate_overlap_with_end_buffer
        """
        world = _cluster_with_one_approved_event()
        cluster_id = world["cluster"]["id"]
        event_b_id = world["event_b"]["id"]

        response = api_client.approve_live_event(event_b_id, LIVEOPS)
        validate_error(response, ApiErrorId.ERR_CLUSTER_CAPACITY_EXCEEDED.value, 422)

        event_b = read_live_event(event_b_id)
        assert event_b["status"] == "PLANNED", (
            "A candidate whose overlap load of 10500 exceeds the 10000 ceiling stays PLANNED, got "
            f"{event_b['status']}"
        )
        assert event_b["reserved_ccu_at_approval"] == 0, (
            "A refused approval reserves nothing, so reserved_ccu_at_approval stays 0, got "
            f"{event_b['reserved_ccu_at_approval']}"
        )

        cluster = read_cluster(cluster_id)
        assert cluster["reserved_ccu"] == 6000, (
            "The cluster must still hold only the approved neighbour's 6000 reservation, got "
            f"{cluster['reserved_ccu']}"
        )

    def test_overlap_load_landing_exactly_on_capacity_is_admitted(self):
        """PRD §3.3: "The event is admissible when that load is less than or equal to the cluster's `ccu_capacity`; a load exactly equal to capacity passes, and a load one greater is refused with `ERR_CLUSTER_CAPACITY_EXCEEDED`."
        PRD §3.3: "The overlap load is then the candidate's own `forecast_ccu` plus the sum of the `forecast_ccu` of every one of those neighbours — a pairwise sum against the candidate, deliberately not a true timeline peak, so three neighbours that overlap the candidate but not each other still all count."
        PRD §3.3: "On success the event's `forecast_ccu` is snapshotted into `reserved_ccu_at_approval`, the cluster's `reserved_ccu` grows by that same figure, and the cluster's `version` moves by 1."

        Design: Difficulty/resource_temporal_overlap/cluster_ccu_aggregate_overlap_with_end_buffer
        """
        world = _cluster_with_one_approved_event()
        cluster_id = world["cluster"]["id"]
        event_b_id = world["event_b"]["id"]
        event_c_id = world["event_c"]["id"]

        refused = api_client.approve_live_event(event_b_id, LIVEOPS)
        validate_error(refused, ApiErrorId.ERR_CLUSTER_CAPACITY_EXCEEDED.value, 422)

        approved = validate_success(api_client.approve_live_event(event_c_id, LIVEOPS), 200)
        assert approved["status"] == "APPROVED", (
            "An overlap load of exactly 10000 against a 10000 ceiling must be admitted, got "
            f"{approved['status']}"
        )
        assert approved["reserved_ccu_at_approval"] == 4000, (
            "The admitted event snapshots its own 4000 forecast, got "
            f"{approved['reserved_ccu_at_approval']}"
        )

        cluster = read_cluster(cluster_id)
        assert cluster["reserved_ccu"] == 10000, (
            "The cluster's reserved_ccu must be 6000 plus the newly reserved 4000, got "
            f"{cluster['reserved_ccu']}"
        )


# ---------------------------------------------------------------------------
# Storefront sku cooldown: closed comparisons on both sides
# ---------------------------------------------------------------------------
class TestOfferSkuCooldownConflict:
    def test_publish_refused_when_window_starts_exactly_at_the_cooldown_boundary(self):
        """PRD §3.5: "The cooldown here is 24 hours, converted to seconds, and it is applied **symmetrically on both sides** of each window rather than only at the end."
        PRD §3.5: "The siblings considered are the offers of the same season, other than the candidate, whose `availability_status` is `LIVE` or `SUSPENDED` and which share at least one line-item `sku` with the candidate; `OFFLINE` and `WITHDRAWN` offers never conflict, no matter what they contain."
        PRD §3.5: "A sibling conflicts when the candidate's `window_start` is at or before that sibling's `window_end` plus the cooldown **and** the sibling's `window_start` is at or before the candidate's `window_end` plus the cooldown — closed comparisons on both sides, so exact adjacency counts as a conflict, as does any gap shorter than 24 hours."
        PRD §3.5: "There is no aggregate allowance here: a single conflicting sibling is fatal, and the publish is refused with `ERR_OFFER_SKU_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/offer_sku_closed_interval_cooldown_conflict
        """
        world = _live_offer_plus_two_adjacent_candidates()
        season_id = world["season"]["id"]
        pack_a_id = world["pack_a"]["id"]
        pack_b_id = world["pack_b"]["id"]

        response = api_client.publish_offer(
            pack_b_id, {"expected_season_version": season_version(season_id)}, DESIGNER
        )
        validate_error(response, ApiErrorId.ERR_OFFER_SKU_WINDOW_CONFLICT.value, 422)

        pack_b = read_offer(pack_b_id)
        assert pack_b["availability_status"] == "OFFLINE", (
            "A candidate starting exactly 24 hours after the LIVE sibling closes must stay OFFLINE, "
            f"got {pack_b['availability_status']}"
        )

        pack_a = read_offer(pack_a_id)
        assert pack_a["availability_status"] == "LIVE", (
            "The conflicting sibling is untouched by the refused publish and stays LIVE, got "
            f"{pack_a['availability_status']}"
        )

    def test_publish_succeeds_one_second_past_the_cooldown_boundary(self):
        """PRD §3.5: "A sibling conflicts when the candidate's `window_start` is at or before that sibling's `window_end` plus the cooldown **and** the sibling's `window_start` is at or before the candidate's `window_end` plus the cooldown — closed comparisons on both sides, so exact adjacency counts as a conflict, as does any gap shorter than 24 hours."
        PRD §3.5: "There is no aggregate allowance here: a single conflicting sibling is fatal, and the publish is refused with `ERR_OFFER_SKU_WINDOW_CONFLICT`."
        PRD §3.5: "A successful publish raises the season's `live_offer_count` by 1 and moves both the season's and the offer's `version` by 1."

        Design: Difficulty/resource_temporal_overlap/offer_sku_closed_interval_cooldown_conflict
        """
        world = _live_offer_plus_two_adjacent_candidates()
        season_id = world["season"]["id"]
        pack_a_id = world["pack_a"]["id"]
        pack_b_id = world["pack_b"]["id"]
        pack_c_id = world["pack_c"]["id"]

        refused = api_client.publish_offer(
            pack_b_id, {"expected_season_version": season_version(season_id)}, DESIGNER
        )
        validate_error(refused, ApiErrorId.ERR_OFFER_SKU_WINDOW_CONFLICT.value, 422)

        published = validate_success(
            api_client.publish_offer(
                pack_c_id, {"expected_season_version": season_version(season_id)}, DESIGNER
            ),
            200,
        )
        assert published["availability_status"] == "LIVE", (
            "A candidate starting one second past the 24-hour cooldown clears the conflict and goes "
            f"LIVE, got {published['availability_status']}"
        )

        pack_a = read_offer(pack_a_id)
        assert pack_a["availability_status"] == "LIVE", (
            f"The original sibling remains LIVE, got {pack_a['availability_status']}"
        )

        season = read_season(season_id)
        assert season["live_offer_count"] == 2, (
            "Exactly two offers of the season are live on the storefront, got "
            f"{season['live_offer_count']}"
        )
