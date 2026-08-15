"""Hull delivery: certification/recall-hold gates, floor-plan headroom, the
delivery cascade (advance -> utilization -> tier), tier lock evaluation order,
and curtailment settlement (PRD §3.6, §3.7, §2.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_dealer_order,
    assert_floor_plan_advance,
    assert_hull,
    book_order_no_options,
    book_order_tower_ballast,
    certify_hull,
    confirm_order,
    create_dealer,
    create_curtailment_payload,
    create_hull,
    curtail,
    deliver_hull,
    get_dealer,
    get_hull,
    get_order,
    list_advances,
    make_dealer_principal_headers,
    make_production_planner_headers,
    set_clock,
    setup_bookable_world,
    setup_certified_hull,
    setup_committed_hull,
    setup_delivered_hull,
    setup_issued_campaign,
    validate_error,
    validate_paginated,
    validate_success,
)

ANY = TEST_USERS["any_headers"]


class TestDeliveryGates:
    def test_deliver_uncertified_hull_rejected(self, api):
        """PRD §3.6: "Four preconditions hold: the hull's `delivery_status` is
        still `AT_PLANT` (else `ERR_INVALID_HULL_STATE`); the hull is not under
        recall hold (`ERR_HULL_RECALL_HOLD`); the hull is `CERTIFIED` (an
        `UNCERTIFIED` hull draws `ERR_HULL_NOT_CERTIFIED`)"

        Design: Difficulty/cross_entity_state_dependency/hull_delivery_gated_on_hull_certification_state
        """
        world = setup_committed_hull(api, with_options=False)
        hull = world["hull"]
        assert hull["certification_status"] == "UNCERTIFIED"
        assert hull["delivery_status"] == "AT_PLANT"
        resp = api.deliver_hull(hull["id"], make_production_planner_headers("planner-1"))
        validate_error(resp, ApiErrorId.ERR_HULL_NOT_CERTIFIED)
        after = get_hull(api, hull["id"])
        assert after["delivery_status"] == "AT_PLANT"
        assert after["certification_status"] == "UNCERTIFIED"

    def test_deliver_after_certification_succeeds(self, api):
        """PRD §3.6: "Four preconditions hold: the hull's `delivery_status` is
        still `AT_PLANT` (else `ERR_INVALID_HULL_STATE`); the hull is not under
        recall hold (`ERR_HULL_RECALL_HOLD`); the hull is `CERTIFIED` (an
        `UNCERTIFIED` hull draws `ERR_HULL_NOT_CERTIFIED`); and the dealer's
        floor plan has headroom — `floor_plan_utilized_cents` plus the order's
        `invoice_total_cents` must not exceed `floor_plan_limit_cents`, with
        landing exactly at the limit permitted and any excess refused as
        `ERR_FLOOR_PLAN_LIMIT_EXCEEDED`."
        PRD §3.6: "Fourth, the order transitions `IN_PRODUCTION` → `DELIVERED`
        with a version increment. Finally the hull's `delivery_status` becomes
        `DELIVERED` (a terminal state), `delivered_at` stamps from the clock,
        and the hull's `version` increments."

        Once the certification dimension reaches CERTIFIED, the delivery gate
        opens and both records advance.

        Design: Difficulty/cross_entity_state_dependency/hull_delivery_gated_on_hull_certification_state
        """
        world = setup_certified_hull(api, with_options=False)
        assert world["hull"]["certification_status"] == "CERTIFIED"
        hull = deliver_hull(api, world["hull"]["id"])
        assert_hull(hull)
        assert hull["delivery_status"] == "DELIVERED"
        assert hull["delivered_at"] is not None
        order = get_order(api, world["order"]["id"])
        assert order["status"] == "DELIVERED"

    def test_recall_hold_blocks_deliver(self, api):
        """PRD §3.6: "Four preconditions hold: the hull's `delivery_status` is
        still `AT_PLANT` (else `ERR_INVALID_HULL_STATE`); the hull is not under
        recall hold (`ERR_HULL_RECALL_HOLD`); the hull is `CERTIFIED` (an
        `UNCERTIFIED` hull draws `ERR_HULL_NOT_CERTIFIED`); and the dealer's
        floor plan has headroom — `floor_plan_utilized_cents` plus the order's
        `invoice_total_cents` must not exceed `floor_plan_limit_cents`, with
        landing exactly at the limit permitted and any excess refused as
        `ERR_FLOOR_PLAN_LIMIT_EXCEEDED`."
        PRD §3.9: "the hull itself flips `CERTIFIED` → `RECALL_HOLD` with a
        version increment — which blocks any pending delivery of that hull
        until remedy."

        Design: Corner/validations/hull_recall_hold_blocks_deliver
        """
        world = setup_certified_hull(api, with_options=False)
        setup_issued_campaign(api, world, serial_start=1, serial_end=5)
        assert get_hull(api, world["hull"]["id"])["certification_status"] == "RECALL_HOLD"
        resp = api.deliver_hull(
            world["hull"]["id"], make_production_planner_headers("planner-1")
        )
        validate_error(resp, ApiErrorId.ERR_HULL_RECALL_HOLD)

    def test_floor_plan_limit_exceeded_at_deliver(self, api):
        """PRD §3.6: "and the dealer's floor plan has headroom —
        `floor_plan_utilized_cents` plus the order's `invoice_total_cents` must
        not exceed `floor_plan_limit_cents`, with landing exactly at the limit
        permitted and any excess refused as `ERR_FLOOR_PLAN_LIMIT_EXCEEDED`."

        Invoice 3093605 against a 3000000-cent limit exceeds it.

        Design: Corner/validations/floor_plan_limit_exceeded_at_deliver
        """
        world = setup_certified_hull(api, option_set="tower_ballast",
                                     floor_plan_limit_cents=3000000)
        order = get_order(api, world["order"]["id"])
        assert order["invoice_total_cents"] == 3093605
        resp = api.deliver_hull(
            world["hull"]["id"], make_production_planner_headers("planner-1")
        )
        validate_error(resp, ApiErrorId.ERR_FLOOR_PLAN_LIMIT_EXCEEDED)


class TestDeliverCascade:
    def test_deliver_cascade_recomputes_utilization_and_tier_elevated(self, api):
        """PRD §3.6: "First, a `FloorPlanAdvance` opens: one advance per hull,
        its `dealer_id` copied from the delivered order, `principal_cents`
        equal to the order's invoice total, `status` `OPEN`, `opened_at` from
        the clock, `accrued_interest_cents` at 0, and `last_accrual_date`
        initialized to the opening date."
        PRD §3.6: "Second, the dealer's `floor_plan_utilized_cents` rises by the
        new principal and the dealer's `version` increments. Third, the dealer's
        `current_rate_tier` is re-derived from the new ratio."
        PRD §3.7: "a ratio of exactly 0.50 up to strictly below 0.80 locks
        `TIER_ELEVATED` at 0.075"

        Limit 6000000 with principal 3093605 lands the ratio at 0.516: the
        dealer's tier re-derives to TIER_ELEVATED as the cascade's third hop.

        Design: Difficulty/transitive_cascade/deliver_cascade_opens_advance_recomputes_utilization_and_tier
        """
        world = setup_certified_hull(api, option_set="tower_ballast",
                                     floor_plan_limit_cents=6000000)
        dealer_before = get_dealer(api, world["dealer"]["id"])
        assert dealer_before["current_rate_tier"] == "TIER_STANDARD"
        assert dealer_before["floor_plan_utilized_cents"] == 0
        set_clock(api, "2026-08-02T00:00:00Z")
        deliver_hull(api, world["hull"]["id"])
        dealer_after = get_dealer(api, world["dealer"]["id"])
        assert dealer_after["floor_plan_utilized_cents"] == 3093605, (
            "hop 2: utilization rises by the new principal"
        )
        assert dealer_after["current_rate_tier"] == "TIER_ELEVATED", (
            "hop 3: ratio 0.516 >= 0.50 re-derives TIER_ELEVATED"
        )
        advances = list_advances(api, hull_id=world["hull"]["id"])
        assert len(advances) == 1
        advance = advances[0]
        assert_floor_plan_advance(advance)
        assert advance["principal_cents"] == 3093605, "hop 1: principal = invoice"
        assert advance["rate_tier"] == "TIER_ELEVATED", (
            "tier locked from the post-inclusion utilization"
        )
        assert advance["annual_rate"] == pytest.approx(0.075)
        assert get_order(api, world["order"]["id"])["status"] == "DELIVERED"

    def test_deliver_cascade_low_ratio_stays_tier_standard(self, api):
        """PRD §3.7: "A ratio strictly below 0.50 locks `TIER_STANDARD` at an
        `annual_rate` of 0.06"
        PRD §3.6: "First, a `FloorPlanAdvance` opens: one advance per hull, its
        `dealer_id` copied from the delivered order, `principal_cents` equal to
        the order's invoice total, `status` `OPEN`, `opened_at` from the clock,
        `accrued_interest_cents` at 0, and `last_accrual_date` initialized to
        the opening date."

        Limit 100000000 keeps the ratio at 0.031: the cascade leaves both the
        advance and the dealer at TIER_STANDARD.

        Design: Difficulty/transitive_cascade/deliver_cascade_opens_advance_recomputes_utilization_and_tier
        """
        world = setup_delivered_hull(api, option_set="tower_ballast",
                                     floor_plan_limit_cents=100000000)
        advance = world["advance"]
        assert advance["rate_tier"] == "TIER_STANDARD"
        assert advance["annual_rate"] == pytest.approx(0.06)
        assert advance["principal_cents"] == 3093605
        assert advance["accrued_interest_cents"] == 0
        dealer = get_dealer(api, world["dealer"]["id"])
        assert dealer["floor_plan_utilized_cents"] == 3093605
        assert dealer["current_rate_tier"] == "TIER_STANDARD"
        hull = get_hull(api, world["hull"]["id"])
        assert hull["delivery_status"] == "DELIVERED"
        assert hull["delivered_at"] is not None


class TestTierLockEvaluationOrder:
    """The tier is locked from utilization that INCLUDES the new advance —
    the pinned evaluation order that breaks the circular dependency."""

    def test_tier_locks_from_post_inclusion_utilization(self, api):
        """PRD §3.7: "The utilization ratio is computed as the dealer's
        `floor_plan_utilized_cents` before the delivery plus the new
        `principal_cents`, all divided by `floor_plan_limit_cents`. A ratio
        strictly below 0.50 locks `TIER_STANDARD` at an `annual_rate` of 0.06;
        a ratio of exactly 0.50 up to strictly below 0.80 locks `TIER_ELEVATED`
        at 0.075; a ratio of exactly 0.80 or above locks `TIER_HIGH` at 0.095."

        Identical 3093605-cent deliveries: limit 100000000 -> 0.031 ->
        TIER_STANDARD (0.06); limit 6000000 -> 0.516 -> TIER_ELEVATED (0.075).

        Design: Difficulty/combinatorial_formula/floor_plan_tier_circular_dependency_evaluation_order
        """
        world = setup_bookable_world(api, with_options=True)
        model, tower, ballast, slot = (
            world["model"], world["tower"], world["ballast"], world["slot"],
        )
        da = create_dealer(api, dealer_code="D-A", floor_plan_limit_cents=100000000)
        db = create_dealer(api, dealer_code="D-B", floor_plan_limit_cents=6000000)
        hulls = {}
        for dealer in (da, db):
            order = book_order_tower_ballast(
                api, dealer, model, tower, ballast, slot_id=slot["id"]
            )
            order = confirm_order(api, order, dealer)
            hull = create_hull(api, order["id"])
            certify_hull(api, hull["id"])
            hulls[dealer["id"]] = hull["id"]
        set_clock(api, "2026-08-02T00:00:00Z")
        for dealer in (da, db):
            deliver_hull(api, hulls[dealer["id"]])
        adv_a = list_advances(api, dealer_id=da["id"])[0]
        adv_b = list_advances(api, dealer_id=db["id"])[0]
        assert adv_a["rate_tier"] == "TIER_STANDARD"
        assert adv_a["annual_rate"] == pytest.approx(0.06)
        assert adv_b["rate_tier"] == "TIER_ELEVATED", (
            "0.516 >= 0.50 boundary locks TIER_ELEVATED"
        )
        assert adv_b["annual_rate"] == pytest.approx(0.075)
        assert adv_a["principal_cents"] == adv_b["principal_cents"] == 3093605

    def test_tier_lock_high_band(self, api):
        """PRD §3.7: "a ratio of exactly 0.80 or above locks `TIER_HIGH` at
        0.095."

        Limit 3800000 puts 3093605 at a 0.814 ratio: TIER_HIGH.

        Design: Difficulty/combinatorial_formula/floor_plan_tier_circular_dependency_evaluation_order
        """
        world = setup_delivered_hull(api, option_set="tower_ballast",
                                     floor_plan_limit_cents=3800000)
        advance = world["advance"]
        assert advance["rate_tier"] == "TIER_HIGH"
        assert advance["annual_rate"] == pytest.approx(0.095)
        dealer = get_dealer(api, world["dealer"]["id"])
        assert dealer["current_rate_tier"] == "TIER_HIGH"


class TestCurtailment:
    def test_zero_day_interest_same_day_curtail(self, api):
        """PRD §3.7: "The interest owed on an advance is its
        `outstanding_principal_cents` times its locked `annual_rate` times the
        number of whole days from `last_accrual_date` to the clock date (zero
        when they coincide), divided by a 365-day year and rounded half up"
        PRD §3.7: "a payment that zeroes the outstanding principal transitions
        the advance `OPEN` → `PAID`, its terminal state."

        Same-day payoff: days == 0, interest == 0, a principal-only payment
        pays the advance off.

        Design: Corner/calculations/floor_plan_interest_zero_days_same_day_curtail
        """
        world = setup_delivered_hull(api, with_options=False)
        assert world["advance"]["principal_cents"] == 2575000
        curtail(api, world["dealer"]["id"], 2575000)
        advance = list_advances(api, hull_id=world["hull"]["id"])[0]
        assert advance["status"] == "PAID"
        assert advance["outstanding_principal_cents"] == 0
        assert advance["accrued_interest_cents"] == 0

    def test_curtailment_exceeds_balance_rejected(self, api):
        """PRD §3.7: "The amount may not exceed the total due across the
        dealer's `OPEN` advances, where the total due is interest accrued to
        the clock date plus outstanding principal; an over-payment is rejected
        with `ERR_CURTAILMENT_EXCEEDS_BALANCE`, while an exact full payoff is
        expressly allowed."

        Same-day total due is exactly the 2575000 principal; one cent over
        rejects.

        Design: Corner/validations/curtailment_exceeds_balance_rejected
        """
        world = setup_delivered_hull(api, with_options=False)
        dealer = get_dealer(api, world["dealer"]["id"])
        resp = api.post_curtailment(
            world["dealer"]["id"],
            create_curtailment_payload(dealer["version"], 2575001),
            make_dealer_principal_headers(world["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CURTAILMENT_EXCEEDS_BALANCE)

    def test_curtail_stale_dealer_version_returns_412(self, api):
        """PRD §2.7: "Posting a curtailment (`POST /dealers/{id}/curtailments`)
        likewise requires `expected_dealer_version`; a stale value is rejected
        with `ERR_STALE_DEALER_VERSION` (HTTP 412), forcing a re-read before
        the payment waterfall is applied against balances the client never
        observed."

        Design: Corner/validations/occ_stale_dealer_version_on_curtailment_returns_412
        """
        world = setup_delivered_hull(api, with_options=False)
        dealer = get_dealer(api, world["dealer"]["id"])
        resp = api.post_curtailment(
            world["dealer"]["id"],
            create_curtailment_payload(dealer["version"] - 1, 100),
            make_dealer_principal_headers(world["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_DEALER_VERSION)


class TestUtilizationConservation:
    def test_full_payoff_restores_zero_utilization(self, api):
        """PRD §2.8: "a dealer's `floor_plan_utilized_cents` is the sum of
        `outstanding_principal_cents` over that dealer's `OPEN` advances,
        re-established on every advance opening and curtailment"
        PRD §3.7: "The dealer's `floor_plan_utilized_cents` falls by the total
        principal repaid, `current_rate_tier` is recomputed from the lower
        ratio, and the dealer's `version` increments."

        Deliver (utilized 2575000), advance the clock ten days, then pay
        principal plus accrued interest (2575000 + rhu(2575000*0.06*10/365) =
        2579233): utilization returns to 0 and the advance is PAID.

        Design: Difficulty/compensating_invariant/dealer_floor_plan_utilization_conservation_across_deliver_and_curtail
        """
        world = setup_certified_hull(api, with_options=False)
        set_clock(api, "2026-08-02T00:00:00Z")
        deliver_hull(api, world["hull"]["id"])
        dealer = get_dealer(api, world["dealer"]["id"])
        assert dealer["floor_plan_utilized_cents"] == 2575000
        set_clock(api, "2026-08-12T00:00:00Z")  # ten whole days of interest
        curtail(api, world["dealer"]["id"], 2579233)
        dealer_after = get_dealer(api, world["dealer"]["id"])
        assert dealer_after["floor_plan_utilized_cents"] == 0, (
            "full payoff must restore the initial utilization (conservation)"
        )
        advance = list_advances(api, hull_id=world["hull"]["id"])[0]
        assert advance["status"] == "PAID"
        assert advance["outstanding_principal_cents"] == 0

    def test_partial_curtailment_keeps_advance_open(self, api):
        """PRD §3.7: "A partial payoff leaves the advance `OPEN`; a payment
        that zeroes the outstanding principal transitions the advance `OPEN` →
        `PAID`, its terminal state. The dealer's `floor_plan_utilized_cents`
        falls by the total principal repaid"

        Same-day partial payment of 1000000: no interest has accrued, so the
        whole payment reduces principal to 1575000 and utilization follows.

        Design: Difficulty/compensating_invariant/dealer_floor_plan_utilization_conservation_across_deliver_and_curtail
        """
        world = setup_delivered_hull(api, with_options=False)
        assert world["advance"]["principal_cents"] == 2575000
        curtail(api, world["dealer"]["id"], 1000000)
        advance = list_advances(api, hull_id=world["hull"]["id"])[0]
        assert advance["status"] == "OPEN", "partial payoff leaves the advance OPEN"
        assert advance["outstanding_principal_cents"] == 1575000
        dealer = get_dealer(api, world["dealer"]["id"])
        assert dealer["floor_plan_utilized_cents"] == 1575000


class TestAdvanceListFilter:
    def test_advances_list_filter_by_dealer(self, api):
        """PRD §3.6: "Hulls can be listed with `order_id`, `slot_id`, or
        `model_id` filters; advances with `dealer_id`, `hull_id`, or `status`
        filters."

        Design: Corner/endpoints/floor_plan_advances_list_filter_by_dealer
        """
        world = setup_bookable_world(api, with_options=False)
        da = world["dealer"]
        db = create_dealer(api, dealer_code="D-B")
        hulls = {}
        for dealer in (da, db):
            order = book_order_no_options(
                api, dealer, world["model"], slot_id=world["slot"]["id"]
            )
            order = confirm_order(api, order, dealer)
            hull = create_hull(api, order["id"])
            certify_hull(api, hull["id"])
            hulls[dealer["id"]] = hull["id"]
        set_clock(api, "2026-08-02T00:00:00Z")
        for dealer in (da, db):
            deliver_hull(api, hulls[dealer["id"]])
        data, meta = validate_paginated(
            api.list_floor_plan_advances(ANY, params={"dealer_id": da["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["dealer_id"] == da["id"]
        assert data[0]["hull_id"] == hulls[da["id"]]
