"""Cross-entity gates and dual accumulator tests (PRD §3.5, §3.6, §3.8)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_employee_headers,
    make_recruiter_headers,
    create_employee,
    create_open_requisition,
    create_active_policy,
    create_active_campaign,
    submit_referral,
    setup_program,
    setup_verified_tax_profile,
    advance_referral_to_offer,
    hire_referral,
    get_hire_milestone,
    get_employee,
    create_referral_payload,
    api_client,
)


class TestMilestoneApproveGatedByTaxProfile:
    def test_approve_rejected_when_profile_missing_and_submitted(self, api):
        """PRD §3.6: "the tax gate — the referrer's tax profile must exist and be in
        `VERIFIED` status, otherwise `ERR_TAX_PROFILE_NOT_VERIFIED` (HTTP 422)".
        PRD §3.1: "Payout approval requires a verified profile, so an unreviewed edit
        deliberately blocks the approve step described in §3.6."

        Missing profile: rejected. SUBMITTED (unverified) profile: rejected again.

        Design: Difficulty/cross_entity_state_dependency/milestone_approve_gated_by_tax_profile_state
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="ca@x.com",
                              candidate_full_name="C A")
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])
        ms = get_hire_milestone(ref["id"])

        pp = TEST_USERS["payroll_processor_headers"]
        # No profile at all
        resp1 = api.approve_milestone(ms["id"], pp)
        validate_error(resp1, ApiErrorId.ERR_TAX_PROFILE_NOT_VERIFIED)

        # Profile exists but only SUBMITTED
        get_success_data(
            api.put_tax_profile(
                emp["id"], {"filing_status": "SINGLE", "withholding_method": "FLAT"},
                make_employee_headers(emp["id"]),
            )
        )
        resp2 = api.approve_milestone(ms["id"], pp)
        validate_error(resp2, ApiErrorId.ERR_TAX_PROFILE_NOT_VERIFIED)

    def test_approve_succeeds_after_verify_and_locks_withholding(self, api):
        """PRD §3.6: "On success the milestone's withholding is computed and *locked* at
        that instant, and `approved_by_user_id` records the approver." and "Under `FLAT`,
        the rate is the profile's `supplemental_rate_bps` when set, else the default 2200
        basis points".

        After verification the approve succeeds: status APPROVED, withholding 9900 on
        45000.

        Design: Difficulty/cross_entity_state_dependency/milestone_approve_gated_by_tax_profile_state
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="ca@x.com",
                              candidate_full_name="C A")
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])
        ms = get_hire_milestone(ref["id"])

        pp = TEST_USERS["payroll_processor_headers"]
        get_success_data(
            api.put_tax_profile(
                emp["id"], {"filing_status": "SINGLE", "withholding_method": "FLAT"},
                make_employee_headers(emp["id"]),
            )
        )
        get_success_data(api.verify_tax_profile(emp["id"], pp))

        data = get_success_data(api.approve_milestone(ms["id"], pp))
        assert data["status"] == "APPROVED"
        assert data["withholding_cents"] == 9900
        assert data["net_cents"] == 35100


class TestCampaignActivationGatedByPolicyState:
    def test_campaign_activation_rejected_without_active_policy(self, api):
        """PRD §3.2: "Activation requires, checked in this order, that some policy version
        is currently `ACTIVE` (otherwise `ERR_NO_ACTIVE_POLICY`)".

        With no ACTIVE policy the activation fails.

        Design: Difficulty/cross_entity_state_dependency/campaign_activation_gated_by_policy_state
        """
        ta = TEST_USERS["talent_admin_headers"]
        req = create_open_requisition(
            req_number="REQ-SR-1", title="Sr Engineer", level="SENIOR", hard_to_fill=True
        )
        camp = get_success_data(
            api.create_campaign(
                {
                    "name": "gated", "job_requisition_id": req["id"],
                    "multiplier_bps": 15000, "flat_addon_cents": 50000,
                    "window_start": "2026-07-01T00:00:00Z", "window_end": "2026-09-30T00:00:00Z",
                    "budget_cents": 500000,
                },
                ta,
            )
        )
        resp = api.activate_campaign(camp["id"], ta)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_POLICY)

    def test_campaign_activation_succeeds_after_policy_activated(self, api):
        """PRD §3.2: "Activation requires, checked in this order, that some policy version
        is currently `ACTIVE` (otherwise `ERR_NO_ACTIVE_POLICY`) and that the campaign
        window has not already elapsed — `window_end` at or after the logical now".

        Once a policy is ACTIVE the same activation succeeds.

        Design: Difficulty/cross_entity_state_dependency/campaign_activation_gated_by_policy_state
        """
        ta = TEST_USERS["talent_admin_headers"]
        req = create_open_requisition(
            req_number="REQ-SR-1", title="Sr Engineer", level="SENIOR", hard_to_fill=True
        )
        camp = get_success_data(
            api.create_campaign(
                {
                    "name": "gated", "job_requisition_id": req["id"],
                    "multiplier_bps": 15000, "flat_addon_cents": 50000,
                    "window_start": "2026-07-01T00:00:00Z", "window_end": "2026-09-30T00:00:00Z",
                    "budget_cents": 500000,
                },
                ta,
            )
        )
        create_active_policy()
        data = get_success_data(api.activate_campaign(camp["id"], ta))
        assert data["status"] == "ACTIVE"


class TestAnnualCapProvisionalVsCommitted:
    def test_provisional_counts_earned_committed_excludes_it(self, api):
        """PRD §3.5: "The `annual_provisional_cents` accumulator sums the `amount_cents`
        of milestones in `EARNED`, `APPROVED`, `BATCHED`, or `PAID` status, then subtracts
        the `amount_cents` of milestones in `CLAWED_BACK`. The `annual_committed_cents`
        accumulator is the same computation over the narrower lens of `APPROVED`,
        `BATCHED`, and `PAID`, again subtracting `CLAWED_BACK`."

        With the 45000 milestone merely EARNED: provisional 45000, committed 0.

        Design: Difficulty/dual_variant_calc/annual_cap_provisional_vs_committed
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        setup_verified_tax_profile(emp["id"])
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="ca@x.com",
                              candidate_full_name="C A")
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])

        emp_read = get_employee(emp["id"])
        assert emp_read["annual_provisional_cents"] == 45000
        assert emp_read["annual_committed_cents"] == 0

    def test_committed_catches_up_after_approve(self, api):
        """PRD §3.5: "The `annual_committed_cents` accumulator is the same computation
        over the narrower lens of `APPROVED`, `BATCHED`, and `PAID`, again subtracting
        `CLAWED_BACK`." and "both accumulators are recomputed whenever a milestone
        changes status."

        After approve: committed 45000 (provisional unchanged at 45000) — the two
        variants diverged exactly while the milestone sat in EARNED.

        Design: Difficulty/dual_variant_calc/annual_cap_provisional_vs_committed
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        setup_verified_tax_profile(emp["id"])
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="ca@x.com",
                              candidate_full_name="C A")
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])
        ms = get_hire_milestone(ref["id"])

        pp = TEST_USERS["payroll_processor_headers"]
        get_success_data(api.approve_milestone(ms["id"], pp))

        emp_read = get_employee(emp["id"])
        assert emp_read["annual_provisional_cents"] == 45000
        assert emp_read["annual_committed_cents"] == 45000


class TestSourceQualityRawVsAdjusted:
    def test_raw_vs_adjusted_diverge_on_small_sample(self, api):
        """PRD §3.8: "`hire_rate_raw`, the hires divided by the submissions (zero when
        the group has no submissions); `hire_rate_adjusted`, a beta-smoothed rate computed
        as hires plus 5 divided by submissions plus 10, which diverges from the raw rate
        most sharply on small samples; `low_confidence`, true whenever the group's
        submissions number fewer than 10; and `total_bonus_paid_cents`, the sum of `PAID`
        milestone amounts across the group's referrals. Both rates are decimal fractions
        rounded half-up to six decimal places."

        One submission, zero hires: raw 0.0, adjusted (0+5)/(1+10) = 0.454545.

        Design: Difficulty/dual_variant_calc/source_quality_raw_vs_adjusted
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="ca@x.com",
                              candidate_full_name="C A")
        rec_h = make_recruiter_headers(program["rec"]["id"])
        get_success_data(api.review_referral(ref["id"], rec_h))
        get_success_data(api.reject_referral(ref["id"], {"reason_code": "OTHER"}, rec_h))

        ta = TEST_USERS["talent_admin_headers"]
        data = get_success_data(api.get_source_quality(ta, params={"group_by": "REFERRER_LEVEL"}))
        groups = data["groups"]
        assert len(groups) == 1, f"expected exactly one group (IC), got {groups}"
        g = groups[0]
        assert g["submissions"] == 1
        assert g["hires"] == 0
        assert g["hire_rate_raw"] == 0.0
        assert g["hire_rate_adjusted"] == 0.454545, (
            f"(0+5)/(1+10) rounded half-up to 6dp = 0.454545, got {g['hire_rate_adjusted']}"
        )
        assert g["hire_rate_raw"] != g["hire_rate_adjusted"]

    def test_low_confidence_and_zero_bonus_paid(self, api):
        """PRD §3.8: "`low_confidence`, true whenever the group's submissions number
        fewer than 10; and `total_bonus_paid_cents`, the sum of `PAID` milestone amounts
        across the group's referrals." and "`retention_met`, the count currently in
        `COMPLETED`".

        One rejected referral: low_confidence true, retention_met 0, total_bonus_paid 0.

        Design: Difficulty/dual_variant_calc/source_quality_raw_vs_adjusted
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="ca@x.com",
                              candidate_full_name="C A")
        rec_h = make_recruiter_headers(program["rec"]["id"])
        get_success_data(api.review_referral(ref["id"], rec_h))
        get_success_data(api.reject_referral(ref["id"], {"reason_code": "OTHER"}, rec_h))

        ta = TEST_USERS["talent_admin_headers"]
        data = get_success_data(api.get_source_quality(ta, params={"group_by": "REFERRER_LEVEL"}))
        g = data["groups"][0]
        assert g["low_confidence"] is True
        assert g["retention_met"] == 0
        assert g["total_bonus_paid_cents"] == 0
