"""Three different kinds of threshold, each probed one unit either side.

A money equality on the Medicaid residue rule, an integer sample-size guard on
courier suspension, and the cardinality of the selector's candidate set at zero.
"""

import pytest

from test_helpers import (
    CLOCK_DOORSTEP_DAY3,
    CLOCK_PICKUP_DAY3,
    OPS_HEADERS,
    advance_to_assigned,
    advance_to_out_for_delivery,
    advance_to_picked_up,
    active_allocation,
    assert_courier_counters,
    assert_instant,
    assert_payer_mix,
    assert_reliability_scores,
    build_courier,
    build_health_plan,
    build_network,
    build_plan_grant,
    build_queued_delivery,
    build_ready_order,
    build_window,
    build_zone,
    factories,
    force_cold_breach,
    make_plan_admin_headers,
    read_courier,
    read_delivery,
    read_grant,
    read_order,
    read_window,
    record_attempt,
    redepart,
    reserve_delivery,
    set_clock,
    utc_ts,
    validate_error,
    validate_paginated,
    validate_success,
)

MEDICAID_SHARE = {"payer_type": "MEDICAID", "member_cost_share_pct": 0.2}
SINGLE_LINE_ORDER = {
    "rx_line_count": 1,
    "cold_chain_required": False,
    "controlled_schedule": "NONE",
    "total_rx_value_cents": 1000,
}
COLD_CII_ORDER = {
    "rx_line_count": 2,
    "cold_chain_required": True,
    "controlled_schedule": "CII",
    "total_rx_value_cents": 31000,
}
MEDICAID_GROSS_SHARE_CENTS = 313


@pytest.fixture
def medicaid_pools_one_cent_apart(api):
    """Three identical Medicaid plans funded to 314, 313 and 312 cents.

    The member's share on the standard Z1 schedule is exactly 313 cents and each
    pool's per-delivery cap is 400, so only the budget moves across the three
    rows. All three orders point at one window of capacity 3.
    """
    net = build_network(
        api,
        plan=dict(MEDICAID_SHARE, name="State Care Over"),
        grant={"grant_budget_cents": 314, "per_delivery_cap_cents": 400},
    )
    exact_plan = build_health_plan(api, name="State Care Exact", **MEDICAID_SHARE)
    exact_grant = build_plan_grant(
        api, exact_plan["id"], grant_budget_cents=313, per_delivery_cap_cents=400
    )
    under_plan = build_health_plan(api, name="State Care Under", **MEDICAID_SHARE)
    under_grant = build_plan_grant(
        api, under_plan["id"], grant_budget_cents=312, per_delivery_cap_cents=400
    )

    orders = {
        "over": build_ready_order(api, net, **SINGLE_LINE_ORDER),
        "exact": build_ready_order(
            api, net, health_plan_id=exact_plan["id"], **SINGLE_LINE_ORDER
        ),
        "under": build_ready_order(
            api, net, health_plan_id=under_plan["id"], **SINGLE_LINE_ORDER
        ),
    }
    window = build_window(api, net.zone["id"], capacity_slots=3)
    pools = {
        "over": (net.plan, net.grant),
        "exact": (exact_plan, exact_grant),
        "under": (under_plan, under_grant),
    }
    return net, pools, orders, window


class TestMedicaidCoverageEquality:
    """"Second — and only for a `MEDICAID` payer — if that eligible amount is
    less than the gross share, the request is rejected outright with
    `ERR_GRANT_COVERAGE_INSUFFICIENT`"
    """

    def test_pool_above_the_share_funds_the_whole_member_liability(
        self, api, medicaid_pools_one_cent_apart
    ):
        """One cent of headroom: the share is fully funded and nothing remains.

        "First, the grant-eligible amount is the smallest of three quantities:
        the member's gross share, the selected pool's `per_delivery_cap_cents`,
        and the pool's `remaining_cents`."

        Design: Difficulty/boundary_precision_check/medicaid_grant_coverage_exact_equality_admits_delivery
        """
        net, _pools, orders, window = medicaid_pools_one_cent_apart
        delivery = reserve_delivery(api, net, orders["over"]["id"], window["id"])

        allocation = active_allocation(api, delivery["id"])
        assert_payer_mix(
            allocation,
            patient_gross_share_cents=MEDICAID_GROSS_SHARE_CENTS,
            plan_grant_cents=313,
            patient_payable_cents=0,
            pharmacy_payable_cents=1253,
        )

    def test_pool_exactly_equal_to_the_share_still_admits_the_reservation(
        self, api, medicaid_pools_one_cent_apart
    ):
        """Equality is not a shortfall, and it drains the pool exactly.

        "Second — and only for a `MEDICAID` payer — if that eligible amount is
        less than the gross share, the request is rejected outright with
        `ERR_GRANT_COVERAGE_INSUFFICIENT`: a Medicaid member may not be billed
        any residue, so a pool that can only partly fund the share cannot be used
        at all."

        Design: Difficulty/boundary_precision_check/medicaid_grant_coverage_exact_equality_admits_delivery
        """
        net, pools, orders, window = medicaid_pools_one_cent_apart
        reserve_delivery(api, net, orders["over"]["id"], window["id"])
        delivery = reserve_delivery(api, net, orders["exact"]["id"], window["id"])

        allocation = active_allocation(api, delivery["id"])
        assert allocation["plan_grant_cents"] == 313
        assert allocation["patient_payable_cents"] == 0

        exact_plan, exact_grant = pools["exact"]
        grant = read_grant(
            api, exact_grant["id"], headers=make_plan_admin_headers(exact_plan["id"])
        )
        assert grant["remaining_cents"] == 0
        assert grant["status"] == "EXHAUSTED"

    def test_pool_one_cent_short_of_the_share_cannot_be_used_at_all(
        self, api, medicaid_pools_one_cent_apart
    ):
        """A partly funded Medicaid share is refused rather than split.

        "a Medicaid member may not be billed any residue, so a pool that can only
        partly fund the share cannot be used at all."

        Design: Difficulty/boundary_precision_check/medicaid_grant_coverage_exact_equality_admits_delivery
        """
        net, pools, orders, window = medicaid_pools_one_cent_apart
        reserve_delivery(api, net, orders["over"]["id"], window["id"])
        reserve_delivery(api, net, orders["exact"]["id"], window["id"])

        response = api.create_delivery(
            factories.delivery_payload(
                orders["under"]["id"],
                window["id"],
                read_window(api, window["id"])["version"],
            ),
            headers=net.pharmacy_headers,
        )
        validate_error(response, "ERR_GRANT_COVERAGE_INSUFFICIENT", 409)

        under_plan, under_grant = pools["under"]
        assert read_grant(
            api, under_grant["id"], headers=make_plan_admin_headers(under_plan["id"])
        )["committed_cents"] == 0
        assert read_window(api, window["id"])["reserved_slots"] == 2
        assert read_order(api, orders["under"]["id"])["status"] == "READY"


@pytest.fixture
def courier_two_failures_into_a_disastrous_career(api):
    """A courier with a no-answer and a cold breach behind it, on a fresh bag.

    The cold controlled bag departs at 14:00Z after a 13:50Z pickup, so the
    second run at 16:00Z is 130 minutes out of the cooler and scores nothing. A
    next-day standard bag is then handed to the same courier and left standing at
    the door so the third run is the trigger.
    """
    first = build_queued_delivery(
        api,
        order_kwargs=COLD_CII_ORDER,
        window_kwargs={"window_end": utc_ts(3, 18), "capacity_slots": 1},
    )
    advance_to_assigned(api, first)
    set_clock(api, CLOCK_PICKUP_DAY3)
    advance_to_picked_up(api, first)
    advance_to_out_for_delivery(api, first, depart_clock=CLOCK_DOORSTEP_DAY3)
    record_attempt(api, first, "NO_ANSWER", id_verification_method="NONE")
    redepart(api, first, utc_ts(3, 15, 55))
    force_cold_breach(
        api,
        first,
        breach_clock=utc_ts(3, 16),
        recipient_relationship="SELF",
        pod_photo_ref="pod/4471-b.jpg",
    )

    courier_after_two_runs = read_courier(api, first.courier["id"])

    net = first.net
    next_day_order = build_ready_order(api, net, **SINGLE_LINE_ORDER)
    next_day_window = build_window(
        api,
        net.zone["id"],
        window_start=utc_ts(4, 14),
        window_end=utc_ts(4, 16),
        capacity_slots=1,
    )
    second = build_queued_delivery(
        api, net=net, order=next_day_order, window=next_day_window
    )
    advance_to_assigned(
        api, second, courier=first.courier, dispatch_clock=utc_ts(4, 13, 50)
    )
    advance_to_picked_up(api, second)
    advance_to_out_for_delivery(api, second, depart_clock=utc_ts(4, 14))
    return second, courier_after_two_runs


class TestSuspensionSampleSizeGuard:
    """"The minimum-attempts gate matters: a courier two attempts into a
    disastrous career is not suspended even at a lifetime score of 0.00."
    """

    def test_two_attempts_at_a_zero_lifetime_score_do_not_suspend(
        self, api, courier_two_failures_into_a_disastrous_career
    ):
        """Below the gate the score is irrelevant, however bad it is.

        "The minimum-attempts gate matters: a courier two attempts into a
        disastrous career is not suspended even at a lifetime score of 0.00."

        Design: Difficulty/boundary_precision_check/courier_suspension_requires_min_attempt_count_not_score
        """
        _scn, courier = courier_two_failures_into_a_disastrous_career
        assert_courier_counters(
            courier, attempt_total_count=2, delivered_count=0, status="AVAILABLE"
        )
        assert_reliability_scores(courier, rolling=22.22, lifetime=0.00)

    def test_the_third_recorded_attempt_reaches_the_gate_and_suspends(
        self, api, courier_two_failures_into_a_disastrous_career
    ):
        """Only the count moved between the two rows, and now it suspends.

        "After every recorded attempt, if the courier's `attempt_total_count` has
        reached 3 or more **and** its `lifetime_reliability_score` is strictly
        below 60.00 **and** its `status` is `OFFLINE`, `AVAILABLE`, or
        `ON_ROUTE`, the courier is moved to `SUSPENDED`."

        Design: Difficulty/boundary_precision_check/courier_suspension_requires_min_attempt_count_not_score
        """
        scn, _before = courier_two_failures_into_a_disastrous_career
        record_attempt(api, scn, "NO_ANSWER")

        courier = read_courier(api, scn.courier["id"])
        assert_courier_counters(
            courier, attempt_total_count=3, delivered_count=0, status="SUSPENDED"
        )
        assert courier["lifetime_reliability_score"] == pytest.approx(0.00, abs=0.01)

    def test_the_suspending_attempt_is_still_accepted_and_recorded(
        self, api, courier_two_failures_into_a_disastrous_career
    ):
        """The suspension rides along with the write rather than blocking it.

        "Suspension from `AVAILABLE` removes the courier from the selector
        candidate set for all future dispatches; suspension from `ON_ROUTE`
        deliberately leaves any in-flight `ACCEPTED` assignment untouched, so a
        bag is never abandoned mid-route."

        Design: Difficulty/boundary_precision_check/courier_suspension_requires_min_attempt_count_not_score
        """
        scn, _before = courier_two_failures_into_a_disastrous_career
        third = record_attempt(api, scn, "NO_ANSWER")
        assert third["outcome"] == "NO_ANSWER"
        assert third["attempt_no"] == 1

        delivery = read_delivery(api, scn.delivery["id"])
        assert delivery["custody_status"] == "ATTEMPT_FAILED"
        assert delivery["attempt_count"] == 1


@pytest.fixture
def two_couriers_neither_of_them_eligible(api):
    """A queued Z1 scheduled bag, and a pool that filters down to nothing.

    Ola Beck serves the right zone in the right mode but never came on shift;
    Pia Chen is on shift but is on-demand and serves a zone this window is not in.
    """
    scn = build_queued_delivery(api, order_kwargs=SINGLE_LINE_ORDER)
    off_shift = build_courier(api, available=False, display_name="Ola Beck")
    # A courier's served_zone_codes are body foreign keys, so the far-away zone
    # has to exist as a row before anyone can be onboarded against it.
    build_zone(api, zone_code="Z9")
    far_away = build_courier(
        api, display_name="Pia Chen", mode="ON_DEMAND", served_zone_codes=["Z9"]
    )
    set_clock(api, utc_ts(3, 13, 45))
    return scn, off_shift, far_away


class TestEmptyCandidatePoolFallback:
    """"When the candidate pool is empty, no assignment is created, nothing at
    all is mutated, the delivery stays `QUEUED`, and the request fails with
    `ERR_NO_ELIGIBLE_COURIER`."
    """

    def test_a_pool_that_filters_to_zero_reports_no_eligible_courier(
        self, api, two_couriers_neither_of_them_eligible
    ):
        """Neither the off-shift courier nor the out-of-zone one is a candidate.

        "A courier is a candidate only when every one of the following holds: its
        `status` is `AVAILABLE` or `ON_ROUTE`; its `mode` equals the window's
        `courier_mode`; the window zone's `zone_code` appears in its
        `served_zone_codes`"

        Design: Difficulty/boundary_precision_check/empty_eligible_courier_pool_falls_back_to_no_eligible_courier
        """
        scn, _off_shift, _far_away = two_couriers_neither_of_them_eligible
        response = api.dispatch_delivery(
            scn.delivery["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload()
        )
        validate_error(response, "ERR_NO_ELIGIBLE_COURIER", 409)

    def test_the_empty_pool_dispatch_mutated_nothing_at_all(
        self, api, two_couriers_neither_of_them_eligible
    ):
        """The declared fallback is inert as well as loud.

        "When the candidate pool is empty, no assignment is created, nothing at
        all is mutated, the delivery stays `QUEUED`, and the request fails with
        `ERR_NO_ELIGIBLE_COURIER`."

        Design: Difficulty/boundary_precision_check/empty_eligible_courier_pool_falls_back_to_no_eligible_courier
        """
        scn, off_shift, far_away = two_couriers_neither_of_them_eligible
        validate_error(
            api.dispatch_delivery(
                scn.delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(),
            ),
            "ERR_NO_ELIGIBLE_COURIER",
            409,
        )

        delivery = read_delivery(api, scn.delivery["id"])
        assert delivery["custody_status"] == "QUEUED"
        assert delivery["courier_id"] is None
        _rows, meta = validate_paginated(
            api.list_courier_assignments(OPS_HEADERS, delivery_id=scn.delivery["id"])
        )
        assert meta["total_count"] == 0
        assert read_courier(api, off_shift["id"])["status"] == "OFFLINE"
        assert read_courier(api, far_away["id"])["status"] == "AVAILABLE"

    def test_one_eligible_courier_is_enough_to_produce_an_offer(
        self, api, two_couriers_neither_of_them_eligible
    ):
        """A single candidate is offered the job on the same delivery.

        "Either path writes a `CourierAssignment` carrying `delivery_id`, the
        `courier_id` it was routed to, a `mode` copied from the courier at offer
        time, `status` `OFFERED`, `offered_at` stamped from the clock, an
        `offer_expires_at` ten minutes later"

        Design: Difficulty/boundary_precision_check/empty_eligible_courier_pool_falls_back_to_no_eligible_courier
        """
        scn, _off_shift, _far_away = two_couriers_neither_of_them_eligible
        validate_error(
            api.dispatch_delivery(
                scn.delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(),
            ),
            "ERR_NO_ELIGIBLE_COURIER",
            409,
        )

        candidate = build_courier(api)
        assignment = validate_success(
            api.dispatch_delivery(
                scn.delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(),
            ),
            201,
        )
        assert assignment["courier_id"] == candidate["id"]
        assert assignment["status"] == "OFFERED"
        assert assignment["mode"] == "SCHEDULED"
        assert_instant(assignment["offered_at"], utc_ts(3, 13, 45))
        assert_instant(assignment["offer_expires_at"], utc_ts(3, 13, 55))

        assert read_delivery(api, scn.delivery["id"])["custody_status"] == "QUEUED"
        _rows, meta = validate_paginated(
            api.list_courier_assignments(OPS_HEADERS, delivery_id=scn.delivery["id"])
        )
        assert meta["total_count"] == 1
