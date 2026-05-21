"""I9 document registration and the document-list / category / expiry
validations applied at Section 2.

Covers PRD §3.2 (document registration, receipt rule), §3.3
(Section 2 list rule, category match, expiry).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    assert_i9_document,
    create_employee,
    create_i9_document_payload,
    register_document,
    register_list_a_document,
    register_list_b_document,
    register_list_c_document,
    setup_employee_with_section2_done,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Document registration — PRD §3.2
# ===========================================================================
class TestDocumentRegistration:

    def test_register_list_a_document_returns_201(self, api, hr_staff_headers):
        """PRD §3.2: "Either `HRStaff` or an `EmployerRep` may register
        a document against an employee"."""
        emp = create_employee()
        resp = api.create_i9_document(
            emp["id"],
            create_i9_document_payload(
                category="LIST_A",
                document_title="U.S. Passport",
                expiration_date="2030-01-01",
            ),
            hr_staff_headers,
        )
        doc = validate_success(resp, expected_status=201)
        assert_i9_document(doc)
        assert doc["category"] == "LIST_A"
        assert doc["receipt"] is False

    def test_register_receipt_computes_receipt_resolution_due(self, api,
                                                              hr_staff_headers):
        """PRD §3.2: "When a document is a receipt, the system computes
        `receipt_resolution_due` as the employee's `start_date` plus 90
        calendar days; the actual document must replace the receipt by
        that date."

        Claim: start_date=2026-06-01, receipt=true → receipt_resolution_due
        is 90 calendar days after start_date.
        """
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        resp = api.create_i9_document(
            emp["id"],
            create_i9_document_payload(
                category="LIST_A",
                document_title="EAD I-766",
                receipt=True,
                expiration_date="2026-09-01",
            ),
            hr_staff_headers,
        )
        doc = validate_success(resp, expected_status=201)
        # 2026-06-01 + 90 days = 2026-08-30.
        assert doc["receipt"] is True
        assert doc["receipt_resolution_due"] is not None, (
            "PRD §3.2: receipt=true triggers receipt_resolution_due"
        )
        # Day-granularity comparison: accept either 'YYYY-MM-DD' or ISO datetime.
        rrd = str(doc["receipt_resolution_due"])
        assert rrd.startswith("2026-08-30"), (
            f"Expected receipt_resolution_due starting 2026-08-30 "
            f"(start_date 2026-06-01 + 90 calendar days), got {rrd!r}"
        )


# ===========================================================================
# Document list rule on Section 2 — PRD §3.3
# ===========================================================================
class TestDocumentListRule:

    def test_section2_with_list_a_and_list_b_is_list_rule_violation(
            self, api, employer_rep_headers):
        """PRD §3.3: "Any other combination — `LIST_A` together with
        `LIST_B`, `LIST_A` together with `LIST_C`, `LIST_B` alone,
        `LIST_C` alone, or all three together — is rejected with
        `ERR_DOCUMENT_LIST_RULE`."

        Claim: list_a + list_b → ERR_DOCUMENT_LIST_RULE.
        """
        from test_helpers import (
            attest_section1, create_employee, create_i9_form,
            section2_payload,
        )
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp["id"], form_id=form["id"])
        doc_a = register_list_a_document(employee_id=emp["id"])
        doc_b = register_list_b_document(employee_id=emp["id"])
        advance_clock_to("2026-06-02T08:00:00.000Z")
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_a_document_id=doc_a["id"],
                list_b_document_id=doc_b["id"],
            ),
            employer_rep_headers,
        )
        validate_error(resp, "ERR_DOCUMENT_LIST_RULE")

    def test_section2_with_list_b_only_is_list_rule_violation(
            self, api, employer_rep_headers):
        """PRD §3.3: list_b alone is one of the explicitly-rejected
        combinations."""
        from test_helpers import (
            attest_section1, create_employee, create_i9_form,
            section2_payload,
        )
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp["id"], form_id=form["id"])
        doc_b = register_list_b_document(employee_id=emp["id"])
        advance_clock_to("2026-06-02T08:00:00.000Z")
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_b_document_id=doc_b["id"],
            ),
            employer_rep_headers,
        )
        validate_error(resp, "ERR_DOCUMENT_LIST_RULE")

    def test_section2_with_list_b_plus_list_c_succeeds(self, api,
                                                      employer_rep_headers):
        """PRD §3.3: "exactly one of `list_a_document_id` is set with
        both `list_b_document_id` and `list_c_document_id` null, **or**
        `list_a_document_id` is null while both `list_b_document_id`
        and `list_c_document_id` are set."

        Claim: B + C (no A) is the second permitted combination.
        """
        from test_helpers import (
            attest_section1, create_employee, create_i9_form,
            section2_payload,
        )
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp["id"], form_id=form["id"])
        doc_b = register_list_b_document(employee_id=emp["id"])
        doc_c = register_list_c_document(employee_id=emp["id"])
        advance_clock_to("2026-06-02T08:00:00.000Z")
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_b_document_id=doc_b["id"],
                list_c_document_id=doc_c["id"],
            ),
            employer_rep_headers,
        )
        signed = validate_success(resp, expected_status=200)
        assert signed["form_status"] == "SECTION_2_DONE"


# ===========================================================================
# Category mismatch — PRD §3.3
# ===========================================================================
class TestDocumentCategoryMatch:

    def test_section2_list_a_field_pointing_at_list_b_doc_is_mismatch(
            self, api, employer_rep_headers):
        """PRD §3.3: "its `category` must match the field that
        references it (the document in `list_a_document_id` must have
        `category` `LIST_A`, and likewise for the B and C fields),
        otherwise `ERR_DOCUMENT_CATEGORY_MISMATCH` is returned"."""
        from test_helpers import (
            attest_section1, create_employee, create_i9_form,
            section2_payload,
        )
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp["id"], form_id=form["id"])
        # Register a LIST_B doc, then point list_a_document_id at it.
        doc_b = register_list_b_document(employee_id=emp["id"])
        advance_clock_to("2026-06-02T08:00:00.000Z")
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_a_document_id=doc_b["id"],
            ),
            employer_rep_headers,
        )
        validate_error(resp, "ERR_DOCUMENT_CATEGORY_MISMATCH")

    def test_section2_document_belonging_to_other_employee_is_mismatch(
            self, api, employer_rep_headers):
        """PRD §3.3: "Each referenced document must belong to the same
        `employee_id` as the form's path".

        Claim: a LIST_A doc belonging to employee2 referenced by a form
        on employee1 → ERR_DOCUMENT_CATEGORY_MISMATCH (per PRD's
        catalogue this is the cross-owner case rolled into the same
        category-mismatch error).
        """
        from test_helpers import (
            attest_section1, create_employee, create_i9_form,
            section2_payload,
        )
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp1 = create_employee(start_date="2026-06-01")
        emp2 = create_employee(start_date="2026-06-01")
        form = create_i9_form(employee_id=emp1["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp1["id"], form_id=form["id"])
        # Register a LIST_A doc under emp2, then reference it on emp1's form.
        foreign_doc = register_list_a_document(employee_id=emp2["id"])
        advance_clock_to("2026-06-02T08:00:00.000Z")
        resp = api.sign_section2(
            emp1["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_a_document_id=foreign_doc["id"],
            ),
            employer_rep_headers,
        )
        validate_error(resp, "ERR_DOCUMENT_CATEGORY_MISMATCH")


# ===========================================================================
# Document expiry exception via receipt — PRD §3.3
# ===========================================================================
class TestReceiptExceptionAtSection2:

    def test_section2_with_expired_doc_but_valid_receipt_succeeds(
            self, api, employer_rep_headers):
        """PRD §3.3: "Every referenced document must also be unexpired
        at `SystemClock.current_time`, with one carve-out: a document
        where `receipt` is true is accepted if and only if its
        `receipt_resolution_due` is strictly after the current time."

        Claim: receipt=true with receipt_resolution_due > current_time
        is accepted even if expiration_date is in the past.
        """
        from test_helpers import (
            attest_section1, create_employee, create_i9_form,
            register_document, section2_payload,
        )
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        form = create_i9_form(employee_id=emp["id"], form_kind="INITIAL")
        form = attest_section1(employee_id=emp["id"], form_id=form["id"])
        # Receipt that "expired" 2025-12-31 — but receipt_resolution_due
        # is start_date + 90 days = 2026-08-30, which is > 2026-06-02 now.
        doc = register_document(
            employee_id=emp["id"], category="LIST_A",
            document_title="EAD I-766",
            expiration_date="2025-12-31",
            receipt=True,
        )
        advance_clock_to("2026-06-02T08:00:00.000Z")
        resp = api.sign_section2(
            emp["id"], form["id"],
            section2_payload(
                version=form["version"],
                list_a_document_id=doc["id"],
            ),
            employer_rep_headers,
        )
        signed = validate_success(resp, expected_status=200)
        assert signed["form_status"] == "SECTION_2_DONE"
