"""Utilisation pressure, upgrade order costing and the vendor scorecard.

Telemetry drives a single running counter, the counter drives the circuit's
capacity posture, and the posture eventually raises an order whose money is
frozen at creation. Only completion widens the circuit; cancellation gives back
the megabits and nothing else.
"""

from test_helpers import (
    CAPACITY_PLANNER_HEADERS,
    CAPACITY_PLANNER_USER_ID,
    SYSTEM_USER_ID,
    VENDOR_MANAGER_HEADERS,
    VENDOR_MANAGER_USER_ID,
    ApiErrorId,
    advance_clock,
    approve_upgrade_order,
    assert_carrier_ledger,
    assert_circuit_posture,
    assert_credit_ratio,
    assert_minutes,
    assert_page,
    assert_score,
    assert_upgrade_cost,
    assert_utilization_pct,
    build_pft_capacity_circuit,
    build_wbf_circuit,
    capacity_reading_payload,
    create_carrier,
    create_circuit,
    create_manual_upgrade_order,
    create_vendor_review,
    decide_vendor_review,
    order_cancel_payload,
    read_carrier,
    read_circuit,
    record_reading,
    review_decide_payload,
    set_order_state,
    submit_upgrade_order,
    validate_error,
    validate_paginated,
    validate_success,
)

EXPEDITED_SUBTOTAL_CENTS = 430000
EXPEDITED_FEE_CENTS = 107500
EXPEDITED_TOTAL_CENTS = 537500
TIER_KEYED_ON_TOTAL_CENTS = 494500


def _list_orders(api, circuit_id: str, params: dict = None):
    """Read a circuit's upgrade orders, since orders have no single-row read."""
    return validate_paginated(
        api.list_circuit_upgrade_orders(circuit_id, CAPACITY_PLANNER_HEADERS, params)
    )


class TestUtilizationThresholdIsInclusive:
    """The high-utilisation bound is compared at two decimals and includes 80.00."""

    def test_a_sample_of_79_99_is_normal_and_moves_nothing(self, api):
        """One hundredth of a percent below the bound leaves every counter at rest.

        PRD 3.8: "The reading's `threshold_state` is `HIGH` when `utilization_pct` is at or above 80.00 and `NORMAL` otherwise, compared at two decimal places, so exactly 80.00 is `HIGH` while 79.99 is `NORMAL`."
        PRD 3.8: "The circuit's `capacity_state` is then re-derived from that counter alone: `UPGRADE_REQUIRED` once the counter has reached 3, `WATCH` while it stands at 1 or 2, and `NORMAL` when it is 0."

        Design: Difficulty/boundary_precision_check/utilization_threshold_inclusive_at_exactly_80_00
        """
        state = build_wbf_circuit(api, "2026-08-05T01:00:00Z")

        reading = record_reading(
            api, state["circuit_id"], "2026-08-05T01:00:00Z", 79.99, direction="EGRESS"
        )

        assert_utilization_pct(reading["utilization_pct"], 79.99)
        assert reading["threshold_state"] == "NORMAL", (
            f"79.99 is below the inclusive bound, got {reading['threshold_state']}"
        )
        assert_circuit_posture(
            read_circuit(api, state["circuit_id"]),
            capacity_state="NORMAL",
            consecutive_high_readings=0,
            bandwidth_mbps=100,
        )
        assert_carrier_ledger(read_carrier(api, state["carrier_id"]), committed_mbps=0)

    def test_exactly_80_00_is_high_yet_orders_nothing_on_its_own(self, api):
        """The boundary sample moves the counter and the posture, and only those.

        PRD 3.8: "A `HIGH` reading raises the circuit's `consecutive_high_readings` by 1; a `NORMAL` reading resets it to 0 outright, with no decay and no partial credit."
        PRD 3.8: "Crossing into `UPGRADE_REQUIRED` for the first time — that is, when the previous `capacity_state` was something else — raises an upgrade order without anyone asking."

        Design: Difficulty/boundary_precision_check/utilization_threshold_inclusive_at_exactly_80_00
        """
        state = build_wbf_circuit(api, "2026-08-05T01:00:00Z")
        record_reading(
            api, state["circuit_id"], "2026-08-05T01:00:00Z", 79.99, direction="EGRESS"
        )

        advance_clock(api, "2026-08-05T01:05:00Z")
        boundary = record_reading(
            api, state["circuit_id"], "2026-08-05T01:05:00Z", 80.00, direction="EGRESS"
        )

        assert boundary["threshold_state"] == "HIGH", (
            f"80.00 satisfies the inclusive bound, got {boundary['threshold_state']}"
        )
        assert_circuit_posture(
            read_circuit(api, state["circuit_id"]),
            capacity_state="WATCH",
            consecutive_high_readings=1,
            bandwidth_mbps=100,
        )

        _, meta = _list_orders(api, state["circuit_id"])
        assert_page(meta, total_count=0)
        assert_carrier_ledger(read_carrier(api, state["carrier_id"]), committed_mbps=0)


class TestExpediteTierIsKeyedOnTheSubtotal:
    """The expedite band is selected before the fee is added, never after."""

    def _expedited_order(self, api) -> dict:
        """A manual, expedited 100 to 300 Mbps order on an otherwise quiet circuit."""
        state = build_wbf_circuit(api, "2026-08-05T00:00:00Z")
        state["order"] = create_manual_upgrade_order(
            api,
            state["circuit_id"],
            300,
            state["circuit_version"],
            expedite=True,
            user_id=CAPACITY_PLANNER_USER_ID,
        )
        return state

    def test_the_expedited_order_is_priced_from_its_own_subtotal(self, api):
        """A 430000-cent subtotal sits in the 0.25 band, so the total is 537500.

        PRD 3.8: "Second, `subtotal_cents` is 250000 plus `delta_mbps` multiplied by 900."
        PRD 3.8: "Third, an expedite tier percentage is selected **from `subtotal_cents`**: 0.25 when `subtotal_cents` is below 500000, 0.15 when it is below 1500000, and 0.08 otherwise, with each band's lower bound included."
        PRD 3.8: "Fourth, `expedite_fee_cents` is `subtotal_cents` multiplied by that tier percentage and rounded half up to whole cents when `expedite` is true, and exactly 0 when it is false."

        Design: Difficulty/combinatorial_formula/upgrade_cost_tier_keyed_on_subtotal_not_total
        """
        state = self._expedited_order(api)
        order = state["order"]

        assert_upgrade_cost(
            order,
            delta_mbps=200,
            subtotal_cents=EXPEDITED_SUBTOTAL_CENTS,
            expedite_fee_cents=EXPEDITED_FEE_CENTS,
            total_cost_cents=EXPEDITED_TOTAL_CENTS,
        )
        assert order["state"] == "DRAFT", (
            f"a new order is a draft, got {order['state']}"
        )
        assert order["origin"] == "MANUAL", (
            f"a planner-raised order is manual, got {order['origin']}"
        )
        assert order["expedite"] is True, "the order was raised as expedited"
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]), committed_mbps=200
        )
        assert_circuit_posture(
            read_circuit(api, state["circuit_id"]), bandwidth_mbps=100
        )

    def test_the_total_is_never_the_tier_key(self, api):
        """Keying the band on 537500 would have charged 494500, and it does not.

        PRD 3.8: "Fifth, `total_cost_cents` is `subtotal_cents` plus `expedite_fee_cents`."
        PRD 3.8: "The tier is never re-selected from `total_cost_cents`, and a later completed upgrade never restates the figures on an order created earlier."

        Design: Difficulty/combinatorial_formula/upgrade_cost_tier_keyed_on_subtotal_not_total
        """
        order = self._expedited_order(api)["order"]

        assert order["total_cost_cents"] != TIER_KEYED_ON_TOTAL_CENTS, (
            "the 0.15 band belongs to the total, which is not the tier key; "
            f"expected {EXPEDITED_TOTAL_CENTS}, got {order['total_cost_cents']}"
        )
        assert (
            order["total_cost_cents"]
            == order["subtotal_cents"] + order["expedite_fee_cents"]
        ), "the total is exactly the subtotal plus the fee"
        assert order["expedite_fee_cents"] * 4 == order["subtotal_cents"], (
            "the fee is a quarter of the subtotal, which is the band the subtotal "
            f"selects; got {order['expedite_fee_cents']} on {order['subtotal_cents']}"
        )


class TestCancellingReleasesOnlyTheMegabits:
    """Cancellation is a bandwidth compensation and deliberately nothing more."""

    def _submitted_order_under_pressure(self, api) -> dict:
        """Two high samples, then a submitted expedited order holding 200 Mbps."""
        state = build_wbf_circuit(api, "2026-08-05T01:00:00Z")
        record_reading(
            api, state["circuit_id"], "2026-08-05T01:00:00Z", 95.00, direction="EGRESS"
        )
        advance_clock(api, "2026-08-05T01:05:00Z")
        record_reading(
            api, state["circuit_id"], "2026-08-05T01:05:00Z", 96.00, direction="EGRESS"
        )

        order = create_manual_upgrade_order(
            api,
            state["circuit_id"],
            300,
            read_circuit(api, state["circuit_id"])["version"],
            expedite=True,
            user_id=CAPACITY_PLANNER_USER_ID,
        )
        state["order"] = submit_upgrade_order(
            api, order["id"], user_id=CAPACITY_PLANNER_USER_ID
        )
        state["order_id"] = order["id"]
        return state

    def _cancel(self, api, order_id: str) -> dict:
        return validate_success(
            api.cancel_upgrade_order(
                order_id,
                order_cancel_payload("budget deferred to next quarter"),
                VENDOR_MANAGER_HEADERS,
            )
        )["data"]

    def test_cancelling_returns_exactly_the_committed_megabits(self, api):
        """The 200 Mbps the order added is the 200 Mbps the cancellation gives back.

        PRD 3.8: "Cancellation is the compensating action, optionally recording a `cancel_reason`; it subtracts exactly the `delta_mbps` that was added at creation, restoring `committed_upgrade_mbps` to its pre-order value, and deliberately leaves both `bandwidth_mbps` and `capacity_state` alone, since abandoning an upgrade does not relieve the utilisation pressure that prompted it."
        PRD 2.10: "`committed_upgrade_mbps` is the sum of `delta_mbps` over upgrade orders on that carrier's circuits whose `state` is `DRAFT`, `SUBMITTED`, `APPROVED` or `IN_PROGRESS`; orders in `COMPLETED` or `CANCELLED` are outside the committed set."

        Design: Difficulty/compensating_invariant/upgrade_order_cancel_restores_committed_bandwidth_not_circuit_capacity
        """
        state = self._submitted_order_under_pressure(api)
        assert state["order"]["state"] == "SUBMITTED", (
            f"the order is an open commitment, got {state['order']['state']}"
        )
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]), committed_mbps=200
        )

        cancelled = self._cancel(api, state["order_id"])

        assert cancelled["state"] == "CANCELLED", (
            f"the order is withdrawn, got {cancelled['state']}"
        )
        assert cancelled["cancel_reason"] == "budget deferred to next quarter", (
            "the recorded reason survives on the cancelled order"
        )
        assert_upgrade_cost(
            cancelled,
            delta_mbps=200,
            subtotal_cents=EXPEDITED_SUBTOTAL_CENTS,
            expedite_fee_cents=EXPEDITED_FEE_CENTS,
            total_cost_cents=EXPEDITED_TOTAL_CENTS,
        )
        assert_carrier_ledger(read_carrier(api, state["carrier_id"]), committed_mbps=0)

    def test_the_cancellation_leaves_the_pressure_and_the_money_alone(self, api):
        """The circuit is neither widened nor calmed, and no credit money moved.

        PRD 3.8: "The circuit's `capacity_state` is then re-derived from that counter alone: `UPGRADE_REQUIRED` once the counter has reached 3, `WATCH` while it stands at 1 or 2, and `NORMAL` when it is 0."
        PRD 3.8: "Cancellation is the compensating action, optionally recording a `cancel_reason`; it subtracts exactly the `delta_mbps` that was added at creation, restoring `committed_upgrade_mbps` to its pre-order value, and deliberately leaves both `bandwidth_mbps` and `capacity_state` alone, since abandoning an upgrade does not relieve the utilisation pressure that prompted it."

        Design: Difficulty/compensating_invariant/upgrade_order_cancel_restores_committed_bandwidth_not_circuit_capacity
        """
        state = self._submitted_order_under_pressure(api)
        self._cancel(api, state["order_id"])

        assert_circuit_posture(
            read_circuit(api, state["circuit_id"]),
            bandwidth_mbps=100,
            capacity_state="WATCH",
            consecutive_high_readings=2,
        )
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]),
            committed_mbps=0,
            exposure_cents=0,
        )


class TestThirdConsecutiveHighReading:
    """The third consecutive high sample raises the order nobody asked for."""

    def test_the_third_high_sample_drafts_an_order_at_the_next_rung(self, api):
        """Two samples leave the circuit watching; the third orders 200 Mbps for 340000.

        PRD 3.8: "The bandwidth ladder is 100, 200, 300, 500, 1000 and 10000 Mbps, and the target chosen is the lowest rung strictly greater than the circuit's current `bandwidth_mbps`."
        PRD 3.8: "Otherwise the order is created in `DRAFT` with `origin` `AUTO_THRESHOLD`, `expedite` false, `target_bandwidth_mbps` set to that rung, and `created_by_user_id` holding the literal string `system`, since no human raised it."
        PRD 3.8: "Its `delta_mbps` immediately joins the carrier's `committed_upgrade_mbps`."

        Design: Corner/calculations/corner_third_consecutive_high_reading_orders_next_ladder_rung
        """
        state = build_pft_capacity_circuit(api, "2026-08-22T00:00:00Z")
        circuit_id = state["circuit_id"]

        record_reading(api, circuit_id, "2026-08-22T00:05:00Z", 85.00)
        record_reading(api, circuit_id, "2026-08-22T00:10:00Z", 82.50)

        assert_circuit_posture(
            read_circuit(api, circuit_id),
            capacity_state="WATCH",
            consecutive_high_readings=2,
        )
        _, before = _list_orders(api, circuit_id)
        assert_page(before, total_count=0)

        third = record_reading(api, circuit_id, "2026-08-22T00:15:00Z", 90.00)
        assert third["threshold_state"] == "HIGH", (
            f"90.00 is above the bound, got {third['threshold_state']}"
        )
        assert_circuit_posture(
            read_circuit(api, circuit_id),
            capacity_state="UPGRADE_REQUIRED",
            consecutive_high_readings=3,
            bandwidth_mbps=100,
        )

        rows, meta = _list_orders(api, circuit_id, {"origin": "AUTO_THRESHOLD"})
        assert_page(meta, total_count=1)
        order = rows[0]
        assert order["state"] == "DRAFT", (
            f"the synthesised order is a draft, got {order['state']}"
        )
        assert order["origin"] == "AUTO_THRESHOLD", (
            f"the order records why it exists, got {order['origin']}"
        )
        assert order["created_by_user_id"] == SYSTEM_USER_ID, (
            f"no human raised it, got {order['created_by_user_id']!r}"
        )
        assert order["expedite"] is False, "an automatic order is never expedited"
        assert order["target_bandwidth_mbps"] == 200, (
            f"200 is the lowest rung above 100, got {order['target_bandwidth_mbps']}"
        )
        assert_upgrade_cost(
            order,
            delta_mbps=100,
            subtotal_cents=340000,
            expedite_fee_cents=0,
            total_cost_cents=340000,
        )
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]), committed_mbps=100
        )


class TestReadingsMustArriveInOrder:
    """The accumulator has no history to reorder, so late samples are refused."""

    def test_an_earlier_or_equal_sample_instant_is_refused(self, api):
        """Both the backdated sample and the tying sample are rejected outright.

        PRD 3.8: "Utilisation telemetry arrives one reading at a time, and the platform deliberately keeps no re-sortable history: each reading carries a `sample_at` that must be strictly later than the `sample_at` of the circuit's most recent reading, and a reading that arrives out of order is refused with `ERR_READING_OUT_OF_ORDER` rather than being inserted into the past."
        PRD 3.8: "Readings may be listed per circuit and narrowed by `direction` and `threshold_state`."

        Design: Corner/validations/corner_capacity_reading_out_of_order_rejected
        """
        state = build_pft_capacity_circuit(api, "2026-08-26T00:00:00Z")
        circuit_id = state["circuit_id"]
        record_reading(api, circuit_id, "2026-08-26T00:10:00Z", 85.00)

        validate_error(
            api.create_capacity_reading(
                circuit_id,
                capacity_reading_payload("2026-08-26T00:05:00Z", 90.00),
                CAPACITY_PLANNER_HEADERS,
            ),
            ApiErrorId.ERR_READING_OUT_OF_ORDER,
        )
        validate_error(
            api.create_capacity_reading(
                circuit_id,
                capacity_reading_payload(
                    "2026-08-26T00:10:00Z", 91.00, direction="EGRESS"
                ),
                CAPACITY_PLANNER_HEADERS,
            ),
            ApiErrorId.ERR_READING_OUT_OF_ORDER,
        )

        rows, meta = validate_paginated(
            api.list_capacity_readings(circuit_id, CAPACITY_PLANNER_HEADERS)
        )
        assert_page(meta, total_count=1)
        assert_utilization_pct(rows[0]["utilization_pct"], 85.00)
        assert_circuit_posture(
            read_circuit(api, circuit_id),
            capacity_state="WATCH",
            consecutive_high_readings=1,
        )


class TestUpgradeOrderLifecycle:
    """Only the completion step touches the circuit the order was raised against."""

    def test_completion_alone_raises_the_bandwidth_and_releases_the_commitment(
        self, api
    ):
        """Draft, submitted, approved and in-progress all hold the commitment open.

        PRD 3.8: "The order lifecycle then runs `DRAFT → SUBMITTED → APPROVED → IN_PROGRESS → COMPLETED`, with cancellation available from any of the first three."
        PRD 3.8: "`IN_PROGRESS` keeps the commitment open; `COMPLETED` is where the estate actually changes — the circuit's `bandwidth_mbps` is raised to the order's `target_bandwidth_mbps`, its `consecutive_high_readings` resets to 0 and its `capacity_state` to `NORMAL`, and the order's `delta_mbps` is released from the carrier's `committed_upgrade_mbps` because `COMPLETED` sits outside the committed set."
        PRD 3.8: "Approval is a `VendorManager` act and enforces the separation of Section 2.11: the acting `X-User-ID` must differ from the order's `created_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`, which also means an `AUTO_THRESHOLD` order — created by `system` — can always be approved by any authorised manager."

        Design: Corner/endpoints/corner_upgrade_order_lifecycle_completes_and_raises_bandwidth
        """
        state = build_pft_capacity_circuit(api, "2026-09-02T00:00:00Z")
        circuit_id = state["circuit_id"]
        record_reading(api, circuit_id, "2026-09-02T00:05:00Z", 88.00)

        order = create_manual_upgrade_order(
            api,
            circuit_id,
            300,
            read_circuit(api, circuit_id)["version"],
            expedite=False,
            user_id=CAPACITY_PLANNER_USER_ID,
        )
        assert order["state"] == "DRAFT", (
            f"the manual order starts as a draft, got {order['state']}"
        )
        assert order["origin"] == "MANUAL", "a planner raised it by hand"
        assert order["created_by_user_id"] == CAPACITY_PLANNER_USER_ID, (
            "the acting planner is recorded as the creator"
        )
        assert_upgrade_cost(
            order,
            delta_mbps=200,
            subtotal_cents=EXPEDITED_SUBTOTAL_CENTS,
            expedite_fee_cents=0,
            total_cost_cents=EXPEDITED_SUBTOTAL_CENTS,
        )
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]), committed_mbps=200
        )
        assert_circuit_posture(read_circuit(api, circuit_id), bandwidth_mbps=100)

        submit_upgrade_order(api, order["id"], user_id=CAPACITY_PLANNER_USER_ID)
        approved = approve_upgrade_order(
            api, order["id"], user_id=VENDOR_MANAGER_USER_ID
        )
        assert approved["state"] == "APPROVED", (
            f"the manager approved the spend, got {approved['state']}"
        )
        assert approved["approved_by_user_id"] == VENDOR_MANAGER_USER_ID, (
            "the approving manager is stamped, and differs from the creator"
        )
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]), committed_mbps=200
        )

        set_order_state(api, order["id"], "IN_PROGRESS")
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]), committed_mbps=200
        )
        assert_circuit_posture(read_circuit(api, circuit_id), bandwidth_mbps=100)

        completed = set_order_state(api, order["id"], "COMPLETED")

        assert completed["state"] == "COMPLETED", (
            f"the upgrade is done, got {completed['state']}"
        )
        assert_upgrade_cost(
            completed,
            subtotal_cents=EXPEDITED_SUBTOTAL_CENTS,
            total_cost_cents=EXPEDITED_SUBTOTAL_CENTS,
        )
        assert_circuit_posture(
            read_circuit(api, circuit_id),
            bandwidth_mbps=300,
            capacity_state="NORMAL",
            consecutive_high_readings=0,
        )
        assert_carrier_ledger(read_carrier(api, state["carrier_id"]), committed_mbps=0)


class TestVendorReviewOnACleanPeriod:
    """An empty period scores a perfect 100, which makes replacement indefensible."""

    def test_a_clean_period_scores_one_hundred_and_only_retain_is_defensible(
        self, api
    ):
        """Every penalty term is zero, so the score is 100.00 rather than an empty zero.

        PRD 3.8: "The credit side gathers the carrier's claims whose `state` is `ACKNOWLEDGED` or `PAID` and whose `submitted_at` falls in the period; their `credit_amount_cents` are summed and divided by the total `mrc_cents` of every circuit of that carrier whose `created_at` is before `period_end`, giving `credit_ratio` rounded half up to four decimals — or exactly 0.0 when that revenue base is zero, which is the division-guard rather than an error."
        PRD 3.8: "The raw score starts at 100 and subtracts three penalties: `credit_ratio` multiplied by 100 and then by 2; `chronic_circuit_count` multiplied by 5; and the smaller of `mttr_minutes` divided by 60 and the cap of 10 hours, multiplied by 3 — so a carrier that takes a week per repair is penalised no more heavily than one that takes ten hours."
        PRD 3.8: "`REPLACE` requires both a `net_performance_score` strictly below 60 and a `chronic_circuit_count` of at least 1 — a bad score alone is not enough, there must be a chronic circuit to replace — otherwise `ERR_REPLACEMENT_NOT_JUSTIFIED`; it likewise sets `watchlist_state` to `WATCHLIST`, and then drives the estate cascade in three linked steps."
        PRD 3.8: "`RETAIN` requires `net_performance_score` to be at or above 60, otherwise `ERR_RETAIN_NOT_JUSTIFIED`, and beyond stamping the decision it changes nothing else in the estate."

        Design: Corner/calculations/corner_vendor_review_on_clean_period_scores_one_hundred
        """
        advance_clock(api, "2026-09-01T00:00:00Z")
        carrier = create_carrier(api)
        create_circuit(api, carrier["id"])

        review = create_vendor_review(
            api, carrier["id"], "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"
        )

        assert_credit_ratio(review["credit_ratio"], 0.0)
        assert_minutes(review["mttr_minutes"], 0.00, "mttr_minutes")
        assert review["chronic_circuit_count"] == 0, (
            f"no circuit is chronic, got {review['chronic_circuit_count']}"
        )
        assert_score(review["net_performance_score"], 100.00)
        assert review["decision"] == "PENDING", (
            f"a new review awaits its decision, got {review['decision']}"
        )

        validate_error(
            api.decide_vendor_review(
                review["id"],
                review_decide_payload(
                    "REPLACE", justification="gut feeling about this carrier"
                ),
                VENDOR_MANAGER_HEADERS,
            ),
            ApiErrorId.ERR_REPLACEMENT_NOT_JUSTIFIED,
        )

        retained = decide_vendor_review(
            api,
            review["id"],
            "RETAIN",
            justification="clean period, no credits and no chronic circuits",
        )
        assert retained["decision"] == "RETAIN", (
            f"retaining a perfect scorer is defensible, got {retained['decision']}"
        )
        assert retained["decided_by_user_id"] == VENDOR_MANAGER_USER_ID, (
            "the deciding manager is recorded"
        )
        assert_carrier_ledger(
            read_carrier(api, carrier["id"]), watchlist_state="ACTIVE"
        )

        _, meta = validate_paginated(
            api.list_carrier_vendor_reviews(
                carrier["id"], VENDOR_MANAGER_HEADERS, {"decision": "RETAIN"}
            )
        )
        assert_page(meta, total_count=1)
