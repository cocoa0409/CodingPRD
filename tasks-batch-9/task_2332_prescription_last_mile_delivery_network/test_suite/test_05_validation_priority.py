"""Which rule speaks when two of them are violated at once.

The ladder is a contract, not an implementation note: state precedes fiscal
policy, and patient safety precedes scheduling. Each pair is followed by a proof
that the losing rule is genuinely live rather than absent.
"""

import pytest

from test_helpers import (
    OPS_HEADERS,
    build_courier,
    build_network,
    build_ready_order,
    build_window,
    factories,
    read_delivery,
    read_order,
    read_window,
    reserve_delivery,
    set_clock,
    utc_ts,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD_ORDER = {
    "rx_line_count": 2,
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


@pytest.fixture
def held_order_under_a_short_medicaid_pool(api):
    """A Medicaid order that is both in the wrong state and underfunded.

    The pool holds 312 cents against a 313-cent member share, and the order was
    released and then pulled back, so both rules are violated at once.
    """
    net = build_network(
        api,
        plan={
            "name": "State Care Plus",
            "payer_type": "MEDICAID",
            "member_cost_share_pct": 0.2,
        },
        grant={"grant_budget_cents": 312, "per_delivery_cap_cents": 400},
    )
    order = build_ready_order(api, net, **STANDARD_ORDER)
    validate_success(api.hold_order(order["id"], headers=net.pharmacy_headers))
    window = build_window(api, net.zone["id"], capacity_slots=1)
    return net, order, window


def _reserve(api, net, order, window):
    return api.create_delivery(
        factories.delivery_payload(
            order["id"], window["id"], read_window(api, window["id"])["version"]
        ),
        headers=net.pharmacy_headers,
    )


class TestOrderStateBeatsGrantCoverage:
    """"Being last in the ladder, this rule deliberately loses to every state
    check: an order that is not `READY` reports `ERR_ORDER_NOT_READY` even when
    the grant is also short."
    """

    def test_order_state_is_reported_ahead_of_the_medicaid_coverage_shortfall(
        self, api, held_order_under_a_short_medicaid_pool
    ):
        """The widest span in the ladder resolves in favour of the state check.

        "Being last in the ladder, this rule deliberately loses to every state
        check: an order that is not `READY` reports `ERR_ORDER_NOT_READY` even
        when the grant is also short."

        Design: Difficulty/priority_pair_validation_conflict/order_state_beats_grant_coverage_shortfall
        """
        net, order, window = held_order_under_a_short_medicaid_pool
        validate_error(_reserve(api, net, order, window), "ERR_ORDER_NOT_READY", 409)

        held = read_order(api, order["id"])
        assert held["status"] == "INTAKE"
        assert held["hold_count"] == 1

    def test_the_rejected_reservation_left_no_row_slot_or_commitment_behind(
        self, api, held_order_under_a_short_medicaid_pool
    ):
        """A refused reservation writes nothing anywhere.

        "The window's `reserved_slots` rises by one and it flips to `FULL` if
        that reaches `capacity_slots`; the order moves to `DISPATCHED`; and the
        bill is built."

        Design: Difficulty/priority_pair_validation_conflict/order_state_beats_grant_coverage_shortfall
        """
        net, order, window = held_order_under_a_short_medicaid_pool
        validate_error(_reserve(api, net, order, window), "ERR_ORDER_NOT_READY", 409)

        _rows, meta = validate_paginated(
            api.list_deliveries(OPS_HEADERS, order_id=order["id"])
        )
        assert meta["total_count"] == 0
        assert read_window(api, window["id"])["reserved_slots"] == 0
        assert validate_success(
            api.get_plan_grant(net.grant["id"], headers=net.plan_admin_headers)
        )["committed_cents"] == 0

    def test_the_coverage_rule_fires_once_the_state_objection_is_cleared(
        self, api, held_order_under_a_short_medicaid_pool
    ):
        """Proof the losing rule is live: release the order and it speaks.

        "Second — and only for a `MEDICAID` payer — if that eligible amount is
        less than the gross share, the request is rejected outright with
        `ERR_GRANT_COVERAGE_INSUFFICIENT`: a Medicaid member may not be billed
        any residue, so a pool that can only partly fund the share cannot be used
        at all."

        Design: Difficulty/priority_pair_validation_conflict/order_state_beats_grant_coverage_shortfall
        """
        net, order, window = held_order_under_a_short_medicaid_pool
        validate_error(_reserve(api, net, order, window), "ERR_ORDER_NOT_READY", 409)

        validate_success(api.mark_order_ready(order["id"], headers=net.pharmacy_headers))
        validate_error(
            _reserve(api, net, order, window), "ERR_GRANT_COVERAGE_INSUFFICIENT", 409
        )


@pytest.fixture
def cold_bag_past_its_window(api):
    """A cold controlled bag reserved in good time, then left behind the clock.

    No routing sweep runs, so the window's status flag is untouched and the
    elapsed condition can only come from the clock comparison.
    """
    net = build_network(api)
    order = build_ready_order(api, net, **COLD_CII_ORDER)
    window = build_window(api, net.zone["id"], capacity_slots=1)
    delivery = reserve_delivery(api, net, order["id"], window["id"])

    uninsulated = build_courier(
        api, display_name="Nia Fell", cold_chain_equipped=False, controlled_certified=True
    )
    certified = build_courier(api, display_name="Ray Ortiz")
    set_clock(api, utc_ts(3, 16, 30))
    return net, window, delivery, uninsulated, certified


class TestCourierSafetyBeatsWindowElapsed:
    """"Placed deliberately ahead of rung 34: an uncertified handoff is a
    patient-safety fact, a late window is only a scheduling fact."
    """

    def test_uninsulated_courier_is_refused_before_the_late_window_is_mentioned(
        self, api, cold_bag_past_its_window
    ):
        """Safety outranks scheduling on the dispatch endpoint.

        "Placed deliberately ahead of rung 34: an uncertified handoff is a
        patient-safety fact, a late window is only a scheduling fact."

        Design: Difficulty/priority_pair_validation_conflict/cold_chain_courier_safety_beats_window_elapsed
        """
        _net, window, delivery, uninsulated, _certified = cold_bag_past_its_window
        response = api.dispatch_delivery(
            delivery["id"],
            headers=OPS_HEADERS,
            payload=factories.dispatch_payload(uninsulated["id"]),
        )
        validate_error(response, "ERR_COURIER_NOT_COLD_CERTIFIED", 409)

        # The single slot was taken by this delivery's own reservation, so the
        # window stands at FULL both before and after the refused dispatch; what
        # matters is that no sweep has driven it to CLOSED.
        assert read_window(api, window["id"])["status"] == "FULL"
        after = read_delivery(api, delivery["id"])
        assert after["custody_status"] == "QUEUED"
        assert after["courier_id"] is None
        _rows, meta = validate_paginated(
            api.list_courier_assignments(OPS_HEADERS, delivery_id=delivery["id"])
        )
        assert meta["total_count"] == 0

    def test_the_elapsed_window_rule_fires_once_the_courier_is_beyond_reproach(
        self, api, cold_bag_past_its_window
    ):
        """Proof the losing rule is live: a fully certified courier hits it.

        "The clock is at or after `last_attempt_at` plus the cooldown for the
        current rung" is not what bites here; instead: "The clock is earlier than
        the target window's `window_end`, and for a *new* reservation on a
        `SCHEDULED` window the clock is at or before `window_start` minus two
        hours — otherwise `ERR_WINDOW_ELAPSED`."

        Design: Difficulty/priority_pair_validation_conflict/cold_chain_courier_safety_beats_window_elapsed
        """
        _net, _window, delivery, _uninsulated, certified = cold_bag_past_its_window
        response = api.dispatch_delivery(
            delivery["id"],
            headers=OPS_HEADERS,
            payload=factories.dispatch_payload(certified["id"]),
        )
        validate_error(response, "ERR_WINDOW_ELAPSED", 409)

    def test_neither_rejected_dispatch_disclosed_any_patient_data(
        self, api, cold_bag_past_its_window
    ):
        """A refused handoff shows the courier nothing at all.

        "every release of that projection is logged as a `CourierDataDisclosure`
        row that cannot afterwards be edited" is only reached on success; here
        "the delivery stays `QUEUED`, and the request fails with
        `ERR_NO_ELIGIBLE_COURIER`" describes the sibling path, while a rejected
        override likewise leaves the audit trail empty.

        Design: Difficulty/priority_pair_validation_conflict/cold_chain_courier_safety_beats_window_elapsed
        """
        _net, _window, delivery, uninsulated, certified = cold_bag_past_its_window
        validate_error(
            api.dispatch_delivery(
                delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(uninsulated["id"]),
            ),
            "ERR_COURIER_NOT_COLD_CERTIFIED",
            409,
        )
        validate_error(
            api.dispatch_delivery(
                delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(certified["id"]),
            ),
            "ERR_WINDOW_ELAPSED",
            409,
        )
        _rows, meta = validate_paginated(
            api.list_delivery_disclosures(delivery["id"], OPS_HEADERS)
        )
        assert meta["total_count"] == 0
