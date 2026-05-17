"""Consent versioning and the re-consent gate.

PRD §2.10 governs consent publication, active_consent_version
maintenance, the publish-status gating, and the stale-versioned
re-consent gate that ties into visit completion.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    anchor_clock,
    assert_consent_version,
    create_consent_version_payload,
    create_trial_in_draft,
    publish_consent_version,
    re_get_trial,
    setup_approved_irb_trial,
    setup_trial_open_for_enrollment,
    setup_two_arms_irb_pending,
    validate_error,
    validate_success,
)


# ===========================================================================
# §2.10 first publish sets active_consent_version to 1.
# ===========================================================================
class TestConsentVersionPublish:
    """PRD §2.10 publish semantics."""

    def test_first_publish_sets_active_to_one(self, api):
        """PRD §2.10: "When a PrincipalInvestigator publishes the first
        consent for a trial, it is assigned version 1 and the trial's
        active_consent_version is set to 1."

        Claim: a freshly created trial's first publish yields a
        ConsentVersion with version 1 and bumps the parent
        active_consent_version to 1.
        """
        anchor_clock()
        trial = create_trial_in_draft()
        res = api.create_consent_version(
            trial["id"],
            create_consent_version_payload(),
            TEST_USERS["pi_headers"],
        )
        cv = validate_success(res, 201)
        assert_consent_version(cv)
        assert cv["version"] == 1
        # Re-read parent to confirm active_consent_version.
        t = re_get_trial(trial["id"])
        assert t["active_consent_version"] == 1

    def test_second_publish_increments_active(self, api):
        """PRD §2.10: "Every subsequent publish increments the version
        by exactly one (1, 2, 3, ...) and updates active_consent_version
        on the parent trial atomically."

        Claim: a second publish yields version 2 and the parent
        active_consent_version is 2.
        """
        anchor_clock()
        trial = create_trial_in_draft()
        publish_consent_version(trial["id"])  # v1
        res = api.create_consent_version(
            trial["id"],
            create_consent_version_payload(
                change_summary="Risk language tightened.",
            ),
            TEST_USERS["pi_headers"],
        )
        cv2 = validate_success(res, 201)
        assert cv2["version"] == 2
        t = re_get_trial(trial["id"])
        assert t["active_consent_version"] == 2

    def test_second_publish_without_change_summary_rejected(self, api):
        """PRD §2.10: "Publishing a second or later version requires
        change_summary of between 1 and 500 characters; publishing the
        first version does not require change_summary."

        Claim: omitting change_summary on a v2 publish returns
        ERR_INVALID_INPUT.
        """
        anchor_clock()
        trial = create_trial_in_draft()
        publish_consent_version(trial["id"])  # v1
        res = api.create_consent_version(
            trial["id"],
            {"document_uri": "s3://consents/v2.pdf"},  # no change_summary
            TEST_USERS["pi_headers"],
        )
        validate_error(res, "ERR_INVALID_INPUT")


# ===========================================================================
# §2.10 publish gated by trial.status.
# ===========================================================================
class TestConsentPublishStateGate:
    """PRD §2.10: "A new consent version may only be published while
    the trial's status is one of DRAFT, IRB_PENDING, APPROVED, or
    OPEN_FOR_ENROLLMENT; an attempt to publish a consent version when
    the trial is in any other status is rejected with
    ERR_INVALID_STATE.\""""

    def test_publish_in_draft_allowed(self, api):
        """PRD §2.10 allowed status: DRAFT.

        Claim: a publish on a DRAFT trial succeeds.
        """
        anchor_clock()
        trial = create_trial_in_draft()
        res = api.create_consent_version(
            trial["id"],
            create_consent_version_payload(),
            TEST_USERS["pi_headers"],
        )
        validate_success(res, 201)

    def test_publish_in_irb_pending_allowed(self, api):
        """PRD §2.10 allowed status: IRB_PENDING.

        Claim: a publish on an IRB_PENDING trial succeeds (e.g., to
        publish v2 alongside the original v1 already published).
        """
        trial, _arms, _v1 = setup_two_arms_irb_pending()
        res = api.create_consent_version(
            trial["id"],
            create_consent_version_payload(
                change_summary="Reviewer note added.",
            ),
            TEST_USERS["pi_headers"],
        )
        validate_success(res, 201)

    def test_publish_in_approved_allowed(self, api):
        """PRD §2.10 allowed status: APPROVED."""
        trial, _arms, _v1 = setup_approved_irb_trial()
        res = api.create_consent_version(
            trial["id"],
            create_consent_version_payload(
                change_summary="Pre-open clarification.",
            ),
            TEST_USERS["pi_headers"],
        )
        validate_success(res, 201)

    def test_publish_in_open_for_enrollment_allowed(self, api):
        """PRD §2.10 allowed status: OPEN_FOR_ENROLLMENT."""
        trial, _arms, _v1 = setup_trial_open_for_enrollment()
        res = api.create_consent_version(
            trial["id"],
            create_consent_version_payload(
                change_summary="Post-open language update.",
                requires_re_consent=False,
            ),
            TEST_USERS["pi_headers"],
        )
        validate_success(res, 201)

    def test_publish_in_terminated_rejected(self, api):
        """PRD §2.10: "an attempt to publish a consent version when the
        trial is in any other status is rejected with
        ERR_INVALID_STATE."

        Claim: a publish on a TERMINATED trial fires
        ERR_INVALID_STATE.
        """
        trial, _arms, _v1 = setup_trial_open_for_enrollment()
        api.terminate_trial(
            trial["id"], {"reason": "Sponsor pull."},
            TEST_USERS["pi_headers"],
        )
        res = api.create_consent_version(
            trial["id"],
            create_consent_version_payload(
                change_summary="Post-termination publish."
            ),
            TEST_USERS["pi_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")
