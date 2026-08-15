"""Invoice lifecycle: final-invoice composition, the dispute → adjustment →
settlement money conservation, settlement exactness, the credit ceiling, the
kind-uniqueness and assignment preconditions, and the adjustment OCC guard."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_port_call,
    create_provisional_invoice,
    dispute_invoice,
    get_final_invoice_for_call,
    get_invoice,
    issue_invoice,
    post_adjustment,
    setup_confirmed_call,
    setup_executed_turnaround,
    setup_scheduled_call,
    settle_invoice,
    validate_error,
    validate_paginated,
)

BILLING = TEST_USERS["billing_headers"]


class TestFinalInvoiceComposition:
    def test_final_invoice_fee_components(self, api):
        """PRD §3.8: "The FINAL variant counts real manifest rows instead: the
        embark side is the count of the call's `EMBARK` entries in `EMBARKED`
        whose `cabin_class` is not `CREW`, and the debark side is the count of
        `DEBARK` entries in `DISEMBARKED`, `HELD`, or `CLEARED` whose
        `cabin_class` is not `CREW`."
        PRD §3.8: "The PROVISIONAL variant counts orders in `APPROVED`,
        `IN_PROGRESS`, or `COMPLETED` at their planned `units`; the FINAL
        variant counts only `COMPLETED` orders at their `actual_units`; orders
        in `REQUESTED`, `REJECTED`, or `CANCELLED` contribute zero."
        PRD §3.8: "Fifth, `dockage_fee_cents` is the subtotal plus the late
        penalty."

        Design: Difficulty/combinatorial_formula/invoice_total_pinned_evaluation_order
        """
        ctx = setup_executed_turnaround(actual_etd="2026-08-10T20:20:00Z")
        close_port_call(ctx["port_call"]["id"])
        final = get_final_invoice_for_call(ctx["port_call"]["id"])

        assert final["dockage_fee_cents"] == 1763438
        assert final["head_tax_cents"] == 4050, (
            "2 EMBARKED non-CREW + 1 CLEARED debark; the CREW boarding is "
            "exempt"
        )
        assert final["service_fee_cents"] == 48000, (
            "the COMPLETED provisioning order at 10 actual units x 4,800"
        )

    def test_final_invoice_gross_and_total_follow_pinned_order(self, api):
        """PRD §3.8: "Invoice arithmetic across the three fees follows a pinned
        evaluation order that never feeds back on itself: first
        `dockage_fee_cents` (including its overtime and late penalty), second
        `head_tax_cents`, third `service_fee_cents`; fourth, `gross_cents` is
        the sum of those three; fifth, `total_cents` is `gross_cents` minus
        `adjustments_total_cents`."
        PRD §3.8: "Posted adjustments never re-enter the three fee steps —
        they only ever reduce the total."

        Design: Difficulty/combinatorial_formula/invoice_total_pinned_evaluation_order
        """
        ctx = setup_executed_turnaround(actual_etd="2026-08-10T20:20:00Z")
        close_port_call(ctx["port_call"]["id"])
        final = get_final_invoice_for_call(ctx["port_call"]["id"])

        assert final["gross_cents"] == 1815488, (
            "1,763,438 dockage + 4,050 head tax + 48,000 service"
        )
        assert final["total_cents"] == 1815488
        assert final["adjustments_total_cents"] == 0


class TestMoneyConservation:
    def _setup_issued_final_invoice(self):
        """Executed turnaround closed; FINAL invoice issued."""
        ctx = setup_executed_turnaround(actual_etd="2026-08-10T20:20:00Z")
        close_port_call(ctx["port_call"]["id"])
        final = get_final_invoice_for_call(ctx["port_call"]["id"])
        assert final["gross_cents"] == 1815488
        issue_invoice(final["id"])
        ctx["final_invoice"] = final
        return ctx

    def test_gross_invariant_across_dispute_and_adjustment(self, api):
        """PRD §3.8: "The billed vessel's `VesselAgent` may instead **dispute**
        an `ISSUED` invoice, moving it to `DISPUTED` with the payload's
        `reason` recorded as `dispute_reason` and incrementing the `version`."
        PRD §3.8: "A posted adjustment adds its `amount_cents` into
        `adjustments_total_cents`, recomputes `total_cents`, returns a
        `DISPUTED` invoice to `ISSUED` at the adjusted total, and increments
        the invoice's `version` by 1."

        Design: Difficulty/compensating_invariant/gross_billed_dispute_adjust_settle_conservation
        """
        ctx = self._setup_issued_final_invoice()
        inv_id = ctx["final_invoice"]["id"]

        dispute_invoice(inv_id, ctx["vessel"]["id"],
                        reason="late penalty contested")
        disputed = get_invoice(inv_id)
        assert disputed["status"] == "DISPUTED"
        assert disputed["gross_cents"] == 1815488
        assert disputed["total_cents"] == 1815488

        adjusted = post_adjustment(inv_id, 10000, "DELAY_COMPENSATION",
                                   disputed["version"])
        assert adjusted["status"] == "ISSUED"
        assert adjusted["total_cents"] == 1805488
        assert adjusted["gross_cents"] == 1815488, (
            "gross billed never moves across dispute and adjustment"
        )

    def test_settle_records_payment_and_adjustments_total(self, api):
        """PRD §3.8: "**Settlement** moves an `ISSUED` invoice to `SETTLED` and
        accepts the payload's `payment_cents` only when it equals `total_cents`
        exactly: a lesser payment is rejected with `ERR_UNDERPAYMENT` (HTTP
        422) and a greater one with `ERR_OVERPAYMENT` (HTTP 422); a successful
        settle records `payment_cents` and increments the `version`."
        PRD §3.8: "fifth, `total_cents` is `gross_cents` minus
        `adjustments_total_cents`."

        Design: Difficulty/compensating_invariant/gross_billed_dispute_adjust_settle_conservation
        """
        ctx = self._setup_issued_final_invoice()
        inv_id = ctx["final_invoice"]["id"]

        dispute_invoice(inv_id, ctx["vessel"]["id"], reason="contested")
        disputed = get_invoice(inv_id)
        post_adjustment(inv_id, 10000, "DELAY_COMPENSATION",
                        disputed["version"])
        settled = settle_invoice(inv_id, 1805488)
        assert settled["status"] == "SETTLED"

        final = get_invoice(inv_id)
        assert final["payment_cents"] == 1805488
        assert final["adjustments_total_cents"] == 10000
        assert final["gross_cents"] == 1815488
        assert final["gross_cents"] == (
            final["total_cents"] + final["adjustments_total_cents"]
        ), "gross == total + adjustments_total after settlement"


class TestSettleStateGate:
    def _setup_draft_provisional(self):
        """Confirmed call with a DRAFT provisional invoice, total 1,695,000."""
        ctx = setup_confirmed_call(vessel_name="MV L", booked_embark_pax=100,
                                   booked_debark_pax=100)
        ctx["provisional_invoice"] = create_provisional_invoice(
            ctx["port_call"]["id"])
        return ctx

    def test_settle_draft_invoice_reports_invalid_state_not_overpayment(self, api):
        """PRD §2.9: "Incoming requests are validated in a fixed priority
        order, so that when several checks could fail, the rejection is
        deterministic."
        PRD §2.9: "8. State preconditions: the target entity is in a state from
        which the requested transition exists, including parent-state gates on
        child creation — otherwise `ERR_INVALID_STATE` (409)."
        PRD §2.9: "23. Settlement exactness — otherwise `ERR_UNDERPAYMENT` or
        `ERR_OVERPAYMENT` (422)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_overpayment
        """
        ctx = self._setup_draft_provisional()
        inv = ctx["provisional_invoice"]
        assert inv["total_cents"] == 1695000, (
            "dockage 1,425,000 + head tax 270,000 pinned by the provisional "
            "variants"
        )
        # The DRAFT invoice cannot settle at all; the overpaying amount also
        # violates the exactness rule, but the state gate fires first.
        resp = api.settle_invoice(inv["id"], {"payment_cents": 1695001}, BILLING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_settle_leaves_invoice_draft(self, api):
        """PRD §3.8: "**Settlement** moves an `ISSUED` invoice to `SETTLED` and
        accepts the payload's `payment_cents` only when it equals `total_cents`
        exactly: a lesser payment is rejected with `ERR_UNDERPAYMENT` (HTTP
        422) and a greater one with `ERR_OVERPAYMENT` (HTTP 422); a successful
        settle records `payment_cents` and increments the `version`."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_overpayment
        """
        ctx = self._setup_draft_provisional()
        inv = ctx["provisional_invoice"]
        api.settle_invoice(inv["id"], {"payment_cents": 1695001}, BILLING)
        assert get_invoice(inv["id"])["status"] == "DRAFT"


class TestSettlementExactness:
    def test_settle_requires_exact_payment(self, api):
        """PRD §3.8: "**Settlement** moves an `ISSUED` invoice to `SETTLED` and
        accepts the payload's `payment_cents` only when it equals `total_cents`
        exactly: a lesser payment is rejected with `ERR_UNDERPAYMENT` (HTTP
        422) and a greater one with `ERR_OVERPAYMENT` (HTTP 422); a successful
        settle records `payment_cents` and increments the `version`."

        Design: Corner/validations/settle_requires_exact_payment
        """
        ctx = setup_confirmed_call(booked_embark_pax=100, booked_debark_pax=100)
        inv = create_provisional_invoice(ctx["port_call"]["id"])
        issue_invoice(inv["id"])
        assert get_invoice(inv["id"])["total_cents"] == 1695000

        under = api.settle_invoice(inv["id"], {"payment_cents": 1694999}, BILLING)
        validate_error(under, ApiErrorId.ERR_UNDERPAYMENT)
        over = api.settle_invoice(inv["id"], {"payment_cents": 1695001}, BILLING)
        validate_error(over, ApiErrorId.ERR_OVERPAYMENT)
        assert get_invoice(inv["id"])["status"] == "ISSUED"

        settled = settle_invoice(inv["id"], 1695000)
        assert settled["status"] == "SETTLED"
        assert settled["payment_cents"] == 1695000


class TestAdjustmentCreditCeiling:
    def test_credit_ceiling_inclusive_then_exhausted(self, api):
        """PRD §3.8: "a stale version is rejected with
        `ERR_STALE_INVOICE_VERSION`, and an `amount_cents` greater than the
        invoice's current `total_cents` is rejected with
        `ERR_CREDIT_EXCEEDS_OUTSTANDING` (HTTP 422). A posted adjustment adds
        its `amount_cents` into `adjustments_total_cents`, recomputes
        `total_cents`, returns a `DISPUTED` invoice to `ISSUED` at the adjusted
        total, and increments the invoice's `version` by 1."

        Design: Corner/validations/adjustment_credit_ceiling
        """
        ctx = setup_confirmed_call(booked_embark_pax=100, booked_debark_pax=100)
        inv = create_provisional_invoice(ctx["port_call"]["id"])
        issue_invoice(inv["id"])
        version = get_invoice(inv["id"])["version"]

        over = api.post_invoice_adjustment(
            inv["id"],
            {"amount_cents": 1695001, "reason": "over-credit attempt",
             "expected_invoice_version": version},
            BILLING)
        validate_error(over, ApiErrorId.ERR_CREDIT_EXCEEDS_OUTSTANDING)

        # A credit exactly equal to the outstanding total is allowed.
        credited = post_adjustment(inv["id"], 1695000, "full credit", version)
        assert credited["total_cents"] == 0
        assert credited["gross_cents"] == 1695000

        version2 = get_invoice(inv["id"])["version"]
        past = api.post_invoice_adjustment(
            inv["id"],
            {"amount_cents": 1, "reason": "past zero",
             "expected_invoice_version": version2},
            BILLING)
        validate_error(past, ApiErrorId.ERR_CREDIT_EXCEEDS_OUTSTANDING)


class TestInvoicePreconditions:
    def test_duplicate_provisional_invoice_rejected(self, api):
        """PRD §3.8: "Each call carries at most one invoice of each `kind` — a
        duplicate attempt is rejected with `ERR_INVOICE_KIND_EXISTS`."

        Design: Corner/validations/duplicate_provisional_invoice_rejected
        """
        ctx = setup_confirmed_call()
        create_provisional_invoice(ctx["port_call"]["id"])
        resp = api.create_provisional_invoice(ctx["port_call"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_INVOICE_KIND_EXISTS)

    def test_provisional_invoice_requires_confirmed_assignment(self, api):
        """PRD §3.8: "The `BillingClerk` generates the `PROVISIONAL` invoice
        once the call holds a `CONFIRMED` or `ACTIVE` berth assignment (without
        one, the request fails the state gate with `ERR_INVALID_STATE`); the
        call must not be `CANCELLED` or `CLOSED`."

        Design: Corner/validations/provisional_invoice_requires_confirmed_assignment
        """
        ctx = setup_scheduled_call()
        resp = api.create_provisional_invoice(ctx["port_call"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        _, meta = validate_paginated(
            api.list_invoices(BILLING,
                              params={"port_call_id": ctx["port_call"]["id"]}))
        assert meta["total_count"] == 0


class TestAdjustmentOcc:
    def test_stale_adjustment_version_rejected(self, api):
        """PRD §2.8: "Posting a credit adjustment to an invoice must carry
        `expected_invoice_version`, holding the caller's last observed
        `version` of that invoice. A post whose `expected_invoice_version`
        trails the invoice's current `version` is rejected with
        `ERR_STALE_INVOICE_VERSION` (HTTP 412): the credit ceiling — the
        invoice's `total_cents` — that the caller validated against may no
        longer be current."

        Design: Corner/cross_cutting_layers/occ_invoice_adjustment_stale_version
        """
        ctx = setup_confirmed_call(booked_embark_pax=100, booked_debark_pax=100)
        inv = create_provisional_invoice(ctx["port_call"]["id"])
        issue_invoice(inv["id"])
        observed_version = get_invoice(inv["id"])["version"]

        first = post_adjustment(inv["id"], 5000, "goodwill", observed_version)
        assert first["total_cents"] == 1690000

        stale = api.post_invoice_adjustment(
            inv["id"],
            {"amount_cents": 5000, "reason": "stale retry",
             "expected_invoice_version": observed_version},
            BILLING)
        validate_error(stale, ApiErrorId.ERR_STALE_INVOICE_VERSION)
        assert get_invoice(inv["id"])["adjustments_total_cents"] == 5000, (
            "the stale retry did not double-post"
        )
