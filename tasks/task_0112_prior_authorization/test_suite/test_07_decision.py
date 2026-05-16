"""Initial decision (APPROVED / DENIED).

PRD §3.9 (decision payload, validations, Decision row, expires_at on
approval), §2.4 (Decision is append-only).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    DEFAULT_APPROVAL_VALIDITY_DAYS,
    HOURS_PER_DAY,
    TEST_USERS,
    decide_authorization,
    decide_authorization_payload,
    iso_offset,
    occ_payload,
    parse_iso,
    re_get_authorization,
    setup_under_review_authorization,
    validate_error,
    validate_success,
)


# ===========================================================================
# Approve happy path
# ===========================================================================
class TestApproveDecision:
    """PRD §3.9: APPROVED outcome."""

    def test_decide_approved_transitions_status(self, api):
        """PRD §3.9: "The InitialReviewer issues the initial decision
        while the authorization is in UNDER_REVIEW, advancing it to
        APPROVED or DENIED."

        Claim: decide outcome=APPROVED → status=APPROVED on the
        authorization.
        """
        _, _, _, auth, _ = setup_under_review_authorization()
        res = api.decide_authorization_request(
            auth["id"],
            decide_authorization_payload(
                outcome="APPROVED", approved_units=1,
                version=auth["version"],
            ),
            TEST_USERS["initial_reviewer_headers"],
        )
        validate_success(res, 201)
        after = re_get_authorization(auth["id"])
        assert after["status"] == "APPROVED"
        assert after.get("decided_at") is not None

    def test_decide_approved_computes_expires_at(self, api):
        """PRD §3.9: "If the outcome is APPROVED, the system also
        computes expires_at as decided_at plus the version-pinned
        approval_validity_days multiplied by 24 hours, expressed to the
        millisecond in ISO 8601 UTC."

        Claim: a STANDARD authorization approved with default
        approval_validity_days=90 produces expires_at == decided_at +
        90 * 24 hours.
        """
        _, _, _, auth, _ = setup_under_review_authorization(
            approval_validity_days=DEFAULT_APPROVAL_VALIDITY_DAYS,
        )
        decide_authorization(
            authorization=auth, outcome="APPROVED", approved_units=1,
        )
        after = re_get_authorization(auth["id"])
        decided_at = parse_iso(after["decided_at"])
        expires_at = parse_iso(after["expires_at"])
        delta = expires_at - decided_at
        assert delta.total_seconds() == (
            DEFAULT_APPROVAL_VALIDITY_DAYS * HOURS_PER_DAY * 3600
        )

    def test_approved_units_above_requested_units_rejected(self, api):
        """PRD §3.9: "When the outcome is APPROVED, approved_units must
        be at least 1 and at most the authorization's requested_units;
        values outside that range are rejected with
        ERR_INVALID_APPROVED_UNITS."

        Claim: approving with approved_units = requested_units + 1
        returns ERR_INVALID_APPROVED_UNITS.
        """
        _, _, _, auth, _ = setup_under_review_authorization(
            requested_units=5,
        )
        res = api.decide_authorization_request(
            auth["id"],
            decide_authorization_payload(
                outcome="APPROVED",
                approved_units=auth["requested_units"] + 1,
                version=auth["version"],
            ),
            TEST_USERS["initial_reviewer_headers"],
        )
        validate_error(res, "ERR_INVALID_APPROVED_UNITS")

    def test_approved_units_zero_rejected(self, api):
        """PRD §3.9: "When the outcome is APPROVED, approved_units must
        be at least 1".

        Claim: approving with approved_units=0 returns
        ERR_INVALID_APPROVED_UNITS.
        """
        _, _, _, auth, _ = setup_under_review_authorization()
        res = api.decide_authorization_request(
            auth["id"],
            decide_authorization_payload(
                outcome="APPROVED", approved_units=0,
                version=auth["version"],
            ),
            TEST_USERS["initial_reviewer_headers"],
        )
        validate_error(res, "ERR_INVALID_APPROVED_UNITS")


# ===========================================================================
# Deny path
# ===========================================================================
class TestDenyDecision:
    """PRD §3.9: DENIED outcome."""

    def test_decide_denied_transitions_status(self, api):
        """PRD §3.9: "The InitialReviewer issues the initial decision
        while the authorization is in UNDER_REVIEW, advancing it to
        APPROVED or DENIED."

        Claim: decide outcome=DENIED with denial_reason_code →
        status=DENIED.
        """
        _, _, _, auth, _ = setup_under_review_authorization()
        res = api.decide_authorization_request(
            auth["id"],
            decide_authorization_payload(
                outcome="DENIED", approved_units=0,
                denial_reason_code="NOT_MEDICALLY_NECESSARY",
                version=auth["version"],
            ),
            TEST_USERS["initial_reviewer_headers"],
        )
        validate_success(res, 201)
        after = re_get_authorization(auth["id"])
        assert after["status"] == "DENIED"

    def test_denied_without_reason_code_rejected(self, api):
        """PRD §3.9: "When the outcome is DENIED, approved_units must
        be 0 (and a denial_reason_code must be supplied, else
        ERR_DENIAL_REASON_REQUIRED)."

        Claim: decide outcome=DENIED with no denial_reason_code returns
        ERR_DENIAL_REASON_REQUIRED.
        """
        _, _, _, auth, _ = setup_under_review_authorization()
        payload = decide_authorization_payload(
            outcome="DENIED", approved_units=0,
            version=auth["version"],
        )
        # Make sure denial_reason_code is absent.
        payload.pop("denial_reason_code", None)
        res = api.decide_authorization_request(
            auth["id"], payload,
            TEST_USERS["initial_reviewer_headers"],
        )
        validate_error(res, "ERR_DENIAL_REASON_REQUIRED")

    def test_denied_with_nonzero_approved_units_rejected(self, api):
        """PRD §3.9: "When the outcome is DENIED, approved_units must
        be 0".

        Claim: decide outcome=DENIED with approved_units=2 returns
        ERR_INVALID_APPROVED_UNITS.
        """
        _, _, _, auth, _ = setup_under_review_authorization()
        res = api.decide_authorization_request(
            auth["id"],
            decide_authorization_payload(
                outcome="DENIED", approved_units=2,
                denial_reason_code="NOT_MEDICALLY_NECESSARY",
                version=auth["version"],
            ),
            TEST_USERS["initial_reviewer_headers"],
        )
        validate_error(res, "ERR_INVALID_APPROVED_UNITS")


# ===========================================================================
# Decision row contents (append-only)
# ===========================================================================
class TestDecisionRowShape:
    """PRD §3.9: Decision is append-only audit history."""

    def test_initial_decision_row_carries_role_and_no_predecessor(
        self, api,
    ):
        """PRD §3.9: "A successful decision creates a Decision row
        whose authorization_request_id ties it back to the
        authorization, whose outcome and rationale and approved_units
        and denial_reason_code mirror the decision payload, and whose
        decided_by_role is set by the system to INITIAL_REVIEWER on the
        initial decision … On the initial decision,
        supersedes_decision_id is null because no prior decision is
        being overridden."

        Claim: the Decision returned by the initial /decide call has
        decided_by_role=INITIAL_REVIEWER and supersedes_decision_id is
        null.
        """
        _, _, _, auth, _ = setup_under_review_authorization()
        res = api.decide_authorization_request(
            auth["id"],
            decide_authorization_payload(
                outcome="APPROVED", approved_units=1,
                version=auth["version"],
            ),
            TEST_USERS["initial_reviewer_headers"],
        )
        decision = validate_success(res, 201)
        assert decision["decided_by_role"] == "INITIAL_REVIEWER"
        assert decision.get("supersedes_decision_id") is None
        # PRD §2.4 / §3.9: Decision is append-only — no updated_at /
        # version.
        assert "updated_at" not in decision
        assert "version" not in decision
