"""Arithmetic corners of the episode-grant selector, the refund waterfall, the rolling-spend
bands and the two pacing readings.

Every test builds its own world from scratch: the harness wipes the server database before
each test, so no cross-test state is shared.
"""

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE,
    LIVEOPS,
    PRODUCER,
    api_client,
    append_adjustment,
    approve_offer,
    create_draft_episode,
    create_draft_offer,
    create_live_season,
    create_pending_purchase,
    create_player,
    get_success_data,
    ingest_xp,
    open_account,
    publish_offer,
    read_account,
    read_player,
    read_season,
    set_clock,
    settle_purchase,
    submit_offer,
    submit_refund,
    validate_success,
)


# ---------------------------------------------------------------------------
# Local helpers (private to this module — test_helpers is shared and read-only)
# ---------------------------------------------------------------------------
def _schedule(episode_id: str) -> Dict[str, Any]:
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


def _publish_live_offer(season_id: str, **offer_overrides) -> Dict[str, Any]:
    """Author, submit, approve and publish one offer, pinning the season version at publish."""
    offer = create_draft_offer(season_id, **offer_overrides)
    submit_offer(offer["id"])
    approve_offer(offer["id"])
    return publish_offer(offer["id"], season_id)


def _pacing(player_id: str, variant: str) -> Dict[str, Any]:
    return validate_success(api_client.get_pacing(player_id, LIVEOPS, params={"variant": variant}))


# ---------------------------------------------------------------------------
# Episode grant selector
# ---------------------------------------------------------------------------
def test_grant_selector_filters_currency_and_season_and_tolerates_empty_pool() -> None:
    """PRD §3.2: "At the first level, the recipient set is selected: every currency account whose `currency_code` is `SOFT_COIN`, whose `status` is `ACTIVE`, whose owning player's `active_season_id` is the episode's season, and whose owning player's `spend_state` is anything other than `LOCKED`."
    PRD §3.2: "Hard-gem and event-token accounts are never episode-grant recipients."
    PRD §3.2: "For each recipient in that order a ledger entry is appended with `direction` `FAUCET`, `source_kind` `EPISODE_GRANT`, an `amount_minor` equal to the episode's `soft_currency_grant_minor` — every recipient receives exactly that amount, with no proration — and the episode's season as `season_id`; the episode's `grant_batch_size` records how many entries were appended."
    PRD §3.2: "At the second level, because those entries now exist, each recipient account's `lifetime_faucet_minor` grows by the granted amount, its `balance_minor` is recomputed as lifetime faucet minus lifetime sink, and its `version` moves by 1."
    PRD §3.2: "At the third level, because those account totals changed, the season's `gross_faucet_minor` grows by `grant_batch_size` multiplied by `soft_currency_grant_minor`."
    PRD §3.2: "An empty recipient pool is not an error: the release succeeds, `grant_batch_size` is 0, and no ledger entries are appended."
    PRD §3.9: "In both readings the candidate rows are the ledger entries attributed to the season, and the ratio itself is formed the same way: when the faucet total and the sink total are both zero the ratio is exactly 10000 basis points; when the faucet total is zero but sinks exist the ratio is 20000 basis points; otherwise it is the sink total multiplied by 10000, divided by the faucet total, rounded half up, and then capped at 20000."

    Two concurrent seasons run side by side: the first releases to exactly one recipient
    (its buyer's hard-gem account and the other season's player are both skipped), while the
    second releases to nobody at all and still succeeds.

    Design: Corner/calculations/corner_calc_grant_selector_filters_and_empty_pool
    """
    season_7 = create_live_season()
    season_8 = create_live_season(
        set_clock_first=False, code="S8", title="Season 8 Shoreline"
    )

    player_1 = create_player(season_7["id"], handle="tide_p1", region_code="NA")
    p1_soft = open_account(player_1["id"], "SOFT_COIN")
    p1_gem = open_account(player_1["id"], "HARD_GEM")
    player_2 = create_player(season_8["id"], handle="shore_p2", region_code="EU")
    p2_gem = open_account(player_2["id"], "HARD_GEM")

    episode_7 = create_draft_episode(
        season_7["id"],
        sequence_no=1,
        title="E7 Tidefall",
        planned_release_at="2026-08-02T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=1200,
    )
    _schedule(episode_7["id"])
    episode_8 = create_draft_episode(
        season_8["id"],
        sequence_no=1,
        title="E8 Shorebreak",
        planned_release_at="2026-08-02T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=900,
    )
    _schedule(episode_8["id"])
    set_clock("2026-08-02T00:00:00Z")

    released_7 = validate_success(api_client.release_episode(episode_7["id"], PRODUCER))
    released_8 = validate_success(api_client.release_episode(episode_8["id"], PRODUCER))

    assert released_7["grant_batch_size"] == 1
    assert read_account(p1_soft["id"])["balance_minor"] == 1200
    assert read_account(p1_gem["id"])["balance_minor"] == 0
    assert read_account(p2_gem["id"])["balance_minor"] == 0
    assert read_season(season_7["id"])["gross_faucet_minor"] == 1200

    assert released_8["status"] == "LIVE"
    assert released_8["grant_batch_size"] == 0
    season_8_final = read_season(season_8["id"])
    assert season_8_final["gross_faucet_minor"] == 0
    assert season_8_final["lifetime_ratio_bp"] == 10000


# ---------------------------------------------------------------------------
# Refund settlement arithmetic
# ---------------------------------------------------------------------------
def test_goodwill_credit_rounds_a_half_unit_up() -> None:
    """PRD §3.7: "**Step two** computes `refund_base_minor`: the purchase's `price_paid_minor` multiplied by the quantity 10000 minus `consumed_ratio_bp`, divided by 10000, rounded half up."
    PRD §3.7: "**Step three** selects the restocking fee tier, and it is keyed on the Step-two figure and on nothing else: the tier is 0 basis points when `refund_base_minor` is strictly below 1000 minor units, 500 basis points when it is at least 1000 but strictly below 5000, and 1000 basis points at 5000 or above."
    PRD §3.7: "**Step four** computes `restock_fee_minor`: `refund_base_minor` multiplied by that tier, divided by 10000, rounded half up."
    PRD §3.7: "**Step five** computes `refund_amount_minor`: `refund_base_minor` minus `restock_fee_minor`, floored at 0."
    PRD §3.7: "**Step six** computes `goodwill_credit_minor`: half of the restocking fee — that is, `restock_fee_minor` multiplied by 5000, divided by 10000, rounded half up — but only when the player holds a currency account whose `currency_code` is `SOFT_COIN` and the player's `spend_state` is not `LOCKED`; when either condition fails the goodwill credit is 0."
    PRD §2.6: "Rounding half up means a fractional remainder of exactly one half moves away from zero to the next integer."
    PRD §3.6: "On the purchase itself, `price_paid_minor` is copied from `quoted_price_minor` and `settled_at` is stamped with the clock."

    A 1700-minor base draws an 85-minor restocking fee, whose half share lands on exactly
    42.5 — banker's rounding would answer 42, so this single value pins the rounding mode.

    Design: Corner/calculations/corner_calc_precision_goodwill_half_up_rounding
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_pm", region_code="NA")
    open_account(player["id"], "HARD_GEM")
    open_account(player["id"], "SOFT_COIN")

    offer = _publish_live_offer(
        season["id"],
        offer_type="LIMITED_TIME",
        sku="MID_1700",
        price_tier="T1",
        list_price_minor=1700,
        line_items=[_line("MID_HOARD", 1700, 2100, "HARD_GEM", 1700)],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    purchase = create_pending_purchase(player["id"], offer["id"])
    settled = settle_purchase(purchase["id"])
    request = submit_refund(purchase["id"], player["id"], "ACCIDENTAL")

    decided = validate_success(
        api_client.decide_refund_request(
            request["id"],
            {"decision": "APPROVE", "decision_note": "Accidental purchase"},
            COMPLIANCE,
        )
    )

    assert settled["price_paid_minor"] == 1700
    assert decided["refund_base_minor"] == 1700
    assert decided["restock_fee_minor"] == 85
    assert decided["refund_amount_minor"] == 1615
    assert decided["goodwill_credit_minor"] == 43
    assert decided["goodwill_credit_minor"] != 42


def test_partial_consumption_reduces_the_base_the_fee_is_charged_on() -> None:
    """PRD §3.7: "**Step one** computes `consumed_ratio_bp`: the purchase's `granted_consumed_minor` multiplied by 10000, divided by its `granted_total_minor` — or by 1 if that total is 0, so that a purchase which granted nothing does not divide by zero — rounded half up, then capped at 10000."
    PRD §3.7: "**Step two** computes `refund_base_minor`: the purchase's `price_paid_minor` multiplied by the quantity 10000 minus `consumed_ratio_bp`, divided by 10000, rounded half up."
    PRD §3.7: "**Step three** selects the restocking fee tier, and it is keyed on the Step-two figure and on nothing else: the tier is 0 basis points when `refund_base_minor` is strictly below 1000 minor units, 500 basis points when it is at least 1000 but strictly below 5000, and 1000 basis points at 5000 or above."
    PRD §3.7: "**Step four** computes `restock_fee_minor`: `refund_base_minor` multiplied by that tier, divided by 10000, rounded half up."
    PRD §3.7: "**Step five** computes `refund_amount_minor`: `refund_base_minor` minus `restock_fee_minor`, floored at 0."
    PRD §3.7: "**Step six** computes `goodwill_credit_minor`: half of the restocking fee — that is, `restock_fee_minor` multiplied by 5000, divided by 10000, rounded half up — but only when the player holds a currency account whose `currency_code` is `SOFT_COIN` and the player's `spend_state` is not `LOCKED`; when either condition fails the goodwill credit is 0."
    PRD §3.4: "One adjustment shape has an extra consequence: when a `purchase_id` is supplied together with `direction` `SINK` and `source_kind` `OFFER_SPEND`, the named purchase's `granted_consumed_minor` grows by the same amount, which is how the system learns that a player has spent what a bundle granted them — and, as §3.7 shows, that consumption is precisely what makes a later refund smaller."
    PRD §3.6: "Then, for each entry of the offer's `line_items` taken in ascending line `sku` order, a ledger entry is appended with `direction` `FAUCET`, `source_kind` `PURCHASE_GRANT`, an `amount_minor` equal to that line's `granted_amount_minor`, the purchase as its `purchase_id`, and the offer's season as its `season_id`; the purchase's `granted_total_minor` becomes the sum of those amounts."
    PRD §3.6: "On the purchase itself, `price_paid_minor` is copied from `quoted_price_minor` and `settled_at` is stamped with the clock."
    PRD §2.8: "The credited or debited account's `lifetime_faucet_minor` or `lifetime_sink_minor` grows by the entry's `amount_minor`, and its `balance_minor` is then recomputed as lifetime faucet total minus lifetime sink total — a quantity that is never allowed to go negative."

    Spending 300 of 1200 granted tokens consumes a quarter of the grant, so the restocking
    fee is charged on the reduced 1306 base rather than on the 1741 price actually paid, and
    the buyer holds no soft-coin account for a goodwill credit to land in.

    Design: Corner/calculations/corner_calc_waterfall_partial_consumption_reduces_base
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_pe", region_code="EU")
    token_account = open_account(player["id"], "EVENT_TOKEN")

    offer = _publish_live_offer(
        season["id"],
        offer_type="BUNDLE",
        sku="AUG_BUNDLE",
        price_tier="T3",
        list_price_minor=1798,
        line_items=[
            _line("COIN_PACK", 499, 700, "EVENT_TOKEN", 600),
            _line("SKIN_A", 1299, 1700, "EVENT_TOKEN", 600),
        ],
        personalization_discount_bp=1500,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    purchase = create_pending_purchase(player["id"], offer["id"])
    settled = settle_purchase(purchase["id"])
    append_adjustment(
        token_account["id"],
        direction="SINK",
        amount_minor=300,
        source_kind="OFFER_SPEND",
        purchase_id=purchase["id"],
    )
    request = submit_refund(purchase["id"], player["id"], "DISSATISFIED")

    decided = validate_success(
        api_client.decide_refund_request(
            request["id"],
            {"decision": "APPROVE", "decision_note": "Partial goodwill refund"},
            COMPLIANCE,
        )
    )

    assert settled["price_paid_minor"] == 1741
    assert settled["granted_total_minor"] == 1200
    consumed = validate_success(api_client.get_purchase(purchase["id"], LIVEOPS))
    assert consumed["granted_consumed_minor"] == 300

    assert decided["consumed_ratio_bp"] == 2500
    assert decided["refund_base_minor"] == 1306
    assert decided["restock_fee_minor"] == 65
    assert decided["refund_amount_minor"] == 1241
    assert decided["goodwill_credit_minor"] == 0
    assert read_account(token_account["id"])["balance_minor"] == 900


# ---------------------------------------------------------------------------
# Rolling spend bands at their exact edges
# ---------------------------------------------------------------------------
def test_rolling_spend_lands_on_each_band_edge_exactly() -> None:
    """PRD §3.7: "The rolling spend figure is computed by taking the window that begins 30 days before the current clock and ends at the clock itself, summing the `price_paid_minor` of every purchase of that player whose `status` is `SETTLED` or `REFUNDED` and whose `settled_at` falls inside that window with both ends inclusive, then subtracting the `refund_amount_minor` of every refund request in `EXECUTED` status against that player's purchases whose `executed_at` falls inside the same inclusive window, and finally flooring the result at 0 so it can never go negative."
    PRD §3.7: "A player enters the cooldown band when `spend_30d_minor` reaches or exceeds 40000 minor units while remaining below 75000, and enters the lock band when it reaches or exceeds 75000; both boundaries are inclusive, so exactly 40000 is already cooldown and exactly 75000 is already lock."
    PRD §3.7: "The system moves a player `UNRESTRICTED → COOLDOWN` when a recompute — triggered either by a settlement or by a monitoring run — lands the recomputed `spend_30d_minor` in the cooldown band, and that move only touches the player's `version`."
    PRD §3.7: "The system moves a player `UNRESTRICTED → LOCKED` or `COOLDOWN → LOCKED` when a settlement recompute pushes `spend_30d_minor` into the lock band, and a `ComplianceOfficer` can force the same landing at any time by supplying an `action` of `LOCK`, optionally with a `note`."
    PRD §3.6: "On the player, `pending_spend_minor` falls by the quoted price, `lifetime_spend_minor` rises by the price paid, `spend_30d_minor` is recomputed, `spend_state` is re-evaluated against the responsible-spending thresholds, `pacing_bp_realized` and `retention_band` are recomputed, and `version` moves by 1."
    PRD §3.6: "On the season, `pending_revenue_minor` falls by the quoted price, `settled_revenue_minor` rises by the price paid, and `version` moves by 1."
    PRD §3.6: "Each credited account's `lifetime_faucet_minor` and `balance_minor` are updated, the season's `gross_faucet_minor` grows by `granted_total_minor`, and the season's `lifetime_ratio_bp` is recomputed."

    Both thresholds are hit dead-on: the first settlement lands rolling spend on exactly
    40000 and the second on exactly 75000, so an inclusive comparison is required at each edge.

    Design: Corner/calculations/corner_calc_threshold_spend_bands_at_exact_limits
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_ph", region_code="NA")
    gem_account = open_account(player["id"], "HARD_GEM")

    whale = _publish_live_offer(
        season["id"],
        offer_type="LIMITED_TIME",
        sku="WHALE_40K",
        price_tier="T1",
        list_price_minor=40000,
        line_items=[_line("WHALE_HOARD", 40000, 50000, "HARD_GEM", 40000)],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    top = _publish_live_offer(
        season["id"],
        offer_type="LIMITED_TIME",
        sku="TOP_35K",
        price_tier="T1",
        list_price_minor=35000,
        line_items=[_line("TOP_HOARD", 35000, 40000, "HARD_GEM", 35000)],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )

    whale_purchase = create_pending_purchase(player["id"], whale["id"])
    settle_purchase(whale_purchase["id"])

    after_first = read_player(player["id"])
    assert after_first["spend_30d_minor"] == 40000
    assert after_first["spend_state"] == "COOLDOWN"

    top_purchase = create_pending_purchase(player["id"], top["id"])
    settle_purchase(top_purchase["id"])

    after_second = read_player(player["id"])
    assert after_second["spend_30d_minor"] == 75000
    assert after_second["spend_state"] == "LOCKED"
    assert after_second["lifetime_spend_minor"] == 75000
    assert read_account(gem_account["id"])["balance_minor"] == 75000
    assert read_season(season["id"])["settled_revenue_minor"] == 75000


# ---------------------------------------------------------------------------
# Forward-looking pacing projection
# ---------------------------------------------------------------------------
def test_projected_pacing_reacts_when_a_scheduled_drop_ships() -> None:
    """PRD §3.4: "The **projected** reading is a full-season forecast that absorbs content not yet shipped: it adds to the player's `season_xp_total` the sum of the `xp_grant` of every episode of the player's active season that is currently `SCHEDULED` and whose `planned_release_at` is at or after the current clock — overdue scheduled drops are excluded from that sum — then multiplies the total by 10000, divides by the season's full `target_xp_total`, rounds half up, and caps at 20000 basis points."
    PRD §3.4: "The season's total length in whole days is the difference between `ends_at` and `starts_at` divided by 86400 and truncated downward."
    PRD §3.4: "Elapsed days are the difference between the current clock and `starts_at`, divided by 86400 and truncated downward, then clamped so that the figure is never below 0 and never above the season's total days."
    PRD §3.4: "The experience the player was expected to have earned by now is the season's `target_xp_total` multiplied by elapsed days, divided by that total-days figure, and rounded half up."
    PRD §3.4: "Otherwise it is the player's `season_xp_total` multiplied by 10000, divided by the expected-to-date figure, rounded half up, and then capped at 20000 basis points."
    PRD §3.4: "This is the reading that is persisted into `pacing_bp_realized`, and it is recomputed and stored whenever engagement telemetry is ingested, whenever a purchase settles, and whenever a monitoring run computes."
    PRD §3.4: "It answers with the `player_id`, the `variant` evaluated, the `elapsed_days` and `season_total_days` it derived, the `expected_to_date_xp` denominator, the `eligible_scheduled_xp` it summed (relevant to the projected reading), the player's current `season_xp_total`, the resulting `pacing_bp`, and the `retention_band` that figure maps to."
    PRD §3.4: "The player's `season_xp_total` grows by the experience delta, `session_count` grows by the session delta, and `last_active_at` is set to the `occurred_at` of the ingest."

    The pipeline term is re-read on every call: while the second drop is still scheduled for
    a future date its 600 XP counts as pending, and once it ships the pending term falls to
    zero while the realized total absorbs the same 600, so the projection holds its value for
    an entirely different reason. The overdue first drop is excluded throughout.

    Design: Corner/calculations/corner_calc_forward_looking_projection_reacts_to_release
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_pj", region_code="NA")

    episode_1 = create_draft_episode(
        season["id"],
        sequence_no=1,
        title="E1 Tidefall",
        planned_release_at="2026-08-10T00:00:00Z",
        xp_grant=5000,
        soft_currency_grant_minor=0,
    )
    _schedule(episode_1["id"])
    episode_2 = create_draft_episode(
        season["id"],
        sequence_no=2,
        title="E2 Undertow",
        planned_release_at="2026-09-05T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=0,
    )
    _schedule(episode_2["id"])
    set_clock("2026-08-31T00:00:00Z")
    ingest_xp(player["id"], 2400, 10)

    first_projected = _pacing(player["id"], "PROJECTED")
    assert first_projected["eligible_scheduled_xp"] == 600
    assert first_projected["season_xp_total"] == 2400
    assert first_projected["pacing_bp"] == 3333

    set_clock("2026-09-05T00:00:00Z")
    released = validate_success(api_client.release_episode(episode_2["id"], PRODUCER))
    assert released["status"] == "LIVE"
    ingest_xp(player["id"], 600, 2)

    second_projected = _pacing(player["id"], "PROJECTED")
    assert second_projected["eligible_scheduled_xp"] == 0
    assert second_projected["season_xp_total"] == 3000
    assert second_projected["pacing_bp"] == 3333

    realized = _pacing(player["id"], "REALIZED")
    assert realized["elapsed_days"] == 35
    assert realized["expected_to_date_xp"] == 3500
    assert realized["pacing_bp"] == 8571
    assert read_player(player["id"])["pacing_bp_realized"] == 8571
