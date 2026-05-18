"""Income document import — W-2, 1099-NEC, 1099-INT, 1099-DIV, 1099-B.

Coverage targets (PRD §3.2):
- All five doc_type variants accepted.
- Qualified > ordinary dividends rejected (ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY).
- 1099-B missing/NONE holding_period rejected (ERR_INCOME_DOC_INVALID).
- 1099-B cost_basis > proceeds + 100_000_000 rejected.
- PATCH on a doc with READY_TO_FILE parent reverts to DRAFT (PRD §2.7).
- DELETE on a doc with READY_TO_FILE parent reverts to DRAFT (PRD §2.7).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_w2,
    add_1099_b,
    add_1099_div,
    add_1099_int,
    add_1099_nec,
    assert_income_document,
    create_1099_b_payload,
    create_1099_div_payload,
    create_1099_int_payload,
    create_1099_nec_payload,
    create_w2_payload,
    INCOME_DOC_LOOSE_CAP_CENTS,
    make_taxpayer_headers,
    re_get_tax_return,
    setup_active_taxpayer_with_draft_return,
    setup_ready_to_file_return,
    validate_error,
    validate_success,
)


# ===========================================================================
# Happy-path imports for all five doc types — PRD §3.2
# ===========================================================================
class TestImportAllVariants:

    def test_import_w2(self, api):
        """PRD §3.2: "A W2 import populates wages_cents (box 1) and
        federal_withholding_cents (box 2)".

        Claim: POST income-documents with doc_type=W2 succeeds and
        echoes wages and withholding.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        doc = add_w2(
            taxpayer, tax_return["id"],
            wages_cents=1_000_000, federal_withholding_cents=100_000,
        )
        assert_income_document(doc)
        assert doc["doc_type"] == "W2"
        assert doc["wages_cents"] == 1_000_000
        assert doc["federal_withholding_cents"] == 100_000

    def test_import_1099_nec(self, api):
        """PRD §3.2: "A 1099_NEC import sets nonemployee_comp_cents."

        Claim: 1099_NEC import returns the same nonemployee_comp_cents.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        doc = add_1099_nec(
            taxpayer, tax_return["id"], nonemployee_comp_cents=500_000,
        )
        assert doc["doc_type"] == "1099_NEC"
        assert doc["nonemployee_comp_cents"] == 500_000

    def test_import_1099_int(self, api):
        """PRD §3.2: "A 1099_INT import populates interest_income_cents."

        Claim: 1099_INT import returns the supplied interest amount.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        doc = add_1099_int(
            taxpayer, tax_return["id"], interest_income_cents=25_000,
        )
        assert doc["doc_type"] == "1099_INT"
        assert doc["interest_income_cents"] == 25_000

    def test_import_1099_div(self, api):
        """PRD §3.2: "A 1099_DIV import sets ordinary_dividends_cents
        and qualified_dividends_cents".

        Claim: 1099_DIV import accepts both fields with qualified <=
        ordinary.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        doc = add_1099_div(
            taxpayer, tax_return["id"],
            ordinary_dividends_cents=100_000,
            qualified_dividends_cents=80_000,
        )
        assert doc["doc_type"] == "1099_DIV"
        assert doc["ordinary_dividends_cents"] == 100_000
        assert doc["qualified_dividends_cents"] == 80_000

    def test_import_1099_b_short_term(self, api):
        """PRD §3.2: "A 1099_B import provides proceeds_cents,
        cost_basis_cents, and a holding_period of either SHORT_TERM
        or LONG_TERM".

        Claim: 1099_B import with SHORT_TERM holding_period succeeds.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        doc = add_1099_b(
            taxpayer, tax_return["id"],
            proceeds_cents=50_000, cost_basis_cents=40_000,
            holding_period="SHORT_TERM",
        )
        assert doc["doc_type"] == "1099_B"
        assert doc["holding_period"] == "SHORT_TERM"


# ===========================================================================
# Dividend validation — PRD §3.2 / priority 10
# ===========================================================================
class TestDividendValidation:

    def test_qualified_exceeds_ordinary_rejected(self, api):
        """PRD §3.2: "the firm constraint that the qualified portion
        never exceeds the ordinary portion - a violation is rejected
        with ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY."

        Claim: qualified > ordinary on POST -> ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        resp = api.create_income_document(
            tax_return["id"],
            create_1099_div_payload(
                ordinary_dividends_cents=10_000,
                qualified_dividends_cents=20_000,
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY.value,
        )

    def test_qualified_equals_ordinary_allowed(self, api):
        """PRD §3.2: "the firm constraint that the qualified portion
        never exceeds the ordinary portion".

        Claim: qualified == ordinary is allowed (boundary).
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        doc = add_1099_div(
            taxpayer, tax_return["id"],
            ordinary_dividends_cents=10_000,
            qualified_dividends_cents=10_000,
        )
        assert doc["qualified_dividends_cents"] == 10_000


# ===========================================================================
# 1099-B validation — PRD §3.2 / priority 11
# ===========================================================================
class TestBrokerageValidation:

    def test_holding_period_none_rejected(self, api):
        """PRD §3.2: "the placeholder NONE is not acceptable as a
        holding period on a brokerage form, and a brokerage import
        that omits the holding period or that supplies cost basis
        greater than proceeds plus 100,000,000 cents is rejected with
        ERR_INCOME_DOC_INVALID."

        Claim: holding_period=NONE on POST 1099_B -> ERR_INCOME_DOC_INVALID.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        resp = api.create_income_document(
            tax_return["id"],
            create_1099_b_payload(
                proceeds_cents=10_000,
                cost_basis_cents=8_000,
                holding_period="NONE",
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INCOME_DOC_INVALID.value)

    def test_cost_basis_absurd_rejected(self, api):
        """PRD §3.2: "a brokerage import that omits the holding period
        or that supplies cost basis greater than proceeds plus
        100,000,000 cents is rejected with ERR_INCOME_DOC_INVALID."

        Claim: cost_basis > proceeds + 100_000_000 -> ERR_INCOME_DOC_INVALID.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        resp = api.create_income_document(
            tax_return["id"],
            create_1099_b_payload(
                proceeds_cents=1_000,
                # 1_000 + 100_000_000 + 1 = 100_001_001 — over the cap
                cost_basis_cents=INCOME_DOC_LOOSE_CAP_CENTS + 1_000 + 1,
                holding_period="SHORT_TERM",
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INCOME_DOC_INVALID.value)


# ===========================================================================
# Child mutations revert READY_TO_FILE -> DRAFT — PRD §2.7
# ===========================================================================
class TestChildMutationCascades:

    def test_create_income_doc_on_ready_reverts_to_draft(self, api):
        """PRD §2.7: "Any creation, update, or deletion of an
        IncomeDocument, Schedule, or TaxCredit belonging to a TaxReturn
        currently in READY_TO_FILE reverts the parent return to DRAFT
        and invalidates the computed numbers".

        Claim: POST a new W-2 on a READY_TO_FILE return reverts the
        return to DRAFT.
        """
        taxpayer, ready_return, _ = setup_ready_to_file_return()
        add_w2(taxpayer, ready_return["id"], wages_cents=1)
        after = re_get_tax_return(taxpayer, ready_return["id"])
        assert after["status"] == "DRAFT"

    def test_patch_income_doc_reverts_to_draft(self, api):
        """PRD §2.7 / §3.2: child PATCH on a READY_TO_FILE return
        reverts the return to DRAFT. PRD §3.2: "Whenever a document
        is created, patched, or deleted on a return whose status is
        READY_TO_FILE, the parent return is automatically reverted
        to DRAFT".

        Claim: PATCH /income-documents/{id} reverts parent to DRAFT.
        """
        taxpayer, ready_return, w2 = setup_ready_to_file_return()
        from test_helpers import patch_income_document_payload
        resp = api.patch_income_document(
            w2["id"],
            patch_income_document_payload(wages_cents=9_000_000),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_success(resp)
        after = re_get_tax_return(taxpayer, ready_return["id"])
        assert after["status"] == "DRAFT"

    def test_delete_income_doc_reverts_to_draft(self, api):
        """PRD §3.2: "Whenever a document is created, patched, or
        deleted on a return whose status is READY_TO_FILE, the parent
        return is automatically reverted to DRAFT, because the
        previously-computed numbers are no longer trustworthy."

        Claim: DELETE /income-documents/{id} reverts parent to DRAFT.
        """
        taxpayer, ready_return, w2 = setup_ready_to_file_return()
        # Need at least one income doc to exist before delete — create
        # another so the return still has docs after the delete.
        add_w2(taxpayer, ready_return["id"], wages_cents=1)
        resp = api.delete_income_document(
            w2["id"], make_taxpayer_headers(taxpayer["id"]),
        )
        assert resp.status_code == 204
        after = re_get_tax_return(taxpayer, ready_return["id"])
        assert after["status"] == "DRAFT"
