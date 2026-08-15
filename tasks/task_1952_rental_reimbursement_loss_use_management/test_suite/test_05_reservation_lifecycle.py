"""Reservation lifecycle: authorize/cancel/activate/return/close, reserve
conservation, and the unnecessary-day assessment."""
import pytest

from test_helpers import (
    ADJUSTER,
    DESK,
    NON_EXISTENT_UUID,
    RECOVERY,
    SETTLEMENT,
    ApiErrorId,
    add_approved_repair_order,
    add_repair_order_in_progress,
    api_client,
    assert_recovery_case,
    assert_rental_reservation,
    authorize_reservation,
    book_reservation,
    cancel_reservation,
    complete_repair_order,
    create_rental_reservation_payload,
    get_claim_view,
    get_reservation_view,
    list_claim_recovery_cases,
    make_rental_partner_headers,
    register_rental_partner,
    return_reservation,
    set_clock,
    setup_active_rental_scenario,
    setup_authorized_rental_scenario,
    setup_manual_review_invoice_scenario,
    setup_pending_extension_scenario,
    setup_returned_rental_scenario,
    setup_verified_claim_context,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthorizeAndCancel:
    def test_authorize_twice_rejected(self, api):
        """PRD §3.4: "Authorizing a reservation that is not in `DRAFT` fails with
        `ERR_RESERVATION_INVALID_STATE`."

        Design: Corner/state_machines/authorize_twice_rejected
        """
        ctx = setup_authorized_rental_scenario()
        reserve_after_first = get_claim_view(ctx["claim"]["id"])["rental_reserve_cents"]
        assert reserve_after_first == 60000

        resp = api.authorize_rental_reservation(ctx["reservation"]["id"], DESK)
        validate_error(resp, ApiErrorId.ERR_RESERVATION_INVALID_STATE)
        assert get_claim_view(ctx["claim"]["id"])["rental_reserve_cents"] == 60000, (
            "The rejected second authorize must not double-debit the reserve"
        )

    def test_cancel_from_terminal_state_rejected(self, api):
        """PRD §3.4: "Cancelling is a `RentalDeskAgent` action available from
        `DRAFT` or `AUTHORIZED` only — any other state is
        `ERR_RESERVATION_INVALID_STATE` — and it lands the reservation in the
        terminal `CANCELLED` state."

        Design: Corner/state_machines/cancel_from_terminal_state_rejected
        """
        ctx = setup_verified_claim_context()
        add_approved_repair_order(ctx)
        reservation = book_reservation(ctx["claim"]["id"], ctx["partner"]["id"],
                                       ctx["repair_order"]["id"])
        cancel_reservation(reservation["id"])

        resp = api.cancel_rental_reservation(reservation["id"], DESK)
        validate_error(resp, ApiErrorId.ERR_RESERVATION_INVALID_STATE)

    def test_insufficient_reserve_rejected(self, api):
        """PRD §3.4: "This provisional estimate is deliberately uncapped by the
        coverage daily limit and excludes tax entirely: it is the desk's
        forward-looking authorization exposure, not the audit figure, and it
        diverges from the audited charge whenever the booked rate exceeds the
        limit or any tax is later billed."
        PRD §3.4: "The provisional `estimated_charge_cents` must not exceed the
        claim's current `rental_reserve_cents`, else the authorization is refused
        with `ERR_INSUFFICIENT_RESERVE` (HTTP 402)."

        Design: Corner/validations/insufficient_reserve_rejected
        """
        ctx = setup_verified_claim_context()
        add_approved_repair_order(ctx)
        reservation = book_reservation(
            ctx["claim"]["id"], ctx["partner"]["id"], ctx["repair_order"]["id"],
            vehicle_class="PREMIUM",
            pickup_date="2026-08-05", authorized_return_date="2026-08-20")
        assert reservation["estimated_charge_cents"] == 135000, (
            f"Expected uncapped provisional estimate 135000 (15 x 9000), "
            f"got {reservation['estimated_charge_cents']}"
        )

        resp = api.authorize_rental_reservation(reservation["id"], DESK)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_RESERVE)
        assert get_reservation_view(reservation["id"])["status"] == "DRAFT"
        assert get_claim_view(ctx["claim"]["id"])["rental_reserve_cents"] == 120000, (
            "A refused authorization must leave the reserve unchanged"
        )

    def test_reservation_not_found_rejected(self, api):
        """PRD §2.8: "Each resource type has its own not-found error:
        `ERR_POLICYHOLDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
        `ERR_COVERAGE_VERIFICATION_NOT_FOUND`, `ERR_REPAIR_SHOP_NOT_FOUND`,
        `ERR_RENTAL_PARTNER_NOT_FOUND`, `ERR_REPAIR_ORDER_NOT_FOUND`,
        `ERR_MILESTONE_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`,
        `ERR_EXTENSION_REQUEST_NOT_FOUND`, `ERR_LOSS_OF_USE_CLAIM_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND`, and `ERR_RECOVERY_CASE_NOT_FOUND`."

        Design: Corner/errors/reservation_not_found_rejected
        """
        resp = api.authorize_rental_reservation(NON_EXISTENT_UUID, DESK)
        validate_error(resp, ApiErrorId.ERR_RESERVATION_NOT_FOUND)


class TestReserveConservation:
    def test_authorize_debits_reserve(self, api):
        """PRD §2.6: "First, authorizing a reservation and then cancelling it
        leaves the reserve unchanged: authorization debits the estimate, and
        cancellation of an `AUTHORIZED` reservation credits the same estimate back
        in full."

        Design: Difficulty/compensating_invariant/authorize_cancel_reserve_conservation
        """
        ctx = setup_verified_claim_context()
        add_approved_repair_order(ctx)
        reservation = book_reservation(ctx["claim"]["id"], ctx["partner"]["id"],
                                       ctx["repair_order"]["id"])
        before = get_claim_view(ctx["claim"]["id"])["rental_reserve_cents"]
        assert before == 120000, f"Expected initial reserve 120000, got {before}"

        authorize_reservation(reservation["id"])
        after = get_claim_view(ctx["claim"]["id"])["rental_reserve_cents"]
        assert after == 60000, (
            f"Expected reserve 60000 after authorizing the 60000 estimate, "
            f"got {after}"
        )

    def test_cancel_after_authorize_restores_reserve(self, api):
        """PRD §3.4: "Cancellation of an `AUTHORIZED` reservation performs a full
        compensating release, crediting the entire `estimated_charge_cents` back
        to the claim's reserve; this is what makes the authorize-then-cancel
        sequence reserve-neutral under the conservation invariant of §2.6."
        PRD §2.6: "The `authorized_days_total` ledger sums `authorized_days` over
        the claim's reservations in `AUTHORIZED`, `ACTIVE`, `EXTENSION_REVIEW`, or
        `RETURNED` status."

        Design: Difficulty/compensating_invariant/authorize_cancel_reserve_conservation
        """
        ctx = setup_authorized_rental_scenario()
        cancel_reservation(ctx["reservation"]["id"])
        claim = get_claim_view(ctx["claim"]["id"])
        assert claim["rental_reserve_cents"] == 120000, (
            f"Authorize-then-cancel must be reserve-neutral at 120000, "
            f"got {claim['rental_reserve_cents']}"
        )
        assert claim["authorized_days_total"] == 0, (
            "A CANCELLED reservation must leave the authorized-days aggregate"
        )


class TestActivation:
    def test_activation_before_pickup_rejected(self, api):
        """PRD §3.4: "Activation requires the reservation to be `AUTHORIZED`
        (`ERR_RESERVATION_INVALID_STATE` otherwise), requires the caller to own
        the reservation (`ERR_NOT_RESOURCE_OWNER`), and requires the logical
        clock's date to be on or after the `pickup_date` — early activation fails
        with `ERR_ACTIVATION_BEFORE_PICKUP_DATE`."

        Design: Corner/validations/activation_before_pickup_rejected
        """
        ctx = setup_authorized_rental_scenario()
        set_clock("2026-08-04T09:00:00Z")
        resp = api.activate_rental_reservation(
            ctx["reservation"]["id"],
            make_rental_partner_headers(ctx["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ACTIVATION_BEFORE_PICKUP_DATE)

        set_clock("2026-08-05T09:00:00Z")
        resp = api.activate_rental_reservation(
            ctx["reservation"]["id"],
            make_rental_partner_headers(ctx["partner"]["id"]))
        activated = validate_success(resp, 200)
        assert activated["status"] == "ACTIVE"

    def test_first_activation_flips_rental_track(self, api):
        """PRD §3.4: "The reservation moves to `ACTIVE` and `actual_pickup_date`
        is stamped from the clock. When this is the claim's first reservation to
        reach `ACTIVE`, the claim's rental track automatically advances from
        `COVERAGE_VERIFIED` to `RENTAL_ACTIVE` with a claim version increment;
        activations beyond the first touch no claim state."

        Design: Corner/state_machines/first_activation_flips_rental_track
        """
        ctx = setup_authorized_rental_scenario()
        set_clock("2026-08-05T09:00:00Z")
        resp = api.activate_rental_reservation(
            ctx["reservation"]["id"],
            make_rental_partner_headers(ctx["partner"]["id"]))
        activated = validate_success(resp, 200)
        assert activated["actual_pickup_date"] == "2026-08-05", (
            f"Pickup must be stamped from the logical clock at 2026-08-05, "
            f"got {activated['actual_pickup_date']}"
        )
        claim = get_claim_view(ctx["claim"]["id"])
        assert claim["rental_track_status"] == "RENTAL_ACTIVE"

    def test_partner_cannot_activate_others_reservation_forbidden(self, api):
        """PRD §2.9: "A `RentalPartner` caller may act only on reservations it
        owns — recording pickup, recording return, and submitting direct-bill
        invoices all require the reservation's `rental_partner_id` to equal the
        caller's `X-User-ID`."
        PRD §2.9: "Every ownership failure is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/partner_cannot_activate_others_reservation_forbidden
        """
        ctx = setup_authorized_rental_scenario()
        partner_b = register_rental_partner(
            partner_name="RentCo B", partner_code="RC-B",
            economy_rate_cents=5000, standard_rate_cents=6500,
            premium_rate_cents=9500)
        set_clock("2026-08-05T09:00:00Z")
        resp = api.activate_rental_reservation(
            ctx["reservation"]["id"], make_rental_partner_headers(partner_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        reservation = get_reservation_view(ctx["reservation"]["id"])
        assert reservation["status"] == "AUTHORIZED"
        assert reservation["actual_pickup_date"] is None


class TestReturn:
    def test_consumed_days_computed_on_return(self, api):
        """PRD §3.6: "On success the reservation moves to `RETURNED`,
        `actual_return_date` is stamped from the logical clock, `consumed_days` is
        computed as the half-open day count from `actual_pickup_date` to
        `actual_return_date`, and the reservation leaves the reserve's estimate
        term — its provisional charge is released from the `rental_reserve_cents`
        reconciliation of §2.6."
        PRD §3.6: "If the reservation's repair order is not `COMPLETED`, there is
        nothing to recover: `unnecessary_days` is zero and no recovery case is
        created."

        Design: Corner/calculations/consumed_days_computed_on_return
        """
        ctx = setup_active_rental_scenario()
        returned = return_reservation(ctx["reservation"]["id"],
                                      ctx["partner"]["id"],
                                      clock="2026-08-12T11:00:00Z")
        assert returned["actual_return_date"] == "2026-08-12"
        assert returned["consumed_days"] == 7, (
            f"Expected 7 consumed days for [2026-08-05, 2026-08-12), "
            f"got {returned['consumed_days']}"
        )
        assert returned["unnecessary_days"] == 0, (
            "Repair still IN_PROGRESS — the overstay assessment must stay inert"
        )

    def test_unnecessary_days_one_past_grace(self, api):
        """PRD §3.6: "Otherwise the system extends the order's
        `actual_completion_date` by one calendar day of return grace — the
        claimant is entitled to keep the car through the day after repairs finish
        — and counts the days from that grace boundary to the actual return date,
        floored at zero; that count is the reservation's `unnecessary_days`. When
        the count is positive, a recovery case is opened automatically with
        `source` `RETURN_OVERSTAY`, its `claim_id` and `reservation_id` copied
        from the reservation, its `unnecessary_days` set to the computed count,
        and its `assessed_amount_cents` set to the unnecessary days multiplied by
        the reservation's current `daily_rate_cents`."

        Design: Corner/calculations/unnecessary_days_one_past_grace
        """
        ctx = setup_active_rental_scenario()
        complete_repair_order(ctx["repair_order"]["id"], ctx["shop"]["id"],
                              clock="2026-08-14T15:00:00Z")
        returned = return_reservation(ctx["reservation"]["id"],
                                      ctx["partner"]["id"],
                                      clock="2026-08-16T10:00:00Z")
        assert returned["unnecessary_days"] == 1, (
            f"Return 2026-08-16 against grace end 2026-08-15 must yield 1 "
            f"unnecessary day, got {returned['unnecessary_days']}"
        )
        cases = list_claim_recovery_cases(ctx["claim"]["id"])
        assert len(cases) == 1
        assert_recovery_case(cases[0])
        assert cases[0]["source"] == "RETURN_OVERSTAY"
        assert cases[0]["unnecessary_days"] == 1
        assert cases[0]["assessed_amount_cents"] == 6000, (
            f"Expected assessment 1 x 6000, got {cases[0]['assessed_amount_cents']}"
        )

    def test_return_with_pending_extension_rejected(self, api):
        """PRD §3.6: "A return is also refused while any extension request on the
        reservation is still `SUBMITTED`, surfacing
        `ERR_PENDING_EXTENSION_EXISTS`; the desk must decide the pending extension
        first."

        Design: Corner/state_machines/return_with_pending_extension_rejected
        """
        ctx = setup_pending_extension_scenario(
            new_estimated_completion_date="2026-08-18", requested_additional_days=4)
        resp = api.return_rental_reservation(
            ctx["reservation"]["id"],
            make_rental_partner_headers(ctx["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PENDING_EXTENSION_EXISTS)

        deny = api.deny_extension_request(ctx["extension"]["id"], {}, ADJUSTER)
        validate_success(deny, 200)
        returned = return_reservation(ctx["reservation"]["id"], ctx["partner"]["id"])
        assert returned["status"] == "RETURNED"


class TestReturnZeroUnnecessaryDays:
    def _setup_grace_boundary_return(self):
        """Repair completed 2026-08-14 (grace end 2026-08-15); vehicle returned
        exactly at the 2026-08-15 grace boundary."""
        ctx = setup_active_rental_scenario()
        complete_repair_order(ctx["repair_order"]["id"], ctx["shop"]["id"],
                              clock="2026-08-14T15:00:00Z")
        set_clock("2026-08-15T10:00:00Z")
        return ctx

    def test_return_at_grace_boundary_zero_unnecessary_days(self, api):
        """PRD §3.6: "Otherwise the system extends the order's
        `actual_completion_date` by one calendar day of return grace — the
        claimant is entitled to keep the car through the day after repairs finish
        — and counts the days from that grace boundary to the actual return date,
        floored at zero; that count is the reservation's `unnecessary_days`."

        Design: Difficulty/boundary_precision_check/return_zero_unnecessary_days_no_case
        """
        ctx = self._setup_grace_boundary_return()
        resp = api.return_rental_reservation(
            ctx["reservation"]["id"],
            make_rental_partner_headers(ctx["partner"]["id"]))
        returned = validate_success(resp, 200)
        assert returned["unnecessary_days"] == 0, (
            f"Return exactly at the grace boundary must floor to 0 unnecessary "
            f"days, got {returned['unnecessary_days']}"
        )

    def test_zero_unnecessary_days_creates_no_recovery_case(self, api):
        """PRD §3.6: "When the count is zero, return touches no claim state at
        all."
        PRD §3.6: "When the count is positive, a recovery case is opened
        automatically with `source` `RETURN_OVERSTAY`"

        Design: Difficulty/boundary_precision_check/return_zero_unnecessary_days_no_case
        """
        ctx = self._setup_grace_boundary_return()
        return_reservation(ctx["reservation"]["id"], ctx["partner"]["id"], clock=None)
        cases, meta = validate_paginated(
            api.list_claim_recovery_cases(ctx["claim"]["id"], RECOVERY))
        assert meta["total_count"] == 0, (
            f"No recovery case may be created at the zero boundary, "
            f"got {meta['total_count']}"
        )
        assert get_claim_view(ctx["claim"]["id"])["recovery_balance_cents"] == 0


class TestReservationClose:
    def test_close_blocked_while_invoice_unsettled(self, api):
        """PRD §3.6: "Closure by a `RentalDeskAgent` requires the reservation to
        be `RETURNED` (`ERR_RESERVATION_INVALID_STATE` otherwise), every invoice
        on the reservation to be `SETTLED`, and every recovery case on the
        reservation to be `CLOSED` or `WAIVED` (or none to exist) — either
        shortfall blocks the close with `ERR_RESERVATION_CLOSE_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/reservation_close_blocked_by_unsettled_invoice
        """
        ctx = setup_manual_review_invoice_scenario(
            invoice_overrides={"period_end": "2026-08-16", "tax_cents": 4800})
        assert ctx["invoice"]["status"] == "MANUAL_REVIEW"

        resp = api.close_rental_reservation(ctx["reservation"]["id"], DESK)
        validate_error(resp, ApiErrorId.ERR_RESERVATION_CLOSE_BLOCKED)

    def test_close_succeeds_after_invoice_settled(self, api):
        """PRD §3.6: "A successful close lands the reservation in the terminal
        `CLOSED` state, and when every reservation on the claim is now terminal
        (`CLOSED` or `CANCELLED`) and at least one reservation exists, the claim's
        rental track automatically advances from `RENTAL_ACTIVE` to
        `RENTAL_CLOSED` with a claim version increment."

        Design: Difficulty/cross_entity_state_dependency/reservation_close_blocked_by_unsettled_invoice
        """
        ctx = setup_manual_review_invoice_scenario(
            invoice_overrides={"period_end": "2026-08-16", "tax_cents": 4800})
        audit = api.decide_invoice_audit(ctx["invoice"]["id"],
                                         {"decision": "ADJUST_TO_AUTHORIZED"},
                                         ADJUSTER)
        validate_success(audit, 200)
        settle = api.settle_invoice(ctx["invoice"]["id"], SETTLEMENT)
        validate_success(settle, 200)

        resp = api.close_rental_reservation(ctx["reservation"]["id"], DESK)
        closed = validate_success(resp, 200)
        assert closed["status"] == "CLOSED"
        assert get_claim_view(ctx["claim"]["id"])["rental_track_status"] == "RENTAL_CLOSED"
