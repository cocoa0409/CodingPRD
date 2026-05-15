"""Declaration creation, document intake, declared-value review, and
pre-validation tests (PRD §3.3, §3.4, §3.5)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_declaration,
    assert_shipment_document,
    attach_core_docs,
    attach_document,
    attach_document_payload,
    create_agreement,
    create_client,
    create_declaration,
    create_declaration_payload,
    iso_utc,
    pre_validate_declaration,
    request_documents,
    request_signature,
    reset_clock_to_epoch,
    setup_active_agreement,
    setup_declaration_in_docs_pending,
    setup_declaration_in_pre_validated,
    sign_agreement,
    update_declaration_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.3 — Declaration creation gating
# ===========================================================================
class TestDeclarationCreation:

    def test_create_declaration_initial_state_draft(self, api):
        """PRD §3.3: "A newly created declaration is in DRAFT status, with
        declared_value_review_status initialised to PENDING, amendment_count
        initialised to zero".

        Claim: POST /customs/declarations → status=DRAFT, amendment_count=0.
        """
        _, agreement = setup_active_agreement()
        dec = create_declaration(agreement["id"])
        assert dec["status"] == "DRAFT"
        assert dec["amendment_count"] == 0
        assert_declaration(dec)

    def test_create_declaration_under_draft_agreement_rejected(
        self, api, declaration_officer_headers,
    ):
        """PRD §3.3: "The parent agreement must be in ACTIVE status with
        the current instant in the inclusive-exclusive range from
        valid_from to valid_until — otherwise the request is rejected
        with ERR_AGREEMENT_NOT_ACTIVE and HTTP 409."

        Claim: agreement_id pointing at DRAFT agreement → ERR_AGREEMENT_NOT_ACTIVE.
        """
        client = create_client()
        agreement = create_agreement(client["id"])  # remains DRAFT
        resp = api.create_declaration(
            create_declaration_payload(agreement_id=agreement["id"]),
            declaration_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)

    def test_create_declaration_outside_validity_window_rejected(
        self, api, declaration_officer_headers,
    ):
        """PRD §3.3: "The parent agreement must be in ACTIVE status with
        the current instant in the inclusive-exclusive range from
        valid_from to valid_until — otherwise the request is rejected
        with ERR_AGREEMENT_NOT_ACTIVE and HTTP 409."

        Claim: clock past valid_until → ERR_AGREEMENT_NOT_ACTIVE.
        """
        reset_clock_to_epoch()
        _, agreement = setup_active_agreement(
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            valid_until=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        # Advance past valid_until
        advance_clock_to(datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc))
        resp = api.create_declaration(
            create_declaration_payload(agreement_id=agreement["id"]),
            declaration_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)

    def test_create_declaration_without_declaration_in_scope_rejected(
        self, api, declaration_officer_headers,
    ):
        """PRD §3.3: "The string DECLARATION must also appear in the
        agreement's scope_of_service; otherwise the create returns
        ERR_SERVICE_OUT_OF_SCOPE."

        Claim: agreement.scope_of_service omits DECLARATION →
        ERR_SERVICE_OUT_OF_SCOPE.
        """
        _, agreement = setup_active_agreement(
            scope_of_service=["INSPECTION"],
            fee_schedule={"INSPECTION": 50},
        )
        resp = api.create_declaration(
            create_declaration_payload(agreement_id=agreement["id"]),
            declaration_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SERVICE_OUT_OF_SCOPE.value)

    def test_declaration_default_trade_agreement_code_is_none(self, api):
        """PRD §3.3: "an optional trade_agreement_code from the set NONE,
        RCEP, USMCA, EU_GSP, or CPTPP (defaulting to NONE, which means
        the most-favoured-nation general tariff applies)".

        Claim: omitting trade_agreement_code → server stores NONE.
        """
        _, agreement = setup_active_agreement()
        dec = create_declaration(agreement["id"], trade_agreement_code=None)
        assert dec["trade_agreement_code"] == "NONE"


# ===========================================================================
# §3.3 — Declared-value review heuristic
# ===========================================================================
class TestDeclaredValueReview:

    def test_no_reference_data_passes_review(self, api):
        """PRD §3.3: "if no reference exists for the pair,
        declared_value_review_status is set to ACCEPTED."

        Claim: HS prefix without reference table entry → ACCEPTED.
        """
        _, agreement = setup_active_agreement()
        dec = create_declaration(
            agreement["id"],
            jurisdiction_code="CN", hs_code="73089090",  # not in ref table
            declared_value_amount=99999.99, declared_currency="USD",
        )
        assert dec["declared_value_review_status"] == "ACCEPTED"

    def test_deviation_within_threshold_accepted(self, api):
        """PRD §3.3: "the server computes the absolute difference between
        the rounded base value and the reference, divides by the reference
        to obtain a deviation ratio, and sets declared_value_review_status
        to ACCEPTED when the deviation is at most twenty-five percent".

        Claim: deviation 10% (within 25%) → ACCEPTED.
        """
        _, agreement = setup_active_agreement(default_settlement_currency="CNY")
        # CNY settlement; (CN, 8517) ref = 800.00 CNY. With fx not yet pinned
        # (DRAFT state), the PRD uses fx_rate_to_settlement = 1.0. So a CNY
        # declared value of 880 produces deviation = |880-800|/800 = 10%.
        dec = create_declaration(
            agreement["id"], jurisdiction_code="CN", hs_code="85171200",
            declared_value_amount=880.00, declared_currency="CNY",
        )
        assert dec["declared_value_review_status"] == "ACCEPTED"

    def test_deviation_exceeds_threshold_flagged(self, api):
        """PRD §3.3: "and to FLAGGED when the deviation exceeds twenty-five
        percent. The boundary at exactly twenty-five percent resolves to
        ACCEPTED."

        Claim: declared value far above reference (>25% deviation) → FLAGGED.
        """
        _, agreement = setup_active_agreement(default_settlement_currency="CNY")
        dec = create_declaration(
            agreement["id"], jurisdiction_code="CN", hs_code="85171200",
            declared_value_amount=2000.00, declared_currency="CNY",
        )
        # |2000 - 800|/800 = 1.5 → 150% deviation → FLAGGED.
        assert dec["declared_value_review_status"] == "FLAGGED"

    def test_deviation_boundary_at_25pct_accepted(self, api):
        """PRD §3.3: "The boundary at exactly twenty-five percent resolves
        to ACCEPTED."

        Claim: base_value = 1000.00 vs ref 800 → 25% exactly → ACCEPTED.
        """
        _, agreement = setup_active_agreement(default_settlement_currency="CNY")
        dec = create_declaration(
            agreement["id"], jurisdiction_code="CN", hs_code="85171200",
            declared_value_amount=1000.00, declared_currency="CNY",
        )
        assert dec["declared_value_review_status"] == "ACCEPTED"


# ===========================================================================
# §3.4 — request-documents stubs missing core docs
# ===========================================================================
class TestRequestDocuments:

    def test_request_documents_advances_to_docs_pending(self, api):
        """PRD §3.4: "When the operator is ready to gather supporting
        paperwork, a DeclarationOfficer invokes the request-documents
        action, which advances the declaration from DRAFT to DOCS_PENDING."

        Claim: status advances DRAFT → DOCS_PENDING.
        """
        ctx = setup_declaration_in_docs_pending()
        assert ctx["declaration"]["status"] == "DOCS_PENDING"


# ===========================================================================
# §3.4 — Document authenticity scoring
# ===========================================================================
class TestAuthenticityScoring:

    def test_authenticity_score_at_threshold_is_accepted(self, api):
        """PRD §3.4: "a score of at least 0.70 yields authenticity_status
        of ACCEPTED, a score strictly below 0.70 yields FLAGGED, and the
        boundary value 0.70 itself resolves to ACCEPTED."

        Claim: a doc that scores exactly 0.70 → ACCEPTED.
        Recipe: total_match=0 (no sibling yet) + currency_consistent=1 (0.3)
        + uri_format=1 (0.2) = 0.5. To hit 0.70 we need total_match=1; we
        add a packing list first, then attach an invoice — total match
        signal contributes 0.5; currency_consistent=1 (0.3); uri=1 (0.2)
        → 1.0. Test the boundary at lower scenario: simulate FLAGGED
        case where currency_consistent=0 + uri=0.5 + total_match=1.0:
        0.5 + 0 + 0.1 = 0.6 → FLAGGED. For the precise 0.70 boundary, we
        use total_match=1.0 + currency_consistent=0 + uri=1.0:
        0.5 + 0 + 0.2 = 0.7 → ACCEPTED.
        """
        ctx = setup_declaration_in_docs_pending()
        dec_id = ctx["declaration"]["id"]
        # PRD §3.3: declared_currency was USD by default.
        # Attach packing list first (USD total).
        attach_document(
            dec_id, doc_type="PACKING_LIST",
            declared_total_value=1000.00, declared_total_currency="USD",
        )
        # Now attach invoice with matching total_value but a DIFFERENT
        # declared_total_currency (so currency_consistent=0) and a clean
        # storage_uri (uri_format=1.0).
        invoice = attach_document(
            dec_id, doc_type="COMMERCIAL_INVOICE",
            declared_total_value=1000.00, declared_total_currency="CNY",
            storage_uri="https://docs/invoice.pdf",
        )
        # total_match=1.0(0.5) + currency_consistent=0(0) + uri=1.0(0.2) = 0.70
        assert invoice["authenticity_score"] == pytest.approx(0.70, abs=0.005), (
            f"Expected exactly 0.70, got {invoice['authenticity_score']}"
        )
        assert invoice["authenticity_status"] == "ACCEPTED"

    def test_authenticity_score_below_threshold_flagged(self, api):
        """PRD §3.4: "a score strictly below 0.70 yields FLAGGED".

        Claim: total_match=0 + currency_consistent=0 + uri_format=0.5 (no
        scheme://) → 0.0 + 0.0 + 0.1 = 0.10 → FLAGGED.
        """
        ctx = setup_declaration_in_docs_pending()
        dec_id = ctx["declaration"]["id"]
        doc = attach_document(
            dec_id, doc_type="COMMERCIAL_INVOICE",
            declared_total_value=1000.00, declared_total_currency="EUR",
            storage_uri="no-scheme-just-text",  # fails s+://. pattern
        )
        assert doc["authenticity_score"] < 0.70
        assert doc["authenticity_status"] == "FLAGGED"


# ===========================================================================
# §3.5 — Pre-validate cross-cutting checks
# ===========================================================================
class TestPreValidateGates:

    def test_pre_validate_succeeds_when_all_four_core_docs_present_consistent(
        self, api,
    ):
        """PRD §3.5: "the four core documents — COMMERCIAL_INVOICE,
        PACKING_LIST, BILL_OF_LADING, and CONTRACT — must all exist for
        the declaration, or the transition is rejected with
        ERR_DOC_INCOMPLETE."

        Claim: when all four core docs are attached with consistent
        totals, /pre-validate succeeds and state advances to PRE_VALIDATED.
        """
        ctx = setup_declaration_in_pre_validated(
            invoice_total=1000.00, invoice_currency="USD",
        )
        assert ctx["declaration"]["status"] == "PRE_VALIDATED"

    def test_pre_validate_authenticity_flagged_blocks_transition(self, api):
        """PRD §3.5: "no ShipmentDocument under the declaration may have
        authenticity_status of FLAGGED — any flagged document blocks the
        transition with ERR_DOC_AUTHENTICITY_FLAGGED."

        Claim: a FLAGGED ShipmentDocument under the declaration causes
        pre-validate to return ERR_DOC_AUTHENTICITY_FLAGGED.
        """
        from test_helpers import TEST_USERS
        ctx = setup_declaration_in_docs_pending()
        dec = ctx["declaration"]
        # Attach 4 core docs but make one FLAGGED via bad signals.
        attach_document(dec["id"], doc_type="COMMERCIAL_INVOICE",
                        declared_total_value=1000.0, declared_total_currency="EUR",
                        storage_uri="raw-text-no-scheme")
        attach_document(dec["id"], doc_type="PACKING_LIST",
                        declared_total_value=1000.0, declared_total_currency="USD")
        attach_document(dec["id"], doc_type="BILL_OF_LADING")
        attach_document(dec["id"], doc_type="CONTRACT")
        resp = api.pre_validate_declaration(
            dec["id"], {"version": dec["version"]},
            TEST_USERS["doc_reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DOC_AUTHENTICITY_FLAGGED.value)

    def test_pre_validate_missing_dangerous_goods_decl_rejected(self, api):
        """PRD §3.5: "when hs_code starts with 2208, 2402, or 2710, a
        DANGEROUS_GOODS_DECL document must exist, or the transition is
        rejected with ERR_DOC_MISSING_DG".

        Claim: HS=2208xxxx with all four core docs but no DG decl →
        ERR_DOC_MISSING_DG.
        """
        from test_helpers import TEST_USERS
        ctx = setup_declaration_in_docs_pending(hs_code="22080000",
                                                jurisdiction_code="CN")
        dec = ctx["declaration"]
        attach_core_docs(dec["id"], invoice_total=200.0, invoice_currency="USD")
        # Refresh
        from test_helpers import api_client
        dec = validate_success(api_client.get_declaration(
            dec["id"], TEST_USERS["declaration_officer_headers"],
        ))
        resp = api.pre_validate_declaration(
            dec["id"], {"version": dec["version"]},
            TEST_USERS["doc_reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DOC_MISSING_DG.value)

    def test_pre_validate_success_pins_agreement_version(self, api):
        """PRD §3.5: "The third snapshots pinned_agreement_version to the
        parent agreement's current version, which becomes the drift
        sentinel at file time."

        Claim: post-pre-validate, pinned_agreement_version equals the
        parent agreement's current version.
        """
        ctx = setup_declaration_in_pre_validated()
        agreement = ctx["agreement"]
        dec = ctx["declaration"]
        assert dec.get("pinned_agreement_version") == agreement["version"], (
            f"pinned_agreement_version={dec.get('pinned_agreement_version')} "
            f"but agreement.version={agreement['version']}"
        )

    def test_pre_validate_success_sets_fx_rate(self, api):
        """PRD §3.5: "The first computes the snapshot fx_rate_to_settlement
        from the declared currency to the agreement client's settlement
        currency (1.0 when the two currencies match)."

        Claim: declared=USD, settlement=USD → fx_rate_to_settlement=1.0.
        """
        ctx = setup_declaration_in_pre_validated(
            default_settlement_currency="USD",
            declared_currency="USD",
        )
        assert ctx["declaration"].get("fx_rate_to_settlement") == 1.0
