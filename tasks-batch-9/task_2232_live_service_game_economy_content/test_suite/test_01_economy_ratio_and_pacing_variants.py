"""Dual-variant economy and progression readings over one identical data set."""

from typing import Any, Dict, Tuple

from test_helpers import (
    DESIGNER,
    LIVEOPS,
    api_client,
    append_adjustment,
    assert_health_band,
    assert_monitoring_run,
    assert_retention_band,
    create_live_season,
    create_player,
    create_scheduled_episode,
    ingest_xp,
    open_account,
    open_monitoring_run,
    read_player,
    read_season,
    release_episode_at,
    rollback_episode_at,
    set_clock,
    validate_success,
)


# ---------------------------------------------------------------------------
# Private setup helpers (state is rebuilt from scratch inside every test)
# ---------------------------------------------------------------------------
def _season_with_reversal_pair_ledger() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """LIVE season whose ledger holds gross faucets 2200 and gross sinks 1600, of which a
    1200 episode grant and its 1200 rollback reversal form one compensating pair.

    Returns (season, soft_coin_account, open_monitoring_run) with the run's window spanning
    every appended row.
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_p1", region_code="NA")
    account = open_account(player["id"], "SOFT_COIN")
    append_adjustment(account["id"], "FAUCET", 1000, "ADMIN_ADJUSTMENT")

    episode = create_scheduled_episode(
        season["id"],
        sequence_no=1,
        title="E1 Tidefall",
        planned_release_at="2026-08-02T12:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=1200,
    )
    release_episode_at(episode["id"], "2026-08-02T12:00:00Z")
    rollback_episode_at(
        episode["id"], "Grant table shipped with the wrong multiplier", "2026-08-02T18:00:00Z"
    )

    set_clock("2026-08-02T20:00:00Z")
    append_adjustment(account["id"], "SINK", 400, "OFFER_SPEND")

    run = open_monitoring_run(
        season["id"],
        epoch_no=1,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-03T00:00:00Z",
    )
    return season, account, run


def _season_with_two_scheduled_episodes_and_telemetry() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """LIVE 90-day season with an overdue SCHEDULED episode (5000 xp) and a future one
    (600 xp), the clock 30 days in, and a player carrying 2400 ingested season XP.
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_p3", region_code="NA")

    create_scheduled_episode(
        season["id"],
        sequence_no=1,
        title="E1 Tidefall",
        planned_release_at="2026-08-10T00:00:00Z",
        xp_grant=5000,
        soft_currency_grant_minor=0,
    )
    create_scheduled_episode(
        season["id"],
        sequence_no=2,
        title="E2 Undertow",
        planned_release_at="2026-09-05T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=0,
    )

    set_clock("2026-08-31T00:00:00Z")
    ingest_xp(player["id"], 2400, 12)
    return season, player


class TestSeasonSinkFaucetRatioVariants:
    """The epoch-windowed and lifetime-cumulative readings of the same season ledger."""

    def test_epoch_windowed_compute_drops_both_members_of_the_compensating_pair(self):
        """PRD §3.9: "Only the rows whose `occurred_at` falls at or after the window start and strictly before the window end are considered, and on top of that every compensating pair is removed entirely — a row whose `reversal_of_entry_id` is set is dropped, and so is the row it points at."
        PRD §3.9: "In both readings the candidate rows are the ledger entries attributed to the season, and the ratio itself is formed the same way: when the faucet total and the sink total are both zero the ratio is exactly 10000 basis points; when the faucet total is zero but sinks exist the ratio is 20000 basis points; otherwise it is the sink total multiplied by 10000, divided by the faucet total, rounded half up, and then capped at 20000."
        PRD §3.9: "The health band follows from the ratio: `HEALTHY` when the ratio is at least 6000 basis points, `WATCH` when it is at least 4000 but below 6000, and `INFLATED` when it is below 4000."
        PRD §3.9: "The run's own `gross_faucet_minor`, `gross_sink_minor` and `sink_faucet_ratio_bp` are computed under the epoch-windowed reading over the run's own window, the run's `resulting_health` is derived from that ratio, and `computed_at` is stamped with the clock."
        PRD §3.9: "At the first level, the season's `economy_health` is overwritten with the run's `resulting_health`, the season's `cadence_debt_days` and `content_posture` are recomputed, and the season's `version` moves by 1."

        Design: Difficulty/dual_variant_calc/season_sink_faucet_ratio_epoch_vs_lifetime
        """
        season, _account, run = _season_with_reversal_pair_ledger()

        computed = validate_success(api_client.compute_monitoring_run(run["id"], LIVEOPS))
        assert_monitoring_run(computed)

        assert computed["gross_faucet_minor"] == 1000, (
            "The epoch-windowed reading must drop the reversed 1200 episode grant, leaving "
            f"gross_faucet_minor 1000, got {computed['gross_faucet_minor']}"
        )
        assert computed["gross_sink_minor"] == 400, (
            "The epoch-windowed reading must drop the 1200 rollback reversal, leaving "
            f"gross_sink_minor 400, got {computed['gross_sink_minor']}"
        )
        assert computed["sink_faucet_ratio_bp"] == 4000, (
            "400 * 10000 / 1000 must round to 4000 bp under the epoch-windowed reading, got "
            f"{computed['sink_faucet_ratio_bp']}"
        )
        assert computed["resulting_health"] == "WATCH", (
            f"4000 bp bands as WATCH, got {computed['resulting_health']}"
        )
        assert_health_band(computed["sink_faucet_ratio_bp"], computed["resulting_health"])

        season_after = read_season(season["id"])
        assert season_after["economy_health"] == "WATCH", (
            "The compute cascade must overwrite the season's economy_health with the run's "
            f"resulting_health WATCH, got {season_after['economy_health']}"
        )

    def test_lifetime_cumulative_summary_counts_the_reversal_gross_and_diverges(self):
        """PRD §3.9: "The **lifetime-cumulative** reading uses gross semantics: every row of the season counts regardless of `occurred_at`, including compensating rows and the rows they reverse."
        PRD §3.9: "Because of the difference in reversal treatment, identical ledger data yields two different ratios whenever any reversal exists in the season, and that is intentional — one number tells the operator what is happening now, the other tells them what has ever happened."
        PRD §3.9: "This is the reading maintained continuously in the season's `lifetime_ratio_bp`, refreshed on every ledger append."
        PRD §3.1: "It takes a required `variant` and an optional `epoch_no`, computes the sink-to-faucet ratio fresh without persisting anything, and answers with the `season_id`, the `variant` that was evaluated, the `window_start` and `window_end` of the window it used, the `gross_faucet_minor` and `gross_sink_minor` it summed inside that window, the resulting `sink_faucet_ratio_bp`, the `health_band` that ratio maps to, and — for context, read straight from the stored season — its current `economy_health`, `cadence_debt_days`, `content_posture` and `effective_sink_rate_bp`."
        PRD §3.9: "For the lifetime-cumulative reading the window covers the whole season."

        Design: Difficulty/dual_variant_calc/season_sink_faucet_ratio_epoch_vs_lifetime
        """
        season, _account, run = _season_with_reversal_pair_ledger()

        computed = validate_success(api_client.compute_monitoring_run(run["id"], LIVEOPS))

        summary = validate_success(
            api_client.get_economy_summary(
                season["id"], DESIGNER, params={"variant": "LIFETIME_CUMULATIVE"}
            )
        )
        assert summary["variant"] == "LIFETIME_CUMULATIVE", (
            f"The summary must echo the variant it evaluated, got {summary.get('variant')!r}"
        )
        assert summary["gross_faucet_minor"] == 2200, (
            "Gross semantics must count the 1000 operator faucet and the 1200 episode grant, "
            f"totalling 2200, got {summary['gross_faucet_minor']}"
        )
        assert summary["gross_sink_minor"] == 1600, (
            "Gross semantics must count the 1200 rollback reversal and the 400 operator sink, "
            f"totalling 1600, got {summary['gross_sink_minor']}"
        )
        assert summary["sink_faucet_ratio_bp"] == 7273, (
            "1600 * 10000 / 2200 must round half up to 7273 bp, got "
            f"{summary['sink_faucet_ratio_bp']}"
        )
        assert summary["health_band"] == "HEALTHY", (
            f"7273 bp bands as HEALTHY, got {summary['health_band']}"
        )
        assert_health_band(summary["sink_faucet_ratio_bp"], summary["health_band"])

        season_after = read_season(season["id"])
        assert season_after["lifetime_ratio_bp"] == 7273, (
            "The season's continuously maintained lifetime_ratio_bp must read 7273 bp, got "
            f"{season_after['lifetime_ratio_bp']}"
        )
        assert season_after["economy_health"] == "WATCH", (
            "The stored posture comes from the epoch-windowed run, so it must remain WATCH even "
            f"though the lifetime ratio bands HEALTHY, got {season_after['economy_health']}"
        )
        assert computed["sink_faucet_ratio_bp"] != season_after["lifetime_ratio_bp"], (
            "The two readings must disagree over identical ledger data holding a reversal pair, "
            f"but both read {computed['sink_faucet_ratio_bp']}"
        )


class TestPlayerPacingVariants:
    """The realized and projected readings of the same player's progression."""

    def test_realized_pacing_divides_season_xp_by_the_schedule_to_date(self):
        """PRD §3.4: "The season's total length in whole days is the difference between `ends_at` and `starts_at` divided by 86400 and truncated downward."
        PRD §3.4: "Elapsed days are the difference between the current clock and `starts_at`, divided by 86400 and truncated downward, then clamped so that the figure is never below 0 and never above the season's total days."
        PRD §3.4: "The experience the player was expected to have earned by now is the season's `target_xp_total` multiplied by elapsed days, divided by that total-days figure, and rounded half up."
        PRD §3.4: "Otherwise it is the player's `season_xp_total` multiplied by 10000, divided by the expected-to-date figure, rounded half up, and then capped at 20000 basis points."
        PRD §3.4: "From the realized figure the system derives `retention_band`: `HEALTHY` when the realized pacing is at least 9000 basis points, `AT_RISK` when it is at least 6000 but below 9000, and `CHURN_RISK` when it is below 6000."
        PRD §3.4: "It answers with the `player_id`, the `variant` evaluated, the `elapsed_days` and `season_total_days` it derived, the `expected_to_date_xp` denominator, the `eligible_scheduled_xp` it summed (relevant to the projected reading), the player's current `season_xp_total`, the resulting `pacing_bp`, and the `retention_band` that figure maps to."

        Design: Difficulty/dual_variant_calc/player_pacing_realized_vs_projected
        """
        _season, player = _season_with_two_scheduled_episodes_and_telemetry()

        realized = validate_success(
            api_client.get_pacing(player["id"], LIVEOPS, params={"variant": "REALIZED"})
        )

        assert realized["variant"] == "REALIZED", (
            f"The pacing read must echo the variant evaluated, got {realized.get('variant')!r}"
        )
        assert realized["season_total_days"] == 90, (
            "2026-08-01 to 2026-10-30 is 90 whole days, got "
            f"{realized['season_total_days']}"
        )
        assert realized["elapsed_days"] == 30, (
            "The clock stands 30 whole days after starts_at, got "
            f"{realized['elapsed_days']}"
        )
        assert realized["expected_to_date_xp"] == 3000, (
            "9000 * 30 / 90 must give an expected-to-date denominator of 3000, got "
            f"{realized['expected_to_date_xp']}"
        )
        assert realized["pacing_bp"] == 8000, (
            "2400 * 10000 / 3000 must give 8000 bp under the realized reading, got "
            f"{realized['pacing_bp']}"
        )
        assert realized["retention_band"] == "AT_RISK", (
            f"8000 bp bands as AT_RISK, got {realized['retention_band']}"
        )
        assert_retention_band(realized["pacing_bp"], realized["retention_band"])

    def test_projected_pacing_excludes_the_overdue_episode_and_is_never_persisted(self):
        """PRD §3.4: "The **projected** reading is a full-season forecast that absorbs content not yet shipped: it adds to the player's `season_xp_total` the sum of the `xp_grant` of every episode of the player's active season that is currently `SCHEDULED` and whose `planned_release_at` is at or after the current clock — overdue scheduled drops are excluded from that sum — then multiplies the total by 10000, divides by the season's full `target_xp_total`, rounds half up, and caps at 20000 basis points."
        PRD §3.4: "The projected reading is available only through the on-demand pacing read and is never persisted and never used for pricing."
        PRD §3.4: "This is the reading that is persisted into `pacing_bp_realized`, and it is recomputed and stored whenever engagement telemetry is ingested, whenever a purchase settles, and whenever a monitoring run computes."
        PRD §3.4: "The player's `season_xp_total` grows by the experience delta, `session_count` grows by the session delta, and `last_active_at` is set to the `occurred_at` of the ingest."

        Design: Difficulty/dual_variant_calc/player_pacing_realized_vs_projected
        """
        _season, player = _season_with_two_scheduled_episodes_and_telemetry()

        projected = validate_success(
            api_client.get_pacing(player["id"], LIVEOPS, params={"variant": "PROJECTED"})
        )

        assert projected["eligible_scheduled_xp"] == 600, (
            "Only the not-yet-due SCHEDULED episode contributes, so eligible_scheduled_xp must "
            f"be 600 rather than 5600, got {projected['eligible_scheduled_xp']}"
        )
        assert projected["pacing_bp"] == 3333, (
            "(2400 + 600) * 10000 / 9000 must round half up to 3333 bp, got "
            f"{projected['pacing_bp']}"
        )
        assert projected["retention_band"] == "CHURN_RISK", (
            f"3333 bp bands as CHURN_RISK, got {projected['retention_band']}"
        )
        assert_retention_band(projected["pacing_bp"], projected["retention_band"])

        stored = read_player(player["id"])
        assert stored["season_xp_total"] == 2400, (
            f"The ingest must leave season_xp_total at 2400, got {stored['season_xp_total']}"
        )
        assert stored["pacing_bp_realized"] == 8000, (
            "Only the realized reading is persisted, so pacing_bp_realized must stay at 8000 "
            f"after the projected read, got {stored['pacing_bp_realized']}"
        )
        assert stored["retention_band"] == "AT_RISK", (
            "The stored band derives from the realized figure, so it must stay AT_RISK rather "
            f"than following the projected CHURN_RISK, got {stored['retention_band']}"
        )
