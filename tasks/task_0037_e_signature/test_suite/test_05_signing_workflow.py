"""Signing workflow: identity verification, sign/decline, TSA drift, hash
match, party-state cascades.

Covers PRD §3.4 (step activation, branch conditions, party AUTHENTICATING),
§3.5 (identity verification, sign-act preconditions, TSA), §3.6 (step
completion, contract completion, decline cascade).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    activate_contract,
    add_seconds,
    add_minutes,
    advance_clock,
    api_client,
    append_signing_party,
    append_signing_step,
    branch_condition,
    create_contract_in_draft,
    create_identity_verification,
    create_published_template,
    create_signing_party_payload,
    current_clock_iso,
    decline_party,
    get_contract,
    get_evidence_package,
    list_audit_logs,
    make_contract_initiator_headers,
    make_signer_headers,
    setup_completed_single_party_contract,
    setup_decline_two_party_step,
    setup_pending_sign_single_party,
    setup_single_party_contract,
    setup_three_step_branched_contract,
    sign_party,
    sign_party_payload,
    signature_position,
    stable_user_id,
    validate_error,
    validate_success,
    variable_field,
)


# =========================================================================
# §3.5 -- Sign-act preconditions
# =========================================================================
class TestSignParty:

    def test_sign_drives_party_to_signed_and_contract_to_completed(self, api):
        """PRD §3.5: 'The party then transitions AUTHENTICATING -> SIGNED,
        its signed_at is stamped to the current server time'.
        PRD §3.6: 'When the last party of the last required step signs,
        the Contract transitions from PARTIALLY_SIGNED to COMPLETED (or
        directly from PENDING_SIGN to COMPLETED if the workflow had only
        one party).'

        Claim: a single-party contract reaches COMPLETED after one sign.
        """
        ctx = setup_completed_single_party_contract()
        contract = ctx["contract"]
        assert contract["status"] == "COMPLETED"
        assert contract["completed_at"] is not None
        assert contract["signing_progress_percent"] == 100.00


class TestSignAuthFactorsSufficient:

    def test_sign_with_insufficient_factors_rejected(self, api):
        """PRD §3.5: 'whose factors_passed is a superset of the party's
        required_auth_factors; otherwise the call is rejected with
        ERR_AUTH_FACTORS_INSUFFICIENT.'

        Claim: party requires [SMS, FACE]; IV passed only [SMS] ->
        ERR_AUTH_FACTORS_INSUFFICIENT.
        """
        ctx = setup_pending_sign_single_party(
            required_auth_factors=["SMS", "FACE"],
        )
        iv = create_identity_verification(
            subject_user_id=ctx["signer_user_id"],
            contract_id=ctx["contract"]["id"],
            factors=[("SMS", "PASS"), ("FACE", "FAIL")],
        )
        res = api.sign_party(
            ctx["party"]["id"],
            sign_party_payload(
                tsa_anchor_at=current_clock_iso(),
                identity_verification_id=iv["id"],
            ),
            make_signer_headers(ctx["signer_user_id"]),
        )
        validate_error(res, ApiErrorId.ERR_AUTH_FACTORS_INSUFFICIENT.value)

    def test_sign_with_failed_iv_rejected(self, api):
        """PRD §3.5: 'There must exist a fresh IdentityVerification...
        with result = VERIFIED... otherwise the call is rejected with
        ERR_AUTH_FACTORS_INSUFFICIENT.'

        Claim: IV with all factors FAIL (result=FAILED) cannot be
        consumed -> ERR_AUTH_FACTORS_INSUFFICIENT.
        """
        ctx = setup_pending_sign_single_party(required_auth_factors=["SMS"])
        iv = create_identity_verification(
            subject_user_id=ctx["signer_user_id"],
            contract_id=ctx["contract"]["id"],
            factors=[("SMS", "FAIL")],  # zero factors_passed -> FAILED
        )
        res = api.sign_party(
            ctx["party"]["id"],
            sign_party_payload(
                tsa_anchor_at=current_clock_iso(),
                identity_verification_id=iv["id"],
            ),
            make_signer_headers(ctx["signer_user_id"]),
        )
        validate_error(res, ApiErrorId.ERR_AUTH_FACTORS_INSUFFICIENT.value)


class TestSignTimestampDrift:

    def test_drift_within_60s_succeeds(self, api):
        """PRD §3.5: 'If drift_seconds exceeds the operational ceiling of
        60 seconds (MAX_TSA_DRIFT_SECONDS), the token's verification_status
        is set to INVALID and the sign is rejected with
        ERR_TIMESTAMP_DRIFT_EXCEEDED'.

        Claim: drift = 30 seconds is within bound, sign succeeds.
        """
        ctx = setup_pending_sign_single_party()
        iv = create_identity_verification(
            subject_user_id=ctx["signer_user_id"],
            contract_id=ctx["contract"]["id"],
            factors=[("SMS", "PASS")],
        )
        res = api.sign_party(
            ctx["party"]["id"],
            sign_party_payload(
                tsa_anchor_at=add_seconds(current_clock_iso(), 30),
                identity_verification_id=iv["id"],
            ),
            make_signer_headers(ctx["signer_user_id"]),
        )
        data = validate_success(res)
        assert data["status"] == "SIGNED"

    def test_drift_above_60s_rejected(self, api):
        """PRD §3.5: 'If drift_seconds exceeds the operational ceiling of
        60 seconds (MAX_TSA_DRIFT_SECONDS), the token's verification_status
        is set to INVALID and the sign is rejected with
        ERR_TIMESTAMP_DRIFT_EXCEEDED'.

        Claim: drift = 61 seconds (just above bound) ->
        ERR_TIMESTAMP_DRIFT_EXCEEDED.
        """
        ctx = setup_pending_sign_single_party()
        iv = create_identity_verification(
            subject_user_id=ctx["signer_user_id"],
            contract_id=ctx["contract"]["id"],
            factors=[("SMS", "PASS")],
        )
        res = api.sign_party(
            ctx["party"]["id"],
            sign_party_payload(
                tsa_anchor_at=add_seconds(current_clock_iso(), 61),
                identity_verification_id=iv["id"],
            ),
            make_signer_headers(ctx["signer_user_id"]),
        )
        validate_error(res, ApiErrorId.ERR_TIMESTAMP_DRIFT_EXCEEDED.value)


class TestSignContractStateGate:

    def test_sign_against_draft_contract_rejected(self, api):
        """PRD §3.5: 'The Contract must be in PENDING_SIGN or
        PARTIALLY_SIGNED, otherwise the call is rejected with
        ERR_INVALID_STATE.'

        Claim: a Contract in DRAFT (party still WAITING, never
        AUTHENTICATING) -> sign returns ERR_INVALID_STATE.
        """
        ctx = setup_single_party_contract()  # contract is DRAFT
        # Build the IV first (requires only contract_id reference; PRD
        # allows IV creation independent of activation).
        iv = create_identity_verification(
            subject_user_id=ctx["signer_user_id"],
            contract_id=ctx["contract"]["id"],
            factors=[("SMS", "PASS")],
        )
        res = api.sign_party(
            ctx["party"]["id"],
            sign_party_payload(
                tsa_anchor_at=current_clock_iso(),
                identity_verification_id=iv["id"],
            ),
            make_signer_headers(ctx["signer_user_id"]),
        )
        # PRD §2.9: 'authentication first; then role authorization; then
        # path-id existence; then template-publication state; then
        # Contract state; then SigningParty active-state'. State gate
        # at priority 5 fires before party-active at priority 6.
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


class TestPartyActiveGate:

    def test_sign_a_signed_party_rejected(self, api):
        """PRD §5: 'ERR_PARTY_NOT_ACTIVE: SigningParty is not in
        AUTHENTICATING.' PRD §3.5: 'The party must currently be in
        AUTHENTICATING, otherwise the call is rejected with
        ERR_PARTY_NOT_ACTIVE.'

        Claim: a re-sign of an already-SIGNED party (Contract is COMPLETED)
        is rejected. Because both Contract state and party state would
        fail, PRD §2.9 gives ERR_INVALID_STATE precedence at priority 5.
        """
        ctx = setup_completed_single_party_contract()
        # Try to sign again on the already-signed party.
        from test_helpers import validate_error_is_one_of
        # Issue a fresh IV (regardless of acceptance, the party is no
        # longer AUTHENTICATING).
        iv = create_identity_verification(
            subject_user_id=ctx["signer_user_id"],
            contract_id=ctx["contract"]["id"],
            factors=[("SMS", "PASS")],
        )
        res = api.sign_party(
            ctx["party"]["id"],
            sign_party_payload(
                tsa_anchor_at=current_clock_iso(),
                identity_verification_id=iv["id"],
            ),
            make_signer_headers(ctx["signer_user_id"]),
        )
        # PRD §2.9 gives Contract state (priority 5, ERR_INVALID_STATE)
        # precedence over Party state (priority 6, ERR_PARTY_NOT_ACTIVE)
        # when both apply.
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# =========================================================================
# §3.4 -- Branch evaluation auto-skips a step
# =========================================================================
class TestBranchSkip:

    def test_branch_false_skips_step(self, api):
        """PRD §3.4: 'When a step has a branch_condition and the condition
        evaluates false, the step is auto-skipped -- its status flips
        directly from PENDING to SKIPPED, every child SigningParty
        cascades from WAITING to SKIPPED, and the next eligible step (the
        one with the lowest step_index still in PENDING) is then
        evaluated for activation, either advancing to ACTIVE or skipping
        in the same way.'

        Claim: with three steps where S2 has a branch evaluating false,
        signing S1 leads to S2 SKIPPED and S3 ACTIVE. After signing S3,
        contract becomes COMPLETED with progress_percent == 100.00.
        """
        # Setup S2 with branch_condition amount >= 10000; amount=5000
        # makes it false -> SKIPPED.
        ctx = setup_three_step_branched_contract(
            amount_value=5000, branch_threshold=10000,
        )
        contract_id = ctx["contract"]["id"]
        init_id = ctx["initiator_id"]
        signer_ids = ctx["signer_user_ids"]
        parties = ctx["parties"]

        # Activate.
        activate_contract(contract_id=contract_id, initiator_id=init_id)
        # Sign S1 party.
        iv1 = create_identity_verification(
            subject_user_id=signer_ids[0], contract_id=contract_id,
            factors=[("SMS", "PASS")],
        )
        sign_party(
            party_id=parties[0]["id"], signer_user_id=signer_ids[0],
            identity_verification_id=iv1["id"],
        )
        # Now S2 should auto-skip and S3 should be ACTIVE. Sign S3.
        iv3 = create_identity_verification(
            subject_user_id=signer_ids[2], contract_id=contract_id,
            factors=[("SMS", "PASS")],
        )
        sign_party(
            party_id=parties[2]["id"], signer_user_id=signer_ids[2],
            identity_verification_id=iv3["id"],
        )
        contract = get_contract(contract_id)
        assert contract["status"] == "COMPLETED"
        # PRD §3.9 + §3.6: chronological progress at completion is 100.00.
        assert contract["signing_progress_percent"] == 100.00


# =========================================================================
# §3.6 -- Decline cascades to step REJECTED and contract VOIDED
# =========================================================================
class TestDeclineCascade:

    def test_decline_cascades_to_void_with_rejected_by_party(self, api):
        """PRD §3.6: 'On decline the party advances AUTHENTICATING ->
        DECLINED. The parent SigningStep cascades to REJECTED... and the
        Contract cascades to VOIDED with void_reason = REJECTED_BY_PARTY.'

        Claim: declining one of two parties -> contract VOIDED with
        void_reason 'REJECTED_BY_PARTY'.
        """
        ctx = setup_decline_two_party_step()
        contract_id = ctx["contract"]["id"]
        sig_a = ctx["signer_user_ids"][0]
        # We don't need an IV for decline -- PRD §3.6: 'A party in
        # AUTHENTICATING can be declined by the signer; the call requires
        # the same identity check as sign (the acting X-User-ID must
        # match the party's signer_user_id or an authorized delegate)
        # and that the party is currently in AUTHENTICATING.'
        decline_party(
            party_id=ctx["parties"][0]["id"],
            signer_user_id=sig_a,
        )
        contract = get_contract(contract_id)
        assert contract["status"] == "VOIDED"
        assert contract["void_reason"] == "REJECTED_BY_PARTY"
        assert contract["voided_at"] is not None


class TestSignByWrongUser:

    def test_signing_party_wrong_signer_id_rejected(self, api):
        """PRD §3.5: 'The acting X-User-ID must equal the party's
        signer_user_id -- except that an ORG_LEGAL_REP may sign on behalf
        of an ORG_DELEGATE under the registered delegation_authorization_id.'

        Claim: a Signer whose X-User-ID does NOT equal the party's
        signer_user_id (and there's no delegation) is rejected. PRD §2.9:
        role authorization is at priority 2 and resource ownership/
        identity check is part of the sign endpoint flow. The PRD does
        not name a specific error for this mismatch; expect either
        ERR_FORBIDDEN (role/identity) or ERR_AUTH_FACTORS_INSUFFICIENT
        (since no IV exists for the wrong user).
        """
        ctx = setup_pending_sign_single_party()
        wrong_signer = stable_user_id("wrong")
        # Create an IV under the wrong signer's id (not the party's).
        iv = create_identity_verification(
            subject_user_id=wrong_signer,
            contract_id=ctx["contract"]["id"],
            factors=[("SMS", "PASS")],
        )
        res = api.sign_party(
            ctx["party"]["id"],
            sign_party_payload(
                tsa_anchor_at=current_clock_iso(),
                identity_verification_id=iv["id"],
            ),
            make_signer_headers(wrong_signer),
        )
        # PRD does not declare a single specific error for the wrong-user
        # case. Two-reader: implementations could legitimately surface
        # ERR_FORBIDDEN, ERR_AUTH_FACTORS_INSUFFICIENT (no IV for the
        # actual signer), or ERR_VALIDATION_FAILED. We accept any of
        # these reject categories.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_FORBIDDEN.value,
            ApiErrorId.ERR_AUTH_FACTORS_INSUFFICIENT.value,
            ApiErrorId.ERR_VALIDATION_FAILED.value,
        ])
