"""Account documents, authorized signers, and the title-change workflow
(including the reject/resubmit loop and the document-verification gate)."""
from test_helpers import (
    MANAGER,
    MANAGER_2,
    OFFICER,
    OFFICER_1,
    ApiErrorId,
    add_active_signer,
    add_verified_document,
    api_client,
    assert_title_change_request,
    file_title_change,
    get_account,
    open_account,
    submit_document,
    title_change_payload,
    validate_error,
    validate_success,
)


class TestDocumentReview:

    def test_document_review_from_terminal_rejected(self):
        """PRD section 3.2: "Only a document still in `SUBMITTED` can be
        reviewed — re-deciding a decided document fails with
        `ERR_INVALID_STATE` — and both outcomes are terminal."

        Design: Corner/state_machines/document_review_from_terminal_rejected
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="Doc D", owner_tax_id="C6")
        doc = submit_document(acct["id"], "SIGNATURE_CARD", "SC-D")
        reviewed = validate_success(
            api_client.review_document(doc["id"], {"decision": "VERIFIED"},
                                       MANAGER),
            expected_status=200,
        )
        assert reviewed["status"] == "VERIFIED"

        resp = api_client.review_document(doc["id"], {"decision": "REJECTED"},
                                          MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSignerGating:

    def test_signer_create_without_verified_card_rejected(self):
        """PRD section 3.2: "Adding an authorized signer — an officer-only
        action supplying `full_name`, `tax_id`, a `signer_role` of `OWNER`,
        `AUTHORIZED_SIGNER`, `POWER_OF_ATTORNEY`, `TRUSTEE`, or
        `BUSINESS_OFFICER`, and a `signature_card_reference` — requires that
        the reference equal the `reference_number` of a `VERIFIED`
        `SIGNATURE_CARD` document on the same account; without one the
        request fails with `ERR_DOCUMENTS_INCOMPLETE`."

        Design: Corner/validations/signer_create_without_verified_card_rejected
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="Sgn S", owner_tax_id="R6")
        submit_document(acct["id"], "SIGNATURE_CARD", "SC-UV")

        resp = api_client.add_signer(
            acct["id"],
            {"full_name": "Unv U", "tax_id": "TUV",
             "signer_role": "AUTHORIZED_SIGNER",
             "signature_card_reference": "SC-UV"},
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_DOCUMENTS_INCOMPLETE)

    def test_signer_remove_from_removed_rejected(self):
        """PRD section 3.2: "an `ACTIVE` signer can be removed while the
        account is not `CLOSED` — attempts against a closed account, or
        against a signer not currently `ACTIVE` or `SUSPENDED`, fail with
        `ERR_INVALID_STATE` — and a `SUSPENDED` signer can be removed as
        well; either way a manual removal stamps `removed_reason` with
        `STAFF_REQUEST`."
        PRD section 3.2: "`REMOVED` is terminal, and `removed_reason` stays
        null until then."

        Design: Corner/state_machines/signer_remove_from_removed_rejected
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="Rem R", owner_tax_id="C10")
        signer = add_active_signer(acct["id"], reference_number="SC-R",
                                   full_name="Sig R", tax_id="TSR")

        removed = validate_success(
            api_client.remove_signer(signer["id"], OFFICER),
            expected_status=200,
        )
        assert removed["status"] == "REMOVED"
        assert removed["removed_reason"] == "STAFF_REQUEST"

        resp = api_client.remove_signer(signer["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDocumentReferenceUniqueness:

    def test_err_duplicate_document_reference(self):
        """PRD section 3.2: "The reference is unique per account across all
        statuses: reusing a reference already on file, even one belonging to
        a previously rejected document, is rejected with
        `ERR_DUPLICATE_REFERENCE`."

        Design: Corner/errors/err_duplicate_document_reference
        """
        acct_a = open_account(opening_deposit_cents=5000,
                              primary_owner_name="Dup A", owner_tax_id="E3")
        acct_b = open_account(opening_deposit_cents=5000,
                              primary_owner_name="Dup B", owner_tax_id="E4")
        submit_document(acct_a["id"], "SIGNATURE_CARD", "SC-DUP")

        resp_dup = api_client.submit_document(
            acct_a["id"],
            {"doc_type": "SIGNATURE_CARD", "reference_number": "SC-DUP"},
            OFFICER,
        )
        validate_error(resp_dup, ApiErrorId.ERR_DUPLICATE_REFERENCE)

        # The same reference on a different account is accepted.
        other = validate_success(
            api_client.submit_document(
                acct_b["id"],
                {"doc_type": "SIGNATURE_CARD", "reference_number": "SC-DUP"},
                OFFICER,
            ),
            expected_status=201,
        )
        assert other["status"] == "SUBMITTED"


class TestTitleChangeFiling:

    def test_err_active_request_exists_second_title_change(self):
        """PRD section 3.3: "An account tolerates at most one `SUBMITTED`
        title change at a time — a second filing while one is in flight
        fails with `ERR_ACTIVE_REQUEST_EXISTS`."

        Design: Corner/errors/err_active_request_exists_second_title_change
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="Dup D", owner_tax_id="E2")
        req = file_title_change(acct["id"], "JOINT", acct["version"])
        assert req["status"] == "SUBMITTED"

        fresh = get_account(acct["id"])
        resp = api_client.file_title_change(
            acct["id"],
            title_change_payload("TRUST", fresh["version"]),
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_REQUEST_EXISTS)

    def test_err_stale_version_on_title_change_create(self):
        """PRD section 3.3: "Because retitling rewrites legal ownership,
        filing is optimistic-concurrency guarded per §2.11: the request must
        carry `expected_account_version` equal to the account's current
        `version`, and a mismatch rejects the filing with
        `ERR_STALE_VERSION` (HTTP 412), forcing the officer to re-read the
        account before proceeding."

        Design: Corner/errors/err_stale_version_on_title_change_create
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="Occ O", owner_tax_id="E7")
        stale_version = acct["version"]
        # An intervening deposit advances the account version.
        validate_success(
            api_client.post_transaction(
                acct["id"],
                {"txn_type": "DEPOSIT", "amount_cents": 100,
                 "customer_initiated": True},
                OFFICER,
            ),
            expected_status=201,
        )

        resp = api_client.file_title_change(
            acct["id"],
            title_change_payload("JOINT", stale_version),
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestTitleApprovalDocumentGate:

    def test_title_approve_without_verified_docs_rejected(self):
        """PRD section 3.3: "The server derives `required_doc_types` from
        the requested type: a `POD` target demands a `POD_DESIGNATION`; a
        `TRUST` target a `TRUST_AGREEMENT`; a `BUSINESS` target both a
        `BUSINESS_RESOLUTION` and a `SIGNATURE_CARD`; and `INDIVIDUAL` and
        `JOINT` targets each demand a `SIGNATURE_CARD`."
        PRD section 3.3: "every document type in `required_doc_types` must
        have a `VERIFIED` document on the account
        (`ERR_DOCUMENTS_INCOMPLETE` otherwise)".

        Design: Difficulty/cross_entity_state_dependency/title_approval_gated_on_document_verification
        """
        acct = open_account(opening_deposit_cents=50000,
                            primary_owner_name="Tru T", owner_tax_id="T16")
        req = file_title_change(acct["id"], "TRUST", acct["version"],
                                headers=OFFICER_1)
        assert_title_change_request(req)
        assert req["required_doc_types"] == ["TRUST_AGREEMENT"], (
            f"TRUST target must demand a TRUST_AGREEMENT, got "
            f"{req['required_doc_types']}"
        )

        resp = api_client.approve_title_change(req["id"], MANAGER_2)
        validate_error(resp, ApiErrorId.ERR_DOCUMENTS_INCOMPLETE)

    def test_title_approve_after_document_verification_succeeds(self):
        """PRD section 3.3: "Approval applies the new title: the account's
        `ownership_type` becomes the requested type, `pod_beneficiary_name`
        is updated when the requested type is `POD`, the deciding manager is
        recorded in `decided_by_user_id`, and the account's `version`
        increments."

        Design: Difficulty/cross_entity_state_dependency/title_approval_gated_on_document_verification
        """
        acct = open_account(opening_deposit_cents=50000,
                            primary_owner_name="Tru T", owner_tax_id="T16")
        req = file_title_change(acct["id"], "TRUST", acct["version"],
                                headers=OFFICER_1)
        add_verified_document(acct["id"], "TRUST_AGREEMENT", "TA-1")

        approved = validate_success(
            api_client.approve_title_change(req["id"], MANAGER_2),
            expected_status=200,
        )
        assert approved["status"] == "APPROVED"

        acct_after = get_account(acct["id"])
        assert acct_after["ownership_type"] == "TRUST"


class TestTitleRejectResubmitCycle:

    def test_title_reject_stores_reason_resubmit_clears_it(self):
        """PRD section 3.3: "A manager rejects a `SUBMITTED` request — any
        other status fails with `ERR_INVALID_STATE` — by supplying a
        `reason`, stored verbatim in `decision_reason` alongside the
        manager's identity in `decided_by_user_id`."
        PRD section 3.3: "Resubmission returns the request to `SUBMITTED`,
        recomputes `required_doc_types`, and clears `decision_reason` and
        `decided_by_user_id` — the reject-and-resubmit loop may repeat any
        number of times."

        Design: Difficulty/non_linear_state_machine/title_change_reject_resubmit_cycle
        """
        acct = open_account(opening_deposit_cents=50000,
                            primary_owner_name="Tit T", owner_tax_id="T9")
        req = file_title_change(acct["id"], "POD", acct["version"],
                                pod_beneficiary_name="Bene A",
                                headers=OFFICER_1)

        rejected = validate_success(
            api_client.reject_title_change(
                req["id"], {"reason": "missing pod designation"}, MANAGER),
            expected_status=200,
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["decision_reason"] == "missing pod designation"

        resubmitted = validate_success(
            api_client.resubmit_title_change(req["id"], OFFICER),
            expected_status=200,
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["decision_reason"] is None, (
            f"resubmission must clear decision_reason, got "
            f"{resubmitted['decision_reason']}"
        )
        assert resubmitted["decided_by_user_id"] is None

    def test_title_resubmit_then_approve_applies_new_ownership(self):
        """PRD section 3.3: "Approval applies the new title: the account's
        `ownership_type` becomes the requested type, `pod_beneficiary_name`
        is updated when the requested type is `POD`, the deciding manager is
        recorded in `decided_by_user_id`, and the account's `version`
        increments. `APPROVED` is terminal."

        Design: Difficulty/non_linear_state_machine/title_change_reject_resubmit_cycle
        """
        acct = open_account(opening_deposit_cents=50000,
                            primary_owner_name="Tit T", owner_tax_id="T9")
        req = file_title_change(acct["id"], "POD", acct["version"],
                                pod_beneficiary_name="Bene A",
                                headers=OFFICER_1)
        validate_success(
            api_client.reject_title_change(
                req["id"], {"reason": "missing pod designation"}, MANAGER),
            expected_status=200,
        )
        validate_success(api_client.resubmit_title_change(req["id"], OFFICER),
                         expected_status=200)
        add_verified_document(acct["id"], "POD_DESIGNATION", "POD-1")

        approved = validate_success(
            api_client.approve_title_change(req["id"], MANAGER_2),
            expected_status=200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == "u-mgr-2"

        acct_after = get_account(acct["id"])
        assert acct_after["ownership_type"] == "POD"
        assert acct_after["pod_beneficiary_name"] == "Bene A"
