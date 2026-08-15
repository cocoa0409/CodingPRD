"""Difficulty rule boundary_precision: the seat-count boundary at
seats_available == 1 vs == 0, and the inclusive drop-deadline boundary at the
exact deadline second (PRD 2.4, 3.5, 3.6)."""
from test_helpers import (
    ApiErrorId,
    drop_enrollment,
    first_invoice_for_enrollment,
    get_invoice,
    get_offering,
    list_invoices_for_enrollment,
    register_and_confirm,
    set_clock,
    setup_base,
    setup_mixed_enrollment_scenario,
    validate_error,
    withdraw_enrollment,
)


class TestSeatZeroVsOneBoundary:
    def test_first_confirm_at_exactly_one_seat_lands_registered(self, api):
        """PRD 3.5: "If every check passes and at least one seat is free, the
        enrollment moves to `REGISTERED`: `seats_taken` increases by 1, the
        offering's `version` increments, and an `Invoice` is created per §3.7 with
        `status` `ISSUED` and `refund_status` `NONE`."
        PRD 2.5: "The computed `seats_taken` is the count of `Enrollment` records
        on that offering whose status is `REGISTERED`; no other enrollment status
        consumes a seat."

        Design: Difficulty/boundary_precision/seat_zero_vs_one_boundary
        """
        ctx = setup_mixed_enrollment_scenario(capacity=1, num_students=1)
        enrollment = ctx["enrollments"][0]
        assert enrollment["status"] == "REGISTERED", (
            "seats_available was exactly 1 — the >= 1 boundary passes"
        )
        offering = get_offering(ctx["offering"]["id"])
        assert offering["seats_taken"] == 1
        assert offering["seats_available"] == 0

    def test_second_confirm_at_zero_seats_lands_waitlisted_without_error(self, api):
        """PRD 3.5: "If every check passes but `seats_available` is 0, the same
        request does not fail; it lands the enrollment in `WAITLISTED` instead."
        PRD 3.5: "The system assigns `waitlist_seq` as one more than the maximum
        existing `waitlist_seq` for the offering, starting at 1 for the first
        waitlisted enrollment; the sequence is per-offering monotonic and never
        reused."
        PRD 3.5: "No invoice is created for a `WAITLISTED` enrollment."

        Design: Difficulty/boundary_precision/seat_zero_vs_one_boundary
        """
        ctx = setup_mixed_enrollment_scenario(capacity=1, num_students=2)
        e1, e2 = ctx["enrollments"]
        assert e1["status"] == "REGISTERED"
        assert e2["status"] == "WAITLISTED", (
            f"seats_available was exactly 0 — the boundary fails WITHOUT an error, "
            f"got {e2['status']}"
        )
        assert e2["waitlist_seq"] == 1, "The first waitlist slot is 1"
        assert list_invoices_for_enrollment(e2["id"]) == [], (
            "No invoice may be created for a WAITLISTED enrollment"
        )
        offering = get_offering(ctx["offering"]["id"])
        assert offering["seats_taken"] == 1 and offering["seats_available"] == 0


class TestDropDeadlineExactSecondBoundary:
    def test_drop_at_exactly_the_effective_drop_deadline_succeeds(self, api):
        """PRD 2.4: "Three effective deadlines are derived from the pair by taking
        the earlier instant in each case: the effective add deadline is the earlier
        of `college_term.add_deadline` and `hs_term.add_deadline`; the effective
        drop deadline is the earlier of `college_term.drop_deadline` and
        `hs_term.drop_deadline`; the effective withdraw deadline is the earlier of
        `college_term.withdraw_deadline` and `hs_term.withdraw_deadline`."
        PRD 2.4: "Deadline boundaries are inclusive — an action taken at exactly
        the deadline instant passes, and an action taken after it fails."
        PRD 3.5: "the coordinator may drop the enrollment while the logical clock
        reads at or before the earlier of the two terms' `drop_deadline` values
        (else `ERR_DROP_WINDOW_CLOSED`, HTTP 409; an attempt from any status other
        than `REGISTERED` is `ERR_ENROLLMENT_INVALID_STATE`)."

        Design: Difficulty/boundary_precision/drop_deadline_exact_second_boundary
        """
        ctx = setup_base()
        pair = register_and_confirm(ctx)
        # min(college drop 2026-09-15, HS drop 2026-09-10) == 2026-09-10T00:00:00Z.
        set_clock("2026-09-10T00:00:00Z")
        dropped = drop_enrollment(pair["enrollment"]["id"])
        assert dropped["status"] == "DROPPED", (
            "now == the effective drop deadline exactly: the inclusive boundary "
            "passes"
        )

    def test_one_second_past_the_deadline_fails_and_only_withdraw_remains(self, api, coordinator_headers):
        """PRD 2.4: "Deadline boundaries are inclusive — an action taken at exactly
        the deadline instant passes, and an action taken after it fails."
        PRD 3.5: "The invoice is settled per §3.7 with a `refund_pct` of 50 when
        the clock reads at or before the college term's `drop_deadline` and 0
        otherwise — note that the college calendar alone governs the 50-percent
        compensation even though the high school calendar may have been what forced
        the withdraw, which is the cross-calendar mismatch window."

        Design: Difficulty/boundary_precision/drop_deadline_exact_second_boundary
        """
        ctx = setup_base()
        pair = register_and_confirm(ctx)
        invoice = first_invoice_for_enrollment(pair["enrollment"]["id"])
        set_clock("2026-09-10T00:00:01Z")  # one second past the HS drop deadline

        drop_response = api.drop_enrollment(pair["enrollment"]["id"], coordinator_headers)
        validate_error(drop_response, ApiErrorId.ERR_DROP_WINDOW_CLOSED.value)

        withdrawn = withdraw_enrollment(pair["enrollment"]["id"])
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["grade"] == "W"
        settled_invoice = get_invoice(invoice["id"])
        assert settled_invoice["refund_pct"] == 50, (
            f"Withdraw forced only by the HS calendar: 2026-09-10T00:00:01Z <= "
            f"college drop 2026-09-15 earns the 50-pct mismatch compensation, got "
            f"{settled_invoice['refund_pct']}"
        )
