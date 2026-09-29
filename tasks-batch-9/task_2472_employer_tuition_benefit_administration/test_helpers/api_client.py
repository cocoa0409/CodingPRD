"""
Typed HTTP client for the Employer Tuition Benefit Administration API.

One method per row of the endpoint table in PRD §4, in the order the table
declares them. Every method returns the raw response so tests can assert the
status code as well as the envelope.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]


class TuitionBenefitApiClient(GenericApiClient):
    """One method per PRD §4 endpoint."""

    # ─── Employers, policies and employees (PRD §3.1) ──────────────────────
    def create_employer(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id: str, headers: Headers = None):
        return self._request("GET", f"/employers/{employer_id}", None, headers)

    def get_utilization_report(self, employer_id: str, headers: Headers = None):
        return self._request(
            "GET", f"/employers/{employer_id}/utilization-report", None, headers
        )

    def create_benefit_policy(
        self, employer_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/employers/{employer_id}/benefit-policies", payload, headers
        )

    def list_benefit_policies(
        self, employer_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET", f"/employers/{employer_id}/benefit-policies", params, headers
        )

    def activate_benefit_policy(self, policy_id: str, headers: Headers = None):
        return self._request(
            "POST", f"/benefit-policies/{policy_id}/activate", {}, headers
        )

    def create_employee(
        self, employer_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/employers/{employer_id}/employees", payload, headers
        )

    def list_employees(
        self, employer_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET", f"/employers/{employer_id}/employees", params, headers
        )

    def get_employee(self, employee_id: str, headers: Headers = None):
        return self._request("GET", f"/employees/{employee_id}", None, headers)

    def patch_employee(
        self, employee_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request("PATCH", f"/employees/{employee_id}", payload, headers)

    # ─── Schools, programs and partner agreements (PRD §3.2) ───────────────
    def create_school(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/schools", payload, headers)

    def get_school(self, school_id: str, headers: Headers = None):
        return self._request("GET", f"/schools/{school_id}", None, headers)

    def create_program(
        self, school_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/schools/{school_id}/programs", payload, headers
        )

    def list_programs(
        self, school_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request("GET", f"/schools/{school_id}/programs", params, headers)

    def create_partner_agreement(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/partner-agreements", payload, headers)

    def list_partner_agreements(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/partner-agreements", params, headers)

    def get_partner_agreement(self, agreement_id: str, headers: Headers = None):
        return self._request(
            "GET", f"/partner-agreements/{agreement_id}", None, headers
        )

    def activate_partner_agreement(self, agreement_id: str, headers: Headers = None):
        return self._request(
            "POST", f"/partner-agreements/{agreement_id}/activate", {}, headers
        )

    def terminate_partner_agreement(self, agreement_id: str, headers: Headers = None):
        return self._request(
            "POST", f"/partner-agreements/{agreement_id}/terminate", {}, headers
        )

    # ─── Catalog and the non-catalog exception path (PRD §3.3) ─────────────
    def create_catalog_listing(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/catalog-listings", payload, headers)

    def list_catalog_listings(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/catalog-listings", params, headers)

    def get_catalog_listing(self, listing_id: str, headers: Headers = None):
        return self._request("GET", f"/catalog-listings/{listing_id}", None, headers)

    def suspend_catalog_listing(self, listing_id: str, headers: Headers = None):
        return self._request(
            "POST", f"/catalog-listings/{listing_id}/suspend", {}, headers
        )

    def create_program_approval_request(
        self, payload: Payload, headers: Headers = None
    ):
        return self._request("POST", "/program-approval-requests", payload, headers)

    def list_program_approval_requests(
        self, headers: Headers = None, params: Payload = None
    ):
        return self._request("GET", "/program-approval-requests", params, headers)

    def get_program_approval_request(self, request_id: str, headers: Headers = None):
        return self._request(
            "GET", f"/program-approval-requests/{request_id}", None, headers
        )

    def review_program_approval_request(
        self, request_id: str, headers: Headers = None
    ):
        return self._request(
            "POST", f"/program-approval-requests/{request_id}/review", {}, headers
        )

    def resubmit_program_approval_request(
        self, request_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/program-approval-requests/{request_id}/resubmit",
            payload if payload is not None else {},
            headers,
        )

    def decide_program_approval_request(
        self, request_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/program-approval-requests/{request_id}/decide",
            payload,
            headers,
        )

    # ─── Enrollment, registration and outcomes (PRD §3.4 – §3.6) ──────────
    def create_enrollment(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/enrollments", params, headers)

    def get_enrollment(self, enrollment_id: str, headers: Headers = None):
        return self._request("GET", f"/enrollments/{enrollment_id}", None, headers)

    def confirm_registration(self, enrollment_id: str, headers: Headers = None):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/confirm-registration", {}, headers
        )

    def withdraw_enrollment(self, enrollment_id: str, headers: Headers = None):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/withdraw", {}, headers
        )

    def create_academic_outcome(
        self, enrollment_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/enrollments/{enrollment_id}/academic-outcomes",
            payload,
            headers,
        )

    def list_academic_outcomes(
        self, enrollment_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/academic-outcomes", params, headers
        )

    def create_coaching_session(
        self, enrollment_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/enrollments/{enrollment_id}/coaching-sessions",
            payload,
            headers,
        )

    def list_coaching_sessions(
        self, enrollment_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/coaching-sessions", params, headers
        )

    # ─── Direct billing (PRD §3.5) ─────────────────────────────────────────
    def list_enrollment_invoices(
        self, enrollment_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/invoices", params, headers
        )

    def approve_invoice_for_payment(self, invoice_id: str, headers: Headers = None):
        return self._request(
            "POST", f"/tuition-invoices/{invoice_id}/approve-payment", {}, headers
        )

    def pay_invoice(self, invoice_id: str, headers: Headers = None):
        return self._request(
            "POST", f"/tuition-invoices/{invoice_id}/pay", {}, headers
        )

    # ─── Reimbursement claims (PRD §3.6) ───────────────────────────────────
    def create_reimbursement_claim(
        self, enrollment_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/enrollments/{enrollment_id}/reimbursement-claims",
            payload,
            headers,
        )

    def list_reimbursement_claims(
        self, enrollment_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET",
            f"/enrollments/{enrollment_id}/reimbursement-claims",
            params,
            headers,
        )

    def decide_reimbursement_claim(
        self, claim_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/reimbursement-claims/{claim_id}/decide", payload, headers
        )

    # ─── Repayment obligations (PRD §3.7) ──────────────────────────────────
    def list_repayment_obligations(
        self, enrollment_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET",
            f"/enrollments/{enrollment_id}/repayment-obligations",
            params,
            headers,
        )

    def create_repayment_payment(
        self, obligation_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/repayment-obligations/{obligation_id}/payments", payload, headers
        )

    def waive_repayment_obligation(
        self, obligation_id: str, headers: Headers = None
    ):
        return self._request(
            "POST", f"/repayment-obligations/{obligation_id}/waive", {}, headers
        )

    # ─── Tax ledger (PRD §2.10) ────────────────────────────────────────────
    def list_tax_ledger_entries(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/tax-ledger-entries", params, headers)

    def get_tax_ledger_entry(self, entry_id: str, headers: Headers = None):
        return self._request("GET", f"/tax-ledger-entries/{entry_id}", None, headers)

    # ─── Logical clock and operator batch (PRD §2.4, §3.9) ────────────────
    def set_clock(self, to_iso8601: str, headers: Headers = None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def term_close(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/_ops/term-close", payload, headers)
