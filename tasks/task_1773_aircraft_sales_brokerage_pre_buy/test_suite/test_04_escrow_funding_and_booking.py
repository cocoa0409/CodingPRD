"""Escrow funding, inspection booking lifecycle, and slot-conflict rules."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_escrow_disposition_invariant,
    book_inspection,
    create_facility,
    create_inspection_booking_payload,
    fund_escrow,
    fund_escrow_payload,
    get_success_data,
    setup_accepted_deal,
    setup_deal_with_booking,
    setup_funded_deal,
    setup_inspection_scheduled_deal,
    validate_error,
    validate_success,
)

BROKER = TEST_USERS["broker_principal_headers"]
LISTING_AGENT = TEST_USERS["listing_agent_headers"]
BUYER_AGENT = TEST_USERS["buyer_agent_headers"]
ESCROW = TEST_USERS["escrow_officer_headers"]
SCHEDULER = TEST_USERS["facility_scheduler_headers"]


class TestEscrowFunding:
    def test_fund_escrow_twice_returns_invalid_state(self, api):
        """PRD §3.7: "The deposit moves from `AWAITING_FUNDS` to `FUNDED`, its
        `version` increments, and the transaction bubbles up from `OPENED` to
        `ESCROW_FUNDED` in the same request"
        PRD §2.8: "5. **State preconditions**, evaluated in three sub-steps: (a)
        the target resource is in a state that permits the requested transition,
        failing with `ERR_INVALID_STATE` (HTTP 409)"

        Design: Corner/state_machines/fund_escrow_twice_returns_invalid_state
        """
        deal = setup_funded_deal(funding_reference="WIRE-1")
        resp = api.fund_escrow_deposit(deal["escrow"]["id"],
                                       fund_escrow_payload("WIRE-DUP"), ESCROW)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fetched = validate_success(api.get_escrow_deposit(deal["escrow"]["id"], ESCROW))
        assert fetched["status"] == "FUNDED"
        assert fetched["funding_reference"] == "WIRE-1", (
            "The first funding_reference is retained")

    def test_listing_agent_cannot_fund_escrow(self, api):
        """PRD §2.1: "Each endpoint declares the roles authorized to invoke it,
        and a caller whose role is not in that list is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "POST `/api/escrow-deposits/{id}/fund` | Record receipt of the
        deposit wire | EscrowOfficer"

        Design: Corner/rbac/listing_agent_cannot_fund_escrow
        """
        deal = setup_accepted_deal()
        resp = api.fund_escrow_deposit(deal["escrow"]["id"], fund_escrow_payload(),
                                       LISTING_AGENT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        fetched = validate_success(api.get_escrow_deposit(deal["escrow"]["id"], ESCROW))
        assert fetched["status"] == "AWAITING_FUNDS"


class TestBookingFundingGate:
    def test_booking_on_opened_transaction_rejected(self, api):
        """PRD §3.7: "If the transaction is not in `ESCROW_FUNDED` status, the
        booking is rejected with `ERR_TRANSACTION_NOT_FUNDED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/booking_requires_escrow_funded_transaction
        """
        deal = setup_accepted_deal()  # transaction OPENED, escrow AWAITING_FUNDS
        facility = create_facility()
        resp = api.create_inspection_booking(
            create_inspection_booking_payload(deal["transaction"]["id"], facility["id"]),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_TRANSACTION_NOT_FUNDED)

    def test_booking_after_escrow_funding_succeeds(self, api):
        """PRD §3.7: "If the transaction is not in `ESCROW_FUNDED` status, the
        booking is rejected with `ERR_TRANSACTION_NOT_FUNDED` (HTTP 409)."
        PRD §3.7: "The deposit moves from `AWAITING_FUNDS` to `FUNDED`, its
        `version` increments, and the transaction bubbles up from `OPENED` to
        `ESCROW_FUNDED` in the same request — the funding event is what arms the
        deal for inspection."

        Design: Difficulty/cross_entity_state_dependency/booking_requires_escrow_funded_transaction
        """
        deal = setup_accepted_deal()
        facility = create_facility()
        resp = api.create_inspection_booking(
            create_inspection_booking_payload(deal["transaction"]["id"], facility["id"]),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_TRANSACTION_NOT_FUNDED)

        fund_escrow(deal["escrow"]["id"])
        tx = validate_success(api.get_transaction(deal["transaction"]["id"], BROKER))
        assert tx["status"] == "ESCROW_FUNDED", "Funding bubbles the transaction up"
        booking = validate_success(
            api.create_inspection_booking(
                create_inspection_booking_payload(deal["transaction"]["id"],
                                                  facility["id"]),
                SCHEDULER), 201)
        assert booking["status"] == "REQUESTED"


class TestBookingWindowSchema:
    def test_booking_end_not_after_start_returns_window_invalid(self, api):
        """PRD §3.7: "The window itself must be well-formed — an `end_at` that
        is not strictly after `start_at` is rejected with
        `ERR_BOOKING_WINDOW_INVALID` (HTTP 422)"

        Design: Corner/validations/booking_end_not_after_start_returns_window_invalid
        """
        deal = setup_funded_deal()
        facility = create_facility()
        resp = api.create_inspection_booking(
            create_inspection_booking_payload(
                deal["transaction"]["id"], facility["id"],
                start_at="2026-09-01T10:00:00Z", end_at="2026-09-01T10:00:00Z"),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_BOOKING_WINDOW_INVALID)


class TestBookingNotFound:
    def test_get_inspection_booking_not_found_returns_404(self, api):
        """PRD §2.9: "Wherever a path carries identifiers, the system validates
        their existence sequentially from left to right and rejects the request
        with the not-found error corresponding to the first identifier that does
        not resolve: `ERR_LISTING_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`,
        `ERR_COMPARABLE_SALE_NOT_FOUND`, `ERR_LOI_NOT_FOUND`,
        `ERR_TRANSACTION_NOT_FOUND`, `ERR_ESCROW_DEPOSIT_NOT_FOUND`,
        `ERR_INSPECTION_FACILITY_NOT_FOUND`, `ERR_INSPECTION_BOOKING_NOT_FOUND`,
        or `ERR_DISCREPANCY_ITEM_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/get_inspection_booking_not_found_returns_404
        """
        setup_funded_deal()
        resp = api.get_inspection_booking(NON_EXISTENT_UUID, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_BOOKING_NOT_FOUND)

    def test_booking_with_missing_facility_returns_404(self, api):
        """PRD §2.9: "Identifiers referenced from a request body — such as
        `listing_id`, `buyer_id`, `transaction_id`, `facility_id`, or
        `inspection_booking_id` — must likewise resolve to existing resources
        before any business rule is evaluated, surfacing the corresponding
        not-found error."

        Design: Corner/errors/booking_with_missing_facility_returns_404
        """
        deal = setup_funded_deal()
        resp = api.create_inspection_booking(
            create_inspection_booking_payload(deal["transaction"]["id"],
                                              NON_EXISTENT_UUID),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_FACILITY_NOT_FOUND)


class TestEscrowNotFound:
    def test_get_escrow_deposit_not_found_returns_404(self, api):
        """PRD §2.9: "Wherever a path carries identifiers, the system validates
        their existence sequentially from left to right and rejects the request
        with the not-found error corresponding to the first identifier that does
        not resolve: `ERR_LISTING_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`,
        `ERR_COMPARABLE_SALE_NOT_FOUND`, `ERR_LOI_NOT_FOUND`,
        `ERR_TRANSACTION_NOT_FOUND`, `ERR_ESCROW_DEPOSIT_NOT_FOUND`,
        `ERR_INSPECTION_FACILITY_NOT_FOUND`, `ERR_INSPECTION_BOOKING_NOT_FOUND`,
        or `ERR_DISCREPANCY_ITEM_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/get_escrow_deposit_not_found_returns_404
        """
        setup_accepted_deal()
        resp = api.get_escrow_deposit(NON_EXISTENT_UUID, ESCROW)
        validate_error(resp, ApiErrorId.ERR_ESCROW_DEPOSIT_NOT_FOUND)


class TestBookingLifecycle:
    def test_complete_requested_booking_returns_invalid_state(self, api):
        """PRD §3.7: "Completing a confirmed slot moves it from `CONFIRMED` to
        `COMPLETED`, requires the transaction to be in `INSPECTION_SCHEDULED`,
        and bubbles the transaction up to `INSPECTION_COMPLETE`"
        PRD §2.8: "5. **State preconditions**, evaluated in three sub-steps: (a)
        the target resource is in a state that permits the requested transition,
        failing with `ERR_INVALID_STATE` (HTTP 409)"

        Design: Corner/state_machines/complete_requested_booking_returns_invalid_state
        """
        deal = setup_deal_with_booking()  # booking REQUESTED
        resp = api.complete_booking(deal["booking"]["id"], SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fetched = validate_success(api.get_inspection_booking(deal["booking"]["id"],
                                                              SCHEDULER))
        assert fetched["status"] == "REQUESTED", "complete from REQUESTED is not declared"

    def test_booking_cancel_reverts_transaction_to_escrow_funded(self, api):
        """PRD §3.7: "Cancelling moves a `REQUESTED` or `CONFIRMED` booking to
        `CANCELLED`, and when the transaction is `INSPECTION_SCHEDULED` and no
        other booking of the transaction remains in `REQUESTED` or `CONFIRMED`,
        the cancellation reverts the transaction back to `ESCROW_FUNDED`,
        reopening the scheduling step."

        Design: Corner/state_machines/booking_cancel_reverts_transaction_to_escrow_funded
        """
        deal = setup_inspection_scheduled_deal()
        assert deal["transaction"]["status"] == "INSPECTION_SCHEDULED"
        cancelled = validate_success(api.cancel_booking(deal["booking"]["id"], SCHEDULER))
        assert cancelled["status"] == "CANCELLED"
        tx = validate_success(api.get_transaction(deal["transaction"]["id"], BROKER))
        assert tx["status"] == "ESCROW_FUNDED", (
            "Cancelling the only active booking reverts the transaction")


class TestFacilityBufferRule:
    def _two_funded_deals_one_facility(self, api):
        deal_1 = setup_funded_deal(funding_reference="WIRE-1")
        deal_2 = setup_funded_deal(
            funding_reference="WIRE-2",
            listing_overrides={"tail_number": "N1002GS", "year": 2016,
                               "total_time_hours": 3050,
                               "asking_price_usd": 11800000.00,
                               "seller_name": "Meridian Air LLC"})
        facility = create_facility(name="SkyMRO", airport_code="KTEB",
                                   turnaround_buffer_minutes=120)
        booking_1 = book_inspection(deal_1["transaction"]["id"], facility["id"],
                                    start_at="2026-09-01T10:00:00Z",
                                    end_at="2026-09-01T14:00:00Z")
        return deal_1, deal_2, facility, booking_1

    def test_facility_buffer_rejects_zero_gap_booking(self, api):
        """PRD §3.7: "The facility buffer rule rejects the booking with
        `ERR_FACILITY_SLOT_CONFLICT` (HTTP 409) when any other booking in
        `REQUESTED` or `CONFIRMED` status at the same facility has a window that
        — expanded by that facility's `turnaround_buffer_minutes` — intersects
        the requested half-open window from `start_at` up to but not including
        `end_at`."

        Design: Difficulty/resource_temporal_overlap/facility_buffer_rejects_adjacent_slot
        """
        _d1, deal_2, facility, _b1 = self._two_funded_deals_one_facility(api)
        # Zero-minute gap: 14:00 start equals the existing booking's 14:00 end,
        # inside the 120-minute expanded window.
        resp = api.create_inspection_booking(
            create_inspection_booking_payload(deal_2["transaction"]["id"],
                                              facility["id"],
                                              start_at="2026-09-01T14:00:00Z",
                                              end_at="2026-09-01T16:00:00Z"),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_FACILITY_SLOT_CONFLICT)

    def test_facility_buffer_accepts_gap_equal_to_buffer(self, api):
        """PRD §3.7: "The facility buffer rule rejects the booking with
        `ERR_FACILITY_SLOT_CONFLICT` (HTTP 409) when any other booking in
        `REQUESTED` or `CONFIRMED` status at the same facility has a window that
        — expanded by that facility's `turnaround_buffer_minutes` — intersects
        the requested half-open window from `start_at` up to but not including
        `end_at`."

        Design: Difficulty/resource_temporal_overlap/facility_buffer_rejects_adjacent_slot
        """
        _d1, deal_2, facility, _b1 = self._two_funded_deals_one_facility(api)
        # Gap exactly equal to the 120-minute buffer: the expanded window
        # [08:00, 16:00) no longer intersects [16:00, 18:00).
        booking = validate_success(
            api.create_inspection_booking(
                create_inspection_booking_payload(deal_2["transaction"]["id"],
                                                  facility["id"],
                                                  start_at="2026-09-01T16:00:00Z",
                                                  end_at="2026-09-01T18:00:00Z"),
                SCHEDULER), 201)
        assert booking["status"] == "REQUESTED"


class TestAircraftOverlapRule:
    def _deal_with_booking_and_three_facilities(self, api):
        deal = setup_funded_deal()
        fac_1 = create_facility(name="SkyMRO", airport_code="KTEB",
                                turnaround_buffer_minutes=120)
        fac_2 = create_facility(name="AeroTech", airport_code="KFXE",
                                turnaround_buffer_minutes=60)
        fac_3 = create_facility(name="JetCare", airport_code="KPBI",
                                turnaround_buffer_minutes=30)
        booking_1 = book_inspection(deal["transaction"]["id"], fac_1["id"],
                                    start_at="2026-09-01T10:00:00Z",
                                    end_at="2026-09-01T14:00:00Z")
        return deal, fac_1, fac_2, fac_3, booking_1

    def test_aircraft_adjacent_booking_allowed(self, api):
        """PRD §3.7: "The aircraft rule then rejects the booking with
        `ERR_AIRCRAFT_SLOT_CONFLICT` (HTTP 409) when any other `REQUESTED` or
        `CONFIRMED` booking for the same transaction's listing strictly overlaps
        the requested window; because windows are half-open, adjacency — one
        booking's `end_at` exactly equal to another's `start_at` — does not
        count as an overlap and is allowed."

        Design: Difficulty/resource_temporal_overlap/aircraft_half_open_adjacency_allowed_overlap_rejected
        """
        deal, _f1, fac_2, _f3, _b1 = self._deal_with_booking_and_three_facilities(api)
        # Same aircraft, different facility, start exactly at the existing
        # booking's end: half-open adjacency is allowed.
        booking = validate_success(
            api.create_inspection_booking(
                create_inspection_booking_payload(deal["transaction"]["id"],
                                                  fac_2["id"],
                                                  start_at="2026-09-01T14:00:00Z",
                                                  end_at="2026-09-01T16:00:00Z"),
                SCHEDULER), 201)
        assert booking["status"] == "REQUESTED"

    def test_aircraft_overlapping_booking_rejected(self, api):
        """PRD §3.7: "The aircraft rule then rejects the booking with
        `ERR_AIRCRAFT_SLOT_CONFLICT` (HTTP 409) when any other `REQUESTED` or
        `CONFIRMED` booking for the same transaction's listing strictly overlaps
        the requested window; because windows are half-open, adjacency — one
        booking's `end_at` exactly equal to another's `start_at` — does not
        count as an overlap and is allowed."

        Design: Difficulty/resource_temporal_overlap/aircraft_half_open_adjacency_allowed_overlap_rejected
        """
        deal, _f1, _f2, fac_3, _b1 = self._deal_with_booking_and_three_facilities(api)
        # 13:30-15:00 strictly overlaps the existing 10:00-14:00 booking of the
        # same aircraft (at another facility, so the facility rule cannot fire).
        resp = api.create_inspection_booking(
            create_inspection_booking_payload(deal["transaction"]["id"],
                                              fac_3["id"],
                                              start_at="2026-09-01T13:30:00Z",
                                              end_at="2026-09-01T15:00:00Z"),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_AIRCRAFT_SLOT_CONFLICT)
