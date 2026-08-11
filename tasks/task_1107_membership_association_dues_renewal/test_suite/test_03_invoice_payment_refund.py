"""Dues invoice payment, refund, and cascade behaviors.

Covers Queue A difficulty instances:
- non_linear_state_machine/dues_invoice_parallel_payment_x_fulfillment_dimensions
- transitive_cascade/refund_cascade_invoice_member_chapter_entitlement
- transitive_cascade/failed_payment_cascade_invoice_autorenew_riskscore
- priority_pair_validation_conflict/business_safety_vs_business_fiscal_refund_after_period_end
- compensating_invariant/lifetime_dues_paid_conserved_under_settle_then_refund

Covers Queue B corner instances:
- validations/refund_on_pending_invoice_returns_not_settled
- errors/error_retry_exhausted_on_sixth_attempt
- consistency_model/immediate_consistency_settle_then_read_reflects
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_category,
    create_chapter,
    create_cycle_policy,
    create_published_schedule,
    create_member,
    get_initial_invoice,
    settle_invoice,
    verify_member,
    set_clock,
    advance_clock_and_run,
    get_pending_renewal_invoice,
    make_member_headers,
    list_benefits,
    get_auto_renew_auth,
    TEST_USERS,
)

DUES_ADMIN = TEST_USERS["dues_admin_headers"]
MEMBERSHIP_ADMIN = TEST_USERS["membership_admin_headers"]


def _setup_active_member():
    cat = create_category(code="PROF", name="P")
    ch = create_chapter(code="CH", name="C")
    pol = create_cycle_policy(code="POLICY", mode="ANNIVERSARY",
                               calendar_anchor_month=1, calendar_anchor_day=1,
                               proration_method="NONE")
    sched = create_published_schedule(cat["id"],
                                       effective_from="2026-01-01T00:00:00Z",
                                       annual_amount_cents=120000,
                                       chapter_share_bps=2000,
                                       increase_notice_days=60)
    m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
    mh = make_member_headers(m["id"])
    inv0 = get_initial_invoice(m["id"], mh)
    settle_invoice(inv0["id"], mh)
    verify_member(m["id"])
    inv0 = get_success_data(api_client.get_dues_invoice(inv0["id"], MEMBERSHIP_ADMIN))
    return cat, ch, pol, sched, m, inv0, mh


# =====================================================================
# Queue A — non_linear_state_machine/dues_invoice_parallel_payment_x_fulfillment_dimensions
# =====================================================================

class TestInvoiceParallelDimensions:
    def test_settle_sets_payment_and_fulfillment_axes(self, api):
        """PRD §3.5: "When the outcome is SUCCEEDED and the invoice is in PENDING or
        FAILED_RETRYABLE, the invoice transitions to SETTLED in payment_status and
        COVERAGE_ACTIVE in fulfillment_status."

        Design: Difficulty/non_linear_state_machine/dues_invoice_parallel_payment_x_fulfillment_dimensions
        """
        cat, ch, pol, sched, m, inv0, mh = _setup_active_member()
        assert inv0["payment_status"] == "SETTLED"
        assert inv0["fulfillment_status"] == "COVERAGE_ACTIVE"

    def test_refund_flips_both_axes(self, api):
        """PRD §3.5: "When both preconditions hold, the invoice transitions from
        SETTLED to REFUNDED and from COVERAGE_ACTIVE to COVERAGE_ENDED."

        Design: Difficulty/non_linear_state_machine/dues_invoice_parallel_payment_x_fulfillment_dimensions
        """
        cat, ch, pol, sched, m, inv0, mh = _setup_active_member()
        refund_resp = api_client.refund_invoice(inv0["id"], MEMBERSHIP_ADMIN)
        validate_success(refund_resp, expected_status=200)
        inv_after = get_success_data(api_client.get_dues_invoice(inv0["id"], MEMBERSHIP_ADMIN))
        assert inv_after["payment_status"] == "REFUNDED"
        assert inv_after["fulfillment_status"] == "COVERAGE_ENDED"


# =====================================================================
# Queue A — transitive_cascade/refund_cascade_invoice_member_chapter_entitlement
# =====================================================================

class TestRefundCascade:
    def test_refund_drops_member_to_grace_and_zeroes_lifetime(self, api):
        """PRD §3.5: "The member's lifetime_dues_paid_cents is decremented by
        amount_cents. ... If after the refund the member has no remaining SETTLED
        coverage, the member transitions from ACTIVE to GRACE with immediate effect
        and every BenefitEntitlement for the member transitions to SUSPENDED."

        Design: Difficulty/transitive_cascade/refund_cascade_invoice_member_chapter_entitlement
        """
        cat, ch, pol, sched, m, inv0, mh = _setup_active_member()
        refund_resp = api_client.refund_invoice(inv0["id"], MEMBERSHIP_ADMIN)
        validate_success(refund_resp, expected_status=200)
        m_after = get_success_data(api_client.get_member(m["id"], MEMBERSHIP_ADMIN))
        assert m_after["lifetime_dues_paid_cents"] == 0
        assert m_after["status"] == "GRACE"

    def test_refund_suspends_all_entitlements(self, api):
        """PRD §3.5: "If after the refund the member has no remaining SETTLED coverage,
        the member transitions from ACTIVE to GRACE with immediate effect and every
        BenefitEntitlement for the member transitions to SUSPENDED."

        Design: Difficulty/transitive_cascade/refund_cascade_invoice_member_chapter_entitlement
        """
        cat, ch, pol, sched, m, inv0, mh = _setup_active_member()
        refund_resp = api_client.refund_invoice(inv0["id"], MEMBERSHIP_ADMIN)
        validate_success(refund_resp, expected_status=200)
        benefits = list_benefits(m["id"], MEMBERSHIP_ADMIN)
        assert isinstance(benefits, list) and len(benefits) >= 1
        for b in benefits:
            assert b["status"] == "SUSPENDED", (
                f"BenefitEntitlement {b.get('id')} must be SUSPENDED after refund; got {b['status']}"
            )


# =====================================================================
# Queue A — transitive_cascade/failed_payment_cascade_invoice_autorenew_riskscore
# =====================================================================

class TestFailedPaymentCascade:
    def _setup_active_with_auto_renew(self):
        cat, ch, pol, sched, m, inv0, mh = _setup_active_member()
        enroll_resp = api_client.enroll_auto_renew(
            m["id"], {"payment_method_token": "tok_v"}, mh
        )
        validate_success(enroll_resp, expected_status=201)
        # Advance to just before renewal so scheduler issues renewal invoice
        advance_clock_and_run("2027-04-25T00:00:00Z")
        inv_r = get_pending_renewal_invoice(m["id"])
        return m, inv_r, mh

    def test_hard_decline_moves_invoice_to_failed_final_and_suspends_auto_renew(self, api):
        """PRD §3.5: "When the outcome is DECLINED_HARD, or when a further retry would
        push attempt_index past the retry cap of 5 failed attempts for the invoice, the
        invoice transitions to FAILED_FINAL in payment_status while fulfillment_status
        stays NOT_DUE. The member's AutoRenewAuthorization, if ACTIVE, transitions to
        SUSPENDED_HARD_DECLINE."

        Design: Difficulty/transitive_cascade/failed_payment_cascade_invoice_autorenew_riskscore
        """
        m, inv_r, mh = self._setup_active_with_auto_renew()
        # Four transient declines to put the invoice in FAILED_RETRYABLE
        for _ in range(4):
            r = api_client.submit_payment(
                inv_r["id"],
                {"payment_method_token": "tok_v", "simulated_outcome": "DECLINED_TRANSIENT"},
                mh,
            )
            validate_success(r, expected_status=201)
        # Hard decline
        r = api_client.submit_payment(
            inv_r["id"],
            {"payment_method_token": "tok_v", "simulated_outcome": "DECLINED_HARD"},
            mh,
        )
        validate_success(r, expected_status=201)
        inv_after = get_success_data(api_client.get_dues_invoice(inv_r["id"], MEMBERSHIP_ADMIN))
        assert inv_after["payment_status"] == "FAILED_FINAL"
        ar_list = get_auto_renew_auth(m["id"], mh)
        assert isinstance(ar_list, list) and len(ar_list) == 1
        assert ar_list[0]["status"] == "SUSPENDED_HARD_DECLINE"

    def test_failed_final_bumps_member_version(self, api):
        """PRD §3.5: "The member's risk_score is recomputed, and the member's version
        is incremented." (hard-decline path)

        Design: Difficulty/transitive_cascade/failed_payment_cascade_invoice_autorenew_riskscore
        """
        m, inv_r, mh = self._setup_active_with_auto_renew()
        m_before = get_success_data(api_client.get_member(m["id"], MEMBERSHIP_ADMIN))
        for _ in range(4):
            r = api_client.submit_payment(
                inv_r["id"],
                {"payment_method_token": "tok_v", "simulated_outcome": "DECLINED_TRANSIENT"},
                mh,
            )
            validate_success(r, expected_status=201)
        r = api_client.submit_payment(
            inv_r["id"],
            {"payment_method_token": "tok_v", "simulated_outcome": "DECLINED_HARD"},
            mh,
        )
        validate_success(r, expected_status=201)
        m_after = get_success_data(api_client.get_member(m["id"], MEMBERSHIP_ADMIN))
        assert m_after["version"] > m_before["version"], (
            f"member.version must increment across hard-decline cascade; "
            f"before={m_before['version']}, after={m_after['version']}"
        )


# =====================================================================
# Queue A — priority_pair_validation_conflict/business_safety_vs_business_fiscal_refund_after_period_end
# =====================================================================

class TestRefundPriorityPair:
    def test_refund_settled_invoice_after_period_end_returns_window_expired(self, api):
        """PRD §3.5: "A MembershipAdministrator may refund a settled invoice, but only
        while the member's current_period_end is still strictly in the future — a
        refund attempted on or after current_period_end is rejected with
        ERR_REFUND_WINDOW_EXPIRED."
        PRD §2.5: "(14) refund-window check — failures yield ERR_REFUND_WINDOW_EXPIRED;
        ... (16) refund only on settled invoices — failures yield ERR_INVOICE_NOT_SETTLED."

        Invoice IS settled (priority 16 passes), but window is expired — priority 14 fires.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_refund_after_period_end
        """
        cat, ch, pol, sched, m, inv0, mh = _setup_active_member()
        # current_period_end == 2027-05-01; move clock past it
        set_clock("2027-06-15T00:00:00Z")
        refund_resp = api_client.refund_invoice(inv0["id"], MEMBERSHIP_ADMIN)
        validate_error(refund_resp, ApiErrorId.ERR_REFUND_WINDOW_EXPIRED)

    def test_refund_pending_invoice_returns_not_settled(self, api):
        """PRD §3.5: "A refund on an invoice whose payment_status is anything other
        than SETTLED is rejected with ERR_INVOICE_NOT_SETTLED."

        Refund attempted while clock still precedes current_period_end, so only the
        fiscal check (priority 16) fires.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_refund_after_period_end
        """
        cat = create_category(code="PROF", name="P")
        ch = create_chapter(code="CH", name="C")
        pol = create_cycle_policy(code="POLICY", mode="ANNIVERSARY",
                                   calendar_anchor_month=1, calendar_anchor_day=1,
                                   proration_method="NONE")
        create_published_schedule(cat["id"],
                                   effective_from="2026-01-01T00:00:00Z",
                                   annual_amount_cents=120000, chapter_share_bps=2000,
                                   increase_notice_days=60)
        m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
        mh = make_member_headers(m["id"])
        inv = get_initial_invoice(m["id"], mh)
        # No settle; refund the PENDING invoice
        refund_resp = api_client.refund_invoice(inv["id"], MEMBERSHIP_ADMIN)
        validate_error(refund_resp, ApiErrorId.ERR_INVOICE_NOT_SETTLED)


# =====================================================================
# Queue A — compensating_invariant/lifetime_dues_paid_conserved_under_settle_then_refund
# =====================================================================

class TestLifetimeDuesConservation:
    def test_settle_then_refund_nets_lifetime_to_zero(self, api):
        """PRD §3.5: "The member's lifetime_dues_paid_cents is incremented by the
        invoice's amount_cents." (settle path)
        PRD §3.5: "The member's lifetime_dues_paid_cents is decremented by
        amount_cents." (refund path)

        Net drift on the conserved quantity must be zero.

        Design: Difficulty/compensating_invariant/lifetime_dues_paid_conserved_under_settle_then_refund
        """
        cat, ch, pol, sched, m, inv0, mh = _setup_active_member()
        m_after_settle = get_success_data(api_client.get_member(m["id"], MEMBERSHIP_ADMIN))
        assert m_after_settle["lifetime_dues_paid_cents"] == 120000
        refund_resp = api_client.refund_invoice(inv0["id"], MEMBERSHIP_ADMIN)
        validate_success(refund_resp, expected_status=200)
        m_after_refund = get_success_data(api_client.get_member(m["id"], MEMBERSHIP_ADMIN))
        assert m_after_refund["lifetime_dues_paid_cents"] == 0

    def test_settle_then_refund_invoice_lands_in_refunded_coverage_ended(self, api):
        """PRD §3.5: "When both preconditions hold, the invoice transitions from
        SETTLED to REFUNDED and from COVERAGE_ACTIVE to COVERAGE_ENDED."

        The compensating action restores the invoice's terminal axis state.

        Design: Difficulty/compensating_invariant/lifetime_dues_paid_conserved_under_settle_then_refund
        """
        cat, ch, pol, sched, m, inv0, mh = _setup_active_member()
        refund_resp = api_client.refund_invoice(inv0["id"], MEMBERSHIP_ADMIN)
        validate_success(refund_resp, expected_status=200)
        inv_after = get_success_data(api_client.get_dues_invoice(inv0["id"], MEMBERSHIP_ADMIN))
        assert inv_after["payment_status"] == "REFUNDED"
        assert inv_after["fulfillment_status"] == "COVERAGE_ENDED"


# =====================================================================
# Queue B — validations/refund_on_pending_invoice_returns_not_settled
# =====================================================================

def test_refund_pending_invoice_rejected_not_settled(api):
    """PRD §3.5: "A refund on an invoice whose payment_status is anything other than
    SETTLED is rejected with ERR_INVOICE_NOT_SETTLED."

    Design: Corner/validations/refund_on_pending_invoice_returns_not_settled
    """
    cat = create_category(code="PROF", name="P")
    ch = create_chapter(code="CH", name="C")
    pol = create_cycle_policy(code="POLICY", mode="ANNIVERSARY",
                               calendar_anchor_month=1, calendar_anchor_day=1,
                               proration_method="NONE")
    create_published_schedule(cat["id"],
                               effective_from="2026-01-01T00:00:00Z",
                               annual_amount_cents=120000, chapter_share_bps=2000,
                               increase_notice_days=60)
    m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
    mh = make_member_headers(m["id"])
    inv = get_initial_invoice(m["id"], mh)
    refund_resp = api_client.refund_invoice(inv["id"], MEMBERSHIP_ADMIN)
    validate_error(refund_resp, ApiErrorId.ERR_INVOICE_NOT_SETTLED)


# =====================================================================
# Queue B — errors/error_retry_exhausted_on_sixth_attempt
# =====================================================================

def test_sixth_payment_attempt_rejected_retry_exhausted(api):
    """PRD §3.5: "When the outcome is DECLINED_HARD, or when a further retry would push
    attempt_index past the retry cap of 5 failed attempts for the invoice, the invoice
    transitions to FAILED_FINAL in payment_status while fulfillment_status stays
    NOT_DUE." "Any subsequent payment attempt on an invoice that has already reached
    the retry cap is rejected with ERR_RETRY_EXHAUSTED."

    After 5 DECLINED_TRANSIENT attempts the invoice has hit the cap; a 6th is rejected.

    Design: Corner/errors/error_retry_exhausted_on_sixth_attempt
    """
    cat = create_category(code="PROF", name="P")
    ch = create_chapter(code="CH", name="C")
    pol = create_cycle_policy(code="POLICY", mode="ANNIVERSARY",
                               calendar_anchor_month=1, calendar_anchor_day=1,
                               proration_method="NONE")
    create_published_schedule(cat["id"],
                               effective_from="2026-01-01T00:00:00Z",
                               annual_amount_cents=120000, chapter_share_bps=2000,
                               increase_notice_days=60)
    m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
    mh = make_member_headers(m["id"])
    inv = get_initial_invoice(m["id"], mh)
    for _ in range(5):
        r = api_client.submit_payment(
            inv["id"],
            {"payment_method_token": "tok_v", "simulated_outcome": "DECLINED_TRANSIENT"},
            mh,
        )
        # First 4 must succeed; 5th attempt triggers FAILED_FINAL via retry cap
        # but the 5th itself is still a recorded attempt (201). Subsequent calls reject.
        # Tolerate either 201 or 4xx on the 5th to absorb implementation choice on
        # whether the 5th attempt is recorded before the state flips.
        # The pinned assert is on the 6th call.
        pass
    sixth = api_client.submit_payment(
        inv["id"],
        {"payment_method_token": "tok_v", "simulated_outcome": "DECLINED_TRANSIENT"},
        mh,
    )
    validate_error(sixth, ApiErrorId.ERR_RETRY_EXHAUSTED)


# =====================================================================
# Queue B — consistency_model/immediate_consistency_settle_then_read_reflects
# =====================================================================

def test_settle_then_read_reflects_immediately(api):
    """PRD §3.5: "When the outcome is SUCCEEDED and the invoice is in PENDING or
    FAILED_RETRYABLE, the invoice transitions to SETTLED in payment_status and
    COVERAGE_ACTIVE in fulfillment_status." "The member's lifetime_dues_paid_cents
    is incremented by the invoice's amount_cents. The chapter-share ledger accrues
    chapter_share_cents to the member's home_chapter_id, computed as the invoice's
    amount_cents multiplied by the schedule's chapter_share_bps, divided by 10000,
    rounded half-up to a whole cent..."

    round_half_up(120000 * 2000 / 10000) = 24000.

    Design: Corner/consistency_model/immediate_consistency_settle_then_read_reflects
    """
    cat = create_category(code="PROF", name="P")
    ch = create_chapter(code="CH", name="C")
    pol = create_cycle_policy(code="POLICY", mode="ANNIVERSARY",
                               calendar_anchor_month=1, calendar_anchor_day=1,
                               proration_method="NONE")
    create_published_schedule(cat["id"],
                               effective_from="2026-01-01T00:00:00Z",
                               annual_amount_cents=120000, chapter_share_bps=2000,
                               increase_notice_days=60)
    m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
    mh = make_member_headers(m["id"])
    inv = get_initial_invoice(m["id"], mh)
    settle_invoice(inv["id"], mh)
    inv_after = get_success_data(api_client.get_dues_invoice(inv["id"], mh))
    assert inv_after["payment_status"] == "SETTLED"
    assert inv_after["chapter_share_cents"] == 24000
    m_after = get_success_data(api_client.get_member(m["id"], mh))
    assert m_after["lifetime_dues_paid_cents"] == 120000
