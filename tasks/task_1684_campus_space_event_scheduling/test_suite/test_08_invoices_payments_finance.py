"""Invoices, payments, waivers, refunds: dual invoice variants, bucket rounding
order, ledger conservation, and finance controls."""

from test_helpers import (
    FINANCE_ADMIN,
    SCHEDULER,
    ApiErrorId,
    approve_event,
    assert_invoice,
    assert_invoice_total_invariant,
    build_user_headers,
    create_event,
    find_invoice_for_event,
    get_event,
    get_invoice,
    get_org,
    org_headers,
    pay_invoice,
    set_clock,
    setup_approved_event,
    setup_completed_event_with_unfulfilled_quote,
    setup_org_room,
    validate_error,
    validate_success,
)


class TestDualVariantInvoice:
    def test_provisional_counts_quoted_order_final_excludes_it(self, api):
        """PRD §3.6: "The provisional variant, computed at approval or rebooking,
        is forward-looking: its service charge sums the quoted totals of orders
        in `QUOTED`, `APPROVED`, `SCHEDULED`, or `FULFILLED`, and its total is
        the room charge plus that service charge plus the insurance surcharge."
        PRD §3.6: "On completion, the service charge sums orders in `FULFILLED`
        or `INVOICED` only, the surcharge is recomputed on that final base for
        external clients, and the total adds any `deposit_charge_cents`."

        Design: Difficulty/dual_variant_calc/invoice_provisional_includes_quoted_but_final_excludes
        """
        scn = setup_completed_event_with_unfulfilled_quote()
        prov = scn.prov_invoice
        assert prov["status"] == "PROVISIONAL"
        assert prov["room_charge_cents"] == 10000, "two off-peak buckets at 5000"
        assert prov["service_charge_cents"] == 6000, "the QUOTED order counts"
        assert prov["insurance_surcharge_cents"] == 0, "INTERNAL requester"
        assert prov["total_cents"] == 16000

        final = get_invoice(prov["id"])
        assert final["status"] == "FINALIZED"
        assert final["room_charge_cents"] == 10000
        assert final["service_charge_cents"] == 0, (
            "the never-fulfilled QUOTED order drops out of the final variant"
        )
        assert final["total_cents"] == 10000
        assert_invoice_total_invariant(final)

    def test_completion_cancels_unfulfilled_orders_with_fee_waived(self, api):
        """PRD §3.4: "An event that does proceed completes at the daily-close
        once the clock reaches its `end_at`, moving from `IN_PROGRESS` to
        `COMPLETED`."
        PRD §3.4: "Fulfilled orders move to `INVOICED`, while orders still in
        `SCHEDULED`, `APPROVED`, `QUOTED`, `REQUESTED`, or `NEEDS_REVISION` are
        cancelled with `fee_waived` true."

        Design: Difficulty/dual_variant_calc/invoice_provisional_includes_quoted_but_final_excludes
        """
        scn = setup_completed_event_with_unfulfilled_quote()
        assert scn.event["status"] == "COMPLETED"
        assert scn.order["status"] == "CANCELLED"
        assert scn.order["fee_waived"] is True, "event-completion cascade"


class TestBucketRoundingOrder:
    def test_peak_buckets_round_per_bucket_then_sum(self, api):
        """PRD §3.6: "The rounding order is pinned: each bucket is rounded to
        cents first, and the rounded bucket charges are then summed. Summing
        first and rounding once is a different, forbidden order — with a pinned
        rate of 9999 cents and three peak buckets, the pinned order yields 37497
        cents where sum-then-round would yield 37496."
        PRD §3.6: "The insurance surcharge applies to external clients only: two
        percent of the combined room and service charges, rounded half-up to
        whole cents, and zero for `INTERNAL_DEPARTMENT` and `STUDENT_GROUP`
        organizations."

        Design: Difficulty/combinatorial_formula/room_charge_per_bucket_rounding_order
        """
        scn = setup_approved_event(
            org_overrides={
                "name": "Alumni Assoc",
                "org_type": "EXTERNAL",
                "contact_email": "alum@ext.org",
                "insurance_certificate_expiry": "2026-12-31T00:00:00Z",
                "insurance_coverage_cents": 100000000,
            },
            room_overrides={
                "name": "GYM-A",
                "building_code": "GYM",
                "capacity": 300,
                "external_hourly_rate_cents": 9999,
            },
            event_overrides={
                "title": "Reception",
                "expected_attendance": 250,
                "start_at": "2026-09-10T17:30:00Z",
                "end_at": "2026-09-10T20:30:00Z",
            },
        )
        invoice = scn.invoice
        assert_invoice(invoice)
        # Billable [17:30, 20:30): bucket 17 off-peak at 9999; buckets 18/19/20
        # peak at round_half_up(9999 * 12500 / 10000) = 12499 each.
        assert invoice["room_charge_cents"] == 47496, (
            "9999 + 12499 + 12499 + 12499 — per-bucket rounding pinned"
        )
        assert invoice["insurance_surcharge_cents"] == 950, (
            "round_half_up(0.02 * 47496) over the already-rounded lines"
        )
        assert invoice["total_cents"] == 48446
        assert_invoice_total_invariant(invoice)

    def test_weekend_buckets_are_peak_even_before_18_00(self, api):
        """PRD §2.7: "An hour bucket is peak when its starting clock hour is
        18:00 UTC or later, or when its date falls on a Saturday or Sunday in
        UTC."
        PRD §3.6: "A peak bucket — one whose starting clock hour is 18:00 UTC or
        later, or whose date is a Saturday or Sunday in UTC — charges the pinned
        hourly rate multiplied by the pinned peak multiplier basis points and
        divided by ten thousand, rounded half-up to whole cents; any other
        bucket charges the pinned hourly rate."

        Design: Difficulty/combinatorial_formula/room_charge_per_bucket_rounding_order
        """
        scn = setup_approved_event(
            org_overrides={
                "name": "Alumni Weekend",
                "org_type": "EXTERNAL",
                "contact_email": "weekend@ext.org",
                "insurance_certificate_expiry": "2026-12-31T00:00:00Z",
                "insurance_coverage_cents": 100000000,
            },
            room_overrides={
                "name": "GYM-B",
                "building_code": "GYM",
                "capacity": 300,
                "external_hourly_rate_cents": 9999,
            },
            event_overrides={
                "title": "Saturday Fair",
                "expected_attendance": 250,
                # 2026-09-12 is a Saturday: both 14:00 and 15:00 buckets peak.
                "start_at": "2026-09-12T14:00:00Z",
                "end_at": "2026-09-12T16:00:00Z",
            },
        )
        event = get_event(scn.event["id"])
        assert event["pinned_peak_multiplier_bps"] == 12500
        invoice = scn.invoice
        assert invoice["room_charge_cents"] == 24998, "2 x 12499 peak buckets"
        assert invoice["insurance_surcharge_cents"] == 500
        assert invoice["total_cents"] == 25498


class TestLedgerConservation:
    def _setup_two_approved_events(self, api):
        """Two approved INTERNAL events (E1 on 09-14, E2 on 09-15, each 2h at
        5000 -> provisional 10000 apiece)."""
        scn = setup_org_room(
            org_overrides={"name": "Dept Astr", "contact_email": "astr@univ.edu"},
            room_overrides={"name": "AST-1", "building_code": "AST", "capacity": 30},
        )
        e1 = create_event(
            scn.org, scn.room["id"], title="E1", expected_attendance=10,
            start_at="2026-09-14T14:00:00Z", end_at="2026-09-14T16:00:00Z",
        )
        approve_event(e1["id"])
        e2 = create_event(
            scn.org, scn.room["id"], title="E2", expected_attendance=10,
            start_at="2026-09-15T14:00:00Z", end_at="2026-09-15T16:00:00Z",
        )
        approve_event(e2["id"])
        scn.e1, scn.e2 = e1, e2
        scn.inv1 = find_invoice_for_event(e1["id"])
        scn.inv2 = find_invoice_for_event(e2["id"])
        return scn

    def test_admin_cancel_voids_invoice_and_releases_balance(self, api):
        """PRD §3.4: "Cancellations with reason `ADMIN`, `BUMPED`, or
        `ORG_SUSPENDED` are always free regardless of notice."
        PRD §3.4: "For an event with a live invoice, the invoice is voided when
        the fee is zero and no order has been fulfilled"
        PRD §3.1: "`outstanding_balance_cents` is the sum, over the
        organization's invoices in `PROVISIONAL`, `FINALIZED`, or
        `PARTIALLY_PAID` status, of each invoice's `total_cents` less its
        `paid_cents` and `waived_cents`; voided invoices contribute nothing."

        Design: Difficulty/compensating_invariant/invoice_ledger_conservation_across_cancel_pay_refund
        """
        scn = self._setup_two_approved_events(api)
        assert get_org(scn.org["id"])["outstanding_balance_cents"] == 20000

        cancelled = validate_success(api.cancel_event(scn.e1["id"], SCHEDULER), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "ADMIN"
        assert cancelled["cancellation_fee_cents"] == 0

        inv1 = get_invoice(scn.inv1["id"])
        assert inv1["status"] == "VOIDED"

        # The voided 10000 is released; E2's live provisional 10000 remains.
        assert get_org(scn.org["id"])["outstanding_balance_cents"] == 10000

    def test_client_cancel_pay_refund_cycle_conserves_money(self, api):
        """PRD §3.4: "notice under 24 hours incurs the full base, expressed as
        10000 basis points"
        PRD §3.6: "a payment or waiver that brings `paid_cents` plus
        `waived_cents` to exactly `total_cents` moves the invoice to `PAID`,
        whether it started `PROVISIONAL`, `FINALIZED`, or `PARTIALLY_PAID`."
        PRD §3.6: "the invoice becomes `REFUNDED` only when the accumulated
        refunds equal the accumulated payments in full, from either `PAID` or
        `PARTIALLY_PAID`."
        PRD §3.1: "`outstanding_balance_cents` is the sum, over the
        organization's invoices in `PROVISIONAL`, `FINALIZED`, or
        `PARTIALLY_PAID` status, of each invoice's `total_cents` less its
        `paid_cents` and `waived_cents`; voided invoices contribute nothing."

        Design: Difficulty/compensating_invariant/invoice_ledger_conservation_across_cancel_pay_refund
        """
        scn = self._setup_two_approved_events(api)
        # E1 leaves the ledger the free way.
        api.cancel_event(scn.e1["id"], SCHEDULER)

        # E2 cancelled by the client one hour before start: 100% tier.
        set_clock("2026-09-15T13:00:00Z")
        cancelled = validate_success(
            api.cancel_event(scn.e2["id"], org_headers(scn.org)), 200
        )
        assert cancelled["cancel_reason"] == "CLIENT"
        assert cancelled["cancellation_fee_cents"] == 10000

        inv2 = get_invoice(scn.inv2["id"])
        assert inv2["status"] == "FINALIZED"
        assert inv2["total_cents"] == 10000
        assert inv2["cancellation_fee_cents"] == 10000

        paid = pay_invoice(scn.inv2["id"], 10000, scn.org)
        assert paid["status"] == "PAID"
        assert paid["paid_cents"] == 10000

        refunded = validate_success(
            api.refund_invoice(
                scn.inv2["id"], {"amount_cents": 10000}, FINANCE_ADMIN
            ),
            200,
        )
        assert refunded["status"] == "REFUNDED"
        assert refunded["refunded_cents"] == 10000
        assert refunded["paid_cents"] == 10000

        # Both invoices are terminal and outside the outstanding set: the
        # ledger is back to exactly zero with no drift.
        assert get_org(scn.org["id"])["outstanding_balance_cents"] == 0


class TestPaymentBoundaries:
    def test_overpayment_rejected_exact_balance_payment_pays(self, api):
        """PRD §3.6: "The amount may not exceed the remaining balance, the
        invoice's `total_cents` less its `paid_cents` and `waived_cents`, and
        attempts beyond that are rejected with `ERR_OVERPAYMENT`"
        PRD §3.6: "a payment or waiver that brings `paid_cents` plus
        `waived_cents` to exactly `total_cents` moves the invoice to `PAID`,
        whether it started `PROVISIONAL`, `FINALIZED`, or `PARTIALLY_PAID`."

        Design: Corner/validations/overpayment_rejected_exact_payment_paid
        """
        scn = setup_approved_event(
            room_overrides={
                "internal_hourly_rate_cents": 1000,
                "student_hourly_rate_cents": 500,
                "external_hourly_rate_cents": 2000,
            },
            event_overrides={"expected_attendance": 5},
        )
        invoice = scn.invoice
        assert invoice["total_cents"] == 1000

        over = api.pay_invoice(
            invoice["id"], {"amount_cents": 1001}, FINANCE_ADMIN
        )
        validate_error(over, ApiErrorId.ERR_OVERPAYMENT)
        assert get_invoice(invoice["id"])["paid_cents"] == 0

        paid = validate_success(
            api.pay_invoice(invoice["id"], {"amount_cents": 1000}, FINANCE_ADMIN),
            200,
        )
        assert paid["status"] == "PAID"
        assert paid["paid_cents"] == 1000

    def test_refunds_accumulate_and_refund_only_at_full_equality(self, api):
        """PRD §3.6: "A `FinanceAdmin` supplies an `amount_cents` that may not
        exceed `paid_cents` less `refunded_cents`, otherwise
        `ERR_REFUND_EXCEEDS_PAID`. Each refund adds to `refunded_cents`, and the
        invoice becomes `REFUNDED` only when the accumulated refunds equal the
        accumulated payments in full, from either `PAID` or `PARTIALLY_PAID`."

        Design: Corner/validations/refund_exceeding_paid_rejected_partial_refunds_accumulate
        """
        # Two-hour window 14:00-16:00 on a Monday: two off-peak hour buckets
        # billed at the default 5000-cent internal rate -> total 10000.
        scn = setup_approved_event(
            event_overrides={
                "expected_attendance": 5,
                "start_at": "2026-09-14T14:00:00Z",
                "end_at": "2026-09-14T16:00:00Z",
            }
        )
        invoice = scn.invoice
        assert invoice["total_cents"] == 10000, "two off-peak buckets at 5000"
        pay_invoice(invoice["id"], 10000)

        over = api.refund_invoice(
            invoice["id"], {"amount_cents": 10001}, FINANCE_ADMIN
        )
        validate_error(over, ApiErrorId.ERR_REFUND_EXCEEDS_PAID)

        first = validate_success(
            api.refund_invoice(invoice["id"], {"amount_cents": 4000}, FINANCE_ADMIN),
            200,
        )
        assert first["status"] == "PAID", "partial refund keeps the status"
        assert first["refunded_cents"] == 4000

        second = validate_success(
            api.refund_invoice(invoice["id"], {"amount_cents": 6000}, FINANCE_ADMIN),
            200,
        )
        assert second["status"] == "REFUNDED"
        assert second["refunded_cents"] == 10000


class TestWaiverSegregationOfDuties:
    def test_waive_by_approving_operator_is_blocked(self, api):
        """PRD §3.6: "they are segregation-of-duties gated: the waiving
        operator's `X-User-ID` must differ from the event's recorded
        `approved_by_user_id`, or the waiver is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.6: "The waived amount is capped at the remaining balance —
        `total_cents` less `paid_cents` and `waived_cents` — with excess
        rejected as `ERR_OVERPAYMENT`, and each waiver adds to `waived_cents`."
        PRD §3.4: "`approved_by_user_id` records the acting scheduler's
        `X-User-ID`, later feeding the segregation-of-duties rule on waivers."

        Design: Corner/validations/waive_by_approving_user_blocked_segregation_of_duties
        """
        scn = setup_org_room(
            room_overrides={
                "internal_hourly_rate_cents": 1000,
                "student_hourly_rate_cents": 500,
                "external_hourly_rate_cents": 2000,
            }
        )
        event = create_event(scn.org, scn.room["id"], expected_attendance=5)
        # approved_by_user_id records the approving scheduler's X-User-ID.
        validate_success(
            api.approve_event(event["id"], build_user_headers("sched-1", "Scheduler")),
            200,
        )
        invoice = find_invoice_for_event(event["id"])
        assert invoice["total_cents"] == 1000

        # The same opaque identifier cannot waive, even under FinanceAdmin.
        blocked = api.waive_invoice(
            invoice["id"],
            {"amount_cents": 500, "reason": "goodwill"},
            build_user_headers("sched-1", "FinanceAdmin"),
        )
        validate_error(blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_invoice(invoice["id"])["waived_cents"] == 0

        waived = validate_success(
            api.waive_invoice(
                invoice["id"],
                {"amount_cents": 400, "reason": "goodwill"},
                build_user_headers("fin-1", "FinanceAdmin"),
            ),
            200,
        )
        assert waived["waived_cents"] == 400
        assert waived["status"] == "PROVISIONAL", "400 < 1000: partial waiver"
