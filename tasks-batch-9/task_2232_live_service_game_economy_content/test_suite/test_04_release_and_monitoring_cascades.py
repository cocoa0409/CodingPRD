"""Multi-level cascades that fan out from a single episode release or monitoring compute."""

from typing import Any, Dict

from test_helpers import (
    LIVEOPS,
    PRODUCER,
    api_client,
    append_adjustment,
    approve_offer,
    create_draft_offer,
    create_live_season,
    create_pending_purchase,
    create_player,
    create_scheduled_episode,
    disclosure_entry,
    draft_disclosure,
    lock_player,
    offer_line_item,
    open_account,
    open_monitoring_run,
    publish_disclosure,
    publish_offer,
    read_account,
    read_offer,
    read_player,
    read_purchase,
    read_season,
    set_clock,
    submit_offer,
    validate_success,
)


def _setup_episode_release_cascade() -> Dict[str, Any]:
    """LIVE season with two eligible SOFT_COIN holders, one locked holder, and a due episode.

    Player p1's account already carries an operator faucet of 1000 and an operator sink of
    500, so the season opens the release with gross faucet 1000 and gross sink 500.
    """
    season = create_live_season()
    season_id = season["id"]

    p1 = create_player(season_id, handle="tide_p1")
    p1_soft = open_account(p1["id"], "SOFT_COIN")
    append_adjustment(p1_soft["id"], "FAUCET", 1000, "EVENT_REWARD")
    append_adjustment(p1_soft["id"], "SINK", 500, "OFFER_SPEND")

    p2 = create_player(season_id, handle="tide_p2")
    p2_soft = open_account(p2["id"], "SOFT_COIN")

    p5 = create_player(season_id, handle="tide_p5")
    p5_soft = open_account(p5["id"], "SOFT_COIN")
    lock_player(p5["id"], note="Chargeback investigation")

    episode = create_scheduled_episode(season_id)
    set_clock("2026-08-02T00:00:00Z")

    return {
        "season_id": season_id,
        "episode_id": episode["id"],
        "p1_soft_id": p1_soft["id"],
        "p2_soft_id": p2_soft["id"],
        "p5_soft_id": p5_soft["id"],
    }


def _setup_inflation_monitoring_cascade() -> Dict[str, Any]:
    """LIVE season with a LIVE loot-box offer, one PENDING purchase of it, and an open epoch.

    Inside the epoch window the season has seen faucets of 1000 against sinks of 100.
    """
    season = create_live_season()
    season_id = season["id"]

    p6 = create_player(season_id, handle="tide_p6")
    open_account(p6["id"], "HARD_GEM")
    p6_soft = open_account(p6["id"], "SOFT_COIN")
    append_adjustment(p6_soft["id"], "FAUCET", 1000, "EVENT_REWARD")
    append_adjustment(p6_soft["id"], "SINK", 100, "OFFER_SPEND")

    crate = create_draft_offer(
        season_id,
        offer_type="LOOT_BOX",
        sku="GEM_CRATE",
        price_tier="T1",
        list_price_minor=300,
        line_items=[offer_line_item("CRATE_KEY", 300, 400, "HARD_GEM", 300)],
        personalization_discount_bp=0,
        minor_purchasable=False,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    disclosure = draft_disclosure(
        crate["id"],
        entries=[
            disclosure_entry("C_COMMON", 8500, 200, False),
            disclosure_entry("C_RARE", 1400, 1500, False),
            disclosure_entry("C_MYTHIC", 100, 9000, True),
        ],
    )
    publish_disclosure(crate["id"], disclosure["id"])
    submit_offer(crate["id"])
    approve_offer(crate["id"])
    publish_offer(crate["id"], season_id)

    purchase = create_pending_purchase(p6["id"], crate["id"])
    run = open_monitoring_run(
        season_id,
        epoch_no=1,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-02T00:00:00Z",
    )

    return {
        "season_id": season_id,
        "player_id": p6["id"],
        "offer_id": crate["id"],
        "purchase_id": purchase["id"],
        "run_id": run["id"],
    }


class TestEpisodeReleaseFaucetCascade:
    def test_release_grants_only_eligible_soft_coin_accounts(self):
        """PRD §3.2: "At the first level, the recipient set is selected: every currency account whose `currency_code` is `SOFT_COIN`, whose `status` is `ACTIVE`, whose owning player's `active_season_id` is the episode's season, and whose owning player's `spend_state` is anything other than `LOCKED`."
        PRD §3.2: "For each recipient in that order a ledger entry is appended with `direction` `FAUCET`, `source_kind` `EPISODE_GRANT`, an `amount_minor` equal to the episode's `soft_currency_grant_minor` — every recipient receives exactly that amount, with no proration — and the episode's season as `season_id`; the episode's `grant_batch_size` records how many entries were appended."
        PRD §3.2: "At the second level, because those entries now exist, each recipient account's `lifetime_faucet_minor` grows by the granted amount, its `balance_minor` is recomputed as lifetime faucet minus lifetime sink, and its `version` moves by 1."
        PRD §3.4: "Each account records its owner as `player_id`, opens `ACTIVE` with `balance_minor`, `lifetime_faucet_minor` and `lifetime_sink_minor` all at 0, and its `status` thereafter tracks the owning player: an account is `FROZEN` for exactly as long as its player's `spend_state` is `LOCKED`."

        Design: Difficulty/transitive_cascade/episode_release_faucet_cascade_to_season_ratio
        """
        ctx = _setup_episode_release_cascade()

        episode = validate_success(api_client.release_episode(ctx["episode_id"], PRODUCER))
        assert episode["grant_batch_size"] == 2, (
            "Only the two unlocked ACTIVE SOFT_COIN accounts are recipients, so "
            f"grant_batch_size must be 2, got {episode['grant_batch_size']}"
        )

        p1_soft = read_account(ctx["p1_soft_id"])
        assert p1_soft["lifetime_faucet_minor"] == 2200, (
            "p1's lifetime faucet must be the operator faucet of 1000 plus the 1200 grant, "
            f"got {p1_soft['lifetime_faucet_minor']}"
        )
        assert p1_soft["balance_minor"] == 1700, (
            "p1's balance must be lifetime faucet 2200 minus lifetime sink 500, "
            f"got {p1_soft['balance_minor']}"
        )

        p2_soft = read_account(ctx["p2_soft_id"])
        assert p2_soft["balance_minor"] == 1200, (
            f"p2 receives exactly the 1200 grant with no proration, got {p2_soft['balance_minor']}"
        )

        p5_soft = read_account(ctx["p5_soft_id"])
        assert p5_soft["status"] == "FROZEN", (
            f"the locked player's account must be FROZEN, got {p5_soft['status']}"
        )
        assert p5_soft["balance_minor"] == 0, (
            "the FROZEN account of the LOCKED player is excluded from the recipient set, so its "
            f"balance must stay 0, got {p5_soft['balance_minor']}"
        )

    def test_release_cascade_moves_season_totals_and_lifetime_ratio(self):
        """PRD §3.2: "At the third level, because those account totals changed, the season's `gross_faucet_minor` grows by `grant_batch_size` multiplied by `soft_currency_grant_minor`."
        PRD §3.2: "At the fourth level, because the season's gross faucet total changed, the season's `lifetime_ratio_bp` is recomputed under the lifetime-cumulative reading described in §3.9."
        PRD §3.9: "In both readings the candidate rows are the ledger entries attributed to the season, and the ratio itself is formed the same way: when the faucet total and the sink total are both zero the ratio is exactly 10000 basis points; when the faucet total is zero but sinks exist the ratio is 20000 basis points; otherwise it is the sink total multiplied by 10000, divided by the faucet total, rounded half up, and then capped at 20000."
        PRD §3.4: "On success a ledger entry is appended, attributed to the owning player's `active_season_id` as its `season_id`, and the full ledger fan-out of §2.8 runs: the account's lifetime totals and `balance_minor` move, the season's `gross_faucet_minor` or `gross_sink_minor` moves, the season's `lifetime_ratio_bp` is recomputed, and the account's `version` moves by 1."
        PRD §3.2: "On success the episode's `actual_release_at` is stamped with the clock, the season's `scheduled_episode_count` falls by 1 and its `released_episode_count` rises by 1, and any episode of the same season that is currently `LIVE` with a lower `sequence_no` is automatically carried from `LIVE` to `CONCLUDED` — the previous drop closing out as the new one opens, with `released_episode_count` unaffected by that automatic closure."

        Design: Difficulty/transitive_cascade/episode_release_faucet_cascade_to_season_ratio
        """
        ctx = _setup_episode_release_cascade()

        validate_success(api_client.release_episode(ctx["episode_id"], PRODUCER))

        season = read_season(ctx["season_id"])
        assert season["gross_faucet_minor"] == 3400, (
            "the season's gross faucet must be the operator faucet of 1000 plus 2 recipients "
            f"times 1200, got {season['gross_faucet_minor']}"
        )
        assert season["gross_sink_minor"] == 500, (
            "an episode release appends no sink rows, so gross sink stays at the operator sink "
            f"of 500, got {season['gross_sink_minor']}"
        )
        assert season["lifetime_ratio_bp"] == 1471, (
            "lifetime_ratio_bp must be 500 * 10000 / 3400 rounded half up, i.e. 1471, got "
            f"{season['lifetime_ratio_bp']}"
        )
        assert season["released_episode_count"] == 1, (
            f"the released episode count must rise to 1, got {season['released_episode_count']}"
        )


class TestMonitoringComputeInflationCascade:
    def test_compute_suspends_live_loot_box_when_ratio_lands_inflated(self):
        """PRD §3.9: "The run's own `gross_faucet_minor`, `gross_sink_minor` and `sink_faucet_ratio_bp` are computed under the epoch-windowed reading over the run's own window, the run's `resulting_health` is derived from that ratio, and `computed_at` is stamped with the clock."
        PRD §3.9: "The health band follows from the ratio: `HEALTHY` when the ratio is at least 6000 basis points, `WATCH` when it is at least 4000 but below 6000, and `INFLATED` when it is below 4000."
        PRD §3.9: "At the first level, the season's `economy_health` is overwritten with the run's `resulting_health`, the season's `cadence_debt_days` and `content_posture` are recomputed, and the season's `version` moves by 1."
        PRD §3.9: "At the second level, if and only if the season's `economy_health` has become `INFLATED`, every offer of that season whose `offer_type` is `LOOT_BOX` and whose `availability_status` is `LIVE` is carried `LIVE → SUSPENDED`, processed in ascending `created_at` order; the run's `suspended_offer_count` records how many were suspended, and the season's `live_offer_count` falls by one per suspended offer."
        PRD §3.5: "A newly created offer is `DRAFT` on the first dimension and `OFFLINE` on the second, and neither dimension ever moves the other implicitly: an offer can be re-reviewed while it sits live on the storefront, and it can be suspended and resumed without its approval ever being revisited."

        Design: Difficulty/transitive_cascade/monitoring_compute_suspends_lootbox_and_denies_pending_purchase
        """
        ctx = _setup_inflation_monitoring_cascade()

        run = validate_success(api_client.compute_monitoring_run(ctx["run_id"], LIVEOPS))
        assert run["sink_faucet_ratio_bp"] == 1000, (
            "sinks of 100 against faucets of 1000 inside the epoch window give 1000 bp, got "
            f"{run['sink_faucet_ratio_bp']}"
        )
        assert run["resulting_health"] == "INFLATED", (
            f"1000 bp is below the 4000 bp watch floor, so the band is INFLATED, got {run['resulting_health']}"
        )
        assert run["suspended_offer_count"] == 1, (
            f"the single LIVE loot box must be suspended, got {run['suspended_offer_count']}"
        )

        season = read_season(ctx["season_id"])
        assert season["economy_health"] == "INFLATED", (
            f"the season posture must be overwritten with the run's band, got {season['economy_health']}"
        )
        assert season["live_offer_count"] == 0, (
            f"live_offer_count must fall by one per suspended offer, got {season['live_offer_count']}"
        )

        offer = read_offer(ctx["offer_id"])
        assert offer["availability_status"] == "SUSPENDED", (
            f"the loot-box offer must be carried LIVE to SUSPENDED, got {offer['availability_status']}"
        )
        assert offer["approval_status"] == "APPROVED", (
            "the governance dimension is untouched by a storefront suspension, got "
            f"{offer['approval_status']}"
        )

    def test_compute_denies_pending_purchase_of_the_suspended_offer(self):
        """PRD §3.9: "At the third level, because those offers became `SUSPENDED`, every purchase of them still in `PENDING` is denied with the `deny_reason` `OFFER_SUSPENDED_BY_MONITORING`, and the run's `denied_purchase_count` records how many were denied."
        PRD §3.9: "At the fourth level, because those purchases were denied, the season's `pending_revenue_minor` and each affected buyer's `pending_spend_minor` are each lowered by the denied purchase's `quoted_price_minor`."
        PRD §3.6: "The supplied `deny_reason` is recorded, the season's `pending_revenue_minor` and the player's `pending_spend_minor` each fall by the purchase's `quoted_price_minor`, the offer's `pending_purchase_count` falls by 1, and the `version` of the offer, the season and the player each move by 1."
        PRD §3.6: "The same `PENDING → DENIED` transition also occurs as a system cascade in four situations, each writing its own `deny_reason`: an offer being withdrawn (`OFFER_WITHDRAWN`), a season concluding (`SEASON_CONCLUDED`), a player being locked (`SPEND_LOCKED`), and an offer being suspended by an inflation monitoring run (`OFFER_SUSPENDED_BY_MONITORING`)."
        PRD §3.6: "First, the region multiplier is selected from the buyer's `region_code`: North America is the reference at 10000 basis points, Europe is 11000, Latin America is 6500, and Asia-Pacific is 8500."
        PRD §3.6: "Second, the tier discount is selected from the offer's `price_tier`: `T1` discounts nothing, `T2` discounts 500 basis points, `T3` discounts 1200, and `T4` discounts 2000."

        Design: Difficulty/transitive_cascade/monitoring_compute_suspends_lootbox_and_denies_pending_purchase
        """
        ctx = _setup_inflation_monitoring_cascade()

        run = validate_success(api_client.compute_monitoring_run(ctx["run_id"], LIVEOPS))
        assert run["denied_purchase_count"] == 1, (
            f"the one PENDING purchase of the suspended offer must be denied, got {run['denied_purchase_count']}"
        )

        purchase = read_purchase(ctx["purchase_id"])
        assert purchase["status"] == "DENIED", (
            f"the pending purchase must be carried to DENIED, got {purchase['status']}"
        )
        assert purchase["deny_reason"] == "OFFER_SUSPENDED_BY_MONITORING", (
            f"the cascade writes its own deny reason, got {purchase['deny_reason']}"
        )
        assert purchase["quoted_price_minor"] == 300, (
            "an NA buyer at tier T1 with no personalization pays the 300 list price, got "
            f"{purchase['quoted_price_minor']}"
        )

        offer = read_offer(ctx["offer_id"])
        assert offer["pending_purchase_count"] == 0, (
            f"the offer's pending purchase count must fall to 0, got {offer['pending_purchase_count']}"
        )

        season = read_season(ctx["season_id"])
        assert season["pending_revenue_minor"] == 0, (
            "the season's pending revenue must fall by the denied purchase's quoted price, got "
            f"{season['pending_revenue_minor']}"
        )

        player = read_player(ctx["player_id"])
        assert player["pending_spend_minor"] == 0, (
            "the buyer's pending spend must fall by the denied purchase's quoted price, got "
            f"{player['pending_spend_minor']}"
        )
