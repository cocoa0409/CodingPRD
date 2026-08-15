"""Difficulty rule compensating_invariant: the seat-count invariant across a
mixed forward/compensating action sequence, and the cents invariant across the
drop -> void -> refund chain (PRD 2.5, 3.6, 3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_seat_conservation,
    drop_enrollment,
    first_invoice_for_enrollment,
    get_enrollment,
    get_invoice,
    get_offering,
    pay_invoice,
    refund_invoice,
    register_and_confirm,
    reinstate_enrollment,
    set_clock,
    setup_base,
    setup_mixed_enrollment_scenario,
    validate_error,
    withdraw_enrollment,
)


def _setup_seat_cycle():
    """Capacity 2: e1 REGISTERED, e2 REGISTERED, e3 WAITLISTED (seq 1)."""
    return setup_mixed_enrollment_scenario(capacity=2, num_students=3)


class TestSeatConservationAcrossCycles:
    def test_seat_counters_conserve_capacity_at_every_hop(self, api):
        """PRD 2.5: "The computed `seats_taken` is the count of `Enrollment`
        records on that offering whose status is `REGISTERED`; no other enrollment
        status consumes a seat. The computed `seats_available` is `capacity` minus
        `seats_taken`. The two sum to `capacity` at all times, so a reader who
        knows any two of the three numbers can derive the third."
        PRD 3.6: "Promotion moves that enrollment to `REGISTERED`, increments
        `seats_taken` by 1, increments the offering's `version` again (on top of
        the increment from the drop or withdraw that released the seat), and
        creates a new `Invoice` for the promoted enrollment per §3.7."

        Design: Difficulty/compensating_invariant/seat_conservation_across_cycles
        """
        ctx = _setup_seat_cycle()
        offering_id = ctx["offering"]["id"]
        after_confirms = get_offering(offering_id)
        assert after_confirms["seats_taken"] == 2
        assert_seat_conservation(after_confirms)

        # Hop 1: drop e1 — the freed seat immediately promotes e3.
        drop_enrollment(ctx["enrollments"][0]["id"])
        after_drop = get_offering(offering_id)
        assert after_drop["seats_taken"] == 2, (
            f"e3 was promoted into e1's seat: taken {after_drop['seats_taken']}"
        )
        assert after_drop["seats_available"] == 0
        assert_seat_conservation(after_drop)

        # Hop 2: withdraw e2 inside the withdraw window — no waitlist remains.
        set_clock("2026-09-12T00:00:00Z")
        withdraw_enrollment(ctx["enrollments"][1]["id"])
        after_withdraw = get_offering(offering_id)
        assert after_withdraw["seats_taken"] == 1
        assert_seat_conservation(after_withdraw)

        # Hop 3: reinstate e2 — the seat is re-taken.
        reinstate_enrollment(offering_id, ctx["enrollments"][1]["id"])
        after_reinstate = get_offering(offering_id)
        assert after_reinstate["seats_taken"] == 2
        assert after_reinstate["seats_available"] == 0
        assert_seat_conservation(after_reinstate)

    def test_enrollment_outcomes_after_the_cycle(self, api):
        """PRD 3.5: "The system assigns `waitlist_seq` as one more than the maximum
        existing `waitlist_seq` for the offering, starting at 1 for the first
        waitlisted enrollment; the sequence is per-offering monotonic and never
        reused."
        PRD 3.5: "A `CollegeRegistrar` may reinstate a `WITHDRAWN` enrollment,
        moving it back to `REGISTERED`."
        PRD 3.1: "Closing a term has a cascade: every `WAITLISTED` enrollment whose
        offering is tied to this term — through either its `college_term_id` or its
        `hs_term_id` — transitions to `EXPIRED`, retaining its `waitlist_seq`,
        which is never reused."

        Design: Difficulty/compensating_invariant/seat_conservation_across_cycles
        """
        ctx = _setup_seat_cycle()
        offering_id = ctx["offering"]["id"]
        e1, e2, e3 = ( enrollment["id"] for enrollment in ctx["enrollments"] )

        drop_enrollment(e1)
        promoted = get_enrollment(e3)
        assert promoted["status"] == "REGISTERED", (
            "The promotion fired while the offering was OPEN"
        )
        assert promoted["waitlist_seq"] == 1, "The sequence number is retained as audit"

        set_clock("2026-09-12T00:00:00Z")
        withdraw_enrollment(e2)
        assert get_enrollment(e2)["status"] == "WITHDRAWN"

        reinstated = reinstate_enrollment(offering_id, e2)
        assert reinstated["status"] == "REGISTERED", (
            "e2 returns to REGISTERED after the WITHDRAWN detour"
        )
        assert get_enrollment(e1)["status"] == "DROPPED"


class TestMoneyConservationFullRefundCycle:
    def _setup_fully_paid_then_dropped(self):
        ctx = setup_base()
        pair = register_and_confirm(ctx)
        invoice = first_invoice_for_enrollment(pair["enrollment"]["id"])
        pay_invoice(invoice["id"], "STATE", 90000)
        pay_invoice(invoice["id"], "FAMILY", 30000)
        assert get_invoice(invoice["id"])["status"] == "PAID"
        drop_enrollment(pair["enrollment"]["id"])  # default clock: drop window open
        ctx["enrollment"] = pair["enrollment"]
        ctx["invoice"] = get_invoice(invoice["id"])
        return ctx

    def test_drop_voids_the_fully_paid_invoice_with_full_estimate(self, api):
        """PRD 3.5: "It also settles the enrollment's invoice per §3.7 with
        `refund_pct` set to 100."
        PRD 3.7: "When `refund_pct` is 100 the invoice's `status` moves to
        `VOIDED`; when it is 50 the status is unchanged."
        PRD 3.7: "`refund_status` is set to `DUE` when the percentage is greater
        than 0 and the sum of payments on the invoice is greater than 0, and `NONE`
        otherwise."

        Design: Difficulty/compensating_invariant/money_conservation_full_refund_cycle
        """
        ctx = self._setup_fully_paid_then_dropped()
        invoice = ctx["invoice"]
        assert invoice["status"] == "VOIDED"
        assert invoice["refund_pct"] == 100
        assert invoice["refund_estimate_cents"] == 120000, (
            f"Estimate variant on billed shares: 120000 x 100%, got "
            f"{invoice['refund_estimate_cents']}"
        )
        assert invoice["refund_status"] == "DUE", (
            "90000 + 30000 had been paid, so the refund is DUE"
        )

    def test_refund_returns_exactly_the_money_in(self, api, bursar_headers):
        """PRD 3.7: "The settled `refund_paid_cents` is computed from amounts
        actually paid, not billed shares: it is the rounded state refund plus the
        rounded district refund plus a family remainder, where the rounded state
        refund is `paid_state_cents` multiplied by the percentage and divided by
        100 rounded half-up, the rounded district refund is `paid_district_cents`
        multiplied by the percentage and divided by 100 rounded half-up, and the
        family remainder is `paid_state_cents` plus `paid_district_cents` plus
        `paid_family_cents`, multiplied by the percentage and divided by 100 and
        rounded half-up, minus the rounded state refund, minus the rounded district
        refund."
        PRD 3.7: "When the invoice is fully paid the settled amount equals the
        estimate; when partially paid the settled amount is at most the estimate
        and the two diverge."

        Design: Difficulty/compensating_invariant/money_conservation_full_refund_cycle
        """
        ctx = self._setup_fully_paid_then_dropped()
        invoice = ctx["invoice"]

        settled = refund_invoice(invoice["id"])
        paid_total = (
            settled["paid_state_cents"]
            + settled["paid_district_cents"]
            + settled["paid_family_cents"]
        )
        assert paid_total == 120000
        assert settled["refund_paid_cents"] == 120000, (
            f"Conservation: refund_paid_cents ({settled['refund_paid_cents']}) "
            f"must equal the 120000 paid in and the 120000 billed"
        )
        assert settled["refund_paid_cents"] == settled["tuition_total_cents"]
        assert settled["refund_status"] == "PROCESSED"

        second = api.refund_invoice(invoice["id"], bursar_headers)
        validate_error(second, ApiErrorId.ERR_REFUND_NOT_DUE.value)
