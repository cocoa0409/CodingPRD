"""Clinical evidence attach / withdraw / reuse semantics.

PRD §3.3 (categories, byte_size bounds, duplicate uri, reuse), §3.7
(reuse-discount).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    EVIDENCE_BYTE_SIZE_MAX,
    NON_EXISTENT_UUID,
    attach_clinical_evidence_payload,
    attach_evidence,
    attach_categories,
    create_authorization_request,
    create_authorization_request_payload,
    make_provider_headers,
    random_uri,
    re_get_authorization,
    setup_reference_data,
    setup_resubmission_with_n_reused_evidence,
    setup_submitted_authorization,
    validate_error,
    validate_success,
    withdraw_evidence,
)


# ===========================================================================
# Attach success path
# ===========================================================================
class TestAttachEvidence:
    """PRD §3.3: attach a clinical-evidence document."""

    def test_attach_creates_attached_evidence(self, api):
        """PRD §3.3: "Every evidence row is created in ATTACHED status
        by default."

        Claim: a newly attached evidence row has status=ATTACHED.
        """
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        ev = attach_evidence(
            provider=provider, authorization=auth, category="LAB",
        )
        assert ev["status"] == "ATTACHED"
        assert ev["category"] == "LAB"
        assert ev["authorization_request_id"] == auth["id"]


# ===========================================================================
# byte_size bounds
# ===========================================================================
class TestByteSize:
    """PRD §3.3: byte_size strictly > 0 and <= 50_000_000."""

    def test_byte_size_zero_rejected(self, api):
        """PRD §3.3: "The byte_size must be strictly greater than 0 and
        no greater than 50,000,000 (50 MB); any size outside that
        closed-bounded range is rejected with ERR_EVIDENCE_SIZE_INVALID."

        Claim: byte_size=0 returns ERR_EVIDENCE_SIZE_INVALID.
        """
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        res = api.attach_clinical_evidence(
            auth["id"],
            attach_clinical_evidence_payload(byte_size=0),
            make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_EVIDENCE_SIZE_INVALID")

    def test_byte_size_above_max_rejected(self, api):
        """PRD §3.3: "no greater than 50,000,000 (50 MB); any size
        outside that closed-bounded range is rejected with
        ERR_EVIDENCE_SIZE_INVALID."

        Claim: byte_size=50_000_001 returns ERR_EVIDENCE_SIZE_INVALID.
        """
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        res = api.attach_clinical_evidence(
            auth["id"],
            attach_clinical_evidence_payload(
                byte_size=EVIDENCE_BYTE_SIZE_MAX + 1,
            ),
            make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_EVIDENCE_SIZE_INVALID")

    def test_byte_size_at_max_accepted(self, api):
        """PRD §3.3: "The byte_size must be strictly greater than 0 and
        no greater than 50,000,000 (50 MB)".

        Claim: byte_size=50_000_000 (the inclusive maximum) is accepted.
        """
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        res = api.attach_clinical_evidence(
            auth["id"],
            attach_clinical_evidence_payload(
                byte_size=EVIDENCE_BYTE_SIZE_MAX,
            ),
            make_provider_headers(provider["id"]),
        )
        ev = validate_success(res, 201)
        assert ev["byte_size"] == EVIDENCE_BYTE_SIZE_MAX


# ===========================================================================
# Duplicate uri
# ===========================================================================
class TestDuplicateUri:
    """PRD §3.3: same uri among ATTACHED rows under the same auth is
    rejected."""

    def test_duplicate_uri_rejected(self, api):
        """PRD §3.3: "Two ATTACHED evidence rows under the same
        authorization may not share the same uri; a colliding upload is
        rejected with ERR_EVIDENCE_DUPLICATE_URI."

        Claim: a second attach with the same uri returns
        ERR_EVIDENCE_DUPLICATE_URI.
        """
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        uri = random_uri()
        attach_evidence(
            provider=provider, authorization=auth,
            category="LAB", uri=uri,
        )
        res = api.attach_clinical_evidence(
            auth["id"],
            attach_clinical_evidence_payload(category="LAB", uri=uri),
            make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_EVIDENCE_DUPLICATE_URI")


# ===========================================================================
# Reuse / sourced_from_request_id
# ===========================================================================
class TestEvidenceReuse:
    """PRD §3.3: reuse only valid in the context of a resubmission."""

    def test_reuse_on_non_resubmission_rejected(self, api):
        """PRD §3.3: "Reuse is only valid in the context of a
        resubmission: if sourced_from_request_id is set, it must equal
        the current authorization's prior_request_id, otherwise the
        upload is rejected with ERR_EVIDENCE_REUSE_MISMATCH."

        Claim: attach with sourced_from_request_id but no
        prior_request_id on the current request → ERR_EVIDENCE_REUSE_MISMATCH.
        """
        # NOTE: we must use a valid existing AuthorizationRequest.id for
        # sourced_from_request_id so the FK existence check (priority
        # 4, ERR_REFERENCE_NOT_FOUND) does not preempt the reuse-mismatch
        # check (priority 11). Create a second auth to point at.
        patient, provider, catalog_item = setup_reference_data()
        other_auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        # auth.prior_request_id is null but sourced_from_request_id is
        # set to another existing authorization → ERR_EVIDENCE_REUSE_MISMATCH.
        res = api.attach_clinical_evidence(
            auth["id"],
            attach_clinical_evidence_payload(
                category="LAB",
                sourced_from_request_id=other_auth["id"],
            ),
            make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_EVIDENCE_REUSE_MISMATCH")

    def test_reuse_with_wrong_prior_id_rejected(self, api):
        """PRD §3.3: "if sourced_from_request_id is set, it must equal
        the current authorization's prior_request_id, otherwise the
        upload is rejected with ERR_EVIDENCE_REUSE_MISMATCH."

        Claim: on a resubmission, attaching with
        sourced_from_request_id pointing to an authorization OTHER than
        prior_request_id → ERR_EVIDENCE_REUSE_MISMATCH.
        """
        _, provider, _, prior, resub, _ = (
            setup_resubmission_with_n_reused_evidence(num_reused=1)
        )
        # Construct a totally different existing auth id by creating
        # another reference set.
        from test_helpers import setup_reference_data
        p2, prov2, item2 = setup_reference_data()
        other = create_authorization_request(
            patient=p2, provider=prov2, catalog_item=item2,
        )
        res = api.attach_clinical_evidence(
            resub["id"],
            attach_clinical_evidence_payload(
                category="OTHER",
                sourced_from_request_id=other["id"],
            ),
            make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_EVIDENCE_REUSE_MISMATCH")


# ===========================================================================
# Withdraw evidence
# ===========================================================================
class TestWithdrawEvidence:
    """PRD §3.3: withdraw transitions ATTACHED → WITHDRAWN."""

    def test_withdraw_evidence_transitions_to_withdrawn(self, api):
        """PRD §3.3: "A provider can withdraw a previously attached
        document; this transitions its status from ATTACHED to
        WITHDRAWN."

        Claim: POST .../clinical-evidence/{id}/withdraw flips status
        to WITHDRAWN.
        """
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        ev = attach_evidence(
            provider=provider, authorization=auth, category="LAB",
        )
        wd = withdraw_evidence(
            provider=provider, authorization=auth, evidence=ev,
        )
        assert wd["status"] == "WITHDRAWN"


# ===========================================================================
# Append-only shape
# ===========================================================================
class TestEvidenceShape:
    """PRD §2.4: ClinicalEvidence carries only id + created_at."""

    def test_evidence_omits_updated_at_and_version(self, api):
        """PRD §2.4: "ClinicalEvidence is created in ATTACHED status and
        may only transition to WITHDRAWN … Both carry id and created_at
        but omit both updated_at and version."

        Claim: the response object does NOT contain updated_at or
        version keys.
        """
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        ev = attach_evidence(
            provider=provider, authorization=auth, category="LAB",
        )
        assert "updated_at" not in ev
        assert "version" not in ev
