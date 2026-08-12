"""Registry filings (reject/resubmit cycle, parallel verification dimension,
DEREGISTRATION lien gate) and closing-document signature logistics
(PRD §3.8, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_filing,
    complete_title_search,
    create_document_payload,
    create_filing,
    create_sent_document,
    get_aircraft,
    get_escrow_file,
    get_filing,
    lien_by_amount,
    make_finding,
    order_title_search,
    set_clock,
    setup_accepted_filing,
    setup_cleared_file,
    setup_closed_file,
    setup_funded_file,
    sign_document,
    submit_filing,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]

HIGH_PRICE_OVERRIDES = {
    "purchase_price_cents": 250_000_000,
    "annual_registration_fee_cents": 120_000,
}


class TestFilingRejectResubmitCycle:
    def _setup_submitted_bill_of_sale(self, api, n_number="N300FN"):
        ctx = setup_closed_file(file_overrides=dict(HIGH_PRICE_OVERRIDES))
        filing = create_filing(ctx["file"]["id"], "BILL_OF_SALE")
        submitted = submit_filing(filing["id"])
        assert submitted["status"] == "SUBMITTED"
        ctx["filing"] = submitted
        return ctx

    def test_reject_resubmit_cycle_then_accept_arms_verification(self, api):
        """PRD §3.9: "Rejection is recorded by an `EscrowOfficer` presenting a
        `reason`; the filing transitions from `SUBMITTED` to `REJECTED` and
        `reject_reason` is stored."
        PRD §3.9: "Resubmission re-evaluates the same prerequisite chain at
        resubmit time — so a filing whose prerequisite was accepted while it sat
        in `REJECTED` may now go through — and on success it refreshes
        `submitted_at`, reassigns `sequence_index`, clears `reject_reason`, and
        returns the filing to `SUBMITTED`."
        PRD §3.9: "The filing transitions from `SUBMITTED` to `ACCEPTED`,
        `registry_confirmation_code` is stored, and `verification_status` moves
        from `NONE` to `PENDING`."

        Design: Difficulty/non_linear_state_machine/n1_filing_reject_resubmit_cycle_with_parallel_verification
        """
        ctx = self._setup_submitted_bill_of_sale(api)
        filing_id = ctx["filing"]["id"]

        rejected = validate_success(
            api.reject_filing(filing_id, {"reason": "illegible notary seal"}, OFFICER),
            200,
        )
        assert rejected["status"] == "REJECTED"

        resubmitted = validate_success(api.resubmit_filing(filing_id, OFFICER), 200)
        assert resubmitted["status"] == "SUBMITTED"

        accepted = validate_success(
            api.accept_filing(filing_id, {"confirmation_code": "FAA-C-1"}, OFFICER), 200
        )
        assert_filing(accepted)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["verification_status"] == "PENDING"

    def test_verification_flips_independently_of_lifecycle_status(self, api):
        """PRD §3.9: "If it equals the filing's stored `registry_confirmation_code`,
        `verification_status` moves to `MATCHED`; otherwise it moves to
        `MISMATCHED`."
        PRD §3.9: "Verification is permitted from `PENDING` and again from
        `MISMATCHED`, so a mismatched filing can be re-verified once the
        underlying discrepancy is reconciled."

        The lifecycle status stays ACCEPTED while verification flips
        PENDING -> MISMATCHED -> MATCHED.

        Design: Difficulty/non_linear_state_machine/n1_filing_reject_resubmit_cycle_with_parallel_verification
        """
        ctx = self._setup_submitted_bill_of_sale(api)
        filing_id = ctx["filing"]["id"]
        validate_success(
            api.accept_filing(filing_id, {"confirmation_code": "FAA-C-1"}, OFFICER), 200
        )

        mismatched = validate_success(
            api.verify_filing(filing_id, {"recorded_confirmation_code": "FAA-C-999"},
                              OFFICER),
            200,
        )
        assert mismatched["verification_status"] == "MISMATCHED"
        assert mismatched["status"] == "ACCEPTED"

        matched = validate_success(
            api.verify_filing(filing_id, {"recorded_confirmation_code": "FAA-C-1"},
                              OFFICER),
            200,
        )
        assert matched["verification_status"] == "MATCHED"
        assert matched["status"] == "ACCEPTED"


class TestDeregistrationLienGate:
    def _setup_dereg_blocked_by_lien(self, api):
        """CLOSED file with BILL_OF_SALE ACCEPTED, then a post-close re-search
        surfaces one DISCOVERED lien; a DEREGISTRATION filing sits QUEUED."""
        ctx = setup_closed_file(with_lender=True,
                                file_overrides=dict(HIGH_PRICE_OVERRIDES))
        file_id = ctx["file"]["id"]
        setup_accepted_filing(file_id, "BILL_OF_SALE", "FAA-B-1")

        set_clock("2026-07-02T00:00:00Z")
        search = order_title_search(file_id)
        complete_title_search(search["id"], [
            make_finding(ctx["lender"]["id"], 75_000, lien_type="STATE",
                         filed_at="2026-06-15"),
        ])
        lien = lien_by_amount(file_id, 75_000)
        dereg = create_filing(file_id, "DEREGISTRATION")
        ctx["new_lien"] = lien
        ctx["dereg"] = dereg
        return ctx

    def test_dereg_submit_rejected_while_lien_discovered(self, api):
        """PRD §3.9: "A `DEREGISTRATION` requires the file's `BILL_OF_SALE` to be
        `ACCEPTED` — and additionally requires that every lien of the file be in
        `RELEASED` (otherwise the submit is rejected with `ERR_LIENS_OUTSTANDING`)
        and that the aircraft's `registry_status` currently be `REGISTERED`."

        The BILL_OF_SALE prerequisite is satisfied; only the lien gate fails.

        Design: Difficulty/cross_entity_state_dependency/x1_dereg_submit_requires_liens_released
        """
        ctx = self._setup_dereg_blocked_by_lien(api)
        assert ctx["new_lien"]["status"] == "DISCOVERED"
        res = api.submit_filing(ctx["dereg"]["id"], OFFICER)
        validate_error(res, ApiErrorId.ERR_LIENS_OUTSTANDING, expected_status=409)

    def test_failed_dereg_submit_leaves_filing_and_aircraft_untouched(self, api):
        """PRD §3.9: "A `DEREGISTRATION` requires the file's `BILL_OF_SALE` to be
        `ACCEPTED` — and additionally requires that every lien of the file be in
        `RELEASED` (otherwise the submit is rejected with `ERR_LIENS_OUTSTANDING`)
        and that the aircraft's `registry_status` currently be `REGISTERED`."
        PRD §3.1: "A newly registered aircraft begins life with `registry_status`
        set to `REGISTERED`."

        The rejected submit applies no transition: the filing stays QUEUED and the
        aircraft stays REGISTERED.

        Design: Difficulty/cross_entity_state_dependency/x1_dereg_submit_requires_liens_released
        """
        ctx = self._setup_dereg_blocked_by_lien(api)
        api.submit_filing(ctx["dereg"]["id"], OFFICER)

        dereg = get_filing(ctx["dereg"]["id"])
        assert dereg["status"] == "QUEUED"
        aircraft = get_aircraft(ctx["aircraft"]["id"])
        assert aircraft["registry_status"] == "REGISTERED"


class TestDocumentSignatures:
    def test_signature_progression_to_fully_signed(self, api):
        """PRD §3.8: "The first valid signature moves the document from
        `OUT_FOR_SIGNATURE` to `PARTIALLY_SIGNED` and appends the signer to
        `signed_party_ids`."
        PRD §3.8: "The signature that completes the required set — meaning that
        after appending, the `signed_party_ids` set equals the
        `required_signer_party_ids` set — moves the document from either
        `OUT_FOR_SIGNATURE` or `PARTIALLY_SIGNED` to `FULLY_SIGNED`."

        Design: Corner/state_machines/s_document_signature_progression
        """
        ctx = setup_cleared_file()
        doc = create_sent_document(ctx["file"]["id"], "PURCHASE_AGREEMENT",
                                   [ctx["buyer"]["id"], ctx["seller"]["id"]])

        first = sign_document(doc["id"], ctx["buyer"]["id"])
        assert first["status"] == "PARTIALLY_SIGNED"
        assert first["signed_party_ids"] == [ctx["buyer"]["id"]]

        second = sign_document(doc["id"], ctx["seller"]["id"])
        assert second["status"] == "FULLY_SIGNED"
        assert sorted(second["signed_party_ids"]) == sorted(
            [ctx["buyer"]["id"], ctx["seller"]["id"]]
        )

    def test_duplicate_signature_rejected(self, api):
        """PRD §3.8: "The signer must be a member of `required_signer_party_ids`
        — a signer outside the required set is rejected with
        `ERR_SIGNER_NOT_REQUIRED` — and must not already appear in
        `signed_party_ids`, since duplicates are rejected with
        `ERR_ALREADY_SIGNED`."
        PRD §3.8: "`FULLY_SIGNED` is terminal."

        With a one-signer required set the first signature lands the document in
        terminal FULLY_SIGNED, so the duplicate attempt trips both the duplicate
        rule and the terminal-state gate; PRD names both rules but never pins
        their precedence, so either ERR_ALREADY_SIGNED or ERR_INVALID_TRANSITION
        is acceptable (both 409).

        Design: Corner/errors/er_already_signed_rejected
        """
        ctx = setup_cleared_file()
        doc = create_sent_document(ctx["file"]["id"], "WIRE_AUTHORIZATION",
                                   [ctx["buyer"]["id"]])
        signed = sign_document(doc["id"], ctx["buyer"]["id"])
        assert signed["status"] == "FULLY_SIGNED"

        res = api.sign_document(doc["id"], {"signer_party_id": ctx["buyer"]["id"]},
                                OFFICER)
        validate_error_is_one_of(
            res,
            [ApiErrorId.ERR_ALREADY_SIGNED.value, ApiErrorId.ERR_INVALID_TRANSITION.value],
        )
        assert res.status_code == 409

    def test_signer_not_in_required_set_rejected(self, api):
        """PRD §3.8: "The signer must be a member of `required_signer_party_ids`
        — a signer outside the required set is rejected with
        `ERR_SIGNER_NOT_REQUIRED` — and must not already appear in
        `signed_party_ids`, since duplicates are rejected with
        `ERR_ALREADY_SIGNED`."

        The seller is a party on the file but not a required signer here.

        Design: Corner/errors/er_signer_not_required_rejected
        """
        ctx = setup_cleared_file()
        doc = create_sent_document(ctx["file"]["id"], "ESCROW_INSTRUCTIONS",
                                   [ctx["buyer"]["id"]])
        res = api.sign_document(doc["id"], {"signer_party_id": ctx["seller"]["id"]},
                                OFFICER)
        validate_error(res, ApiErrorId.ERR_SIGNER_NOT_REQUIRED, expected_status=422)

        after = validate_success(
            api.list_documents(ctx["file"]["id"], OFFICER), 200
        )
        assert after[0]["status"] == "OUT_FOR_SIGNATURE"
        assert after[0]["signed_party_ids"] == []

    def test_required_signer_who_is_not_a_file_party_rejected(self, api):
        """PRD §3.8: "Every entry in `required_signer_party_ids` must be one of
        the file's named parties — the buyer, the seller, the lender if present,
        or the trustee if present; an entry that is not is rejected with
        `ERR_SIGNER_NOT_PARTY`."

        Design: Corner/errors/er_signer_not_party_rejected
        """
        from test_helpers import create_party

        ctx = setup_cleared_file()
        outsider = create_party("LENDER", "Outsider Bank")
        payload = create_document_payload(
            "CLOSING_STATEMENT", [ctx["buyer"]["id"], outsider["id"]],
        )
        res = api.create_document(ctx["file"]["id"], payload, OFFICER)
        validate_error(res, ApiErrorId.ERR_SIGNER_NOT_PARTY, expected_status=422)
        data, meta = validate_paginated(
            api.list_documents(ctx["file"]["id"], OFFICER)
        )
        assert meta["total_count"] == 0
