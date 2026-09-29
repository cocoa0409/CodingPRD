"""Two four-level cascades that run in opposite money directions.

A temperature excursion at the door voids a bill and frees budget; an ops
authorisation of a replacement bag creates a bill and commits budget. In both
chains each level is caused by the level above it rather than by the request.
"""

import pytest

from test_helpers import (
    assert_instant,
    CLOCK_DOORSTEP_DAY3,
    CLOCK_PICKUP_DAY3,
    OPS_REVIEWER,
    TEST_USERS,
    Z1_COLD_CONTROLLED_SUBTOTAL_CENTS,
    Z1_STANDARD_SUBTOTAL_CENTS,
    adjudicate,
    advance_to_assigned,
    advance_to_out_for_delivery,
    advance_to_picked_up,
    allocations_for,
    assert_courier_counters,
    assert_delivery_state,
    assert_grant_ledger,
    assert_payer_mix,
    assert_reliability_scores,
    assert_window_occupancy,
    build_queued_delivery,
    build_window,
    cases_for,
    exhaust_attempt_ladder,
    factories,
    force_cold_breach,
    read_assignment,
    read_courier,
    read_delivery,
    read_grant,
    read_order,
    read_window,
    record_attempt,
    redepart,
    set_clock,
    start_review,
    utc_ts,
    validate_error,
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


@pytest.fixture
def cold_bag_breached_at_the_door(api):
    """A cold controlled bag 130 minutes out of the cooler on its second run.

    The pool is funded to exactly the one delivery's commitment, so the fourth
    level of the chain is observable as a status flip back to ACTIVE.
    """
    scn = build_queued_delivery(
        api,
        network_kwargs={
            "grant": {"grant_budget_cents": 150, "per_delivery_cap_cents": 150}
        },
        order_kwargs=COLD_CII_ORDER,
        window_kwargs={"window_end": utc_ts(3, 18), "capacity_slots": 1},
    )
    advance_to_assigned(api, scn)
    set_clock(api, CLOCK_PICKUP_DAY3)
    advance_to_picked_up(api, scn)
    advance_to_out_for_delivery(api, scn, depart_clock=CLOCK_DOORSTEP_DAY3)
    record_attempt(api, scn, "NO_ANSWER", id_verification_method="NONE")
    redepart(api, scn, utc_ts(3, 15, 55))
    force_cold_breach(
        api,
        scn,
        breach_clock=utc_ts(3, 16),
        recipient_relationship="SELF",
        pod_photo_ref="pod/4471-b.jpg",
    )
    return scn


class TestColdBreachCascade:
    """"A forced `COLD_BREACH` produces a four-level transitive cascade in which
    each level is caused by the one before it, not by the attempt itself."
    """

    def test_level_one_overrides_the_reported_outcome_and_opens_the_return_clock(
        self, api, cold_bag_breached_at_the_door
    ):
        """Two hours out of the box beats any proof of delivery.

        "If the `handling_class` is `COLD_CHAIN` or `COLD_CHAIN_CONTROLLED`
        **and** that elapsed figure is 120 minutes or more, the reported
        `requested_outcome` is discarded and the recorded `outcome` becomes
        `COLD_BREACH`."

        Design: Difficulty/transitive_cascade/cold_breach_forced_outcome_cascade_depth_four
        """
        scn = cold_bag_breached_at_the_door
        breach = scn.attempts[-1]
        assert breach["requested_outcome"] == "DELIVERED"
        assert breach["outcome"] == "COLD_BREACH"
        assert breach["elapsed_since_pickup_minutes"] == 130
        assert breach["reliability_credit"] == pytest.approx(0.0, abs=0.01)
        assert breach["attempt_no"] == 2

        delivery = read_delivery(api, scn.delivery["id"])
        assert delivery["custody_status"] == "RETURN_PENDING"
        assert_instant(delivery["return_due_at"], utc_ts(3, 20))

    def test_level_two_opens_a_cold_breach_case_nobody_asked_for(
        self, api, cold_bag_breached_at_the_door
    ):
        """The case exists because the bag entered RETURN_PENDING while cold.

        "Second, *because* the delivery entered `RETURN_PENDING` with a cold
        handling class, an exception case is opened with `exception_type`
        `COLD_BREACH`, `status` `OPEN`, and a null `opened_by_ops_user_id`."

        Design: Difficulty/transitive_cascade/cold_breach_forced_outcome_cascade_depth_four
        """
        scn = cold_bag_breached_at_the_door
        cases = cases_for(api, scn.delivery["id"])
        assert len(cases) == 1
        assert cases[0]["exception_type"] == "COLD_BREACH"
        assert cases[0]["status"] == "OPEN"
        assert cases[0]["opened_by_ops_user_id"] is None

    def test_levels_three_and_four_void_the_bill_and_hand_the_budget_back(
        self, api, cold_bag_breached_at_the_door
    ):
        """Spoiled product is not billed, and the pool recovers its commitment.

        "Third, *because* a `COLD_BREACH` case was opened, the delivery's
        `ACTIVE` fee allocation is set to `VOIDED`, the delivery's
        `settlement_status` moves `PROVISIONAL → VOIDED`, and its
        `fee_subtotal_cents` is zeroed — spoiled product is not billed. Fourth,
        *because* that allocation was voided, its `plan_grant_cents` is
        subtracted from the pool's `committed_cents`, and the pool returns
        `EXHAUSTED → ACTIVE` if `remaining_cents` thereby rises above 0."

        Design: Difficulty/transitive_cascade/cold_breach_forced_outcome_cascade_depth_four
        """
        scn = cold_bag_breached_at_the_door
        rows = allocations_for(api, scn.delivery["id"])
        assert len(rows) == 1
        assert rows[0]["status"] == "VOIDED"
        assert rows[0]["fee_subtotal_cents"] == Z1_COLD_CONTROLLED_SUBTOTAL_CENTS

        delivery = read_delivery(api, scn.delivery["id"])
        assert_delivery_state(delivery, "RETURN_PENDING", "VOIDED")
        assert delivery["fee_subtotal_cents"] == 0

        assert_grant_ledger(
            read_grant(api, scn.net.grant["id"]),
            committed_cents=0,
            consumed_cents=0,
            remaining_cents=150,
            status="ACTIVE",
        )

    def test_fan_out_releases_the_courier_and_the_slot_but_not_the_order(
        self, api, cold_bag_breached_at_the_door
    ):
        """The side effects alongside the chain, and the one that does not move.

        "Alongside the chain, the courier's `ACCEPTED` assignment moves to
        `RELEASED`, its `active_delivery_count` drops with the usual `ON_ROUTE →
        AVAILABLE` at 0, the window's slot is released with the usual `FULL →
        OPEN`, and both reliability scores are recomputed with the possibility of
        an automatic suspension."

        Design: Difficulty/transitive_cascade/cold_breach_forced_outcome_cascade_depth_four
        """
        scn = cold_bag_breached_at_the_door
        assert read_assignment(api, scn.assignment["id"])["status"] == "RELEASED"

        courier = read_courier(api, scn.courier["id"])
        assert_courier_counters(
            courier,
            attempt_total_count=2,
            delivered_count=0,
            active_delivery_count=0,
            status="AVAILABLE",
        )
        assert_reliability_scores(courier, rolling=22.22, lifetime=0.00)

        assert_window_occupancy(read_window(api, scn.window["id"]), reserved_slots=0)
        assert read_order(api, scn.order["id"])["status"] == "DISPATCHED"


@pytest.fixture
def reship_target_ready(api):
    """An exhausted ladder, a reviewer holding the case, and a next-day window.

    The pool is funded to exactly two commitments so the reship drives it to its
    ceiling.
    """
    scn = build_queued_delivery(
        api,
        network_kwargs={
            "grant": {"grant_budget_cents": 300, "per_delivery_cap_cents": 150}
        },
        order_kwargs=STANDARD_ORDER,
        window_kwargs={"window_end": utc_ts(3, 22), "capacity_slots": 2},
    )
    reship_window = build_window(
        api,
        scn.net.zone["id"],
        window_start=utc_ts(4, 14),
        window_end=utc_ts(4, 16),
        capacity_slots=1,
    )
    advance_to_assigned(api, scn)
    advance_to_picked_up(api, scn)
    advance_to_out_for_delivery(api, scn, depart_clock=CLOCK_DOORSTEP_DAY3)
    exhaust_attempt_ladder(api, scn, first_attempt_clock=CLOCK_DOORSTEP_DAY3)
    scn.case = start_review(api, scn.case["id"], headers=TEST_USERS["ops_reviewer"])
    return scn, reship_window


def _authorize_reship(api, scn, reship_window):
    version = read_delivery(api, scn.delivery["id"])["version"]
    return adjudicate(
        api,
        scn.case["id"],
        "RESHIP",
        version,
        headers=TEST_USERS["ops_reviewer"],
        reship_window_id=reship_window["id"],
        notes="Rebag and re-run next day.",
    )


class TestReshipAuthorizationCascade:
    """"The branch then runs its own four-level cascade."
    """

    def test_level_one_creates_a_replacement_bag_linked_to_the_original(
        self, api, reship_target_ready
    ):
        """The authorisation itself is what puts a new bag on the board.

        "First, a new delivery is created for the same `order_id`, pointing at
        the `reship_window_id`, with `reship_of_delivery_id` set to the original
        delivery, `custody_status` `QUEUED`, and `settlement_status`
        `PROVISIONAL`."

        Design: Difficulty/transitive_cascade/reship_authorization_cascade_depth_four
        """
        scn, reship_window = reship_target_ready
        case = _authorize_reship(api, scn, reship_window)
        assert case["status"] == "RESHIP_AUTHORIZED"
        assert case["disposition"] == "RESHIP"
        assert case["adjudicated_by_ops_user_id"] == OPS_REVIEWER
        assert case["reship_delivery_id"] is not None

        rows, meta = validate_paginated(
            api.list_deliveries(
                TEST_USERS["ops"], reship_of_delivery_id=scn.delivery["id"]
            )
        )
        assert meta["total_count"] == 1
        reship = rows[0]
        assert reship["order_id"] == scn.order["id"]
        assert reship["window_id"] == reship_window["id"]
        assert_delivery_state(reship, "QUEUED", "PROVISIONAL")
        assert reship["attempt_count"] == 0
        assert reship["courier_id"] is None

    def test_levels_two_to_four_price_the_reship_and_exhaust_the_pool(
        self, api, reship_target_ready
    ):
        """A fresh provisional bill drives the pool's commitment to its ceiling.

        "Second, *because* that reship delivery was created, a `PROVISIONAL`
        allocation is computed for it exactly as in §3.3, with
        `billable_attempts` pinned to 1. Third, *because* that allocation was
        created, its `plan_grant_cents` is added to the pool's `committed_cents`.
        Fourth, *because* `committed_cents` rose, the pool moves `ACTIVE →
        EXHAUSTED` if `remaining_cents` reaches 0."

        Design: Difficulty/transitive_cascade/reship_authorization_cascade_depth_four
        """
        scn, reship_window = reship_target_ready
        case = _authorize_reship(api, scn, reship_window)

        rows = allocations_for(api, case["reship_delivery_id"])
        assert len(rows) == 1
        allocation = rows[0]
        assert allocation["variant"] == "PROVISIONAL"
        assert allocation["status"] == "ACTIVE"
        assert allocation["fee_subtotal_cents"] == Z1_STANDARD_SUBTOTAL_CENTS
        assert_payer_mix(
            allocation,
            patient_gross_share_cents=157,
            plan_grant_cents=150,
            absorption_tier_cents=50,
            patient_payable_cents=0,
            pharmacy_payable_cents=1416,
        )

        assert_grant_ledger(
            read_grant(api, scn.net.grant["id"]),
            committed_cents=300,
            remaining_cents=0,
            status="EXHAUSTED",
        )

    def test_fan_out_fills_the_reship_window_and_bumps_the_original_row(
        self, api, reship_target_ready
    ):
        """The slot reservation and the linkage bump sit beside the chain.

        "Alongside, the target window's `reserved_slots` rises by one with `OPEN
        → FULL` at capacity, and the case's `reship_delivery_id` records the new
        delivery. The original delivery's `version` increments because its reship
        linkage changed."

        Design: Difficulty/transitive_cascade/reship_authorization_cascade_depth_four
        """
        scn, reship_window = reship_target_ready
        before = read_delivery(api, scn.delivery["id"])
        _authorize_reship(api, scn, reship_window)

        assert_window_occupancy(
            read_window(api, reship_window["id"]),
            reserved_slots=1,
            available_slots=0,
            status="FULL",
        )

        after = read_delivery(api, scn.delivery["id"])
        assert_delivery_state(after, "RETURN_PENDING", "PROVISIONAL")
        assert after["version"] == before["version"] + 1

    def test_the_same_case_cannot_be_adjudicated_twice(
        self, api, reship_target_ready
    ):
        """An authorised case has left the adjudicable state behind.

        "`ExceptionCase.status` is `OPEN` to start review, `UNDER_REVIEW` to
        adjudicate, and one of `RESHIP_AUTHORIZED`, `CREDIT_ISSUED`, or `DENIED`
        to close — otherwise `ERR_INVALID_EXCEPTION_STATE`."

        Design: Difficulty/transitive_cascade/reship_authorization_cascade_depth_four
        """
        scn, reship_window = reship_target_ready
        _authorize_reship(api, scn, reship_window)

        version = read_delivery(api, scn.delivery["id"])["version"]
        response = api.adjudicate_exception_case(
            scn.case["id"],
            factories.adjudication_payload("CREDIT", version),
            headers=TEST_USERS["ops_reviewer"],
        )
        validate_error(response, "ERR_INVALID_EXCEPTION_STATE", 409)
