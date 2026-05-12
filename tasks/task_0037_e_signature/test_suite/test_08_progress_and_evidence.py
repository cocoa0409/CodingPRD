"""Signing progress query (chronological / forward_looking) and evidence
strength score (raw, tier banding, NOTARIZED bonus, pre-seal preview,
seal action, export action).

Covers PRD §3.9 (signing_progress_percent variants), §3.10 (evidence
strength tiers and notary bonus), §3.11 (sealing and exporting).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    activate_contract,
    add_seconds,
    api_client,
    assert_contract,
    assert_evidence_package,
    assert_evidence_score_precision,
    assert_progress_precision,
    create_identity_verification,
    current_clock_iso,
    get_contract,
    get_evidence_package,
    get_evidence_preview,
    get_progress,
    list_audit_logs,
    make_contract_initiator_headers,
    make_evidence_archivist_headers,
    seal_evidence_payload,
    setup_completed_single_party_contract,
    setup_completed_with_evidence_in_generating,
    setup_two_step_two_parties_each,
    sign_party,
    stable_user_id,
    validate_error,
    validate_success,
)


# =========================================================================
# §3.9 -- signing_progress_percent (chronological is canonical)
# =========================================================================
class TestProgressChronological:

    def test_zero_progress_when_no_eligible_party(self, api):
        """PRD §3.9: 'When the denominator is 0 (no eligible parties yet),
        the percentage is 0.00.'

        Claim: a brand-new PENDING_SIGN contract (just activated, nobody
        signed yet) has progress 0.00.
        """
        ctx = setup_two_step_two_parties_each()
        activate_contract(
            contract_id=ctx["contract"]["id"],
            initiator_id=ctx["initiator_id"],
        )
        progress = get_progress(ctx["contract"]["id"])
        assert progress["progress_percent"] == 0.00


class TestProgressForwardLooking:

    def test_forward_looking_includes_pending_parties(self, api):
        """PRD §3.9: 'The forward-looking variant assumes every PENDING
        SigningStep will activate and every WAITING SigningParty in those
        steps will be required, so it includes every party under every
        non-SKIPPED step (PENDING plus ACTIVE plus SIGNED plus REJECTED)
        in the denominator; the numerator is still the count of SIGNED
        parties.'

        Claim: with 4 total parties (2 in S1 ACTIVE, 2 in S2 PENDING),
        signing both S1 parties yields forward_looking = 50.00 (2/4).
        """
        ctx = setup_two_step_two_parties_each()
        activate_contract(
            contract_id=ctx["contract"]["id"],
            initiator_id=ctx["initiator_id"],
        )
        for i in range(2):
            iv = create_identity_verification(
                subject_user_id=ctx["signer_user_ids"][i],
                contract_id=ctx["contract"]["id"],
                factors=[("SMS", "PASS")],
            )
            sign_party(
                party_id=ctx["parties"][i]["id"],
                signer_user_id=ctx["signer_user_ids"][i],
                identity_verification_id=iv["id"],
            )
        progress = get_progress(
            ctx["contract"]["id"], variant="forward_looking",
        )
        assert progress["progress_percent"] == 50.00
        assert progress["variant"] == "forward_looking"


# =========================================================================
# §3.10 -- evidence_strength_score and tier banding
# =========================================================================
class TestEvidenceScorePrecisionAndTier:

    def test_completed_contract_score_is_two_decimals(self, api):
        """PRD §2.5: 'Two numeric quantities -- signing_progress_percent
        and evidence_strength_score -- are stored to two decimal places
        using half-up rounding.'

        Claim: a COMPLETED contract has evidence_strength_score stored
        to two decimal places.
        """
        ctx = setup_completed_single_party_contract()
        contract = ctx["contract"]
        assert_progress_precision(contract["signing_progress_percent"])
        assert_evidence_score_precision(contract["evidence_strength_score"])

    def test_single_factor_completed_score(self, api):
        """PRD §3.10: Identity score 50 (single factor) -> raw =
        0.30*50 + 0.30*100 + 0.20*100 + 0.20*0 = 15+30+20+0 = 65.00 (no
        notary, no completion bonus). Tier: 65 in [40, 70) -> SILVER.

        Claim: single-factor completion (drift=0) with notary_provider
        defaulting to NONE yields score 65.00 and tier SILVER.
        """
        ctx = setup_completed_single_party_contract(
            factors=[("SMS", "PASS")], drift_seconds=0.0,
        )
        contract = ctx["contract"]
        assert contract["evidence_strength_score"] == 65.00
        assert contract["evidence_tier"] == "SILVER"


# =========================================================================
# §3.10 -- pre-seal preview
# =========================================================================
class TestEvidencePreview:

    def test_preview_zeroes_notary_when_provider_none(self, api):
        """PRD §3.10: 'A pre-seal preview is available before the
        EvidencePackage is sealed. The preview reports a provisional
        score and a provisional tier computed with the notary score
        forced to 0... For identical inputs at the post-completion-but-
        pre-seal moment, the provisional score is strictly less than the
        post-seal score whenever notary_provider is not NONE, and equal
        to the post-seal score when notary_provider is already NONE.'

        Claim: with notary_provider=NONE on a COMPLETED contract,
        provisional_score == post-completion score.
        """
        ctx = setup_completed_single_party_contract(
            factors=[("SMS", "PASS")], drift_seconds=0.0,
        )
        # Read post-seal computed score before sealing.
        contract = ctx["contract"]
        preview = get_evidence_preview(contract["id"])
        # When notary_provider is NONE, post-seal final and provisional
        # should match (per the PRD sentence above).
        assert preview["provisional_score"] == contract[
            "evidence_strength_score"
        ]


# =========================================================================
# §3.11 -- Sealing
# =========================================================================
class TestEvidenceSeal:

    def test_seal_advances_to_sealed(self, api):
        """PRD §3.11: 'On a successful seal, package_sha256 is computed...,
        sealed_at is stamped to the current server time'.

        Claim: a valid seal transitions the EvidencePackage from
        GENERATING to SEALED with sealed_at non-null and package_sha256
        non-null.
        """
        ctx = setup_completed_with_evidence_in_generating()
        # The archivist must NOT be the same OrgUser as
        # Contract.initiator_user_id.
        archivist_id = ctx["archivist_id"]
        res = api.seal_evidence(
            ctx["contract"]["id"],
            seal_evidence_payload(),
            make_evidence_archivist_headers(archivist_id),
        )
        data = validate_success(res)
        assert_evidence_package(data)
        assert data["status"] == "SEALED"
        assert data["sealed_at"] is not None
        assert data["package_sha256"] is not None

    def test_seal_by_initiator_violates_segregation(self, api):
        """PRD §3.11: 'requires that... the acting user is not the same
        OrgUser as the Contract's initiator_user_id (segregation of
        duties -- violation yields ERR_SEGREGATION_OF_DUTIES)'.

        Claim: when X-User-ID equals initiator_user_id, seal ->
        ERR_SEGREGATION_OF_DUTIES.
        """
        ctx = setup_completed_with_evidence_in_generating()
        # Use the initiator's id as X-User-ID with role
        # EvidenceArchivist -- the SoD compares X-User-ID to
        # initiator_user_id directly.
        res = api.seal_evidence(
            ctx["contract"]["id"],
            seal_evidence_payload(),
            make_evidence_archivist_headers(ctx["initiator_id"]),
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_seal_with_notary_provider_but_empty_reference_rejected(
        self, api,
    ):
        """PRD §3.11: 'if notary_provider is anything other than NONE,
        then notary_reference is non-empty (otherwise the call is
        rejected with ERR_NOTARY_REFERENCE_REQUIRED)'.

        Claim: seal with notary_provider=NOTARY_PUBLIC and empty
        notary_reference -> ERR_NOTARY_REFERENCE_REQUIRED.
        """
        ctx = setup_completed_with_evidence_in_generating()
        res = api.seal_evidence(
            ctx["contract"]["id"],
            seal_evidence_payload(
                notary_provider="NOTARY_PUBLIC",
                notary_reference="",
            ),
            make_evidence_archivist_headers(ctx["archivist_id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOTARY_REFERENCE_REQUIRED.value)


class TestEvidenceExport:

    def test_export_after_seal_advances_to_exported(self, api):
        """PRD §3.11: 'Exporting follows a successful seal. The package
        must be in SEALED... On success, exported_at is stamped... the
        package transitions SEALED -> EXPORTED.'

        Claim: a SEALED package can be exported -> status EXPORTED with
        exported_at non-null.
        """
        ctx = setup_completed_with_evidence_in_generating()
        api.seal_evidence(
            ctx["contract"]["id"],
            seal_evidence_payload(),
            make_evidence_archivist_headers(ctx["archivist_id"]),
        )
        res = api.export_evidence(
            ctx["contract"]["id"],
            make_evidence_archivist_headers(ctx["archivist_id"]),
        )
        data = validate_success(res)
        assert data["status"] == "EXPORTED"
        assert data["exported_at"] is not None

    def test_export_before_seal_rejected(self, api):
        """PRD §3.11 + §2.10: 'an export attempted before seal commits
        sees a non-SEALED package and is rejected with ERR_INVALID_STATE.'

        Claim: export on a GENERATING (not yet SEALED) package ->
        ERR_INVALID_STATE.
        """
        ctx = setup_completed_with_evidence_in_generating()
        res = api.export_evidence(
            ctx["contract"]["id"],
            make_evidence_archivist_headers(ctx["archivist_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
