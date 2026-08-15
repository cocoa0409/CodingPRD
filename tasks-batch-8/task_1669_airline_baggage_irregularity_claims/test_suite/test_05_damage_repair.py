"""Damage assessment and the repair workshop: depreciation, repair-vs-replace,
bench capacity (PRD §3.7)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_repair_order_payload,
    create_repair_vendor,
    setup_bag_and_report, setup_damage_report_repairable,
    setup_damage_report_claim_review,
    assert_vendor_slot_invariants,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


class TestAssessDamagePreconditions:

    def test_assess_damage_requires_damage_review(self, api):
        """PRD §3.7: "Assessing a report that is not in `DAMAGE_REVIEW` is rejected
        with `ERR_REPORT_NOT_IN_DAMAGE_REVIEW`."

        Design: Corner/state_machines/assess_damage_requires_damage_review
        """
        ctx = setup_bag_and_report(report_type="DELAYED")  # TRACING, never DAMAGE_REVIEW
        resp = api.assess_damage(ctx["report"]["id"],
                                 {"repairable": False, "contents_damage_cents": 5000},
                                 ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_IN_DAMAGE_REVIEW, 409)
        report_now = get_success_data(api.get_report(ctx["report"]["id"], ADJUSTER))
        assert report_now["status"] == "TRACING"


class TestRepairOrderCreation:

    def test_repair_on_pilfered_report_rejected(self, api):
        """PRD §3.7: "Repair orders exist only for `DAMAGED` reports in
        `DAMAGE_REVIEW` whose assessment marked the bag repairable: a request
        against a non-`DAMAGED` report or one whose `damage_repairable` is not true
        is rejected with `ERR_REPAIR_NOT_ALLOWED_FOR_TYPE`"

        Design: Corner/validations/repair_on_pilfered_report_rejected
        """
        ctx = setup_bag_and_report(report_type="PILFERED")
        vendor = create_repair_vendor()
        # PILFERED report sits in the same DAMAGE_REVIEW state; assess it repairable.
        get_success_data(api.assess_damage(
            ctx["report"]["id"],
            {"repairable": True, "contents_damage_cents": 5000}, ADJUSTER))
        resp = api.create_repair_order(
            create_repair_order_payload(ctx["report"]["id"], vendor["id"]), ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_REPAIR_NOT_ALLOWED_FOR_TYPE, 409)

    def test_repair_window_equal_dates_rejected(self, api):
        """PRD §3.7: "The dates must form a valid window — `promised_date` strictly
        after `intake_date`, and `purchase_date` on or before `intake_date` —
        failing which the request is rejected with `ERR_REPAIR_WINDOW_INVALID`
        (HTTP 422)."

        Design: Corner/validations/repair_window_invalid_rejected
        """
        ctx = setup_damage_report_repairable(contents_damage_cents=0)
        vendor = create_repair_vendor()
        resp = api.create_repair_order(
            create_repair_order_payload(ctx["report"]["id"], vendor["id"],
                                        intake_date="2026-08-05",
                                        promised_date="2026-08-05"), ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_REPAIR_WINDOW_INVALID, 422)


class TestDepreciationDecision:

    def test_depreciation_floor_after_eleven_years(self, api):
        """PRD §3.7: "the raw value is the original `purchase_price_cents`
        multiplied by 0.8 once for each of those years — a twenty-percent annual
        decay, compounding. The raw value is rounded half up to whole cents, and
        `depreciated_value_cents` is the greater of that rounded figure and a floor
        equal to ten percent of the purchase price, itself rounded half up to whole
        cents. The computed `decision` is `REPAIR` when the `repair_estimate_cents`
        is strictly less than seventy-five percent of the depreciated value, and
        `REPLACE` otherwise."

        Design: Corner/calculations/depreciation_floor_applies_after_eleven_years
        """
        ctx = setup_damage_report_repairable(contents_damage_cents=0)
        vendor = create_repair_vendor(bench_capacity=2)
        # purchase 2015-08-01, intake 2026-08-10: 11 full 365-day periods.
        # raw = 10000 * 0.8^11 = 858.99 -> 859; floor = 1000; floor binds.
        order = get_success_data(api.create_repair_order(
            create_repair_order_payload(ctx["report"]["id"], vendor["id"],
                                        intake_date="2026-08-10",
                                        promised_date="2026-08-20",
                                        purchase_price_cents=10000,
                                        purchase_date="2015-08-01",
                                        repair_estimate_cents=500), ADJUSTER))
        decided = validate_success(api.decide_repair_order(order["id"], ADJUSTER), 200)
        assert decided["depreciated_value_cents"] == 1000
        # 500 < 0.75 * 1000 = 750 -> REPAIR
        assert decided["decision"] == "REPAIR"
        completed = validate_success(api.complete_repair_order(order["id"], ADJUSTER),
                                     200)
        # REPAIR payout = min(repair_estimate, depreciated value) = min(500, 1000).
        assert completed["payout_cents"] == 500
        assert completed["status"] == "REPAIR_SETTLED"

    def test_decision_replace_at_threshold(self, api):
        """PRD §3.7: "The computed `decision` is `REPAIR` when the
        `repair_estimate_cents` is strictly less than seventy-five percent of the
        depreciated value, and `REPLACE` otherwise."
        PRD §3.7: "From `REPLACEMENT_PENDING`, completion moves the order to
        `REPLACE_SETTLED` and sets `payout_cents` to the full depreciated value."

        Design: Corner/calculations/depreciation_floor_applies_after_eleven_years
        """
        ctx = setup_damage_report_repairable(contents_damage_cents=0)
        vendor = create_repair_vendor(bench_capacity=2)
        # purchase 2024-08-01, intake 2026-08-05: 2 full years.
        # raw = 100000 * 0.64 = 64000; floor 10000; depreciated = 64000.
        # estimate 50000 >= 0.75 * 64000 = 48000 -> REPLACE.
        order = get_success_data(api.create_repair_order(
            create_repair_order_payload(ctx["report"]["id"], vendor["id"],
                                        repair_estimate_cents=50000), ADJUSTER))
        decided = validate_success(api.decide_repair_order(order["id"], ADJUSTER), 200)
        assert decided["depreciated_value_cents"] == 64000
        assert decided["decision"] == "REPLACE"
        completed = validate_success(api.complete_repair_order(order["id"], ADJUSTER),
                                     200)
        assert completed["status"] == "REPLACE_SETTLED"
        assert completed["payout_cents"] == 64000


class TestSettlementOfferWithRepair:

    def _setup_repair_settled(self, api):
        """DAMAGED domestic 20kg report, repairable, repair order completed.

        Repair: purchase 100000 on 2024-08-01, intake 2026-08-05 (2 years ->
        depreciated 64000), estimate 40000 -> REPAIR, payout min(40000, 64000).
        """
        ctx = setup_damage_report_repairable(contents_damage_cents=15000)
        vendor = create_repair_vendor(bench_capacity=2)
        order = get_success_data(api.create_repair_order(
            create_repair_order_payload(ctx["report"]["id"], vendor["id"],
                                        repair_estimate_cents=40000), ADJUSTER))
        get_success_data(api.decide_repair_order(order["id"], ADJUSTER))
        completed = get_success_data(api.complete_repair_order(order["id"], ADJUSTER))
        return ctx, vendor, order, completed

    def test_offer_combines_repair_payout_and_contents_damage(self, api):
        """PRD §3.8: "a `DAMAGED` report uses its `repair_payout_cents` plus its
        `contents_damage_cents` (treated as zero while null) ... The offer is then
        the lesser of the report's `effective_cap_cents` and that loss basis."
        PRD §3.7: "From `REPAIR_IN_PROGRESS`, completion moves the order to
        `REPAIR_SETTLED` and sets `payout_cents` to the lesser of the repair
        estimate and the depreciated value."

        Design: Difficulty/combinatorial_formula/settlement_offer_nested_min_max_branch
        """
        ctx, vendor, order, completed = self._setup_repair_settled(api)
        assert completed["decision"] == "REPAIR"
        assert completed["depreciated_value_cents"] == 64000
        assert completed["payout_cents"] == 40000

        resp = api.offer_settlement(
            ctx["report"]["id"],
            {"root_cause": "LOADING_ERROR",
             "root_cause_station_id": ctx["station"]["id"]}, ADJUSTER)
        report = validate_success(resp, 200)
        # loss_basis = 40000 + 15000 = 55000; DOMESTIC 20kg cap = 50000 binds.
        assert report["effective_cap_cents"] == 50000
        assert report["settlement_offer_cents"] == 50000
        assert report["amount_payable_cents"] == 50000

    def test_repair_completion_cascades_report_to_claim_review(self, api):
        """PRD §3.7: "Either way the vendor's bench slot is released —
        `occupied_bench_slots` decremented, `available_bench_slots` restored — and
        the settlement cascades into the report: the report moves from
        `DAMAGE_REVIEW` to `CLAIM_REVIEW`, its `repair_payout_cents` takes the
        order's `payout_cents`"

        Design: Difficulty/combinatorial_formula/settlement_offer_nested_min_max_branch
        """
        ctx, vendor, order, completed = self._setup_repair_settled(api)
        report_now = get_success_data(api.get_report(ctx["report"]["id"], ADJUSTER))
        assert report_now["status"] == "CLAIM_REVIEW"
        assert report_now["repair_payout_cents"] == 40000
        vendor_now = get_success_data(api.get_repair_vendor(vendor["id"], ADJUSTER))
        assert vendor_now["occupied_bench_slots"] == 0
        assert_vendor_slot_invariants(vendor_now)


class TestBenchCapacity:

    def test_half_open_interval_and_capacity_limit(self, api):
        """PRD §3.7: "An order occupies its vendor's bench over the half-open range
        from `intake_date` up to but not including `promised_date`, so an order
        ending on a given day does not overlap one beginning that same day. If any
        day in that range would hold `bench_capacity` or more open repair orders at
        the vendor — orders in `INTAKE`, `REPAIR_IN_PROGRESS`, or
        `REPLACEMENT_PENDING` — creation is rejected with
        `ERR_VENDOR_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/repair_vendor_half_open_bench_capacity
        """
        ctx = setup_damage_report_repairable()
        vendor = create_repair_vendor(bench_capacity=2)
        rpt = ctx["report"]["id"]
        # A: [08-03, 08-10); B: [08-05, 08-12) -> days 08-05..08-09 carry 2 orders.
        order_a = get_success_data(api.create_repair_order(
            create_repair_order_payload(rpt, vendor["id"],
                                        intake_date="2026-08-03",
                                        promised_date="2026-08-10"), ADJUSTER))
        order_b = get_success_data(api.create_repair_order(
            create_repair_order_payload(rpt, vendor["id"],
                                        intake_date="2026-08-05",
                                        promised_date="2026-08-12"), ADJUSTER))
        assert order_a["status"] == "INTAKE" and order_b["status"] == "INTAKE"

        # C starts the day A ends: [08-10, 08-15) overlaps only B -> allowed.
        order_c = validate_success(api.create_repair_order(
            create_repair_order_payload(rpt, vendor["id"],
                                        intake_date="2026-08-10",
                                        promised_date="2026-08-15"), ADJUSTER), 201)
        assert order_c["status"] == "INTAKE"

        # D: [08-06, 08-09) overlaps both A and B -> third order on a full day.
        resp_d = api.create_repair_order(
            create_repair_order_payload(rpt, vendor["id"],
                                        intake_date="2026-08-06",
                                        promised_date="2026-08-09"), ADJUSTER)
        validate_error(resp_d, ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED, 409)
        vendor_now = get_success_data(api.get_repair_vendor(vendor["id"], ADJUSTER))
        assert vendor_now["occupied_bench_slots"] == 3

    def test_touching_intervals_never_overlap(self, api):
        """PRD §3.7: "an order ending on a given day does not overlap one beginning
        that same day."

        Design: Difficulty/resource_temporal_overlap/repair_vendor_half_open_bench_capacity
        """
        ctx = setup_damage_report_repairable()
        vendor = create_repair_vendor(bench_capacity=1)
        rpt = ctx["report"]["id"]
        # Capacity 1: two back-to-back orders must both fit.
        get_success_data(api.create_repair_order(
            create_repair_order_payload(rpt, vendor["id"],
                                        intake_date="2026-08-03",
                                        promised_date="2026-08-10"), ADJUSTER))
        resp = api.create_repair_order(
            create_repair_order_payload(rpt, vendor["id"],
                                        intake_date="2026-08-10",
                                        promised_date="2026-08-12"), ADJUSTER)
        second = validate_success(resp, 201)
        assert second["status"] == "INTAKE"


class TestBenchSlotConservation:

    def test_slots_conserved_across_intake_and_completion(self, api):
        """PRD §3.7: "A created order starts in `INTAKE`, and the vendor's
        `occupied_bench_slots` is incremented while `available_bench_slots` falls by
        one."
        PRD §3.7: "Either way the vendor's bench slot is released —
        `occupied_bench_slots` decremented, `available_bench_slots` restored"

        Design: Difficulty/compensating_invariant/vendor_bench_slots_conserved_across_intake_and_completion
        """
        ctx = setup_damage_report_repairable()
        vendor = create_repair_vendor(bench_capacity=3)
        order = get_success_data(api.create_repair_order(
            create_repair_order_payload(ctx["report"]["id"], vendor["id"],
                                        repair_estimate_cents=40000), ADJUSTER))
        get_success_data(api.decide_repair_order(order["id"], ADJUSTER))

        vendor_mid = get_success_data(api.get_repair_vendor(vendor["id"], ADJUSTER))
        assert vendor_mid["occupied_bench_slots"] == 1
        assert vendor_mid["available_bench_slots"] == 2
        assert_vendor_slot_invariants(vendor_mid)

        completed = validate_success(api.complete_repair_order(order["id"], ADJUSTER),
                                     200)
        assert completed["status"] == "REPAIR_SETTLED"
        vendor_after = get_success_data(api.get_repair_vendor(vendor["id"], ADJUSTER))
        assert vendor_after["occupied_bench_slots"] == 0
        assert vendor_after["available_bench_slots"] == 3
        assert_vendor_slot_invariants(vendor_after)

    def test_completion_moves_report_to_claim_review(self, api):
        """PRD §3.7: "the settlement cascades into the report: the report moves from
        `DAMAGE_REVIEW` to `CLAIM_REVIEW`, its `repair_payout_cents` takes the
        order's `payout_cents`"

        Design: Difficulty/compensating_invariant/vendor_bench_slots_conserved_across_intake_and_completion
        """
        ctx = setup_damage_report_repairable()
        vendor = create_repair_vendor(bench_capacity=3)
        order = get_success_data(api.create_repair_order(
            create_repair_order_payload(ctx["report"]["id"], vendor["id"]), ADJUSTER))
        get_success_data(api.decide_repair_order(order["id"], ADJUSTER))
        get_success_data(api.complete_repair_order(order["id"], ADJUSTER))
        report_now = get_success_data(api.get_report(ctx["report"]["id"], ADJUSTER))
        assert report_now["status"] == "CLAIM_REVIEW"
        assert report_now["repair_payout_cents"] == 40000
