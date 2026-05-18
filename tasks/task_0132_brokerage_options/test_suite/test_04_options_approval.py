"""Options-approval workflow + eligibility-cap calculation.

Coverage targets (PRD §3.2):
- Submission initial state: SUBMITTED, revision_count=0.
- One-approval-at-a-time per account constraint
  -> ERR_OPTIONS_APPROVAL_IN_PROGRESS.
- start-review: SUBMITTED -> UNDER_REVIEW.
- decide APPROVE: cascades Account.options_level := max(current, level).
- decide APPROVE: approved_level above eligibility cap
  -> ERR_OPTIONS_LEVEL_EXCEEDS_ELIGIBILITY.
- decide REQUEST_REVISION: cycles back via revision_count++.
- decide REQUEST_REVISION: revision_count == 3 -> ERR_REVISION_LIMIT_REACHED.
- decide REJECT: terminal REJECTED.
- decide on wrong state -> ERR_INVALID_STATE.
- Eligibility-tier boundary checks (LNW thresholds at exact boundary).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    LEVEL_1_LNW_CENTS,
    LEVEL_2_LNW_CENTS,
    LEVEL_3_LNW_CENTS,
    LEVEL_3_TNW_CENTS,
    LEVEL_4_LNW_CENTS,
    LEVEL_4_TNW_CENTS,
    REVISION_LIMIT,
    TEST_USERS,
    assert_options_approval,
    create_options_approval,
    create_options_approval_payload,
    decide_options_approval,
    decide_options_approval_payload,
    make_customer_headers,
    patch_options_approval_payload,
    setup_funded_account,
    setup_options_approval_under_review,
    start_options_review,
    validate_error,
    validate_success,
)


# ===========================================================================
# Submission shape — PRD §3.2
# ===========================================================================
class TestOptionsApprovalSubmission:
    """PRD §3.2: 'The new approval row is created with status set to
    SUBMITTED, approved_level null until decided, review_notes null,
    and revision_count set to 0.'"""

    def test_submission_initial_state(self, api):
        """PRD §3.2: "The new approval row is created with status set
        to SUBMITTED, approved_level null until decided, review_notes
        null, and revision_count set to 0."

        Claim: a newly-created OptionsApproval has the documented
        initial state.
        """
        customer, account = setup_funded_account(
            account_type="CASH", cash_amount_cents=0,
        )
        # cash_amount_cents=0 keeps account empty but APPROVED.
        approval = create_options_approval(
            customer, account, requested_level=1,
        )
        assert_options_approval(approval)
        assert approval["status"] == "SUBMITTED"
        assert approval["approved_level"] is None
        assert approval["review_notes"] is None
        assert approval["revision_count"] == 0
        assert approval["version"] == 1


# ===========================================================================
# Only one non-terminal approval per account — PRD §3.2
# ===========================================================================
class TestSingleApprovalConstraint:
    """PRD §3.2: 'At most one OptionsApproval for a given account may
    sit in the non-terminal set (SUBMITTED, UNDER_REVIEW,
    REVISION_REQUESTED) at any time; a second submission while one is
    already pending is rejected with ERR_OPTIONS_APPROVAL_IN_PROGRESS.'"""

    def test_second_submission_blocked(self, api):
        """PRD §3.2: "At most one OptionsApproval for a given account
        may sit in the non-terminal set (SUBMITTED, UNDER_REVIEW,
        REVISION_REQUESTED) at any time; a second submission while one
        is already pending is rejected with
        ERR_OPTIONS_APPROVAL_IN_PROGRESS."

        Claim: second POST /brokerage/options-approvals while the
        first is still in SUBMITTED -> ERR_OPTIONS_APPROVAL_IN_PROGRESS.
        """
        customer, account = setup_funded_account(
            account_type="CASH", cash_amount_cents=0,
        )
        create_options_approval(customer, account, requested_level=1)
        # Now submit a second one — should fail.
        resp = api.create_options_approval(
            create_options_approval_payload(
                account_id=account["id"], requested_level=2,
            ),
            make_customer_headers(customer["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_OPTIONS_APPROVAL_IN_PROGRESS.value,
        )


# ===========================================================================
# start-review transition — PRD §3.2
# ===========================================================================
class TestStartReview:
    """PRD §3.2: 'A compliance officer picks up the submission via a
    start-review action that advances OptionsApproval.status from
    SUBMITTED to UNDER_REVIEW.'"""

    def test_start_review_transitions_to_under_review(self, api):
        """PRD §3.2: "A compliance officer picks up the submission via
        a start-review action that advances OptionsApproval.status
        from SUBMITTED to UNDER_REVIEW."

        Claim: SUBMITTED -> UNDER_REVIEW.
        """
        customer, account = setup_funded_account(
            account_type="CASH", cash_amount_cents=0,
        )
        approval = create_options_approval(
            customer, account, requested_level=1,
        )
        assert approval["status"] == "SUBMITTED"
        v0 = approval["version"]
        ur = start_options_review(approval["id"])
        assert ur["status"] == "UNDER_REVIEW"
        assert ur["version"] == v0 + 1

    def test_start_review_from_wrong_state_rejected(self, api):
        """PRD §2.9: "Source-state checks for the relevant entity
        follow (yielding ERR_INVALID_STATE when a transition source is
        wrong)."

        Claim: start-review on an approval already in UNDER_REVIEW ->
        ERR_INVALID_STATE.
        """
        customer, account = setup_funded_account(
            account_type="CASH", cash_amount_cents=0,
        )
        approval = create_options_approval(
            customer, account, requested_level=1,
        )
        start_options_review(approval["id"])
        # Second start-review should fail.
        resp = api.start_options_review(
            approval["id"], TEST_USERS["compliance_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# decide APPROVE — PRD §3.2
# ===========================================================================
class TestDecideApprove:
    """PRD §3.2: 'Approval requires an approved_level in the body and is
    gated by the system's options-eligibility calculation ... on success
    it sets OptionsApproval.approved_level to the chosen value and
    bumps Account.options_level to the maximum of its current value and
    the newly-granted level (so a later, lower approval never demotes
    an existing higher grant).'"""

    def test_approve_sets_approved_level_and_account_level(self, api):
        """PRD §3.2: "on success it sets OptionsApproval.approved_level
        to the chosen value and bumps Account.options_level to the
        maximum of its current value and the newly-granted level".

        Claim: APPROVE decision writes approved_level and bumps
        Account.options_level to max(current, approved_level).
        """
        customer, account = setup_funded_account(
            account_type="CASH", cash_amount_cents=0,
            years_options_experience=10,
            liquid_net_worth_cents=50_000_000_00,
            total_net_worth_cents=100_000_000_00,
        )
        assert account["options_level"] == 0
        oa = create_options_approval(
            customer, account, requested_level=2,
        )
        start_options_review(oa["id"])
        approved = decide_options_approval(
            oa["id"], decision="APPROVE", approved_level=2,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_level"] == 2
        # Account.options_level is bumped to max(current, approved_level).
        fresh = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        assert fresh["options_level"] == 2

    def test_approve_above_eligibility_rejected(self, api):
        """PRD §3.2: "On approval, the compliance officer's chosen
        approved_level must be at least 1 and must not exceed this
        calculated maximum; a value above the cap is rejected with
        ERR_OPTIONS_LEVEL_EXCEEDS_ELIGIBILITY at HTTP 422."

        Claim: APPROVE with approved_level > options_eligibility_max
        -> ERR_OPTIONS_LEVEL_EXCEEDS_ELIGIBILITY / 422.

        Setup pins a customer eligible for at most level 1
        (yrs=0, lnw=1_000_000, tnw=1_000_000) and asks for level 2.
        """
        # Customer eligible up to level 1 only.
        customer, account = setup_funded_account(
            account_type="CASH", cash_amount_cents=0,
            years_options_experience=0,
            liquid_net_worth_cents=LEVEL_1_LNW_CENTS,
            total_net_worth_cents=LEVEL_1_LNW_CENTS,
        )
        oa = create_options_approval(
            customer, account, requested_level=2,
        )
        start_options_review(oa["id"])
        resp = api.decide_options_approval(
            oa["id"],
            decide_options_approval_payload(
                decision="APPROVE", approved_level=2,
            ),
            TEST_USERS["compliance_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_OPTIONS_LEVEL_EXCEEDS_ELIGIBILITY.value,
        )


# ===========================================================================
# Eligibility-tier boundary on LNW for level 1 — PRD §3.2
# ===========================================================================
class TestEligibilityLnwBoundary:
    """PRD §3.2 boundary at LNW=$10,000 for level 1."""

    def test_lnw_one_below_threshold_fails_level_1(self, api):
        """PRD §3.2: "Level 1 (covered calls and cash-secured puts)
        requires years at least 0 and liquid_net_worth_cents at least
        1,000,000 — that is, at least ten thousand dollars of liquid
        net worth."

        Claim: lnw = 999_999 (1 below the level-1 threshold) ->
        eligibility cap is 0; APPROVE level=1 ->
        ERR_OPTIONS_LEVEL_EXCEEDS_ELIGIBILITY.
        """
        customer, account = setup_funded_account(
            account_type="CASH", cash_amount_cents=0,
            years_options_experience=0,
            liquid_net_worth_cents=LEVEL_1_LNW_CENTS - 1,
            total_net_worth_cents=LEVEL_1_LNW_CENTS - 1,
        )
        oa = create_options_approval(
            customer, account, requested_level=1,
        )
        start_options_review(oa["id"])
        resp = api.decide_options_approval(
            oa["id"],
            decide_options_approval_payload(
                decision="APPROVE", approved_level=1,
            ),
            TEST_USERS["compliance_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_OPTIONS_LEVEL_EXCEEDS_ELIGIBILITY.value,
        )

    def test_lnw_exactly_at_threshold_passes_level_1(self, api):
        """PRD §3.2: "Level 1 (covered calls and cash-secured puts)
        requires years at least 0 and liquid_net_worth_cents at least
        1,000,000".

        Claim: lnw = 1_000_000 (exactly at threshold) -> eligibility
        cap is 1; APPROVE level=1 succeeds.
        """
        customer, account = setup_funded_account(
            account_type="CASH", cash_amount_cents=0,
            years_options_experience=0,
            liquid_net_worth_cents=LEVEL_1_LNW_CENTS,
            total_net_worth_cents=LEVEL_1_LNW_CENTS,
        )
        oa = create_options_approval(
            customer, account, requested_level=1,
        )
        start_options_review(oa["id"])
        resp = api.decide_options_approval(
            oa["id"],
            decide_options_approval_payload(
                decision="APPROVE", approved_level=1,
            ),
            TEST_USERS["compliance_headers"],
        )
        approved = validate_success(resp)
        assert approved["status"] == "APPROVED"
        assert approved["approved_level"] == 1


# ===========================================================================
# Eligibility level-3 TNW boundary — PRD §3.2
# ===========================================================================
class TestEligibilityLevel3TnwBoundary:
    """PRD §3.2 level-3 requires both lnw>=10M AND tnw>=25M."""

    def test_level3_with_tnw_below_threshold_caps_at_level2(self, api):
        """PRD §3.2: "Level 3 (spreads) additionally requires years at
        least 2 with liquid_net_worth_cents at least 10,000,000 and
        total_net_worth_cents at least 25,000,000".

        Claim: yrs=2, lnw=10_000_000, tnw=24_999_999 -> eligibility
        cap is 2 (level 3 fails); APPROVE level=3 ->
        ERR_OPTIONS_LEVEL_EXCEEDS_ELIGIBILITY.
        """
        customer, account = setup_funded_account(
            account_type="CASH", cash_amount_cents=0,
            years_options_experience=2,
            liquid_net_worth_cents=LEVEL_3_LNW_CENTS,
            total_net_worth_cents=LEVEL_3_TNW_CENTS - 1,
        )
        oa = create_options_approval(
            customer, account, requested_level=3,
        )
        start_options_review(oa["id"])
        resp = api.decide_options_approval(
            oa["id"],
            decide_options_approval_payload(
                decision="APPROVE", approved_level=3,
            ),
            TEST_USERS["compliance_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_OPTIONS_LEVEL_EXCEEDS_ELIGIBILITY.value,
        )


# ===========================================================================
# REQUEST_REVISION cycle — PRD §3.2
# ===========================================================================
class TestRequestRevisionCycle:
    """PRD §3.2 revision loop."""

    def test_request_revision_records_notes_and_state(self, api):
        """PRD §3.2: "Requesting a revision requires non-empty notes
        and is permitted only while revision_count is strictly less
        than 3 ... On success, the request-revision action writes the
        supplied notes into OptionsApproval.review_notes and
        transitions the row to REVISION_REQUESTED."

        Claim: REQUEST_REVISION (notes='...') from UNDER_REVIEW
        transitions to REVISION_REQUESTED and writes notes.
        """
        customer, account = setup_funded_account(
            account_type="CASH", cash_amount_cents=0,
            years_options_experience=10,
            liquid_net_worth_cents=50_000_000_00,
            total_net_worth_cents=100_000_000_00,
        )
        oa = create_options_approval(
            customer, account, requested_level=2,
        )
        start_options_review(oa["id"])
        resp = api.decide_options_approval(
            oa["id"],
            decide_options_approval_payload(
                decision="REQUEST_REVISION",
                notes="Please supply additional broker statements",
            ),
            TEST_USERS["compliance_headers"],
        )
        revised = validate_success(resp)
        assert revised["status"] == "REVISION_REQUESTED"
        assert revised["review_notes"]

    def test_patch_resubmit_increments_revision_count(self, api):
        """PRD §3.2: "From REVISION_REQUESTED the customer resubmits
        supporting data through a customer-driven patch action, which
        carries an optional requested_level and the resource's
        version, transitions the row back to SUBMITTED, and increments
        revision_count by exactly 1."

        Claim: PATCH /brokerage/options-approvals/{id} from
        REVISION_REQUESTED -> status:=SUBMITTED, revision_count++.
        """
        customer, account = setup_funded_account(
            account_type="CASH", cash_amount_cents=0,
            years_options_experience=10,
            liquid_net_worth_cents=50_000_000_00,
            total_net_worth_cents=100_000_000_00,
        )
        oa = create_options_approval(
            customer, account, requested_level=2,
        )
        start_options_review(oa["id"])
        revised = decide_options_approval(
            oa["id"], decision="REQUEST_REVISION", notes="please update",
        )
        assert revised["revision_count"] == 0
        # Customer patches resubmit.
        resp = api.patch_options_approval(
            oa["id"],
            patch_options_approval_payload(version=revised["version"]),
            make_customer_headers(customer["id"]),
        )
        resubmitted = validate_success(resp)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_count"] == 1


# ===========================================================================
# decide REJECT — PRD §3.2
# ===========================================================================
class TestDecideReject:
    """PRD §3.2: 'Rejection from UNDER_REVIEW likewise requires
    non-empty notes, lands the row in terminal REJECTED, and unlike the
    revision branch is not bounded by revision_count.'"""

    def test_reject_from_under_review_to_terminal_rejected(self, api):
        """PRD §3.2: "Rejection from UNDER_REVIEW likewise requires
        non-empty notes, lands the row in terminal REJECTED".

        Claim: REJECT decision transitions UNDER_REVIEW -> REJECTED
        (terminal).
        """
        customer, account = setup_funded_account(
            account_type="CASH", cash_amount_cents=0,
            years_options_experience=10,
            liquid_net_worth_cents=50_000_000_00,
            total_net_worth_cents=100_000_000_00,
        )
        oa = create_options_approval(
            customer, account, requested_level=2,
        )
        start_options_review(oa["id"])
        rejected = decide_options_approval(
            oa["id"], decision="REJECT", notes="ineligible",
        )
        assert rejected["status"] == "REJECTED"
