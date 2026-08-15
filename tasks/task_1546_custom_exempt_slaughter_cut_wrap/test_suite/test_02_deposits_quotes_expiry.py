"""Deposit quotes, deposit payment rules, cancellation refunds, expiry sweep.

Covers the STANDARD vs ELEVATED deposit variants, insufficient-deposit
rejection, double-confirm rejection, the seven-day cancel refund boundary,
deposit-window expiry via run-daily, immediate visibility after payment, and
the run-daily output lists.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_appointment,
    book_and_confirm,
    create_appointment_payload,
    create_capacity_day,
    create_customer,
    earn_no_show_strike,
    get_appointment,
    get_capacity_day_by_date,
    get_customer,
    get_success_data,
    list_appointment_animals,
    make_customer_headers,
    pay_deposit_payload,
    set_logical_clock,
    validate_error,
    validate_success,
)

OP = TEST_USERS["operator_headers"]


class TestDepositQuoteVariants:
    def _setup_active_and_elevated_customers(self):
        """c1 stays ACTIVE; c2 earns one no-show strike on 2026-08-15.
        Fresh capacity days for the probe bookings satisfy the 14-day lead
        from the post-strike clock (2026-08-15)."""
        c1 = create_customer("Ann Orr", "555-0101", "ann@x.com")
        c2 = create_customer("Bob Venn", "555-0102", "bob@x.com")
        earn_no_show_strike(c2["id"], "2026-08-15", species="BEEF", head_count=1)
        day1 = create_capacity_day("2026-08-30", 1)
        day2 = create_capacity_day("2026-08-31", 1)
        return c1, c2, day1, day2

    def test_standard_deposit_quote_flat_per_head(self, api):
        """PRD §3.1: "For an `ACTIVE` customer the quote is a flat per-head
        rate by species multiplied by the head count: 15000 cents per head for
        `BEEF`, 7500 for `HOG`, and 5000 for either `LAMB` or `GOAT`."

        Design: Difficulty/dual_variant_calc/deposit_flat_vs_elevated_quote
        """
        c1, _c2, day1, _day2 = self._setup_active_and_elevated_customers()
        resp = api.create_appointment(
            create_appointment_payload(c1["id"], day1["id"], "BEEF", 1),
            make_customer_headers(c1["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["deposit_amount_cents"] == 15000, (
            "ACTIVE customer gets the STANDARD flat per-head quote"
        )

    def test_elevated_deposit_quote_half_estimated_value(self, api):
        """PRD §3.1: "For a customer carrying a strike — standing
        `ELEVATED_DEPOSIT` — the quote instead estimates the value of the work
        to be performed ... the deposit is one half of the resulting estimated
        value, rounded half-up to a whole cent."
        PRD §3.1: "one strike yields `ELEVATED_DEPOSIT`".

        BEEF 1 head: estimated hanging 1200 * 0.62 = 744 lb -> tiered
        200*95 + 544*85 = 65240; + slaughter 12000 = 77240; half = 38620.

        Design: Difficulty/dual_variant_calc/deposit_flat_vs_elevated_quote
        """
        c1, c2, day1, day2 = self._setup_active_and_elevated_customers()
        standard = validate_success(
            api.create_appointment(
                create_appointment_payload(c1["id"], day1["id"], "BEEF", 1),
                make_customer_headers(c1["id"]),
            ),
            expected_status=201,
        )
        elevated = validate_success(
            api.create_appointment(
                create_appointment_payload(c2["id"], day2["id"], "BEEF", 1),
                make_customer_headers(c2["id"]),
            ),
            expected_status=201,
        )
        assert standard["deposit_amount_cents"] == 15000
        assert elevated["deposit_amount_cents"] == 38620, (
            "ELEVATED_DEPOSIT customer gets half the estimated "
            "processing+slaughter value"
        )
        assert standard["deposit_amount_cents"] != elevated["deposit_amount_cents"]
        assert get_customer(c2["id"])["status"] == "ELEVATED_DEPOSIT"


class TestDepositPayment:
    def test_deposit_partial_payment_rejected(self, api):
        """PRD §3.2: "the payment must be at least the remaining deposit due —
        `deposit_amount_cents` minus whatever `deposit_paid_cents` has already
        accumulated — or it is refused with `ERR_DEPOSIT_INSUFFICIENT`."

        Design: Corner/validations/deposit_partial_payment_rejected
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 1)
        appointment = book_appointment(customer["id"], day["id"], "BEEF", 1)
        assert appointment["deposit_amount_cents"] == 15000
        resp = api.pay_deposit(
            appointment["id"], pay_deposit_payload(10000),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT, expected_status=402)
        after = get_appointment(appointment["id"])
        assert after["status"] == "PENDING_DEPOSIT"
        assert after["deposit_paid_cents"] == 0
        assert list_appointment_animals(appointment["id"]) == [], (
            "no animals may be created by a rejected deposit payment"
        )

    def test_appointment_pay_deposit_after_confirm_rejected(self, api):
        """PRD §3.2: "A successful payment adds the paid amount to
        `deposit_paid_cents`, moves the appointment from `PENDING_DEPOSIT` to
        `CONFIRMED`, and creates one Animal row per booked head".
        PRD §2.8: "then state-transition legality including terminal-state
        lockdown (`ERR_INVALID_STATE`, HTTP 409)".

        Design: Corner/state_machines/appointment_pay_deposit_after_confirm_rejected
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 1)
        appointment, animals = book_and_confirm(customer["id"], day["id"], "BEEF", 1)
        resp = api.pay_deposit(
            appointment["id"], pay_deposit_payload(15000),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = get_appointment(appointment["id"])
        assert after["deposit_paid_cents"] == 15000, (
            "rejected second payment must not add to deposit_paid_cents"
        )
        assert len(list_appointment_animals(appointment["id"])) == 1


class TestCancelRefundBoundary:
    def test_cancel_refund_window_boundary(self, api):
        """PRD §3.2: "if the whole-day count from the current date to
        `appointment_date` is at least seven, `refund_cents` is the full
        `deposit_paid_cents`; fewer than seven days out, the deposit is
        forfeited and `refund_cents` is zero."
        PRD §3.2: "A confirmed cancellation voids each expected animal, and
        each voided animal releases one head of capacity back to the day."

        Design: Corner/calculations/cancel_refund_window_boundary
        """
        c1 = create_customer("Ann Orr", "555-0101", "ann@x.com")
        c2 = create_customer("Bob Venn", "555-0102", "bob@x.com")
        day = create_capacity_day("2026-08-20", 2)
        appt_a, _ = book_and_confirm(c1["id"], day["id"], "BEEF", 1)
        appt_b, _ = book_and_confirm(c2["id"], day["id"], "BEEF", 1)
        # Exactly 7 days before the appointment date: full refund.
        set_logical_clock("2026-08-13T00:00:00Z")
        cancelled_a = validate_success(
            api.cancel_appointment(appt_a["id"], make_customer_headers(c1["id"]))
        )
        assert cancelled_a["status"] == "CANCELLED"
        assert cancelled_a["refund_cents"] == 15000
        # 6 days before: deposit forfeited.
        set_logical_clock("2026-08-14T00:00:00Z")
        cancelled_b = validate_success(
            api.cancel_appointment(appt_b["id"], make_customer_headers(c2["id"]))
        )
        assert cancelled_b["status"] == "CANCELLED"
        assert cancelled_b["refund_cents"] == 0
        # Both cancellations voided their EXPECTED animals and freed the day.
        for appt in (appt_a, appt_b):
            animals = list_appointment_animals(appt["id"])
            assert len(animals) == 1 and animals[0]["status"] == "VOIDED"
        assert get_capacity_day_by_date("2026-08-20")["booked_head"] == 0


class TestExpirySweep:
    def test_pending_appointment_expires_via_run_daily(self, api):
        """PRD §3.2: "If the logical clock passes `deposit_due_at` while the
        appointment remains `PENDING_DEPOSIT`, the daily sweep moves it to
        `EXPIRED`, releases its head count back to the day, and charges no
        strike — no animals ever existed and no money changed hands."

        Design: Corner/state_machines/pending_appointment_expires_via_run_daily
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 2)
        appointment = book_appointment(customer["id"], day["id"], "BEEF", 1)
        # deposit_due_at = created_at + 48h = 2026-08-03T00:00:00Z.
        # At exactly the due instant the clock has not passed it: survives.
        set_logical_clock("2026-08-03T00:00:00Z")
        sweep1 = get_success_data(api.run_daily(OP))
        assert appointment["id"] not in sweep1["expired_appointment_ids"]
        assert get_appointment(appointment["id"])["status"] == "PENDING_DEPOSIT"
        # One second past the due instant: expired, capacity released, no strike.
        set_logical_clock("2026-08-03T00:00:01Z")
        sweep2 = get_success_data(api.run_daily(OP))
        assert appointment["id"] in sweep2["expired_appointment_ids"]
        assert get_appointment(appointment["id"])["status"] == "EXPIRED"
        assert get_capacity_day_by_date("2026-08-20")["booked_head"] == 0
        assert get_customer(customer["id"])["no_show_strikes"] == 0

    def test_run_daily_output_lists_swept_ids(self, api):
        """PRD §3.8: "The sweep responds with three lists —
        `expired_appointment_ids`, `no_show_appointment_ids`, and
        `abandoned_storage_ids` — so the front desk can see exactly what the
        pass touched."

        Design: Corner/endpoints/run_daily_output_lists_swept_ids
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 1)
        appointment = book_appointment(customer["id"], day["id"], "BEEF", 1)
        sweep = get_success_data(api.run_daily(OP))
        assert sweep["expired_appointment_ids"] == []
        assert sweep["no_show_appointment_ids"] == []
        assert sweep["abandoned_storage_ids"] == []
        assert get_appointment(appointment["id"])["status"] == "PENDING_DEPOSIT"


class TestImmediateConsistency:
    def test_immediate_visibility_after_confirm(self, api):
        """PRD §3.2: "A successful payment adds the paid amount to
        `deposit_paid_cents`, moves the appointment from `PENDING_DEPOSIT` to
        `CONFIRMED`, and creates one Animal row per booked head, each in
        `EXPECTED` status with its `species` copied from the appointment and
        its `appointment_id` pointing back to the booking."
        PRD §3.1: "The day's `booked_head` immediately increases by
        `head_count`".

        Design: Corner/consistency_model/immediate_visibility_after_confirm
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 2)
        appointment = book_appointment(customer["id"], day["id"], "BEEF", 2)
        # The reservation is visible from booking time.
        assert get_capacity_day_by_date("2026-08-20")["booked_head"] == 2
        paid = validate_success(
            api.pay_deposit(
                appointment["id"], pay_deposit_payload(30000),
                make_customer_headers(customer["id"]),
            )
        )
        assert paid["status"] == "CONFIRMED"
        animals = list_appointment_animals(appointment["id"])
        assert len(animals) == 2
        for animal in animals:
            assert animal["status"] == "EXPECTED"
            assert animal["species"] == "BEEF"
            assert animal["appointment_id"] == appointment["id"]
        # Confirming changes nothing about the day's aggregate.
        assert get_capacity_day_by_date("2026-08-20")["booked_head"] == 2
