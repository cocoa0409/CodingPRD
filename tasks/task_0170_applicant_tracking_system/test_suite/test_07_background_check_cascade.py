"""Background check lifecycle and post-hire revoke cascade
— PRD §3.7.

Covers: order/PENDING, PASS, FAIL cascade on EXTENDED/APPROVED, the
post-hire revoke chain when FAIL arrives after ACCEPTED, cancel on
non-live offer.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    assert_background_check,
    cancel_background_check,
    get_application,
    get_background_check,
    get_offer,
    get_referral_bonus,
    get_requisition,
    list_referral_bonuses,
    order_background_check,
    report_bgc_fail,
    report_bgc_pass,
    setup_offer_accepted,
    setup_offer_approved,
    setup_offer_extended,
    setup_referral_hire,
    validate_error,
    validate_success,
)


# ===========================================================================
# Order + report PASS — PRD §3.7
# ===========================================================================
class TestBackgroundCheckHappyPath:

    def test_order_returns_pending(self, api):
        """PRD §3.7: "The new check is in `PENDING` with `ordered_at`
        stamped by the server and `result_received_at` null."

        Claim: POST /offers/{id}/background-check returns a check in
        PENDING with ordered_at populated and result_received_at null.
        """
        ctx = setup_offer_approved()
        # But the approve path already orders BG; we order a fresh one
        # on a new offer-stage offer to assert PENDING outcome
        # exactly. Use a NEW workflow.
        from test_helpers import (
            setup_offer_in_pending_approval,
        )
        ctx2 = setup_offer_in_pending_approval()
        bgc = order_background_check(
            offer_id=ctx2["offer"]["id"],
            recruiter_id=ctx2["recruiter"]["id"],
        )
        assert_background_check(bgc)
        assert bgc["status"] == "PENDING"
        assert bgc.get("result_received_at") is None

    def test_report_pass_transitions_to_passed(self, api):
        """PRD §3.7: "A `PASS` transitions the check to `PASSED`."

        Claim: /report-result outcome=PASS → status=PASSED and
        result_received_at populated.
        """
        from test_helpers import setup_offer_in_pending_approval
        ctx = setup_offer_in_pending_approval()
        bgc = order_background_check(
            offer_id=ctx["offer"]["id"],
            recruiter_id=ctx["recruiter"]["id"],
        )
        bgc = report_bgc_pass(bgc_id=bgc["id"])
        assert bgc["status"] == "PASSED"
        assert bgc.get("result_received_at") is not None


# ===========================================================================
# FAIL on EXTENDED — PRD §3.7
# ===========================================================================
class TestBgFailOnExtended:

    def test_fail_on_extended_offer_rescinds_offer(self, api):
        """PRD §3.7: "If the linked offer is in `APPROVED` or
        `EXTENDED` at the moment of `FAIL`, the offer is forced to
        `RESCINDED`, the parent requisition's `active_offer_count`
        is decremented by one, the hiring manager's `budget_cents` is
        credited back by the offer's `total_first_year_comp_cents`,
        and the parent application is auto-rejected with
        `rejection_reason` set to `FAILED_BACKGROUND_CHECK`."

        Claim: /report-result FAIL while Offer is EXTENDED →
        Offer.status==RESCINDED, Application.stage==REJECTED with
        rejection_reason==FAILED_BACKGROUND_CHECK.
        """
        ctx = setup_offer_extended()
        report_bgc_fail(bgc_id=ctx["background_check"]["id"])
        offer = get_offer(ctx["offer"]["id"])
        app = get_application(ctx["application"]["id"])
        assert offer["status"] == "RESCINDED", (
            f"After BG FAIL on EXTENDED, offer.status must be "
            f"RESCINDED, got {offer['status']!r}"
        )
        assert app["stage"] == "REJECTED", (
            f"Application must auto-REJECTED, got {app['stage']!r}"
        )
        assert app.get("rejection_reason") == "FAILED_BACKGROUND_CHECK", (
            f"rejection_reason must be FAILED_BACKGROUND_CHECK, got "
            f"{app.get('rejection_reason')!r}"
        )


# ===========================================================================
# Post-hire revoke cascade — PRD §3.7
# ===========================================================================
class TestPostHireRevokeChain:

    def test_fail_after_accepted_unwinds_hire(self, api):
        """PRD §3.7: "If instead the linked offer has already been
        `ACCEPTED` — that is, the hire has been recorded — the
        cascade is broader (this is the post-hire revoke chain): the
        offer transitions `ACCEPTED` → `RESCINDED`; the parent
        application transitions `HIRED` → `REJECTED` with
        `rejection_reason` set to `FAILED_BACKGROUND_CHECK`; the
        parent requisition's `filled_count` is decremented by one;
        if the requisition was already in `CLOSED`, it is reopened
        back to `OPEN` and `closed_at` is cleared".

        Claim: BG FAIL on ACCEPTED Offer drives Offer→RESCINDED,
        Application→REJECTED with FAILED_BACKGROUND_CHECK,
        Requisition.filled_count back to 0, Requisition reopened to
        OPEN with closed_at cleared.
        """
        # Single-headcount → ACCEPTED hits CLOSED on the requisition.
        ctx = setup_offer_accepted()
        assert ctx["requisition"]["status"] == "CLOSED", (
            f"Pre-condition: req must be CLOSED after the hire, got "
            f"{ctx['requisition']['status']!r}"
        )
        assert ctx["requisition"]["filled_count"] == 1
        # Now fire FAIL.
        report_bgc_fail(bgc_id=ctx["background_check"]["id"])
        offer = get_offer(ctx["offer"]["id"])
        app = get_application(ctx["application"]["id"])
        req = get_requisition(ctx["requisition"]["id"])
        assert offer["status"] == "RESCINDED"
        assert app["stage"] == "REJECTED"
        assert app["rejection_reason"] == "FAILED_BACKGROUND_CHECK"
        assert req["filled_count"] == 0, (
            f"filled_count must decrement to 0, got {req['filled_count']}"
        )
        assert req["status"] == "OPEN", (
            f"Requisition must reopen to OPEN, got {req['status']!r}"
        )
        assert req.get("closed_at") is None, (
            f"closed_at must be cleared on reopen, got {req.get('closed_at')!r}"
        )

    def test_fail_after_accepted_clawbacks_referral_bonus(self, api):
        """PRD §3.7: "any `ReferralBonus` tied to this hire is
        transitioned to `CLAWED_BACK` regardless of whether it was
        previously `ACCRUED` or `PAYABLE`."

        Claim: after BG FAIL on an ACCEPTED referral hire,
        ReferralBonus.status == CLAWED_BACK.
        """
        ctx = setup_referral_hire()
        # The hire produced at least one ReferralBonus.
        assert len(ctx["referral_bonuses"]) >= 1, (
            "expected at least one ReferralBonus to be created on hire"
        )
        rb_id = ctx["referral_bonuses"][0]["id"]
        report_bgc_fail(bgc_id=ctx["background_check"]["id"])
        rb = get_referral_bonus(rb_id)
        assert rb["status"] == "CLAWED_BACK", (
            f"ReferralBonus must be CLAWED_BACK after post-hire revoke, "
            f"got {rb['status']!r}"
        )


# ===========================================================================
# Cancel on non-live offer — PRD §3.7
# ===========================================================================
class TestBackgroundCheckCancel:

    def test_cancel_on_live_offer_rejected(self, api):
        """PRD §3.7: "A pending background check may also be cancelled
        by the recruiter, but only when the linked offer is in
        `NEGOTIATING`, `DECLINED`, `RESCINDED`, or `EXPIRED` (in other
        words, the offer is no longer a live candidate for a hire)."

        Claim: BG cancel attempted while Offer is in PENDING_APPROVAL
        (a live state) → ERR_INVALID_STATE / 409.
        """
        from test_helpers import (
            setup_offer_in_pending_approval, make_recruiter_headers,
        )
        ctx = setup_offer_in_pending_approval()
        bgc = order_background_check(
            offer_id=ctx["offer"]["id"],
            recruiter_id=ctx["recruiter"]["id"],
        )
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        resp = api.cancel_background_check(bgc["id"], h)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
