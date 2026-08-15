"""Loaner fleet program: reservation windows, overlap semantics, checkout and
OCC-guarded return, and the order-cancellation cascade."""
from test_helpers import (
    ApiErrorId,
    assert_loaner_assignment,
    get_assignment,
    get_customer,
    get_loaner,
    make_assignment,
    make_customer_headers,
    make_loaner,
    set_clock,
    setup_checked_out_assignment,
    setup_order_in_scope_approval,
    setup_unit_with_order,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestWindowValidation:
    def test_zero_length_window_rejected(self, api, intake_coordinator_headers):
        """PRD §3.6: "The window must be non-empty — an `end_date` at or
        before `start_date` is rejected with `ERR_INVALID_WINDOW`."

        Design: Corner/validations/loaner_window_end_not_after_start_rejected
        """
        ctx = setup_unit_with_order(serial_number="GBX-WIN")
        loaner = make_loaner(serial_number="LN-WIN")
        resp = api.create_loaner_assignment(
            loaner["id"],
            {"reman_order_id": ctx["order"]["id"], "start_date": "2026-08-10",
             "end_date": "2026-08-10"},
            intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)

    def test_checkout_before_window_start_rejected(
            self, api, intake_coordinator_headers):
        """PRD §3.6: "At the window start the coordinator checks the loaner
        out (`RESERVED → CHECKED_OUT`), which requires the loaner to
        currently be `AVAILABLE` (`ERR_LOANER_UNAVAILABLE`) and the current
        date — per the logical clock of §2.8 — to be on or after `start_date`
        (`ERR_LOANER_WINDOW_FUTURE`)".

        Design: Corner/validations/checkout_before_window_start_rejected
        """
        set_clock("2026-08-05T00:00:00Z")
        ctx = setup_unit_with_order(serial_number="GBX-FUT")
        loaner = make_loaner(serial_number="LN-FUT")
        assignment = make_assignment(loaner["id"], ctx["order"]["id"],
                                     start_date="2026-08-10",
                                     end_date="2026-08-20")
        resp = api.checkout_loaner(assignment["id"], intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_LOANER_WINDOW_FUTURE.value)
        assert get_assignment(assignment["id"])["status"] == "RESERVED"


class TestOverlapSemantics:
    def test_partial_overlap_rejected(self, api, intake_coordinator_headers):
        """PRD §3.6: "the reservation conflicts with an existing
        non-cancelled assignment on the same loaner exactly when the existing
        window starts before the requested `end_date` and the requested
        `start_date` starts before the existing window's end — touching
        back-to-back windows are allowed — and a true conflict is rejected
        with `ERR_LOANER_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/loaner_window_true_overlap_rejected
        """
        ctx1 = setup_unit_with_order(serial_number="GBX-O1")
        ctx2 = setup_unit_with_order(serial_number="GBX-O2",
                                     legal_name="Overlap Co Two")
        loaner = make_loaner(serial_number="LN-OV")
        first = make_assignment(loaner["id"], ctx1["order"]["id"],
                                start_date="2026-08-10", end_date="2026-08-20")

        resp = api.create_loaner_assignment(
            loaner["id"],
            {"reman_order_id": ctx2["order"]["id"], "start_date": "2026-08-15",
             "end_date": "2026-08-25"},
            intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_LOANER_OVERLAP.value)
        assert get_assignment(first["id"])["status"] == "RESERVED"

    def test_containing_overlap_rejected(self, api, intake_coordinator_headers):
        """PRD §3.6: "the reservation conflicts with an existing
        non-cancelled assignment on the same loaner exactly when the existing
        window starts before the requested `end_date` and the requested
        `start_date` starts before the existing window's end".

        Design: Difficulty/resource_temporal_overlap/loaner_window_true_overlap_rejected
        """
        ctx1 = setup_unit_with_order(serial_number="GBX-O3")
        ctx2 = setup_unit_with_order(serial_number="GBX-O4",
                                     legal_name="Contain Co Two")
        loaner = make_loaner(serial_number="LN-OV2")
        make_assignment(loaner["id"], ctx1["order"]["id"],
                        start_date="2026-08-10", end_date="2026-08-20")

        resp = api.create_loaner_assignment(
            loaner["id"],
            {"reman_order_id": ctx2["order"]["id"], "start_date": "2026-08-01",
             "end_date": "2026-08-30"},
            intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_LOANER_OVERLAP.value)


class TestAdjacency:
    def test_adjacent_window_after_existing_accepted(
            self, api, intake_coordinator_headers):
        """PRD §3.6: "The coordinator then reserves a loaner for a specific
        order by posting the `reman_order_id` it covers together with a
        window: `start_date` inclusive and `end_date` exclusive, a half-open
        interval." and "touching back-to-back windows are allowed".

        Design: Difficulty/boundary_precision_check/loaner_adjacent_windows_zero_gap_accepted
        """
        ctx1 = setup_unit_with_order(serial_number="GBX-A1")
        ctx2 = setup_unit_with_order(serial_number="GBX-A2",
                                     legal_name="Adj Co Two")
        loaner = make_loaner(serial_number="LN-ADJ")
        first = make_assignment(loaner["id"], ctx1["order"]["id"],
                                start_date="2026-08-10", end_date="2026-08-20")

        # Half-open [2026-08-20, 2026-08-30) shares zero days with the
        # existing [2026-08-10, 2026-08-20).
        resp = api.create_loaner_assignment(
            loaner["id"],
            {"reman_order_id": ctx2["order"]["id"], "start_date": "2026-08-20",
             "end_date": "2026-08-30"},
            intake_coordinator_headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "RESERVED"
        assert_loaner_assignment(data)
        assert get_assignment(first["id"])["status"] == "RESERVED"

    def test_adjacent_window_before_existing_accepted(
            self, api, intake_coordinator_headers):
        """PRD §3.6: "Overlap is judged on those half-open windows: the
        reservation conflicts with an existing non-cancelled assignment on
        the same loaner exactly when the existing window starts before the
        requested `end_date` and the requested `start_date` starts before the
        existing window's end — touching back-to-back windows are allowed".

        Design: Difficulty/boundary_precision_check/loaner_adjacent_windows_zero_gap_accepted
        """
        ctx1 = setup_unit_with_order(serial_number="GBX-A3")
        ctx2 = setup_unit_with_order(serial_number="GBX-A4",
                                     legal_name="Adj Co Four")
        loaner = make_loaner(serial_number="LN-ADJ2")
        make_assignment(loaner["id"], ctx1["order"]["id"],
                        start_date="2026-08-10", end_date="2026-08-20")

        # [2026-08-01, 2026-08-10) ends exactly when the existing begins.
        resp = api.create_loaner_assignment(
            loaner["id"],
            {"reman_order_id": ctx2["order"]["id"], "start_date": "2026-08-01",
             "end_date": "2026-08-10"},
            intake_coordinator_headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "RESERVED"


class TestCheckoutReturnInvariant:
    def test_checkout_return_round_trip_restores_availability(
            self, api, intake_coordinator_headers, service_manager_headers):
        """PRD §3.6: "checkout flips the loaner itself to `CHECKED_OUT`" and
        "a successful return flips the loaner back to `AVAILABLE` and
        increments the assignment's `version` by one."

        Design: Difficulty/compensating_invariant/loaner_checkout_return_conserves_unit_availability
        """
        ctx = setup_checked_out_assignment(
            start_date="2026-08-01", end_date="2026-08-10",
            clock="2026-08-02T00:00:00Z", serial_number="GBX-LN1",
            loaner_serial="LN-INV")
        loaner_id = ctx["loaner"]["id"]
        assignment = ctx["assignment"]
        assert assignment["status"] == "CHECKED_OUT"
        assert get_loaner(loaner_id)["status"] == "CHECKED_OUT"

        data = validate_success(
            api.return_loaner(assignment["id"], assignment["version"],
                              intake_coordinator_headers))
        assert data["status"] == "RETURNED"
        # The round trip restores the loaner's availability exactly.
        assert get_loaner(loaner_id)["status"] == "AVAILABLE"

    def test_return_increments_assignment_version_by_one(
            self, api, intake_coordinator_headers):
        """PRD §3.6: "a successful return flips the loaner back to
        `AVAILABLE` and increments the assignment's `version` by one."

        Design: Difficulty/compensating_invariant/loaner_checkout_return_conserves_unit_availability
        """
        ctx = setup_checked_out_assignment(
            start_date="2026-08-01", end_date="2026-08-10",
            clock="2026-08-02T00:00:00Z", serial_number="GBX-LN2",
            loaner_serial="LN-INV2")
        assignment = ctx["assignment"]
        before = assignment["version"]

        data = validate_success(
            api.return_loaner(assignment["id"], before,
                              intake_coordinator_headers))
        assert data["version"] == before + 1
        assert data["status"] == "RETURNED"


class TestOccOnReturn:
    def test_return_stale_version_rejected_then_fresh_version_succeeds(
            self, api, intake_coordinator_headers):
        """PRD §2.7: "The loaner-return write, `POST
        /reman/loaner-assignments/{assignmentId}/return`, requires a
        non-optional `expected_assignment_version` field carrying the
        `version` of the LoanerAssignment as the client last observed it. A
        mismatch with the assignment's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.6: "A reservation may also be extended while `RESERVED` or
        `CHECKED_OUT` by supplying a `new_end_date`; the overlap rule is
        re-validated against the extended window and the assignment's
        `version` increments."

        Design: Corner/cross_cutting_layers/occ_correct_version_succeeds
        """
        ctx = setup_checked_out_assignment(
            start_date="2026-08-01", end_date="2026-08-10",
            clock="2026-08-02T00:00:00Z", serial_number="GBX-OC2",
            loaner_serial="LN-OCC")
        assignment = ctx["assignment"]
        observed_version = assignment["version"]

        # An intervening extend mutates the assignment, bumping its version.
        extended = validate_success(
            api.extend_loaner(assignment["id"], "2026-08-12",
                              intake_coordinator_headers))
        assert extended["version"] == observed_version + 1

        # The stale return is rejected; the assignment is still CHECKED_OUT
        # so the state precondition passes and OCC is the failing check.
        resp = api.return_loaner(assignment["id"], observed_version,
                                 intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
        assert get_assignment(assignment["id"])["status"] == "CHECKED_OUT"

        # Retry with the fresh version succeeds.
        data = validate_success(
            api.return_loaner(assignment["id"], extended["version"],
                              intake_coordinator_headers))
        assert data["status"] == "RETURNED"
        assert get_loaner(ctx["loaner"]["id"])["status"] == "AVAILABLE"


class TestCheckoutAvailability:
    def test_checkout_while_loaner_checked_out_rejected(
            self, api, intake_coordinator_headers):
        """PRD §3.6: "At the window start the coordinator checks the loaner
        out (`RESERVED → CHECKED_OUT`), which requires the loaner to
        currently be `AVAILABLE` (`ERR_LOANER_UNAVAILABLE`)".

        Design: Corner/state_machines/checkout_while_loaner_checked_out_rejected
        """
        set_clock("2026-08-05T00:00:00Z")
        ctx1 = setup_unit_with_order(serial_number="GBX-U1")
        ctx2 = setup_unit_with_order(serial_number="GBX-U2",
                                     legal_name="Unavail Co Two")
        loaner = make_loaner(serial_number="LN-UNAV")
        first = make_assignment(loaner["id"], ctx1["order"]["id"],
                                start_date="2026-08-01", end_date="2026-08-10")
        api.checkout_loaner(first["id"], intake_coordinator_headers)
        second = make_assignment(loaner["id"], ctx2["order"]["id"],
                                 start_date="2026-08-11", end_date="2026-08-20")

        # The first assignment is still out (overdue, never returned) when
        # the second window opens.
        set_clock("2026-08-11T00:00:00Z")
        resp = api.checkout_loaner(second["id"], intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_LOANER_UNAVAILABLE.value)
        assert get_assignment(second["id"])["status"] == "RESERVED"
        assert get_loaner(loaner["id"])["status"] == "CHECKED_OUT"


class TestOrderCancelCascade:
    def test_cancel_frees_reserved_loaner_window(
            self, api, intake_coordinator_headers):
        """PRD §3.3: "The customer may cancel an order waiting in
        `SCOPE_APPROVAL`: its `PENDING` decisions flip to `SUPERSEDED`, any
        `RESERVED` loaner assignments held for the order flip to `CANCELLED`
        (freeing those loaner windows)".

        Design: Difficulty/transitive_cascade/order_cancel_cascades_loaner_assignment_then_window_freed
        """
        ctx = setup_order_in_scope_approval(serial_number="GBX-X1",
                                            legal_name="Cancel Co")
        order_id = ctx["order"]["id"]
        loaner = make_loaner(serial_number="LN-001")
        assignment = make_assignment(loaner["id"], order_id,
                                     start_date="2026-08-10",
                                     end_date="2026-08-20")

        resp = api.cancel_order(order_id,
                                make_customer_headers(ctx["customer"]["id"]))
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"

        # First hop: the RESERVED assignment is cancelled by the cascade.
        assert get_assignment(assignment["id"])["status"] == "CANCELLED"

        # Second hop: the freed window accepts a fresh reservation.
        resp = api.create_loaner_assignment(
            loaner["id"],
            {"reman_order_id": order_id, "start_date": "2026-08-10",
             "end_date": "2026-08-20"},
            intake_coordinator_headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "RESERVED"

    def test_cancel_from_scope_approval_supersedes_decisions_without_credit_debit(
            self, api, reman_engineer_headers):
        """PRD §3.3: "The customer may cancel an order waiting in
        `SCOPE_APPROVAL`: its `PENDING` decisions flip to `SUPERSEDED`, any
        `RESERVED` loaner assignments held for the order flip to `CANCELLED`
        (freeing those loaner windows), and — because a scope awaiting
        approval never entered the outstanding-exposure sum of §2.10 — no
        credit debit occurs."

        Design: Difficulty/transitive_cascade/order_cancel_cascades_loaner_assignment_then_window_freed
        """
        ctx = setup_order_in_scope_approval(serial_number="GBX-X2",
                                            legal_name="Cancel Two Co")
        order_id = ctx["order"]["id"]

        resp = api.cancel_order(order_id,
                                make_customer_headers(ctx["customer"]["id"]))
        assert validate_success(resp)["status"] == "CANCELLED"

        decisions, _ = validate_paginated(
            api.list_decisions(order_id, reman_engineer_headers))
        assert decisions
        assert all(d["approval_status"] == "SUPERSEDED" for d in decisions)

        # No credit debit: the scope never entered the exposure sum.
        customer = get_customer(ctx["customer"]["id"])
        assert customer["outstanding_approved_cents"] == 0
        assert customer["credit_hold"] is False
