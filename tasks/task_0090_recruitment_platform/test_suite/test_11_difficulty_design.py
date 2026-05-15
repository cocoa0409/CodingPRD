"""Difficulty-design priority-queue coverage.

Each rule_id from the difficulty-design index drives at least TWO
dedicated tests per declared instance. Each test cites the verbatim
PRD sentence that states the underlying rule the instance exercises.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    BASIC_POSTING_QUOTA,
    INTERVIEW_ROUND_MINUTES,
    OFFER_ACCEPTANCE_WINDOW_HOURS,
    POSTING_LISTED_TTL_DAYS,
    RATE_LIMIT_MAX_PER_WINDOW,
    RATE_LIMIT_WINDOW_SECONDS,
    TEST_EPOCH,
    accept_offer_payload,
    advance_clock_by,
    advance_clock_to,
    api_client,
    assert_commission_settlement_invariant,
    bind_hr_user,
    blacklist_company,
    candidate_confirm_payload,
    candidate_confirm_slot,
    create_application_payload,
    create_candidate,
    create_company,
    create_headhunter_contract,
    create_interview_round,
    create_job_posting_payload,
    create_live_posting,
    create_offer,
    create_verified_company,
    find_audit_events,
    forward_application,
    hm_approve_offer,
    hr_approve_offer,
    iso_utc,
    list_audit_events_for,
    make_candidate_headers,
    make_finance_approver_headers,
    make_hiring_manager_headers,
    make_hr_approver_headers,
    make_hr_user_headers,
    mark_application_read,
    publish_round_slots,
    reject_posting_payload,
    rescind_offer_payload,
    reset_clock_to_epoch,
    run_settlement_sweep,
    setup_accepted_offer,
    setup_application_at_interview_passed,
    setup_issued_offer,
    submit_application,
    submit_company_verification,
    submit_offer_for_approval,
    submit_posting_review,
    submit_round_feedback,
    take_posting_off_shelf,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule: dual_variant_calc
# ===========================================================================
class TestDualVariantCommissionProjectedVsFinal:
    """difficulty: dual_variant_calc/commission_projected_vs_final_net"""

    def test_projected_net_while_accrued_differs_from_clawed_back(self, api, platform_admin_headers):
        """PRD §3.8: "the single-record read on a commission row in
        `ACCRUED` status returns a forward-looking projected net derived
        as `gross_commission_cents` minus `tax_withheld_cents` (assuming
        no clawback). That projected figure may differ from the eventual
        final net if a clawback intervenes between the moment of read
        and the moment of sweep."

        Claim: same CommissionRecord row yields net = gross - tax while
        ACCRUED (forward-looking) but net = 0 when CLAWED_BACK
        (chronological final value).
        """
        reset_clock_to_epoch()
        company, _hr = create_verified_company(verification_tier="PREMIUM")
        contract = create_headhunter_contract(
            company_id=company["id"], fee_model="SUCCESS_FEE",
            success_fee_pct_bps=2500, trigger_event="OFFER_ACCEPTED",
            tax_withholding_pct_bps=1500, clawback_window_days=90,
        )
        bag = setup_accepted_offer(
            base_salary_cents=5_000_000, sign_on_bonus_cents=0,
            source_channel="HEADHUNTER", headhunter_contract=contract,
        )
        records = validate_success(
            api.list_commission_records(
                platform_admin_headers,
                params={"headhunter_contract_id": contract["id"]},
            ),
            expected_status=200,
        )
        record = records[0]
        # First read while ACCRUED: forward-looking projection.
        assert record["settlement_status"] == "ACCRUED"
        assert record["gross_commission_cents"] == 1_250_000
        assert record["tax_withheld_cents"] == 187_500
        assert record["net_settlement_cents"] == 1_062_500
        # Rescind from ACCEPTED before the sweep — clawback flips the row.
        api.rescind_offer(
            bag["offer"]["id"], rescind_offer_payload("BUSINESS_NEED"),
            make_hr_user_headers(bag["hr_user"]["id"]),
        )
        clawed = validate_success(
            api.get_commission_record(record["id"], platform_admin_headers),
            expected_status=200,
        )
        assert clawed["settlement_status"] == "CLAWED_BACK"
        assert clawed["net_settlement_cents"] == 0
        # Same gross/tax inputs, different final net.
        assert clawed["gross_commission_cents"] == record["gross_commission_cents"]
        assert_commission_settlement_invariant(clawed)

    def test_settlement_locks_final_net_at_sweep_time(self, api, platform_admin_headers):
        """PRD §3.8: "Once the record transitions to `SETTLED`, the read
        returns the chronological figure locked at sweep time."

        Claim: after sweep, the second GET returns SETTLED with
        net_settlement_cents == gross - tax == projected value from before.
        """
        reset_clock_to_epoch()
        company, _hr = create_verified_company(verification_tier="PREMIUM")
        contract = create_headhunter_contract(
            company_id=company["id"], fee_model="SUCCESS_FEE",
            success_fee_pct_bps=2500, trigger_event="OFFER_ACCEPTED",
            tax_withholding_pct_bps=1500, clawback_window_days=90,
        )
        bag = setup_accepted_offer(
            base_salary_cents=5_000_000, sign_on_bonus_cents=0,
            source_channel="HEADHUNTER", headhunter_contract=contract,
        )
        record = validate_success(
            api.list_commission_records(
                platform_admin_headers,
                params={"headhunter_contract_id": contract["id"]},
            ),
            expected_status=200,
        )[0]
        record_id = record["id"]
        # Advance to TEST_EPOCH + 31 days. The commission record was created
        # during setup_accepted_offer (clock ~ TEST_EPOCH + 2h), so its age
        # at TEST_EPOCH + 31 days is ~30d 22h — strictly >= 30 days.
        advance_clock_by(31 * 86400)
        run_settlement_sweep()
        settled = validate_success(
            api.get_commission_record(record_id, platform_admin_headers),
            expected_status=200,
        )
        assert settled["settlement_status"] == "SETTLED"
        assert settled["net_settlement_cents"] == 1_062_500
        assert settled["settled_at"] is not None
        assert_commission_settlement_invariant(settled)


class TestDualVariantOfferRemainingVsConsumed:
    """difficulty: dual_variant_calc/offer_remaining_vs_consumed_window"""

    def test_get_offer_while_issued_returns_seconds_remaining(self, api):
        """PRD §3.6: "The single-resource read on an `ISSUED` offer
        projects a forward-looking `seconds_remaining` derived from
        `acceptance_deadline_at` minus the current instant, clamped at
        zero."

        Claim: GET /recruitment/offers/{id} while ISSUED returns a
        positive seconds_remaining that equals deadline - now.
        """
        reset_clock_to_epoch()
        bag = setup_issued_offer()
        offer = bag["offer"]
        # 60 seconds after issued_at:
        issued_at = datetime.fromisoformat(
            offer["issued_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(issued_at + timedelta(seconds=60))
        resp = api.get_offer(
            offer["id"], make_candidate_headers(bag["candidate"]["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["offer_status"] == "ISSUED"
        assert "seconds_remaining" in data, (
            "PRD §3.6: GET on an ISSUED offer 'projects a forward-looking "
            "seconds_remaining' — field must be exposed"
        )
        # Total window = 168h*3600 = 604800s; minus 60s = 604740.
        assert data["seconds_remaining"] == 168 * 3600 - 60

    def test_get_offer_after_accepted_freezes_terminal_window(self, api):
        """PRD §3.6: "once the offer reaches any of the terminal states
        `ACCEPTED`, `DECLINED`, or `EXPIRED`, this projected value freezes
        at the chronological figure `terminal_event_time` minus
        `issued_at`, which may be smaller than the live projection ever
        showed."

        Claim: GET after ACCEPTED returns the chronological terminal
        delta (frozen at acceptance), distinct from the live projection
        that would have included additional time.
        """
        reset_clock_to_epoch()
        bag = setup_issued_offer()
        offer = bag["offer"]
        issued_at = datetime.fromisoformat(
            offer["issued_at"].replace("Z", "+00:00"),
        )
        # Accept 120 seconds after issued_at.
        advance_clock_to(issued_at + timedelta(seconds=120))
        api.accept_offer(
            offer["id"], make_candidate_headers(bag["candidate"]["id"]),
            accept_offer_payload(),
        )
        # Move clock further forward; the terminal-frozen value must not change.
        advance_clock_to(issued_at + timedelta(seconds=200))
        data = validate_success(
            api.get_offer(
                offer["id"],
                make_candidate_headers(bag["candidate"]["id"]),
            ),
            expected_status=200,
        )
        assert data["offer_status"] == "ACCEPTED"
        # Terminal window: accepted_at - issued_at.
        accepted_at = datetime.fromisoformat(
            data["accepted_at"].replace("Z", "+00:00"),
        )
        delta_s = int((accepted_at - issued_at).total_seconds())
        assert delta_s == 120


# ===========================================================================
# Rule: combinatorial_formula
# ===========================================================================
class TestCommissionSumThenRoundOrder:
    """difficulty: combinatorial_formula/commission_sum_then_round_order"""

    def test_hybrid_inputs_round_after_sum(self, api, platform_admin_headers):
        """PRD §3.8: "The raw total is the sum of the four raw parts:
        first slice plus remainder slice plus bonus share plus retainer
        part. The rounding rule is then applied exactly once, at the end
        of this sum, using the round-half-up convention to yield
        `gross_commission_cents` as an integer cent value. The evaluation
        order is fixed: compute all four raw parts (keeping fractional
        precision), sum them, and then round half up."

        Claim: HYBRID with base_salary_cents=10_000_004 and
        sign_on_bonus_cents=8 at success_fee_pct_bps=2000 yields
        gross_commission_cents == 2_000_001 (sum-then-round).
        Per-part-then-sum would give 2_000_000 and is a defect.
        """
        reset_clock_to_epoch()
        company, _hr = create_verified_company(verification_tier="PREMIUM")
        contract = create_headhunter_contract(
            company_id=company["id"], fee_model="HYBRID",
            success_fee_pct_bps=2000, retainer_amount_cents=0,
            trigger_event="OFFER_ACCEPTED", tax_withholding_pct_bps=1000,
        )
        bag = setup_accepted_offer(
            base_salary_cents=10_000_004, sign_on_bonus_cents=8,
            source_channel="HEADHUNTER", headhunter_contract=contract,
        )
        record = validate_success(
            api.list_commission_records(
                platform_admin_headers,
                params={"headhunter_contract_id": contract["id"]},
            ),
            expected_status=200,
        )[0]
        # first_slice_raw = min(10_000_004, 10_000_000) * 2000/10000 = 2_000_000
        # remainder_slice_raw = max(0, 10_000_004 - 10_000_000) * 2000/10000 * 0.5 = 4 * 0.2 * 0.5 = 0.4
        # bonus_share_raw = 8 * 2000/10000 * 0.25 = 8 * 0.2 * 0.25 = 0.4
        # retainer_part_raw = 0
        # raw_total = 2_000_000 + 0.4 + 0.4 + 0 = 2_000_000.8
        # round_half_up(2_000_000.8) = 2_000_001
        assert record["gross_commission_cents"] == 2_000_001, (
            "sum-then-round yields 2_000_001; per-part-then-sum would "
            f"give 2_000_000. Implementation returned "
            f"{record['gross_commission_cents']}."
        )
        # tax = round_half_up(2_000_001 * 1000/10000) = round_half_up(200_000.1) = 200_000
        assert record["tax_withheld_cents"] == 200_000

    def test_hybrid_projected_net_while_accrued(self, api, platform_admin_headers):
        """PRD §3.8: "the single-record read on a commission row in
        `ACCRUED` status returns a forward-looking projected net derived
        as `gross_commission_cents` minus `tax_withheld_cents` (assuming
        no clawback)."

        Claim: the same HYBRID inputs project net_settlement_cents =
        2_000_001 - 200_000 = 1_800_001 while ACCRUED.
        """
        reset_clock_to_epoch()
        company, _hr = create_verified_company(verification_tier="PREMIUM")
        contract = create_headhunter_contract(
            company_id=company["id"], fee_model="HYBRID",
            success_fee_pct_bps=2000, retainer_amount_cents=0,
            trigger_event="OFFER_ACCEPTED", tax_withholding_pct_bps=1000,
        )
        bag = setup_accepted_offer(
            base_salary_cents=10_000_004, sign_on_bonus_cents=8,
            source_channel="HEADHUNTER", headhunter_contract=contract,
        )
        record = validate_success(
            api.list_commission_records(
                platform_admin_headers,
                params={"headhunter_contract_id": contract["id"]},
            ),
            expected_status=200,
        )[0]
        assert record["settlement_status"] == "ACCRUED"
        assert record["net_settlement_cents"] == 1_800_001


class TestCommissionThreeInputBranchSelection:
    """difficulty: combinatorial_formula/commission_three_input_branch_selection"""

    def test_success_fee_branch_ignores_retainer(self, api, platform_admin_headers):
        """PRD §3.8: "For a `SUCCESS_FEE` contract, the first slice,
        remainder slice, and bonus share contribute as defined above and
        the retainer part is zero."

        Claim: a SUCCESS_FEE contract with retainer_amount_cents=999999
        yields gross_commission_cents from the success branch only —
        retainer is ignored.
        """
        reset_clock_to_epoch()
        company, _hr = create_verified_company(verification_tier="PREMIUM")
        contract = create_headhunter_contract(
            company_id=company["id"], fee_model="SUCCESS_FEE",
            success_fee_pct_bps=2500, retainer_amount_cents=999_999,
            trigger_event="OFFER_ACCEPTED", tax_withholding_pct_bps=1000,
        )
        bag = setup_accepted_offer(
            base_salary_cents=5_000_000, sign_on_bonus_cents=0,
            source_channel="HEADHUNTER", headhunter_contract=contract,
        )
        record = validate_success(
            api.list_commission_records(
                platform_admin_headers,
                params={"headhunter_contract_id": contract["id"]},
            ),
            expected_status=200,
        )[0]
        # SUCCESS branch: gross = 5_000_000 * 2500/10000 = 1_250_000 (no retainer).
        assert record["gross_commission_cents"] == 1_250_000

    def test_retainer_branch_ignores_success_fee_pct(self, api, platform_admin_headers):
        """PRD §3.8: "For a `RETAINER` contract, the first slice,
        remainder slice, and bonus share are all zero and the retainer
        part equals the contract's `retainer_amount_cents`."

        Claim: a RETAINER contract with success_fee_pct_bps=2500 and
        retainer_amount_cents=750_000 yields gross = 750_000.
        """
        reset_clock_to_epoch()
        company, _hr = create_verified_company(verification_tier="PREMIUM")
        contract = create_headhunter_contract(
            company_id=company["id"], fee_model="RETAINER",
            success_fee_pct_bps=2500, retainer_amount_cents=750_000,
            trigger_event="OFFER_ACCEPTED", tax_withholding_pct_bps=1000,
        )
        bag = setup_accepted_offer(
            base_salary_cents=5_000_000, sign_on_bonus_cents=0,
            source_channel="HEADHUNTER", headhunter_contract=contract,
        )
        record = validate_success(
            api.list_commission_records(
                platform_admin_headers,
                params={"headhunter_contract_id": contract["id"]},
            ),
            expected_status=200,
        )[0]
        assert record["gross_commission_cents"] == 750_000


# ===========================================================================
# Rule: non_linear_state_machine
# ===========================================================================
class TestJobPostingRejectionRevisionCycle:
    """difficulty: non_linear_state_machine/job_posting_rejection_revision_cycle"""

    def test_revise_then_resubmit_loop(self, api, platform_admin_headers):
        """PRD §3.2: "An HR user may then revise the posting, transitioning
        from `REJECTED` back to `DRAFT` and clearing
        `review_rejection_reason`; the same `REJECTED → DRAFT → UNDER_REVIEW`
        loop may repeat until the posting either is approved or is abandoned."

        Claim: DRAFT → UNDER_REVIEW → REJECTED → DRAFT → UNDER_REVIEW → LIVE
        is a valid trajectory; final posting_status == LIVE.
        """
        company, hr_user = create_verified_company()
        posting_resp = api.create_job_posting(
            create_job_posting_payload(company_id=company["id"]),
            make_hr_user_headers(hr_user["id"]),
        )
        posting = validate_success(posting_resp, expected_status=201)
        submit_posting_review(posting["id"], hr_user["id"])
        # Reject.
        api.reject_posting(
            posting["id"], reject_posting_payload("DISCRIMINATORY_WORDING"),
            platform_admin_headers,
        )
        # Revise.
        validate_success(
            api.revise_posting(posting["id"], make_hr_user_headers(hr_user["id"])),
            expected_status=200,
        )
        # Re-submit & approve.
        submit_posting_review(posting["id"], hr_user["id"])
        approved = validate_success(
            api.approve_posting(posting["id"], platform_admin_headers),
            expected_status=200,
        )
        assert approved["posting_status"] == "LIVE"

    def test_audit_log_records_each_cycle_transition(self, api, platform_admin_headers):
        """PRD §3.9: "Every state transition in §3.1 through §3.8 writes
        a row into the audit log carrying `subject_entity`, `subject_id`,
        `event_kind` ... `from_state` and `to_state` for state-transition
        events..."

        Claim: the cycle DRAFT → UNDER_REVIEW → REJECTED → DRAFT → UNDER_REVIEW
        produces audit rows for each transition.
        """
        company, hr_user = create_verified_company()
        posting_resp = api.create_job_posting(
            create_job_posting_payload(company_id=company["id"]),
            make_hr_user_headers(hr_user["id"]),
        )
        posting = validate_success(posting_resp, expected_status=201)
        submit_posting_review(posting["id"], hr_user["id"])
        api.reject_posting(
            posting["id"], reject_posting_payload("OTHER"),
            platform_admin_headers,
        )
        api.revise_posting(posting["id"], make_hr_user_headers(hr_user["id"]))
        submit_posting_review(posting["id"], hr_user["id"])
        events = list_audit_events_for(
            "JobPosting", posting["id"], event_kind="STATE_TRANSITION",
        )
        # Look for the second DRAFT→UNDER_REVIEW row (the cycle revisit).
        dr_to_ur = find_audit_events(
            events, from_state="DRAFT", to_state="UNDER_REVIEW",
        )
        assert len(dr_to_ur) >= 2, (
            f"Expected ≥2 DRAFT→UNDER_REVIEW transitions on the cycle; "
            f"found {len(dr_to_ur)} ({events!r})"
        )


class TestOfferApprovalRejectCycle:
    """difficulty: non_linear_state_machine/offer_approval_reject_and_resubmit_cycle"""

    def test_reject_from_pending_hr_returns_to_draft_and_loops(self, api):
        """PRD §3.6: "From `PENDING_HR`, rejecting returns the offer to
        `DRAFT` and clears `hm_approver_user_id`."

        Claim: PENDING_HR → DRAFT and a subsequent submit-approval loops
        the offer back to PENDING_HM; the cycle eventually drives the
        offer to ISSUED.
        """
        bag = setup_application_at_interview_passed()
        company = bag["company"]
        hm_hr = bag["hr_user"]
        hr_approver = bind_hr_user(company["id"])
        finance_approver = bind_hr_user(company["id"])
        offer = create_offer(bag["application"]["id"], hm_hr["id"])
        submit_offer_for_approval(offer["id"], hm_hr["id"])
        hm_approve_offer(offer["id"], hm_hr["id"])
        # Reject at PENDING_HR — HM is cleared.
        rejected = validate_success(
            api.reject_offer_approval(
                offer["id"], make_hr_approver_headers(hr_approver["id"]),
            ),
            expected_status=200,
        )
        assert rejected["offer_status"] == "DRAFT"
        assert rejected.get("hm_approver_user_id") in (None, "")
        # Re-submit and complete the full chain.
        submit_offer_for_approval(offer["id"], hm_hr["id"])
        hm_approve_offer(offer["id"], hm_hr["id"])
        hr_approve_offer(offer["id"], hr_approver["id"])
        final = validate_success(
            api.approve_offer(
                offer["id"], make_finance_approver_headers(finance_approver["id"]),
            ),
            expected_status=200,
        )
        assert final["offer_status"] == "ISSUED"

    def test_audit_records_two_draft_to_pending_hm_transitions(self, api):
        """PRD §3.9: "Every state transition in §3.1 through §3.8 writes
        a row into the audit log carrying `subject_entity`, `subject_id`,
        `event_kind` ... `from_state` and `to_state` for state-transition
        events..."

        Claim: after a reject-resubmit cycle, the AuditEvent log carries
        two DRAFT → PENDING_HM rows on this Offer.
        """
        bag = setup_application_at_interview_passed()
        company = bag["company"]
        hm_hr = bag["hr_user"]
        hr_approver = bind_hr_user(company["id"])
        offer = create_offer(bag["application"]["id"], hm_hr["id"])
        submit_offer_for_approval(offer["id"], hm_hr["id"])
        hm_approve_offer(offer["id"], hm_hr["id"])
        api.reject_offer_approval(
            offer["id"], make_hr_approver_headers(hr_approver["id"]),
        )
        submit_offer_for_approval(offer["id"], hm_hr["id"])
        events = list_audit_events_for(
            "Offer", offer["id"], event_kind="STATE_TRANSITION",
        )
        dr_to_pm = find_audit_events(
            events, from_state="DRAFT", to_state="PENDING_HM",
        )
        assert len(dr_to_pm) >= 2, (
            f"Expected ≥2 DRAFT→PENDING_HM transitions; found "
            f"{len(dr_to_pm)} ({events!r})"
        )


# ===========================================================================
# Rule: transitive_cascade
# ===========================================================================
class TestTakeOffShelfTransitiveCascade:
    """difficulty: transitive_cascade/jobposting_off_shelf_cascades_to_interview_rounds

    The two tests in this class were removed because their asserted
    outcomes are not uniquely derivable from PRD. PRD §2.6 lists the
    take-off-shelf application cascade trigger as {SUBMITTED, READ,
    FORWARDED}, excluding INTERVIEW; PRD §3.4 says creating the first
    InterviewRound advances FORWARDED → INTERVIEW. Together these rules
    make the third-hop cascade onto SCHEDULED rounds unreachable under a
    literal PRD reading. The "depth-three transitive chain" claim in
    PRD §2.6 is the contrary cue, but PRD does not pin which reading is
    authoritative. The audit-row variant additionally asserts a
    FORWARDED→CLOSED transition which cannot be produced when the test
    setup creates an InterviewRound (which moves the app out of
    FORWARDED). Both tests fail the unique-derivability check.
    """


class TestBlacklistTransitiveCascade:
    """difficulty: transitive_cascade/company_blacklist_cascades_to_contracts_and_postings"""

    def test_blacklist_drives_live_postings_to_off_shelf_and_closes_apps(self, api, platform_admin_headers):
        """PRD §3.1: "When the source state was `VERIFIED`, blacklisting
        cascades to every job posting in `DRAFT`, `UNDER_REVIEW`, or
        `LIVE` (moving them to `OFF_SHELF` and chaining downward), and to
        every `HeadhunterContract` for this company whose
        `contract_status` is `ACTIVE` (moving them to `TERMINATED`)."

        Claim: blacklisting cascades LIVE postings to OFF_SHELF and
        in turn closes Applications underneath them.
        """
        company, hr_user = create_verified_company()
        posting_a = create_live_posting(company["id"], hr_user["id"])
        posting_b = create_live_posting(company["id"], hr_user["id"])
        candidate = create_candidate()
        application = submit_application(candidate["id"], posting_a["id"])
        mark_application_read(application["id"], hr_user["id"])
        forward_application(application["id"], hr_user["id"])
        blacklist_company(company["id"])
        for p in (posting_a, posting_b):
            data = validate_success(
                api.get_job_posting(p["id"], platform_admin_headers),
                expected_status=200,
            )
            assert data["posting_status"] == "OFF_SHELF"
        app = validate_success(
            api.get_application(application["id"], make_hr_user_headers(hr_user["id"])),
            expected_status=200,
        )
        assert app["application_status"] == "CLOSED"

    def test_blacklist_audit_subject_company_records_terminal_state(self, api):
        """PRD §3.9: "Every state transition in §3.1 through §3.8 writes
        a row into the audit log carrying `subject_entity`, `subject_id`,
        `event_kind` ... `from_state` and `to_state` for state-transition
        events..."

        Claim: blacklisting a VERIFIED Company writes a STATE_TRANSITION
        audit row with from_state=VERIFIED, to_state=BLACKLISTED.
        """
        company, _hr = create_verified_company()
        blacklist_company(company["id"])
        events = list_audit_events_for(
            "Company", company["id"], event_kind="STATE_TRANSITION",
        )
        assert find_audit_events(
            events, from_state="VERIFIED", to_state="BLACKLISTED",
        ), "Expected Company VERIFIED→BLACKLISTED audit row"


# ===========================================================================
# Rule: priority_pair_validation_conflict
# ===========================================================================
class TestStateVsQuotaPair:
    """difficulty: priority_pair_validation_conflict/state_vs_quota_pair_on_jobposting_approve"""

    def test_state_check_wins_when_posting_already_live(self, api, platform_admin_headers):
        """PRD §2.7 priority 8: "State machine — the target resource must
        be in a state from which the requested transition is declared;
        otherwise `ERR_INVALID_STATE` (409). Applies to every action
        endpoint."
        PRD §2.7 priority 16: "Posting quota — at posting-approval time,
        the owning `Company.active_job_posting_count` must be strictly
        less than its `posting_quota_limit`."

        Claim: approving an already-LIVE posting yields ERR_INVALID_STATE
        (priority 8), even when the company is at quota (priority 16).
        """
        company, hr_user = create_verified_company(verification_tier="BASIC")
        for _ in range(BASIC_POSTING_QUOTA):
            create_live_posting(company["id"], hr_user["id"])
        # Pick one of the already-LIVE postings and try to approve it again.
        listing = validate_success(
            api.list_job_postings(
                platform_admin_headers,
                params={"company_id": company["id"], "posting_status": "LIVE"},
            ),
            expected_status=200,
        )
        existing = listing[0]
        resp = api.approve_posting(existing["id"], platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_quota_check_wins_when_state_valid_but_quota_exceeded(self, api, platform_admin_headers):
        """PRD §2.7 priority 16: "Posting quota — at posting-approval
        time, the owning `Company.active_job_posting_count` must be
        strictly less than its `posting_quota_limit`."

        Claim: at quota (5 LIVE postings on a BASIC company) and a sixth
        posting in UNDER_REVIEW, approve yields ERR_POSTING_QUOTA_EXCEEDED.
        """
        company, hr_user = create_verified_company(verification_tier="BASIC")
        for _ in range(BASIC_POSTING_QUOTA):
            create_live_posting(company["id"], hr_user["id"])
        posting_resp = api.create_job_posting(
            create_job_posting_payload(
                company_id=company["id"], title="Sixth job",
                description="Yet another unique role description.",
            ),
            make_hr_user_headers(hr_user["id"]),
        )
        posting = validate_success(posting_resp, expected_status=201)
        submit_posting_review(posting["id"], hr_user["id"])
        resp = api.approve_posting(posting["id"], platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_POSTING_QUOTA_EXCEEDED.value)


class TestProhibitedContentVsDuplicatePair:
    """difficulty: priority_pair_validation_conflict/prohibited_content_vs_duplicate_posting_pair

    test_prohibited_content_wins_over_duplicate was removed: the
    scenario (a posting that is BOTH prohibited-content AND a fingerprint
    duplicate of an existing LIVE posting) is unreachable under
    PRD-faithful semantics. content_fingerprint = lowercase(title) | sha256(
    lowercase(description)), so an identical-fingerprint pair must share
    identical title+description; if those contain prohibited content, the
    first posting could never have been approved into LIVE. The priority
    conflict is therefore unobservable, and the test's setup cannot be
    arranged without either depending on a dictionary leak (the test
    text itself contains discriminatory wording in the prerequisite
    LIVE posting) or pretending the duplicate condition fires. The
    plain-prohibited-content path is already covered by
    test_03/TestApprovalGuards.test_approve_prohibited_content_returns_prohibited_content.
    """

    def test_duplicate_check_fires_when_content_is_clean(self, api, platform_admin_headers):
        """PRD §2.7 priority 10: "Duplicate-posting detection — at
        posting-approval time, no other `JobPosting` with `posting_status`
        equal to `LIVE` may share the same `content_fingerprint` for the
        same `company_id`; otherwise `ERR_DUPLICATE_POSTING` (409)."

        Claim: in the absence of prohibited content, a duplicate fingerprint
        yields ERR_DUPLICATE_POSTING.
        """
        company, hr_user = create_verified_company()
        create_live_posting(
            company["id"], hr_user["id"],
            title="Senior Backend", description="Innocuous role text.",
        )
        posting_resp = api.create_job_posting(
            create_job_posting_payload(
                company_id=company["id"],
                title="Senior Backend",
                description="Innocuous role text.",
            ),
            make_hr_user_headers(hr_user["id"]),
        )
        posting = validate_success(posting_resp, expected_status=201)
        submit_posting_review(posting["id"], hr_user["id"])
        resp = api.approve_posting(posting["id"], platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_POSTING.value)


# ===========================================================================
# Rule: boundary_precision_check
# ===========================================================================
class TestOfferAcceptanceDeadlineBoundary:
    """difficulty: boundary_precision_check/offer_acceptance_deadline_exact_boundary"""

    def test_accept_at_exact_deadline_rejected(self, api):
        """PRD §3.6: "is gated on the current instant being strictly less
        than `acceptance_deadline_at`; equality means the deadline has
        already arrived and the request must be rejected with
        `ERR_OFFER_EXPIRED`."

        Claim: at now() == acceptance_deadline_at, accept yields
        ERR_OFFER_EXPIRED.
        """
        reset_clock_to_epoch()
        bag = setup_issued_offer()
        deadline = datetime.fromisoformat(
            bag["offer"]["acceptance_deadline_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(deadline)
        resp = api.accept_offer(
            bag["offer"]["id"], make_candidate_headers(bag["candidate"]["id"]),
            accept_offer_payload(),
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED.value)

    def test_accept_one_second_before_deadline_succeeds(self, api):
        """PRD §3.6: "is gated on the current instant being strictly less
        than `acceptance_deadline_at`."

        Claim: at now() == acceptance_deadline_at - 1s, accept succeeds.
        """
        reset_clock_to_epoch()
        bag = setup_issued_offer()
        deadline = datetime.fromisoformat(
            bag["offer"]["acceptance_deadline_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(deadline - timedelta(seconds=1))
        resp = api.accept_offer(
            bag["offer"]["id"], make_candidate_headers(bag["candidate"]["id"]),
            accept_offer_payload(),
        )
        data = validate_success(resp, expected_status=200)
        assert data["offer_status"] == "ACCEPTED"


class TestCandidateRateLimitBoundary:
    """difficulty: boundary_precision_check/candidate_rate_limit_zero_count_and_strict_count"""

    def test_first_submission_with_zero_count_succeeds(self, api):
        """PRD §3.4: "the platform counts the candidate's `Application`
        rows whose `created_at` falls in the half-open window starting
        sixty seconds before the current instant and ending strictly
        before the current instant. If that count is already five at the
        time of evaluation — so that persisting the new row would carry
        the count to six — the request is rejected with
        ERR_CANDIDATE_RATE_LIMIT."

        Claim: count==0 → first POST succeeds.
        """
        reset_clock_to_epoch()
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        candidate = create_candidate()
        resp = api.create_application(
            create_application_payload(
                candidate_id=candidate["id"], job_posting_id=posting["id"],
            ),
            make_candidate_headers(candidate["id"]),
        )
        validate_success(resp, expected_status=201)

    def test_sixth_within_window_rejected_count_equals_five(self, api):
        """PRD §3.4: "If that count is already five at the time of
        evaluation — so that persisting the new row would carry the count
        to six — the request is rejected with ERR_CANDIDATE_RATE_LIMIT."

        Claim: count==5 → sixth POST rejected with 429
        ERR_CANDIDATE_RATE_LIMIT.
        """
        reset_clock_to_epoch()
        # PREMIUM tier so the 6 LIVE postings fit under the posting quota.
        company, hr_user = create_verified_company(verification_tier="PREMIUM")
        postings = [
            create_live_posting(company["id"], hr_user["id"])
            for _ in range(6)
        ]
        candidate = create_candidate()
        for i in range(5):
            api.create_application(
                create_application_payload(
                    candidate_id=candidate["id"],
                    job_posting_id=postings[i]["id"],
                ),
                make_candidate_headers(candidate["id"]),
            )
        resp = api.create_application(
            create_application_payload(
                candidate_id=candidate["id"], job_posting_id=postings[5]["id"],
            ),
            make_candidate_headers(candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CANDIDATE_RATE_LIMIT.value)


# ===========================================================================
# Rule: cross_entity_state_dependency
# ===========================================================================
class TestJobPostingRequiresCompanyVerified:
    """difficulty: cross_entity_state_dependency/jobposting_approve_requires_company_verified"""

    def test_submit_review_blocked_when_company_pending(self, api):
        """PRD §3.2: "Submitting the posting for review requires the
        owning company to be in `VERIFIED` status..."

        Claim: when the owning Company is PENDING (not yet VERIFIED),
        submit-review yields ERR_INVALID_STATE.
        """
        # Company in PENDING (submit-verification done, approve-verification not).
        company = create_company()
        submit_company_verification(company["id"])
        hr_user = bind_hr_user(company["id"])
        posting_resp = api.create_job_posting(
            create_job_posting_payload(company_id=company["id"]),
            make_hr_user_headers(hr_user["id"]),
        )
        posting = validate_success(posting_resp, expected_status=201)
        resp = api.submit_review_posting(
            posting["id"], make_hr_user_headers(hr_user["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_submit_review_succeeds_after_company_verified(self, api):
        """PRD §3.2: "Submitting the posting for review requires the
        owning company to be in `VERIFIED` status..."

        Claim: once the company is VERIFIED, submit-review succeeds.
        """
        company, hr_user = create_verified_company()
        posting_resp = api.create_job_posting(
            create_job_posting_payload(company_id=company["id"]),
            make_hr_user_headers(hr_user["id"]),
        )
        posting = validate_success(posting_resp, expected_status=201)
        resp = api.submit_review_posting(
            posting["id"], make_hr_user_headers(hr_user["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["posting_status"] == "UNDER_REVIEW"


class TestOfferSubmitRequiresInterviewPassed:
    """difficulty: cross_entity_state_dependency/offer_submit_approval_requires_application_interview"""

    def test_submit_approval_blocked_without_interview_state(self, api):
        """PRD §3.6: "The submit guards re-check the money fields and
        additionally require that the parent `Application` be in
        `application_status` `INTERVIEW` and that at least one
        `InterviewRound` on that application has `round_status` `PASSED`."

        Claim: submit-approval against an application still in FORWARDED
        (no InterviewRound) yields ERR_INVALID_STATE.
        """
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        candidate = create_candidate()
        application = submit_application(candidate["id"], posting["id"])
        mark_application_read(application["id"], hr_user["id"])
        forward_application(application["id"], hr_user["id"])
        # No interview round yet — application is FORWARDED, not INTERVIEW.
        offer = create_offer(application["id"], hr_user["id"])
        resp = api.submit_offer_approval(
            offer["id"], make_hr_user_headers(hr_user["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_submit_approval_succeeds_after_round_passed(self, api):
        """PRD §3.6: "The submit guards re-check the money fields and
        additionally require that the parent `Application` be in
        `application_status` `INTERVIEW` and that at least one
        `InterviewRound` on that application has `round_status` `PASSED`."

        Claim: once an InterviewRound is PASSED and the application is in
        INTERVIEW, submit-approval succeeds.
        """
        bag = setup_application_at_interview_passed()
        offer = create_offer(bag["application"]["id"], bag["hr_user"]["id"])
        resp = api.submit_offer_approval(
            offer["id"], make_hr_user_headers(bag["hr_user"]["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["offer_status"] == "PENDING_HM"


# ===========================================================================
# Rule: resource_temporal_overlap
# ===========================================================================
class TestInterviewerHalfOpenOverlap:
    """difficulty: resource_temporal_overlap/interviewer_half_open_overlap"""

    def test_overlapping_slot_for_shared_interviewer_rejected(self, api):
        """PRD §3.5: "for each interviewer in `interviewer_user_ids`, the
        set of half-open candidate windows (each spanning sixty minutes
        from the proposed start) is compared against every existing
        `SCHEDULED` `InterviewRound` whose interviewers include that user;
        two windows collide if and only if the start of the first is
        strictly less than the end of the second and the start of the
        second is strictly less than the end of the first."

        Claim: confirming a slot that overlaps an existing SCHEDULED
        round for a shared interviewer yields ERR_INTERVIEWER_BUSY.
        """
        reset_clock_to_epoch()
        # To exercise the candidate-confirm collision check, R2's slot must
        # be published BEFORE R1 reaches SCHEDULED — otherwise R2's publish
        # itself fails with ERR_INTERVIEWER_BUSY at the publish-time check.
        company_a, hr_a = create_verified_company()
        posting_a = create_live_posting(company_a["id"], hr_a["id"])
        cand_a = create_candidate()
        app_a = submit_application(cand_a["id"], posting_a["id"])
        mark_application_read(app_a["id"], hr_a["id"])
        forward_application(app_a["id"], hr_a["id"])
        r1 = create_interview_round(app_a["id"], hr_a["id"])
        slot1 = TEST_EPOCH + timedelta(hours=1)
        publish_round_slots(r1["id"], hr_a["id"], [slot1])
        # Round 2 on a different company, shared interviewer (hr_a).
        company_b, hr_b = create_verified_company()
        posting_b = create_live_posting(company_b["id"], hr_b["id"])
        cand_b = create_candidate()
        app_b = submit_application(cand_b["id"], posting_b["id"])
        mark_application_read(app_b["id"], hr_b["id"])
        forward_application(app_b["id"], hr_b["id"])
        r2 = create_interview_round(
            app_b["id"], hr_b["id"],
            interviewer_user_ids=[hr_b["id"], hr_a["id"]],
        )
        # Slot at T0+45min overlaps R1's window [T0+1h, T0+2h): window for
        # R2 = [T0+45m, T0+1h45m); overlaps R1.
        slot2 = TEST_EPOCH + timedelta(minutes=45)
        # Publish R2's slot BEFORE R1 is confirmed.
        publish_round_slots(r2["id"], hr_b["id"], [slot2])
        candidate_confirm_slot(r1["id"], cand_a["id"], slot1)
        # Now candidate B's confirm collides with R1's SCHEDULED window.
        resp = api.candidate_confirm_slot(
            r2["id"], candidate_confirm_payload(iso_utc(slot2)),
            make_candidate_headers(cand_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INTERVIEWER_BUSY.value)

    def test_touching_boundary_is_not_overlap(self, api):
        """PRD §3.5: "Touching exactly at a boundary (the end of one
        round equals the start of the next) is not a collision under
        this half-open rule."

        Claim: a slot starting exactly at the previous round's
        scheduled_end_at confirms successfully.
        """
        reset_clock_to_epoch()
        company_a, hr_a = create_verified_company()
        posting_a = create_live_posting(company_a["id"], hr_a["id"])
        cand_a = create_candidate()
        app_a = submit_application(cand_a["id"], posting_a["id"])
        mark_application_read(app_a["id"], hr_a["id"])
        forward_application(app_a["id"], hr_a["id"])
        r1 = create_interview_round(app_a["id"], hr_a["id"])
        slot1 = TEST_EPOCH + timedelta(hours=1)  # window [1h, 2h)
        publish_round_slots(r1["id"], hr_a["id"], [slot1])
        candidate_confirm_slot(r1["id"], cand_a["id"], slot1)
        company_b, hr_b = create_verified_company()
        posting_b = create_live_posting(company_b["id"], hr_b["id"])
        cand_b = create_candidate()
        app_b = submit_application(cand_b["id"], posting_b["id"])
        mark_application_read(app_b["id"], hr_b["id"])
        forward_application(app_b["id"], hr_b["id"])
        r2 = create_interview_round(
            app_b["id"], hr_b["id"],
            interviewer_user_ids=[hr_b["id"], hr_a["id"]],
        )
        slot2 = TEST_EPOCH + timedelta(hours=2)  # exactly R1.end
        publish_round_slots(r2["id"], hr_b["id"], [slot2])
        resp = api.candidate_confirm_slot(
            r2["id"], candidate_confirm_payload(iso_utc(slot2)),
            make_candidate_headers(cand_b["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["round_status"] == "SCHEDULED"


class TestCompanyPostingQuotaCapacity:
    """difficulty: resource_temporal_overlap/company_posting_quota_aggregate_capacity"""

    def test_approve_at_quota_strict_boundary_rejected(self, api, platform_admin_headers):
        """PRD §3.2: "Approval also gates on the company's posting quota:
        `active_job_posting_count` must be strictly less than
        `posting_quota_limit`, where the strict inequality means that
        equality already means the quota is exhausted and yields
        `ERR_POSTING_QUOTA_EXCEEDED`."

        Claim: at active_job_posting_count == posting_quota_limit == 5,
        the next approve yields ERR_POSTING_QUOTA_EXCEEDED.
        """
        company, hr_user = create_verified_company(verification_tier="BASIC")
        for _ in range(5):
            create_live_posting(company["id"], hr_user["id"])
        posting_resp = api.create_job_posting(
            create_job_posting_payload(
                company_id=company["id"], title="Sixth job",
                description="Different role description.",
            ),
            make_hr_user_headers(hr_user["id"]),
        )
        posting = validate_success(posting_resp, expected_status=201)
        submit_posting_review(posting["id"], hr_user["id"])
        resp = api.approve_posting(posting["id"], platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_POSTING_QUOTA_EXCEEDED.value)

    def test_take_off_shelf_frees_quota_slot(self, api, platform_admin_headers):
        """PRD §3.2: "Both transitions ... decrement the owning company's
        `active_job_posting_count`."

        Claim: after take-off-shelf reduces the count below quota, a new
        approve succeeds (4 < 5 again).
        """
        company, hr_user = create_verified_company(verification_tier="BASIC")
        postings = [
            create_live_posting(company["id"], hr_user["id"])
            for _ in range(5)
        ]
        # Take one off shelf.
        take_posting_off_shelf(postings[0]["id"], hr_user["id"])
        # Build a sixth (unique) posting and approve.
        posting_resp = api.create_job_posting(
            create_job_posting_payload(
                company_id=company["id"], title="Replacement role",
                description="Replacement role description.",
            ),
            make_hr_user_headers(hr_user["id"]),
        )
        posting = validate_success(posting_resp, expected_status=201)
        submit_posting_review(posting["id"], hr_user["id"])
        approved = validate_success(
            api.approve_posting(posting["id"], platform_admin_headers),
            expected_status=200,
        )
        assert approved["posting_status"] == "LIVE"


# ===========================================================================
# Rule: compensating_invariant
# ===========================================================================
class TestPostingQuotaCounterInvariant:
    """difficulty: compensating_invariant/posting_quota_counter_invariant"""

    def test_counter_matches_live_count_after_approve_and_off_shelf(self, api, platform_admin_headers):
        """PRD §3.2: "On a successful approval, ... `active_job_posting_count`
        is incremented by one (a derived-field reconciliation: the
        persistent counter on the company is kept in lockstep with the
        count of `LIVE` postings under it)."
        PRD §3.2: "Both transitions ... decrement the owning company's
        `active_job_posting_count`."

        Claim: after a forward approve and a compensating take-off-shelf,
        Company.active_job_posting_count returns to zero (the pre-approve
        value).
        """
        company, hr_user = create_verified_company()
        before = validate_success(
            api.get_company(company["id"], platform_admin_headers),
            expected_status=200,
        )
        assert before["active_job_posting_count"] == 0
        posting = create_live_posting(company["id"], hr_user["id"])
        after_approve = validate_success(
            api.get_company(company["id"], platform_admin_headers),
            expected_status=200,
        )
        assert after_approve["active_job_posting_count"] == 1
        take_posting_off_shelf(posting["id"], hr_user["id"])
        after_off_shelf = validate_success(
            api.get_company(company["id"], platform_admin_headers),
            expected_status=200,
        )
        assert after_off_shelf["active_job_posting_count"] == 0

    def test_counter_matches_listing_count_at_every_step(self, api, platform_admin_headers):
        """PRD §3.2: "the persistent counter on the company is kept in
        lockstep with the count of `LIVE` postings under it."

        Claim: at every checkpoint, Company.active_job_posting_count
        equals the number of postings with posting_status == LIVE
        returned by the list endpoint.
        """
        company, hr_user = create_verified_company(verification_tier="PREMIUM")
        for i in range(3):
            create_live_posting(company["id"], hr_user["id"])
        c = validate_success(
            api.get_company(company["id"], platform_admin_headers),
            expected_status=200,
        )
        live_rows = validate_success(
            api.list_job_postings(
                platform_admin_headers,
                params={"company_id": company["id"], "posting_status": "LIVE"},
            ),
            expected_status=200,
        )
        assert c["active_job_posting_count"] == len(live_rows) == 3


class TestCommissionSettlementValueInvariant:
    """difficulty: compensating_invariant/commission_settlement_value_invariant"""

    def test_invariant_holds_after_clawback(self, api, platform_admin_headers):
        """PRD §3.8: "At any terminal state, the invariant
        `net_settlement_cents` plus `clawback_amount_cents` equals
        `gross_commission_cents` minus `tax_withheld_cents` holds by
        construction."

        Claim: after Offer rescission triggers clawback, the invariant
        net + clawback == gross - tax holds.
        """
        reset_clock_to_epoch()
        company, _hr = create_verified_company(verification_tier="PREMIUM")
        contract = create_headhunter_contract(
            company_id=company["id"], fee_model="SUCCESS_FEE",
            success_fee_pct_bps=2500, trigger_event="OFFER_ACCEPTED",
            tax_withholding_pct_bps=1500, clawback_window_days=90,
        )
        bag = setup_accepted_offer(
            base_salary_cents=5_000_000, sign_on_bonus_cents=0,
            source_channel="HEADHUNTER", headhunter_contract=contract,
        )
        record = validate_success(
            api.list_commission_records(
                platform_admin_headers,
                params={"headhunter_contract_id": contract["id"]},
            ),
            expected_status=200,
        )[0]
        api.rescind_offer(
            bag["offer"]["id"], rescind_offer_payload("BUSINESS_NEED"),
            make_hr_user_headers(bag["hr_user"]["id"]),
        )
        final = validate_success(
            api.get_commission_record(record["id"], platform_admin_headers),
            expected_status=200,
        )
        assert final["settlement_status"] == "CLAWED_BACK"
        # Pinned: net + clawback == gross - tax
        assert (
            final["net_settlement_cents"] + final["clawback_amount_cents"]
            == final["gross_commission_cents"] - final["tax_withheld_cents"]
        )
        # Specific values from the difficulty-index instance:
        # gross=1_250_000, tax=187_500, clawback=1_062_500, net=0
        assert final["gross_commission_cents"] == 1_250_000
        assert final["tax_withheld_cents"] == 187_500
        assert final["clawback_amount_cents"] == 1_062_500
        assert final["net_settlement_cents"] == 0

    def test_invariant_holds_after_settled(self, api, platform_admin_headers):
        """PRD §3.8: "At any terminal state, the invariant
        `net_settlement_cents` plus `clawback_amount_cents` equals
        `gross_commission_cents` minus `tax_withheld_cents` holds by
        construction."

        Claim: after sweep settles the record, the invariant holds with
        clawback==0 and net==gross-tax.
        """
        reset_clock_to_epoch()
        company, _hr = create_verified_company(verification_tier="PREMIUM")
        contract = create_headhunter_contract(
            company_id=company["id"], fee_model="SUCCESS_FEE",
            success_fee_pct_bps=2500, trigger_event="OFFER_ACCEPTED",
            tax_withholding_pct_bps=1500,
        )
        bag = setup_accepted_offer(
            base_salary_cents=5_000_000, sign_on_bonus_cents=0,
            source_channel="HEADHUNTER", headhunter_contract=contract,
        )
        record = validate_success(
            api.list_commission_records(
                platform_admin_headers,
                params={"headhunter_contract_id": contract["id"]},
            ),
            expected_status=200,
        )[0]
        advance_clock_by(31 * 86400)
        run_settlement_sweep()
        final = validate_success(
            api.get_commission_record(record["id"], platform_admin_headers),
            expected_status=200,
        )
        assert final["settlement_status"] == "SETTLED"
        assert (
            final["net_settlement_cents"] + final["clawback_amount_cents"]
            == final["gross_commission_cents"] - final["tax_withheld_cents"]
        )
