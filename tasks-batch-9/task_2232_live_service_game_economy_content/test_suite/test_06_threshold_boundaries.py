"""Threshold arithmetic exercised exactly on its boundary and one step past it."""

from typing import Any, Dict, Tuple

from test_helpers import (
    LIVEOPS,
    ApiErrorId,
    api_client,
    append_adjustment,
    approve_offer,
    compute_monitoring_run,
    create_draft_offer,
    create_live_season,
    create_player,
    make_player_headers,
    offer_line_item,
    offer_version,
    open_account,
    open_monitoring_run,
    publish_offer,
    read_offer,
    read_player,
    read_season,
    set_clock,
    submit_offer,
    validate_error,
    validate_success,
)


def _setup_two_epoch_windows() -> Tuple[str, str]:
    """A LIVE season whose two epoch windows hold 400/1000 and 399/1000 respectively.

    Returns (season_id, epoch_1_run_id). The epoch-2 window rows are appended at
    2026-08-04 and 2026-08-05, so they fall outside the epoch-1 window entirely.
    """
    season = create_live_season()
    season_id = season["id"]

    player = create_player(season_id, handle="tide_p1")
    account = open_account(player["id"], "SOFT_COIN")

    append_adjustment(account["id"], "FAUCET", 1000, "EVENT_REWARD")
    append_adjustment(account["id"], "SINK", 400, "OFFER_SPEND")

    run1 = open_monitoring_run(
        season_id,
        epoch_no=1,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-02T00:00:00Z",
    )

    set_clock("2026-08-04T00:00:00Z")
    append_adjustment(account["id"], "FAUCET", 1000, "EVENT_REWARD")
    set_clock("2026-08-05T00:00:00Z")
    append_adjustment(account["id"], "SINK", 399, "OFFER_SPEND")

    return season_id, run1["id"]


def _setup_minor_cap_offer() -> Dict[str, Any]:
    """A verified minor buyer and a LIVE offer quoted at exactly the 5000 monthly ceiling."""
    season = create_live_season()
    season_id = season["id"]

    player = create_player(
        season_id, handle="tide_p10_minor", is_minor=True, guardian_verified=True
    )
    open_account(player["id"], "HARD_GEM")

    offer = create_draft_offer(
        season_id,
        offer_type="LIMITED_TIME",
        sku="STARTER_5K",
        price_tier="T1",
        list_price_minor=5000,
        line_items=[offer_line_item("STARTER_PACK", 5000, 6000, "HARD_GEM", 5000)],
        personalization_discount_bp=0,
        minor_purchasable=True,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    submit_offer(offer["id"])
    approve_offer(offer["id"])
    published = publish_offer(offer["id"], season_id)

    return {
        "season_id": season_id,
        "player_id": player["id"],
        "offer_id": offer["id"],
        "pinned_offer_version": published["version"],
    }


def _buy(ctx: Dict[str, Any], pinned_version: int):
    return api_client.create_purchase(
        {
            "player_id": ctx["player_id"],
            "offer_id": ctx["offer_id"],
            "expected_offer_version": pinned_version,
        },
        make_player_headers(ctx["player_id"]),
    )


class TestMonitoringRatioWatchFloor:
    def test_ratio_exactly_on_the_watch_floor_bands_as_watch(self):
        """PRD §3.9: "In both readings the candidate rows are the ledger entries attributed to the season, and the ratio itself is formed the same way: when the faucet total and the sink total are both zero the ratio is exactly 10000 basis points; when the faucet total is zero but sinks exist the ratio is 20000 basis points; otherwise it is the sink total multiplied by 10000, divided by the faucet total, rounded half up, and then capped at 20000."
        PRD §3.9: "The health band follows from the ratio: `HEALTHY` when the ratio is at least 6000 basis points, `WATCH` when it is at least 4000 but below 6000, and `INFLATED` when it is below 4000."
        PRD §3.9: "Only the rows whose `occurred_at` falls at or after the window start and strictly before the window end are considered, and on top of that every compensating pair is removed entirely — a row whose `reversal_of_entry_id` is set is dropped, and so is the row it points at."
        PRD §3.9: "The run's own `gross_faucet_minor`, `gross_sink_minor` and `sink_faucet_ratio_bp` are computed under the epoch-windowed reading over the run's own window, the run's `resulting_health` is derived from that ratio, and `computed_at` is stamped with the clock."

        Design: Difficulty/boundary_precision_check/monitoring_ratio_exactly_watch_floor_versus_ten_below
        """
        _season_id, run1_id = _setup_two_epoch_windows()

        run1 = validate_success(api_client.compute_monitoring_run(run1_id, LIVEOPS))
        assert run1["sink_faucet_ratio_bp"] == 4000, (
            "sinks of 400 against faucets of 1000 inside the epoch-1 window give exactly 4000 bp, "
            f"got {run1['sink_faucet_ratio_bp']}"
        )
        assert run1["resulting_health"] == "WATCH", (
            "the watch band is inclusive at its 4000 bp floor, so exactly 4000 bp is WATCH, got "
            f"{run1['resulting_health']}"
        )

    def test_ratio_ten_basis_points_below_the_watch_floor_bands_as_inflated(self):
        """PRD §3.9: "In both readings the candidate rows are the ledger entries attributed to the season, and the ratio itself is formed the same way: when the faucet total and the sink total are both zero the ratio is exactly 10000 basis points; when the faucet total is zero but sinks exist the ratio is 20000 basis points; otherwise it is the sink total multiplied by 10000, divided by the faucet total, rounded half up, and then capped at 20000."
        PRD §3.9: "The health band follows from the ratio: `HEALTHY` when the ratio is at least 6000 basis points, `WATCH` when it is at least 4000 but below 6000, and `INFLATED` when it is below 4000."
        PRD §3.9: "Only the rows whose `occurred_at` falls at or after the window start and strictly before the window end are considered, and on top of that every compensating pair is removed entirely — a row whose `reversal_of_entry_id` is set is dropped, and so is the row it points at."
        PRD §3.9: "At the first level, the season's `economy_health` is overwritten with the run's `resulting_health`, the season's `cadence_debt_days` and `content_posture` are recomputed, and the season's `version` moves by 1."

        Design: Difficulty/boundary_precision_check/monitoring_ratio_exactly_watch_floor_versus_ten_below
        """
        season_id, run1_id = _setup_two_epoch_windows()

        compute_monitoring_run(run1_id)
        run2 = open_monitoring_run(
            season_id,
            epoch_no=2,
            window_start="2026-08-04T00:00:00Z",
            window_end="2026-08-06T00:00:00Z",
        )
        computed = validate_success(api_client.compute_monitoring_run(run2["id"], LIVEOPS))

        assert computed["gross_faucet_minor"] == 1000, (
            "only the 2026-08-04 faucet row falls inside the epoch-2 window, got "
            f"{computed['gross_faucet_minor']}"
        )
        assert computed["gross_sink_minor"] == 399, (
            "only the 2026-08-05 sink row falls inside the epoch-2 window, got "
            f"{computed['gross_sink_minor']}"
        )
        assert computed["sink_faucet_ratio_bp"] == 3990, (
            "399 * 10000 / 1000 rounded half up is 3990 bp, got "
            f"{computed['sink_faucet_ratio_bp']}"
        )
        assert computed["resulting_health"] == "INFLATED", (
            "3990 bp is below the 4000 bp watch floor, so the band is INFLATED, got "
            f"{computed['resulting_health']}"
        )

        season = read_season(season_id)
        assert season["economy_health"] == "INFLATED", (
            "the season posture is overwritten with the newest run's band, got "
            f"{season['economy_health']}"
        )


class TestMinorSpendCapBoundary:
    def test_projected_exposure_exactly_on_the_cap_is_accepted(self):
        """PRD §3.7: "The minor spend ceiling behaves the other way round: at purchase creation, a player whose `is_minor` flag is true has a projected exposure formed as the sum of their current `spend_30d_minor`, their outstanding `pending_spend_minor`, and the `quoted_price_minor` of the purchase being created, and the purchase is refused with `ERR_MINOR_SPEND_CAP_EXCEEDED` only when that projected total is strictly greater than 5000 minor units — landing exactly on 5000 is allowed."
        PRD §3.6: "Walking the offer's `line_items` in ascending line `sku` order, each line is priced in two rounded steps: the gross line is that line's `base_price_minor` multiplied by the region multiplier, divided by 10000, and rounded half up; the net line is that gross line multiplied by the quantity 10000 minus the tier discount minus the personalization discount, divided by 10000, and rounded half up again."
        PRD §3.6: "On success the purchase is stored in `PENDING` with `quoted_price_minor` and `applied_personalization_bp` pinned from the quote just computed, `price_paid_minor` and `granted_total_minor` and `granted_consumed_minor` at 0, `settled_at` and `deny_reason` null, and `is_minor_purchase` snapshotted from the buyer's `is_minor` flag at this moment so that a later change to the account's minor status cannot rewrite history."
        PRD §3.6: "The offer's `pending_purchase_count` rises by 1 and its `version` moves by 1; the season's `pending_revenue_minor` and the player's `pending_spend_minor` each rise by the quoted price."

        Design: Difficulty/boundary_precision_check/minor_spend_cap_exact_equality_allowed_then_exceeded
        """
        ctx = _setup_minor_cap_offer()

        purchase = validate_success(_buy(ctx, ctx["pinned_offer_version"]), 201)
        assert purchase["quoted_price_minor"] == 5000, (
            "an NA buyer at tier T1 with no personalization is quoted the 5000 list price, got "
            f"{purchase['quoted_price_minor']}"
        )
        assert purchase["status"] == "PENDING", (
            "0 + 0 + 5000 lands exactly on the ceiling and is allowed, so the purchase must be "
            f"stored in PENDING, got {purchase['status']}"
        )
        assert purchase["is_minor_purchase"] is True, (
            "is_minor_purchase is snapshotted from the buyer's is_minor flag, got "
            f"{purchase['is_minor_purchase']}"
        )

        player = read_player(ctx["player_id"])
        assert player["pending_spend_minor"] == 5000, (
            f"the buyer's pending spend must rise by the quoted price, got {player['pending_spend_minor']}"
        )
        assert player["spend_30d_minor"] == 0, (
            "nothing has settled yet, so the trailing 30-day spend stays at 0, got "
            f"{player['spend_30d_minor']}"
        )

    def test_second_purchase_pushing_exposure_past_the_cap_is_refused(self):
        """PRD §3.7: "The minor spend ceiling behaves the other way round: at purchase creation, a player whose `is_minor` flag is true has a projected exposure formed as the sum of their current `spend_30d_minor`, their outstanding `pending_spend_minor`, and the `quoted_price_minor` of the purchase being created, and the purchase is refused with `ERR_MINOR_SPEND_CAP_EXCEEDED` only when that projected total is strictly greater than 5000 minor units — landing exactly on 5000 is allowed."
        PRD §3.6: "The offer's `pending_purchase_count` rises by 1 and its `version` moves by 1; the season's `pending_revenue_minor` and the player's `pending_spend_minor` each rise by the quoted price."

        Design: Difficulty/boundary_precision_check/minor_spend_cap_exact_equality_allowed_then_exceeded
        """
        ctx = _setup_minor_cap_offer()

        validate_success(_buy(ctx, ctx["pinned_offer_version"]), 201)

        error = validate_error(
            _buy(ctx, offer_version(ctx["offer_id"])),
            ApiErrorId.ERR_MINOR_SPEND_CAP_EXCEEDED.value,
            422,
        )
        assert error["error_id"] == ApiErrorId.ERR_MINOR_SPEND_CAP_EXCEEDED.value, (
            "0 + 5000 + 5000 is strictly greater than the 5000 ceiling, so the second purchase "
            f"must be refused with the spend-cap error, got {error['error_id']}"
        )

        offer = read_offer(ctx["offer_id"])
        assert offer["pending_purchase_count"] == 1, (
            "only the first purchase was accepted, so the pending count stays at 1, got "
            f"{offer['pending_purchase_count']}"
        )

        season = read_season(ctx["season_id"])
        assert season["pending_revenue_minor"] == 5000, (
            "the season's pending revenue reflects only the accepted purchase, got "
            f"{season['pending_revenue_minor']}"
        )
