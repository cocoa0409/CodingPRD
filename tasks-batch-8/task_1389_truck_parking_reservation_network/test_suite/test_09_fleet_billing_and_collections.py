"""Fleet billing: authorization gates, fiscal gates, invoicing math, payment
cascades, overdue collections, disputes, and write-offs."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_driver_authorization,
    assert_invoice,
    close_billing_period,
    create_active_authorization,
    create_booking_payload,
    create_reserved_booking,
    create_site_with_stalls,
    make_driver_headers,
    make_fleet_manager_headers,
    register_driver,
    run_site_ops,
    set_clock,
    settle_booking,
    setup_fleet_with_active_auth,
    setup_invoiced_fleet_booking,
    transition_authorization,
    request_authorization,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestInvoiceVolumeTier:

    def test_tier_keyed_on_gross_selects_two_percent(self):
        """PRD section 3.9: "The volume tier is keyed on the gross, never the
        net: gross of at least 500000 cents earns `discount_pct` 2, at least
        2000000 earns 5, and at least 5000000 earns 8, with anything less
        earning 0. The `discount_cents` is the gross times the percentage over
        one hundred, rounded half up; `net_cents` is gross minus discount".

        Design: Difficulty/combinatorial_formula/invoice_tier_keyed_on_gross_not_net
        """
        ctx = setup_invoiced_fleet_booking(base=500000,
                                           arrival_date="2026-08-14")
        invoice = ctx["invoice"]
        assert_invoice(invoice)
        assert invoice["gross_cents"] == 540000, (
            f"Friday night: rhu(500000 * 0.9 * 1.2); got "
            f"{invoice['gross_cents']}"
        )
        assert invoice["discount_pct"] == 2, \
            "the tier is keyed on gross 540000 >= 500000"
        assert invoice["discount_cents"] == 10800
        assert invoice["net_cents"] == 529200

    def test_due_date_is_period_end_plus_terms(self):
        """PRD section 3.9: "`due_date` is the last day of the period plus
        the fleet's `payment_terms_days`."
        PRD section 3.9: "Each member booking's `billing_status` moves
        `UNBILLED` → `INVOICED` and its id lands in the invoice's
        `booking_ids`".

        Design: Difficulty/combinatorial_formula/invoice_tier_keyed_on_gross_not_net
        """
        ctx = setup_invoiced_fleet_booking(base=500000,
                                           arrival_date="2026-08-14")
        invoice = ctx["invoice"]
        assert invoice["due_date"] == "2026-09-30", \
            "period end 2026-08-31 plus 30 payment terms days"
        assert ctx["booking"]["id"] in invoice["booking_ids"]
        resp = api_client.get_booking(ctx["booking"]["id"], ADMIN)
        assert validate_success(resp)["billing_status"] == "INVOICED"


class TestParallelBillingDimensions:

    def _setup_noshowed_fleet_booking(self):
        """A FLEET_BILL booking that no-shows (08-10), then its fee is swept
        into the 2026-08 invoice."""
        ctx = setup_fleet_with_active_auth(num_reservable=2,
                                           cdl_number="CDL-P-1")
        site, fleet, driver = ctx["site"], ctx["fleet"], ctx["driver"]
        booking = create_reserved_booking(
            driver["id"], site["id"], "2026-08-10", 1,
            payment_mode="FLEET_BILL", fleet_account_id=fleet["id"])
        set_clock("2026-08-10T16:00:01Z")
        run_site_ops(site["id"])
        set_clock("2026-09-01T00:00:00Z")
        invoice = close_billing_period(fleet["id"], "2026-08")
        return {"site": site, "fleet": fleet, "driver": driver,
                "booking": booking, "invoice": invoice}

    def test_lifecycle_terminal_billing_axis_advances(self):
        """PRD section 3.5: "Its billing dimension runs in parallel, from
        `UNBILLED` toward the terminal `PAID` or `WAIVED` (passing through
        `PARTIALLY_PAID` or `INVOICED` along the way), and the two dimensions
        evolve independently: a lifecycle-terminal booking still moves along
        `billing_status` as its fees are paid, invoiced, or waived."
        PRD section 3.9: "Closing a billing period takes a `period` in YYYY-MM
        form and sweeps up the fleet's `FLEET_BILL` bookings that are still
        `UNBILLED`, have a non-null `final_total_cents`, and settled —
        reached their terminal state — inside that calendar month."

        Design: Difficulty/non_linear_state_machine/booking_parallel_billing_survives_noshow
        """
        ctx = self._setup_noshowed_fleet_booking()
        resp = api_client.get_booking(ctx["booking"]["id"], ADMIN)
        booking = validate_success(resp)
        assert booking["status"] == "NO_SHOW", \
            "the lifecycle axis landed terminally"
        assert booking["billing_status"] == "INVOICED", \
            "the billing axis advanced independently of the terminal lifecycle"

    def test_noshow_fee_swept_into_invoice(self):
        """PRD section 3.5: "The fee is the full first pinned night's rate,
        never discounted, and `final_total_cents` equals it while
        `billing_status` stays `UNBILLED`."
        PRD section 3.9: "The invoice's `gross_cents` is the sum of those
        members' `final_total_cents` (for fee-only settlements such as
        no-shows and late cancellations, that final total is exactly the
        fee)."

        Design: Difficulty/non_linear_state_machine/booking_parallel_billing_survives_noshow
        """
        ctx = self._setup_noshowed_fleet_booking()
        resp = api_client.get_booking(ctx["booking"]["id"], ADMIN)
        booking = validate_success(resp)
        assert booking["fee_cents"] == 4500
        assert booking["final_total_cents"] == 4500
        invoice = ctx["invoice"]
        assert invoice["gross_cents"] == 4500
        assert invoice["discount_pct"] == 0, "gross 4500 earns no volume tier"


class TestOverdueCascade:

    def _setup_overdue_fleet(self):
        """Fleet with a settled+invoiced 4500 booking (2026-08) and a second
        future BOOKED fleet booking (2026-10-10); clock past the invoice due
        date, ready for the fleet ops-run."""
        ctx = setup_fleet_with_active_auth(
            num_reservable=2, credit_limit_cents=10_000_000,
            cdl_number="CDL-O-1")
        site, fleet, driver = ctx["site"], ctx["fleet"], ctx["driver"]
        set_clock("2026-08-01T00:00:00Z")
        b1 = create_reserved_booking(
            driver["id"], site["id"], "2026-08-03", 1,
            payment_mode="FLEET_BILL", fleet_account_id=fleet["id"])
        b2 = create_reserved_booking(
            driver["id"], site["id"], "2026-10-10", 1,
            payment_mode="FLEET_BILL", fleet_account_id=fleet["id"])
        settle_booking(b1["id"], driver["id"], "2026-08-03", 1)
        set_clock("2026-09-01T00:00:00Z")
        invoice = close_billing_period(fleet["id"], "2026-08")
        set_clock("2026-10-01T00:00:00Z")
        return {"site": site, "fleet": fleet, "driver": driver,
                "auth": ctx["auth"], "b1": b1, "b2": b2, "invoice": invoice}

    def test_overdue_invoice_suspends_fleet(self):
        """PRD section 3.9: "When the sweep finds an `ISSUED` or
        `PARTIALLY_PAID` invoice whose `due_date` end-of-day UTC has passed,
        the invoice becomes `OVERDUE`, and any `OVERDUE` invoice triggers the
        fleet-overdue cascade: the fleet account moves `ACTIVE` → `SUSPENDED`
        with `auto_suspended` set true, every `ACTIVE` authorization on the
        fleet moves to `SUSPENDED` with `auto_suspended` true".

        Design: Difficulty/transitive_cascade/overdue_invoice_suspends_fleet_and_cancels_fleet_bookings
        """
        ctx = self._setup_overdue_fleet()
        resp = api_client.run_fleet_ops(ctx["fleet"]["id"], ADMIN)
        validate_success(resp, expected_status=200)

        resp = api_client.get_fleet_account(ctx["fleet"]["id"], ADMIN)
        fleet = validate_success(resp)
        assert fleet["status"] == "SUSPENDED"
        assert fleet["auto_suspended"] is True, \
            "the suspension was caused by the overdue cascade"

        resp = api_client.get_invoice(ctx["invoice"]["id"], ADMIN)
        assert validate_success(resp)["status"] == "OVERDUE", \
            "clock 2026-10-01 is past due 2026-09-30 end-of-day"

        resp = api_client.get_driver_authorization(ctx["auth"]["id"], ADMIN)
        auth = validate_success(resp)
        assert auth["status"] == "SUSPENDED"
        assert auth["auto_suspended"] is True

    def test_cascade_cancels_future_fleet_bookings(self):
        """PRD section 3.9: "each of those suspensions cascades as described
        above — future fleet-billed bookings cancelled fee-free, stalls
        released, waitlist scans run."
        PRD section 3.5: "Cancellations issued by the system itself — the
        fleet-overdue cascade, a fleet closure, the driver-suspension cascade,
        or a failed stall reassignment — never charge: `fee_cents` and
        `final_total_cents` are both 0 and `billing_status` becomes `WAIVED`".

        Design: Difficulty/transitive_cascade/overdue_invoice_suspends_fleet_and_cancels_fleet_bookings
        """
        ctx = self._setup_overdue_fleet()
        api_client.run_fleet_ops(ctx["fleet"]["id"], ADMIN)

        resp = api_client.get_booking(ctx["b2"]["id"], ADMIN)
        b2 = validate_success(resp)
        assert b2["status"] == "CANCELLED", \
            "the future fleet-billed booking is cancelled by the cascade"
        assert b2["billing_status"] == "WAIVED"
        assert b2["fee_cents"] == 0, "system cancellations never charge"


class TestInvoicePaymentCascade:

    def _setup_unpaid_invoice(self):
        return setup_invoiced_fleet_booking(cdl_number="CDL-L-1")

    def test_exact_payment_flips_invoice_and_booking(self):
        """PRD section 3.9: "a payment of exactly the remainder moves it to
        `PAID`, recomputes the fleet balance, and cascades to every booking in
        `booking_ids`: each flips `INVOICED` → `PAID` and credits its driver
        10 loyalty points per night with tier recomputed."

        Design: Difficulty/transitive_cascade/invoice_payment_paid_cascade_earns_loyalty_points
        """
        ctx = self._setup_unpaid_invoice()
        invoice, fleet = ctx["invoice"], ctx["fleet"]
        resp = api_client.pay_invoice(
            invoice["id"], {"amount_cents": invoice["net_cents"]},
            make_fleet_manager_headers(fleet["id"]))
        paid = validate_success(resp, expected_status=201)
        assert paid["status"] == "PAID"

        resp = api_client.get_booking(ctx["booking"]["id"], ADMIN)
        assert validate_success(resp)["billing_status"] == "PAID", \
            "the cascade flips each member booking INVOICED -> PAID"

    def test_exact_payment_credits_loyalty_points(self):
        """PRD section 3.9: "each flips `INVOICED` → `PAID` and credits its
        driver 10 loyalty points per night with tier recomputed."
        PRD section 3.3: "the loyalty points ledger credits
        `loyalty_points_balance` with 10 points per booked night each time one
        of the driver's bookings reaches `billing_status` `PAID`, whether the
        driver paid directly or a fleet invoice covering the booking was paid
        in full."

        Design: Difficulty/transitive_cascade/invoice_payment_paid_cascade_earns_loyalty_points
        """
        ctx = self._setup_unpaid_invoice()
        invoice, fleet = ctx["invoice"], ctx["fleet"]
        resp = api_client.pay_invoice(
            invoice["id"], {"amount_cents": invoice["net_cents"]},
            make_fleet_manager_headers(fleet["id"]))
        validate_success(resp, expected_status=201)

        resp = api_client.get_driver(ctx["driver"]["id"], ADMIN)
        d = validate_success(resp)
        assert d["loyalty_points_balance"] == 10, "10 points x 1 night"
        assert d["settled_nights_90d"] == 1


class TestFleetBalanceConservation:

    def _setup_paid_then_written_off(self):
        """Settled 4500 booking invoiced, invoice paid in full, then disputed
        and resolved WAIVED (write-off)."""
        ctx = setup_invoiced_fleet_booking(cdl_number="CDL-K-2")
        invoice, fleet = ctx["invoice"], ctx["fleet"]

        resp = api_client.get_fleet_account(fleet["id"], ADMIN)
        balance_after_issue = validate_success(resp)["current_balance_cents"]

        resp = api_client.pay_invoice(
            invoice["id"], {"amount_cents": invoice["net_cents"]},
            make_fleet_manager_headers(fleet["id"]))
        validate_success(resp, expected_status=201)
        resp = api_client.get_fleet_account(fleet["id"], ADMIN)
        balance_after_pay = validate_success(resp)["current_balance_cents"]
        resp = api_client.get_driver(ctx["driver"]["id"], ADMIN)
        points_after_pay = validate_success(resp)["loyalty_points_balance"]

        resp = api_client.dispute_invoice(
            invoice["id"], {"reason": "duplicate charge"},
            make_fleet_manager_headers(fleet["id"]))
        validate_success(resp, expected_status=200)
        resp = api_client.resolve_invoice_dispute(
            invoice["id"], {"outcome": "WAIVED"}, ADMIN)
        written_off = validate_success(resp, expected_status=200)

        resp = api_client.get_fleet_account(fleet["id"], ADMIN)
        fleet_after = validate_success(resp)
        resp = api_client.get_driver(ctx["driver"]["id"], ADMIN)
        driver_after = validate_success(resp)
        return {"ctx": ctx, "balance_after_issue": balance_after_issue,
                "balance_after_pay": balance_after_pay,
                "points_after_pay": points_after_pay,
                "written_off": written_off, "fleet_after": fleet_after,
                "driver_after": driver_after}

    def test_balance_returns_to_pre_invoice_value(self):
        """PRD section 3.9: "The `current_balance_cents` is always derived:
        the sum, over every invoice whose status is not `WRITTEN_OFF`, of
        `net_cents` minus `paid_cents`. Separately, `credit_cents` accumulates
        refunded credit from written-off invoices that had collected payments;
        it is informational and never negative."
        PRD section 3.9: "Either write-off path moves every booking in
        `booking_ids` to `WAIVED` billing — clawing back 10 loyalty points per
        night from any booking that had already reached `PAID` — adds any
        collected `paid_cents` to the fleet's `credit_cents`, and recomputes
        `current_balance_cents` with the written-off invoice excluded."

        Design: Difficulty/compensating_invariant/fleet_balance_conserved_across_payment_and_writeoff
        """
        r = self._setup_paid_then_written_off()
        assert r["balance_after_issue"] == 4500
        assert r["balance_after_pay"] == 0, "payment zeroes the balance"
        assert r["fleet_after"]["current_balance_cents"] == 0, \
            "the written-off invoice is excluded from the balance"
        assert r["fleet_after"]["credit_cents"] == 4500, \
            "the collected payment accumulates as refunded credit"
        assert r["written_off"]["status"] == "WRITTEN_OFF"

    def test_loyalty_points_clawed_back(self):
        """PRD section 3.3: "If a booking that had reached `PAID` later moves
        to `WAIVED` — through an invoice write-off, for example — the same 10
        points per night are clawed back; the balance is allowed to go
        negative and has no floor."
        PRD section 3.9: "Either write-off path moves every booking in
        `booking_ids` to `WAIVED` billing — clawing back 10 loyalty points per
        night from any booking that had already reached `PAID`".

        Design: Difficulty/compensating_invariant/fleet_balance_conserved_across_payment_and_writeoff
        """
        r = self._setup_paid_then_written_off()
        assert r["points_after_pay"] == 10, \
            "the invoice payment credited 10 points x 1 night"
        assert r["driver_after"]["loyalty_points_balance"] == 0, \
            "the write-off claws the earned points back"
        resp = api_client.get_booking(r["ctx"]["booking"]["id"], ADMIN)
        assert validate_success(resp)["billing_status"] == "WAIVED"


class TestAuthorizationGates:

    def test_missing_authorization_beats_credit_limit(self):
        """PRD section 2.7: "Every mutating request passes through an ordered
        validation pipeline. The first failing check determines the response;
        once a check fails, no later check is consulted."
        PRD section 2.7: "13. Fleet billing requires an `ACTIVE`
        DriverAuthorization for the (driver, fleet) pair — otherwise
        `ERR_DRIVER_NOT_AUTHORIZED` (403) — on booking creation, waitlist
        joins, and waitlist accepts."
        PRD section 2.7: "19. Fleet fiscal gate: projected exposure must fit
        within the fleet's credit limit — otherwise `ERR_FLEET_CREDIT_EXCEEDED`
        (422)."

        Design: Difficulty/priority_pair_validation_conflict/missing_authorization_beats_credit_limit
        """
        ctx = create_site_with_stalls(num_reservable=1)
        fleet = validate_success(
            api_client.create_fleet_account(
                {"company_name": "F", "credit_limit_cents": 1,
                 "payment_terms_days": 30},
                ADMIN),
            expected_status=201)
        driver = register_driver("CDL-V-3", "V Three")
        request_authorization(driver["id"], fleet["id"])  # stays PENDING
        set_clock("2026-08-01T00:00:00Z")

        resp = api_client.create_booking(
            create_booking_payload(driver["id"], ctx["site"]["id"],
                                   "2026-08-10", payment_mode="FLEET_BILL",
                                   fleet_account_id=fleet["id"]),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_AUTHORIZED)
        assert resp.json()["data"]["error_id"] != "ERR_FLEET_CREDIT_EXCEEDED", \
            "the referential check (step 13) fires before the fiscal gate (step 19)"

    def test_credit_limit_alone_yields_fleet_credit_exceeded(self):
        """PRD section 3.4: "the fleet's projected exposure — its
        `current_balance_cents`, plus for each of the fleet's `FLEET_BILL`
        bookings still `UNBILLED` the `final_total_cents` where set and
        otherwise the `quoted_total_cents`, plus this booking's
        `quoted_total_cents` — must be at most the fleet's
        `credit_limit_cents`, with equality allowed and any excess rejected as
        `ERR_FLEET_CREDIT_EXCEEDED`".

        Design: Difficulty/priority_pair_validation_conflict/missing_authorization_beats_credit_limit
        """
        ctx = setup_fleet_with_active_auth(credit_limit_cents=1,
                                           cdl_number="CDL-V-4")
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.create_booking(
            create_booking_payload(ctx["driver"]["id"], ctx["site"]["id"],
                                   "2026-08-10", payment_mode="FLEET_BILL",
                                   fleet_account_id=ctx["fleet"]["id"]),
            make_driver_headers(ctx["driver"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FLEET_CREDIT_EXCEEDED)
        # With an ACTIVE authorization, only the fiscal gate remains to fail,
        # confirming the dual-failure outcome above is a priority decision.

    def test_fleet_bill_booking_requires_active_authorization(self):
        """PRD section 2.7: "13. Fleet billing requires an `ACTIVE`
        DriverAuthorization for the (driver, fleet) pair — otherwise
        `ERR_DRIVER_NOT_AUTHORIZED` (403) — on booking creation, waitlist
        joins, and waitlist accepts."
        PRD section 3.9: "From `PENDING`, `ACTIVE`, or `SUSPENDED`, the
        manager may revoke the authorization outright".

        Design: Difficulty/cross_entity_state_dependency/fleet_bill_booking_requires_active_authorization
        """
        ctx = setup_fleet_with_active_auth(cdl_number="CDL-X-2")
        auth = ctx["auth"]
        transition_authorization(auth["id"], ctx["fleet"]["id"], "REVOKED")
        set_clock("2026-08-01T00:00:00Z")

        resp = api_client.create_booking(
            create_booking_payload(ctx["driver"]["id"], ctx["site"]["id"],
                                   "2026-08-10", payment_mode="FLEET_BILL",
                                   fleet_account_id=ctx["fleet"]["id"]),
            make_driver_headers(ctx["driver"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_AUTHORIZED)

    def test_revoked_authorization_creates_no_booking(self):
        """PRD section 2.7: "The first failing check determines the response;
        once a check fails, no later check is consulted."
        PRD section 3.4: "the booking list, which filters on `driver_id`,
        `site_id`, `stall_id`, `waitlist_entry_id`, `fleet_account_id`,
        `status`, and `billing_status`".

        Design: Difficulty/cross_entity_state_dependency/fleet_bill_booking_requires_active_authorization
        """
        ctx = setup_fleet_with_active_auth(cdl_number="CDL-X-2")
        transition_authorization(ctx["auth"]["id"], ctx["fleet"]["id"],
                                 "REVOKED")
        set_clock("2026-08-01T00:00:00Z")

        resp = api_client.create_booking(
            create_booking_payload(ctx["driver"]["id"], ctx["site"]["id"],
                                   "2026-08-10", payment_mode="FLEET_BILL",
                                   fleet_account_id=ctx["fleet"]["id"]),
            make_driver_headers(ctx["driver"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_AUTHORIZED)

        data, meta = validate_paginated(
            api_client.list_bookings(ADMIN,
                                     params={"driver_id": ctx["driver"]["id"]}))
        assert meta["total_count"] == 0, \
            "a rejected creation leaves no booking behind"


class TestFiscalGates:

    def test_spend_cap_exceeded_rejected(self):
        """PRD section 3.4: "when the authorization carries a non-null
        `spend_cap_per_night_cents`, the quote divided by `night_count`,
        rounded half up, must be at most the cap, otherwise
        `ERR_SPEND_CAP_EXCEEDED`."

        Design: Corner/validations/spend_cap_exceeded_rejected
        """
        ctx = setup_fleet_with_active_auth(spend_cap_per_night_cents=4000,
                                           cdl_number="CDL-SC-1")
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.create_booking(
            create_booking_payload(ctx["driver"]["id"], ctx["site"]["id"],
                                   "2026-08-10", payment_mode="FLEET_BILL",
                                   fleet_account_id=ctx["fleet"]["id"]),
            make_driver_headers(ctx["driver"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SPEND_CAP_EXCEEDED)
        # per-night average of the 4500 quote exceeds the 4000 cap even
        # though the authorization is ACTIVE and fleet credit suffices.

    def test_credit_limit_inclusive_boundary_then_exceeded(self):
        """PRD section 3.4: "must be at most the fleet's `credit_limit_cents`,
        with equality allowed and any excess rejected as
        `ERR_FLEET_CREDIT_EXCEEDED`".

        Design: Corner/validations/credit_limit_inclusive_boundary_then_exceeded
        """
        ctx = setup_fleet_with_active_auth(credit_limit_cents=4500,
                                           cdl_number="CDL-CL-1")
        set_clock("2026-08-01T00:00:00Z")
        first = create_reserved_booking(
            ctx["driver"]["id"], ctx["site"]["id"], "2026-08-10", 1,
            payment_mode="FLEET_BILL", fleet_account_id=ctx["fleet"]["id"])
        assert first["quoted_total_cents"] == 4500, \
            "exposure 4500 == the limit: equality is allowed"

        resp = api_client.create_booking(
            create_booking_payload(ctx["driver"]["id"], ctx["site"]["id"],
                                   "2026-08-11", payment_mode="FLEET_BILL",
                                   fleet_account_id=ctx["fleet"]["id"]),
            make_driver_headers(ctx["driver"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FLEET_CREDIT_EXCEEDED)
        # projected exposure 4500 + 4500 = 9000 > 4500


class TestPaymentDiscipline:

    def test_overpayment_rejected_then_exact_payment_settles(self):
        """PRD section 3.5: "Paying less than the remaining balance moves
        `billing_status` to `PARTIALLY_PAID` and adds the `amount_cents` to
        `paid_cents`; paying exactly the remaining balance moves it to `PAID`,
        sets `paid_cents` equal to `final_total_cents`, and credits the
        loyalty ledger with 10 points per `night_count`".
        PRD section 3.5: "Paying more than the remainder is
        `ERR_OVERPAYMENT`".

        Design: Corner/validations/overpayment_rejected_then_exact_payment_settles
        """
        ctx = create_site_with_stalls(num_reservable=1)
        driver = register_driver("CDL-OP-1", "O Pee")
        set_clock("2026-08-01T00:00:00Z")
        booking = create_reserved_booking(driver["id"], ctx["site"]["id"],
                                          "2026-08-10", 1)
        settled = settle_booking(booking["id"], driver["id"], "2026-08-10", 1)
        assert settled["final_total_cents"] == 4500

        resp = api_client.pay_booking(
            booking["id"], {"amount_cents": 4501},
            make_driver_headers(driver["id"]))
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)

        resp = api_client.pay_booking(
            booking["id"], {"amount_cents": 4500},
            make_driver_headers(driver["id"]))
        paid = validate_success(resp, expected_status=201)
        assert paid["billing_status"] == "PAID"
        assert paid["paid_cents"] == 4500

    def test_payment_on_fleet_bill_booking_not_due(self):
        """PRD section 3.5: "Paying more than the remainder is
        `ERR_OVERPAYMENT`, and paying when nothing is due — billing already
        `PAID` or `WAIVED`, a `FLEET_BILL` booking, or no final total yet — is
        `ERR_PAYMENT_NOT_DUE`."

        Design: Corner/validations/payment_on_fleet_bill_booking_not_due
        """
        ctx = setup_fleet_with_active_auth(cdl_number="CDL-PN-1")
        set_clock("2026-08-01T00:00:00Z")
        booking = create_reserved_booking(
            ctx["driver"]["id"], ctx["site"]["id"], "2026-08-10", 1,
            payment_mode="FLEET_BILL", fleet_account_id=ctx["fleet"]["id"])
        settled = settle_booking(booking["id"], ctx["driver"]["id"],
                                 "2026-08-10", 1)
        assert settled["final_total_cents"] == 4500

        resp = api_client.pay_booking(
            booking["id"], {"amount_cents": 4500},
            make_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_DUE)


class TestCloseBillingPeriod:

    def test_close_billing_period_without_members_rejected(self):
        """PRD section 3.9: "A period with no billable members creates nothing
        — the request is rejected with `ERR_VALIDATION` rather than returning
        success with empty data."

        Design: Corner/endpoints/close_billing_period_without_members_rejected
        """
        fleet = validate_success(
            api_client.create_fleet_account(
                {"company_name": "F", "credit_limit_cents": 1_000_000,
                 "payment_terms_days": 30},
                ADMIN),
            expected_status=201)
        resp = api_client.close_billing_period(fleet["id"],
                                               {"period": "2026-08"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestDisputedInvoice:

    def test_invoice_payment_blocked_while_disputed(self):
        """PRD section 3.9: "an invoice in `ISSUED`, `PARTIALLY_PAID`, or
        `OVERDUE` is payable, and anything else — including `DISPUTED` — is
        `ERR_INVOICE_NOT_PAYABLE`."

        Design: Corner/endpoints/invoice_payment_blocked_while_disputed
        """
        ctx = setup_invoiced_fleet_booking(cdl_number="CDL-ID-1")
        invoice, fleet = ctx["invoice"], ctx["fleet"]
        resp = api_client.dispute_invoice(
            invoice["id"], {"reason": "rate dispute"},
            make_fleet_manager_headers(fleet["id"]))
        disputed = validate_success(resp, expected_status=200)
        assert disputed["status"] == "DISPUTED"

        resp = api_client.pay_invoice(
            invoice["id"], {"amount_cents": 4500},
            make_fleet_manager_headers(fleet["id"]))
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE)


class TestManualSuspension:

    def test_manual_auth_suspension_never_auto_restores(self):
        """PRD section 3.9: "An `ACTIVE` authorization can be suspended in two
        ways that matter later: a manual `FleetManager` suspension leaves
        `auto_suspended` false, while the fleet cascade sets it true."
        PRD section 3.9: "Reactivation (`SUSPENDED` → `ACTIVE`) happens only
        from the fleet reactivation sweep and only when `auto_suspended` is
        true — manual suspensions never auto-restore — and it clears the flag
        back to false."
        PRD section 3.9: "When a later sweep finds no invoice in `ISSUED`,
        `PARTIALLY_PAID`, `OVERDUE`, or `DISPUTED` carrying a past-due date or
        outstanding balance, and the suspension was automatic, the fleet
        returns to `ACTIVE`, `auto_suspended` clears, and authorizations
        flagged `auto_suspended` restore to `ACTIVE`; manual suspensions stay
        untouched."

        Design: Corner/state_machines/manual_auth_suspension_never_auto_restores
        """
        ctx = setup_invoiced_fleet_booking(cdl_number="CDL-M-1")
        fleet, auth, invoice = ctx["fleet"], ctx["auth"], ctx["invoice"]

        suspended = transition_authorization(auth["id"], fleet["id"],
                                             "SUSPENDED")
        assert_driver_authorization(suspended)
        assert suspended["status"] == "SUSPENDED"
        assert suspended["auto_suspended"] is False, \
            "a manual suspension leaves auto_suspended false"

        set_clock("2026-10-01T00:00:00Z")
        resp = api_client.run_fleet_ops(fleet["id"], ADMIN)
        validate_success(resp, expected_status=200)
        resp = api_client.get_fleet_account(fleet["id"], ADMIN)
        fleet_overdue = validate_success(resp)
        assert fleet_overdue["status"] == "SUSPENDED", \
            "the overdue invoice suspends the fleet"
        assert fleet_overdue["auto_suspended"] is True

        resp = api_client.pay_invoice(
            invoice["id"], {"amount_cents": 4500},
            make_fleet_manager_headers(fleet["id"]))
        validate_success(resp, expected_status=201)
        resp = api_client.run_fleet_ops(fleet["id"], ADMIN)
        validate_success(resp, expected_status=200)
        resp = api_client.get_fleet_account(fleet["id"], ADMIN)
        fleet_restored = validate_success(resp)
        assert fleet_restored["status"] == "ACTIVE", \
            "no outstanding balance: the automatic suspension restores"
        assert fleet_restored["auto_suspended"] is False

        resp = api_client.get_driver_authorization(auth["id"], ADMIN)
        auth_after = validate_success(resp)
        assert auth_after["status"] == "SUSPENDED", \
            "manual suspensions never auto-restore"
        assert auth_after["auto_suspended"] is False


class TestApproveWhileSuspended:

    def test_approve_auth_while_fleet_suspended_rejected(self):
        """PRD section 3.9: "`PENDING` → `ACTIVE` approves it — permitted only
        while the fleet itself is `ACTIVE`, else `ERR_FLEET_SUSPENDED`".

        Design: Corner/validations/approve_auth_while_fleet_suspended_rejected
        """
        ctx = setup_fleet_with_active_auth(cdl_number="CDL-F-2")
        site, fleet = ctx["site"], ctx["fleet"]
        # A second driver whose authorization is never approved (PENDING);
        # the cascade only suspends ACTIVE authorizations, so it stays so.
        pending_driver = register_driver("CDL-F-1", "F One")
        pending_auth = request_authorization(pending_driver["id"], fleet["id"])

        set_clock("2026-08-01T00:00:00Z")
        booking = create_reserved_booking(
            ctx["driver"]["id"], site["id"], "2026-08-03", 1,
            payment_mode="FLEET_BILL", fleet_account_id=fleet["id"])
        settle_booking(booking["id"], ctx["driver"]["id"], "2026-08-03", 1)
        set_clock("2026-09-01T00:00:00Z")
        close_billing_period(fleet["id"], "2026-08")

        set_clock("2026-10-01T00:00:00Z")
        resp = api_client.run_fleet_ops(fleet["id"], ADMIN)
        validate_success(resp, expected_status=200)
        resp = api_client.get_fleet_account(fleet["id"], ADMIN)
        assert validate_success(resp)["status"] == "SUSPENDED"

        resp = api_client.transition_driver_authorization(
            pending_auth["id"], {"to": "ACTIVE"},
            make_fleet_manager_headers(fleet["id"]))
        validate_error(resp, ApiErrorId.ERR_FLEET_SUSPENDED)
