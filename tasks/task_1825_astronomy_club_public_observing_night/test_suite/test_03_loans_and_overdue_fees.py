"""Loan program: creation gates, window overlap, overdue fee arithmetic."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_certification,
    create_checked_out_loan,
    create_loan_reservation_payload,
    create_member_with_paid_dues,
    create_reserved_loan,
    create_telescope,
    get_success_data,
    make_member_headers,
    set_clock,
    setup_member_with_cert_and_scope,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["club_officer_headers"]
CHAIR = TEST_USERS["equipment_chair_headers"]


class TestOverdueFeeVariants:
    def test_overdue_fee_provisional_uncapped_while_overdue(self, api):
        """PRD: "While the loan remains `OVERDUE`, reading it returns a
        provisional `overdue_fees_cents` computed against the logical clock
        — the value keeps growing and is never persisted."
        PRD: "the first 2 days are free, so the billable day count is the
        days late minus 2, again floored at zero; the fee is the billable
        days multiplied by 500 cents."
        PRD: "The final variant then applies a cap of 10000 cents; the
        provisional variant is uncapped so that a member reading the loan
        sees the true exposure."

        Design: Difficulty/combinatorial_formula/overdue_fee_nested_rounding_and_cap
        """
        member, scope, _cert = setup_member_with_cert_and_scope(
            member_name="Late Larry")
        loan = create_reserved_loan(member, scope, "2026-08-02T00:00:00Z",
                                    "2026-08-04T00:00:00Z")
        set_clock("2026-08-02T12:00:00Z")
        get_success_data(api.checkout_loan(loan["id"], CHAIR))
        set_clock("2026-08-29T00:00:00Z")

        fetched = validate_success(api.get_loan_reservation(loan["id"], CHAIR))
        assert fetched["status"] == "OVERDUE", (
            "Clock 2026-08-29 >= window_end 2026-08-04 flips the loan OVERDUE")
        assert fetched["overdue_fees_cents"] == 11500, (
            "Provisional read is uncapped: (25 days late - 2 grace) * 500")

    def test_overdue_fee_final_capped_on_return(self, api):
        """PRD: "On return, the fee is finalized against `returned_at` and
        persisted."
        PRD: "The final variant then applies a cap of 10000 cents; the
        provisional variant is uncapped so that a member reading the loan
        sees the true exposure."
        PRD: "From either `CHECKED_OUT` or `OVERDUE`, the reservation moves
        to the terminal `RETURNED` state"

        Design: Difficulty/combinatorial_formula/overdue_fee_nested_rounding_and_cap
        """
        member, scope, _cert = setup_member_with_cert_and_scope(
            member_name="Cap Carrie")
        loan = create_reserved_loan(member, scope, "2026-08-02T00:00:00Z",
                                    "2026-08-04T00:00:00Z")
        set_clock("2026-08-02T12:00:00Z")
        get_success_data(api.checkout_loan(loan["id"], CHAIR))
        set_clock("2026-08-29T00:00:00Z")

        returned = validate_success(
            api.return_loan(loan["id"], CHAIR, damage_reported=False))
        assert returned["status"] == "RETURNED"
        assert returned["overdue_fees_cents"] == 10000, (
            "Final fee is capped at 10000: (25 - 2) * 500 = 11500 -> 10000")


class TestOverdueFeeGraceBoundary:
    def test_return_at_exactly_two_days_late_yields_zero_fee(self, api):
        """PRD: "The boundary is inclusive in the natural direction: exactly
        2 days late yields zero fee, and 3 days late yields exactly 500
        cents."

        Design: Difficulty/boundary_precision_check/overdue_fee_grace_boundary
        """
        member, scope, _cert = setup_member_with_cert_and_scope(
            member_name="Boundary Ann")
        loan = create_reserved_loan(member, scope, "2026-08-02T00:00:00Z",
                                    "2026-08-04T00:00:00Z")
        set_clock("2026-08-02T12:00:00Z")
        get_success_data(api.checkout_loan(loan["id"], CHAIR))
        # window_end 2026-08-04T00:00:00Z; 2 days late at 2026-08-06T12:00:00Z
        set_clock("2026-08-06T12:00:00Z")
        returned = validate_success(
            api.return_loan(loan["id"], CHAIR, damage_reported=False))
        assert returned["overdue_fees_cents"] == 0, (
            "Exactly 2 days late == GRACE_DAYS: zero fee, boundary inclusive")

    def test_return_at_three_days_late_yields_one_billable_day(self, api):
        """PRD: "The boundary is inclusive in the natural direction: exactly
        2 days late yields zero fee, and 3 days late yields exactly 500
        cents."

        Design: Difficulty/boundary_precision_check/overdue_fee_grace_boundary
        """
        member, scope, _cert = setup_member_with_cert_and_scope(
            member_name="Boundary Bob")
        loan = create_reserved_loan(member, scope, "2026-08-02T00:00:00Z",
                                    "2026-08-04T00:00:00Z")
        set_clock("2026-08-02T12:00:00Z")
        get_success_data(api.checkout_loan(loan["id"], CHAIR))
        # 3 days late at 2026-08-07T12:00:00Z
        set_clock("2026-08-07T12:00:00Z")
        returned = validate_success(
            api.return_loan(loan["id"], CHAIR, damage_reported=False))
        assert returned["overdue_fees_cents"] == 500, (
            "3 days late => exactly one billable day => 500 cents")


class TestLoanWindowHalfOpenOverlap:
    def test_adjacent_loan_starting_at_prior_window_end_is_legal(self, api):
        """PRD: "For loan scheduling this means a new reservation whose
        `window_start` equals an existing reservation's `window_end` does
        **not** intersect it — touching windows are legal for the same
        borrower."

        Design: Difficulty/resource_temporal_overlap/loan_window_half_open_adjacency
        """
        member, scope1, _cert = setup_member_with_cert_and_scope(
            member_name="Adjacent Al")
        scope2 = create_telescope(name="Adj Scope 2", equipment_class="REFRACTOR")
        loan1 = create_reserved_loan(member, scope1, "2026-08-05T00:00:00Z",
                                     "2026-08-09T00:00:00Z")
        assert loan1["status"] == "RESERVED"

        resp = api.create_loan_reservation(
            create_loan_reservation_payload(
                member["id"], scope2["id"],
                "2026-08-09T00:00:00Z", "2026-08-12T00:00:00Z"),
            make_member_headers(member["id"]))
        adjacent = validate_success(resp, 201)
        assert adjacent["status"] == "RESERVED", (
            "Half-open windows: window_start == prior window_end is legal")

    def test_overlapping_loan_one_hour_before_prior_end_rejected(self, api):
        """PRD: "the new window must not intersect any non-terminal
        reservation of the **same member**, regardless of which telescope is
        involved — a borrower cannot be responsible for two kits over one
        night."
        PRD: "otherwise a conflict is rejected with
        `ERR_LOAN_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/loan_window_half_open_adjacency
        """
        member, scope1, _cert = setup_member_with_cert_and_scope(
            member_name="Overlap Ollie")
        scope2 = create_telescope(name="Ov Scope 2", equipment_class="REFRACTOR")
        create_reserved_loan(member, scope1, "2026-08-05T00:00:00Z",
                             "2026-08-09T00:00:00Z")

        resp = api.create_loan_reservation(
            create_loan_reservation_payload(
                member["id"], scope2["id"],
                "2026-08-08T23:00:00Z", "2026-08-13T00:00:00Z"),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_LOAN_WINDOW_CONFLICT)
        assert resp.status_code == 409


class TestLoanCreationStandingGate:
    def test_suspended_member_cannot_create_loan(self, api):
        """PRD: "Second, the standing gate: the member's `status` must be
        `ACTIVE` and the member's tier must have `loan_privilege` true;
        otherwise the rejection is `ERR_MEMBER_NOT_IN_GOOD_STANDING`
        (HTTP 422)."
        PRD: "When the logical clock reaches `dues_paid_through` plus a
        grace period of 7 days while the member is `ACTIVE`, the member
        transitions `ACTIVE → SUSPENDED`"

        Design: Difficulty/cross_entity_state_dependency/loan_create_depends_on_member_standing
        """
        member, _tier, _inv, _pay = create_member_with_paid_dues(
            period_start="2025-08-01T00:00:00Z",
            period_end="2026-08-01T00:00:00Z",
            full_name="Slipping Stan")
        scope = create_telescope(name="Free Scope", equipment_class="REFRACTOR")
        create_certification(member["id"], "REFRACTOR",
                             "2027-08-01T00:00:00Z")
        # dues_paid_through 2026-08-01; +7 days grace -> SUSPENDED at 08-08.
        set_clock("2026-08-10T00:00:00Z")
        suspended = validate_success(api.get_member(member["id"], OFFICER))
        assert suspended["status"] == "SUSPENDED"

        resp = api.create_loan_reservation(
            create_loan_reservation_payload(
                member["id"], scope["id"],
                "2026-08-12T00:00:00Z", "2026-08-14T00:00:00Z"),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_IN_GOOD_STANDING)
        assert resp.status_code == 422

        scope_after = validate_success(api.get_telescope(scope["id"], CHAIR))
        assert scope_after["status"] == "AVAILABLE", (
            "Rejected reservation never moves the telescope")

    def test_active_member_with_privilege_creates_loan(self, api):
        """PRD: "Second, the standing gate: the member's `status` must be
        `ACTIVE` and the member's tier must have `loan_privilege` true"
        PRD: "A successful creation moves the named telescope
        `AVAILABLE → RESERVED` and the reservation begins in `RESERVED`."

        Design: Difficulty/cross_entity_state_dependency/loan_create_depends_on_member_standing
        """
        member, scope, _cert = setup_member_with_cert_and_scope(
            member_name="Good Gwen")
        loan = create_reserved_loan(member, scope, "2026-08-05T00:00:00Z",
                                    "2026-08-07T00:00:00Z")
        assert loan["status"] == "RESERVED"
        scope_after = validate_success(api.get_telescope(scope["id"], CHAIR))
        assert scope_after["status"] == "RESERVED"


class TestTelescopeAvailabilityConservation:
    def test_reserve_then_cancel_returns_telescope_to_available(self, api):
        """PRD: "A successful creation moves the named telescope
        `AVAILABLE → RESERVED`"
        PRD: "A `RESERVED` reservation can instead be cancelled — by the
        borrowing `Member`, by a `ClubOfficer` via the member's lifecycle
        cascades, or by the `EquipmentChair` directly — moving it
        `RESERVED → CANCELLED` and releasing the telescope
        `RESERVED → AVAILABLE`."

        Design: Difficulty/compensating_invariant/telescope_availability_conservation
        """
        member, scope, _cert = setup_member_with_cert_and_scope(
            member_name="Conserve Kay")
        _before, meta_before = validate_paginated(
            api.list_telescopes(CHAIR, params={"status": "AVAILABLE"}))
        avail_before = meta_before["total_count"]

        loan = create_reserved_loan(member, scope, "2026-08-05T00:00:00Z",
                                    "2026-08-07T00:00:00Z")
        mid = validate_success(api.get_telescope(scope["id"], CHAIR))
        assert mid["status"] == "RESERVED"

        cancelled = validate_success(
            api.cancel_loan(loan["id"], make_member_headers(member["id"])))
        assert cancelled["status"] == "CANCELLED"

        final = validate_success(api.get_telescope(scope["id"], CHAIR))
        assert final["status"] == "AVAILABLE", (
            "Reserve + compensating cancel conserves the availability pool")
        _after, meta_after = validate_paginated(
            api.list_telescopes(CHAIR, params={"status": "AVAILABLE"}))
        assert meta_after["total_count"] == avail_before, (
            "AVAILABLE pool count unchanged after reserve/cancel pair")

    def test_checkout_then_return_conserves_availability(self, api):
        """PRD: "Checkout, performed by the `EquipmentChair`, moves the
        reservation `RESERVED → CHECKED_OUT` and simultaneously moves the
        telescope `RESERVED → ON_LOAN`"
        PRD: "Without damage reported, the telescope returns
        `ON_LOAN → AVAILABLE`."

        Design: Difficulty/compensating_invariant/telescope_availability_conservation
        """
        member, scope, _cert = setup_member_with_cert_and_scope(
            member_name="Conserve Carl")
        loan = create_checked_out_loan(
            member, scope, "2026-08-01T00:00:00Z", "2026-08-05T00:00:00Z",
            checkout_clock="2026-08-02T12:00:00Z")
        mid = validate_success(api.get_telescope(scope["id"], CHAIR))
        assert mid["status"] == "ON_LOAN"

        returned = validate_success(
            api.return_loan(loan["id"], CHAIR, damage_reported=False))
        assert returned["status"] == "RETURNED"
        final = validate_success(api.get_telescope(scope["id"], CHAIR))
        assert final["status"] == "AVAILABLE", (
            "Checkout + return returns the telescope to the available pool")


class TestLoanInvalidTransitions:
    def test_checkout_from_checked_out_invalid(self, api):
        """PRD: "state-machine legality — the target resource is in a state
        from which the requested transition exists, otherwise
        `ERR_INVALID_STATE`"
        PRD: "Checkout, performed by the `EquipmentChair`, moves the
        reservation `RESERVED → CHECKED_OUT` and simultaneously moves the
        telescope `RESERVED → ON_LOAN`"

        Design: Corner/state_machines/checkout_from_checked_out_invalid
        """
        member, scope, _cert = setup_member_with_cert_and_scope(
            member_name="Double Check")
        loan = create_checked_out_loan(
            member, scope, "2026-08-01T00:00:00Z", "2026-08-05T00:00:00Z",
            checkout_clock="2026-08-02T12:00:00Z")
        assert loan["status"] == "CHECKED_OUT"

        resp = api.checkout_loan(loan["id"], CHAIR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

        after_loan = validate_success(api.get_loan_reservation(loan["id"], CHAIR))
        assert after_loan["status"] == "CHECKED_OUT", "No double checkout"
        after_scope = validate_success(api.get_telescope(scope["id"], CHAIR))
        assert after_scope["status"] == "ON_LOAN"


class TestLoanCreationGates:
    def test_invalid_window_rejected(self, api):
        """PRD: "Window sanity itself requires the start to be strictly
        before the end: a request whose `window_start` is not strictly
        earlier than `window_end`, or whose `period_start` is not strictly
        earlier than `period_end`, is rejected with `ERR_INVALID_WINDOW`
        (HTTP 422). This check applies to loan reservation creation,
        observing event creation, dark-sky report creation, and dues invoice
        issuance."

        Design: Corner/validations/invalid_window_rejected
        """
        member, scope, _cert = setup_member_with_cert_and_scope(
            member_name="Window Will")
        resp = api.create_loan_reservation(
            create_loan_reservation_payload(
                member["id"], scope["id"],
                "2026-08-05T00:00:00Z", "2026-08-05T00:00:00Z"),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)
        assert resp.status_code == 422

        scope_after = validate_success(api.get_telescope(scope["id"], CHAIR))
        assert scope_after["status"] == "AVAILABLE", (
            "A rejected reservation never materializes against the telescope")

    def test_collimation_due_blocks_reservation(self, api):
        """PRD: "a telescope whose `collimation_due_at` is not strictly
        later than the logical clock cannot be reserved (§3.4), so an
        overdue-for-collimation instrument effectively self-grounds until a
        `COLLIMATION` ticket runs to completion."
        PRD: "Third, telescope reservability: the telescope must be in
        `AVAILABLE` status and its `collimation_due_at` must be strictly
        later than the logical clock; a telescope that is reserved, on loan,
        under maintenance, or due for collimation is rejected with
        `ERR_TELESCOPE_NOT_RESERVABLE` (HTTP 409)."
        PRD: "a read-only `collimation_due_at` initialized to its
        `created_at` plus 180 days — new inventory is assumed freshly
        collimated."

        Design: Corner/validations/collimation_due_blocks_reservation
        """
        # Dues paid through 2028 so the clock advance does not suspend.
        member, _tier, _inv, _pay = create_member_with_paid_dues(
            period_start="2026-08-01T00:00:00Z",
            period_end="2028-08-01T00:00:00Z",
            full_name="Colli Chris")
        scope = create_telescope(name="Uncollimated", equipment_class="REFLECTOR")
        create_certification(member["id"], "REFLECTOR",
                             "2028-08-01T00:00:00Z")
        # Scope created at default clock 2026-08-01 -> due 2027-01-28.
        set_clock("2027-02-01T00:00:00Z")

        resp = api.create_loan_reservation(
            create_loan_reservation_payload(
                member["id"], scope["id"],
                "2027-02-05T00:00:00Z", "2027-02-07T00:00:00Z"),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_TELESCOPE_NOT_RESERVABLE)
        assert resp.status_code == 409

        scope_after = validate_success(api.get_telescope(scope["id"], CHAIR))
        assert scope_after["status"] == "AVAILABLE", (
            "The collimation gate rejects without changing telescope status")

    def test_err_loan_cap_reached_triggerable(self, api):
        """PRD: "Fifth and last, the tier's concurrency cap: the count of
        the member's non-terminal reservations — those in `RESERVED`,
        `CHECKED_OUT`, or `OVERDUE` — must be strictly below the tier's
        `max_concurrent_loans` before another is created; at or over the cap
        the creation is rejected with `ERR_LOAN_CAP_REACHED` (HTTP 422)."

        Design: Corner/errors/err_loan_cap_reached_triggerable
        """
        member, scope1, _cert = setup_member_with_cert_and_scope(
            member_name="Cap Carl",
            tier_kwargs={"code": "STUDENT", "annual_dues_cents": 60000,
                         "observatory_access_level": 1, "loan_privilege": True,
                         "max_concurrent_loans": 1})
        scope2 = create_telescope(name="Cap S2", equipment_class="REFRACTOR")
        create_reserved_loan(member, scope1, "2026-08-05T00:00:00Z",
                             "2026-08-07T00:00:00Z")

        resp = api.create_loan_reservation(
            create_loan_reservation_payload(
                member["id"], scope2["id"],
                "2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z"),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_LOAN_CAP_REACHED)
        assert resp.status_code == 422

        scope2_after = validate_success(api.get_telescope(scope2["id"], CHAIR))
        assert scope2_after["status"] == "AVAILABLE"
