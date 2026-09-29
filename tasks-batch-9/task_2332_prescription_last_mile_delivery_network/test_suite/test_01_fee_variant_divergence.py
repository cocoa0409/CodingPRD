"""The two dual-variant computations: the bill and the courier's reliability.

Both variants are recomputed from the same underlying history, and both are
expected to disagree with each other. On the money side the disagreement is the
cold-pack re-ice and the re-attempt surcharge; on the courier side it is
recency weighting and partial credit.
"""

import pytest

from test_helpers import (
    CLOCK_DOORSTEP_DAY3,
    CLOCK_PICKUP_DAY3,
    OPS_HEADERS,
    Z1_COLD_CONTROLLED_LINES,
    Z1_COLD_CONTROLLED_SUBTOTAL_CENTS,
    advance_to_assigned,
    advance_to_out_for_delivery,
    advance_to_picked_up,
    allocations_for,
    assert_courier_counters,
    assert_delivery_state,
    assert_fee_lines,
    assert_payer_mix,
    assert_reliability_scores,
    attempts_for,
    build_queued_delivery,
    build_ready_order,
    build_window,
    deliver,
    read_courier,
    read_grant,
    read_order,
    record_attempt,
    redepart,
    reserve_delivery,
    set_clock,
    settle,
    utc_ts,
    validate_paginated,
)

COLD_CII_ORDER = {
    "rx_line_count": 2,
    "cold_chain_required": True,
    "controlled_schedule": "CII",
    "total_rx_value_cents": 31000,
}
STANDARD_ORDER = {
    "rx_line_count": 2,
    "cold_chain_required": False,
    "controlled_schedule": "NONE",
    "total_rx_value_cents": 1000,
}

# The FINAL bill for the same cold controlled bag once two runs are charged:
# the re-ice doubles and one surcharge unit appears.
Z1_COLD_CONTROLLED_FINAL_LINES = [705, 861, 910, 605, 0, 400]
Z1_COLD_CONTROLLED_FINAL_SUBTOTAL_CENTS = 3481


@pytest.fixture
def settled_after_reattempt(api):
    """A cold controlled bag delivered on its second run, then settled.

    The first run is a NO_ANSWER at 14:00Z; the cooldown boundary at 15:00Z
    admits the second departure, and the second run lands the bag.
    """
    scn = build_queued_delivery(
        api,
        order_kwargs=COLD_CII_ORDER,
        window_kwargs={"capacity_slots": 2},
    )
    advance_to_assigned(api, scn)
    set_clock(api, CLOCK_PICKUP_DAY3)
    advance_to_picked_up(api, scn)
    advance_to_out_for_delivery(api, scn, depart_clock=CLOCK_DOORSTEP_DAY3)
    record_attempt(api, scn, "NO_ANSWER")
    redepart(api, scn, utc_ts(3, 15))
    deliver(api, scn, pod_photo_ref="POD-4471")
    settle(api, scn)
    return scn


class TestFeeVariantDivergence:
    """"A provisional bill therefore always shows exactly one cold-pack re-ice
    and no re-attempt surcharge; the delta between the two variants is entirely
    attributable to those two lines."
    """

    def test_provisional_variant_prices_exactly_one_run_and_is_superseded(
        self, api, settled_after_reattempt
    ):
        """The provisional bill priced one run and is kept as readable history.

        "Let *billable attempts* mean the number of door-step runs the bill is
        charging for; on a provisional bill it is pinned to 1, since no run has
        happened yet."

        "The `PROVISIONAL` allocation is set to `SUPERSEDED` and its
        `plan_grant_cents` is released from the pool's `committed_cents`."

        Design: Difficulty/dual_variant_calc/delivery_fee_provisional_vs_final_diverges_after_reattempt
        """
        scn = settled_after_reattempt
        provisional = allocations_for(api, scn.delivery["id"], variant="PROVISIONAL")
        assert len(provisional) == 1
        allocation = provisional[0]
        assert allocation["status"] == "SUPERSEDED"

        assert_fee_lines(allocation, Z1_COLD_CONTROLLED_LINES)
        assert allocation["fee_subtotal_cents"] == Z1_COLD_CONTROLLED_SUBTOTAL_CENTS
        assert_payer_mix(
            allocation,
            patient_gross_share_cents=264,
            plan_grant_cents=150,
            pharmacy_absorption_cents=50,
            patient_payable_cents=64,
            pharmacy_payable_cents=2412,
        )

    def test_final_variant_reprices_both_moving_lines_after_the_second_run(
        self, api, settled_after_reattempt
    ):
        """Two runs double the re-ice line and add one surcharge unit.

        "`cold_pack_line_cents` becomes the zone's `cold_pack_fee_cents`
        multiplied by that count, because each run consumed a fresh re-ice; and
        `reattempt_line_cents` stops being zero, charging 400 cents for each run
        beyond the first, capped at two such units."

        Design: Difficulty/dual_variant_calc/delivery_fee_provisional_vs_final_diverges_after_reattempt
        """
        scn = settled_after_reattempt
        final = allocations_for(api, scn.delivery["id"], variant="FINAL")
        assert len(final) == 1
        allocation = final[0]
        assert allocation["status"] == "ACTIVE"

        assert_fee_lines(allocation, Z1_COLD_CONTROLLED_FINAL_LINES)
        assert allocation["fee_subtotal_cents"] == Z1_COLD_CONTROLLED_FINAL_SUBTOTAL_CENTS
        assert_payer_mix(
            allocation,
            patient_gross_share_cents=349,
            plan_grant_cents=150,
            pharmacy_absorption_cents=50,
            patient_payable_cents=149,
            pharmacy_payable_cents=3182,
        )
        assert (
            allocation["fee_subtotal_cents"] - Z1_COLD_CONTROLLED_SUBTOTAL_CENTS == 855
        )

    def test_settled_delivery_mirrors_the_final_bill_and_moves_the_pool_to_consumed(
        self, api, settled_after_reattempt
    ):
        """The row, the pool and the order all follow the final variant.

        "The new allocation's `plan_grant_cents` is added to the pool's
        `consumed_cents` and the pool's `remaining_cents` and `status` are
        recomputed"

        Design: Difficulty/dual_variant_calc/delivery_fee_provisional_vs_final_diverges_after_reattempt
        """
        scn = settled_after_reattempt
        assert scn.delivery["fee_subtotal_cents"] == Z1_COLD_CONTROLLED_FINAL_SUBTOTAL_CENTS
        assert_delivery_state(scn.delivery, "DELIVERED", "FINALIZED")

        grant = read_grant(api, scn.net.grant["id"])
        assert grant["committed_cents"] == 0
        assert grant["consumed_cents"] == 150
        assert grant["remaining_cents"] == 99850

        assert read_order(api, scn.order["id"])["status"] == "CLOSED"


@pytest.fixture
def two_runs_recorded_and_third_bag_at_the_door(api):
    """One courier, two bags, two runs recorded: NO_ANSWER then DELIVERED.

    The second bag sits on a later window so the courier's buffered committed
    interval does not collide with the first, and it is left standing at the
    door so each test can record the third run itself.
    """
    scn = build_queued_delivery(
        api,
        order_kwargs=STANDARD_ORDER,
        window_kwargs={"capacity_slots": 2},
    )
    net = scn.net
    second_order = build_ready_order(api, net, rx_line_count=1, total_rx_value_cents=900)
    second_window = build_window(
        api,
        net.zone["id"],
        window_start=utc_ts(3, 17),
        window_end=utc_ts(3, 19),
        capacity_slots=2,
    )
    second_delivery = reserve_delivery(api, net, second_order["id"], second_window["id"])

    advance_to_assigned(api, scn)
    advance_to_picked_up(api, scn)
    advance_to_out_for_delivery(api, scn, depart_clock=CLOCK_DOORSTEP_DAY3)
    record_attempt(api, scn, "NO_ANSWER")
    redepart(api, scn, utc_ts(3, 15))
    deliver(api, scn, id_verification_method="DOB_MATCH", signature_captured=False)

    scn.window = second_window
    scn.order = second_order
    scn.delivery = second_delivery
    advance_to_assigned(api, scn, courier=scn.courier, dispatch_clock=utc_ts(3, 16, 50))
    advance_to_picked_up(api, scn)
    advance_to_out_for_delivery(api, scn, depart_clock=utc_ts(3, 17, 5))
    return scn


class TestReliabilityVariantDivergence:
    """"Two scores are computed from the same attempt history and they
    deliberately disagree, because they answer different questions."
    """

    def test_rolling_weighted_score_diverges_from_the_binary_lifetime_rate(
        self, api, two_runs_recorded_and_third_bag_at_the_door
    ):
        """One history, two answers: 86.89 recency-weighted versus 66.67 binary.

        "Give the attempt at index *i* a weight of 0.8 raised to the power *i*,
        so the newest attempt weighs 1, the one before it 0.8, and the one
        before that 0.64."

        "`lifetime_reliability_score` is the unweighted, binary completion rate
        over the courier's whole history: 100 multiplied by `delivered_count`,
        divided by `attempt_total_count`, rounded half up to two decimals"

        Design: Difficulty/dual_variant_calc/courier_rolling_vs_lifetime_reliability_diverges
        """
        scn = two_runs_recorded_and_third_bag_at_the_door
        deliver(api, scn, id_verification_method="DOB_MATCH", signature_captured=False)

        courier = read_courier(api, scn.courier["id"])
        assert_courier_counters(courier, attempt_total_count=3, delivered_count=2)
        assert_reliability_scores(courier, rolling=86.89, lifetime=66.67)
        assert courier["rolling_reliability_score"] != courier["lifetime_reliability_score"]

    def test_third_run_is_the_first_on_its_own_bag_and_frees_the_courier(
        self, api, two_runs_recorded_and_third_bag_at_the_door
    ):
        """The credit is per-run, the ordinal is per-delivery.

        "A recorded `DELIVERED` outcome carries a `reliability_credit` of 1.0
        and cascades widely: the delivery advances `OUT_FOR_DELIVERY →
        DELIVERED`, its `attempt_count` rises by one, `last_attempt_at` and
        `delivered_at` are both stamped from the clock; the courier's `ACCEPTED`
        assignment moves `ACCEPTED → COMPLETED`; the courier's
        `active_delivery_count` drops by one and the courier returns `ON_ROUTE →
        AVAILABLE` once it reaches 0"

        Design: Difficulty/dual_variant_calc/courier_rolling_vs_lifetime_reliability_diverges
        """
        scn = two_runs_recorded_and_third_bag_at_the_door
        third = deliver(
            api, scn, id_verification_method="DOB_MATCH", signature_captured=False
        )
        assert third["reliability_credit"] == pytest.approx(1.0, abs=0.01)
        assert third["attempt_no"] == 1

        courier = read_courier(api, scn.courier["id"])
        assert_courier_counters(courier, active_delivery_count=0, status="AVAILABLE")

        rows, meta = validate_paginated(
            api.list_delivery_attempts(OPS_HEADERS, courier_id=scn.courier["id"])
        )
        assert meta["total_count"] == 3
        assert len(rows) == 3

    def test_every_recorded_run_stays_readable_as_the_input_of_both_variants(
        self, api, two_runs_recorded_and_third_bag_at_the_door
    ):
        """The runs behind the two scores are readable, one per bag history.

        "Individual door-step attempt records are readable by the courier who
        made them, the pharmacy behind the bag, and ops; they are the raw input
        of both reliability variants and are never modified after they are
        written."

        Design: Difficulty/dual_variant_calc/courier_rolling_vs_lifetime_reliability_diverges
        """
        scn = two_runs_recorded_and_third_bag_at_the_door
        deliver(api, scn, id_verification_method="DOB_MATCH", signature_captured=False)

        second_bag_runs = attempts_for(api, scn.delivery["id"])
        assert len(second_bag_runs) == 1
        assert second_bag_runs[0]["outcome"] == "DELIVERED"
