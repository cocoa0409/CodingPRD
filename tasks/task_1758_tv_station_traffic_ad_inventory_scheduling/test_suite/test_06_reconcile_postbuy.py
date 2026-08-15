"""As-run reconciliation, discrepancy credits, audience-delivery shortfall,
post-buy rounding order, and the week-close cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_order_line,
    approve_order,
    as_run_entry,
    assert_post_buy_report,
    create_advertiser,
    create_avail_unit,
    create_avail_week,
    create_log_day,
    create_order,
    create_program,
    create_received_copy,
    finalize_log_day,
    get_avail_unit,
    get_avail_week,
    get_log_day,
    get_post_buy,
    get_spot,
    get_success_data,
    list_line_spots,
    list_log_day_as_run_entries,
    place_spot_fresh,
    reconcile_log_day,
    setup_scheduled_scenario,
    submit_order,
    validate_error,
    validate_success,
)

TRAFFIC = TEST_USERS["trafficmanager_headers"]
BILLING = TEST_USERS["billingclerk_headers"]


class TestDiscrepancyCreditTiers:
    def test_provisional_and_final_tiers_diverge_on_same_price(self, api):
        """PRD §3.6: "Because a manual preemption is discovered while the covering log is still in `DRAFT`, it posts a provisional discrepancy credit at the early tier of §3.8 — the base price of the missed spot with no penalty — immediately against the order's ledger."
        PRD §3.8: "A failure discovered at reconciliation — after the log had been finalized — carries a penalty of twenty-five percent of the base. A failure discovered by manual preemption while the covering log was still in `DRAFT` carries no penalty at all, which is the provisional credit already posted in §3.6."

        Design: Difficulty/dual_variant_calc/discrepancy_credit_provisional_vs_final_on_spot
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=6, air_date="2026-08-08", daypart="PRIME",
            rating_estimate=5.0, num_units=2, total_seconds=120,
            spots_per_week=2, place_count=2, gross_rate_cents=20000,
            log_date="2026-08-08",
        )
        s1, s2 = ctx["placed"]
        # Manual preempt while the covering log day is still DRAFT.
        preempted = validate_success(
            api.preempt_spot(s1["id"], {"preempt_reason": "NEWS_OVERRIDE"}, TRAFFIC)
        )
        assert preempted["status"] == "PREEMPTED"
        assert preempted["preempt_reason"] == "NEWS_OVERRIDE"

        finalize_log_day(ctx["log"]["id"])
        reconcile_log_day(ctx["log"]["id"], [as_run_entry(s2["id"], False)])

        missed = get_spot(s2["id"])
        assert missed["status"] == "PREEMPTED"
        assert missed["preempt_reason"] == "OVERSOLD", (
            "a reconcile-discovered miss is marked OVERSOLD"
        )

        report = get_post_buy(ctx["order"]["id"])
        # Provisional (s1): floor(20000 * 1.00) = 20000.
        # Final (s2): floor(20000 * 1.25) = 25000. Total 45000.
        assert report["discrepancy_credit_cents"] == 45000

    def test_manual_preempt_posts_base_only_provisional_credit(self, api):
        """PRD §3.8: "A failure discovered by manual preemption while the covering log was still in `DRAFT` carries no penalty at all, which is the provisional credit already posted in §3.6."
        PRD §3.8: "Its base is the line's `gross_rate_cents`"

        Design: Difficulty/dual_variant_calc/discrepancy_credit_provisional_vs_final_on_spot
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=6, air_date="2026-08-08", daypart="PRIME",
            rating_estimate=5.0, total_seconds=120, gross_rate_cents=20000,
            log_date="2026-08-08",
        )
        spot = ctx["placed"][0]
        preempted = validate_success(
            api.preempt_spot(spot["id"], {"preempt_reason": "OVERSOLD"}, TRAFFIC)
        )
        assert preempted["status"] == "PREEMPTED"
        assert get_avail_unit(ctx["units"][0]["id"])["booked_commercial_seconds"] == 0
        report = get_post_buy(ctx["order"]["id"])
        # Early tier: floor(20000 * (1 + 0.0)) = 20000 — the base price alone.
        assert report["discrepancy_credit_cents"] == 20000


class TestAudienceShortfallVariants:
    def test_strict_vs_week_averaged_diverge(self, api):
        """PRD §3.8: "under the station's default per-spot-strict method, over-delivery on one spot never offsets under-delivery on another"
        PRD §3.8: "An agency-negotiated alternative, the week-averaged method, averages the actual ratings across the line's aired spots inside a single broadcast week before comparing to the guarantee: the weekly deficit is the amount by which the guarantee exceeds the week's average — floored at zero — multiplied by the count of the line's aired spots that week."
        PRD §3.8: "for each line, the line's deficit rollup under the selected method — the sum of per-spot deficits under the strict method, or the sum of per-week deficits under week-averaging — is valued at the line's average paid cost per point, computed as the line's `gross_rate_cents` divided by its `guaranteed_rating`, and the product is truncated down to whole cents per line"

        Design: Difficulty/dual_variant_calc/audience_shortfall_per_spot_strict_vs_week_averaged
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=1, air_date="2026-08-03", daypart="EARLY_NEWS",
            rating_estimate=5.0, num_units=2, total_seconds=120,
            spots_per_week=2, place_count=2, gross_rate_cents=30000,
            guaranteed_rating=5.0, log_date="2026-08-03", finalize=True,
        )
        s1, s2 = ctx["placed"]
        reconcile_log_day(
            ctx["log"]["id"],
            [as_run_entry(s1["id"], True, 3.0), as_run_entry(s2["id"], True, 6.0)],
        )
        # Strict: deficits max(0, 5.0-3.0)=2.0 and max(0, 5.0-6.0)=0 -> 2.0 points;
        # cpp = 30000/5.0 = 6000 -> floor(2.0 * 6000) = 12000.
        strict = get_post_buy(ctx["order"]["id"], "per_spot_strict")
        assert strict["shortfall_credit_cents"] == 12000
        # Week-averaged: avg (3.0+6.0)/2 = 4.5 -> (5.0-4.5) * 2 = 1.0 -> 6000.
        week = get_post_buy(ctx["order"]["id"], "week_averaged")
        assert week["shortfall_credit_cents"] == 6000
        assert strict["shortfall_credit_cents"] != week["shortfall_credit_cents"]

    def test_week_averaged_offsets_within_one_week(self, api):
        """PRD §3.8: "Under week-averaging, over-delivery does offset under-delivery within the same week, but different weeks never offset each other."
        PRD §3.8: "under the station's default per-spot-strict method, over-delivery on one spot never offsets under-delivery on another"

        Design: Difficulty/dual_variant_calc/audience_shortfall_per_spot_strict_vs_week_averaged
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=1, air_date="2026-08-03", daypart="EARLY_NEWS",
            rating_estimate=5.0, num_units=2, total_seconds=120,
            spots_per_week=2, place_count=2, gross_rate_cents=30000,
            guaranteed_rating=5.0, log_date="2026-08-03", finalize=True,
        )
        s1, s2 = ctx["placed"]
        reconcile_log_day(
            ctx["log"]["id"],
            [as_run_entry(s1["id"], True, 6.0), as_run_entry(s2["id"], True, 4.0)],
        )
        # Strict: max(0, 5.0-6.0)=0 and max(0, 5.0-4.0)=1.0 -> 1.0 * 6000 = 6000.
        strict = get_post_buy(ctx["order"]["id"], "per_spot_strict")
        assert strict["shortfall_credit_cents"] == 6000
        # Week-averaged: avg 5.0 meets the guarantee -> deficit 0.
        week = get_post_buy(ctx["order"]["id"], "week_averaged")
        assert week["shortfall_credit_cents"] == 0


class TestPostBuyRoundingOrder:
    def test_per_line_floor_not_order_total_floor(self, api):
        """PRD §2.7: "Where a credit is aggregated across order lines, the floor is applied per line, never on the order-level total."
        PRD §3.8: "the product is truncated down to whole cents per line, the floor applied after the multiplication and per line rather than on the order total"
        PRD §3.8: "The order's total credit is the sum of the two buckets."

        Design: Difficulty/combinatorial_formula/post_buy_per_line_floor_rounding_order
        """
        advertiser = create_advertiser(name="A4", product_category="FINANCE")
        program = create_program(
            title="Wed Daytime Block", daypart_code="DAYTIME", airs_weekday=3,
            rating_estimate=3.0,
        )
        week = create_avail_week("2026-08-03")
        unit_a = create_avail_unit(week["id"], program["id"], "2026-08-05", total_seconds=120)
        unit_b = create_avail_unit(
            week["id"], program["id"], "2026-08-05", total_seconds=120, break_position=2
        )
        order = create_order(advertiser["id"])
        line_a = add_order_line(
            order["id"], program["id"], gross_rate_cents=10000, guaranteed_rating=3.0
        )
        line_b = add_order_line(
            order["id"], program["id"], gross_rate_cents=10000, guaranteed_rating=3.0
        )
        submit_order(order["id"])
        approve_order(order["id"])
        create_received_copy(advertiser["id"], 30)
        spot_a = list_line_spots(line_a["id"])[0]
        spot_b = list_line_spots(line_b["id"])[0]
        place_spot_fresh(spot_a["id"], unit_a["id"])
        place_spot_fresh(spot_b["id"], unit_b["id"])
        log = create_log_day(week["id"], "2026-08-05")
        finalize_log_day(log["id"])
        reconcile_log_day(
            log["id"],
            [as_run_entry(spot_a["id"], True, 2.5), as_run_entry(spot_b["id"], True, 2.5)],
        )
        report = get_post_buy(order["id"], "per_spot_strict")
        # Per line: deficit max(0, 3.0-2.5) = 0.5; cpp = 10000/3.0;
        # floor(0.5 * 3333.33...) = 1666 per line -> 3332 total (never 3333).
        assert report["shortfall_credit_cents"] == 3332
        assert report["discrepancy_credit_cents"] == 0
        assert report["order_credit_cents"] == 3332

    def test_single_line_floor_applied_after_multiplication(self, api):
        """PRD §2.7: "Monetary values are integer cents throughout the API; no fractional cents are stored or returned. Credit computations multiply first and then truncate once — a floor to whole cents applied after the multiplication, with no per-step rounding."

        Design: Difficulty/combinatorial_formula/post_buy_per_line_floor_rounding_order
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=3, air_date="2026-08-05", gross_rate_cents=10000,
            guaranteed_rating=3.0, log_date="2026-08-05", finalize=True,
        )
        reconcile_log_day(
            ctx["log"]["id"], [as_run_entry(ctx["placed"][0]["id"], True, 2.5)]
        )
        report = get_post_buy(ctx["order"]["id"], "per_spot_strict")
        # floor(0.5 * (10000/3.0)) = 1666.
        assert report["shortfall_credit_cents"] == 1666
        assert report["order_credit_cents"] == 1666
        assert_post_buy_report(report)


class TestReconcileCascade:
    def test_reconcile_miss_posts_credit_and_closes_week(self, api):
        """PRD §3.8: "A spot reported not aired is treated as a miss discovered at air time: it moves from `SCHEDULED` to `PREEMPTED`, its `preempt_reason` is set to `OVERSOLD`, the line's `spot_length_seconds` is released from the unit's booked counter for its class bucket, and a discrepancy credit is posted."
        PRD §3.8: "when every log day of the owning week has reached `RECONCILED`, the week's status moves from `LOCKED` to the terminal `CLOSED`"

        Design: Difficulty/transitive_cascade/reconcile_cascade_spot_credit_week_close
        """
        ctx = setup_scheduled_scenario(
            category="PHARMA", airs_weekday=2, air_date="2026-08-04",
            daypart="LATE_FRINGE", rating_estimate=1.5, total_seconds=120,
            gross_rate_cents=20000, log_date="2026-08-04", finalize=True,
        )
        spot = ctx["placed"][0]
        reconciled = reconcile_log_day(ctx["log"]["id"], [as_run_entry(spot["id"], False)])
        assert reconciled["status"] == "RECONCILED"  # hop 1

        entries = list_log_day_as_run_entries(ctx["log"]["id"])
        assert len(entries) == 1
        assert entries[0]["spot_id"] == spot["id"]
        assert entries[0]["aired"] is False

        missed = get_spot(spot["id"])  # hop 2
        assert missed["status"] == "PREEMPTED"
        assert missed["preempt_reason"] == "OVERSOLD"
        assert get_avail_unit(ctx["units"][0]["id"])["booked_commercial_seconds"] == 0

        report = get_post_buy(ctx["order"]["id"])
        assert report["discrepancy_credit_cents"] == 25000  # floor(20000 * 1.25)

        assert get_avail_week(ctx["week"]["id"])["status"] == "CLOSED"  # hop 3

    def test_week_closes_only_when_every_log_day_reconciled(self, api):
        """PRD §3.8: "Reconciliation has one final cascade: when every log day of the owning week has reached `RECONCILED`, the week's status moves from `LOCKED` to the terminal `CLOSED`, its `version` advancing with the transition, and the week is fully settled."

        Design: Difficulty/transitive_cascade/reconcile_cascade_spot_credit_week_close
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=2, air_date="2026-08-04", daypart="LATE_FRINGE",
            rating_estimate=1.5, total_seconds=120, gross_rate_cents=20000,
            log_date="2026-08-04", finalize=True,
        )
        second_log = create_log_day(ctx["week"]["id"], "2026-08-05")
        finalize_log_day(second_log["id"])

        reconcile_log_day(
            ctx["log"]["id"],
            [as_run_entry(ctx["placed"][0]["id"], True, actual_rating=1.5)],
        )
        assert get_avail_week(ctx["week"]["id"])["status"] == "LOCKED", (
            "one log day of two is still FINALIZED, so the week stays LOCKED"
        )
        # The second log day covers no scheduled spots: the empty list is its
        # exact cover.
        reconciled = reconcile_log_day(second_log["id"], [])
        assert reconciled["status"] == "RECONCILED"
        assert get_avail_week(ctx["week"]["id"])["status"] == "CLOSED"


class TestReconcileExactCover:
    def test_empty_scheduled_set_requires_empty_entries(self, api):
        """PRD §3.8: "the payload's `entries` must contain exactly one entry per spot in `SCHEDULED` status whose `scheduled_air_date` equals the log day's date — no missing spots and no extras, else the reconcile is rejected with `ERR_RECONCILE_MISMATCH`"

        Design: Difficulty/boundary_precision_check/reconcile_empty_scheduled_set_exact_cover
        """
        program = create_program(
            title="Mon Early", daypart_code="EARLY_MORNING", airs_weekday=1,
            rating_estimate=1.0,
        )
        week = create_avail_week("2026-08-03")
        log = create_log_day(week["id"], "2026-08-03")
        finalize_log_day(log["id"])

        # A stray spot scheduled on a DIFFERENT date serves as an extra-entry probe.
        advertiser = create_advertiser(name="A12", product_category="OTHER")
        week_b = create_avail_week("2026-08-10")
        unit_b = create_avail_unit(week_b["id"], program["id"], "2026-08-10", total_seconds=60)
        order = create_order(advertiser["id"], "2026-08-03", "2026-08-16")
        line = add_order_line(
            order["id"], program["id"], weeks_requested=2, gross_rate_cents=2000
        )
        submit_order(order["id"])
        approve_order(order["id"])
        stray = list_line_spots(line["id"])[0]
        place_spot_fresh(stray["id"], unit_b["id"])

        resp = api.reconcile_log_day(
            log["id"],
            {"entries": [as_run_entry(stray["id"], True, 1.0)]},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_RECONCILE_MISMATCH)

        reconciled = reconcile_log_day(log["id"], [])
        assert reconciled["status"] == "RECONCILED"
        assert list_log_day_as_run_entries(log["id"]) == []

    def test_missing_entry_for_scheduled_spot_rejected(self, api):
        """PRD §3.8: "the payload's `entries` must contain exactly one entry per spot in `SCHEDULED` status whose `scheduled_air_date` equals the log day's date — no missing spots and no extras, else the reconcile is rejected with `ERR_RECONCILE_MISMATCH`"

        Design: Difficulty/boundary_precision_check/reconcile_empty_scheduled_set_exact_cover
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=2, air_date="2026-08-04", daypart="LATE_NEWS",
            rating_estimate=4.0, log_date="2026-08-04", finalize=True,
        )
        spot = ctx["placed"][0]
        resp = api.reconcile_log_day(ctx["log"]["id"], {"entries": []}, BILLING)
        validate_error(resp, ApiErrorId.ERR_RECONCILE_MISMATCH)
        assert get_log_day(ctx["log"]["id"])["status"] == "FINALIZED"

        reconciled = reconcile_log_day(
            ctx["log"]["id"], [as_run_entry(spot["id"], True, 4.0)]
        )
        assert reconciled["status"] == "RECONCILED"
        assert get_spot(spot["id"])["status"] == "AIRED"


class TestReconcileGating:
    def test_reconcile_requires_finalized_log(self, api):
        """PRD §3.8: "A `BillingClerk` reconciles a `FINALIZED` log day by posting its as-run entries"
        PRD §2.10: "Fourth, state legality: the target entity must be in a state from which the requested transition exists — this covers terminal-state lockdowns as well as preemption or finalization attempts against already-finalized logs — else `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/reconcile_gated_by_logday_finalized
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=2, air_date="2026-08-04", daypart="LATE_NEWS",
            rating_estimate=4.0, log_date="2026-08-04",
        )
        spot = ctx["placed"][0]
        resp = api.reconcile_log_day(
            ctx["log"]["id"],
            {"entries": [as_run_entry(spot["id"], True, 4.0)]},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_spot(spot["id"])["status"] == "SCHEDULED"
        assert list_log_day_as_run_entries(ctx["log"]["id"]) == []

        finalize_log_day(ctx["log"]["id"])
        reconciled = reconcile_log_day(
            ctx["log"]["id"], [as_run_entry(spot["id"], True, 4.0)]
        )
        assert reconciled["status"] == "RECONCILED"
        assert get_spot(spot["id"])["status"] == "AIRED"

    def test_reconcile_rejected_on_reconciled_log(self, api):
        """PRD §3.7: "A second finalization, or any action on a log day that has moved past the state the action requires, is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/reconcile_gated_by_logday_finalized
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=2, air_date="2026-08-04", daypart="LATE_NEWS",
            rating_estimate=4.0, log_date="2026-08-04", finalize=True,
        )
        spot = ctx["placed"][0]
        reconcile_log_day(ctx["log"]["id"], [as_run_entry(spot["id"], True, 4.0)])
        assert get_log_day(ctx["log"]["id"])["status"] == "RECONCILED"
        resp = api.reconcile_log_day(
            ctx["log"]["id"],
            {"entries": [as_run_entry(spot["id"], True, 4.0)]},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestReconcilePayloadContract:
    def test_aired_entry_without_actual_rating_rejected(self, api):
        """PRD §3.8: "Each entry reports the `spot_id`, whether it `aired`, and — whenever `aired` is true — the measured `actual_rating`, which must not be negative. An entry claiming a spot aired without supplying its `actual_rating` is likewise rejected with `ERR_RECONCILE_MISMATCH`."

        Design: Corner/calculations/reconcile_missing_actual_rating_rejected
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=2, air_date="2026-08-04", daypart="LATE_NEWS",
            rating_estimate=4.0, log_date="2026-08-04", finalize=True,
        )
        spot = ctx["placed"][0]
        resp = api.reconcile_log_day(
            ctx["log"]["id"],
            {"entries": [{"spot_id": spot["id"], "aired": True}]},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_RECONCILE_MISMATCH)
        assert get_log_day(ctx["log"]["id"])["status"] == "FINALIZED"


class TestShortfallInputSet:
    def test_non_aired_spots_excluded_from_shortfall(self, api):
        """PRD §3.8: "Spots that were preempted, cancelled, or never aired are excluded from both methods; only `AIRED` spots count."
        PRD §3.8: "The order's total credit is the sum of the two buckets."

        Design: Corner/calculations/audience_shortfall_input_set_excludes_non_aired
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=1, air_date="2026-08-03", daypart="EARLY_NEWS",
            rating_estimate=5.0, num_units=2, total_seconds=120,
            spots_per_week=2, place_count=2, gross_rate_cents=30000,
            guaranteed_rating=5.0, log_date="2026-08-03", finalize=True,
        )
        s1, s2 = ctx["placed"]
        reconcile_log_day(
            ctx["log"]["id"],
            [as_run_entry(s1["id"], True, 4.0), as_run_entry(s2["id"], False)],
        )
        report = get_post_buy(ctx["order"]["id"], "per_spot_strict")
        # Only the AIRED spot feeds the shortfall: deficit 5.0-4.0 = 1.0;
        # cpp = 30000/5.0 = 6000 -> 6000.
        assert report["shortfall_credit_cents"] == 6000
        # The missed spot lands in the discrepancy bucket: floor(30000 * 1.25).
        assert report["discrepancy_credit_cents"] == 37500
        assert report["order_credit_cents"] == 43500


class TestImmediateConsistency:
    def test_post_buy_reflects_reconcile_immediately(self, api):
        """PRD §3.8: "The post-buy report assembles all of this per order, on demand, for `SalesRep`, `TrafficManager`, `BillingClerk`, and `StationAdmin` readers."
        PRD §3.8: "A spot reported aired moves from `SCHEDULED` to `AIRED`."

        Design: Corner/consistency_model/immediate_consistency_post_buy_reflects_reconcile
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=2, air_date="2026-08-04", daypart="LATE_NEWS",
            rating_estimate=4.0, gross_rate_cents=10000, guaranteed_rating=4.0,
            log_date="2026-08-04", finalize=True,
        )
        spot = ctx["placed"][0]
        reconcile_log_day(ctx["log"]["id"], [as_run_entry(spot["id"], True, 3.0)])
        report = get_post_buy(ctx["order"]["id"], "per_spot_strict")
        # deficit max(0, 4.0-3.0) = 1.0; cpp = 10000/4.0 = 2500 -> 2500.
        assert report["shortfall_credit_cents"] == 2500
        assert get_spot(spot["id"])["status"] == "AIRED"
