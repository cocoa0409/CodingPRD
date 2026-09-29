"""Cross-cutting layers: optimistic concurrency, version accounting, immediacy.

The two version guards protect a view rather than the thing viewed, so a refusal
can arrive while capacity is still free and a whole four-level cascade can be
suppressed by a single intervening write. The same counter that powers those
guards is a per-row write counter, and every effect it counts is visible in the
response that caused it and in the very next read.
"""

import pytest

from test_helpers import (
    OPS_HEADERS,
    TEST_USERS,
    Z1_STANDARD_SUBTOTAL_CENTS,
    advance_to_assigned,
    advance_to_out_for_delivery,
    advance_to_picked_up,
    assert_courier_counters,
    assert_grant_ledger,
    assert_reliability_scores,
    assert_window_occupancy,
    build_courier,
    build_network,
    build_queued_delivery,
    build_out_for_delivery,
    build_ready_order,
    build_window,
    deliver,
    exhaust_attempt_ladder,
    factories,
    find_by,
    latest_case,
    read_assignment,
    read_case,
    read_courier,
    read_delivery,
    read_grant,
    read_order,
    read_window,
    record_attempt,
    reserve_delivery,
    set_clock,
    start_review,
    utc_ts,
    validate_error,
    validate_paginated,
    validate_success,
)

LONG_WINDOW = {"window_end": utc_ts(3, 22)}
NEXT_DAY_WINDOW = {"window_start": utc_ts(4, 14), "window_end": utc_ts(4, 16)}


# ─── The window version ───────────────────────────────


@pytest.fixture
def a_three_slot_window_with_one_slot_already_taken(api):
    """Two free slots remain, but the version the client is holding is one behind."""
    net = build_network(api)
    reserved = build_ready_order(api, net)
    waiting = build_ready_order(api, net)
    window = build_window(api, net.zone["id"], capacity_slots=3)
    stale_version = window["version"]
    reserve_delivery(api, net, reserved["id"], window["id"], stale_version)
    return net, waiting, window, stale_version


class TestTheWindowVersionGuardsAViewNotCapacity:
    """"If that value does not equal the window's current `version`, the
    reservation is rejected with `ERR_STALE_WINDOW_VERSION` (HTTP 412)."
    """

    def test_a_stale_version_is_refused_while_two_slots_stand_free(
        self, api, a_three_slot_window_with_one_slot_already_taken
    ):
        """Capacity was never the objection, and the refusal writes nothing.

        "The point of the check is that another writer may already have taken a
        slot on that window — perfectly legitimate while `available_slots` stays
        positive — which makes the current writer's view of `reserved_slots`,
        `available_slots`, and `status` obsolete."

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_window_version_returns_412_and_the_refreshed_one_succeeds
        """
        net, waiting, window, stale_version = a_three_slot_window_with_one_slot_already_taken

        validate_error(
            api.create_delivery(
                factories.delivery_payload(waiting["id"], window["id"], stale_version),
                headers=net.pharmacy_headers,
            ),
            "ERR_STALE_WINDOW_VERSION",
            412,
        )

        live = read_window(api, window["id"])
        assert_window_occupancy(live, reserved_slots=1, available_slots=2, status="OPEN")
        _rows, meta = validate_paginated(api.list_deliveries(OPS_HEADERS, order_id=waiting["id"]))
        assert meta["total_count"] == 0
        assert_grant_ledger(read_grant(api, net.grant["id"]), committed_cents=150, consumed_cents=0)
        assert read_order(api, waiting["id"])["status"] == "READY"

    def test_re_reading_the_version_makes_the_identical_body_succeed(
        self, api, a_three_slot_window_with_one_slot_already_taken
    ):
        """The rejected attempt bumped nothing, so version counts writes that landed.

        "`version` (integer) — a counter that increments by one on every mutation
        of the row, including mutations the server performs on its own initiative
        as a cascade from a request addressed at some other resource."

        Design: Corner/cross_cutting_complexity_layers/a_stale_expected_window_version_returns_412_and_the_refreshed_one_succeeds
        """
        net, waiting, window, stale_version = a_three_slot_window_with_one_slot_already_taken

        validate_error(
            api.create_delivery(
                factories.delivery_payload(waiting["id"], window["id"], stale_version),
                headers=net.pharmacy_headers,
            ),
            "ERR_STALE_WINDOW_VERSION",
            412,
        )
        live_version = read_window(api, window["id"])["version"]
        assert live_version == stale_version + 1

        created = validate_success(
            api.create_delivery(
                factories.delivery_payload(waiting["id"], window["id"], live_version),
                headers=net.pharmacy_headers,
            ),
            201,
        )
        assert created["custody_status"] == "QUEUED"

        after = read_window(api, window["id"])
        assert after["version"] == live_version + 1
        assert_window_occupancy(after, reserved_slots=2, available_slots=1, status="OPEN")
        assert_grant_ledger(read_grant(api, net.grant["id"]), committed_cents=300)


# ─── The delivery version ─────────────────────────────


@pytest.fixture
def a_reviewed_case_whose_delivery_moved_after_the_operator_read_it(api):
    """The version was read at RETURN_PENDING; the pharmacy then received the bag.

    An empty next-day window in the same zone and mode stands ready as the
    reship target, so nothing but the version can be wrong.
    """
    scn = build_queued_delivery(api, window_kwargs=LONG_WINDOW)
    reship_window = build_window(api, scn.net.zone["id"], **NEXT_DAY_WINDOW)
    advance_to_assigned(api, scn, courier=build_courier(api, display_name="Ray Ortiz"))
    advance_to_picked_up(api, scn)
    advance_to_out_for_delivery(api, scn)
    exhaust_attempt_ladder(api, scn)

    stale_version = read_delivery(api, scn.delivery["id"])["version"]
    scn.delivery = validate_success(
        api.confirm_return(scn.delivery["id"], headers=scn.pharmacy_headers)
    )
    case = latest_case(api, scn.delivery["id"])
    start_review(api, case["id"])
    return scn, case, reship_window, stale_version


class TestTheDeliveryVersionGuardsTheWholeReshipCascade:
    """"If that value does not equal the delivery's current `version`, the
    adjudication is rejected with `ERR_STALE_DELIVERY_VERSION` (HTTP 412)."
    """

    def test_a_stale_version_suppresses_the_four_level_reship_cascade(
        self, api, a_reviewed_case_whose_delivery_moved_after_the_operator_read_it
    ):
        """One intervening write, and none of the four levels happens.

        "The delivery may in the meantime have been settled, waived, returned,
        or re-linked to another reship — each of which legitimately supersedes
        the operator's understanding of what the adjudication would do."

        Design: Corner/cross_cutting_complexity_layers/an_adjudication_on_a_stale_delivery_version_returns_412_before_any_reship_is_created
        """
        scn, case, reship_window, stale_version = (
            a_reviewed_case_whose_delivery_moved_after_the_operator_read_it
        )

        validate_error(
            api.adjudicate_exception_case(
                case["id"],
                factories.adjudication_payload(
                    "RESHIP", stale_version, reship_window_id=reship_window["id"]
                ),
                headers=TEST_USERS["ops_third"],
            ),
            "ERR_STALE_DELIVERY_VERSION",
            412,
        )

        _rows, meta = validate_paginated(
            api.list_deliveries(OPS_HEADERS, reship_of_delivery_id=scn.delivery["id"])
        )
        assert meta["total_count"] == 0
        assert_window_occupancy(read_window(api, reship_window["id"]), reserved_slots=0, status="OPEN")
        assert_grant_ledger(read_grant(api, scn.net.grant["id"]), committed_cents=150)

        reviewed = read_case(api, case["id"])
        assert reviewed["status"] == "UNDER_REVIEW"
        assert reviewed["disposition"] is None
        assert reviewed["reship_delivery_id"] is None
        assert read_delivery(api, scn.delivery["id"])["version"] == stale_version + 1

    def test_the_refreshed_version_lets_the_same_call_fire_completely(
        self, api, a_reviewed_case_whose_delivery_moved_after_the_operator_read_it
    ):
        """The replacement bag, its provisional bill and its commitment all appear.

        "First, a new delivery is created for the same `order_id`, pointing at
        the `reship_window_id`, with `reship_of_delivery_id` set to the original
        delivery, `custody_status` `QUEUED`, and `settlement_status`
        `PROVISIONAL`."

        Design: Corner/cross_cutting_complexity_layers/an_adjudication_on_a_stale_delivery_version_returns_412_before_any_reship_is_created
        """
        scn, case, reship_window, _stale = (
            a_reviewed_case_whose_delivery_moved_after_the_operator_read_it
        )
        live_version = read_delivery(api, scn.delivery["id"])["version"]

        authorized = validate_success(
            api.adjudicate_exception_case(
                case["id"],
                factories.adjudication_payload(
                    "RESHIP", live_version, reship_window_id=reship_window["id"]
                ),
                headers=TEST_USERS["ops_third"],
            )
        )
        assert authorized["status"] == "RESHIP_AUTHORIZED"

        rows, meta = validate_paginated(
            api.list_deliveries(OPS_HEADERS, reship_of_delivery_id=scn.delivery["id"])
        )
        assert meta["total_count"] == 1
        reship = rows[0]
        assert authorized["reship_delivery_id"] == reship["id"]
        assert reship["custody_status"] == "QUEUED"
        assert reship["settlement_status"] == "PROVISIONAL"
        assert reship["window_id"] == reship_window["id"]
        assert reship["fee_subtotal_cents"] == Z1_STANDARD_SUBTOTAL_CENTS
        assert_grant_ledger(read_grant(api, scn.net.grant["id"]), committed_cents=300)


# ─── The counter itself ───────────────────────────────


@pytest.fixture
def a_released_order_an_empty_window_and_an_idle_courier(api):
    """The order stands at version 2 after its release; nothing else has moved."""
    net = build_network(api)
    order = build_ready_order(api, net)
    window = build_window(api, net.zone["id"])
    bystander = build_courier(api, available=False, display_name="Tova Mies")
    return net, order, window, bystander


class TestVersionCountsSuccessfulWritesPerRow:
    """"Because so much of this system moves by cascade, the versioning rule
    deserves emphasis: when one request drives a change on a second or third
    resource, each of those resources independently refreshes its `updated_at`
    and increments its `version`."
    """

    def test_one_reservation_bumps_the_order_and_the_window_and_nothing_else(
        self, api, a_released_order_an_empty_window_and_an_idle_courier
    ):
        """A refused call in between leaves every counter exactly where it was.

        "The window's `reserved_slots` rises by one and it flips to `FULL` if
        that reaches `capacity_slots`; the order moves to `DISPATCHED`; and the
        bill is built. Window, order, and grant pool each bump their own
        `version`."

        Design: Corner/cross_cutting_complexity_layers/version_increments_once_per_successful_write_on_every_touched_entity
        """
        net, order, window, bystander = a_released_order_an_empty_window_and_an_idle_courier
        assert order["version"] == 2
        assert window["version"] == 1

        delivery = reserve_delivery(api, net, order["id"], window["id"])
        assert delivery["version"] == 1

        released = read_order(api, order["id"])
        assert released["status"] == "DISPATCHED"
        assert released["version"] == 3
        assert read_window(api, window["id"])["version"] == 2

        validate_error(
            api.mark_order_ready(order["id"], headers=net.pharmacy_headers),
            "ERR_INVALID_ORDER_STATE",
            409,
        )
        assert read_order(api, order["id"])["version"] == 3
        assert read_courier(api, bystander["id"])["version"] == 1

    def test_the_cancellation_bumps_all_three_rows_again(
        self, api, a_released_order_an_empty_window_and_an_idle_courier
    ):
        """The compensating write is a write like any other on every row it touches.

        "Every touched row bumps its `version`."

        Design: Corner/cross_cutting_complexity_layers/version_increments_once_per_successful_write_on_every_touched_entity
        """
        net, order, window, bystander = a_released_order_an_empty_window_and_an_idle_courier
        delivery = reserve_delivery(api, net, order["id"], window["id"])

        cancelled = validate_success(
            api.cancel_delivery(delivery["id"], headers=net.pharmacy_headers)
        )
        assert cancelled["custody_status"] == "CANCELLED"
        assert cancelled["version"] == 2

        assert read_window(api, window["id"])["version"] == 3
        reopened = read_order(api, order["id"])
        assert reopened["status"] == "READY"
        assert reopened["version"] == 4

        grant = read_grant(api, net.grant["id"])
        assert grant["version"] == 3
        assert_grant_ledger(grant, committed_cents=0, consumed_cents=0, status="ACTIVE")
        assert read_courier(api, bystander["id"])["version"] == 1


# ─── The selector's two steps ─────────────────────────


@pytest.fixture
def ray_one_failed_run_in_and_tova_with_no_history(api):
    """Ray was onboarded first and is carrying a bag that missed the door once.

    A second bag waits on a next-day window that Ray's buffered interval does
    not touch, so he stays in the candidate pool for it.
    """
    net = build_network(api)
    second_order = build_ready_order(api, net)
    next_day = build_window(api, net.zone["id"], **NEXT_DAY_WINDOW)
    scn = build_queued_delivery(api, net=net, window_kwargs=LONG_WINDOW)
    ray = build_courier(api, display_name="Ray Ortiz")
    tova = build_courier(api, display_name="Tova Mies")

    advance_to_assigned(api, scn, courier=ray)
    advance_to_picked_up(api, scn)
    advance_to_out_for_delivery(api, scn)
    record_attempt(api, scn, "NO_ANSWER")

    waiting = reserve_delivery(api, net, second_order["id"], next_day["id"])
    set_clock(api, utc_ts(3, 14, 30))
    return scn, waiting, ray, tova


class TestTheSelectorRanksBeforeItReachesTheTieBreak:
    """"Candidates are then ordered by `rolling_reliability_score` descending,
    ties broken by `active_delivery_count` ascending, and any remaining ties
    broken by `created_at` ascending — never by identifier."
    """

    def test_the_higher_rolling_score_wins_over_the_earlier_created_at(
        self, api, ray_one_failed_run_in_and_tova_with_no_history
    ):
        """Ray was onboarded first, so only the ranking step can explain Tova.

        "The first row after that ordering is the courier offered the job."

        Design: Corner/cross_cutting_complexity_layers/the_selector_ranks_by_rolling_score_before_reaching_the_created_at_tie_break
        """
        scn, waiting, ray, tova = ray_one_failed_run_in_and_tova_with_no_history

        carrying = read_courier(api, ray["id"])
        assert_courier_counters(
            carrying, attempt_total_count=1, delivered_count=0, active_delivery_count=1, status="ON_ROUTE"
        )
        assert_reliability_scores(carrying, rolling=50.00, lifetime=0.00)
        idle = read_courier(api, tova["id"])
        assert_courier_counters(idle, attempt_total_count=0, status="AVAILABLE")
        assert_reliability_scores(idle, rolling=100.00)

        offer = validate_success(
            api.dispatch_delivery(
                waiting["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload()
            ),
            201,
        )
        assert offer["courier_id"] == tova["id"]
        assert offer["rank_score"] == pytest.approx(100.00, abs=0.01)
        assert read_delivery(api, waiting["id"])["custody_status"] == "QUEUED"
        assert read_delivery(api, scn.delivery["id"])["custody_status"] == "ATTEMPT_FAILED"

    def test_the_lower_scoring_courier_was_a_candidate_all_along(
        self, api, ray_one_failed_run_in_and_tova_with_no_history
    ):
        """Take the winner off shift and the same sweep of the pool reaches Ray.

        "A courier is a candidate only when every one of the following holds:
        its `status` is `AVAILABLE` or `ON_ROUTE`; its `mode` equals the
        window's `courier_mode`; the window zone's `zone_code` appears in its
        `served_zone_codes`; its identifier is not in the delivery's
        `excluded_courier_ids`; it is `cold_chain_equipped` if the
        `handling_class` is `COLD_CHAIN` or `COLD_CHAIN_CONTROLLED`; it is
        `controlled_certified` if the `handling_class` is `CONTROLLED` or
        `COLD_CHAIN_CONTROLLED`; and it holds no `ACCEPTED` assignment whose
        buffered committed interval touches this window."

        Design: Corner/cross_cutting_complexity_layers/the_selector_ranks_by_rolling_score_before_reaching_the_created_at_tie_break
        """
        _scn, waiting, ray, tova = ray_one_failed_run_in_and_tova_with_no_history
        assert read_delivery(api, waiting["id"])["excluded_courier_ids"] == []

        validate_success(
            api.set_courier_status(
                tova["id"],
                factories.courier_status_payload("OFFLINE"),
                headers=TEST_USERS["ops"],
            )
        )
        offer = validate_success(
            api.dispatch_delivery(
                waiting["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload()
            ),
            201,
        )
        assert offer["courier_id"] == ray["id"]
        assert offer["rank_score"] == pytest.approx(50.00, abs=0.01)


# ─── Immediacy ────────────────────────────────────────


@pytest.fixture
def a_standard_bag_standing_at_the_door(api):
    """One 1000-cent bag OUT_FOR_DELIVERY at 14:00Z on a single-slot window."""
    return build_out_for_delivery(api, order_kwargs={"rx_line_count": 1, "total_rx_value_cents": 1000})


class TestEveryCascadedEffectIsVisibleImmediately:
    """"The consistency model is immediate: by the time a response is written,
    every derived count, score, status, and money figure the request touched has
    already been brought into line."
    """

    def test_the_attempt_response_and_the_next_read_already_agree(
        self, api, a_standard_bag_standing_at_the_door
    ):
        """No retry loop: the slot, the scores and the assignment have all moved.

        "A recorded `DELIVERED` outcome carries a `reliability_credit` of 1.0 and
        cascades widely: the delivery advances `OUT_FOR_DELIVERY → DELIVERED`,
        its `attempt_count` rises by one, `last_attempt_at` and `delivered_at`
        are both stamped from the clock; the courier's `ACCEPTED` assignment
        moves `ACCEPTED → COMPLETED`; the courier's `active_delivery_count`
        drops by one and the courier returns `ON_ROUTE → AVAILABLE` once it
        reaches 0"

        Design: Corner/consistency_model/every_cascaded_effect_is_visible_in_the_same_response_and_the_very_next_read
        """
        scn = a_standard_bag_standing_at_the_door
        attempt = deliver(api, scn, id_verification_method="DOB_MATCH")
        assert attempt["outcome"] == "DELIVERED"
        assert attempt["attempt_no"] == 1
        assert attempt["reliability_credit"] == pytest.approx(1.0, abs=0.01)

        assert_window_occupancy(
            read_window(api, scn.window["id"]), reserved_slots=0, available_slots=1, status="OPEN"
        )
        courier = read_courier(api, scn.courier["id"])
        assert_courier_counters(
            courier, attempt_total_count=1, delivered_count=1, active_delivery_count=0, status="AVAILABLE"
        )
        assert_reliability_scores(courier, rolling=100.00, lifetime=100.00)
        assert read_assignment(api, scn.assignment["id"])["status"] == "COMPLETED"

    def test_the_settle_response_carries_the_final_bill_not_a_pending_marker(
        self, api, a_standard_bag_standing_at_the_door
    ):
        """The allocation history and the order's closure are readable at once.

        "The `PROVISIONAL` allocation is set to `SUPERSEDED` and its
        `plan_grant_cents` is released from the pool's `committed_cents`. A fresh
        allocation is then computed with `variant` `FINAL` and `status`
        `ACTIVE`, using the very same six-line construction, per-line rounding,
        and payer-mix waterfall described in §3.3 — with one difference, and it
        is the whole point of the variant."

        Design: Corner/consistency_model/every_cascaded_effect_is_visible_in_the_same_response_and_the_very_next_read
        """
        scn = a_standard_bag_standing_at_the_door
        deliver(api, scn, id_verification_method="DOB_MATCH")

        settled = validate_success(api.settle_delivery(scn.delivery["id"], headers=OPS_HEADERS))
        assert settled["settlement_status"] == "FINALIZED"
        assert settled["fee_subtotal_cents"] == Z1_STANDARD_SUBTOTAL_CENTS

        rows, meta = validate_paginated(
            api.list_fee_allocations(OPS_HEADERS, delivery_id=scn.delivery["id"])
        )
        assert meta["total_count"] == 2
        final = find_by(rows, variant="FINAL")
        assert final["status"] == "ACTIVE"
        assert find_by(rows, variant="PROVISIONAL")["status"] == "SUPERSEDED"
        assert read_order(api, scn.order["id"])["status"] == "CLOSED"
