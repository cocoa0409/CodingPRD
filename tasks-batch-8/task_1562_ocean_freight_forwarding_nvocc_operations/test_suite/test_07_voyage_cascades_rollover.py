"""Voyage lifecycle gates, blank-sailing cascades, rollover and delivery."""
from test_helpers import (
    ApiErrorId,
    create_active_contract,
    create_confirmed_booking,
    create_draft_freight_invoice,
    create_issued_freight_invoice,
    create_lcl_booking_payload,
    create_open_voyage,
    create_published_tariff,
    create_shipper,
    create_voyage_payload,
    setup_discharged_fcl_scenario,
    setup_lcl_lane,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BC, DOC_2, FC, OPS
from test_helpers.test_users import make_shipper_headers


class TestBookingCreateVoyageGate:
    def test_booking_create_blocked_by_voyage_not_open(self, api):
        """PRD §3.6: "Creation is gated. The voyage must be `BOOKING_OPEN`
        (otherwise `ERR_VOYAGE_NOT_OPEN`)."

        Design: Difficulty/cross_entity_state_dependency/booking_create_blocked_by_voyage_not_open
        """
        shipper = create_shipper(legal_name="ACME XG2")
        tariff = create_published_tariff()
        contract = create_active_contract()
        voyage = validate_success(
            api.create_voyage(create_voyage_payload(contract["id"]), OPS), 201)
        assert voyage["status"] == "SCHEDULED"

        res = api.create_booking(
            create_lcl_booking_payload(voyage["id"], tariff["id"]),
            make_shipper_headers(shipper["id"]))
        validate_error(res, ApiErrorId.ERR_VOYAGE_NOT_OPEN, expected_status=409)

    def test_booking_create_succeeds_after_open_for_booking(self, api):
        """PRD §3.6: "Creation is gated. The voyage must be `BOOKING_OPEN`
        (otherwise `ERR_VOYAGE_NOT_OPEN`)."
        PRD §3.5: "An `OperationsManager` opens a `SCHEDULED` voyage for
        booking, transitioning `SCHEDULED` to `BOOKING_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/booking_create_blocked_by_voyage_not_open
        """
        shipper = create_shipper(legal_name="ACME XG2")
        tariff = create_published_tariff()
        contract = create_active_contract()
        voyage = validate_success(
            api.create_voyage(create_voyage_payload(contract["id"]), OPS), 201)

        validate_error(
            api.create_booking(
                create_lcl_booking_payload(voyage["id"], tariff["id"]),
                make_shipper_headers(shipper["id"])),
            ApiErrorId.ERR_VOYAGE_NOT_OPEN)

        validate_success(api.open_voyage_for_booking(voyage["id"], OPS), 200)
        booking = validate_success(
            api.create_booking(
                create_lcl_booking_payload(voyage["id"], tariff["id"]),
                make_shipper_headers(shipper["id"])),
            201)
        assert booking["status"] == "QUOTED", (
            "the identical payload succeeds once the voyage is BOOKING_OPEN"
        )


class TestBlankSailingCascade:
    def _setup_booked_with_bl_and_invoice(self, api):
        from test_helpers import create_active_bond, create_draft_bl, issue_bl
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        create_active_bond()
        bl = issue_bl(create_draft_bl(booking["id"])["id"])
        invoice = create_draft_freight_invoice(booking["id"])
        return ctx, booking, bl, invoice

    def test_blank_sailing_rolls_confirmed_booking(self, api):
        """PRD §3.5: "A voyage in `SCHEDULED` or `BOOKING_OPEN` may instead be
        declared a blank sailing, transitioning directly to `BLANKED`. The
        blank-sailing cascade mirrors the departure cascade for bookings that
        have not yet loaded: bookings in `CONFIRMED`, `DOCUMENTATION_CLEARED`,
        or `LOADED` transition to `ROLLED` with `rolled_reason` set to
        `BLANK_SAILING` and `rollover_count` incremented by one (again capped
        at 2, with excesses going to `CANCELLED`)."

        Design: Difficulty/transitive_cascade/blank_sailing_cascade_depth4
        """
        ctx, booking, _bl, _invoice = self._setup_booked_with_bl_and_invoice(api)

        blanked = validate_success(api.blank_voyage(ctx["voyage"]["id"], OPS), 200)
        assert blanked["status"] == "BLANKED"

        after = validate_success(api.get_booking(booking["id"], OPS), 200)
        assert after["status"] == "ROLLED"
        assert after["rolled_reason"] == "BLANK_SAILING"
        assert after["rollover_count"] == 1

    def test_blank_sailing_cascade_voids_bl_invoice_and_exposure(self, api):
        """PRD §3.5: "each rolled booking's bill of lading in `DRAFT`,
        `ISSUED`, `AMENDMENT_PENDING`, or `SURRENDERED` is `VOIDED`, its DRAFT
        FREIGHT invoices are `VOID`, and its container assignments in
        `STUFFED` or `GATED_IN` are `CANCELLED`."
        PRD §3.5: "Voided DRAFT invoices drop out of both shipper
        credit-exposure variants as the recomputation runs."

        Design: Difficulty/transitive_cascade/blank_sailing_cascade_depth4
        """
        ctx, booking, bl, invoice = (
            self._setup_booked_with_bl_and_invoice(api))

        validate_success(api.blank_voyage(ctx["voyage"]["id"], OPS), 200)

        bl_after = validate_success(api.get_bill_of_lading(bl["id"], OPS), 200)
        assert bl_after["status"] == "VOIDED", (
            "ISSUED B/L voided by the roll cascade, not by a direct call"
        )
        inv_after = validate_success(api.get_invoice(invoice["id"], OPS), 200)
        assert inv_after["status"] == "VOID", (
            "DRAFT FREIGHT invoice voided by the same cascade"
        )
        shipper = validate_success(api.get_shipper(ctx["shipper"]["id"], OPS), 200)
        assert shipper["credit_exposure_forward_cents"] == 0
        assert shipper["credit_exposure_posted_cents"] == 0


class TestRolloverCycle:
    def _setup_two_voyage_scenario(self, api):
        ctx = setup_lcl_lane()
        voyage2 = create_open_voyage(
            ctx["contract"]["id"], voyage_number="EG102",
            etd="2026-09-15T00:00:00Z", eta="2026-10-05T00:00:00Z")
        booking = create_confirmed_booking(ctx)
        return ctx, voyage2, booking

    def test_shipper_roll_enters_rolled_state(self, api):
        """PRD §3.7: "The roll action requires `rollover_count` to be below
        the cap of 2 (otherwise `ERR_ROLLOVER_LIMIT_EXCEEDED`) and a booking
        state of `CONFIRMED` or `DOCUMENTATION_CLEARED` (otherwise
        `ERR_BOOKING_INVALID_STATE`). On a successful shipper-initiated roll,
        the booking transitions to `ROLLED`, `rolled_reason` is set to
        `SHIPPER_REQUEST`, and `rollover_count` increments by one."

        Design: Difficulty/non_linear_state_machine/booking_rollover_cycle_confirmed_rolled_confirmed
        """
        ctx, _voyage2, booking = self._setup_two_voyage_scenario(api)
        rolled = validate_success(
            api.roll_booking(booking["id"],
                             make_shipper_headers(ctx["shipper"]["id"]),
                             reason="shipper schedule change"),
            200)
        assert rolled["status"] == "ROLLED"
        assert rolled["rollover_count"] == 1
        assert rolled["rolled_reason"] == "SHIPPER_REQUEST"

    def test_rebook_closes_cycle_with_fresh_quote_and_fee(self, api):
        """PRD §3.7: "On success the booking's `voyage_id` is replaced with
        `new_voyage_id`, the booking returns to `CONFIRMED`, and the estimate
        is recomputed according to the rollover variant: when `rolled_reason`
        is `SHIPPER_REQUEST` the estimate is the fresh quote against the new
        voyage and `pending_rollover_fee_cents` is increased by a 150000-cent
        rollover fee, which will surface as a `ROLLOVER_FEE` line on the
        booking's next FREIGHT invoice; when `rolled_reason` is
        `BLANK_SAILING` or `MISSED_DEPARTURE` (carrier-caused), the estimate
        is the **lesser** of the old estimate and the fresh quote, and no fee
        accrues."

        Design: Difficulty/non_linear_state_machine/booking_rollover_cycle_confirmed_rolled_confirmed
        """
        ctx, voyage2, booking = self._setup_two_voyage_scenario(api)
        validate_success(
            api.roll_booking(booking["id"],
                             make_shipper_headers(ctx["shipper"]["id"]),
                             reason="shipper schedule change"),
            200)

        rebooked = validate_success(
            api.rebook_booking(booking["id"], voyage2["id"], BC), 200)
        assert rebooked["status"] == "CONFIRMED", "cycle closed"
        assert rebooked["voyage_id"] == voyage2["id"]
        assert rebooked["estimated_freight_cents"] == 77400, (
            "SHIPPER_REQUEST variant reprices at the fresh quote"
        )
        assert rebooked["pending_rollover_fee_cents"] == 150000

    def test_rollover_cap_third_roll_rejected(self, api):
        """PRD §3.7: "The roll action requires `rollover_count` to be below
        the cap of 2 (otherwise `ERR_ROLLOVER_LIMIT_EXCEEDED`) and a booking
        state of `CONFIRMED` or `DOCUMENTATION_CLEARED` (otherwise
        `ERR_BOOKING_INVALID_STATE`)."

        Design: Corner/validations/rollover_cap_third_roll_rejected
        """
        ctx, voyage2, booking = self._setup_two_voyage_scenario(api)
        v1 = ctx["voyage"]["id"]

        first = validate_success(
            api.roll_booking(booking["id"], BC, reason="r1"), 200)
        assert first["rollover_count"] == 1
        validate_success(api.rebook_booking(booking["id"], voyage2["id"], BC), 200)

        second = validate_success(
            api.roll_booking(booking["id"], BC, reason="r2"), 200)
        assert second["rollover_count"] == 2
        validate_success(api.rebook_booking(booking["id"], v1, BC), 200)

        res = api.roll_booking(booking["id"], BC, reason="r3")
        validate_error(res, ApiErrorId.ERR_ROLLOVER_LIMIT_EXCEEDED,
                       expected_status=422)
        after = validate_success(api.get_booking(booking["id"], OPS), 200)
        assert after["status"] == "CONFIRMED"
        assert after["voyage_id"] == v1


class TestDeliverAndCloseGates:
    def test_deliver_before_arrival_rejected(self, api):
        """PRD §3.15: "A `BookingCoordinator` may deliver a booking in
        `ARRIVED` (any other state rejects with `ERR_BOOKING_INVALID_STATE`)."

        Design: Corner/state_machines/deliver_before_arrival_rejected
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)

        res = api.deliver_booking(booking["id"], BC)
        validate_error(res, ApiErrorId.ERR_BOOKING_INVALID_STATE,
                       expected_status=409)
        after = validate_success(api.get_booking(booking["id"], OPS), 200)
        assert after["status"] == "CONFIRMED"

    def test_voyage_close_blocked_while_bookings_open(self, api):
        """PRD §3.5: "From `ARRIVED` the voyage may be closed — but only when
        every booking on the voyage is in `DELIVERED` or `CANCELLED`,
        otherwise the close is rejected with `ERR_VOYAGE_HAS_OPEN_BOOKINGS`."
        PRD §3.15: "The booking must hold a bill of lading in `RELEASED`
        (otherwise `ERR_BL_NOT_RELEASED`). And if the booking's `terms` is
        `COLLECT`, every FREIGHT invoice of the booking must be `PAID`
        (otherwise `ERR_OUTSTANDING_BALANCE`)".

        Design: Corner/state_machines/voyage_close_blocked_while_bookings_open
        """
        ctx = setup_discharged_fcl_scenario()
        booking = ctx["booking"]
        assert validate_success(api.get_booking(booking["id"], OPS), 200)[
            "status"] == "ARRIVED"

        res = api.close_voyage(ctx["voyage"]["id"], OPS)
        validate_error(res, ApiErrorId.ERR_VOYAGE_HAS_OPEN_BOOKINGS,
                       expected_status=409)

        released = validate_success(
            api.release_bill_of_lading(ctx["bl"]["id"], DOC_2), 200)
        assert released["status"] == "RELEASED"
        invoice = create_issued_freight_invoice(booking["id"])
        assert invoice["total_cents"] == 236000
        paid = validate_success(
            api.record_invoice_payment(invoice["id"], 236000, FC), 200)
        assert paid["status"] == "PAID"

        delivered = validate_success(api.deliver_booking(booking["id"], BC), 200)
        assert delivered["status"] == "DELIVERED"

        closed = validate_success(api.close_voyage(ctx["voyage"]["id"], OPS), 200)
        assert closed["status"] == "CLOSED"
