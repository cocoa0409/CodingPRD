"""Tax credit claiming — EITC / CTC / AOTC.

Coverage targets (PRD §3.4):
- Create credit row in PENDING with zeros.
- AOTC requires aotc_student_count >= 1 and qualified expenses > 0.
- MARRIED_SEPARATE cannot claim EITC or AOTC.
- Duplicate credit_type -> ERR_DUPLICATE_CREDIT.
- DELETE credit on READY_TO_FILE reverts parent to DRAFT.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_credit,
    assert_tax_credit,
    create_credit_payload,
    make_taxpayer_headers,
    re_get_tax_return,
    setup_active_taxpayer_with_draft_return,
    setup_ready_to_file_return,
    setup_simple_w2_return,
    validate_error,
    validate_success,
)


# ===========================================================================
# Credit row creation — PRD §3.4
# ===========================================================================
class TestCreateCredit:

    def test_create_credit_starts_pending(self, api):
        """PRD §3.4: "Until the return is computed, every TaxCredit
        row sits in eligibility_status PENDING with
        approved_amount_cents and refundable_portion_cents of zero
        and ineligibility_reason of null."

        Claim: a freshly attached credit reports
        eligibility_status=PENDING and zero approved/refundable.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return(
            dependents_count=2, qualifying_children_under_17=2,
        )
        credit = add_credit(
            taxpayer, tax_return["id"],
            credit_type="CTC", requested_amount_cents=400_000,
        )
        assert_tax_credit(credit)
        assert credit["eligibility_status"] == "PENDING"
        assert credit["approved_amount_cents"] == 0
        assert credit["refundable_portion_cents"] == 0
        assert credit["ineligibility_reason"] is None


# ===========================================================================
# Eligibility input checks — PRD §3.4 / priority 14
# ===========================================================================
class TestEligibilityInputs:

    def test_aotc_zero_students_rejected(self, api):
        """PRD §3.4: "AOTC specifically requires two additional inputs
        — aotc_student_count (must be at least 1 to claim AOTC) and
        aotc_qualified_expenses_cents (must be strictly positive)."
        PRD §3.4: "AOTC requires a non-zero student count and positive
        qualified expenses; a violation is rejected with
        ERR_CREDIT_INELIGIBLE."

        Claim: AOTC with aotc_student_count=0 -> ERR_CREDIT_INELIGIBLE.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        resp = api.create_credit(
            tax_return["id"],
            create_credit_payload(
                credit_type="AOTC",
                requested_amount_cents=250_000,
                aotc_student_count=0,
                aotc_qualified_expenses_cents=400_000,
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_INELIGIBLE.value)

    def test_aotc_zero_expenses_rejected(self, api):
        """PRD §3.4: "AOTC requires a non-zero student count and
        positive qualified expenses; a violation is rejected with
        ERR_CREDIT_INELIGIBLE."

        Claim: AOTC with aotc_qualified_expenses_cents=0 ->
        ERR_CREDIT_INELIGIBLE.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        resp = api.create_credit(
            tax_return["id"],
            create_credit_payload(
                credit_type="AOTC",
                requested_amount_cents=250_000,
                aotc_student_count=1,
                aotc_qualified_expenses_cents=0,
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_INELIGIBLE.value)

    def test_eitc_blocked_for_married_separate(self, api):
        """PRD §3.4: "A return whose filing_status is MARRIED_SEPARATE
        cannot claim either EITC or AOTC, and an attempt to do so is
        also rejected with ERR_CREDIT_INELIGIBLE."

        Claim: MARRIED_SEPARATE + EITC -> ERR_CREDIT_INELIGIBLE.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return(
            filing_status="MARRIED_SEPARATE",
        )
        resp = api.create_credit(
            tax_return["id"],
            create_credit_payload(
                credit_type="EITC",
                requested_amount_cents=60_000,
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_INELIGIBLE.value)

    def test_aotc_blocked_for_married_separate(self, api):
        """PRD §3.4: "A return whose filing_status is MARRIED_SEPARATE
        cannot claim either EITC or AOTC".

        Claim: MARRIED_SEPARATE + AOTC -> ERR_CREDIT_INELIGIBLE.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return(
            filing_status="MARRIED_SEPARATE",
        )
        resp = api.create_credit(
            tax_return["id"],
            create_credit_payload(
                credit_type="AOTC",
                requested_amount_cents=250_000,
                aotc_student_count=1,
                aotc_qualified_expenses_cents=400_000,
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_INELIGIBLE.value)


# ===========================================================================
# Duplicate — PRD §3.4 / priority 15
# ===========================================================================
class TestDuplicateCredit:

    def test_duplicate_credit_type_rejected(self, api):
        """PRD §3.4: "Two credits of the same credit_type on the same
        return are blocked with ERR_DUPLICATE_CREDIT."

        Claim: second CTC on the same return -> ERR_DUPLICATE_CREDIT.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return(
            dependents_count=1, qualifying_children_under_17=1,
        )
        add_credit(
            taxpayer, tax_return["id"],
            credit_type="CTC", requested_amount_cents=200_000,
        )
        resp = api.create_credit(
            tax_return["id"],
            create_credit_payload(
                credit_type="CTC", requested_amount_cents=200_000,
            ),
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CREDIT.value)


# ===========================================================================
# Credit cascade — PRD §3.4 / §2.7
# ===========================================================================
class TestCreditCascade:

    def test_delete_credit_on_ready_reverts(self, api):
        """PRD §3.4: "A credit can be removed from the return entirely,
        which reverts the parent return to DRAFT if it had reached
        READY_TO_FILE."

        Claim: DELETE /credits/{id} on a READY_TO_FILE return reverts
        the return to DRAFT.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=2_000_000,
            federal_withholding_cents=200_000,
            filing_status="SINGLE",
            dependents_count=1,
            qualifying_children_under_17=1,
        )
        credit = add_credit(
            taxpayer, tax_return["id"],
            credit_type="CTC", requested_amount_cents=200_000,
        )
        from test_helpers import compute_tax_return
        computed = compute_tax_return(taxpayer, tax_return["id"])
        assert computed["status"] == "READY_TO_FILE"
        # DELETE the credit.
        resp = api.delete_credit(
            credit["id"], make_taxpayer_headers(taxpayer["id"]),
        )
        assert resp.status_code == 204
        after = re_get_tax_return(taxpayer, tax_return["id"])
        assert after["status"] == "DRAFT"
