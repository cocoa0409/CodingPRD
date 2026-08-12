"""Performance parallel state dimensions, readiness gates, completion, and the
three-level cancellation cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_done_tech_slot,
    get_performance,
    get_seat_inventory,
    set_clock,
    setup_cleared_performance,
    setup_net_share_performance,
    setup_readiness_scenario,
    transition_surtitle_track,
    validate_error,
    validate_success,
)

BOM = TEST_USERS["box_office_manager_headers"]
TD = TEST_USERS["technical_director_headers"]
PM = TEST_USERS["production_manager_headers"]
ANY = TEST_USERS["any_headers"]


class TestParallelDimensions:
    def test_parallel_dimensions_full_chain(self, api):
        """PRD §3.8: "Those three statuses are **parallel dimensions** evolving independently on the same row; no transition on one dimension implies a transition on another. On the sales dimension, opening sales — `NOT_ON_SALE` → `ON_SALE` — requires the performance still to be `SCHEDULED`, else `ERR_INVALID_STATE_TRANSITION`; suspending sales moves `ON_SALE` back to `NOT_ON_SALE`; closing sales moves `ON_SALE` → `SALES_CLOSED`."
        PRD §3.8: "Clearing for audience — `TECH_READY` → `CLEARED_FOR_AUDIENCE` — has no further conditions."

        open-sales -> tech-ready -> suspend-sales -> open-sales -> close-sales ->
        clear: the readiness transition succeeds while ON_SALE and the sales
        revert succeeds while TECH_READY.

        Design: Difficulty/non_linear_state_machine/performance_parallel_dims_independent
        """
        scenario = setup_readiness_scenario(surtitle_final_state="LIVE",
                                            with_done_tech_slot=True)
        perf_id = scenario["performance"]["id"]

        validate_success(api.open_sales(perf_id, BOM), 200)
        tech_ready = validate_success(api.mark_tech_ready(perf_id, TD), 200)
        assert tech_ready["readiness_status"] == "TECH_READY", (
            "tech-ready succeeded while sales_status was ON_SALE"
        )
        suspended = validate_success(api.suspend_sales(perf_id, BOM), 200)
        assert suspended["sales_status"] == "NOT_ON_SALE", (
            "suspend-sales succeeded while readiness_status was TECH_READY"
        )
        validate_success(api.open_sales(perf_id, BOM), 200)
        closed = validate_success(api.close_sales(perf_id, BOM), 200)
        assert closed["sales_status"] == "SALES_CLOSED"
        cleared = validate_success(api.clear_for_audience(perf_id, TD), 200)
        assert cleared["sales_status"] == "SALES_CLOSED"
        assert cleared["readiness_status"] == "CLEARED_FOR_AUDIENCE"
        assert cleared["lifecycle_status"] == "SCHEDULED", (
            "no transition on one dimension implies a transition on another"
        )

    def test_sales_suspend_revert_leaves_readiness_untouched(self, api):
        """PRD §3.8: "Those three statuses are **parallel dimensions** evolving independently on the same row; no transition on one dimension implies a transition on another."
        PRD §3.8: "suspending sales moves `ON_SALE` back to `NOT_ON_SALE`; closing sales moves `ON_SALE` → `SALES_CLOSED`."

        Design: Difficulty/non_linear_state_machine/performance_parallel_dims_independent
        """
        scenario = setup_readiness_scenario(surtitle_final_state="LIVE",
                                            with_done_tech_slot=True)
        perf_id = scenario["performance"]["id"]

        opened = validate_success(api.open_sales(perf_id, BOM), 200)
        assert opened["sales_status"] == "ON_SALE"
        assert opened["readiness_status"] == "AWAITING_TECH"

        suspended = validate_success(api.suspend_sales(perf_id, BOM), 200)
        assert suspended["sales_status"] == "NOT_ON_SALE", "sales dimension revert"
        assert suspended["readiness_status"] == "AWAITING_TECH", (
            "the readiness dimension is untouched by sales transitions"
        )
        assert suspended["lifecycle_status"] == "SCHEDULED"


class TestReadinessGate:
    def test_tech_ready_blocked_until_surtitle_live(self, api):
        """PRD §3.8: "On the readiness dimension, marking tech-ready — `AWAITING_TECH` → `TECH_READY` — first requires the performance still `SCHEDULED`, else `ERR_INVALID_STATE_TRANSITION`, and then enforces three gate conditions, any failure surfacing as `ERR_READINESS_GATE_BLOCKED`: a stage slot of the same production with `slot_type` `TECH` and status `DONE` whose `ends_at` is no later than the performance's `starts_at`; a surtitle track of the same production whose `language` equals the production's `default_surtitle_language` and whose status is `LIVE`; and the production itself in `REHEARSAL` or `IN_REPERTORY`."

        Track at CUES_LOCKED blocks the gate; LIVE releases it.

        Design: Difficulty/cross_entity_state_dependency/tech_ready_requires_surtitle_live
        """
        scenario = setup_readiness_scenario(surtitle_final_state="CUES_LOCKED",
                                            with_done_tech_slot=True)
        perf_id = scenario["performance"]["id"]
        track_id = scenario["track"]["id"]

        resp = api.mark_tech_ready(perf_id, TD)
        validate_error(resp, ApiErrorId.ERR_READINESS_GATE_BLOCKED)

        transition_surtitle_track(track_id, "LIVE")
        resp = api.mark_tech_ready(perf_id, TD)
        ready = validate_success(resp, 200)
        assert ready["readiness_status"] == "TECH_READY"

    def test_tech_ready_blocked_without_done_tech_slot(self, api):
        """PRD §3.8: "On the readiness dimension, marking tech-ready — `AWAITING_TECH` → `TECH_READY` — first requires the performance still `SCHEDULED`, else `ERR_INVALID_STATE_TRANSITION`, and then enforces three gate conditions, any failure surfacing as `ERR_READINESS_GATE_BLOCKED`: a stage slot of the same production with `slot_type` `TECH` and status `DONE` whose `ends_at` is no later than the performance's `starts_at`; a surtitle track of the same production whose `language` equals the production's `default_surtitle_language` and whose status is `LIVE`; and the production itself in `REHEARSAL` or `IN_REPERTORY`."

        The default-language track is LIVE but no DONE tech slot exists yet;
        adding and completing one releases the gate.

        Design: Difficulty/cross_entity_state_dependency/tech_ready_requires_surtitle_live
        """
        scenario = setup_readiness_scenario(surtitle_final_state="LIVE",
                                            with_done_tech_slot=False)
        perf_id = scenario["performance"]["id"]
        production = scenario["production"]

        resp = api.mark_tech_ready(perf_id, TD)
        validate_error(resp, ApiErrorId.ERR_READINESS_GATE_BLOCKED)

        create_done_tech_slot(production["id"], "2026-07-04T10:00:00Z", "2026-07-04T14:00:00Z")
        resp = api.mark_tech_ready(perf_id, TD)
        ready = validate_success(resp, 200)
        assert ready["readiness_status"] == "TECH_READY"


class TestCompletion:
    def test_performance_complete_conditional_action(self, api):
        """PRD §3.8: "On the lifecycle dimension, marking the performance completed requires the logical clock to be strictly past `ends_at` — an early complete is rejected with `ERR_PERFORMANCE_NOT_ENDED` — and the readiness dimension to have reached `CLEARED_FOR_AUDIENCE`, else `ERR_READINESS_GATE_BLOCKED`."
        PRD §2.5: "At startup the clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time afterwards."

        Readiness is CLEARED_FOR_AUDIENCE; at the startup clock the complete is
        rejected, and after the clock passes curtain-down it succeeds.

        Design: Corner/endpoints/performance_complete_conditional_action
        """
        scenario = setup_cleared_performance()
        perf_id = scenario["performance"]["id"]

        resp = api.complete_performance(perf_id, BOM)
        validate_error(resp, ApiErrorId.ERR_PERFORMANCE_NOT_ENDED)

        set_clock("2026-07-06T00:00:00Z")
        resp = api.complete_performance(perf_id, BOM)
        completed = validate_success(resp, 200)
        assert completed["lifecycle_status"] == "COMPLETED"


class TestCancelCascade:
    def test_performance_cancel_three_level_cascade(self, api):
        """PRD §3.8: "Cancellation, executed by a `ProductionManager`, triggers a three-level cascade: every seat inventory of the performance is zeroed — `seats_held` and `seats_sold` to zero and `current_price_cents` recomputed at a sold ratio of zero — and the performance's `realized_revenue_cents` is reset to zero; the production's `season_revenue_cents` is recomputed because a cancelled performance no longer contributes; and every `RATIFIED` `NET_REVENUE_SHARE` co-production share of the production has its `accrued_revenue_share_cents` recomputed from the new season revenue."

        Before cancel: 5 seats sold (revenue 100,000), season revenue 100,000,
        net share accrual 40,000. After cancel: all three levels return to zero.

        Design: Difficulty/transitive_cascade/performance_cancel_depth3_cascade
        """
        scenario = setup_net_share_performance(share_percentage=40)
        performance = scenario["performance"]
        production = scenario["production"]
        share = scenario["share"]
        inventory = scenario["inventory"]
        validate_success(api.purchase_seats(inventory["id"], 5, BOM), 200)

        cancelled = validate_success(api.cancel_performance(performance["id"], PM), 200)
        assert cancelled["lifecycle_status"] == "CANCELLED"
        assert cancelled["realized_revenue_cents"] == 0, "refund on cancel"

        inventory_after = get_seat_inventory(inventory["id"])
        assert inventory_after["seats_sold"] == 0, "cascade link 1"
        assert inventory_after["seats_held"] == 0, "cascade link 1"

        production_after = validate_success(api.get_production(production["id"], ANY), 200)
        assert production_after["season_revenue_cents"] == 0, (
            "cascade link 2: 100,000 -> 0"
        )

        share_after = validate_success(api.get_co_production_share(share["id"], ANY), 200)
        assert share_after["accrued_revenue_share_cents"] == 0, (
            "cascade link 3: 40,000 -> 0"
        )

    def test_performance_cancel_recomputes_inventory_price_at_zero_ratio(self, api):
        """PRD §3.8: "every seat inventory of the performance is zeroed — `seats_held` and `seats_sold` to zero and `current_price_cents` recomputed at a sold ratio of zero — and the performance's `realized_revenue_cents` is reset to zero"
        PRD §3.8: "The price is recomputed when the inventory is created and after every purchase; holds and releases do not move the ratio and do not recompute the price."

        After 80 of 100 STALLS @ 20,000 sell (ratio 0.8 -> multiplier 1.5, price
        30,000), cancellation re-prices the inventory at sold ratio zero, back
        to the section-adjusted base of 20,000.

        Design: Difficulty/transitive_cascade/performance_cancel_depth3_cascade
        """
        scenario = setup_net_share_performance(share_percentage=40)
        performance = scenario["performance"]
        inventory = scenario["inventory"]
        validate_success(api.purchase_seats(inventory["id"], 80, BOM), 200)
        priced = get_seat_inventory(inventory["id"])
        assert priced["current_price_cents"] == 30_000, "ratio 0.8 -> multiplier 1.5"

        validate_success(api.cancel_performance(performance["id"], PM), 200)
        inventory_after = get_seat_inventory(inventory["id"])
        assert inventory_after["current_price_cents"] == 20_000, (
            "recomputed at a sold ratio of zero: round_half_up(20000*1.0)*1.0"
        )
