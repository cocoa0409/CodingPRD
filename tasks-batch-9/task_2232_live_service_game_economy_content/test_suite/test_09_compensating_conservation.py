"""Compensating flows: what a refund execution and an event rollback restore exactly."""

from typing import Any, Dict

from test_helpers import (
    LIVEOPS,
    api_client,
    create_approved_event,
    create_cluster,
    create_live_season,
    create_planned_event,
    decide_refund,
    read_account,
    read_cluster,
    read_live_event,
    read_player,
    read_purchase,
    read_season,
    setup_settled_purchase_scenario,
    submit_refund,
    validate_success,
)

_ROLLBACK_REASON = "Sponsor pulled out of the showcase"


# ---------------------------------------------------------------------------
# Private setup helpers (each test rebuilds its own world from scratch)
# ---------------------------------------------------------------------------
def _approved_refund_on_unconsumed_purchase() -> Dict[str, Any]:
    """A 5000-minor purchase settled against a HARD_GEM-only player, nothing consumed,
    with its refund request already APPROVED."""
    scenario = setup_settled_purchase_scenario(
        price_minor=5000, declared_value_minor=6000, granted_currency_code="HARD_GEM"
    )
    purchase = scenario["purchase"]
    assert purchase["granted_total_minor"] == 5000, (
        "Setup expects the settlement to have granted the full 5000 HARD_GEM, got "
        f"{purchase['granted_total_minor']}"
    )
    request = submit_refund(purchase["id"], scenario["player"]["id"], "TECHNICAL_FAILURE")
    scenario["request"] = decide_refund(request["id"], "APPROVE", "Entitlement never delivered")
    return scenario


def _cluster_with_approved_event_and_blocked_successor() -> Dict[str, Any]:
    """A 10000-CCU cluster holding a 6000-CCU APPROVED event, plus a PLANNED 10000-CCU event
    whose window overlaps it."""
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
    event_d = create_planned_event(
        season["id"],
        cluster["id"],
        code="EVT_D",
        window_start="2026-08-05T01:00:00Z",
        window_end="2026-08-05T03:00:00Z",
        forecast_ccu=10000,
    )
    return {"season": season, "cluster": cluster, "event_a": event_a, "event_d": event_d}


# ---------------------------------------------------------------------------
# Refund execution: the ledger grows, the net economy returns
# ---------------------------------------------------------------------------
class TestRefundExecutionConservesSeasonNetCurrency:
    def test_execution_pins_the_six_step_amounts_and_refunds_the_purchase(self):
        """PRD §3.7: "**Step two** computes `refund_base_minor`: the purchase's `price_paid_minor` multiplied by the quantity 10000 minus `consumed_ratio_bp`, divided by 10000, rounded half up."
        PRD §3.7: "**Step three** selects the restocking fee tier, and it is keyed on the Step-two figure and on nothing else: the tier is 0 basis points when `refund_base_minor` is strictly below 1000 minor units, 500 basis points when it is at least 1000 but strictly below 5000, and 1000 basis points at 5000 or above."
        PRD §3.7: "**Step four** computes `restock_fee_minor`: `refund_base_minor` multiplied by that tier, divided by 10000, rounded half up."
        PRD §3.7: "**Step five** computes `refund_amount_minor`: `refund_base_minor` minus `restock_fee_minor`, floored at 0."
        PRD §3.7: "**Step six** computes `goodwill_credit_minor`: half of the restocking fee — that is, `restock_fee_minor` multiplied by 5000, divided by 10000, rounded half up — but only when the player holds a currency account whose `currency_code` is `SOFT_COIN` and the player's `spend_state` is not `LOCKED`; when either condition fails the goodwill credit is 0."
        PRD §3.7: "The purchase itself is carried `SETTLED → REFUNDED`, which is terminal for it, and its `version` moves by 1."
        PRD §3.7: "Finally the request's `executed_at` is stamped with the clock, the request lands in `EXECUTED`, and its `version` moves by 1."

        Design: Difficulty/compensating_invariant/refund_execution_conserves_season_net_currency
        """
        world = _approved_refund_on_unconsumed_purchase()
        request_id = world["request"]["id"]
        purchase_id = world["purchase"]["id"]

        executed = validate_success(api_client.execute_refund_request(request_id, LIVEOPS), 200)
        assert executed["status"] == "EXECUTED", (
            f"An approved refund must land in EXECUTED once executed, got {executed['status']}"
        )
        assert executed["refund_base_minor"] == 5000, (
            "Nothing was consumed, so the base is the full 5000 price paid, got "
            f"{executed['refund_base_minor']}"
        )
        assert executed["restock_fee_minor"] == 500, (
            "A base of 5000 keys the 1000 bp tier, giving a 500 fee, got "
            f"{executed['restock_fee_minor']}"
        )
        assert executed["refund_amount_minor"] == 4500, (
            "The cash returned is 5000 minus the 500 fee, got "
            f"{executed['refund_amount_minor']}"
        )
        assert executed["goodwill_credit_minor"] == 0, (
            "The buyer holds no SOFT_COIN account, so the goodwill credit is 0, got "
            f"{executed['goodwill_credit_minor']}"
        )

        purchase = read_purchase(purchase_id)
        assert purchase["status"] == "REFUNDED", (
            f"The purchase behind an executed refund becomes REFUNDED, got {purchase['status']}"
        )

    def test_execution_returns_the_account_balance_and_season_net_to_pre_settlement(self):
        """PRD §3.7: "At the first level, the ledger entries with `source_kind` `PURCHASE_GRANT` and this purchase's `purchase_id` are walked in ascending `created_at` order, and for each one a compensating entry is appended with `direction` `SINK`, `source_kind` `REFUND_REVERSAL`, this purchase's `purchase_id`, and `reversal_of_entry_id` pointing at the original entry's `id`."
        PRD §3.7: "At the second level, because those entries exist, each affected account's `lifetime_sink_minor` and `balance_minor` are updated and its `version` moves by 1."
        PRD §3.7: "At the third level, because those account totals changed, the season's `gross_sink_minor` grows by the total amount reversed and the season's `lifetime_ratio_bp` is recomputed."
        PRD §3.7: "At the fourth level, because the purchase is being refunded, the season's `settled_revenue_minor` falls by the purchase's `price_paid_minor`, the player's `spend_30d_minor` is recomputed net of the `refund_amount_minor` just returned, and the player's `spend_state` is re-evaluated — dropping from `COOLDOWN` to `UNRESTRICTED` when the recomputed figure falls below 40000 minor units."
        PRD §3.7: "The invariant worth stating: when the purchase had consumed nothing, both the affected accounts' `balance_minor` and the difference between the season's `gross_faucet_minor` and `gross_sink_minor` return exactly to their pre-settlement values."
        PRD §3.7: "The rolling spend figure is computed by taking the window that begins 30 days before the current clock and ends at the clock itself, summing the `price_paid_minor` of every purchase of that player whose `status` is `SETTLED` or `REFUNDED` and whose `settled_at` falls inside that window with both ends inclusive, then subtracting the `refund_amount_minor` of every refund request in `EXECUTED` status against that player's purchases whose `executed_at` falls inside the same inclusive window, and finally flooring the result at 0 so it can never go negative."
        PRD §3.6: "On the player, `pending_spend_minor` falls by the quoted price, `lifetime_spend_minor` rises by the price paid, `spend_30d_minor` is recomputed, `spend_state` is re-evaluated against the responsible-spending thresholds, `pacing_bp_realized` and `retention_band` are recomputed, and `version` moves by 1."

        Design: Difficulty/compensating_invariant/refund_execution_conserves_season_net_currency
        """
        world = _approved_refund_on_unconsumed_purchase()
        request_id = world["request"]["id"]
        season_id = world["season"]["id"]
        account_id = world["account"]["id"]
        player_id = world["player"]["id"]

        validate_success(api_client.execute_refund_request(request_id, LIVEOPS), 200)

        account = read_account(account_id)
        assert account["lifetime_faucet_minor"] == 5000, (
            "The original purchase grant is never rewritten, so lifetime_faucet_minor stays at "
            f"5000, got {account['lifetime_faucet_minor']}"
        )
        assert account["lifetime_sink_minor"] == 5000, (
            "The compensating REFUND_REVERSAL sink mirrors the full 5000 grant, got "
            f"{account['lifetime_sink_minor']}"
        )
        assert account["balance_minor"] == 0, (
            "An unconsumed refund returns the balance to its pre-settlement 0, got "
            f"{account['balance_minor']}"
        )

        season = read_season(season_id)
        assert season["gross_faucet_minor"] == 5000, (
            f"The season's gross faucet total keeps the grant, got {season['gross_faucet_minor']}"
        )
        assert season["gross_sink_minor"] == 5000, (
            "The season's gross sink total grows by the whole amount reversed, got "
            f"{season['gross_sink_minor']}"
        )
        assert season["settled_revenue_minor"] == 0, (
            "settled_revenue_minor falls by the 5000 price paid, back to 0, got "
            f"{season['settled_revenue_minor']}"
        )

        player = read_player(player_id)
        assert player["spend_30d_minor"] == 500, (
            "Rolling spend is the 5000 paid less the 4500 refunded, got "
            f"{player['spend_30d_minor']}"
        )
        assert player["lifetime_spend_minor"] == 5000, (
            "lifetime_spend_minor records what was paid and is not unwound by the refund, got "
            f"{player['lifetime_spend_minor']}"
        )
        assert player["spend_state"] == "UNRESTRICTED", (
            f"A 500 rolling spend keeps the player UNRESTRICTED, got {player['spend_state']}"
        )


# ---------------------------------------------------------------------------
# Live-event rollback: the cluster reservation returns exactly
# ---------------------------------------------------------------------------
class TestLiveEventRollbackConservesReservedCcu:
    def test_rollback_releases_exactly_the_snapshotted_reservation(self):
        """PRD §3.3: "Rolling an event back takes a `reason`, which is stored as `rollback_reason`, and is available from either `APPROVED` or `RUNNING`; in both cases the event lands in `ROLLED_BACK`, the cluster's `reserved_ccu` falls by the event's `reserved_ccu_at_approval`, that snapshot is reset to 0, and the cluster's `version` moves by 1."
        PRD §3.3: "The invariant is that a rollback returns the cluster's `reserved_ccu` exactly to its pre-approval value."

        Design: Difficulty/compensating_invariant/live_event_rollback_conserves_cluster_reserved_ccu
        """
        world = _cluster_with_approved_event_and_blocked_successor()
        cluster_id = world["cluster"]["id"]
        event_a_id = world["event_a"]["id"]

        assert read_cluster(cluster_id)["reserved_ccu"] == 6000, (
            "Setup expects the approved event to hold a 6000 reservation before the rollback"
        )

        rolled_back = validate_success(
            api_client.rollback_live_event(event_a_id, {"reason": _ROLLBACK_REASON}, LIVEOPS), 200
        )
        assert rolled_back["status"] == "ROLLED_BACK", (
            f"An APPROVED event that is rolled back lands in ROLLED_BACK, got {rolled_back['status']}"
        )
        assert rolled_back["reserved_ccu_at_approval"] == 0, (
            "The snapshot is reset to 0 once the reservation is released, got "
            f"{rolled_back['reserved_ccu_at_approval']}"
        )
        assert rolled_back["rollback_reason"] == _ROLLBACK_REASON, (
            f"The supplied reason is stored as rollback_reason, got {rolled_back['rollback_reason']}"
        )

        cluster = read_cluster(cluster_id)
        assert cluster["reserved_ccu"] == 0, (
            "Releasing exactly the snapshotted 6000 returns reserved_ccu to its pre-approval 0, got "
            f"{cluster['reserved_ccu']}"
        )

    def test_released_headroom_admits_a_full_capacity_overlapping_event(self):
        """PRD §3.3: "The invariant is that a rollback returns the cluster's `reserved_ccu` exactly to its pre-approval value."
        PRD §3.3: "The neighbours considered are the events on the same cluster, other than the candidate itself, whose status is `APPROVED` or `RUNNING` and which overlap the candidate under that test; events that are `PLANNED`, `COMPLETED`, `ROLLED_BACK` or `CANCELLED` are ignored entirely."
        PRD §3.3: "The event is admissible when that load is less than or equal to the cluster's `ccu_capacity`; a load exactly equal to capacity passes, and a load one greater is refused with `ERR_CLUSTER_CAPACITY_EXCEEDED`."
        PRD §3.3: "On success the event's `forecast_ccu` is snapshotted into `reserved_ccu_at_approval`, the cluster's `reserved_ccu` grows by that same figure, and the cluster's `version` moves by 1."

        Design: Difficulty/compensating_invariant/live_event_rollback_conserves_cluster_reserved_ccu
        """
        world = _cluster_with_approved_event_and_blocked_successor()
        cluster_id = world["cluster"]["id"]
        event_a_id = world["event_a"]["id"]
        event_d_id = world["event_d"]["id"]

        validate_success(
            api_client.rollback_live_event(event_a_id, {"reason": _ROLLBACK_REASON}, LIVEOPS), 200
        )

        approved = validate_success(api_client.approve_live_event(event_d_id, LIVEOPS), 200)
        assert approved["status"] == "APPROVED", (
            "With the rolled-back neighbour ignored, a 10000-CCU candidate lands exactly on the "
            f"10000 ceiling and is admitted, got {approved['status']}"
        )
        assert approved["reserved_ccu_at_approval"] == 10000, (
            "The admitted event snapshots its own 10000 forecast, got "
            f"{approved['reserved_ccu_at_approval']}"
        )

        cluster = read_cluster(cluster_id)
        assert cluster["reserved_ccu"] == 10000, (
            "The cluster now holds only the new reservation of 10000, got "
            f"{cluster['reserved_ccu']}"
        )
        assert read_live_event(event_a_id)["status"] == "ROLLED_BACK", (
            "The rolled-back event stays terminal in ROLLED_BACK"
        )
