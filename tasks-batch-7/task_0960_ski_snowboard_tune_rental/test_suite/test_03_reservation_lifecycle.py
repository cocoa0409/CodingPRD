"""Reservation lifecycle: parallel payment/fulfillment axes, confirm, cancel,
overdue auto-transition, pickup/close gating, and deposit floor."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_item,
    assert_deposit_conservation,
    confirm,
    make_customer,
    make_customer_headers,
    make_equipment_item,
    make_reservation,
    set_clock,
    setup_assigned_reservation,
    setup_confirmed_reservation,
    setup_picked_up_reservation,
    setup_returned_reservation,
    validate_error,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]
TECH = TEST_USERS["technician_headers"]


class TestParallelPaymentFulfillmentAxes:
    def test_full_lifecycle_moves_both_axes_in_lockstep(self, api):
        """PRD Booking a Rental: "A new reservation carries two independent status axes
        that evolve in parallel: `fulfillment_status`, starting at `DRAFT`, and
        `payment_status`, starting at `UNPAID`."
        PRD From Confirm to Close: "Closing moves fulfillment to `CLOSED` and payment
        from `CAPTURED` to `SETTLED`"

        Design: Difficulty/non_linear_state_machine/reservation_parallel_payment_fulfillment
        """
        ctx = setup_assigned_reservation()
        confirmed = confirm(ctx["reservation"], 2400)
        assert confirmed["fulfillment_status"] == "CONFIRMED"
        assert confirmed["payment_status"] == "AUTHORIZED"

        set_clock("2026-12-10T09:00:00Z")
        picked = validate_success(api.pickup_reservation(confirmed["id"], FD))
        assert picked["fulfillment_status"] == "ACTIVE"
        assert picked["payment_status"] == "AUTHORIZED"

        set_clock("2026-12-12T17:00:00Z")
        returned = validate_success(api.return_reservation(confirmed["id"], FD))
        assert returned["fulfillment_status"] == "RETURNED"
        assert returned["payment_status"] == "CAPTURED"

        validate_success(api.inspect_equipment_item(ctx["units"][0]["id"],
                                                    {"outcome": "PASS"}, TECH))
        closed = validate_success(api.close_reservation(confirmed["id"], FD))
        assert closed["fulfillment_status"] == "CLOSED"
        assert closed["payment_status"] == "SETTLED"
        assert_deposit_conservation(closed)

    def test_cancel_voids_payment_without_activation(self, api):
        """PRD From Confirm to Close: "Cancellation unwinds a reservation still in
        `DRAFT` or `CONFIRMED`. Fulfillment becomes `CANCELLED`; if payment had been
        `AUTHORIZED` it becomes `VOIDED`."

        Design: Difficulty/non_linear_state_machine/reservation_parallel_payment_fulfillment
        """
        ctx = setup_confirmed_reservation(start_date="2027-01-05", end_date="2027-01-06",
                                          deposit_authorized_cents=1600)
        reservation = ctx["reservation"]
        headers = make_customer_headers(ctx["customer"]["id"])
        cancelled = validate_success(api.cancel_reservation(reservation["id"], headers))
        # Payment axis moved AUTHORIZED -> VOIDED while fulfillment never entered ACTIVE.
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "VOIDED"
        assert_deposit_conservation(cancelled)
        assert cancelled["deposit_released_cents"] == 1600


class TestOverdueAutoTransition:
    def test_clock_past_end_date_flips_active_to_overdue(self, api):
        """PRD From Confirm to Close: "when the logical clock moves past the
        reservation's `end_date` while fulfillment is still `ACTIVE` — whether noticed
        by the clock sweep or on read — the reservation slides into `OVERDUE`, with
        payment untouched."

        Design: Corner/state_machines/reservation_overdue_auto_transition_on_clock
        """
        ctx = setup_picked_up_reservation()
        set_clock("2026-12-13T00:00:00Z")
        data = validate_success(api.get_reservation(ctx["reservation"]["id"], FD))
        assert data["fulfillment_status"] == "OVERDUE"
        assert data["payment_status"] == "AUTHORIZED"


class TestConfirmRules:
    def test_confirm_response_immediately_consistent(self, api):
        """PRD Hierarchical Consistency and Cascading Change: "Every such cascade is
        atomic with the triggering request — all side effects are applied and visible
        in the response and in subsequent reads"
        PRD From Confirm to Close: "Confirmation moves fulfillment from `DRAFT` to
        `CONFIRMED` and payment from `UNPAID` to `AUTHORIZED`, freezes the quote as the
        confirmed figure, and increments the reservation's `version`."

        Design: Corner/consistency_model/confirm_response_immediately_consistent
        """
        ctx = setup_assigned_reservation()
        before = ctx["reservation"]
        confirmed = confirm(before, 5000)
        assert confirmed["fulfillment_status"] == "CONFIRMED"
        assert confirmed["payment_status"] == "AUTHORIZED"
        assert confirmed["quoted_total_cents"] == 12000
        assert confirmed["deposit_minimum_cents"] == 2400
        assert confirmed["version"] > before["version"]

    def test_deposit_below_minimum_rejected_exact_minimum_accepted(self, api):
        """PRD From Confirm to Close: "`deposit_minimum_cents` is computed as twenty
        percent of the current `quoted_total_cents`, rounded half-up, and a hold below
        that floor is rejected with `ERR_DEPOSIT_BELOW_MINIMUM`. The boundary is
        inclusive — a hold exactly equal to the minimum is accepted."

        Design: Corner/validations/confirm_deposit_below_minimum_rejected
        """
        ctx = setup_assigned_reservation()
        reservation = ctx["reservation"]
        headers = make_customer_headers(ctx["customer"]["id"])

        resp = api.confirm_reservation(reservation["id"],
                                       {"deposit_authorized_cents": 2300}, headers)
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_BELOW_MINIMUM)
        still = validate_success(api.get_reservation(reservation["id"], FD))
        assert still["fulfillment_status"] == "DRAFT"

        confirmed = validate_success(api.confirm_reservation(
            reservation["id"], {"deposit_authorized_cents": 2400}, headers))
        assert confirmed["fulfillment_status"] == "CONFIRMED"

    def test_confirm_cancelled_reservation_state_error_beats_deposit_floor(self, api):
        """PRD Request Validation Precedence: "Sixth, the target resource's state is
        checked against the requested transition — including terminal-state lockdown —
        yielding `ERR_INVALID_STATE`. Only after all six gates pass do the temporal and
        business rules of §3 apply, in the relative order stated with each workflow."

        Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_state_beats_fiscal
        """
        ctx = setup_assigned_reservation()
        reservation = ctx["reservation"]
        headers = make_customer_headers(ctx["customer"]["id"])
        validate_success(api.cancel_reservation(reservation["id"], headers))

        resp = api.confirm_reservation(reservation["id"],
                                       {"deposit_authorized_cents": 1}, headers)
        # Deposit 1 also violates the 2400 floor, but the state gate runs first.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_confirm_cancelled_reservation_returns_409_and_leaves_state(self, api):
        """PRD From Confirm to Close: "Both `CLOSED` and `CANCELLED` are terminal for
        fulfillment; `SETTLED` and `VOIDED` are terminal for payment."
        PRD Request Validation Precedence: "Sixth, the target resource's state is
        checked against the requested transition — including terminal-state lockdown —
        yielding `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_state_beats_fiscal
        """
        ctx = setup_assigned_reservation()
        reservation = ctx["reservation"]
        headers = make_customer_headers(ctx["customer"]["id"])
        validate_success(api.cancel_reservation(reservation["id"], headers))

        resp = api.confirm_reservation(reservation["id"],
                                       {"deposit_authorized_cents": 1}, headers)
        assert resp.status_code == 409
        body = resp.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE
        after = validate_success(api.get_reservation(reservation["id"], FD))
        assert after["fulfillment_status"] == "CANCELLED"


class TestDateRangeValidation:
    def test_end_date_before_start_date_rejected(self, api):
        """PRD Booking a Rental: "The end date must not precede the start date — a
        reservation whose `end_date` falls before its `start_date` is rejected with
        `ERR_DATE_RANGE_INVALID`"

        Design: Corner/validations/reservation_end_before_start_returns_422
        """
        customer = make_customer()
        headers = make_customer_headers(customer["id"])
        resp = api.create_reservation(
            {"customer_id": customer["id"], "start_date": "2026-12-12",
             "end_date": "2026-12-10", "pickup_method": "SHOP"},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_DATE_RANGE_INVALID)


class TestPickupAndCloseGating:
    def test_pickup_blocked_while_queued_item_remains(self, api):
        """PRD From Confirm to Close: "Handing out the gear is a `FrontDesk` action on
        a `CONFIRMED` reservation, and here queued lines do block: if any line remains
        `QUEUED` the pickup is rejected with `ERR_ITEMS_UNASSIGNED`."

        Design: Corner/validations/pickup_with_queued_item_returns_items_unassigned
        """
        customer = make_customer()
        make_equipment_item()  # only one unit in the fleet
        reservation = make_reservation(customer)
        item1 = add_item(reservation)
        item2 = add_item(reservation)
        assigned = validate_success(api.assign_reservation_item(item1["id"], {}, FD))
        assert assigned["status"] == "ASSIGNED"
        # Empty eligible pool: the request still succeeds but the line stays QUEUED.
        queued = validate_success(api.assign_reservation_item(item2["id"], {}, FD))
        assert queued["status"] == "QUEUED"

        confirmed = confirm(reservation, 2400)
        assert confirmed["fulfillment_status"] == "CONFIRMED"

        resp = api.pickup_reservation(reservation["id"], FD)
        validate_error(resp, ApiErrorId.ERR_ITEMS_UNASSIGNED)
        after = validate_success(api.get_reservation(reservation["id"], FD))
        assert after["fulfillment_status"] == "CONFIRMED"

    def test_close_blocked_while_unit_awaits_inspection(self, api):
        """PRD From Confirm to Close: "A reservation in `RETURNED` fulfillment may be
        closed only when none of its units remains `OUT` or `AWAITING_INSPECTION`;
        attempting to close while a unit still awaits inspection is rejected with
        `ERR_ITEMS_PENDING_INSPECTION`."

        Design: Corner/validations/close_with_pending_inspection_returns_409
        """
        ctx = setup_returned_reservation()
        reservation = ctx["reservation"]
        assert reservation["fulfillment_status"] == "RETURNED"

        resp = api.close_reservation(reservation["id"], FD)
        validate_error(resp, ApiErrorId.ERR_ITEMS_PENDING_INSPECTION)
        after = validate_success(api.get_reservation(reservation["id"], FD))
        assert after["fulfillment_status"] == "RETURNED"
