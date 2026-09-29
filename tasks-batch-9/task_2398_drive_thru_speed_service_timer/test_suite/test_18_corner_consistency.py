"""Consistency: a mutation's own response already carries the recomputed store.

There is no window in which the response body and a follow-up read disagree.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient


class TestUnfreezeRecomputeIsImmediate:
    """Unfreezing does not land on OPEN just because the freeze is gone."""

    def test_the_unfreeze_response_itself_reports_the_accuracy_hold_it_recomputed(
        self, api: DriveThruApiClient
    ):
        """PRD §2.6: "Unfreezing requires `posture_override` to currently be `FROZEN`; it
        sets `posture_override` back to `NONE`, sets `freeze_reason` back to null,
        increments `version` by 1, and then re-runs the rollup chain — so unfreezing does
        not necessarily land on `OPEN`. If the recompute finds two or more open remakes the
        store lands on `ACCURACY_HOLD`; if it finds fewer than two open remakes but more
        outside order-takers required than deployed, it lands on `SURGE`; otherwise it
        lands on `OPEN`."
        PRD §2.7: "The routine runs after any of the following: a timer loop departs or is
        abandoned; a merge slot changes state; an accuracy incident is created, remade,
        closed or waived; a deployment is activated, released or aborted; a forecast
        override is put into force; the store's staffing basis or labor budget is adjusted;
        the store is frozen or unfrozen; the logical clock is advanced."
        And: "`remake_cost_accrued_cents` is the sum of `remake_cost_cents` over the
        store's accuracy incidents whose `settlement_state` is either `ACCRUED` or
        `CHARGED`."
        PRD §3.2: "An **accuracy bump** of 1 applies when `open_remake_count` is at least
        1; otherwise it is 0."

        Design: Corner/consistency_model/consistency_unfreeze_response_already_shows_recomputed_posture
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-70",
            staff_name="Corner Juno",
            name="Corner Immediate Consistency Store",
        )

        first = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=None,
        )
        fx.set_clock(api, fx.at(11, 1, 30))
        cheap = fx.log_incident(api, ctx, first["id"], incident_type="WRONG_SIZE")
        assert cheap["remake_cost_cents"] == 350, cheap

        second = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 2, 0),
            greet_at=fx.at(11, 2, 20),
            order_complete_at=fx.at(11, 3, 0),
            window_arrive_at=None,
        )
        fx.set_clock(api, fx.at(11, 3, 30))
        dear = fx.log_incident(api, ctx, second["id"], incident_type="WRONG_ITEM")
        assert dear["remake_cost_cents"] == 750, dear
        assert dear["restaurant_id"] == ctx.restaurant_id, dear

        held = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            held,
            open_remake_count=2,
            remake_cost_accrued_cents=1100,
            service_posture="ACCURACY_HOLD",
        )
        version_held = held["version"]

        frozen = validate_success(
            api.freeze_restaurant(
                ctx.restaurant_id,
                f.freeze_body("Lane closed for a health inspection walkthrough"),
                ctx.operator_headers,
            )
        )
        assert frozen["service_posture"] == "FROZEN", frozen
        assert frozen["version"] == version_held + 1, (version_held, frozen)

        thawed = validate_success(
            api.unfreeze_restaurant(ctx.restaurant_id, ctx.operator_headers)
        )

        # The response is not stale-FROZEN and not naively-OPEN: it is the recompute.
        assert thawed["posture_override"] == "NONE", thawed
        assert thawed["freeze_reason"] is None, thawed
        a.assert_rollup(
            thawed,
            cars_per_hour_effective=0.0,
            volume_tier="TIER_1",
            required_oot_count=1,
            open_remake_count=2,
            remake_cost_accrued_cents=1100,
            service_posture="ACCURACY_HOLD",
        )
        a.assert_merge_capacity(thawed, free=1)
        assert thawed["version"] == frozen["version"] + 1, (frozen, thawed)

        # A follow-up read agrees field for field; there is no lag window.
        reread = fx.get_restaurant(api, ctx.restaurant_id)
        for field in (
            "service_posture",
            "posture_override",
            "freeze_reason",
            "open_remake_count",
            "remake_cost_accrued_cents",
            "required_oot_count",
            "deployed_oot_count",
            "cars_per_hour_observed",
            "cars_per_hour_effective",
            "volume_tier",
            "merge_slots_free",
            "version",
        ):
            assert reread[field] == thawed[field], (field, reread, thawed)
