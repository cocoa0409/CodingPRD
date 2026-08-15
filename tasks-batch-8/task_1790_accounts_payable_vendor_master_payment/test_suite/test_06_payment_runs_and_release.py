"""Payment run assembly: pay-gates, payment-time screening, discount and fee
computation, run totals, compilation, approval, and release."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_payment_invariants,
    set_clock,
    create_matrix_rule,
    onboard_vendor_to_active,
    onboard_payable_vendor,
    add_verified_primary_bank_account,
    add_bank_account,
    get_vendor,
    create_invoice,
    submit_invoice,
    approve_invoice_fully,
    create_approved_invoice,
    get_invoice,
    create_payment_run,
    get_payment_run,
    get_payment,
    add_invoice_to_run_ok,
    compile_run,
    approve_run,
    release_run,
    create_watchlist_entry,
    list_open_cases_for_vendor,
    create_document_payload,
)

VS1 = TEST_USERS["vendor_specialist_headers"]
VM1 = TEST_USERS["vendor_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CLERK = TEST_USERS["ap_clerk_headers"]
TA = TEST_USERS["treasury_analyst_headers"]
TM1 = TEST_USERS["treasury_manager_headers"]
TM2 = TEST_USERS["treasury_manager_2_headers"]
AUD = TEST_USERS["auditor_headers"]


def _payable_vendor(api, legal_name, tax_id,
                    onboard_clock="2026-06-01T00:00:00Z",
                    w9_window=("2026-01-01", "2027-12-31"), **overrides):
    """Matrix t1 GLOBAL rule + ACTIVE vendor + VERIFIED primary bank account,
    all onboarded at `onboard_clock` (aged: no routing bumps at the default
    2026-08-01 clock)."""
    set_clock(onboard_clock)
    create_matrix_rule()
    vendor = onboard_vendor_to_active(
        legal_name=legal_name, tax_id=tax_id, w9_window=w9_window, **overrides)
    account = add_verified_primary_bank_account(
        vendor["id"], account_holder_name=legal_name)
    return get_vendor(vendor["id"]), account


class TestDiscountVariants:
    def _discount_mills_scenario(self, api):
        """'Discount Mills' 2%/10-day window, activated + bank-verified
        2026-08-01; invoice 50000 received 2026-08-01, approved 2026-08-05."""
        set_clock("2026-08-01T00:00:00Z")
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=0,
                           max_amount_cents=500000, tier=1)
        vendor = onboard_vendor_to_active(
            legal_name="Discount Mills", tax_id="10-0000001",
            early_pay_discount_pct=0.02, discount_window_days=10)
        account = add_verified_primary_bank_account(
            vendor["id"], account_holder_name="Discount Mills")
        set_clock("2026-08-05T00:00:00Z")
        invoice = create_invoice(vendor["id"], amount_cents=50000,
                                 invoice_number="INV-5001",
                                 received_date="2026-08-01")
        submitted = submit_invoice(invoice["id"])
        approved = approve_invoice_fully(invoice["id"])
        run = create_payment_run(scheduled_date="2026-08-15")  # past window end
        return vendor, account, submitted, approved, run

    def test_discount_provisional_snapshot_in_window(self, api):
        """Provisional variant: approval inside the window snapshots a non-zero
        provisional discount; the tier snapshot shows the new-vendor bump.

        PRD §3.6: "The provisional variant taken at final-tier approval answers the same question with the logical date at approval as the reference — "would the discount apply if we paid today" — and is stored on the invoice as `provisional_discount_cents`."
        PRD §3.5: "The required tier starts at the covering rule's base `tier` and receives two possible bumps: one when the vendor's `first_activated_at` is set and the submit time falls strictly before the instant thirty days after it — a vendor exactly thirty days active earns no bump — and one when the vendor has a primary `VERIFIED` bank account whose `verified_at` lies strictly less than 72 hours before the submit time."

        Design: Difficulty/dual_variant_calc/invoice_discount_provisional_vs_final
        """
        _vendor, _account, submitted, approved, _run = \
            self._discount_mills_scenario(api)
        assert submitted["required_tier"] == 2, \
            "base 1 + new-vendor bump; the bank account is 96h old at submit"
        assert approved["status"] == "APPROVED"
        assert approved["provisional_discount_cents"] == 1000, \
            "approval date 2026-08-05 is inside the window ending 2026-08-11: " \
            "round_half_up(50000 * 0.02) == 1000"

    def test_discount_final_variant_zero_when_run_scheduled_past_window(self, api):
        """Final variant: the same invoice yields discount_applied_cents 0 on a
        run scheduled past the window end.

        PRD §3.6: "The discount snapshot `discount_applied_cents` uses the final variant of the pay-amount rule: the discount window ends on the invoice's `received_date` plus the vendor's `discount_window_days`, the end day inclusive, and the discount applies when the run's `scheduled_date` falls on or before that window end — so a run scheduled past the window yields a zero `discount_applied_cents` on the very same invoice whose provisional snapshot was non-zero."

        Design: Difficulty/dual_variant_calc/invoice_discount_provisional_vs_final
        """
        _vendor, _account, _submitted, approved, run = \
            self._discount_mills_scenario(api)
        assert approved["provisional_discount_cents"] == 1000
        payment = add_invoice_to_run_ok(run["id"], approved["id"])
        assert payment["discount_applied_cents"] == 0
        assert payment["net_amount_cents"] == 50000
        assert_payment_invariants(payment)
        run_after = get_payment_run(run["id"])
        assert run_after["total_amount_cents"] == 50000
        assert run_after["item_count"] == 1

    def test_discount_window_end_date_inclusive(self, api):
        """A run scheduled exactly on the window end still discounts; one day
        later does not.

        PRD §3.6: "The discount snapshot `discount_applied_cents` uses the final variant of the pay-amount rule: the discount window ends on the invoice's `received_date` plus the vendor's `discount_window_days`, the end day inclusive, and the discount applies when the run's `scheduled_date` falls on or before that window end — so a run scheduled past the window yields a zero `discount_applied_cents` on the very same invoice whose provisional snapshot was non-zero."

        Design: Corner/calculations/discount_window_end_date_inclusive
        """
        vendor, _account = _payable_vendor(
            api, "Window Widgets", "20-0000021",
            early_pay_discount_pct=0.02, discount_window_days=10)
        set_clock("2026-08-02T00:00:00Z")
        inv_a = create_approved_invoice(vendor["id"], amount_cents=50000,
                                        invoice_number="INV-9881",
                                        received_date="2026-08-01")
        inv_b = create_approved_invoice(vendor["id"], amount_cents=50000,
                                        invoice_number="INV-9882",
                                        received_date="2026-08-01")
        run_a = create_payment_run(scheduled_date="2026-08-11")  # window end
        run_b = create_payment_run(scheduled_date="2026-08-12")  # one day past
        pay_a = add_invoice_to_run_ok(run_a["id"], inv_a["id"])
        pay_b = add_invoice_to_run_ok(run_b["id"], inv_b["id"])
        assert pay_a["discount_applied_cents"] == 1000, \
            "scheduled on the window end day: discount applies (inclusive)"
        assert pay_b["discount_applied_cents"] == 0, \
            "one day past the window end: no discount"


class TestRunTotalsRounding:
    def _roundtrip_scenario(self, api):
        """Aged 2%/30d vendor; invoices 11111 and 22222 received 2026-08-01,
        APPROVED tier 1; CHECK run scheduled 2026-08-20 (inside the window)."""
        vendor, _account = _payable_vendor(
            api, "Roundtrip Office", "10-0000003",
            early_pay_discount_pct=0.02, discount_window_days=30)
        set_clock("2026-08-01T00:00:00Z")
        inv1 = create_approved_invoice(vendor["id"], amount_cents=11111,
                                       invoice_number="INV-11111",
                                       received_date="2026-08-01")
        inv2 = create_approved_invoice(vendor["id"], amount_cents=22222,
                                       invoice_number="INV-22222",
                                       received_date="2026-08-01")
        run = create_payment_run(scheduled_date="2026-08-20")
        return vendor, inv1, inv2, run

    def test_run_total_round_per_payment_then_sum_lines(self, api):
        """Each payment's discount is rounded to whole cents first:
        222 and 444.

        PRD §2.9: "Early-pay discounts are computed per single invoice and rounded half up to whole cents before they are ever combined; discounting is never batched across invoices before rounding."

        Design: Difficulty/combinatorial_formula/run_total_round_per_payment_then_sum
        """
        _vendor, inv1, inv2, run = self._roundtrip_scenario(api)
        pay1 = add_invoice_to_run_ok(run["id"], inv1["id"])
        pay2 = add_invoice_to_run_ok(run["id"], inv2["id"])
        assert pay1["discount_applied_cents"] == 222, \
            "round_half_up(11111 * 0.02) == round_half_up(222.22) == 222"
        assert pay1["net_amount_cents"] == 10889
        assert pay2["discount_applied_cents"] == 444, \
            "round_half_up(22222 * 0.02) == round_half_up(444.44) == 444"
        assert pay2["net_amount_cents"] == 21778
        assert_payment_invariants(pay1)
        assert_payment_invariants(pay2)

    def test_run_total_round_per_payment_then_sum_total(self, api):
        """Run total is the integer sum of per-payment nets: 32667, not the
        32666 a sum-then-round order would produce.

        PRD §2.9: "Payment run totals obey a pinned rounding order: each payment's discount is rounded to whole cents first, each payment's net is then formed as an integer sum of cents, and only then are the per-payment nets summed into the run total."
        PRD §3.6: "Every add recomputes the run's totals under the pinned rounding order of §2.9: `total_amount_cents` is the sum of `net_amount_cents` over the run's payments not in `VOIDED` status, and `item_count` counts those same payments."

        Design: Difficulty/combinatorial_formula/run_total_round_per_payment_then_sum
        """
        _vendor, inv1, inv2, run = self._roundtrip_scenario(api)
        add_invoice_to_run_ok(run["id"], inv1["id"])
        add_invoice_to_run_ok(run["id"], inv2["id"])
        compiled = compile_run(run["id"])
        assert compiled["total_amount_cents"] == 32667, \
            "10889 + 21778 == 32667; sum-then-round would give 32666"
        assert compiled["item_count"] == 2

    def test_run_total_add_then_void_conserved(self, api):
        """Adding then voiding invoice 2's payment restores the run to exactly
        its pre-add total and count.

        PRD §3.7: "A `TreasuryAnalyst` may void a payment manually while it is still `PENDING` — a payment that is no longer `PENDING`, including one inside a `RELEASED`, `CLOSED`, or `VOIDED` run, yields `ERR_INVALID_STATE_TRANSITION` — which sets `void_reason` `MANUAL_REMOVED`, returns its invoice from `IN_PAYMENT_RUN` to `APPROVED`, recomputes the run totals, and demotes the run from `APPROVED` to `COMPILED` if that is where it sat."

        Design: Difficulty/compensating_invariant/run_total_cents_add_then_void_conserved
        """
        vendor, _account = _payable_vendor(
            api, "Invariant Inc", "10-0000014",
            early_pay_discount_pct=0.02, discount_window_days=30)
        set_clock("2026-08-01T00:00:00Z")
        inv1 = create_approved_invoice(vendor["id"], amount_cents=11111,
                                       invoice_number="INV-9101",
                                       received_date="2026-08-01")
        inv2 = create_approved_invoice(vendor["id"], amount_cents=22222,
                                       invoice_number="INV-9102",
                                       received_date="2026-08-01")
        run = create_payment_run(scheduled_date="2026-08-20")
        add_invoice_to_run_ok(run["id"], inv1["id"])
        before = get_payment_run(run["id"])
        assert before["total_amount_cents"] == 10889
        assert before["item_count"] == 1

        pay2 = add_invoice_to_run_ok(run["id"], inv2["id"])
        assert get_payment_run(run["id"])["total_amount_cents"] == 32667

        voided = validate_success(api.void_payment(pay2["id"], TA))
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "MANUAL_REMOVED"

        restored = get_payment_run(run["id"])
        assert restored["total_amount_cents"] == 10889, \
            "add-then-void composes to the identity on run money"
        assert restored["item_count"] == 1
        assert get_invoice(inv2["id"])["status"] == "APPROVED", \
            "the voided invoice reverts to APPROVED and is payable again"

    def test_run_total_add_then_void_invoice_payable_again(self, api):
        """The compensating void marks the payment VOIDED (MANUAL_REMOVED) and
        returns its invoice to APPROVED, where it can be added afresh.

        PRD §3.7: "A `TreasuryAnalyst` may void a payment manually while it is still `PENDING` — a payment that is no longer `PENDING`, including one inside a `RELEASED`, `CLOSED`, or `VOIDED` run, yields `ERR_INVALID_STATE_TRANSITION` — which sets `void_reason` `MANUAL_REMOVED`, returns its invoice from `IN_PAYMENT_RUN` to `APPROVED`, recomputes the run totals, and demotes the run from `APPROVED` to `COMPILED` if that is where it sat."
        PRD §3.6: "Every add recomputes the run's totals under the pinned rounding order of §2.9: `total_amount_cents` is the sum of `net_amount_cents` over the run's payments not in `VOIDED` status, and `item_count` counts those same payments."

        Design: Difficulty/compensating_invariant/run_total_cents_add_then_void_conserved
        """
        vendor, _account = _payable_vendor(
            api, "Invariant Inc", "10-0000014",
            early_pay_discount_pct=0.02, discount_window_days=30)
        set_clock("2026-08-01T00:00:00Z")
        inv1 = create_approved_invoice(vendor["id"], amount_cents=11111,
                                       invoice_number="INV-9101",
                                       received_date="2026-08-01")
        inv2 = create_approved_invoice(vendor["id"], amount_cents=22222,
                                       invoice_number="INV-9102",
                                       received_date="2026-08-01")
        run = create_payment_run(scheduled_date="2026-08-20")
        add_invoice_to_run_ok(run["id"], inv1["id"])
        pay2 = add_invoice_to_run_ok(run["id"], inv2["id"])

        voided = validate_success(api.void_payment(pay2["id"], TA))
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "MANUAL_REMOVED"
        assert get_invoice(inv2["id"])["status"] == "APPROVED"

        # The conserved invariant: re-adding the same invoice reproduces the
        # exact same payment line and run total as the first add.
        pay2_again = add_invoice_to_run_ok(run["id"], inv2["id"])
        assert pay2_again["discount_applied_cents"] == 444
        assert pay2_again["net_amount_cents"] == 21778
        restored = get_payment_run(run["id"])
        assert restored["total_amount_cents"] == 32667
        assert restored["item_count"] == 2

    def test_run_void_unwinds_payments_and_invoices(self, api):
        """Voiding a DRAFT run voids its PENDING payments (RUN_VOIDED) and
        returns their invoices to APPROVED.

        PRD §3.7: "Voiding the whole run, open to both treasury roles from `DRAFT` or `COMPILED`, moves the run to `VOIDED`, moves every `PENDING` payment to `VOIDED` with `void_reason` `RUN_VOIDED`, returns their invoices from `IN_PAYMENT_RUN` to `APPROVED`, and recomputes the totals."

        Design: Corner/endpoints/run_void_unwinds_payments_and_invoices
        """
        vendor, _account = _payable_vendor(api, "Void Valley", "20-0000049")
        set_clock("2026-08-01T00:00:00Z")
        invoice = create_approved_invoice(vendor["id"], amount_cents=100000,
                                          invoice_number="INV-9003",
                                          received_date="2026-08-01")
        run = create_payment_run(scheduled_date="2026-08-05")
        payment = add_invoice_to_run_ok(run["id"], invoice["id"])

        voided_run = validate_success(api.void_payment_run(run["id"], TA))
        assert voided_run["status"] == "VOIDED"
        assert voided_run["total_amount_cents"] == 0
        assert voided_run["item_count"] == 0
        reloaded_payment = get_payment(payment["id"])
        assert reloaded_payment["status"] == "VOIDED"
        assert reloaded_payment["void_reason"] == "RUN_VOIDED"
        assert get_invoice(invoice["id"])["status"] == "APPROVED"


class TestWireFeeAndComputedNet:
    def test_payment_net_amount_includes_wire_fee(self, api):
        """On a WIRE run, fee_cents is 2500 and net = gross - discount + fee.

        PRD §3.6: "The payment's `fee_cents` is the 2,500-cent wire fee when the run's method is `WIRE` and zero otherwise, and its `net_amount_cents` is the gross minus the discount plus the fee."
        PRD §2.9: "All money in the system is represented as integer cents — invoice gross amounts, discounts, fees, payment nets, and run totals alike."

        Design: Corner/entities/payment_net_amount_includes_wire_fee
        """
        vendor, _account = _payable_vendor(api, "Wire Works", "20-0000005")
        set_clock("2026-08-01T00:00:00Z")
        invoice = create_approved_invoice(vendor["id"], amount_cents=100000,
                                          invoice_number="INV-9501",
                                          received_date="2026-08-01")
        run = create_payment_run(scheduled_date="2026-08-05",
                                 payment_method="WIRE")
        payment = add_invoice_to_run_ok(run["id"], invoice["id"])
        assert payment["fee_cents"] == 2500
        assert payment["discount_applied_cents"] == 0, \
            "the vendor's discount fraction is zero"
        assert payment["net_amount_cents"] == 102500
        compiled = compile_run(run["id"])
        assert compiled["total_amount_cents"] == 102500
        assert compiled["item_count"] == 1


class TestRunWorkflowBranches:
    def test_run_uncompile_and_revoke_approval_branch(self, api):
        """The run machine branches backward: COMPILED -> DRAFT via uncompile
        and APPROVED -> COMPILED via revoke-approval, clearing the approver.

        PRD §3.7: "Compilation, performed by a `TreasuryAnalyst`, moves the run from `DRAFT` to `COMPILED` and requires at least one non-`VOIDED` payment — compiling an empty run is rejected with `ERR_EMPTY_PAYMENT_RUN` — recomputing the run totals as it goes; uncompilation reverses it back to `DRAFT` for rework."
        PRD §3.7: "Approval is revocable — the same role can move the run back to `COMPILED`, clearing `approved_by_user_id` to null — and it is also fragile: when the run's contents change underneath it because a payment was voided or the block cascade voided payments, an `APPROVED` run demotes itself to `COMPILED` and must be approved afresh."

        Design: Corner/state_machines/run_uncompile_and_revoke_approval_branch
        """
        vendor, _account = _payable_vendor(api, "Branch Brook", "20-0000013")
        set_clock("2026-08-01T00:00:00Z")
        invoice = create_approved_invoice(vendor["id"], amount_cents=100000,
                                          invoice_number="INV-9701",
                                          received_date="2026-08-01")
        run = create_payment_run(scheduled_date="2026-08-05")
        payment = add_invoice_to_run_ok(run["id"], invoice["id"])

        assert compile_run(run["id"])["status"] == "COMPILED"
        uncompiled = validate_success(api.uncompile_payment_run(run["id"], TA))
        assert uncompiled["status"] == "DRAFT"
        assert compile_run(run["id"])["status"] == "COMPILED"
        approved = approve_run(run["id"])
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "u-tm-01"
        revoked = validate_success(api.revoke_payment_run_approval(run["id"], TM1))
        assert revoked["status"] == "COMPILED"
        assert revoked["approved_by_user_id"] is None
        assert get_payment(payment["id"])["status"] == "PENDING"
        assert get_invoice(invoice["id"])["status"] == "IN_PAYMENT_RUN"

    def test_compile_empty_run_rejected(self, api):
        """Compiling a run with zero non-VOIDED payments fails.

        PRD §3.7: "Compilation, performed by a `TreasuryAnalyst`, moves the run from `DRAFT` to `COMPILED` and requires at least one non-`VOIDED` payment — compiling an empty run is rejected with `ERR_EMPTY_PAYMENT_RUN` — recomputing the run totals as it goes; uncompilation reverses it back to `DRAFT` for rework."

        Design: Corner/validations/compile_empty_run_rejected
        """
        run = create_payment_run(scheduled_date="2026-08-05")
        resp = api.compile_payment_run(run["id"], TA)
        validate_error(resp, ApiErrorId.ERR_EMPTY_PAYMENT_RUN.value)
        assert get_payment_run(run["id"])["status"] == "DRAFT"

    def test_sod_run_creator_cannot_approve(self, api):
        """SoD-4a: the TreasuryManager who created the run cannot approve it.

        PRD §2.6: "The `TreasuryManager` approving a payment run must not be the operator recorded as the run's `created_by_user_id`."
        PRD §2.6: "A violation is rejected with `ERR_SOD_RUN_CREATOR_CANNOT_APPROVE`."

        Design: Corner/validations/sod_run_creator_cannot_approve_forbidden
        """
        vendor, _account = _payable_vendor(
            api, "Dual Control Diesel", "20-0000032")
        set_clock("2026-08-01T00:00:00Z")
        invoice = create_approved_invoice(vendor["id"], amount_cents=100000,
                                          invoice_number="INV-9940",
                                          received_date="2026-08-01")
        run = create_payment_run(scheduled_date="2026-08-05", headers=TM1)
        add_invoice_to_run_ok(run["id"], invoice["id"])
        compile_run(run["id"])

        resp = api.approve_payment_run(run["id"], TM1)
        validate_error(resp, ApiErrorId.ERR_SOD_RUN_CREATOR_CANNOT_APPROVE.value)
        reloaded = get_payment_run(run["id"])
        assert reloaded["status"] == "COMPILED"
        assert reloaded["approved_by_user_id"] is None

    def test_treasury_analyst_cannot_approve_run_forbidden(self, api):
        """Run approval is TreasuryManager-exclusive; the role gate fires before
        any state check.

        PRD §2.1: "A request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §2.11: "Role authorization follows, yielding `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: "| POST | `/payment-runs/{id}/approve` | Move COMPILED to APPROVED (SoD-4a) | TreasuryManager |"

        Design: Corner/rbac/treasury_analyst_cannot_approve_run_forbidden
        """
        run = create_payment_run(scheduled_date="2026-08-05")
        resp = api.approve_payment_run(run["id"], TA)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


class TestReleaseGates:
    def test_daily_limit_exact_equality_allowed(self, api):
        """Releases of 6000000 then 4000000 land exactly on the 10000000 daily
        ceiling and both succeed; one cent over is rejected.

        PRD §3.7: "Last, the daily release limit buckets runs by logical UTC date: the sum of `total_amount_cents` over all runs in `RELEASED` or `CLOSED` whose `released_at` falls on the same logical date, plus this run's `total_amount_cents`, must not exceed 10,000,000 cents — a one-hundred-thousand-dollar daily ceiling; a release landing exactly on the limit is allowed, and one cent over is rejected with `ERR_DAILY_LIMIT_EXCEEDED`."

        Design: Corner/calculations/daily_limit_exact_equality_allowed
        """
        set_clock("2026-06-01T00:00:00Z")
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=1000000,
                           max_amount_cents=None, tier=3)
        # _payable_vendor creates the GLOBAL [0,500000) t1 rule.
        vendor, _account = _payable_vendor(
            api, "Limit Lumber", "20-0000024")
        set_clock("2026-08-01T00:00:00Z")
        inv1 = create_approved_invoice(vendor["id"], amount_cents=6000000,
                                       invoice_number="INV-9891",
                                       received_date="2026-08-01")
        inv2 = create_approved_invoice(vendor["id"], amount_cents=4000000,
                                       invoice_number="INV-9892",
                                       received_date="2026-08-01")
        inv3 = create_approved_invoice(vendor["id"], amount_cents=100,
                                       invoice_number="INV-9893",
                                       received_date="2026-08-01")

        run1 = create_payment_run(scheduled_date="2026-08-05")
        add_invoice_to_run_ok(run1["id"], inv1["id"])
        compile_run(run1["id"])
        approve_run(run1["id"])
        released1 = release_run(run1["id"])
        assert released1["status"] == "RELEASED"

        run2 = create_payment_run(scheduled_date="2026-08-05")
        add_invoice_to_run_ok(run2["id"], inv2["id"])
        compile_run(run2["id"])
        approve_run(run2["id"])
        released2 = release_run(run2["id"])
        assert released2["status"] == "RELEASED", \
            "6000000 + 4000000 lands exactly on the daily limit: allowed"

        run3 = create_payment_run(scheduled_date="2026-08-05")
        add_invoice_to_run_ok(run3["id"], inv3["id"])
        compile_run(run3["id"])
        approve_run(run3["id"])
        resp = api.release_payment_run(run3["id"], TM1)
        validate_error(resp, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED.value)
        assert get_payment_run(run3["id"])["status"] == "APPROVED"

    def test_release_sod_beats_daily_limit_error(self, api):
        """The releaser is the run creator AND the release would breach the
        daily limit: SoD-4b fires first of the three ordered release guards.

        PRD §3.7: "Release is the point of no return, performed by a `TreasuryManager` on an `APPROVED` run, and three guards fire in order."
        PRD §3.7: "SoD-4b bars the run's creator from releasing it with `ERR_SOD_RUN_CREATOR_CANNOT_RELEASE`."

        Design: Difficulty/priority_pair_validation_conflict/release_sod_beats_daily_limit
        """
        run2_id = self._release_sod_vs_limit_scenario(api)
        resp = api.release_payment_run(run2_id, TM1)
        validate_error(resp, ApiErrorId.ERR_SOD_RUN_CREATOR_CANNOT_RELEASE.value)

    def test_release_sod_beats_daily_limit_state_unchanged(self, api):
        """The rejected release leaves the run APPROVED and its payment PENDING,
        even though the fiscal guard would also have failed.

        PRD §3.7: "Release is the point of no return, performed by a `TreasuryManager` on an `APPROVED` run, and three guards fire in order."
        PRD §3.7: "Last, the daily release limit buckets runs by logical UTC date: the sum of `total_amount_cents` over all runs in `RELEASED` or `CLOSED` whose `released_at` falls on the same logical date, plus this run's `total_amount_cents`, must not exceed 10,000,000 cents — a one-hundred-thousand-dollar daily ceiling; a release landing exactly on the limit is allowed, and one cent over is rejected with `ERR_DAILY_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/release_sod_beats_daily_limit
        """
        run2_id = self._release_sod_vs_limit_scenario(api)
        validate_error(api.release_payment_run(run2_id, TM1),
                       ApiErrorId.ERR_SOD_RUN_CREATOR_CANNOT_RELEASE.value)
        run2 = get_payment_run(run2_id)
        assert run2["status"] == "APPROVED"
        payments, meta = validate_paginated(api.list_run_payments(run2_id, AUD))
        assert meta["total_count"] == 1
        assert payments[0]["status"] == "PENDING"

    def _release_sod_vs_limit_scenario(self, api):
        """run1 (5000000) released today; run2 (6000000) created by u-tm-01,
        compiled by the analyst, approved by u-tm-02 — both the SoD-4b and the
        daily-limit conditions hold for a release by u-tm-01."""
        set_clock("2026-06-01T00:00:00Z")
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=1000000,
                           max_amount_cents=None, tier=3)
        vendor, _account = _payable_vendor(
            api, "Bulwark Industrial", "10-0000009")
        set_clock("2026-08-01T00:00:00Z")
        inv1 = create_approved_invoice(vendor["id"], amount_cents=5000000,
                                       invoice_number="INV-6101",
                                       received_date="2026-08-01")
        run1 = create_payment_run(scheduled_date="2026-08-05")
        add_invoice_to_run_ok(run1["id"], inv1["id"])
        compile_run(run1["id"])
        approve_run(run1["id"], headers=TM2)
        release_run(run1["id"], headers=TM2)

        inv2 = create_approved_invoice(vendor["id"], amount_cents=6000000,
                                       invoice_number="INV-6102",
                                       received_date="2026-08-01")
        run2 = create_payment_run(scheduled_date="2026-08-06", headers=TM1)
        add_invoice_to_run_ok(run2["id"], inv2["id"])
        compile_run(run2["id"])
        approve_run(run2["id"], headers=TM2)
        return run2["id"]

    def test_release_with_stale_bank_snapshot_rejected(self, api):
        """After a new primary account supersedes the snapshotted one, release
        fails the snapshot-freshness guard.

        PRD §3.7: "Next, every payment's bank snapshot is re-checked for freshness: for each payment, the vendor's current `primary_bank_account_id` must still equal the payment's `bank_account_id`, and that account's current `version` must still equal the payment's `bank_account_version`; any drift rejects the release with `ERR_BANK_SNAPSHOT_STALE`."
        PRD §3.3: "When the account carries `is_primary` true, the supersede chain fires in the same step: the vendor's previous `VERIFIED` primary, if any, becomes `SUPERSEDED` and its `version` increments, the vendor's `primary_bank_account_id` is set to the newly verified account, and the vendor's `version` increments by one."

        Design: Corner/validations/release_with_stale_bank_snapshot_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        create_matrix_rule()
        vendor = onboard_vendor_to_active(
            legal_name="Snapshot Silk", tax_id="20-0000038")
        account_a = add_verified_primary_bank_account(
            vendor["id"], account_holder_name="Snapshot Silk")

        set_clock("2026-07-01T00:00:00Z")
        invoice = create_approved_invoice(vendor["id"], amount_cents=100000,
                                          invoice_number="INV-9970",
                                          received_date="2026-07-01")
        run = create_payment_run(scheduled_date="2026-07-05")
        payment = add_invoice_to_run_ok(run["id"], invoice["id"])
        assert payment["bank_account_id"] == account_a["id"]
        compile_run(run["id"])
        approve_run(run["id"])

        set_clock("2026-08-01T00:00:00Z")
        account_b = add_verified_primary_bank_account(
            vendor["id"], account_holder_name="Snapshot Silk")
        assert account_b["id"] != account_a["id"]
        assert get_success_data(api.get_bank_account(
            account_a["id"], AUD))["status"] == "SUPERSEDED"

        resp = api.release_payment_run(run["id"], TM1)
        validate_error(resp, ApiErrorId.ERR_BANK_SNAPSHOT_STALE.value)
        assert get_payment_run(run["id"])["status"] == "APPROVED"
        assert get_payment(payment["id"])["status"] == "PENDING"


class TestPaymentTimeScreeningAndDocuments:
    def test_payment_screening_uses_current_watchlist(self, api):
        """The payment variant re-screens against the CURRENT watchlist: an
        entry created after vendor approval flips the add to REVIEW — the add
        is rejected yet the vendor suspends and a case opens.

        PRD §3.2: "The payment variant, evaluated when an invoice is added to a payment run (§3.6), re-evaluates against the current `ACTIVE` watchlist, so an entry created after the vendor was approved can flip that same vendor from `CLEAR` to `REVIEW` or `HIT` at payment time."
        PRD §3.6: "Then the payment variant of sanctions screening runs against the current `ACTIVE` watchlist — before the remaining gates — and its side effects persist even when the add is rejected: the screening row is always written with `subject_type` `PAYMENT`, and on a `REVIEW` the vendor is suspended and a review case opens, while on a `HIT` the vendor is blocked with the full §3.2 cascade."
        PRD §3.6: "The gate order then surfaces the outcome: a vendor already `BLOCKED`, or one whose fresh screening returned `HIT`, rejects the add with `ERR_VENDOR_BLOCKED`; a vendor with an `OPEN` review case, or one whose fresh screening returned `REVIEW`, rejects with `ERR_SANCTIONS_REVIEW_PENDING`; a vendor in any other non-`ACTIVE` status rejects with `ERR_VENDOR_NOT_ACTIVE`."

        Design: Corner/calculations/payment_screening_uses_current_watchlist
        """
        vendor, _account = _payable_vendor(api, "Orion Logistics", "20-0000025")
        set_clock("2026-08-01T00:00:00Z")
        invoice = create_approved_invoice(vendor["id"], amount_cents=100000,
                                          invoice_number="INV-9901",
                                          received_date="2026-08-01")
        create_watchlist_entry("Orion Logistic", severity="REVIEW")
        run = create_payment_run(scheduled_date="2026-08-05")

        resp = api.add_invoice_to_run(run["id"], {"invoice_id": invoice["id"]}, TA)
        validate_error(resp, ApiErrorId.ERR_SANCTIONS_REVIEW_PENDING.value)

        assert get_vendor(vendor["id"])["status"] == "SUSPENDED", \
            "the failed add's screening side effects persist"
        cases = list_open_cases_for_vendor(vendor["id"])
        assert len(cases) == 1
        assert cases[0]["opened_reason"] == "PAYMENT_SCREENING"

        checks, meta = validate_paginated(api.list_screening_checks(
            AUD, params={"vendor_id": vendor["id"], "result": "REVIEW"}))
        assert meta["total_count"] == 1
        assert checks[0]["subject_type"] == "PAYMENT"
        assert checks[0]["match_score"] == pytest.approx(0.9565, abs=1e-6), \
            "Dice('Orion Logistics', 'Orion Logistic') == 22/23 == 0.9565"

        # No payment persisted; the suspended vendor's hold cascade parked the
        # APPROVED invoice ON_HOLD (the §3.4 hold cascade freezes APPROVED
        # invoices whenever the vendor suspends).
        held = get_invoice(invoice["id"])
        assert held["status"] == "ON_HOLD"
        assert held["pre_hold_status"] == "APPROVED"
        payments, meta = validate_paginated(api.list_payments(
            AUD, params={"invoice_id": invoice["id"]}))
        assert meta["total_count"] == 0

    def test_payment_add_with_expired_w9_live_evaluation(self, api):
        """Live document evaluation beats the sweep cache: the W9 row still
        reads VALID (no sweep ran) yet the add fails ERR_DOCUMENT_EXPIRED.

        PRD §3.6: "Last, the vendor must hold a live-valid `W9` at add time under the live evaluation of §3.1; a W9 on file whose window has passed rejects with `ERR_DOCUMENT_EXPIRED`."
        PRD §3.1: "A document passes live evaluation when its status is `VALID` and the current logical date falls on or after `valid_from` and on or before `valid_until` — both bounds inclusive — so a row still cached as `VALID` whose window has already closed fails live checks."

        Design: Corner/validations/payment_add_with_expired_w9_live_evaluation
        """
        set_clock("2026-06-01T00:00:00Z")
        create_matrix_rule()
        vendor = onboard_vendor_to_active(
            legal_name="Lapsed Lanyards", tax_id="20-0000036",
            w9_window=("2026-01-01", "2026-07-31"))
        add_verified_primary_bank_account(
            vendor["id"], account_holder_name="Lapsed Lanyards")

        set_clock("2026-08-05T00:00:00Z")
        invoice = create_approved_invoice(vendor["id"], amount_cents=100000,
                                          invoice_number="INV-9950",
                                          received_date="2026-08-05")
        run = create_payment_run(scheduled_date="2026-08-06")
        resp = api.add_invoice_to_run(run["id"], {"invoice_id": invoice["id"]}, TA)
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_EXPIRED.value)

        docs, _meta = validate_paginated(api.list_documents(vendor["id"], AUD))
        assert docs[0]["doc_type"] == "W9"
        assert docs[0]["status"] == "VALID", \
            "no sweep ran since the window closed, so the cache still says VALID"
        assert get_invoice(invoice["id"])["status"] == "APPROVED"
        payments, meta = validate_paginated(api.list_payments(
            AUD, params={"invoice_id": invoice["id"]}))
        assert meta["total_count"] == 0
