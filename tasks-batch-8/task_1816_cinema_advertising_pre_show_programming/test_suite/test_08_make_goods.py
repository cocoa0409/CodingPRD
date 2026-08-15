"""Make-good credits: strict 5% eligibility threshold, credit computation and
cap, review/apply state machine, and the invoice money invariant."""
import pytest

from test_helpers import (
    ApiErrorId, assert_invoice_money_invariant, make_auditor_headers,
    make_sales_manager_headers, setup_certified_invoice, validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    AUDITOR_1, AUDITOR_2, SM_CREATOR, approve_make_good, apply_make_good,
    get_invoice_version, propose_make_good,
)


class TestMakeGoodThresholdBoundary:
    def test_make_good_threshold_exactly_5pct_rejected(self, api):
        """PRD §3.7: "Eligibility is a strict threshold — the ratio must be
        greater than 0.05, so a campaign under-delivered by exactly five percent
        earns nothing and the proposal is rejected with
        `ERR_MAKE_GOOD_THRESHOLD_NOT_MET` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/make_good_threshold_exactly_5pct_rejected
        """
        ctx = setup_certified_invoice(reported_attendance=950,
                                      contracted_impressions=1000)
        resp = api.create_make_good(ctx["invoice"]["id"], make_auditor_headers(AUDITOR_1))
        validate_error(resp, ApiErrorId.ERR_MAKE_GOOD_THRESHOLD_NOT_MET)

    def test_make_good_threshold_exactly_5pct_creates_nothing(self, api):
        """PRD §3.7: "Eligibility is a strict threshold — the ratio must be
        greater than 0.05, so a campaign under-delivered by exactly five percent
        earns nothing and the proposal is rejected with
        `ERR_MAKE_GOOD_THRESHOLD_NOT_MET` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/make_good_threshold_exactly_5pct_rejected
        """
        ctx = setup_certified_invoice(reported_attendance=950,
                                      contracted_impressions=1000)
        api.create_make_good(ctx["invoice"]["id"], make_auditor_headers(AUDITOR_1))
        resp = api.list_make_goods(ctx["invoice"]["id"], make_auditor_headers(AUDITOR_1))
        credits = validate_success(resp)
        assert credits == [], f"no MakeGoodCredit may exist at exactly 5% under-delivery, got {credits}"


class TestMakeGoodComputedAndApplied:
    def test_make_good_eligible_credit_computed(self, api):
        """PRD §3.7: "`shortfall_impressions` is the campaign's
        `contracted_impressions` minus its current `delivered_impressions`,
        floored at zero, and `under_delivery_pct` is that shortfall divided by
        `contracted_impressions`."
        PRD §3.7: "The offered `credit_cents` is the shortfall multiplied by the
        campaign's `cpm_cents`, then multiplied by 1.10, divided by 1000, and
        rounded half-up to a whole cent — capped at the invoice's
        `audited_amount_cents`, so the credit never exceeds the audited bill."

        Design: Corner/calculations/make_good_eligible_credit_computed_and_applied
        """
        ctx = setup_certified_invoice(reported_attendance=940,
                                      contracted_impressions=1000)
        credit = propose_make_good(ctx["invoice"]["id"], proposer=AUDITOR_1)
        # Shortfall 60 of 1000; credit round_half_up(60 x 2500 x 1.10 / 1000) == 165.
        assert credit["shortfall_impressions"] == 60
        assert credit["under_delivery_pct"] == pytest.approx(0.06, abs=1e-9)
        assert credit["credit_cents"] == 165
        assert credit["credit_status"] == "PROPOSED"
        assert credit["proposed_by_user_id"] == AUDITOR_1

    def test_make_good_apply_moves_invoice_money(self, api):
        """PRD §3.7: "Application moves the credit `APPROVED → APPLIED`, adds
        its `credit_cents` into the invoice's `applied_credit_cents`, and
        subtracts the same amount from the invoice's `final_amount_cents`,
        preserving the invariant that `final_amount_cents` plus
        `applied_credit_cents` always equals `audited_amount_cents`."

        Design: Corner/calculations/make_good_eligible_credit_computed_and_applied
        """
        ctx = setup_certified_invoice(reported_attendance=940,
                                      contracted_impressions=1000)
        invoice = ctx["invoice"]
        credit = propose_make_good(invoice["id"], proposer=AUDITOR_1)
        approve_make_good(credit["id"], reviewer=AUDITOR_2)
        applied = apply_make_good(credit["id"], invoice["id"], applier=SM_CREATOR)
        assert applied["credit_status"] == "APPLIED"
        resp = api.get_invoice(invoice["id"], make_sales_manager_headers(SM_CREATOR))
        after = validate_success(resp)
        assert after["applied_credit_cents"] == 165
        assert after["audited_amount_cents"] == 2350
        assert after["final_amount_cents"] == 2185
        assert_invoice_money_invariant(after)


class TestMakeGoodCap:
    def test_make_good_credit_capped_at_audited_amount(self, api):
        """PRD §3.7: "The offered `credit_cents` is the shortfall multiplied by
        the campaign's `cpm_cents`, then multiplied by 1.10, divided by 1000,
        and rounded half-up to a whole cent — capped at the invoice's
        `audited_amount_cents`, so the credit never exceeds the audited bill."

        Design: Corner/calculations/make_good_credit_capped_at_audited_amount
        """
        ctx = setup_certified_invoice(reported_attendance=940,
                                      contracted_impressions=100000)
        credit = propose_make_good(ctx["invoice"]["id"], proposer=AUDITOR_1)
        # Shortfall 99060 of 100000; raw credit 272415 clamps to audited 2350.
        assert credit["shortfall_impressions"] == 99060
        assert credit["under_delivery_pct"] == pytest.approx(0.9906, abs=1e-9)
        assert credit["credit_cents"] == 2350


class TestMakeGoodStateMachine:
    def test_makegood_apply_before_review_rejected(self, api):
        """PRD §3.7: "the credit itself must be `APPROVED`, with any other state
        rejected as `ERR_MAKE_GOOD_NOT_REVIEWABLE`"

        Design: Corner/state_machines/makegood_apply_before_review_rejected
        """
        ctx = setup_certified_invoice(reported_attendance=940,
                                      contracted_impressions=1000)
        credit = propose_make_good(ctx["invoice"]["id"], proposer=AUDITOR_1)
        version = get_invoice_version(ctx["invoice"]["id"])
        resp = api.apply_make_good(credit["id"], {"expected_invoice_version": version},
                                   make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_MAKE_GOOD_NOT_REVIEWABLE)
        resp = api.list_make_goods(ctx["invoice"]["id"], make_auditor_headers(AUDITOR_1))
        credits = validate_success(resp)
        assert credits[0]["credit_status"] == "PROPOSED"
