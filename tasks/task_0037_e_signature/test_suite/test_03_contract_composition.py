"""Contract composition in DRAFT.

Covers PRD §3.2 (contract creation, signing-step / signing-party
appendage, ORG_LEGAL_REP MFA gate, ORG_DELEGATE delegation gate,
permission scope, workflow-locked rule).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    activate_contract,
    add_hours,
    append_signing_party,
    append_signing_step,
    assert_contract,
    assert_signing_party,
    assert_signing_step,
    create_contract_in_draft,
    create_contract_payload,
    create_published_template,
    create_signing_party_payload,
    create_signing_step_payload,
    current_clock_iso,
    make_contract_initiator_headers,
    setup_pending_sign_single_party,
    setup_single_party_contract,
    stable_user_id,
    unique_org_id,
    validate_error,
    validate_success,
)


class TestContractCreate:

    def test_create_contract_sets_initial_fields_to_null_default(self, api):
        """PRD §3.2: 'On creation the Contract receives a fresh id, the
        initiator_user_id and initiator_org_id copied from the authenticated
        request, and status = DRAFT. The fields activated_at, completed_at,
        voided_at, void_reason, and document_fingerprint_sha256 all default
        to null at creation.'

        Claim: a fresh DRAFT contract has those five fields null and
        status DRAFT.
        """
        bundle = create_published_template()
        contract, init_id = create_contract_in_draft(
            template_version_id=bundle["version"]["id"],
            initiator_org_id=bundle["owner_org_id"],
        )
        assert_contract(contract)
        assert contract["status"] == "DRAFT"
        assert contract.get("activated_at") is None
        assert contract.get("completed_at") is None
        assert contract.get("voided_at") is None
        assert contract.get("void_reason") is None
        assert contract.get("document_fingerprint_sha256") is None

    def test_create_contract_against_unpublished_version_rejected(self, api):
        """PRD §3.2: 'If the referenced TemplateVersion is not in PUBLISHED,
        the call is rejected with ERR_TEMPLATE_NOT_PUBLISHED.'

        Claim: create against a DRAFT version -> 409
        ERR_TEMPLATE_NOT_PUBLISHED.
        """
        from test_helpers import (
            create_template,
            create_template_version,
        )
        template, admin_id, _ = create_template()
        v_draft = create_template_version(
            template_id=template["id"], admin_id=admin_id,
        )
        init_id = stable_user_id("init")
        res = api.create_contract(
            create_contract_payload(
                template_version_id=v_draft["id"],
                expires_at=add_hours(current_clock_iso(), 24),
            ),
            make_contract_initiator_headers(init_id),
        )
        validate_error(res, ApiErrorId.ERR_TEMPLATE_NOT_PUBLISHED.value)


class TestPermissionScope:

    def test_org_only_template_rejects_other_org(self, api):
        """PRD §3.2: 'An ORG_ONLY template may only be instantiated when
        the initiator's initiator_org_id matches the template's
        owner_org_id. Violations are rejected with
        ERR_TEMPLATE_PERMISSION_DENIED.'

        Claim: an initiator from a different org instantiating an
        ORG_ONLY template -> 403 ERR_TEMPLATE_PERMISSION_DENIED.
        """
        bundle = create_published_template(permission_scope="ORG_ONLY")
        # Different initiator_org_id than bundle["owner_org_id"].
        init_id = stable_user_id("init")
        other_org = unique_org_id()
        headers = make_contract_initiator_headers(init_id)
        # Many implementations encode initiator_org_id from a header; we
        # let the helper attach X-Org-ID. The PRD only states the
        # rejection rule; we trust the implementation to surface it.
        headers = dict(headers)
        headers["X-Org-ID"] = other_org
        res = api.create_contract(
            create_contract_payload(
                template_version_id=bundle["version"]["id"],
                expires_at=add_hours(current_clock_iso(), 24),
            ),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_TEMPLATE_PERMISSION_DENIED.value)


class TestSigningStepCompose:

    def test_first_step_index_one(self, api):
        """PRD §3.2: 'each SigningStep carries a step_index starting at 1
        and strictly increasing per Contract'.

        Claim: first step on a fresh DRAFT contract has step_index == 1.
        """
        ctx = setup_single_party_contract()
        # The fixture already added step_index=1; reread to verify.
        assert ctx["step"]["step_index"] == 1
        assert ctx["step"]["status"] == "PENDING"


class TestLegalRepMfa:

    def test_legal_rep_with_one_factor_rejected(self, api):
        """PRD §3.2: 'A signing party representing an ORG_LEGAL_REP must
        require multi-factor authentication: its required_auth_factors
        array must have length of at least 2, otherwise the platform
        rejects the call with ERR_LEGAL_REP_REQUIRES_MFA.'

        Claim: POST a SigningParty with signer_type=ORG_LEGAL_REP and
        required_auth_factors=[SMS] -> ERR_LEGAL_REP_REQUIRES_MFA.
        """
        bundle = create_published_template()
        contract, init_id = create_contract_in_draft(
            template_version_id=bundle["version"]["id"],
            initiator_org_id=bundle["owner_org_id"],
        )
        step = append_signing_step(
            contract_id=contract["id"], initiator_id=init_id,
            step_index=1, mode="PARALLEL_COUNTERSIGN",
        )
        signer_id = stable_user_id("legalrep")
        signer_org = unique_org_id()
        res = api.create_signing_party(
            contract["id"], step["id"],
            create_signing_party_payload(
                signer_type="ORG_LEGAL_REP",
                signer_user_id=signer_id,
                signer_org_id=signer_org,
                required_auth_factors=["SMS"],  # only one factor
            ),
            make_contract_initiator_headers(init_id),
        )
        validate_error(res, ApiErrorId.ERR_LEGAL_REP_REQUIRES_MFA.value)

    def test_legal_rep_with_two_factors_succeeds(self, api):
        """PRD §3.2: 'its required_auth_factors array must have length of
        at least 2, otherwise the platform rejects the call with
        ERR_LEGAL_REP_REQUIRES_MFA.'

        Claim: ORG_LEGAL_REP with two factors -> 201.
        """
        bundle = create_published_template()
        contract, init_id = create_contract_in_draft(
            template_version_id=bundle["version"]["id"],
            initiator_org_id=bundle["owner_org_id"],
        )
        step = append_signing_step(
            contract_id=contract["id"], initiator_id=init_id,
            step_index=1, mode="PARALLEL_COUNTERSIGN",
        )
        signer_id = stable_user_id("legalrep")
        res = api.create_signing_party(
            contract["id"], step["id"],
            create_signing_party_payload(
                signer_type="ORG_LEGAL_REP",
                signer_user_id=signer_id,
                signer_org_id=unique_org_id(),
                required_auth_factors=["SMS", "FACE"],
            ),
            make_contract_initiator_headers(init_id),
        )
        data = validate_success(res, expected_status=201)
        assert_signing_party(data)
        assert data["signer_type"] == "ORG_LEGAL_REP"


class TestDelegation:

    def test_org_delegate_without_authorization_rejected(self, api):
        """PRD §3.2: 'When signer_type is ORG_DELEGATE, the
        delegation_authorization_id must be non-null and must point to an
        active OrgUser whose org_role is AUTHORIZED_DELEGATE within
        signer_org_id; otherwise the call is rejected with
        ERR_DELEGATION_INVALID.'

        Claim: ORG_DELEGATE with delegation_authorization_id missing ->
        ERR_DELEGATION_INVALID.
        """
        bundle = create_published_template()
        contract, init_id = create_contract_in_draft(
            template_version_id=bundle["version"]["id"],
            initiator_org_id=bundle["owner_org_id"],
        )
        step = append_signing_step(
            contract_id=contract["id"], initiator_id=init_id,
            step_index=1, mode="PARALLEL_COUNTERSIGN",
        )
        # Note: required_auth_factors=2 to keep this independent of MFA gate.
        res = api.create_signing_party(
            contract["id"], step["id"],
            create_signing_party_payload(
                signer_type="ORG_DELEGATE",
                signer_user_id=stable_user_id("delegate"),
                signer_org_id=unique_org_id(),
                delegation_authorization_id=None,  # missing
                required_auth_factors=["SMS", "FACE"],
            ),
            make_contract_initiator_headers(init_id),
        )
        validate_error(res, ApiErrorId.ERR_DELEGATION_INVALID.value)


class TestWorkflowLocked:

    def test_append_step_after_activation_locked(self, api):
        """PRD §3.2: 'every structural edit to a Contract -- modifying
        title, expires_at, variable_values, or appending signing steps or
        parties -- is permitted only while the Contract is in DRAFT.
        Once the Contract has left DRAFT, any such structural edit is
        rejected with ERR_WORKFLOW_LOCKED.'

        Claim: appending a signing step to a PENDING_SIGN contract ->
        ERR_WORKFLOW_LOCKED.
        """
        ctx = setup_pending_sign_single_party()
        res = api.create_signing_step(
            ctx["contract"]["id"],
            create_signing_step_payload(step_index=2),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        validate_error(res, ApiErrorId.ERR_WORKFLOW_LOCKED.value)

    def test_append_party_after_activation_locked(self, api):
        """PRD §3.2: 'appending signing steps or parties... is permitted
        only while the Contract is in DRAFT. Once the Contract has left
        DRAFT, any such structural edit is rejected with
        ERR_WORKFLOW_LOCKED.'

        Claim: append a SigningParty under a step on a PENDING_SIGN
        contract -> ERR_WORKFLOW_LOCKED.
        """
        ctx = setup_pending_sign_single_party()
        res = api.create_signing_party(
            ctx["contract"]["id"], ctx["step"]["id"],
            create_signing_party_payload(
                signer_user_id=stable_user_id("late"),
                role_key="LATE",
            ),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        validate_error(res, ApiErrorId.ERR_WORKFLOW_LOCKED.value)
