"""Auto-renew consent lifecycle and non-dues revenue attribution.

Covers Queue A difficulty instances:
- cross_entity_state_dependency/auto_renew_enroll_gated_on_category_allows_auto_renew
- dual_variant_calc/chapter_share_vs_national_revenue_attribution_divergent_aggregation
- compensating_invariant/benefit_entitlement_count_conserved_under_suspend_restore_cycle

Covers Queue B corner instances:
- validations/revenue_attribution_dues_kind_rejected
- validations/member_email_uniqueness_enforced
- validations/inactive_reference_retired_category_rejected_on_member_create
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_category,
    create_chapter,
    create_cycle_policy,
    create_published_schedule,
    create_member,
    get_initial_invoice,
    settle_invoice,
    verify_member,
    advance_clock_and_run,
    get_pending_renewal_invoice,
    make_member_headers,
    list_benefits,
    TEST_USERS,
)

DUES_ADMIN = TEST_USERS["dues_admin_headers"]
MEMBERSHIP_ADMIN = TEST_USERS["membership_admin_headers"]


# =====================================================================
# Queue A — cross_entity_state_dependency/auto_renew_enroll_gated_on_category_allows_auto_renew
# =====================================================================

class TestAutoRenewEnrollGating:
    def test_enroll_rejected_when_category_disallows_auto_renew(self, api):
        """PRD §3.8: "Enrollment against a category whose allows_auto_renew is false
        is rejected with ERR_AUTO_RENEW_NOT_ALLOWED."

        Design: Difficulty/cross_entity_state_dependency/auto_renew_enroll_gated_on_category_allows_auto_renew
        """
        cat = create_category(code="RETIRED_LTD", name="Retired Limited",
                               is_voting=False, is_directory_eligible=False,
                               allows_auto_renew=False)
        ch = create_chapter(code="CH", name="C")
        pol = create_cycle_policy(code="POLICY", mode="ANNIVERSARY",
                                   calendar_anchor_month=1, calendar_anchor_day=1,
                                   proration_method="NONE")
        create_published_schedule(cat["id"],
                                   effective_from="2026-01-01T00:00:00Z",
                                   annual_amount_cents=50000, chapter_share_bps=1000,
                                   increase_notice_days=60)
        m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
        mh = make_member_headers(m["id"])
        inv = get_initial_invoice(m["id"], mh)
        settle_invoice(inv["id"], mh)
        verify_member(m["id"])
        enroll_resp = api_client.enroll_auto_renew(
            m["id"], {"payment_method_token": "tok_v"}, mh
        )
        validate_error(enroll_resp, ApiErrorId.ERR_AUTO_RENEW_NOT_ALLOWED)

    def test_enroll_succeeds_when_category_allows_auto_renew(self, api):
        """PRD §3.8: "A member whose category's allows_auto_renew is true may enroll
        in auto-renewal by submitting a payment_method_token. Enrollment creates an
        AutoRenewAuthorization row with member_id set, authorized_at stamped from the
        logical clock, revoked_at left null, and status set to ACTIVE."

        Design: Difficulty/cross_entity_state_dependency/auto_renew_enroll_gated_on_category_allows_auto_renew
        """
        cat = create_category(code="PROF", name="P", allows_auto_renew=True)
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
        verify_member(m["id"])
        enroll_resp = api_client.enroll_auto_renew(
            m["id"], {"payment_method_token": "tok_v"}, mh
        )
        auth = validate_success(enroll_resp, expected_status=201)
        assert auth["status"] == "ACTIVE"
        assert auth["member_id"] == m["id"]


# =====================================================================
# Queue A — dual_variant_calc/chapter_share_vs_national_revenue_attribution_divergent_aggregation
# =====================================================================

class TestChapterShareVsRevenueAttribution:
    def test_chapter_share_accrues_and_revenue_attribution_does_not_touch_dues_ledger(self, api):
        """PRD §3.5: "The chapter-share ledger accrues chapter_share_cents to the
        member's home_chapter_id, computed as the invoice's amount_cents multiplied by
        the schedule's chapter_share_bps, divided by 10000, rounded half-up to a whole
        cent..."
        PRD §3.10: "The member's lifetime_dues_paid_cents is not changed by these
        attributions — that accumulator counts settled dues invoices only."

        120000 * 2000 / 10000 = 24000.

        Design: Difficulty/dual_variant_calc/chapter_share_vs_national_revenue_attribution_divergent_aggregation
        """
        cat = create_category(code="PROF_ACTIVE", name="Professional")
        ch = create_chapter(code="CH_EAST", name="East Chapter")
        pol = create_cycle_policy(code="POLICY_ANN", mode="ANNIVERSARY",
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
        # Three non-dues attributions
        for kind, amt, at in [
            ("CONFERENCE_REGISTRATION", 45000, "2026-06-05T10:00:00Z"),
            ("PUBLICATION_SALE", 8000, "2026-06-12T10:00:00Z"),
            ("CERTIFICATION_FEE", 15000, "2026-07-01T10:00:00Z"),
        ]:
            r = api_client.create_revenue_attribution(
                m["id"],
                {"revenue_kind": kind, "amount_cents": amt, "occurred_at": at},
                MEMBERSHIP_ADMIN,
            )
            validate_success(r, expected_status=201)
        inv_after = get_success_data(api_client.get_dues_invoice(inv["id"], MEMBERSHIP_ADMIN))
        assert inv_after["chapter_share_cents"] == 24000
        m_after = get_success_data(api_client.get_member(m["id"], MEMBERSHIP_ADMIN))
        assert m_after["lifetime_dues_paid_cents"] == 120000, (
            "RevenueAttribution must not pollute lifetime_dues_paid_cents"
        )

    def test_revenue_attribution_rolls_up_by_fiscal_period(self, api):
        """PRD §3.10: "On creation, the server derives fiscal_period as the YYYY-MM
        string of occurred_at and appends the row to the member's non-dues ledger."

        Two attributions in 2026-06 (45000 + 8000 = 53000); one in 2026-07 (15000).

        Design: Difficulty/dual_variant_calc/chapter_share_vs_national_revenue_attribution_divergent_aggregation
        """
        cat = create_category(code="PROF_ACTIVE", name="Professional")
        ch = create_chapter(code="CH_EAST", name="East Chapter")
        pol = create_cycle_policy(code="POLICY_ANN", mode="ANNIVERSARY",
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
        for kind, amt, at in [
            ("CONFERENCE_REGISTRATION", 45000, "2026-06-05T10:00:00Z"),
            ("PUBLICATION_SALE", 8000, "2026-06-12T10:00:00Z"),
            ("CERTIFICATION_FEE", 15000, "2026-07-01T10:00:00Z"),
        ]:
            r = api_client.create_revenue_attribution(
                m["id"],
                {"revenue_kind": kind, "amount_cents": amt, "occurred_at": at},
                MEMBERSHIP_ADMIN,
            )
            validate_success(r, expected_status=201)
        jun = get_success_data(api_client.list_revenue_attributions(
            m["id"], MEMBERSHIP_ADMIN, params={"fiscal_period": "2026-06"}
        ))
        jul = get_success_data(api_client.list_revenue_attributions(
            m["id"], MEMBERSHIP_ADMIN, params={"fiscal_period": "2026-07"}
        ))
        sum_jun = sum(row["amount_cents"] for row in jun)
        sum_jul = sum(row["amount_cents"] for row in jul)
        assert sum_jun == 53000, f"expected 2026-06 sum=53000, got {sum_jun}"
        assert sum_jul == 15000, f"expected 2026-07 sum=15000, got {sum_jul}"


# =====================================================================
# Queue A — compensating_invariant/benefit_entitlement_count_conserved_under_suspend_restore_cycle
# =====================================================================

class TestBenefitEntitlementCountConservation:
    def _setup_active_member(self):
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
        verify_member(m["id"])
        return m, mh

    def test_five_default_entitlements_all_active_after_grace_cycle(self, api):
        """PRD §3.6: "A BenefitEntitlement row is created for each benefit the category
        confers by default — drawn from the set JOURNAL_ACCESS, CONFERENCE_DISCOUNT,
        CERTIFICATION_REGISTRY, VOTING_BALLOT, and DIRECTORY_LISTING, with the chosen
        value recorded on the row's benefit_code field and with VOTING_BALLOT granted
        only when the category's is_voting is true..."
        PRD §3.7: "Every BenefitEntitlement in SUSPENDED transitions back to ACTIVE."
        (grace-recovery path)

        Category is_voting=true -> 5 default rows. After GRACE then renewal settle,
        all 5 must be ACTIVE again; no row created or destroyed.

        Design: Difficulty/compensating_invariant/benefit_entitlement_count_conserved_under_suspend_restore_cycle
        """
        m, mh = self._setup_active_member()
        benefits_initial = list_benefits(m["id"], MEMBERSHIP_ADMIN)
        assert len(benefits_initial) == 5
        advance_clock_and_run("2027-05-15T00:00:00Z")
        inv_r = get_pending_renewal_invoice(m["id"])
        settle_invoice(inv_r["id"], mh)
        benefits_after = list_benefits(m["id"], MEMBERSHIP_ADMIN)
        assert len(benefits_after) == 5
        for b in benefits_after:
            assert b["status"] == "ACTIVE", (
                f"BenefitEntitlement {b.get('id')} must be ACTIVE after renewal settle; "
                f"got {b['status']}"
            )
        m_after = get_success_data(api_client.get_member(m["id"], MEMBERSHIP_ADMIN))
        assert m_after["status"] == "ACTIVE"

    def test_entitlements_suspended_while_member_in_grace(self, api):
        """PRD §3.7: "When the logical clock advances past the member's
        current_period_end and no SETTLED renewal invoice covers the next period, the
        scheduler transitions the member from ACTIVE to GRACE. Every BenefitEntitlement
        row for the member transitions to SUSPENDED."

        Design: Difficulty/compensating_invariant/benefit_entitlement_count_conserved_under_suspend_restore_cycle
        """
        m, mh = self._setup_active_member()
        advance_clock_and_run("2027-05-15T00:00:00Z")
        m_now = get_success_data(api_client.get_member(m["id"], MEMBERSHIP_ADMIN))
        assert m_now["status"] == "GRACE"
        benefits = list_benefits(m["id"], MEMBERSHIP_ADMIN)
        assert len(benefits) == 5
        for b in benefits:
            assert b["status"] == "SUSPENDED"


# =====================================================================
# Queue B — validations/revenue_attribution_dues_kind_rejected
# =====================================================================

def test_revenue_attribution_dues_kind_rejected(api):
    """PRD §3.10: "A revenue_kind of DUES is forbidden in this ledger, and a
    non-positive amount_cents is rejected; either failure surfaces as
    ERR_INVALID_REVENUE_KIND."

    Design: Corner/validations/revenue_attribution_dues_kind_rejected
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
    resp = api_client.create_revenue_attribution(
        m["id"],
        {"revenue_kind": "DUES", "amount_cents": 100, "occurred_at": "2026-05-15T00:00:00Z"},
        MEMBERSHIP_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REVENUE_KIND)


# =====================================================================
# Queue B — validations/member_email_uniqueness_enforced
# =====================================================================

def test_member_email_uniqueness_enforced(api):
    """PRD §3.3: "The email must be unique across the system — a duplicate is
    rejected with ERR_DUPLICATE_EMAIL."

    Design: Corner/validations/member_email_uniqueness_enforced
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
    create_member(cat["id"], ch["id"], pol["id"], email="m@x.com", full_name="M1")
    dup_resp = api_client.create_member(
        {
            "email": "m@x.com", "full_name": "M2",
            "category_id": cat["id"], "home_chapter_id": ch["id"],
            "cycle_policy_id": pol["id"], "joined_at": "2026-05-01T00:00:00Z",
        },
        make_member_headers("registrar"),
    )
    validate_error(dup_resp, ApiErrorId.ERR_DUPLICATE_EMAIL)


# =====================================================================
# Queue B — validations/inactive_reference_retired_category_rejected_on_member_create
# =====================================================================

def test_member_create_with_nonexistent_chapter_reference_returns_not_found(api):
    """PRD §2.5: "(3) existence of every path id and every referenced body id
    (member, invoice, schedule, chapter, category, cycle policy, and so on) —
    failures yield ERR_NOT_FOUND." Priority 3 precedes priority 10
    (active-reference), so a non-existent chapter reference surfaces as
    ERR_NOT_FOUND.
    PRD §2.6: "The same discipline applies to referenced body ids: a request that
    names a category_id, a home_chapter_id, or a cycle_policy_id is rejected with
    ERR_NOT_FOUND if any of those references does not resolve."

    Design: Corner/validations/inactive_reference_retired_category_rejected_on_member_create
    """
    cat = create_category(code="PROF", name="P")
    pol = create_cycle_policy(code="POLICY", mode="ANNIVERSARY",
                               calendar_anchor_month=1, calendar_anchor_day=1,
                               proration_method="NONE")
    resp = api_client.create_member(
        {
            "email": "m@x.com", "full_name": "M",
            "category_id": cat["id"], "home_chapter_id": NON_EXISTENT_UUID,
            "cycle_policy_id": pol["id"], "joined_at": "2026-05-01T00:00:00Z",
        },
        make_member_headers("registrar"),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
