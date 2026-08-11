"""Invoice pricing: PROVISIONAL vs FINAL billable volume, satisfaction-credit
boundary, and the recurrence discount."""
from test_helpers import (
    add_claim,
    assign_therapist,
    cancel_claim,
    check_in_claim,
    complete_booking,
    complete_claim,
    create_invoice,
    create_wellness_program,
    drive_booking_in_progress,
    get_booking,
    list_booking_chairs,
    open_booking,
    setup_completed_booking,
    setup_in_progress_booking,
    setup_region_account_therapist,
    sign_waiver_for_claim,
    submit_survey,
    validate_success,
)


def _in_progress_with_mixed_claims(api):
    """IN_PROGRESS booking (120-min window, 15-min slots, 200c/min) with three
    claims: two COMPLETED, one CHECKED_IN. booked = 45, delivered = 30."""
    ctx = setup_in_progress_booking(
        num_claims=3,
        claims_checked_in=3,
        booking_overrides={"window_duration_minutes": 120},
        therapist_overrides={"max_minutes_per_day": 2000},
    )
    complete_claim(ctx, ctx["claims"][0]["id"])
    complete_claim(ctx, ctx["claims"][1]["id"])
    ctx["booking"] = get_booking(ctx, ctx["booking"]["id"])
    return ctx


class TestProvisionalVsFinalChairMinutes:
    def test_provisional_invoice_bills_booked_chair_minutes(self, api):
        """PRD §3.8: "Under `PROVISIONAL`, available while the booking is
        `CONFIRMED` or `IN_PROGRESS` for deposit-style pre-billing as well as
        for what-if previews, the billable volume `chair_minutes_billed` is
        the booking's `booked_chair_minutes`. Under `FINAL`, used for
        `COMPLETED` or `CANCELLED` bookings, it is the booking's
        `delivered_chair_minutes` — zero for a cancelled booking, where the
        cancellation fee dominates."
        PRD §3.8: "The invoice's `subtotal_cents` is the billable volume
        multiplied by the booking's `per_minute_rate_cents` — exact integer
        arithmetic, with no rounding."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_chair_minutes
        """
        ctx = _in_progress_with_mixed_claims(api)
        assert ctx["booking"]["booked_chair_minutes"] == 45
        assert ctx["booking"]["delivered_chair_minutes"] == 30
        invoice = create_invoice(ctx, ctx["booking"]["id"], "PROVISIONAL")
        assert invoice["chair_minutes_billed"] == 45, (
            f"PROVISIONAL reads booked_chair_minutes: expected 45, "
            f"got {invoice['chair_minutes_billed']}"
        )
        assert invoice["subtotal_cents"] == 45 * 200

    def test_final_invoice_bills_delivered_chair_minutes(self, api):
        """PRD §3.8: "Under `PROVISIONAL`, available while the booking is
        `CONFIRMED` or `IN_PROGRESS` for deposit-style pre-billing as well as
        for what-if previews, the billable volume `chair_minutes_billed` is
        the booking's `booked_chair_minutes`. Under `FINAL`, used for
        `COMPLETED` or `CANCELLED` bookings, it is the booking's
        `delivered_chair_minutes` — zero for a cancelled booking, where the
        cancellation fee dominates."
        PRD §3.8: "The invoice's `subtotal_cents` is the billable volume
        multiplied by the booking's `per_minute_rate_cents` — exact integer
        arithmetic, with no rounding."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_chair_minutes
        """
        ctx = setup_in_progress_booking(
            num_claims=3,
            claims_completed=2,
            booking_overrides={"window_duration_minutes": 120},
            therapist_overrides={"max_minutes_per_day": 2000},
        )
        # claims 0,1 COMPLETED and claim 2 CLAIMED: booked = 45, delivered = 30.
        assert ctx["booking"]["booked_chair_minutes"] == 45
        assert ctx["booking"]["delivered_chair_minutes"] == 30
        provisional = create_invoice(ctx, ctx["booking"]["id"], "PROVISIONAL")
        assert provisional["chair_minutes_billed"] == 45
        validate_success(api.void_invoice(provisional["id"], ctx["admin"]))
        # FINAL is used for COMPLETED or CANCELLED bookings (PRD §3.8), so
        # resolve the outstanding claim and close the booking out first.
        cancel_claim(ctx, ctx["claims"][2]["id"])
        complete_booking(ctx, ctx["booking"]["id"])
        invoice = create_invoice(ctx, ctx["booking"]["id"], "FINAL")
        assert invoice["chair_minutes_billed"] == 30, (
            f"FINAL reads delivered_chair_minutes: expected 30, "
            f"got {invoice['chair_minutes_billed']}"
        )
        assert invoice["subtotal_cents"] == 30 * 200
        assert invoice["chair_minutes_billed"] != provisional["chair_minutes_billed"], (
            "The two variants must disagree on the same booking data"
        )


class TestSatisfactionCreditBoundary:
    def test_satisfaction_credit_tier_at_exactly_2_00(self, api):
        """PRD §3.8: "An average strictly below 2.00 earns a credit of
        twenty-five percent of the subtotal, floored to whole cents; an
        average of 2.00 or higher but below 3.00 earns ten percent; an
        average of 3.00 or higher earns nothing. The boundary is exact — an
        average of 1.99 earns twenty-five percent while an average of exactly
        2.00 earns only ten."

        Design: Corner/calculations/satisfaction_credit_tier_at_exactly_2_00
        """
        ctx = setup_completed_booking(num_claims_completed=3)
        for claim, rating in zip(ctx["claims"], (1, 2, 3)):
            submit_survey(ctx, claim["id"], rating)
        # avg = (1+2+3)/3 = 2.00 exactly -> 10% tier. Subtotal = 3*15*200 = 9000.
        invoice = create_invoice(ctx, ctx["booking"]["id"], "FINAL")
        assert invoice["subtotal_cents"] == 9000
        assert invoice["satisfaction_credit_cents"] == 900, (
            f"avg_x100 == 200 lands in the 10% tier: expected 900, "
            f"got {invoice['satisfaction_credit_cents']}"
        )


class TestRecurrenceDiscount:
    def test_recurrence_discount_applied_on_recurring_occurrence(self, api):
        """PRD §3.8: "The recurrence tier is then read off the undiscounted
        subtotal: an `EVENT` booking is `STANDARD` and its
        `recurrence_discount_cents` is 0; a `RECURRING_OCCURRENCE` booking
        whose wellness program has not been `TERMINATED` is `RECURRING`, and
        its discount is the subtotal multiplied by the program's
        `recurrence_discount_pct`, floored to whole cents."

        Design: Corner/calculations/recurrence_discount_applied_on_recurring_occurrence
        """
        ctx = setup_region_account_therapist(
            therapist_overrides={"max_minutes_per_day": 2000},
        )
        program = create_wellness_program(
            ctx, name="WP", cadence="WEEKLY", chair_count=1, slot_minutes=15,
            window_start_time="10:00", window_duration_minutes=60,
            recurrence_discount_pct=0.10,
        )
        booking = validate_success(
            api.materialize_occurrence(
                program["id"], {"event_date": "2026-06-10"}, ctx["organizer"],
            ), expected_status=201,
        )
        assert booking["booking_kind"] == "RECURRING_OCCURRENCE"
        assert booking["wellness_program_id"] == program["id"]
        booking, chairs = open_booking(ctx, booking["id"])
        assign_therapist(ctx, chairs[0]["id"], ctx["therapist"]["id"])
        chairs = list_booking_chairs(ctx, booking["id"])
        drive_booking_in_progress(ctx, booking["id"], chairs)
        for i in range(2):
            claim = add_claim(ctx, chairs[0]["id"], f"R{i}", f"r{i}@x")
            sign_waiver_for_claim(ctx, claim["id"], booking["id"], claim["recipient_email"])
            check_in_claim(ctx, claim["id"])
            complete_claim(ctx, claim["id"])
        complete_booking(ctx, booking["id"])
        invoice = create_invoice(ctx, booking["id"], "FINAL")
        expected_discount = (invoice["subtotal_cents"] * 10) // 100
        assert invoice["recurrence_discount_cents"] == expected_discount, (
            f"Discount must be floor(subtotal * 0.10) = {expected_discount}, "
            f"got {invoice['recurrence_discount_cents']}"
        )
        assert invoice["recurrence_discount_cents"] > 0

    def test_event_booking_invoice_has_zero_recurrence_discount(self, api):
        """PRD §3.8: "The recurrence tier is then read off the undiscounted
        subtotal: an `EVENT` booking is `STANDARD` and its
        `recurrence_discount_cents` is 0; a `RECURRING_OCCURRENCE` booking
        whose wellness program has not been `TERMINATED` is `RECURRING`, and
        its discount is the subtotal multiplied by the program's
        `recurrence_discount_pct`, floored to whole cents."

        Design: Corner/calculations/recurrence_discount_applied_on_recurring_occurrence
        """
        ctx = setup_completed_booking(num_claims_completed=1)
        invoice = create_invoice(ctx, ctx["booking"]["id"], "FINAL")
        assert ctx["booking"]["booking_kind"] == "EVENT"
        assert invoice["recurrence_discount_cents"] == 0
