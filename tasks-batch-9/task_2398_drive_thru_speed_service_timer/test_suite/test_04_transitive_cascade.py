"""Cascades that propagate several hops from one request.

A departure walks slot release, capacity, car rate, tier, requirement and
posture. Logging a defect walks pull-forward, slot forfeit and posture.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient
from test_helpers.test_users import ADMIN_HEADERS


# --------------------------------------------------------- departure cascade
def _committed_car_at_the_window(api: DriveThruApiClient):
    """A DUAL_PARALLEL store holding its single post-merge position."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-H",
        lane_config="DUAL_PARALLEL",
        merge_slots_capacity=1,
        staff_name="Nia Patel",
        name="Roswell Dual Parallel",
    )
    fx.set_clock(api, fx.at(11, 0, 0))
    loop = fx.open_loop(api, ctx, lane="LANE_A")
    fx.set_clock(api, fx.at(11, 0, 20))
    fx.greet_loop(api, ctx, loop["id"])
    fx.set_clock(api, fx.at(11, 1, 0))
    fx.complete_order(api, ctx, loop["id"], order_items_count=3)
    slot = fx.award_merge_slot(api, ctx)
    fx.commit_slot(api, ctx, slot["id"])
    fx.set_clock(api, fx.at(11, 2, 0))
    fx.arrive_at_window(api, ctx, loop["id"])
    fx.set_clock(api, fx.at(11, 4, 10))
    return ctx, loop["id"], slot


class TestDepartureCascade:
    """One departure moves five things."""

    def test_departure_releases_the_committed_slot_and_returns_capacity(self, api):
        """PRD §3.3: "**Hop one:** because the loop reached `CLOSED`, its merge
        slot in `COMMITTED` becomes `RELEASED`. **Hop two:** because that slot
        has left the occupied set, the store's `merge_slots_free` is recomputed,
        rising by one."

        Design: Difficulty/transitive_cascade/depart_cascade_slot_release_to_surge_posture
        """
        ctx, loop_id, slot = _committed_car_at_the_window(api)

        fx.depart_loop(api, ctx, loop_id)

        released = validate_success(api.get_merge_slot(slot["id"], ADMIN_HEADERS))
        assert released["slot_state"] == "RELEASED", released
        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_merge_capacity(store, free=1)

    def test_departure_walks_the_rate_tier_requirement_and_posture(self, api):
        """PRD §3.3: "**Hop three:** because a car closed, the rollup chain
        raises `cars_closed_trailing`, then `cars_per_hour_observed` and
        `cars_per_hour_effective`, then `volume_tier`. **Hop four:** because the
        tier may have changed, `required_oot_count` is recomputed from the new
        band's `min_oot_count`. **Hop five:** because the requirement may have
        changed, `service_posture` is recomputed, which is how a single
        departure flips a store from `OPEN` to `SURGE`."

        Design: Difficulty/transitive_cascade/depart_cascade_slot_release_to_surge_posture
        """
        ctx, loop_id, _slot = _committed_car_at_the_window(api)

        before = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(before, cars_closed_trailing=0, service_posture="OPEN")

        fx.depart_loop(api, ctx, loop_id)

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            store,
            cars_closed_trailing=1,
            cars_per_hour_observed=6.0,
            cars_per_hour_effective=6.0,
            volume_tier="TIER_2",
            required_oot_count=1,
            deployed_oot_count=0,
            service_posture="SURGE",
        )

    def test_the_departing_loop_closes_with_a_zero_merge_wait(self, api):
        """PRD §3.3: "At a store whose `lane_config` is `DUAL_TANDEM` or
        `DUAL_PARALLEL`, the car must first be awarded and committed into a
        post-merge position, taking it `ORDERED → MERGED` (see §3.4) and
        stamping `merge_at` and `merge_wait_seconds`, which is `merge_at` minus
        `order_complete_at`."

        Design: Difficulty/transitive_cascade/depart_cascade_slot_release_to_surge_posture
        """
        ctx, loop_id, slot = _committed_car_at_the_window(api)

        assert slot["award_reason"] == "ALTERNATE", slot
        assert slot["sequence_index"] == 1, slot

        departed = fx.depart_loop(api, ctx, loop_id)
        a.assert_loop_states(
            departed, timing_state="CLOSED", accuracy_state="VERIFIED"
        )
        a.assert_loop_segments(
            departed,
            merge_wait_seconds=0,
            pull_forward_seconds=60,
            window_seconds=130,
            total_seconds=250,
        )
        a.assert_breach_flags(departed, ["PULL_FORWARD", "WINDOW"])


# ---------------------------------------------------------- incident cascade
def _reserved_car_awaiting_its_merge(api: DriveThruApiClient):
    """An ordered car holding a RESERVED post-merge position, not yet committed."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-I",
        lane_config="DUAL_PARALLEL",
        merge_slots_capacity=2,
        staff_name="Cole Bryant",
        name="Sandy Springs Dual Parallel",
    )
    fx.set_clock(api, fx.at(11, 0, 0))
    loop = fx.open_loop(api, ctx, lane="LANE_A")
    fx.set_clock(api, fx.at(11, 0, 20))
    fx.greet_loop(api, ctx, loop["id"])
    fx.set_clock(api, fx.at(11, 1, 0))
    fx.complete_order(api, ctx, loop["id"], order_items_count=6)
    slot = fx.award_merge_slot(api, ctx)
    fx.set_clock(api, fx.at(11, 1, 30))
    return ctx, loop["id"], slot["id"]


class TestIncidentCascade:
    """Logging a defect on a reserved car costs it its place in line."""

    def test_logging_auto_issues_a_remake_open_pull_forward(self, api):
        """PRD §3.6: "**Hop one:** because the loop's accuracy dimension became
        `REMAKE_OPEN`, a pull-forward order with `reason` `REMAKE_OPEN` is
        auto-issued whenever that loop is holding a merge slot in `RESERVED`."

        Design: Difficulty/transitive_cascade/incident_cascade_pull_forward_forfeits_reserved_slot
        """
        ctx, loop_id, _slot_id = _reserved_car_awaiting_its_merge(api)

        incident = validate_success(
            api.create_accuracy_incident(
                {
                    "timer_loop_id": loop_id,
                    "logged_by_staff_id": ctx.staff_id,
                    "incident_type": "MISSING_ITEM",
                },
                ctx.leader_headers,
            ),
            expected_status=201,
        )
        assert incident["severity"] == "MAJOR", incident
        assert incident["penalty_seconds"] == 45, incident
        assert incident["remake_cost_cents"] == 750, incident
        assert incident["incident_state"] == "LOGGED", incident
        assert incident["settlement_state"] == "ACCRUED", incident

        orders, meta = validate_paginated(
            api.list_pull_forward_orders(ADMIN_HEADERS, {"timer_loop_id": loop_id})
        )
        assert meta["total_count"] == 1, meta
        assert orders[0]["pf_state"] == "ISSUED", orders[0]
        assert orders[0]["reason"] == "REMAKE_OPEN", orders[0]
        assert orders[0]["escalation_count"] == 0, orders[0]

    def test_the_auto_issued_pull_forward_forfeits_the_reserved_slot(self, api):
        """PRD §3.6: "**Hop two:** because that pull-forward entered `ISSUED`,
        the held slot becomes `FORFEITED` and `merge_slots_free` is recomputed
        upward by one."

        Design: Difficulty/transitive_cascade/incident_cascade_pull_forward_forfeits_reserved_slot
        """
        ctx, loop_id, slot_id = _reserved_car_awaiting_its_merge(api)

        fx.log_incident(api, ctx, loop_id, incident_type="MISSING_ITEM")

        slot = validate_success(api.get_merge_slot(slot_id, ADMIN_HEADERS))
        assert slot["slot_state"] == "FORFEITED", slot
        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_merge_capacity(store, free=2)

        loop = validate_success(api.get_timer_loop(loop_id, ADMIN_HEADERS))
        a.assert_loop_states(loop, timing_state="ORDERED", accuracy_state="REMAKE_OPEN")
        assert loop["adjusted_total_seconds"] is None, loop
        assert loop["total_seconds"] is None, loop

    def test_the_open_remake_raises_the_requirement_into_surge(self, api):
        """PRD §3.6: "**Hop three:** because `open_remake_count` rose, the rollup
        chain re-derives `required_oot_count` — remember the accuracy bump adds
        an outside order-taker as soon as a single remake is open — and then
        `service_posture`, which reaches `ACCURACY_HOLD` at two or more open
        remakes and thereby blocks further merge awards."

        Design: Difficulty/transitive_cascade/incident_cascade_pull_forward_forfeits_reserved_slot
        """
        ctx, loop_id, _slot_id = _reserved_car_awaiting_its_merge(api)

        fx.log_incident(api, ctx, loop_id, incident_type="MISSING_ITEM")

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            store,
            cars_closed_trailing=0,
            open_remake_count=1,
            remake_cost_accrued_cents=750,
            required_oot_count=1,
            deployed_oot_count=0,
            service_posture="SURGE",
        )
