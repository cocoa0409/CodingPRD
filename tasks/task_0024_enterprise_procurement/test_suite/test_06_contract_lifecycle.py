"""Contract drafting, review, versioning, signature, termination (PRD §3.6)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    amend_contract_payload,
    assert_contract,
    assert_contract_version,
    buyer_signs,
    create_clause_template,
    create_contract_for,
    create_contract_payload,
    finalize_contract_review,
    make_supplier_headers,
    setup_approved_po,
    setup_executed_contract,
    sign_contract_payload,
    submit_contract_review,
    supplier_signs,
    terminate_contract_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Contract creation against APPROVED PO (PRD §3.6)
# ===========================================================================
class TestContractCreate:
    def test_create_contract_starts_in_drafting_with_v1_snapshot(
        self, api, buyer_headers
    ):
        """PRD §3.6: "The contract is created in DRAFTING, its
        current_version initialized to 1, its signatures array empty, and
        an immediate ContractVersion snapshot v1 is written capturing
        clause_template_ids_snapshot, payment_terms_snapshot, and the
        originating change_reason."

        Claim: a freshly created Contract has status=DRAFTING,
        current_version=1, empty signatures; a v1 ContractVersion
        snapshot exists.
        """
        setup = setup_approved_po()
        contract = create_contract_for(setup["po"], payment_terms_type="ON_DELIVERY")
        assert_contract(contract)
        assert contract["status"] == "DRAFTING"
        assert contract["current_version"] == 1
        assert contract["signatures"] == []

        versions = validate_success(
            api.list_contract_versions(contract["id"], buyer_headers), 200
        )
        if isinstance(versions, dict):
            versions = versions.get("versions") or versions.get("data") or []
        assert any(v["version_number"] == 1 for v in versions), (
            "Expected v1 ContractVersion snapshot"
        )

    # DELETED test_inactive_clause_template_blocks_submit_for_review:
    # PRD §3.6 names ERR_CLAUSE_TEMPLATE_INACTIVE, but the only template
    # state described is "is_active flag defaults to true". No public
    # mutation path takes a template to is_active=false (no PATCH or
    # DELETE on /clause-templates listed in §4). Silence-pattern:
    # applies_to-scope — the rule fires only on a state PRD provides no
    # path to reach. Unique-derivability fails: implementer A might
    # never expose deactivation; implementer B might add an admin
    # endpoint. DELETED.


# ===========================================================================
# Submit-for-review and finalize (PRD §3.6)
# ===========================================================================
class TestContractSubmitFinalize:
    def test_submit_for_review_advances_to_in_review(self, api, buyer_headers):
        """PRD §3.6: "On submit-for-review, the contract transitions from
        DRAFTING to IN_REVIEW."

        Claim: status DRAFTING -> IN_REVIEW after submit-for-review.
        """
        setup = setup_approved_po()
        contract = create_contract_for(setup["po"])
        c2 = submit_contract_review(contract["id"])
        assert c2["status"] == "IN_REVIEW"

    def test_finalize_review_advances_to_awaiting_signature(
        self, api, legal_headers
    ):
        """PRD §3.6: "A LegalApprover may finalize the review
        (transitioning the contract from IN_REVIEW to AWAITING_SIGNATURE)".

        Claim: finalize-review advances IN_REVIEW -> AWAITING_SIGNATURE.
        """
        setup = setup_approved_po()
        contract = create_contract_for(setup["po"])
        submit_contract_review(contract["id"])
        c3 = finalize_contract_review(contract["id"])
        assert c3["status"] == "AWAITING_SIGNATURE"


# ===========================================================================
# Amend cycles (PRD §3.6)
# ===========================================================================
class TestContractAmend:
    def test_amend_from_in_review_back_to_drafting_bumps_version(
        self, api, buyer_headers
    ):
        """PRD §3.6: "an amendment from IN_REVIEW requires a non-empty
        change_reason, increments current_version by 1, writes a new
        ContractVersion snapshot for the new version capturing the latest
        clause_template_ids, payment_terms_type, and payment_terms_params,
        and appends an AuditLogEntry with action CONTRACT_AMENDED."

        Claim: amend from IN_REVIEW returns the contract in DRAFTING with
        current_version incremented and a new ContractVersion appended.
        """
        setup = setup_approved_po()
        contract = create_contract_for(setup["po"])
        submit_contract_review(contract["id"])
        c2 = validate_success(
            api.amend_contract(
                contract["id"],
                amend_contract_payload(change_reason="Legal feedback"),
                buyer_headers,
            ),
            200,
        )
        assert c2["status"] == "DRAFTING"
        assert c2["current_version"] == 2

    def test_amend_from_awaiting_signature_clears_signatures(
        self, api, buyer_headers
    ):
        """PRD §3.6: "If the buyer amends instead — and either no
        signatures have yet been collected, or all collected signatures
        are invalidated by the amendment — the contract reverts to
        DRAFTING, current_version is incremented, the existing signatures
        array is cleared, and an AuditLogEntry with action
        CONTRACT_AMENDED is appended."

        Claim: amend from AWAITING_SIGNATURE returns contract in DRAFTING
        with current_version incremented and signatures cleared.
        """
        setup = setup_approved_po()
        contract = create_contract_for(setup["po"])
        submit_contract_review(contract["id"])
        finalize_contract_review(contract["id"])
        # No signatures yet.
        amended = validate_success(
            api.amend_contract(
                contract["id"],
                amend_contract_payload(change_reason="Add IP clause"),
                buyer_headers,
            ),
            200,
        )
        assert amended["status"] == "DRAFTING"
        assert amended["current_version"] == 2
        assert amended["signatures"] == []


# ===========================================================================
# Signatures + cascade to EXECUTED (PRD §3.6)
# ===========================================================================
class TestContractSignatures:
    def test_supplier_sign_requires_supplier_id_match(
        self, api, buyer_headers
    ):
        """PRD §3.6: "A Supplier party's X-User-ID must equal the
        supplier_id of the purchase order behind the contract — the
        entity-backed identity check from §2.1."

        Claim: signing with role=Supplier but X-User-ID that does not
        equal the PO's supplier_id is rejected (PRD §2.1 priority 4
        forbidden ownership check).
        """
        setup = setup_approved_po()
        contract = create_contract_for(setup["po"])
        submit_contract_review(contract["id"])
        finalize_contract_review(contract["id"])
        # Supplier role but with a different supplier id.
        wrong_supplier_headers = make_supplier_headers("not-the-real-supplier")
        res = api.sign_contract(
            contract["id"],
            sign_contract_payload(role="Supplier"),
            wrong_supplier_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_final_signature_executes_and_cascades_po_to_contracted(
        self, api, buyer_headers
    ):
        """PRD §3.6: "the moment the final signature lands such that
        every role in parties_required has a corresponding entry in
        signatures, the contract transitions from AWAITING_SIGNATURE to
        EXECUTED, the bound purchase order cascades from APPROVED to
        CONTRACTED, and the payment schedule generation fires."

        Claim: after both Buyer and Supplier signatures, contract is
        EXECUTED and PO is CONTRACTED.
        """
        setup = setup_executed_contract(payment_terms_type="ON_DELIVERY")
        c = setup["contract"]
        po = setup["po"]
        assert c["status"] == "EXECUTED"
        assert po["status"] == "CONTRACTED"

    def test_duplicate_role_signature_rejected(
        self, api, buyer_headers, buyer_headers_alt
    ):
        """PRD §3.6: "Two signatures from the same role on the same
        contract are not allowed; the loser receives
        ERR_SIGNATURE_ALREADY_COLLECTED."

        Claim: a second Buyer signature on the same contract yields
        ERR_SIGNATURE_ALREADY_COLLECTED.
        """
        setup = setup_approved_po()
        contract = create_contract_for(setup["po"])
        submit_contract_review(contract["id"])
        finalize_contract_review(contract["id"])
        # First buyer sig.
        validate_success(
            api.sign_contract(
                contract["id"],
                sign_contract_payload(role="Buyer"),
                buyer_headers,
            ),
            200,
        )
        # Second buyer sig from a different operator id, same role.
        res = api.sign_contract(
            contract["id"],
            sign_contract_payload(role="Buyer"),
            buyer_headers_alt,
        )
        validate_error(res, ApiErrorId.ERR_SIGNATURE_ALREADY_COLLECTED.value)


# ===========================================================================
# Contract uniqueness per PO (PRD §3.6, §2.9)
# ===========================================================================
class TestContractUniquePerPo:
    def test_second_contract_on_same_po_rejected(self, api, buyer_headers):
        """PRD §2.9: "When two contract creations are attempted on the
        same approved purchase order, the unique index on
        Contract.purchase_order_id admits only one; the loser receives
        ERR_CONTRACT_ALREADY_EXISTS."

        Claim: a second POST /contracts with the same purchase_order_id
        yields ERR_CONTRACT_ALREADY_EXISTS.
        """
        setup = setup_approved_po()
        c1 = create_contract_for(setup["po"])
        # Attempt a second create.
        clause = create_clause_template()
        payload = create_contract_payload(
            purchase_order_id=setup["po"]["id"],
            clause_template_ids=[clause["id"]],
            payment_terms_type="ON_DELIVERY",
            payment_terms_params={},
            parties_required=["Buyer", "Supplier"],
        )
        res = api.create_contract(payload, buyer_headers)
        validate_error(res, ApiErrorId.ERR_CONTRACT_ALREADY_EXISTS.value)


# ===========================================================================
# Termination (PRD §3.6)
# ===========================================================================
class TestContractTerminate:
    def test_terminate_executed_contract_moves_to_terminated(
        self, api, gm_headers
    ):
        """PRD §3.6: "A GeneralManager may terminate an EXECUTED contract
        with a supplied reason; termination requires the bound purchase
        order to be in CONTRACTED or FULFILLED, moves the contract to
        TERMINATED, cancels every PENDING PaymentSchedule entry on that
        purchase order, and releases the budget commitment for the
        unpaid balance".

        Claim: after terminate, contract is TERMINATED.
        """
        setup = setup_executed_contract(payment_terms_type="ON_DELIVERY")
        res = validate_success(
            api.terminate_contract(
                setup["contract"]["id"],
                terminate_contract_payload(reason="Vendor non-performance"),
                gm_headers,
            ),
            200,
        )
        assert res["status"] == "TERMINATED"
