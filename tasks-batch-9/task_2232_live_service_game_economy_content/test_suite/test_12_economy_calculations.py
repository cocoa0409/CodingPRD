"""Arithmetic corners of the storefront quote, the fairness index, cluster overlap and cadence debt.

Every test builds its own world from scratch: the harness wipes the server database before
each test, so no cross-test state is shared.
"""

from typing import Any, Dict

import pytest

from test_helpers import (
    DESIGNER,
    LIVEOPS,
    PRODUCER,
    api_client,
    create_cluster,
    create_draft_episode,
    create_draft_offer,
    create_live_season,
    create_planned_event,
    create_player,
    get_success_data,
    read_cluster,
    read_season,
    set_clock,
    validate_success,
)


# ---------------------------------------------------------------------------
# Local helpers (private to this module — test_helpers is shared and read-only)
# ---------------------------------------------------------------------------
def _schedule(episode_id: str) -> Dict[str, Any]:
    """Schedule an episode with no payload override, as the ContentProducer who owns cadence."""
    return get_success_data(api_client.schedule_episode(episode_id, PRODUCER))


def _line(
    sku: str,
    base_price_minor: int,
    declared_value_minor: int,
    granted_currency_code: str,
    granted_amount_minor: int,
) -> Dict[str, Any]:
    return {
        "sku": sku,
        "base_price_minor": base_price_minor,
        "declared_value_minor": declared_value_minor,
        "granted_currency_code": granted_currency_code,
        "granted_amount_minor": granted_amount_minor,
    }


def _quote_as_designer(offer_id: str, player_id: str) -> Dict[str, Any]:
    return validate_success(
        api_client.get_offer_quote(offer_id, DESIGNER, params={"player_id": player_id})
    )


# ---------------------------------------------------------------------------
# Personalized quote: the two pinned multiplier tables
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "region_code, handle, expected_multiplier_bp, expected_quote_minor",
    [
        ("NA", "w_na", 10000, 1000),
        ("EU", "w_eu", 11000, 1100),
        ("LATAM", "w_latam", 6500, 650),
        ("APAC", "w_apac", 8500, 850),
    ],
)
def test_region_multiplier_constants_applied_per_region(
    region_code: str, handle: str, expected_multiplier_bp: int, expected_quote_minor: int
) -> None:
    """PRD §3.6: "First, the region multiplier is selected from the buyer's `region_code`: North America is the reference at 10000 basis points, Europe is 11000, Latin America is 6500, and Asia-Pacific is 8500."
    PRD §3.6: "Walking the offer's `line_items` in ascending line `sku` order, each line is priced in two rounded steps: the gross line is that line's `base_price_minor` multiplied by the region multiplier, divided by 10000, and rounded half up; the net line is that gross line multiplied by the quantity 10000 minus the tier discount minus the personalization discount, divided by 10000, and rounded half up again."
    PRD §3.6: "It takes the `player_id` being quoted and answers with the `offer_id`, that `player_id`, the `region_multiplier_bp` and `tier_discount_bp` that were selected, the `applied_personalization_bp`, the `retention_band` that was read, the resulting `quote_minor`, and a `line_breakdown` array showing the per-line arithmetic."
    PRD §3.6: "Second, the tier discount is selected from the offer's `price_tier`: `T1` discounts nothing, `T2` discounts 500 basis points, `T3` discounts 1200, and `T4` discounts 2000."
    PRD §3.6: "Third, the personalization discount applies only when the buyer's stored `retention_band` is exactly `AT_RISK`: in that case it is the offer's `personalization_discount_bp` capped at 1500 basis points, and in every other band — `HEALTHY` or `CHURN_RISK` — it is 0."

    A T1 offer zeroes the tier discount and a freshly provisioned player is never `AT_RISK`,
    so the only live term is the regional multiplier on a single 1000-minor line.

    Design: Corner/calculations/corner_calc_region_multiplier_constants_applied
    """
    season = create_live_season()
    offer = create_draft_offer(
        season["id"],
        offer_type="BUNDLE",
        sku="WORLD_PACK",
        price_tier="T1",
        list_price_minor=1000,
        line_items=[_line("WORLD_COINS", 1000, 1400, "SOFT_COIN", 1400)],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    player = create_player(season["id"], handle=handle, region_code=region_code)

    quote = _quote_as_designer(offer["id"], player["id"])

    assert quote["region_multiplier_bp"] == expected_multiplier_bp
    assert quote["quote_minor"] == expected_quote_minor
    assert quote["tier_discount_bp"] == 0
    assert quote["applied_personalization_bp"] == 0


@pytest.mark.parametrize(
    "price_tier, line_sku, expected_discount_bp, expected_quote_minor",
    [
        ("T1", "T1_COINS", 0, 1000),
        ("T2", "T2_COINS", 500, 950),
        ("T3", "T3_COINS", 1200, 880),
        ("T4", "T4_COINS", 2000, 800),
    ],
)
def test_tier_discount_boundaries_t1_to_t4(
    price_tier: str, line_sku: str, expected_discount_bp: int, expected_quote_minor: int
) -> None:
    """PRD §3.6: "Second, the tier discount is selected from the offer's `price_tier`: `T1` discounts nothing, `T2` discounts 500 basis points, `T3` discounts 1200, and `T4` discounts 2000."
    PRD §3.6: "Walking the offer's `line_items` in ascending line `sku` order, each line is priced in two rounded steps: the gross line is that line's `base_price_minor` multiplied by the region multiplier, divided by 10000, and rounded half up; the net line is that gross line multiplied by the quantity 10000 minus the tier discount minus the personalization discount, divided by 10000, and rounded half up again."
    PRD §3.6: "It takes the `player_id` being quoted and answers with the `offer_id`, that `player_id`, the `region_multiplier_bp` and `tier_discount_bp` that were selected, the `applied_personalization_bp`, the `retention_band` that was read, the resulting `quote_minor`, and a `line_breakdown` array showing the per-line arithmetic."

    Every rung sits on an identical North-American 1000-minor line, so the discount is
    shown to be a flat per-tier rate rather than a marginal rate accumulated across tiers.

    Design: Corner/calculations/corner_calc_tier_discount_boundaries_t1_to_t4
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_pt", region_code="NA")
    offer = create_draft_offer(
        season["id"],
        offer_type="BUNDLE",
        sku=f"TIER_{price_tier[-1]}",
        price_tier=price_tier,
        list_price_minor=1000,
        line_items=[_line(line_sku, 1000, 1400, "SOFT_COIN", 1400)],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )

    quote = _quote_as_designer(offer["id"], player["id"])

    assert quote["tier_discount_bp"] == expected_discount_bp
    assert quote["quote_minor"] == expected_quote_minor


# ---------------------------------------------------------------------------
# Fairness index: all three penalties firing at once
# ---------------------------------------------------------------------------
def test_all_three_fairness_penalties_subtract_without_drift() -> None:
    """PRD §3.5: "The value ratio in basis points is that declared value multiplied by 10000, divided by the offer's `list_price_minor`, rounded half up — so an offer that declares exactly the value it charges for scores 10000."
    PRD §3.5: "The scarcity penalty looks at the length of the merchandising window in whole hours, taken as the difference between `window_end` and `window_start` divided by 3600 and truncated downward: a window of 72 hours or longer draws no penalty, a window of at least 24 hours but shorter than 72 draws 500 basis points, and anything shorter than 24 hours draws 1200."
    PRD §3.5: "The minor-safety penalty is 800 basis points when the offer is a `LOOT_BOX` whose `minor_purchasable` flag is true, and 0 in every other case."
    PRD §3.5: "The personalization penalty is the offer's `personalization_discount_bp` divided by 5, rounded half up, then capped at 600 basis points."
    PRD §3.5: "The index is the value ratio minus all three penalties, then clamped into the range 0 through 15000 — negative results become 0 and results above 15000 become 15000."
    PRD §3.5: "Creation also records the authoring operator's `X-User-ID` as `created_by_user_id`, leaves `reviewed_by_user_id` null and `revision_count` at 0, sets `units_sold` and `pending_purchase_count` to 0, computes the fairness index described below, and sets `disclosure_state` — to `NOT_REQUIRED` for every `offer_type` other than `LOOT_BOX`, and to `REQUIRED_MISSING` for a `LOOT_BOX`, which is where it stays until a probability table has actually been published."
    PRD §3.5: "A newly created offer is `DRAFT` on the first dimension and `OFFLINE` on the second, and neither dimension ever moves the other implicitly: an offer can be re-reviewed while it sits live on the storefront, and it can be suspended and resumed without its approval ever being revisited."

    The 12-hour minor-purchasable randomized crate draws scarcity, minor-safety and
    personalization at once; the control crate shares its prices but draws none of them.

    Design: Corner/calculations/corner_calc_weighted_scoring_all_fairness_penalties
    """
    season = create_live_season()

    flash = create_draft_offer(
        season["id"],
        offer_type="LOOT_BOX",
        sku="FLASH_CRATE",
        price_tier="T1",
        list_price_minor=300,
        line_items=[_line("FLASH_KEY", 300, 400, "HARD_GEM", 300)],
        personalization_discount_bp=2000,
        minor_purchasable=True,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    calm = create_draft_offer(
        season["id"],
        offer_type="LOOT_BOX",
        sku="CALM_CRATE",
        price_tier="T1",
        list_price_minor=300,
        line_items=[_line("CALM_KEY", 300, 400, "HARD_GEM", 300)],
        personalization_discount_bp=0,
        minor_purchasable=False,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )

    assert flash["fairness_index_bp"] == 10933
    assert calm["fairness_index_bp"] == 13333
    assert flash["disclosure_state"] == "REQUIRED_MISSING"
    assert flash["availability_status"] == "OFFLINE"


# ---------------------------------------------------------------------------
# Cluster overlap load: the buffer lands only on the end of a window
# ---------------------------------------------------------------------------
def test_adjacent_buffered_windows_stay_disjoint_and_both_reserve() -> None:
    """PRD §3.3: "The cluster's `maintenance_buffer_minutes` is converted to seconds and appended to the **end** of every event's window and to no other side, so an event effectively occupies the half-open interval from its `window_start` up to but not including its `window_end` plus that buffer."
    PRD §3.3: "Two events overlap when the first one's start is strictly before the second one's buffered end and the second one's start is strictly before the first one's buffered end."
    PRD §3.3: "The event is admissible when that load is less than or equal to the cluster's `ccu_capacity`; a load exactly equal to capacity passes, and a load one greater is refused with `ERR_CLUSTER_CAPACITY_EXCEEDED`."
    PRD §3.3: "On success the event's `forecast_ccu` is snapshotted into `reserved_ccu_at_approval`, the cluster's `reserved_ccu` grows by that same figure, and the cluster's `version` moves by 1."

    The second event starts exactly on the first event's buffered end, so the strict
    comparison makes them disjoint and the two 6000-CCU reservations coexist on a
    10000-CCU cluster.

    Design: Corner/calculations/corner_calc_interval_merge_adjacent_windows_disjoint
    """
    season = create_live_season()
    cluster = create_cluster(
        name="NA-1", region_code="NA", ccu_capacity=10000, maintenance_buffer_minutes=30
    )
    event_a = create_planned_event(
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
        window_start="2026-08-05T02:30:00Z",
        window_end="2026-08-05T04:00:00Z",
        forecast_ccu=6000,
    )

    approved_a = validate_success(api_client.approve_live_event(event_a["id"], LIVEOPS))
    approved_b = validate_success(api_client.approve_live_event(event_b["id"], LIVEOPS))

    assert approved_a["status"] == "APPROVED"
    assert approved_b["status"] == "APPROVED"
    assert approved_b["reserved_ccu_at_approval"] == 6000
    assert read_cluster(cluster["id"])["reserved_ccu"] == 12000


# ---------------------------------------------------------------------------
# Cadence debt: slip days plus overdue days, and the posture flip
# ---------------------------------------------------------------------------
def test_cadence_debt_sums_slip_and_overdue_then_flips_posture() -> None:
    """PRD §3.2: "Whenever an episode is scheduled, released or rolled back — and again whenever a monitoring run computes — the season's `cadence_debt_days` is recomputed from scratch by walking every episode of the season in ascending `sequence_no` order (an order that is unique per season, so no tie-break is ever needed) and accumulating a running total of whole days."
    PRD §3.2: "An episode that is `LIVE` or `CONCLUDED` contributes the number of whole days by which its `actual_release_at` fell after its `planned_release_at`, truncated downward, and never less than zero, so an early or on-time drop contributes nothing."
    PRD §3.2: "An episode that is still `SCHEDULED` with a `planned_release_at` earlier than the current clock contributes the whole days that have elapsed since that instant, truncated downward."
    PRD §3.2: "The accumulated total is stored as `cadence_debt_days`, and `content_posture` becomes `BEHIND` when that total is strictly greater than 14 days and `ON_TRACK` otherwise."
    PRD §3.2: "On success the episode's `actual_release_at` is stamped with the clock, the season's `scheduled_episode_count` falls by 1 and its `released_episode_count` rises by 1, and any episode of the same season that is currently `LIVE` with a lower `sequence_no` is automatically carried from `LIVE` to `CONCLUDED` — the previous drop closing out as the new one opens, with `released_episode_count` unaffected by that automatic closure."
    PRD §3.2: "A successful schedule raises the season's `scheduled_episode_count` by 1, recomputes the season's `cadence_debt_days` and `content_posture`, and moves the season's `version` by 1."

    A three-day slip alone leaves the roadmap `ON_TRACK`; adding fifteen overdue days from a
    still-scheduled second drop takes the same running total to 18 and flips it to `BEHIND`.

    Design: Corner/calculations/corner_calc_cadence_debt_correct_result_and_posture_flip
    """
    season = create_live_season()
    season_id = season["id"]

    episode_1 = create_draft_episode(
        season_id,
        sequence_no=1,
        title="E1 Tidefall",
        planned_release_at="2026-08-02T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=0,
    )
    _schedule(episode_1["id"])
    episode_2 = create_draft_episode(
        season_id,
        sequence_no=2,
        title="E2 Undertow",
        planned_release_at="2026-08-10T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=0,
    )
    _schedule(episode_2["id"])
    set_clock("2026-08-05T00:00:00Z")

    released = validate_success(api_client.release_episode(episode_1["id"], PRODUCER))

    after_release = read_season(season_id)
    assert after_release["cadence_debt_days"] == 3
    assert after_release["content_posture"] == "ON_TRACK"
    assert released["actual_release_at"].startswith("2026-08-05T00:00:00")

    set_clock("2026-08-25T00:00:00Z")
    episode_3 = create_draft_episode(
        season_id,
        sequence_no=3,
        title="E3 Riptide",
        planned_release_at="2026-09-01T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=0,
    )
    _schedule(episode_3["id"])

    final = read_season(season_id)
    assert final["cadence_debt_days"] == 18
    assert final["content_posture"] == "BEHIND"
    assert final["scheduled_episode_count"] == 2
    assert final["released_episode_count"] == 1


def test_cadence_debt_walks_by_sequence_when_dates_run_backwards() -> None:
    """PRD §3.2: "Whenever an episode is scheduled, released or rolled back — and again whenever a monitoring run computes — the season's `cadence_debt_days` is recomputed from scratch by walking every episode of the season in ascending `sequence_no` order (an order that is unique per season, so no tie-break is ever needed) and accumulating a running total of whole days."
    PRD §3.2: "An episode that is still `SCHEDULED` with a `planned_release_at` earlier than the current clock contributes the whole days that have elapsed since that instant, truncated downward."
    PRD §3.2: "The accumulated total is stored as `cadence_debt_days`, and `content_posture` becomes `BEHIND` when that total is strictly greater than 14 days and `ON_TRACK` otherwise."
    PRD §3.2: "A successful schedule raises the season's `scheduled_episode_count` by 1, recomputes the season's `cadence_debt_days` and `content_posture`, and moves the season's `version` by 1."

    Sequence order and date order disagree — episode 1 is planned after episode 2 — yet the
    walk still charges only the five overdue days of the earlier-dated second drop.

    Design: Corner/calculations/corner_calc_chronological_out_of_order_planned_dates
    """
    season = create_live_season()
    season_id = season["id"]

    episode_1 = create_draft_episode(
        season_id,
        sequence_no=1,
        title="E1 Late Bloom",
        planned_release_at="2026-08-20T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=0,
    )
    _schedule(episode_1["id"])
    set_clock("2026-08-15T00:00:00Z")
    episode_2 = create_draft_episode(
        season_id,
        sequence_no=2,
        title="E2 Early Tide",
        planned_release_at="2026-08-10T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=0,
    )

    scheduled_2 = _schedule(episode_2["id"])

    assert scheduled_2["status"] == "SCHEDULED"
    assert scheduled_2["sequence_no"] == 2
    final = read_season(season_id)
    assert final["scheduled_episode_count"] == 2
    assert final["cadence_debt_days"] == 5
    assert final["content_posture"] == "ON_TRACK"
