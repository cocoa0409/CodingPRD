"""Gates where a transition on one entity is decided by the state of another entity."""

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE,
    LIVEOPS,
    PRODUCER,
    ApiErrorId,
    advance_balance_change,
    api_client,
    append_adjustment,
    compute_monitoring_run,
    create_draft_balance_change,
    create_live_season,
    create_player,
    create_scheduled_episode,
    draft_comms_notice,
    get_success_data,
    open_account,
    open_monitoring_run,
    read_balance_change,
    read_season,
    season_version,
    set_clock,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Private setup helpers (each test rebuilds its own world from scratch)
# ---------------------------------------------------------------------------
def _season_with_inflated_posture_and_due_episode() -> Dict[str, Any]:
    """LIVE season whose posture a computed monitoring epoch has pushed to INFLATED,
    plus a SCHEDULED episode whose release instant the clock has already reached."""
    season = create_live_season()
    player = create_player(season["id"], handle="tide_p1", region_code="NA")
    account = open_account(player["id"], "SOFT_COIN")
    append_adjustment(account["id"], "FAUCET", 1000, "EVENT_REWARD")
    append_adjustment(account["id"], "SINK", 100, "OFFER_SPEND")
    episode = create_scheduled_episode(
        season["id"],
        sequence_no=1,
        title="E1 Tidefall",
        planned_release_at="2026-08-02T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=1200,
    )
    run = open_monitoring_run(
        season["id"],
        epoch_no=1,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-02T00:00:00Z",
    )
    computed = compute_monitoring_run(run["id"])
    assert computed["resulting_health"] == "INFLATED", (
        "Setup expects the epoch ratio (100 sink over 1000 faucet) to band as INFLATED, "
        f"got {computed['resulting_health']}"
    )
    set_clock("2026-08-02T00:00:00Z")
    return {"season": season, "episode": episode, "run": run, "account": account}


def _read_episode(episode_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_episode(episode_id, PRODUCER))


def _canary_change_with_drafted_notice() -> Dict[str, Any]:
    """A SINK_RATE tuning change walked DRAFT -> SHADOW -> CANARY, with a notice still in DRAFT."""
    season = create_live_season()
    change = create_draft_balance_change(
        season["id"],
        target_kind="SINK_RATE",
        delta_bp=500,
        rationale="Gem sink is 6 percent under target for two epochs",
        canary_cohort_pct=5,
    )
    advance_balance_change(change["id"], "SHADOW", season["id"])
    notice = draft_comms_notice(
        change["id"],
        channel="PATCH_NOTES",
        headline="Gem sink tuning",
        body="Crafting costs rise 5 percent next week.",
    )
    advance_balance_change(change["id"], "CANARY", season["id"])
    return {"season": season, "change": change, "notice": notice}


# ---------------------------------------------------------------------------
# Episode release against the season's economy posture
# ---------------------------------------------------------------------------
class TestEpisodeReleaseAgainstSeasonEconomyPosture:
    def test_release_refused_while_season_economy_health_is_inflated(self):
        """PRD §2.9: "While a season's `economy_health` is `INFLATED`, four operations are refused with `ERR_ECONOMY_INFLATED_BLOCK` (HTTP 409): releasing an episode, publishing an offer, resuming a suspended offer, and advancing a tuning change into its live stage."
        PRD §3.2: "Four conditions gate it: the episode is `SCHEDULED`, the season is `LIVE` (otherwise `ERR_SEASON_NOT_LIVE`), the logical clock has reached or passed the episode's `planned_release_at` (an early attempt yielding `ERR_EPISODE_NOT_DUE`), and the season's `economy_health` is not `INFLATED` (otherwise `ERR_ECONOMY_INFLATED_BLOCK`)."
        PRD §3.2: "At the third level, because those account totals changed, the season's `gross_faucet_minor` grows by `grant_batch_size` multiplied by `soft_currency_grant_minor`."

        Design: Difficulty/cross_entity_state_dependency/episode_release_blocked_while_season_economy_inflated
        """
        world = _season_with_inflated_posture_and_due_episode()
        season_id = world["season"]["id"]
        episode_id = world["episode"]["id"]

        response = api_client.release_episode(episode_id, PRODUCER)
        validate_error(response, ApiErrorId.ERR_ECONOMY_INFLATED_BLOCK.value, 409)

        episode = _read_episode(episode_id)
        assert episode["status"] == "SCHEDULED", (
            "A release refused by the INFLATED economy block must leave the episode SCHEDULED, "
            f"got {episode['status']}"
        )

        season = read_season(season_id)
        assert season["gross_faucet_minor"] == 1000, (
            "The refused release must not run its faucet cascade, so gross_faucet_minor stays at "
            f"the 1000 minted before it, got {season['gross_faucet_minor']}"
        )

    def test_release_succeeds_once_voiding_the_run_restores_healthy_posture(self):
        """PRD §3.9: "Voiding carries `COMPUTED → VOIDED` and rolls the posture back but nothing else: the season's `economy_health` is restored to the `resulting_health` of the run of that season which is `CERTIFIED` and carries the highest `epoch_no`, or to `HEALTHY` when the season has no certified run at all, and the season's `version` moves by 1."
        PRD §3.2: "On success the episode's `actual_release_at` is stamped with the clock, the season's `scheduled_episode_count` falls by 1 and its `released_episode_count` rises by 1, and any episode of the same season that is currently `LIVE` with a lower `sequence_no` is automatically carried from `LIVE` to `CONCLUDED` — the previous drop closing out as the new one opens, with `released_episode_count` unaffected by that automatic closure."
        PRD §3.2: "For each recipient in that order a ledger entry is appended with `direction` `FAUCET`, `source_kind` `EPISODE_GRANT`, an `amount_minor` equal to the episode's `soft_currency_grant_minor` — every recipient receives exactly that amount, with no proration — and the episode's season as `season_id`; the episode's `grant_batch_size` records how many entries were appended."
        PRD §3.2: "At the third level, because those account totals changed, the season's `gross_faucet_minor` grows by `grant_batch_size` multiplied by `soft_currency_grant_minor`."

        Design: Difficulty/cross_entity_state_dependency/episode_release_blocked_while_season_economy_inflated
        """
        world = _season_with_inflated_posture_and_due_episode()
        season_id = world["season"]["id"]
        episode_id = world["episode"]["id"]
        run_id = world["run"]["id"]

        blocked = api_client.release_episode(episode_id, PRODUCER)
        validate_error(blocked, ApiErrorId.ERR_ECONOMY_INFLATED_BLOCK.value, 409)

        voided = validate_success(
            api_client.decide_monitoring_run(run_id, {"decision": "VOID"}, LIVEOPS), 200
        )
        assert voided["status"] == "VOIDED", (
            f"A VOID decision on a COMPUTED run must land it in VOIDED, got {voided['status']}"
        )

        season_after_void = read_season(season_id)
        assert season_after_void["economy_health"] == "HEALTHY", (
            "Voiding the only run of the season restores economy_health to HEALTHY, got "
            f"{season_after_void['economy_health']}"
        )

        released = validate_success(api_client.release_episode(episode_id, PRODUCER), 200)
        assert released["status"] == "LIVE", (
            f"The same release must succeed once the posture is HEALTHY, got {released['status']}"
        )
        assert released["grant_batch_size"] == 1, (
            "The one eligible ACTIVE SOFT_COIN account of the season must be the single grant "
            f"recipient, got grant_batch_size {released['grant_batch_size']}"
        )

        season = read_season(season_id)
        assert season["gross_faucet_minor"] == 2200, (
            "gross_faucet_minor must be the pre-release 1000 plus 1 recipient times the 1200 "
            f"episode grant, got {season['gross_faucet_minor']}"
        )
        assert season["released_episode_count"] == 1, (
            f"released_episode_count must rise to 1, got {season['released_episode_count']}"
        )


# ---------------------------------------------------------------------------
# Tuning change go-live against the community notice
# ---------------------------------------------------------------------------
class TestTuningGoLiveAgainstCommsNotice:
    def test_canary_to_live_refused_while_notice_is_only_drafted(self):
        """PRD §3.8: "It requires the change's `comms_state` to be exactly `PUBLISHED`, a merely drafted notice being refused with `ERR_COMMS_NOTICE_REQUIRED`, and it requires the season's `economy_health` not to be `INFLATED`."
        PRD §3.8: "On success the season's current `effective_sink_rate_bp` is snapshotted into the change's `pre_live_sink_rate_bp`, and then — only when the change's `target_kind` is `SINK_RATE` — the season's `effective_sink_rate_bp` is adjusted by the change's `delta_bp`, a positive delta raising it and a negative delta lowering it."

        Design: Difficulty/cross_entity_state_dependency/balance_change_go_live_requires_published_comms_notice
        """
        world = _canary_change_with_drafted_notice()
        season_id = world["season"]["id"]
        change_id = world["change"]["id"]

        response = api_client.advance_balance_change(
            change_id,
            {"to_stage": "LIVE", "expected_season_version": season_version(season_id)},
            LIVEOPS,
        )
        validate_error(response, ApiErrorId.ERR_COMMS_NOTICE_REQUIRED.value, 422)

        change = read_balance_change(change_id)
        assert change["stage"] == "CANARY", (
            f"A refused go-live must leave the change in CANARY, got {change['stage']}"
        )

        season = read_season(season_id)
        assert season["effective_sink_rate_bp"] == 10000, (
            "The refused advance must not apply the delta, so effective_sink_rate_bp stays at its "
            f"opening 10000, got {season['effective_sink_rate_bp']}"
        )

    def test_publishing_the_notice_unblocks_go_live_and_applies_the_delta(self):
        """PRD §3.8: "On success the notice's `published_at` is stamped with the clock, `published_by_user_id` records the acting operator, and the change's `comms_state` becomes `PUBLISHED` with the change's `version` moving by 1."
        PRD §3.8: "It requires the change's `comms_state` to be exactly `PUBLISHED`, a merely drafted notice being refused with `ERR_COMMS_NOTICE_REQUIRED`, and it requires the season's `economy_health` not to be `INFLATED`."
        PRD §3.8: "On success the season's current `effective_sink_rate_bp` is snapshotted into the change's `pre_live_sink_rate_bp`, and then — only when the change's `target_kind` is `SINK_RATE` — the season's `effective_sink_rate_bp` is adjusted by the change's `delta_bp`, a positive delta raising it and a negative delta lowering it."
        PRD §3.8: "Entering `SHADOW` from `DRAFT` requires the season to be `LIVE`; it records the promoting operator as `promoted_by_user_id`, raises the season's `active_tuning_count` by 1, raises the season's `tuning_stage_epoch` by 1, and moves the season's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/balance_change_go_live_requires_published_comms_notice
        """
        world = _canary_change_with_drafted_notice()
        season_id = world["season"]["id"]
        change_id = world["change"]["id"]
        notice_id = world["notice"]["id"]

        blocked = api_client.advance_balance_change(
            change_id,
            {"to_stage": "LIVE", "expected_season_version": season_version(season_id)},
            LIVEOPS,
        )
        validate_error(blocked, ApiErrorId.ERR_COMMS_NOTICE_REQUIRED.value, 422)

        published = validate_success(
            api_client.publish_comms_notice(change_id, notice_id, COMPLIANCE), 200
        )
        assert published["status"] == "PUBLISHED", (
            f"Publication must carry the notice DRAFT -> PUBLISHED, got {published['status']}"
        )
        assert published["published_by_user_id"] == "u_compliance_1", (
            "published_by_user_id must record the acting compliance operator u_compliance_1, got "
            f"{published['published_by_user_id']}"
        )

        change_after_publish = read_balance_change(change_id)
        assert change_after_publish["comms_state"] == "PUBLISHED", (
            "Publishing the only notice of the change turns comms_state to PUBLISHED, got "
            f"{change_after_publish['comms_state']}"
        )

        advanced = validate_success(
            api_client.advance_balance_change(
                change_id,
                {"to_stage": "LIVE", "expected_season_version": season_version(season_id)},
                LIVEOPS,
            ),
            200,
        )
        assert advanced["stage"] == "LIVE", (
            f"The same advance must succeed once the notice is published, got {advanced['stage']}"
        )
        assert advanced["pre_live_sink_rate_bp"] == 10000, (
            "The season's pre-live baseline must be snapshotted at 10000, got "
            f"{advanced['pre_live_sink_rate_bp']}"
        )

        season = read_season(season_id)
        assert season["effective_sink_rate_bp"] == 10500, (
            "A SINK_RATE change with delta_bp 500 must raise effective_sink_rate_bp to 10500, got "
            f"{season['effective_sink_rate_bp']}"
        )
        assert season["active_tuning_count"] == 1, (
            "The single change in flight keeps active_tuning_count at 1 across CANARY -> LIVE, got "
            f"{season['active_tuning_count']}"
        )
