"""Non-linear lifecycles: the episode rollback loop and the offer's two parallel dimensions."""

from datetime import datetime
from typing import Any, Dict, Tuple

from test_helpers import (
    COMPLIANCE,
    DESIGNER,
    PRODUCER,
    ApiErrorId,
    api_client,
    approve_offer,
    assert_episode,
    assert_offer,
    assert_season_ledger_totals,
    create_draft_offer,
    create_live_season,
    create_player,
    create_scheduled_episode,
    get_success_data,
    offer_line_item,
    open_account,
    publish_offer,
    read_account,
    read_offer,
    read_season,
    release_episode_at,
    resume_offer,
    rollback_episode_at,
    set_clock,
    submit_offer,
    suspend_offer,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Private helpers (state is rebuilt from scratch inside every test)
# ---------------------------------------------------------------------------
def _instant(value: str) -> datetime:
    """Parse a server ISO 8601 UTC stamp regardless of its fractional-second precision."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _rolled_back_episode_with_one_grant_recipient() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """LIVE season, one SOFT_COIN recipient, and episode 1 released at 2026-08-02 then rolled
    back at 2026-08-03 with the clock left on the rollback instant.

    Returns (season, episode, soft_coin_account).
    """
    season = create_live_season()
    player = create_player(season["id"], handle="tide_p1", region_code="NA")
    account = open_account(player["id"], "SOFT_COIN")

    episode = create_scheduled_episode(
        season["id"],
        sequence_no=1,
        title="E1 Tidefall",
        planned_release_at="2026-08-02T00:00:00Z",
        xp_grant=600,
        soft_currency_grant_minor=1200,
    )

    release_episode_at(episode["id"], "2026-08-02T00:00:00Z")
    rollback_episode_at(
        episode["id"], "Client crash on the new zone", "2026-08-03T00:00:00Z"
    )
    return season, episode, account


def _relive_the_rolled_back_episode(episode_id: str) -> Dict[str, Any]:
    """Reschedule the ROLLED_BACK episode to 2026-08-05 and release it on that exact instant."""
    validate_success(
        api_client.schedule_episode(
            episode_id, PRODUCER, {"planned_release_at": "2026-08-05T00:00:00Z"}
        )
    )
    set_clock("2026-08-05T00:00:00Z")
    return validate_success(api_client.release_episode(episode_id, PRODUCER))


def _revised_then_approved_bundle() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """LIVE season with a two-line BUNDLE driven once round the revision loop
    (DRAFT -> IN_REVIEW -> DRAFT) and then approved, still OFFLINE.

    Returns (season, offer).
    """
    season = create_live_season()
    offer = create_draft_offer(
        season["id"],
        offer_type="BUNDLE",
        sku="AUG_BUNDLE",
        price_tier="T3",
        list_price_minor=1798,
        line_items=[
            offer_line_item("COIN_PACK", 499, 700, "EVENT_TOKEN", 600),
            offer_line_item("SKIN_A", 1299, 1700, "EVENT_TOKEN", 600),
        ],
        personalization_discount_bp=1500,
        minor_purchasable=False,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    submit_offer(offer["id"])
    get_success_data(
        api_client.review_offer(
            offer["id"],
            {"decision": "REVISE", "note": "Trim the personalization discount"},
            COMPLIANCE,
        )
    )
    submit_offer(offer["id"])
    approve_offer(offer["id"], note="Second pass is fine")
    return season, offer


class TestEpisodeRollbackRescheduleReliveCycle:
    """An episode that traverses SCHEDULED -> LIVE twice through the rollback loop."""

    def test_rolled_back_episode_reschedules_and_reaches_live_a_second_time(self):
        """PRD §3.2: "Rescheduling from `ROLLED_BACK` to `SCHEDULED` requires the season to be `LIVE` and requires the supplied `planned_release_at` to be present, to be at or after the current clock, and to lie inside the season window."
        PRD §3.2: "It clears `actual_release_at` back to null, overwrites `planned_release_at` with the supplied value, raises `scheduled_episode_count` by 1, recomputes the season's cadence figures, and moves the season's `version` by 1."
        PRD §3.2: "The full loop is therefore `LIVE → ROLLED_BACK → SCHEDULED → LIVE`, and each pass through it leaves a permanent mark in `rollback_count`."
        PRD §3.2: "It carries the episode from `LIVE` to `ROLLED_BACK`, raises the episode's `rollback_count` by 1 — a counter that is never reset — and lowers the season's `released_episode_count` by 1."
        PRD §3.2: "On success the episode's `actual_release_at` is stamped with the clock, the season's `scheduled_episode_count` falls by 1 and its `released_episode_count` rises by 1, and any episode of the same season that is currently `LIVE` with a lower `sequence_no` is automatically carried from `LIVE` to `CONCLUDED` — the previous drop closing out as the new one opens, with `released_episode_count` unaffected by that automatic closure."
        PRD §3.2: "For each recipient in that order a ledger entry is appended with `direction` `FAUCET`, `source_kind` `EPISODE_GRANT`, an `amount_minor` equal to the episode's `soft_currency_grant_minor` — every recipient receives exactly that amount, with no proration — and the episode's season as `season_id`; the episode's `grant_batch_size` records how many entries were appended."

        Design: Difficulty/non_linear_state_machine/episode_rollback_reschedule_relive_cycle
        """
        season, episode, _account = _rolled_back_episode_with_one_grant_recipient()

        relived = _relive_the_rolled_back_episode(episode["id"])
        assert_episode(relived)

        assert relived["status"] == "LIVE", (
            f"The second release must carry the episode back to LIVE, got {relived['status']}"
        )
        assert relived["rollback_count"] == 1, (
            "The single rollback must leave a permanent mark of 1 that returning to LIVE never "
            f"resets, got {relived['rollback_count']}"
        )
        assert _instant(relived["planned_release_at"]) == _instant("2026-08-05T00:00:00Z"), (
            "The reschedule must overwrite planned_release_at with the supplied instant, got "
            f"{relived['planned_release_at']}"
        )
        assert relived["actual_release_at"] is not None, (
            "The second release must stamp actual_release_at again after the reschedule cleared it"
        )
        assert _instant(relived["actual_release_at"]) == _instant("2026-08-05T00:00:00Z"), (
            "actual_release_at must be stamped with the clock at the second release, got "
            f"{relived['actual_release_at']}"
        )
        assert relived["grant_batch_size"] == 1, (
            "Exactly one SOFT_COIN account is eligible, so grant_batch_size must be 1, got "
            f"{relived['grant_batch_size']}"
        )

        season_after = read_season(season["id"])
        assert season_after["scheduled_episode_count"] == 0, (
            "The reschedule raised the scheduled count and the second release lowered it again, "
            f"so it must be back at 0, got {season_after['scheduled_episode_count']}"
        )
        assert season_after["released_episode_count"] == 1, (
            "The rollback lowered released_episode_count to 0 and the second release raised it "
            f"to 1, got {season_after['released_episode_count']}"
        )

    def test_rollback_cycle_leaves_three_debt_days_and_a_conserved_balance(self):
        """PRD §3.2: "In addition, and in every status including `DRAFT`, an episode contributes 3 days of debt for each entry in its `rollback_count` — so an episode that has never gone live contributes nothing from this term, while one rolled back twice carries 6 days of debt forever."
        PRD §3.2: "An episode that is `LIVE` or `CONCLUDED` contributes the number of whole days by which its `actual_release_at` fell after its `planned_release_at`, truncated downward, and never less than zero, so an early or on-time drop contributes nothing."
        PRD §3.2: "The accumulated total is stored as `cadence_debt_days`, and `content_posture` becomes `BEHIND` when that total is strictly greater than 14 days and `ON_TRACK` otherwise."
        PRD §3.2: "At the third level, because those account totals changed, the season's `gross_faucet_minor` grows by `grant_batch_size` multiplied by `soft_currency_grant_minor`."
        PRD §3.2: "Second, because those entries exist, each affected account's `lifetime_sink_minor` grows by the reversed amount, its `balance_minor` is recomputed, and its `version` moves by 1."
        PRD §3.2: "The invariant this guarantees is exact: after a rollback, every affected account's `balance_minor` equals what it was immediately before the release."

        Design: Difficulty/non_linear_state_machine/episode_rollback_reschedule_relive_cycle
        """
        season, episode, account = _rolled_back_episode_with_one_grant_recipient()

        _relive_the_rolled_back_episode(episode["id"])

        season_after = read_season(season["id"])
        assert season_after["cadence_debt_days"] == 3, (
            "The on-time second release contributes no lateness, so the only debt is the 3 days "
            f"carried by one rollback, got {season_after['cadence_debt_days']}"
        )
        assert season_after["content_posture"] == "ON_TRACK", (
            "3 debt days is not strictly greater than 14, so the posture stays ON_TRACK, got "
            f"{season_after['content_posture']}"
        )
        assert_season_ledger_totals(season_after, 2400, 1200)
        assert season_after["gross_faucet_minor"] == 2400, (
            "Two releases of a 1200 grant to one recipient must total 2400 gross faucet, got "
            f"{season_after['gross_faucet_minor']}"
        )
        assert season_after["gross_sink_minor"] == 1200, (
            "Only the single rollback reversal removed currency, so gross sink must be 1200, got "
            f"{season_after['gross_sink_minor']}"
        )

        account_after = read_account(account["id"])
        assert account_after["balance_minor"] == 1200, (
            "The first grant was reversed exactly and the second grant stands, so the balance "
            f"must be 1200, got {account_after['balance_minor']}"
        )


class TestOfferParallelStatusDimensions:
    """The governance and storefront dimensions of one offer move independently."""

    def test_availability_cycles_live_suspended_live_without_touching_approval(self):
        """PRD §3.5: "A newly created offer is `DRAFT` on the first dimension and `OFFLINE` on the second, and neither dimension ever moves the other implicitly: an offer can be re-reviewed while it sits live on the storefront, and it can be suspended and resumed without its approval ever being revisited."
        PRD §3.5: "Revising carries it `IN_REVIEW → DRAFT`, raises `revision_count` by 1, likewise records `reviewed_by_user_id`, and likewise moves `version` by 1 — the revision loop `DRAFT → IN_REVIEW → DRAFT` being repeatable, with `availability_status` sitting at `OFFLINE` throughout."
        PRD §3.5: "Approving carries the offer `IN_REVIEW → APPROVED`, records the reviewer as `reviewed_by_user_id`, and moves the offer's `version` by 1."
        PRD §3.5: "A successful publish raises the season's `live_offer_count` by 1 and moves both the season's and the offer's `version` by 1."
        PRD §3.5: "Suspending a `LIVE` offer carries it `LIVE → SUSPENDED`, lowers the season's `live_offer_count` by 1, and moves both the season's and the offer's `version` by 1; the same transition also occurs as a system cascade from a monitoring run, as §3.9 describes."
        PRD §3.5: "The availability cycle `LIVE → SUSPENDED → LIVE` may repeat indefinitely and runs entirely independently of `approval_status`."

        Design: Difficulty/non_linear_state_machine/offer_parallel_approval_and_availability_dimensions
        """
        season, offer = _revised_then_approved_bundle()

        publish_offer(offer["id"], season["id"])
        suspend_offer(offer["id"], reason="Pricing audit")
        resumed = resume_offer(offer["id"])
        assert_offer(resumed)

        assert resumed["revision_count"] == 1, (
            "One REVISE decision must leave revision_count at 1 through the whole availability "
            f"cycle, got {resumed['revision_count']}"
        )
        assert resumed["approval_status"] == "APPROVED", (
            "Publishing, suspending and resuming must never move the governance dimension, got "
            f"{resumed['approval_status']}"
        )
        assert resumed["availability_status"] == "LIVE", (
            "The resume must return the storefront dimension to LIVE, got "
            f"{resumed['availability_status']}"
        )

        season_after = read_season(season["id"])
        assert season_after["live_offer_count"] == 1, (
            "Publish raised the count, suspend lowered it and resume raised it again, so it must "
            f"read 1, got {season_after['live_offer_count']}"
        )

    def test_submit_from_the_approved_live_combination_fails_on_the_approval_dimension(self):
        """PRD §3.5: "An `EconomyDesigner` first submits a `DRAFT` offer into review, which requires the offer's `approval_status` to be `DRAFT`, its `availability_status` to be `OFFLINE`, and its season to be `LIVE` (otherwise `ERR_SEASON_NOT_LIVE`); the submission recomputes `fairness_index_bp` and moves the offer's `version` by 1, touching the storefront dimension not at all."
        PRD §3.5: "Rejections name the dimension at fault — `ERR_OFFER_INVALID_APPROVAL_STATE` for a governance transition that does not exist from the current `approval_status`, and `ERR_OFFER_INVALID_AVAILABILITY_STATE` for a storefront transition that does not exist from the current `availability_status`."

        Design: Difficulty/non_linear_state_machine/offer_parallel_approval_and_availability_dimensions
        """
        season, offer = _revised_then_approved_bundle()

        publish_offer(offer["id"], season["id"])
        suspend_offer(offer["id"], reason="Pricing audit")
        resume_offer(offer["id"])

        validate_error(
            api_client.submit_offer(offer["id"], DESIGNER),
            ApiErrorId.ERR_OFFER_INVALID_APPROVAL_STATE.value,
            409,
        )

        offer_after = read_offer(offer["id"])
        assert offer_after["approval_status"] == "APPROVED", (
            "The rejected submit must leave the governance dimension on APPROVED, got "
            f"{offer_after['approval_status']}"
        )
        assert offer_after["availability_status"] == "LIVE", (
            "The rejected submit must leave the storefront dimension on LIVE, got "
            f"{offer_after['availability_status']}"
        )
