"""Make-good proposals, credit ceiling, negotiation loop, and the
apply/reverse compensating pair."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    assert_make_good,
    create_make_good_payload,
    ApiErrorId, make_analyst_headers, make_billing_headers,
    setup_live_line_item, file_verification_report, setup_breach_report,
    propose_make_good, decide_make_good, get_io,
)


class TestCreditCeiling:
    def test_credit_ceiling_exact_ok_over_rejected(self, api):
        """PRD §3.5: "`credit_cents` is required when the kind is `CREDIT`,
        must be greater than zero, and may not exceed the report's
        `make_good_max_credit_cents` (`ERR_CREDIT_EXCEEDS_BASIS`);
        `bonus_impressions` is required when the kind is `BONUS_IMPRESSIONS`
        and must be greater than zero. Both amount fields default to null
        when not supplied."

        Design: Corner/validations/credit_ceiling_exact_ok_over_rejected
        """
        ctx = setup_live_line_item()
        li_id = ctx["line_item"]["id"]
        # viewability 0.69 < 0.70 (shortfall 1000) and ivt 2100 -> BREACH.
        report = file_verification_report(
            li_id, vendor="MOAT", measured_impressions=100000,
            viewable_impressions=69000, ivt_impressions=2100)
        # ceiling = (2100 + 1000) * 500 / 1000 = 1550.
        assert report["make_good_max_credit_cents"] == 1550

        at_ceiling = propose_make_good(report["id"], kind="CREDIT",
                                       credit_cents=1550)
        assert_make_good(at_ceiling)
        assert at_ceiling["status"] == "PROPOSED", (
            "A credit exactly at the ceiling is allowed")

        res = api.create_make_good(
            create_make_good_payload(report["id"], kind="CREDIT",
                                     credit_cents=1551),
            make_analyst_headers("va-1"))
        validate_error(res, ApiErrorId.ERR_CREDIT_EXCEEDS_BASIS.value, 422)

        bonus_res = api.create_make_good(
            {"verification_report_id": report["id"],
             "kind": "BONUS_IMPRESSIONS", "bonus_impressions": 5000},
            make_analyst_headers("va-1"))
        bonus = validate_success(bonus_res, 201)
        assert bonus["kind"] == "BONUS_IMPRESSIONS"
        assert bonus["credit_cents"] is None, (
            "credit_cents defaults to null when not supplied")
        assert bonus["bonus_impressions"] == 5000

    def test_make_good_on_pass_report_rejected(self, api, analyst_headers):
        """PRD §3.5: "proposing against a passing report or a closed one
        fails with `ERR_NO_BREACH`."

        Design: Corner/validations/make_good_on_pass_report_rejected
        """
        ctx = setup_live_line_item()
        report = file_verification_report(
            ctx["line_item"]["id"], vendor="MOAT",
            measured_impressions=100000, viewable_impressions=80000,
            ivt_impressions=0)
        assert report["assessment"] == "PASS"

        res = api.create_make_good(
            create_make_good_payload(report["id"], kind="CREDIT",
                                     credit_cents=100),
            analyst_headers)
        validate_error(res, ApiErrorId.ERR_NO_BREACH.value, 409)


class TestNegotiationLoop:
    def test_make_good_reject_revise_loop(self, api):
        """PRD §3.5: "A `REJECTED` make-good is not final: the analyst may
        revise it back to `PROPOSED`, which clears `decided_by_user_id` to
        null, and the propose-reject-revise loop may repeat."

        Design: Corner/state_machines/make_good_reject_revise_loop
        """
        ctx = setup_live_line_item()
        report = setup_breach_report(ctx["line_item"]["id"], vendor="IAS")
        mg = propose_make_good(report["id"], kind="CREDIT", credit_cents=1000)
        rejected = decide_make_good(mg["id"], "REJECT", user_id="bm-2")
        assert rejected["status"] == "REJECTED"
        assert rejected["decided_by_user_id"] == "bm-2"

        res = api.transition_make_good(mg["id"], {"action": "REVISE"},
                                       make_analyst_headers("va-1"))
        revised = validate_success(res, 200)
        assert revised["status"] == "PROPOSED"
        assert revised["decided_by_user_id"] is None, (
            "REVISE must clear decided_by_user_id to null")


class TestApplyReverseInvariant:
    def _approved_make_good(self):
        """LIVE line item + IVT-breach report + APPROVED credit make-good."""
        ctx = setup_live_line_item()
        report = setup_breach_report(ctx["line_item"]["id"], vendor="IAS")
        mg = propose_make_good(report["id"], kind="CREDIT", credit_cents=2000)
        decide_make_good(mg["id"], "APPROVE", user_id="bm-2")
        return ctx, report, mg

    def test_apply_reverse_restores_credit(self, api):
        """PRD §2.10: "after apply followed by reverse of the same make-good,
        the parent order's `total_applied_credit_cents` returns to its
        pre-pair value, because only `APPLIED` make-goods count toward it."

        Design: Difficulty/compensating_invariant/make_good_apply_reverse_restores_credit
        """
        ctx, _report, mg = self._approved_make_good()
        io_id = ctx["io"]["id"]
        assert get_io(io_id)["total_applied_credit_cents"] == 0

        decide_make_good(mg["id"], "APPLY", user_id="bm-2")
        assert get_io(io_id)["total_applied_credit_cents"] == 2000

        reversed_mg = decide_make_good(mg["id"], "REVERSE", user_id="bm-2")
        assert reversed_mg["status"] == "REVERSED"
        assert get_io(io_id)["total_applied_credit_cents"] == 0

    def test_only_applied_make_goods_count_toward_credit(self, api):
        """PRD §3.5: "Applying a decided credit (`APPROVED` → `APPLIED`)
        brings its `credit_cents` into the parent order's
        `total_applied_credit_cents` — the sum of `credit_cents` over
        `APPLIED` make-goods whose reports trace back to the order's line
        items — and reversing (`APPLIED` → `REVERSED`) takes it back out"

        Design: Difficulty/compensating_invariant/make_good_apply_reverse_restores_credit
        """
        ctx, _report, mg = self._approved_make_good()
        io_id = ctx["io"]["id"]

        # APPROVED but not yet APPLIED: the order total must not move.
        assert get_io(io_id)["total_applied_credit_cents"] == 0

        applied = decide_make_good(mg["id"], "APPLY", user_id="bm-2")
        assert applied["status"] == "APPLIED"
        assert get_io(io_id)["total_applied_credit_cents"] == 2000
