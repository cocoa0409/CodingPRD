"""Activation, document fingerprint pinning, and segregation of duties.

Covers PRD §3.3 (activation preconditions, document_fingerprint
pinning, step-1 cascade, segregation-of-duties for activation).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    activate_contract,
    add_hours,
    append_signing_party,
    append_signing_step,
    assert_contract,
    create_contract_in_draft,
    create_published_template,
    create_signing_party_payload,
    current_clock_iso,
    is_lower_hex_64,
    make_contract_initiator_headers,
    setup_single_party_contract,
    stable_user_id,
    validate_error,
    validate_success,
)


class TestActivateBasic:

    def test_activate_advances_to_pending_sign(self, api):
        """PRD §3.3: 'On a successful activation, four things happen in
        one logical write. First, Contract.status advances DRAFT ->
        PENDING_SIGN and Contract.activated_at is set to the current
        server time.'

        Claim: activate -> status PENDING_SIGN with activated_at non-null.
        """
        ctx = setup_single_party_contract()
        activated = activate_contract(
            contract_id=ctx["contract"]["id"],
            initiator_id=ctx["initiator_id"],
        )
        assert_contract(activated)
        assert activated["status"] == "PENDING_SIGN"
        assert activated["activated_at"] is not None

    def test_activate_pins_document_fingerprint(self, api):
        """PRD §3.3: 'the document_fingerprint_sha256 is computed and
        pinned for the rest of the Contract's lifecycle'.

        Claim: a PENDING_SIGN Contract has a 64-char lowercase hex
        document_fingerprint_sha256.
        """
        ctx = setup_single_party_contract()
        activated = activate_contract(
            contract_id=ctx["contract"]["id"],
            initiator_id=ctx["initiator_id"],
        )
        fp = activated.get("document_fingerprint_sha256")
        assert is_lower_hex_64(fp), (
            f"document_fingerprint_sha256 must be 64 lowercase hex, got {fp!r}"
        )

    def test_activate_initial_progress_is_zero(self, api):
        """PRD §3.9: 'When the denominator is 0 (no eligible parties yet),
        the percentage is 0.00.' Combined with PRD §3.3: a freshly
        activated single-party contract has step_index=1 in ACTIVE with
        the party in AUTHENTICATING; nothing is SIGNED yet.

        Claim: after activate, signing_progress_percent == 0.00 and
        status is PENDING_SIGN.
        """
        ctx = setup_single_party_contract()
        activated = activate_contract(
            contract_id=ctx["contract"]["id"],
            initiator_id=ctx["initiator_id"],
        )
        assert activated["status"] == "PENDING_SIGN"
        assert activated["signing_progress_percent"] == 0.00


class TestActivateDraftPreconditions:

    def test_activate_non_draft_rejected(self, api):
        """PRD §3.3: 'If the Contract is not in DRAFT, the call returns
        ERR_INVALID_STATE.'

        Claim: activate again on a PENDING_SIGN contract -> ERR_INVALID_STATE.
        """
        ctx = setup_pending_sign_helper()
        res = api.activate_contract(
            ctx["contract"]["id"], ctx["init_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_activate_with_no_signing_step_rejected(self, api):
        """PRD §3.3: 'at least one SigningStep with step_index = 1 exists'.

        Claim: activate with zero signing steps -> ERR_VALIDATION_FAILED
        (request body is missing a precondition the activation check
        depends on).
        """
        bundle = create_published_template()
        contract, init_id = create_contract_in_draft(
            template_version_id=bundle["version"]["id"],
            initiator_org_id=bundle["owner_org_id"],
        )
        # No SigningStep appended.
        res = api.activate_contract(
            contract["id"],
            make_contract_initiator_headers(init_id),
        )
        # PRD §3.3 lists the precondition; the standard error from a
        # validation check is ERR_VALIDATION_FAILED. Two-reader check:
        # implementations that emit ERR_INVALID_STATE for this would also
        # be PRD-faithful, so we relax with validate_error_is_one_of.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_VALIDATION_FAILED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])

    def test_activate_with_step_lacking_party_rejected(self, api):
        """PRD §3.3: 'every SigningStep has at least one SigningParty'.

        Claim: activate with a step that has no parties -> rejected.
        """
        bundle = create_published_template()
        contract, init_id = create_contract_in_draft(
            template_version_id=bundle["version"]["id"],
            initiator_org_id=bundle["owner_org_id"],
        )
        append_signing_step(
            contract_id=contract["id"], initiator_id=init_id,
            step_index=1, mode="PARALLEL_COUNTERSIGN",
        )
        # No party.
        res = api.activate_contract(
            contract["id"],
            make_contract_initiator_headers(init_id),
        )
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_VALIDATION_FAILED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])


class TestActivateExpiration:

    def test_activate_already_expired_rejected(self, api):
        """PRD §3.3: 'the current server time is strictly less than the
        Contract's expires_at (an expired contract at activation time is
        rejected with ERR_CONTRACT_EXPIRED).'

        Claim: activate a contract whose expires_at is at or before now ->
        ERR_CONTRACT_EXPIRED.
        """
        bundle = create_published_template()
        # Set expires_at slightly past current_clock_iso(). We use an
        # expires_at_offset_hours of negative... but expires_at must be
        # ISO. Build it explicitly.
        from test_helpers import (
            create_contract_payload,
            api_client as api_helper_client,
            add_seconds,
        )
        now = current_clock_iso()
        # Past expires_at.
        past = add_seconds(now, -1)
        init_id = stable_user_id("init")
        # Some implementations validate request schema before allowing a
        # past expires_at. We sign through the standard create_contract
        # path; if creation succeeds, we then activate to surface the
        # ERR_CONTRACT_EXPIRED.
        create_res = api_helper_client.create_contract(
            create_contract_payload(
                template_version_id=bundle["version"]["id"],
                expires_at=past,
            ),
            make_contract_initiator_headers(init_id),
        )
        if create_res.status_code >= 400:
            # The implementation rejected at creation time with a
            # validation error; PRD doesn't strictly forbid this. Treat
            # it as an acceptable outcome for the boundary test.
            pytest.skip(
                "Implementation rejects past-expires_at at creation time."
            )
        contract = create_res.json()["data"]
        # Append step + party so other preconditions pass.
        step = append_signing_step(
            contract_id=contract["id"], initiator_id=init_id,
            step_index=1, mode="PARALLEL_COUNTERSIGN",
        )
        append_signing_party(
            contract_id=contract["id"], signing_step_id=step["id"],
            initiator_id=init_id, signer_user_id=stable_user_id("s"),
            role_key="PARTY_A",
        )
        res = api.activate_contract(
            contract["id"],
            make_contract_initiator_headers(init_id),
        )
        validate_error(res, ApiErrorId.ERR_CONTRACT_EXPIRED.value)


class TestActivateSegregation:

    def test_activator_cannot_be_template_publisher(self, api):
        """PRD §3.3: 'the activating user is not the same OrgUser who
        published the referenced TemplateVersion (segregation of duties --
        violation yields ERR_SEGREGATION_OF_DUTIES)'.

        Claim: when the same OrgUser.id appears as both the publisher of
        the TemplateVersion and the initiator of the contract, activate
        -> ERR_SEGREGATION_OF_DUTIES.
        """
        # Mint a single OrgUser id that will play both roles.
        shared_id = stable_user_id("shared")
        bundle = create_published_template(admin_id=shared_id)
        # Now create a contract using the SAME id as the initiator.
        contract, _ = create_contract_in_draft(
            template_version_id=bundle["version"]["id"],
            initiator_id=shared_id,
            initiator_org_id=bundle["owner_org_id"],
        )
        step = append_signing_step(
            contract_id=contract["id"], initiator_id=shared_id,
            step_index=1, mode="PARALLEL_COUNTERSIGN",
        )
        append_signing_party(
            contract_id=contract["id"], signing_step_id=step["id"],
            initiator_id=shared_id,
            signer_user_id=stable_user_id("s"),
            role_key="PARTY_A",
        )
        res = api.activate_contract(
            contract["id"],
            make_contract_initiator_headers(shared_id),
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ---------------------------------------------------------------------------
# Helpers private to this file
# ---------------------------------------------------------------------------
def setup_pending_sign_helper():
    """Build a PENDING_SIGN single-party contract and return a context
    dict including init_headers ready to use in this file's tests."""
    ctx = setup_single_party_contract()
    activated = activate_contract(
        contract_id=ctx["contract"]["id"],
        initiator_id=ctx["initiator_id"],
    )
    ctx["contract"] = activated
    ctx["init_headers"] = make_contract_initiator_headers(ctx["initiator_id"])
    return ctx
