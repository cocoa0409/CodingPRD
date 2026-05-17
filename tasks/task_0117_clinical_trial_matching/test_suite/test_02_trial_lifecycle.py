"""Trial lifecycle — DRAFT through terminal states.

PRD §3.1 (creation + arms + consent v1), §3.2 (IRB review), §3.3
(open-enrollment / close / complete / terminate), §3.5 (auto-close on
cap), §2.6 (OCC on PATCH).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    IRB_APPROVAL_VALIDITY_DAYS,
    TEST_DEFAULTS,
    TEST_USERS,
    add_arm,
    advance_clock_to,
    anchor_clock,
    assert_irb_review,
    assert_trial,
    create_trial_in_draft,
    create_trial_payload,
    iso_anchor_offset,
    iso_utc,
    list_irb_reviews,
    open_trial_for_enrollment,
    parse_anchor,
    parse_iso,
    publish_consent_version,
    re_get_trial,
    setup_approved_irb_trial,
    setup_enrolled_participant,
    setup_trial_open_for_enrollment,
    setup_two_arms_irb_pending,
    submit_irb_review,
    submit_trial_for_irb,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.1 Trial creation + DRAFT state.
# ===========================================================================
class TestTrialCreation:
    """PRD §3.1 trial creation."""

    def test_create_in_draft(self, api):
        """PRD §3.1: "A freshly created trial begins life in DRAFT
        status with active_consent_version of null and enrolled_count
        of zero."

        Claim: a successful create returns a Trial in DRAFT with
        active_consent_version null and enrolled_count zero.
        """
        anchor_clock()
        res = api.create_trial(
            create_trial_payload(),
            TEST_USERS["pi_headers"],
        )
        trial = validate_success(res, 201)
        assert_trial(trial)
        assert trial["status"] == "DRAFT"
        assert trial.get("active_consent_version") is None
        assert trial["enrolled_count"] == 0

    def test_duplicate_protocol_code_rejected(self, api):
        """PRD §3.1: "Two protocol-code constraints apply: any
        duplicate protocol_code collision at create time, or at update
        time (a metadata edit applied to an existing trial in DRAFT),
        is rejected with ERR_DUPLICATE_PROTOCOL_CODE."

        Claim: creating two trials with the same protocol_code fails
        on the second with ERR_DUPLICATE_PROTOCOL_CODE.
        """
        anchor_clock()
        code = "TST-12345"
        first = api.create_trial(
            create_trial_payload(protocol_code=code),
            TEST_USERS["pi_headers"],
        )
        validate_success(first, 201)
        second = api.create_trial(
            create_trial_payload(protocol_code=code),
            TEST_USERS["pi_headers"],
        )
        validate_error(second, "ERR_DUPLICATE_PROTOCOL_CODE")


# ===========================================================================
# §3.1 submit-for-irb — randomization preconditions.
# ===========================================================================
class TestSubmitForIRBPreconditions:
    """PRD §3.1: "The submit precondition fires
    ERR_RANDOMIZATION_MISCONFIGURED (HTTP 422) unless all four of the
    following are true: the trial has at least 2 arms; for
    PERMUTED_BLOCK or STRATIFIED_BLOCK, the block_size is exactly
    divisible by the arm count (block_size modulo the number of arms
    is zero); for those same schemes, every arm's weight is equal to
    every other arm's weight; and for STRATIFIED_BLOCK specifically,
    stratification_field is non-null.\""""

    def test_submit_with_less_than_two_arms_rejected(self, api):
        """PRD §3.1: "the trial has at least 2 arms" — one of the four
        submit-for-irb preconditions.

        Claim: a trial with only one arm fails submit-for-irb with
        ERR_RANDOMIZATION_MISCONFIGURED.
        """
        anchor_clock()
        trial = create_trial_in_draft()
        add_arm(trial["id"], code="A1", label="Arm 1", weight=1)
        publish_consent_version(trial["id"])
        res = api.submit_for_irb(
            trial["id"], TEST_USERS["pi_headers"],
        )
        validate_error(res, "ERR_RANDOMIZATION_MISCONFIGURED")

    def test_submit_with_unequal_arm_weights_under_block_scheme(
        self, api,
    ):
        """PRD §3.1: "for those same schemes, every arm's weight is
        equal to every other arm's weight" — applies to PERMUTED_BLOCK
        and STRATIFIED_BLOCK.

        Claim: PERMUTED_BLOCK with weights [1, 2] fires
        ERR_RANDOMIZATION_MISCONFIGURED on submit.
        """
        anchor_clock()
        trial = create_trial_in_draft(
            randomization_scheme="PERMUTED_BLOCK",
            block_size=4,
        )
        add_arm(trial["id"], code="A1", label="Arm 1", weight=1)
        add_arm(trial["id"], code="A2", label="Arm 2", weight=2)
        publish_consent_version(trial["id"])
        res = api.submit_for_irb(
            trial["id"], TEST_USERS["pi_headers"],
        )
        validate_error(res, "ERR_RANDOMIZATION_MISCONFIGURED")

    def test_submit_with_block_size_not_divisible_by_arm_count(
        self, api,
    ):
        """PRD §3.1: "the block_size is exactly divisible by the arm
        count (block_size modulo the number of arms is zero)".

        Claim: PERMUTED_BLOCK with 3 arms and block_size 4 fires
        ERR_RANDOMIZATION_MISCONFIGURED on submit (4 mod 3 != 0).
        """
        anchor_clock()
        trial = create_trial_in_draft(
            randomization_scheme="PERMUTED_BLOCK",
            block_size=4,
        )
        add_arm(trial["id"], code="A1", label="Arm 1", weight=1)
        add_arm(trial["id"], code="A2", label="Arm 2", weight=1)
        add_arm(trial["id"], code="A3", label="Arm 3", weight=1)
        publish_consent_version(trial["id"])
        res = api.submit_for_irb(
            trial["id"], TEST_USERS["pi_headers"],
        )
        validate_error(res, "ERR_RANDOMIZATION_MISCONFIGURED")

    def test_submit_succeeds_with_two_equal_arms_and_v1(self, api):
        """PRD §3.1: "When all checks pass, the trial moves into
        IRB_PENDING."

        Claim: 2 arms of equal weight + consent v1 + SIMPLE_BERNOULLI
        scheme passes submit and the trial transitions to IRB_PENDING.
        """
        trial, _arms, _v1 = setup_two_arms_irb_pending()
        assert trial["status"] == "IRB_PENDING"


# ===========================================================================
# §3.2 IRB review — three decision branches.
# ===========================================================================
class TestIRBReview:
    """PRD §3.2 IRB review decisions and their state transitions."""

    def test_approved_transitions_to_approved_with_expiry(self, api):
        """PRD §3.2: "An APPROVED decision transitions the trial
        IRB_PENDING → APPROVED. The server records irb_decision_note
        from the supplied notes, sets irb_approval_expires_at to
        exactly 365 days after the decided_at timestamp, and persists
        the new IRBReview row."

        Claim: APPROVED moves the trial to APPROVED and stamps
        irb_approval_expires_at exactly 365 days after decided_at.
        """
        trial, _arms, _v1 = setup_two_arms_irb_pending()
        notes = "All checks pass; trial approved."
        review_res = api.create_irb_review(
            trial["id"],
            {"decision": "APPROVED", "notes": notes},
            TEST_USERS["irb_reviewer_headers"],
        )
        review = validate_success(review_res, 201)
        assert_irb_review(review)
        assert review["decision"] == "APPROVED"
        assert review["notes"] == notes
        decided_at = parse_iso(review["decided_at"])

        approved = re_get_trial(trial["id"])
        assert approved["status"] == "APPROVED"
        assert approved.get("irb_decision_note") == notes
        expires_at = parse_iso(approved["irb_approval_expires_at"])
        delta_days = (expires_at - decided_at).total_seconds() / 86400
        assert abs(delta_days - IRB_APPROVAL_VALIDITY_DAYS) < 1e-3, (
            f"irb_approval_expires_at must be exactly 365 days after "
            f"decided_at; saw {delta_days:.6f} days"
        )

    def test_revisions_requested_returns_to_draft(self, api):
        """PRD §3.2: "A REVISIONS_REQUESTED decision transitions the
        trial back to DRAFT, records the notes as the new
        irb_decision_note, and persists the IRBReview row."

        Claim: REVISIONS_REQUESTED moves the trial to DRAFT.
        """
        trial, _arms, _v1 = setup_two_arms_irb_pending()
        api.create_irb_review(
            trial["id"],
            {"decision": "REVISIONS_REQUESTED",
             "notes": "Tighten exclusion 3."},
            TEST_USERS["irb_reviewer_headers"],
        )
        t = re_get_trial(trial["id"])
        assert t["status"] == "DRAFT"
        assert t.get("irb_decision_note") == "Tighten exclusion 3."

    def test_rejected_moves_to_terminated(self, api):
        """PRD §3.2: "A REJECTED decision transitions the trial
        directly to TERMINATED, persists the IRBReview row, and ends
        the lifecycle."

        Claim: REJECTED moves the trial to TERMINATED.
        """
        trial, _arms, _v1 = setup_two_arms_irb_pending()
        api.create_irb_review(
            trial["id"],
            {"decision": "REJECTED", "notes": "Insufficient rationale."},
            TEST_USERS["irb_reviewer_headers"],
        )
        t = re_get_trial(trial["id"])
        assert t["status"] == "TERMINATED"


# ===========================================================================
# §3.3 open-enrollment / close-enrollment / complete / terminate.
# ===========================================================================
class TestEnrollmentLifecycle:
    """PRD §3.3 lifecycle from APPROVED forward."""

    def test_open_enrollment_succeeds_when_consent_and_clock_ok(
        self, api,
    ):
        """PRD §3.3: "Two conditions must hold: active_consent_version
        must be non-null, and the current logical clock time must be
        strictly earlier than irb_approval_expires_at. When the
        conditions hold, the trial moves to OPEN_FOR_ENROLLMENT."

        Claim: with v1 published and clock not advanced past expiry,
        open-enrollment succeeds.
        """
        trial, _arms, _v1 = setup_approved_irb_trial()
        opened = validate_success(
            api.open_enrollment(
                trial["id"], TEST_USERS["pi_headers"],
            ),
            200,
        )
        assert opened["status"] == "OPEN_FOR_ENROLLMENT"

    def test_open_enrollment_after_expiry_fires_err_irb_expired(
        self, api,
    ):
        """PRD §3.3: "If the clock has reached or passed that expiry,
        the request is rejected with ERR_IRB_EXPIRED and the trial
        must be re-submitted and re-approved before enrollment can
        begin."

        Claim: advancing the clock past irb_approval_expires_at causes
        open-enrollment to fire ERR_IRB_EXPIRED.
        """
        trial, _arms, _v1 = setup_approved_irb_trial()
        # Advance the clock 366 days past the anchor so it is past the
        # 365-day expiry recorded at IRB approval.
        advance_clock_to(iso_anchor_offset(days=366))
        res = api.open_enrollment(
            trial["id"], TEST_USERS["pi_headers"],
        )
        validate_error(res, "ERR_IRB_EXPIRED")

    def test_close_enrollment_moves_to_closed(self, api):
        """PRD §3.3: "a manual close by the investigator moves it from
        OPEN_FOR_ENROLLMENT to CLOSED_TO_ENROLLMENT."

        Claim: POST /close-enrollment on an OPEN trial returns it in
        CLOSED_TO_ENROLLMENT.
        """
        trial, _arms, _v1 = setup_trial_open_for_enrollment()
        res = api.close_enrollment(
            trial["id"], TEST_USERS["pi_headers"],
        )
        closed = validate_success(res, 200)
        assert closed["status"] == "CLOSED_TO_ENROLLMENT"

    def test_complete_blocked_if_active_participants_remain(self, api):
        """PRD §3.3: "Completion is permitted only when every
        participant attached to the trial has reached COMPLETED,
        WITHDRAWN, or INELIGIBLE — that is, when no participant is
        still in SCREENING, ELIGIBLE, CONSENT_PENDING, or ENROLLED. If
        any participant is still active, the request is rejected with
        ERR_INVALID_STATE."

        Claim: with an ENROLLED participant still outstanding, a
        trial-complete on the CLOSED trial fails with
        ERR_INVALID_STATE.
        """
        trial, p, _arms = setup_enrolled_participant()
        # Close enrollment manually.
        api.close_enrollment(trial["id"], TEST_USERS["pi_headers"])
        res = api.complete_trial(
            trial["id"], TEST_USERS["pi_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")
        assert p["status"] == "ENROLLED"

    def test_terminate_from_open_moves_to_terminated(self, api):
        """PRD §3.3: "the investigator may terminate the trial
        outright, optionally supplying a reason field; this transitions
        OPEN_FOR_ENROLLMENT → TERMINATED".

        Claim: terminate on an OPEN trial returns it in TERMINATED.
        """
        trial, _arms, _v1 = setup_trial_open_for_enrollment()
        res = api.terminate_trial(
            trial["id"], {"reason": "Sponsor withdrawn."},
            TEST_USERS["pi_headers"],
        )
        t = validate_success(res, 200)
        assert t["status"] == "TERMINATED"


# ===========================================================================
# §3.1 / §2.6 OCC on PATCH /trials/{id}.
# ===========================================================================
class TestTrialPatchOCC:
    """PRD §2.6 OCC and PRD §3.1 metadata-update editability."""

    def test_patch_draft_metadata_succeeds(self, api):
        """PRD §3.1: "While the trial is in DRAFT, the investigator can
        edit title, sponsor_org, inclusion_criteria,
        exclusion_criteria, and target_enrollment through the
        metadata-update endpoint".

        Claim: PATCH on a DRAFT trial updates title and bumps version.
        """
        anchor_clock()
        trial = create_trial_in_draft()
        old_version = trial["version"]
        res = api.patch_trial(
            trial["id"], {"title": "Updated Title",
                          "version": old_version},
            TEST_USERS["pi_headers"],
        )
        patched = validate_success(res, 200)
        assert patched["title"] == "Updated Title"
        assert patched["version"] == old_version + 1

    def test_patch_with_stale_version_returns_version_conflict(
        self, api,
    ):
        """PRD §2.6: "When a client supplies version, the server
        compares it against the row's persisted version; if the two
        are not equal, the request is rejected with
        ERR_VERSION_CONFLICT at HTTP 409."

        Claim: a PATCH with a stale version returns
        ERR_VERSION_CONFLICT.
        """
        anchor_clock()
        trial = create_trial_in_draft()
        stale = trial["version"]
        # First successful patch bumps version.
        api.patch_trial(
            trial["id"], {"title": "Updated", "version": stale},
            TEST_USERS["pi_headers"],
        )
        res = api.patch_trial(
            trial["id"], {"title": "Again", "version": stale},
            TEST_USERS["pi_headers"],
        )
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_patch_without_version_skips_occ_check(self, api):
        """PRD §2.6: "When the version field is omitted from the body,
        the OCC check is skipped entirely and the mutation proceeds
        without a stale-data guard."

        Claim: a PATCH that omits version succeeds even after the row
        has been mutated to a different version.
        """
        anchor_clock()
        trial = create_trial_in_draft()
        # First mutation to bump version off its starting value.
        api.patch_trial(
            trial["id"], {"title": "First", "version": trial["version"]},
            TEST_USERS["pi_headers"],
        )
        # Now PATCH without version — OCC check is skipped.
        res = api.patch_trial(
            trial["id"], {"title": "Second"},
            TEST_USERS["pi_headers"],
        )
        validate_success(res, 200)
