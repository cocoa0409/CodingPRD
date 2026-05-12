"""Authorization workflow — eligibility gate, branching, reject, revoke.

PRD §3.2 (Authorization Approval Workflow).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    approve_authorization_as_owner,
    approve_authorization_as_platform,
    assert_authorization,
    create_lab_with_owner,
    create_verified_user,
    create_user,
    make_lab_owner_headers,
    make_user_headers,
    register_equipment,
    reject_authorization_payload,
    request_authorization,
    request_and_approve_authorization,
    revoke_authorization,
    setup_basic_scenario,
    setup_high_value_equipment_pair,
    validate_error,
    validate_success,
)


# ===========================================================================
# Eligibility gate (PRD §3.2)
# ===========================================================================
class TestEligibilityGate:
    """PRD §3.2: 'The authorization passes the gate only when the total
    score is at least 100 — meaning every component must be 1; any zero
    input causes immediate rejection. When the failure is specifically a
    sharing-scope mismatch (training, sample, and identity all 1 but
    affiliation 0), the system returns ERR_SHARING_SCOPE_VIOLATION; in
    every other failing combination the system returns
    ERR_QUALIFICATION_NOT_MET.'
    """

    def test_missing_training_fails_qualification(self, api):
        """PRD §3.2: 'training_match input is 1 when every code in the
        equipment's required_training_codes array is present in the
        user's training_certificates array, and 0 otherwise ... any zero
        input causes immediate rejection ... the system returns
        ERR_QUALIFICATION_NOT_MET'."""
        lab, owner = create_lab_with_owner()
        user = create_verified_user(
            affiliation="WITHIN_SCHOOL",
            training_certificates=[],  # missing required code
        )
        equipment = register_equipment(
            lab=lab, owner_user=owner,
            sharing_scope="WITHIN_SCHOOL",
            required_training_codes=["T1"],
            allowed_sample_types=["S"],
        )
        from test_helpers import create_billing_rule_payload, draft_and_publish_billing_rule
        draft_and_publish_billing_rule(
            equipment=equipment, owner_user=owner,
        )
        res = api.create_authorization(
            equipment["id"],
            {"user_id": user["id"], "sample_type": "S",
             "urgency": "NORMAL"},
            make_user_headers(user["id"]),
        )
        validate_error(res, ApiErrorId.ERR_QUALIFICATION_NOT_MET.value)

    def test_sample_type_not_allowed_fails_qualification(self, api):
        """PRD §3.2: 'sample_match input is 1 when the requested
        sample_type is a member of allowed_sample_types, and 0 otherwise
        ... ERR_QUALIFICATION_NOT_MET'."""
        s = setup_basic_scenario()
        res = api.create_authorization(
            s["equipment"]["id"],
            {"user_id": s["user"]["id"], "sample_type": "NOT_ALLOWED",
             "urgency": "NORMAL"},
            make_user_headers(s["user"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_QUALIFICATION_NOT_MET.value)

    def test_identity_unverified_fails_qualification(self, api):
        """PRD §3.2: 'identity_match input is 1 when User.identity_verified
        is true, and 0 otherwise ... ERR_QUALIFICATION_NOT_MET'."""
        lab, owner = create_lab_with_owner()
        u = create_user(  # NOT verified
            affiliation="WITHIN_SCHOOL", training_certificates=["T1"],
        )
        equipment = register_equipment(
            lab=lab, owner_user=owner,
            sharing_scope="WITHIN_SCHOOL",
            required_training_codes=["T1"],
            allowed_sample_types=["S"],
        )
        from test_helpers import draft_and_publish_billing_rule
        draft_and_publish_billing_rule(
            equipment=equipment, owner_user=owner,
        )
        res = api.create_authorization(
            equipment["id"],
            {"user_id": u["id"], "sample_type": "S",
             "urgency": "NORMAL"},
            make_user_headers(u["id"]),
        )
        validate_error(res, ApiErrorId.ERR_QUALIFICATION_NOT_MET.value)

    def test_sharing_scope_mismatch_returns_specific_error(self, api):
        """PRD §3.2: 'When the failure is specifically a sharing-scope
        mismatch (training, sample, and identity all 1 but affiliation 0),
        the system returns ERR_SHARING_SCOPE_VIOLATION'."""
        lab, owner = create_lab_with_owner()
        # Equipment is scoped WITHIN_SCHOOL; user is EXTERNAL but
        # otherwise fully qualified.
        u = create_verified_user(
            affiliation="EXTERNAL", training_certificates=["T1"],
        )
        equipment = register_equipment(
            lab=lab, owner_user=owner,
            sharing_scope="WITHIN_SCHOOL",
            required_training_codes=["T1"],
            allowed_sample_types=["S"],
        )
        from test_helpers import draft_and_publish_billing_rule
        draft_and_publish_billing_rule(
            equipment=equipment, owner_user=owner,
        )
        res = api.create_authorization(
            equipment["id"],
            {"user_id": u["id"], "sample_type": "S",
             "urgency": "NORMAL"},
            make_user_headers(u["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SHARING_SCOPE_VIOLATION.value)


# ===========================================================================
# Branching workflow (PRD §3.2)
# ===========================================================================
class TestAuthorizationBranching:
    """PRD §3.2: 'For a STANDARD instrument, the owner step alone is
    decisive ... For a HIGH_VALUE instrument the workflow forks. When
    urgency is URGENT the same single owner approval transitions the
    authorization directly to APPROVED ... When urgency is NORMAL the
    owner approval first transitions the authorization to
    PENDING_PLATFORM with owner_decision_user_id recorded; a subsequent
    platform approval by any PlatformAdmin then writes
    platform_decision_user_id, sets approved_at and expires_at, and
    transitions to APPROVED.'
    """

    def test_standard_owner_step_alone_approves(self, api):
        """PRD §3.2: 'For a STANDARD instrument, the owner step alone is
        decisive'."""
        s = setup_basic_scenario(value_tier="STANDARD")
        auth = request_authorization(
            equipment=s["equipment"], user=s["user"], urgency="NORMAL",
        )
        auth = approve_authorization_as_owner(
            authorization=auth, owner_user=s["owner_user"],
        )
        assert auth["status"] == "APPROVED"
        assert auth["owner_decision_user_id"] == s["owner_user"]["id"]
        # PRD §3.2: 'approved_at, expires_at written'.
        assert auth["approved_at"] is not None
        assert auth["expires_at"] is not None

    def test_high_value_normal_routes_through_platform(self, api):
        """PRD §3.2: 'When urgency is NORMAL the owner approval first
        transitions the authorization to PENDING_PLATFORM with
        owner_decision_user_id recorded; a subsequent platform approval
        by any PlatformAdmin then writes platform_decision_user_id, sets
        approved_at and expires_at, and transitions to APPROVED'."""
        s = setup_high_value_equipment_pair()
        auth = request_authorization(
            equipment=s["equipment_high"], user=s["user"],
            urgency="NORMAL",
        )
        # Owner step → PENDING_PLATFORM (fork).
        auth = approve_authorization_as_owner(
            authorization=auth, owner_user=s["owner_user"],
        )
        assert auth["status"] == "PENDING_PLATFORM"
        assert auth["owner_decision_user_id"] == s["owner_user"]["id"]
        # Platform step → APPROVED (join).
        auth = approve_authorization_as_platform(authorization=auth)
        assert auth["status"] == "APPROVED"
        assert auth["platform_decision_user_id"] is not None
        assert auth["approved_at"] is not None
        assert auth["expires_at"] is not None

    def test_high_value_urgent_skips_platform(self, api):
        """PRD §3.2: 'For a HIGH_VALUE instrument ... When urgency is
        URGENT the same single owner approval transitions the
        authorization directly to APPROVED and behaves identically to
        the STANDARD flow'."""
        s = setup_high_value_equipment_pair()
        auth = request_authorization(
            equipment=s["equipment_high"], user=s["user"],
            urgency="URGENT",
        )
        auth = approve_authorization_as_owner(
            authorization=auth, owner_user=s["owner_user"],
        )
        assert auth["status"] == "APPROVED"
        assert auth["approved_at"] is not None


# ===========================================================================
# Reject and revoke (PRD §3.2)
# ===========================================================================
class TestRejectAndRevoke:
    """PRD §3.2: 'A rejection at either pending stage uses the same reject
    action ... The authorization moves to REJECTED with the captured
    from_state ... a REJECT audit row is written ... Once APPROVED, an
    authorization remains valid until either it is explicitly revoked or
    its expires_at is reached.'
    """

    def test_owner_reject_moves_to_rejected(self, api):
        """PRD §3.2: 'The authorization moves to REJECTED'."""
        s = setup_basic_scenario()
        auth = request_authorization(
            equipment=s["equipment"], user=s["user"],
        )
        res = api.reject_authorization(
            auth["id"],
            make_lab_owner_headers(s["owner_user"]["id"]),
            reject_authorization_payload(),
        )
        rejected = validate_success(res, 200)
        assert rejected["status"] == "REJECTED"

    def test_revoke_moves_approved_to_revoked(self, api):
        """PRD §3.2: 'Revocation may be requested by the equipment's
        LabOwner or by a PlatformAdmin; the authorization moves to
        REVOKED'."""
        s = setup_basic_scenario()
        revoked = revoke_authorization(
            authorization=s["authorization"],
            owner_user=s["owner_user"],
        )
        assert revoked["status"] == "REVOKED"

    def test_second_approval_after_decision_rejected(self, api):
        """PRD §3.2: 'An approval attempted on an authorization that has
        already left its initial pending state ... is rejected with
        ERR_AUTHORIZATION_ALREADY_DECIDED'."""
        s = setup_basic_scenario()
        # s.authorization is already APPROVED.
        res = api.approve_authorization(
            s["authorization"]["id"],
            make_lab_owner_headers(s["owner_user"]["id"]),
        )
        validate_error(
            res, ApiErrorId.ERR_AUTHORIZATION_ALREADY_DECIDED.value,
        )
