"""Payout withholding, the household-employer W-2 wage threshold, the
tax-withholding ledger conservation across pay/reverse, and the immutable W-2
TaxStatement snapshot.

Translates difficulty instances under dual_variant_calc (W-2 domain),
boundary_precision_check (W-2 threshold), and compensating_invariant (tax
reversal), plus corner entities/validations instances for the tax statement and
payout-session validity.

NOTE: the combinatorial_formula / payout_fica_round_per_session_then_sum
instance is intentionally NOT translated here — see the suite summary; its
asserted payout totals (gross 39350 / fica 3011) are not uniquely derivable from
its own setup_api_calls under PRD prose (the third session computes to 6600, not
the 6900 the asserts assume).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_confirmed_one_time_booking, setup_completed_one_time_session,
    setup_paid_payout, complete_session, create_payout,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


class TestW2WithholdingVsObligation:
    """dual_variant_calc / w2_withholding_vs_obligation_threshold_distinct_domain."""

    def test_paid_holiday_session_withholding_and_obligation(self, api):
        """PRD §3.9: "The `fica_withheld_cents` is computed per session — each
        session's `gross_pay_cents` multiplied by the employee FICA rate of
        0.0765 and rounded to whole cents round-half-up — and only then summed
        across sessions".
        PRD §3.9: "the `fica_withheld_cents` is added to the family's
        `tax_withheld_ytd_cents`."
        PRD §3.9: "sets `is_w2_obligated` to true when, for any single caregiver,
        that grouped wage total is strictly greater than the federal annual wage
        threshold of 270000 cents."

        Holiday 9h @ 15001, 1 child → gross 270018; FICA round(270018*0.0765)=20656;
        270018 > 270000 → obligated.

        Design: Difficulty/dual_variant_calc/w2_withholding_vs_obligation_threshold_distinct_domain
        """
        ctx = setup_paid_payout(
            wallet_balance_cents=1000000, num_children=1, required_tier="PREMIUM",
            caregiver_tier="PREMIUM", agreed_rate_cents=15001, family_pay_rate_cents=15001,
            scheduled_start="2026-03-20T08:00:00Z", scheduled_end="2026-03-20T17:00:00Z",
            clock_in="2026-03-20T08:00:00Z", clock_out="2026-03-20T17:00:00Z",
            is_holiday=True, email_suffix="w2a")
        payout = ctx["payout"]
        assert payout["gross_pay_cents"] == 270018, \
            f"expected gross 270018, got {payout['gross_pay_cents']}"
        assert payout["fica_withheld_cents"] == 20656, \
            f"expected fica 20656, got {payout['fica_withheld_cents']}"

        family = validate_success(api.get_family(ctx["family"]["id"], ADMIN), 200)
        assert family["tax_withheld_ytd_cents"] == 20656, \
            f"expected tax_withheld_ytd 20656, got {family['tax_withheld_ytd_cents']}"
        assert family["is_w2_obligated"] is True, \
            "270018 > 270000 wage threshold must obligate the family"

    def test_obligation_flag_is_boolean_distinct_from_withheld_cents(self, api):
        """PRD §3.9: "The household-employer W-2 obligation is a per-caregiver,
        per-tax-year threshold test."

        The obligation is a boolean flag, a distinct quantity from the withheld
        cents on the same family.

        Design: Difficulty/dual_variant_calc/w2_withholding_vs_obligation_threshold_distinct_domain
        """
        ctx = setup_paid_payout(
            wallet_balance_cents=1000000, num_children=1, required_tier="PREMIUM",
            caregiver_tier="PREMIUM", agreed_rate_cents=15001, family_pay_rate_cents=15001,
            scheduled_start="2026-03-20T08:00:00Z", scheduled_end="2026-03-20T17:00:00Z",
            clock_in="2026-03-20T08:00:00Z", clock_out="2026-03-20T17:00:00Z",
            is_holiday=True, email_suffix="w2b")
        family = validate_success(api.get_family(ctx["family"]["id"], ADMIN), 200)
        assert isinstance(family["is_w2_obligated"], bool)
        assert family["is_w2_obligated"] is True
        assert family["tax_withheld_ytd_cents"] == 20656


class TestW2ThresholdBoundary:
    """boundary_precision_check / w2_threshold_exactly_at_limit_not_obligated."""

    def test_exactly_at_threshold_not_obligated(self, api):
        """PRD §3.9: "The comparison is an exact integer compare and is strictly
        greater-than: a grouped total of exactly 270000 cents does not obligate
        the family, while 270001 cents does."

        Holiday 9h @ 15000, 1 child → gross 270000; cash_wages_ytd 270000;
        not obligated (strict >).

        Design: Difficulty/boundary_precision_check/w2_threshold_exactly_at_limit_not_obligated
        """
        ctx = setup_completed_one_time_session(
            wallet_balance_cents=1000000, num_children=1, required_tier="PREMIUM",
            caregiver_tier="PREMIUM", agreed_rate_cents=15000, family_pay_rate_cents=15000,
            scheduled_start="2026-03-20T08:00:00Z", scheduled_end="2026-03-20T17:00:00Z",
            clock_in="2026-03-20T08:00:00Z", clock_out="2026-03-20T17:00:00Z",
            is_holiday=True, email_suffix="w2t")
        assert ctx["session"]["gross_pay_cents"] == 270000, \
            f"expected gross 270000, got {ctx['session']['gross_pay_cents']}"
        family = validate_success(api.get_family(ctx["family"]["id"], ADMIN), 200)
        assert family["cash_wages_ytd_cents"] == 270000
        assert family["is_w2_obligated"] is False, \
            "exactly 270000 must NOT obligate (strict greater-than)"

    def test_cash_wages_accumulates_on_completion(self, api):
        """PRD §3.7: "the session's `gross_pay_cents` is added to the family's
        `cash_wages_ytd_cents` with the family's `is_w2_obligated` flag
        recomputed".

        Design: Difficulty/boundary_precision_check/w2_threshold_exactly_at_limit_not_obligated
        """
        ctx = setup_completed_one_time_session(
            wallet_balance_cents=1000000, num_children=1, required_tier="PREMIUM",
            caregiver_tier="PREMIUM", agreed_rate_cents=15000, family_pay_rate_cents=15000,
            scheduled_start="2026-03-20T08:00:00Z", scheduled_end="2026-03-20T17:00:00Z",
            clock_in="2026-03-20T08:00:00Z", clock_out="2026-03-20T17:00:00Z",
            is_holiday=True, email_suffix="w2t2")
        family = validate_success(api.get_family(ctx["family"]["id"], ADMIN), 200)
        assert family["cash_wages_ytd_cents"] == 270000
        assert family["is_w2_obligated"] is False


class TestTaxWithholdingConservation:
    """compensating_invariant / tax_withholding_conservation_pay_then_reverse."""

    def test_reverse_restores_tax_and_wages_ledgers(self, api):
        """PRD §3.9: "Reversing a `PAID` payout marks it `REVERSED` and performs
        the exact compensating reversal: the `net_pay_cents` is subtracted back
        out of the caregiver's `lifetime_paid_cents`, the `fica_withheld_cents`
        is subtracted back out of the family's `tax_withheld_ytd_cents`, and the
        `gross_pay_cents` is subtracted back out of the family's
        `cash_wages_ytd_cents` with the family's `is_w2_obligated` flag
        recomputed."

        Session gross 19250 swept + PAID, then reversed → tax_withheld_ytd and
        cash_wages_ytd both return to 0.

        Design: Difficulty/compensating_invariant/tax_withholding_conservation_pay_then_reverse
        """
        ctx = setup_paid_payout(
            wallet_balance_cents=100000, num_children=2, required_tier="BASIC",
            caregiver_tier="BASIC", agreed_rate_cents=2000, family_pay_rate_cents=2000,
            scheduled_start="2026-03-15T08:00:00Z", scheduled_end="2026-03-15T14:00:00Z",
            clock_in="2026-03-15T08:00:00Z", clock_out="2026-03-15T16:30:00Z",
            is_holiday=False, email_suffix="txc")
        reversed_payout = validate_success(
            api.reverse_payout(ctx["payout"]["id"], ADMIN), 200)
        assert reversed_payout["status"] == "REVERSED"
        family = validate_success(api.get_family(ctx["family"]["id"], ADMIN), 200)
        assert family["tax_withheld_ytd_cents"] == 0, \
            "tax_withheld_ytd must return to its pre-pay value after reverse"
        assert family["cash_wages_ytd_cents"] == 0, \
            "cash_wages_ytd must be decremented by the reversed gross"

    def test_reverse_is_exact_for_withheld_quantity(self, api):
        """PRD §2.6: "Every forward posting to these ledgers has an exact
        compensating reversal, so reversing a payout returns each ledger to the
        precise value it held beforehand."

        Session gross 19250 → FICA 1473 withheld at pay; reverse returns it to 0.

        Design: Difficulty/compensating_invariant/tax_withholding_conservation_pay_then_reverse
        """
        ctx = setup_paid_payout(
            wallet_balance_cents=100000, num_children=2, required_tier="BASIC",
            caregiver_tier="BASIC", agreed_rate_cents=2000, family_pay_rate_cents=2000,
            scheduled_start="2026-03-15T08:00:00Z", scheduled_end="2026-03-15T14:00:00Z",
            clock_in="2026-03-15T08:00:00Z", clock_out="2026-03-15T16:30:00Z",
            is_holiday=False, email_suffix="txc2")
        family_before = validate_success(api.get_family(ctx["family"]["id"], ADMIN), 200)
        assert family_before["tax_withheld_ytd_cents"] == 1473
        validate_success(api.reverse_payout(ctx["payout"]["id"], ADMIN), 200)
        family_after = validate_success(api.get_family(ctx["family"]["id"], ADMIN), 200)
        assert family_after["tax_withheld_ytd_cents"] == 0


class TestPayoutSessionValidity:
    """Corner validations / payout_session_not_completed_rejected."""

    def test_payout_with_scheduled_session_rejected(self, api):
        """PRD §3.9: "Every referenced session must be `COMPLETED`, must belong to
        the same caregiver and family pairing, and must not already sit in a
        non-reversed payout; any violation is rejected with
        `ERR_PAYOUT_SESSION_INVALID`."

        Design: Corner/validations/payout_session_not_completed_rejected
        """
        ctx = setup_confirmed_one_time_booking(
            wallet_balance_cents=100000, num_children=1, required_tier="BASIC",
            agreed_rate_cents=2000, scheduled_start="2026-03-20T08:00:00Z",
            scheduled_end="2026-03-20T12:00:00Z", is_holiday=False, email_suffix="psinv")
        # session is SCHEDULED (never clocked in/out).
        res = api.create_payout(
            {"caregiver_id": ctx["caregiver"]["id"], "family_id": ctx["family"]["id"],
             "session_ids": [ctx["session"]["id"]]}, ADMIN)
        validate_error(res, "ERR_PAYOUT_SESSION_INVALID")


class TestTaxStatementSnapshot:
    """Corner entities / tax_statement_immutable_no_version_field."""

    def test_tax_statement_freezes_wages_and_fica(self, api):
        """PRD §3.9: "When the platform issues a W-2, it creates a `TaxStatement`
        for a `family_id`, `caregiver_id`, and `tax_year`, freezing a snapshot of
        `cash_wages_cents` (the gross wages paid from that family to that
        caregiver in the year at issuance) and `fica_withheld_cents` (the FICA
        employee-share withheld in the year at issuance)."

        One PAID payout (gross 19250, fica 1473) in 2026 → statement freezes
        cash_wages 19250 and fica_withheld 1473.

        Design: Corner/entities/tax_statement_immutable_no_version_field
        """
        ctx = setup_paid_payout(
            wallet_balance_cents=100000, num_children=2, required_tier="BASIC",
            caregiver_tier="BASIC", agreed_rate_cents=2000, family_pay_rate_cents=2000,
            scheduled_start="2026-03-15T08:00:00Z", scheduled_end="2026-03-15T14:00:00Z",
            clock_in="2026-03-15T08:00:00Z", clock_out="2026-03-15T16:30:00Z",
            is_holiday=False, email_suffix="ts")
        res = api.create_tax_statement(
            {"family_id": ctx["family"]["id"], "caregiver_id": ctx["caregiver"]["id"],
             "tax_year": 2026}, ADMIN)
        statement = validate_success(res, 201)
        assert statement["cash_wages_cents"] == 19250, \
            f"expected frozen wages 19250, got {statement['cash_wages_cents']}"
        assert statement["fica_withheld_cents"] == 1473, \
            f"expected frozen fica 1473, got {statement['fica_withheld_cents']}"

    def test_tax_statement_has_no_version_field(self, api):
        """PRD §2.4: "A `TaxStatement` is an immutable, frozen snapshot: it
        carries only an `id` and a `created_at` timestamp, and it has neither an
        `updated_at` field nor a `version` field, because it is never mutated
        after issuance."

        Design: Corner/entities/tax_statement_immutable_no_version_field
        """
        ctx = setup_paid_payout(
            wallet_balance_cents=100000, num_children=2, required_tier="BASIC",
            caregiver_tier="BASIC", agreed_rate_cents=2000, family_pay_rate_cents=2000,
            scheduled_start="2026-03-15T08:00:00Z", scheduled_end="2026-03-15T14:00:00Z",
            clock_in="2026-03-15T08:00:00Z", clock_out="2026-03-15T16:30:00Z",
            is_holiday=False, email_suffix="ts2")
        res = api.create_tax_statement(
            {"family_id": ctx["family"]["id"], "caregiver_id": ctx["caregiver"]["id"],
             "tax_year": 2026}, ADMIN)
        statement = validate_success(res, 201)
        assert "version" not in statement, "TaxStatement must NOT carry a version field"
        assert "updated_at" not in statement, "TaxStatement must NOT carry an updated_at field"
