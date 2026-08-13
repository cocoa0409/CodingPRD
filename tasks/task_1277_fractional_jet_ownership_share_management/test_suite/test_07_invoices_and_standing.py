"""Invoice lifecycle: creation, aggregation, issue, payment, dispute loop, aging,
and the derived owner-standing reconciliation."""
import pytest

from test_helpers import (
    ApiErrorId,
    confirm_booking_ok,
    create_booking_ok,
    create_invoice_ok,
    create_issued_invoice,
    create_owner,
    create_program,
    create_activated_share,
    create_aircraft_class,
    get_invoice,
    get_owner,
    issue_invoice_ok,
    make_owner_headers,
    pay_invoice_ok,
    set_clock,
    setup_owner_with_past_due_invoice,
    setup_program_with_share,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
FLEET = TEST_USERS["fleet_ops_headers"]
FIN = TEST_USERS["finance_ops_headers"]


class TestInvoiceCreation:
    def test_invoice_opens_with_zero_totals(self, api):
        """PRD §3.6: "The invoice opens with `invoice_status` `OPEN`, accumulating lines
        as the month unfolds."
        PRD §3.6: "Issuance stamps `issued_at` from the clock and moves the invoice from
        `OPEN` to `ISSUED`."

        Design: Corner/state_machines/invoice_initial_state_open
        """
        program = create_program(program_code="FJX-SM6")
        owner = create_owner(program["id"], legal_name="SM6 Owner")
        resp = api.create_invoice(
            {"owner_id": owner["id"], "billing_period": "2026-08"}, FIN
        )
        data = validate_success(resp, 201)
        assert data["invoice_status"] == "OPEN"
        assert data["issued_at"] is None, "issued_at stays null while OPEN"
        assert data["management_fee_cents"] == 0
        assert data["occupied_hours_fee_cents"] == 0
        assert data["total_due_cents"] == 0

    def test_duplicate_invoice_period_rejected(self, api):
        """PRD §3.6: "One invoice may exist per owner per period; a duplicate is rejected
        with `ERR_DUPLICATE_INVOICE_PERIOD` (HTTP 409)."

        Design: Corner/validations/duplicate_invoice_period_rejected
        """
        program = create_program(program_code="FJX-VA4")
        owner = create_owner(program["id"], legal_name="VA4 Owner")
        create_invoice_ok(owner["id"], "2026-08")
        resp = api.create_invoice({"owner_id": owner["id"], "billing_period": "2026-08"}, FIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVOICE_PERIOD)
        assert resp.status_code == 409

    def test_issue_before_period_end_rejected(self, api):
        """PRD §3.6: "Issuing requires the billing period to have ended relative to the
        clock — an early issue is rejected with `ERR_INVOICE_PERIOD_OPEN` (HTTP 422)"

        Design: Corner/validations/invoice_issue_before_period_end_rejected
        """
        program = create_program(program_code="FJX-VA3")
        owner = create_owner(program["id"], legal_name="VA3 Owner")
        invoice = create_invoice_ok(owner["id"], "2026-08")
        set_clock("2026-08-15T00:00:00Z")  # still inside the August period
        resp = api.issue_invoice(invoice["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_INVOICE_PERIOD_OPEN)
        assert resp.status_code == 422
        assert get_invoice(invoice["id"])["invoice_status"] == "OPEN"


class TestManagementFeeAggregation:
    def test_multi_share_fee_sums_per_share_lines(self, api):
        """PRD §3.6: "The management-fee component sums, across every share of the owner
        that spent any part of the period in `ACTIVE`, `LISTED`, or `IN_EXIT`, the
        class's `monthly_fee_base_cents` scaled by the share's fraction and rounded
        half-up to whole cents per share; a share that remained `PENDING_ACTIVATION` or
        `CLOSED` for the entire period contributes nothing, and a mid-period activation
        is billed for the full month with no proration."

        Design: Corner/calculations/monthly_management_fee_multi_share
        """
        program = create_program(program_code="FJX-CA5")
        mid = create_aircraft_class(program["id"], class_code="MID")
        light = create_aircraft_class(program["id"], class_code="LIGHT")
        heavy = create_aircraft_class(program["id"], class_code="HEAVY")
        owner = create_owner(program["id"], legal_name="CA5 Owner")
        create_activated_share(owner["id"], mid["id"], fraction_numerator=1,
                               fraction_denominator=8, purchase_price_cents=12000000)
        create_activated_share(owner["id"], light["id"], fraction_numerator=1,
                               fraction_denominator=16, purchase_price_cents=1200000)
        # This share stays PENDING_ACTIVATION all period and contributes nothing.
        from test_helpers import create_share
        create_share(owner["id"], heavy["id"], fraction_numerator=1,
                     fraction_denominator=4, purchase_price_cents=48000000)

        invoice = create_invoice_ok(owner["id"], "2026-08")
        set_clock("2026-09-01T00:00:00Z")
        issued = issue_invoice_ok(invoice["id"])
        # 1/8 x 2500000 = 312500; 1/16 x 1500000 = 93750; PENDING HEAVY share -> 0
        assert issued["management_fee_cents"] == 406250, (
            f"per-share rounding then sum, got {issued['management_fee_cents']}"
        )
        assert issued["total_due_cents"] == 406250, (
            "no flights and no December pass-through in August"
        )


class TestDepreciationPassThrough:
    def test_december_straight_line_credit(self, api):
        """PRD §3.6: "Under `STRAIGHT_LINE`, the allowance is the basis divided by the
        recovery years, rounded half-up to whole cents."
        PRD §3.6: "The invoice's `tax_adjustment_cents` is the negated sum of these
        allowances, a credit, posted through `DEPRECIATION_PASSTHROUGH` lines."

        Design: Corner/calculations/depreciation_december_pass_through_single_share
        """
        sc = setup_program_with_share(
            program_code="FJX-CA7", class_code="MID", fraction=(1, 4),
            purchase_price_cents=1200000,
        )
        invoice = create_invoice_ok(sc["owner"]["id"], "2026-12")
        set_clock("2027-01-01T00:00:00Z")
        issued = issue_invoice_ok(invoice["id"])
        # allowance = 1200000 / 5 = 240000, posted as a credit
        assert issued["tax_adjustment_cents"] == -240000, (
            f"December pass-through is a credit, got {issued['tax_adjustment_cents']}"
        )
        # management fee 1/4 x 2500000 = 625000; total = 625000 - 240000
        assert issued["total_due_cents"] == 385000

    def test_december_invoice_combines_both_schedule_methods(self, api):
        """PRD §3.6: "Under `STRAIGHT_LINE`, the allowance is the basis divided by the
        recovery years, rounded half-up to whole cents. Under `DOUBLE_DECLINING`, the
        allowance is the lesser of two values — twice the remaining undepreciated basis
        divided by the recovery years, rounded half-up, and the remaining undepreciated
        basis itself — so accumulated depreciation can never exceed the basis. The
        invoice's `tax_adjustment_cents` is the negated sum of these allowances, a
        credit, posted through `DEPRECIATION_PASSTHROUGH` lines."

        Design: Difficulty/dual_variant_calc/depreciation_straight_line_vs_double_declining
        """
        program = create_program(program_code="FJX-DV2")
        light = create_aircraft_class(program["id"], class_code="LIGHT")
        owner = create_owner(program["id"], legal_name="DV2 Owner")
        create_activated_share(owner["id"], light["id"], fraction_numerator=1,
                               fraction_denominator=16, purchase_price_cents=1200000,
                               schedule_method="STRAIGHT_LINE", recovery_years=5)
        create_activated_share(owner["id"], light["id"], fraction_numerator=1,
                               fraction_denominator=16, purchase_price_cents=1200000,
                               schedule_method="DOUBLE_DECLINING", recovery_years=5)
        invoice = create_invoice_ok(owner["id"], "2026-12")
        set_clock("2027-01-01T00:00:00Z")
        issued = issue_invoice_ok(invoice["id"])
        # SL: 1200000/5 = 240000; DDB: min(2*1200000/5, 1200000) = 480000.
        assert issued["tax_adjustment_cents"] == -720000, (
            f"sum of 240000 + 480000 negated, got {issued['tax_adjustment_cents']}"
        )

    def test_double_declining_exceeds_straight_line_in_first_year(self, api):
        """PRD §3.6: "Under `DOUBLE_DECLINING`, the allowance is the lesser of two values
        — twice the remaining undepreciated basis divided by the recovery years, rounded
        half-up, and the remaining undepreciated basis itself — so accumulated
        depreciation can never exceed the basis."

        Design: Difficulty/dual_variant_calc/depreciation_straight_line_vs_double_declining
        """
        program = create_program(program_code="FJX-DV2B")
        light = create_aircraft_class(program["id"], class_code="LIGHT")
        owner_sl = create_owner(program["id"], legal_name="DV2B SL Owner")
        owner_ddb = create_owner(program["id"], legal_name="DV2B DDB Owner")
        create_activated_share(owner_sl["id"], light["id"], fraction_numerator=1,
                               fraction_denominator=16, purchase_price_cents=1200000,
                               schedule_method="STRAIGHT_LINE", recovery_years=5)
        create_activated_share(owner_ddb["id"], light["id"], fraction_numerator=1,
                               fraction_denominator=16, purchase_price_cents=1200000,
                               schedule_method="DOUBLE_DECLINING", recovery_years=5)
        inv_sl = create_invoice_ok(owner_sl["id"], "2026-12")
        inv_ddb = create_invoice_ok(owner_ddb["id"], "2026-12")
        set_clock("2027-01-01T00:00:00Z")
        issued_sl = issue_invoice_ok(inv_sl["id"])
        issued_ddb = issue_invoice_ok(inv_ddb["id"])
        assert issued_sl["tax_adjustment_cents"] == -240000
        assert issued_ddb["tax_adjustment_cents"] == -480000, (
            "the accelerated schedule front-loads the first-year allowance"
        )
        assert -issued_ddb["tax_adjustment_cents"] > -issued_sl["tax_adjustment_cents"]


class TestPaymentExactness:
    def test_pay_one_cent_short_rejected(self, api):
        """PRD §3.6: "The owner pays by tendering `amount_cents` equal to
        `total_due_cents` to the cent; anything else is rejected with
        `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422)."

        Design: Corner/validations/invoice_pay_exact_amount
        """
        sc = setup_program_with_share(program_code="FJX-VA2", class_code="MID")
        invoice = create_issued_invoice(sc["owner"]["id"], "2026-08", "2026-09-01T00:00:00Z")
        assert invoice["total_due_cents"] == 312500  # 1/8 x 2500000 management fee
        resp = api.pay_invoice(
            invoice["id"], {"amount_cents": 312499}, make_owner_headers(sc["owner"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
        assert resp.status_code == 422
        assert get_invoice(invoice["id"])["invoice_status"] == "ISSUED"


class TestDisputeCycle:
    def _issued_invoice(self, program_code):
        sc = setup_program_with_share(program_code=program_code, class_code="MID")
        invoice = create_issued_invoice(sc["owner"]["id"], "2026-08", "2026-09-01T00:00:00Z")
        return sc, invoice

    def test_reject_adjustment_returns_invoice_to_issued_unchanged(self, api):
        """PRD §3.6: "Supplying the `reject_adjustment` flag instead returns the invoice
        unchanged to `ISSUED`, or to `PAST_DUE` if that is where it stood before the
        dispute."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_cycle_returns_to_issued
        """
        sc, invoice = self._issued_invoice("FJX-NL1")
        assert invoice["total_due_cents"] == 312500
        headers = make_owner_headers(sc["owner"]["id"])
        disputed = validate_success(api.dispute_invoice(invoice["id"], headers), 200)
        assert disputed["invoice_status"] == "DISPUTED"
        resolved = validate_success(
            api.resolve_dispute(
                invoice["id"], {"adjusted_total_cents": 0, "reject_adjustment": True}, FIN
            ),
            200,
        )
        assert resolved["invoice_status"] == "ISSUED", "rejection returns to ISSUED"
        assert resolved["total_due_cents"] == 312500, "rejection leaves the total unchanged"

    def test_cycle_reentry_then_adjusted_settlement(self, api):
        """PRD §3.6: "An owner who disagrees with a bill may dispute it while it stands
        `ISSUED` or `PAST_DUE`, moving it to `DISPUTED`"
        PRD §3.6: "Supplying an `adjusted_total_cents` — which must be non-negative —
        replaces the invoice total and settles the invoice as `SETTLED_AFTER_DISPUTE`."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_cycle_returns_to_issued
        """
        sc, invoice = self._issued_invoice("FJX-NL1B")
        headers = make_owner_headers(sc["owner"]["id"])
        api.dispute_invoice(invoice["id"], headers)
        api.resolve_dispute(invoice["id"], {"adjusted_total_cents": 0, "reject_adjustment": True}, FIN)
        # The cycle re-enters DISPUTED from ISSUED
        disputed2 = validate_success(api.dispute_invoice(invoice["id"], headers), 200)
        assert disputed2["invoice_status"] == "DISPUTED"
        settled = validate_success(
            api.resolve_dispute(
                invoice["id"], {"adjusted_total_cents": 300000, "reject_adjustment": False}, FIN
            ),
            200,
        )
        assert settled["invoice_status"] == "SETTLED_AFTER_DISPUTE"
        assert settled["total_due_cents"] == 300000, "the adjusted total replaces the original"

    def test_reject_adjustment_from_past_due_returns_to_past_due(self, api):
        """PRD §3.6: "Supplying the `reject_adjustment` flag instead returns the invoice
        unchanged to `ISSUED`, or to `PAST_DUE` if that is where it stood before the
        dispute."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_cycle_returns_to_issued
        """
        sc = setup_owner_with_past_due_invoice(program_code="FJX-NL1C")
        invoice = get_invoice(sc["invoice"]["id"])
        assert invoice["invoice_status"] == "PAST_DUE"
        headers = make_owner_headers(sc["owner"]["id"])
        validate_success(api.dispute_invoice(invoice["id"], headers), 200)
        resolved = validate_success(
            api.resolve_dispute(
                invoice["id"], {"adjusted_total_cents": 0, "reject_adjustment": True}, FIN
            ),
            200,
        )
        assert resolved["invoice_status"] == "PAST_DUE", (
            "a dispute rejected from PAST_DUE returns to PAST_DUE, not ISSUED"
        )


class TestPastDueSweep:
    def test_issued_invoice_sweeps_past_due_and_owner_goes_delinquent(self, api):
        """PRD §3.6: "Left unpaid, an issued invoice rolls to `PAST_DUE` when the clock
        passes thirty days after `issued_at`, and the owner's standing degrades from
        `GOOD` to `DELINQUENT` in the same sweep (§2.10)."

        Design: Difficulty/transitive_cascade/invoice_past_due_owner_delinquency_depth2
        """
        sc = setup_program_with_share(program_code="FJX-TC2", class_code="MID")
        invoice = create_issued_invoice(sc["owner"]["id"], "2026-08", "2026-09-01T00:00:00Z")
        set_clock("2026-10-02T00:00:00Z")  # issued_at + 30 days crossed at 2026-10-01
        swept = get_invoice(invoice["id"])
        assert swept["invoice_status"] == "PAST_DUE", (
            f"clock past issued_at + 30 days must sweep the invoice, got {swept['invoice_status']}"
        )
        owner = get_owner(sc["owner"]["id"])
        assert owner["owner_standing"] == "DELINQUENT", (
            "the owner transition is caused by the invoice sweep, hop 2 of the cascade"
        )

    def test_delinquent_standing_blocks_subsequent_confirm(self, api):
        """PRD §2.10: "The moment any invoice of theirs enters `PAST_DUE`, standing
        degrades automatically to `DELINQUENT`, and booking confirmation is rejected
        while that standing holds."

        Design: Difficulty/transitive_cascade/invoice_past_due_owner_delinquency_depth2
        """
        sc = setup_owner_with_past_due_invoice(program_code="FJX-TC2B")
        booking = create_booking_ok(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-11-15T15:00:00Z", 1.00,
        )
        resp = api.confirm_booking(booking["id"], make_owner_headers(sc["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNER_STANDING_BLOCKS)
        assert resp.status_code == 422


class TestStandingReconciliation:
    def test_paying_last_past_due_invoice_restores_good(self, api):
        """PRD §2.10: "When the last `PAST_DUE` invoice is paid or settled after dispute
        and none remain, standing returns to `GOOD` without any operator action."
        PRD §3.6: "A paid invoice moves to `PAID`, and if that clears the owner's last
        `PAST_DUE` invoice, their standing returns from `DELINQUENT` to `GOOD`."

        Design: Corner/cross_cutting_layers/derived_owner_standing_reconciles_on_payment
        """
        sc = setup_program_with_share(program_code="FJX-CC3", class_code="MID")
        owner_id = sc["owner"]["id"]
        inv_aug = create_issued_invoice(owner_id, "2026-08", "2026-09-01T00:00:00Z")
        inv_sep = create_invoice_ok(owner_id, "2026-09")
        set_clock("2026-10-01T00:00:00Z")
        issue_invoice_ok(inv_sep["id"])
        set_clock("2026-10-02T00:00:00Z")  # August invoice sweeps PAST_DUE
        assert get_owner(owner_id)["owner_standing"] == "DELINQUENT"

        # Paying the September (merely ISSUED) invoice does not restore GOOD while the
        # PAST_DUE August invoice remains.
        pay_invoice_ok(inv_sep["id"], owner_id, 312500)
        assert get_invoice(inv_sep["id"])["invoice_status"] == "PAID"
        assert get_owner(owner_id)["owner_standing"] == "DELINQUENT", (
            "paying a non-past-due invoice must not clear delinquency"
        )

        pay_invoice_ok(inv_aug["id"], owner_id, 312500)
        assert get_owner(owner_id)["owner_standing"] == "GOOD", (
            "clearing the last PAST_DUE invoice reconciles the derived standing"
        )


class TestIssueRbac:
    def test_fleetops_cannot_issue_invoice(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "`POST /invoices/{id}/issue` | Issue an invoice; runs all aggregations |
        FinanceOps"

        Design: Corner/rbac/fleetops_cannot_issue_invoice
        """
        program = create_program(program_code="FJX-RB2")
        owner = create_owner(program["id"], legal_name="RB2 Owner")
        invoice = create_invoice_ok(owner["id"], "2026-08")
        set_clock("2026-09-01T00:00:00Z")
        resp = api.issue_invoice(invoice["id"], FLEET)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403
        assert get_invoice(invoice["id"])["invoice_status"] == "OPEN"
