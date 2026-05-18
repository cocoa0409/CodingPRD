"""CC&R disclosure: immutability, buyer ownership, advance gating (PRD §3.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_escrow,
    api_client,
    assert_ccr_disclosure,
    ccr_disclosure_payload,
    create_ccr_disclosure,
    create_emd_held,
    create_escrow_file_basic,
    make_buyer_headers,
    setup_emd_held,
    setup_owners_policy_bound,
    setup_title_cleared,
    sha256_hex,
    validate_error,
    validate_success,
    with_idempotency,
)


# ===========================================================================
# Immutability — PRD §2.4 / §3.4
# ===========================================================================
class TestCCRImmutability:

    def test_ccr_disclosure_no_updated_at_or_version(self, api):
        """PRD §2.4: "A CCRDisclosure is a signed record. It carries
        only id and created_at; it has neither updated_at nor version
        because the buyer's acknowledgment is captured once and never
        edited."

        Claim: CCRDisclosure response excludes updated_at and version.
        """
        bundle = setup_emd_held()
        buyer_id = bundle["buyer"]["id"]
        ef_id = bundle["escrow_file"]["id"]
        ccr = create_ccr_disclosure(ef_id, buyer_id)
        assert_ccr_disclosure(ccr)


# ===========================================================================
# Buyer ownership — PRD §2.1 / §3.4
# ===========================================================================
class TestCCRBuyerOwnership:

    def test_ccr_disclosure_succeeds_for_actual_buyer(self, api):
        """PRD §3.4: "The buyer creates a CCRDisclosure by supplying
        the escrow_file_id, a ccr_document_hash ... and a
        material_restrictions array".
        PRD §2.1: "a buyer can only acknowledge a Closing Disclosure or
        sign a CC&R disclosure on an escrow file whose buyer_party_id
        equals the caller's X-User-ID."

        Claim: the buyer whose Party.id == escrow_file.buyer_party_id
        can create a CCRDisclosure.
        """
        bundle = setup_emd_held()
        ef_id = bundle["escrow_file"]["id"]
        headers = with_idempotency(
            make_buyer_headers(bundle["buyer"]["id"]),
        )
        resp = api.create_ccr_disclosure(
            ccr_disclosure_payload(escrow_file_id=ef_id),
            headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_ccr_disclosure(data)
        assert data["escrow_file_id"] == ef_id

    def test_ccr_disclosure_by_wrong_buyer_rejected(self, api):
        """PRD §2.1: "ownership checks on any resource that references
        a Party compare the resource's foreign-key field to X-User-ID.
        Concretely, a buyer can only acknowledge a Closing Disclosure
        or sign a CC&R disclosure on an escrow file whose
        buyer_party_id equals the caller's X-User-ID."

        Claim: a Buyer whose X-User-ID is not the escrow file's
        buyer_party_id cannot create a CCR disclosure for that file
        (ERR_FORBIDDEN_ROLE per priority 2 of §2.8).
        """
        bundle_a = setup_emd_held()
        bundle_b = setup_emd_held()
        # Buyer of bundle_b tries to act on bundle_a.
        headers = with_idempotency(
            make_buyer_headers(bundle_b["buyer"]["id"]),
        )
        resp = api.create_ccr_disclosure(
            ccr_disclosure_payload(
                escrow_file_id=bundle_a["escrow_file"]["id"],
            ),
            headers,
        )
        # PRD §2.8 priority 2 is role authorization; an unauthorized
        # actor on a resource they don't own → ERR_FORBIDDEN_ROLE.
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


# ===========================================================================
# CC&R advance gating — PRD §3.9
# ===========================================================================
class TestCCRAdvanceGating:

    def test_advance_past_contingent_title_without_ccr_blocked(self, api):
        """PRD §3.9: "Advancing past CONTINGENT_TITLE without a
        CCRDisclosure is rejected with ERR_CCR_NOT_ACKNOWLEDGED".

        Claim: with title CLEARED and OWNERS BOUND but no CCR, advance
        from CONTINGENT_TITLE yields ERR_CCR_NOT_ACKNOWLEDGED.
        """
        bundle = setup_emd_held()
        ef_id = bundle["escrow_file"]["id"]
        advance_escrow(ef_id)  # OPEN → CONTINGENT_TITLE
        setup_title_cleared(ef_id)
        setup_owners_policy_bound(ef_id)
        # NO CCR.
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.advance_escrow_file(ef_id, eo)
        validate_error(resp, ApiErrorId.ERR_CCR_NOT_ACKNOWLEDGED)

    def test_advance_past_contingent_title_with_ccr_succeeds(self, api):
        """PRD §3.9: "From CONTINGENT_TITLE it advances to
        CONTINGENT_CD once three preconditions hold simultaneously: a
        TitleSearch on the file is in CLEARED, a TitleInsurancePolicy
        with policy_kind equal to OWNERS is in BOUND, and a
        CCRDisclosure exists for the file."

        Claim: with CCR present and the other preconditions met, the
        advance succeeds to CONTINGENT_CD.
        """
        bundle = setup_emd_held()
        ef_id = bundle["escrow_file"]["id"]
        advance_escrow(ef_id)
        setup_title_cleared(ef_id)
        setup_owners_policy_bound(ef_id)
        create_ccr_disclosure(ef_id, bundle["buyer"]["id"])
        ef_after = advance_escrow(ef_id)
        assert ef_after["status"] == "CONTINGENT_CD"
