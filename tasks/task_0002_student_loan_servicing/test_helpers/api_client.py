"""API client: one method per endpoint defined in the PRD.

All paths include the /v1 prefix per the PRD endpoint table in §4.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Borrowers ────────────────────────────────────
    def create_borrower(self, payload, headers):
        return self._request("POST", "/v1/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/v1/borrowers/{borrower_id}", headers=headers)

    def list_borrowers(self, headers, params=None):
        return self._request("GET", "/v1/borrowers", headers=headers, params=params)

    def patch_borrower_military_status(self, borrower_id, payload, headers):
        return self._request(
            "PATCH", f"/v1/borrowers/{borrower_id}/military-status", payload, headers
        )

    # ─── Loans ────────────────────────────────────────
    def create_loan(self, payload, headers):
        return self._request("POST", "/v1/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/v1/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/v1/loans", headers=headers, params=params)

    # ─── Servicing Events ────────────────────────────
    def create_servicing_event(self, loan_id, payload, headers):
        return self._request(
            "POST", f"/v1/loans/{loan_id}/servicing-events", payload, headers
        )

    def list_servicing_events(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/v1/loans/{loan_id}/servicing-events",
            headers=headers, params=params,
        )

    # ─── Delinquency Records ─────────────────────────
    def list_delinquency_records(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/v1/loans/{loan_id}/delinquency-records",
            headers=headers, params=params,
        )

    # ─── Repayment Plans ─────────────────────────────
    def create_repayment_plan(self, payload, headers):
        return self._request("POST", "/v1/repayment-plans", payload, headers)

    def get_repayment_plan(self, plan_id, headers):
        return self._request("GET", f"/v1/repayment-plans/{plan_id}", headers=headers)

    def list_repayment_plans(self, headers, params=None):
        return self._request("GET", "/v1/repayment-plans", headers=headers, params=params)

    def recertify_repayment_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/v1/repayment-plans/{plan_id}/recertify", payload, headers
        )

    # ─── Payments ────────────────────────────────────
    def create_payment(self, payload, headers):
        return self._request("POST", "/v1/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/v1/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/v1/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/v1/payments/{payment_id}/reverse", headers=headers
        )

    # ─── Employment Certifications ───────────────────
    def create_employment_certification(self, payload, headers):
        return self._request("POST", "/v1/employment-certifications", payload, headers)

    def list_employment_certifications(self, headers, params=None):
        return self._request(
            "GET", "/v1/employment-certifications", headers=headers, params=params
        )

    def approve_employment_certification(self, certification_id, headers):
        return self._request(
            "POST", f"/v1/employment-certifications/{certification_id}/approve",
            headers=headers,
        )

    def reject_employment_certification(self, certification_id, headers):
        return self._request(
            "POST", f"/v1/employment-certifications/{certification_id}/reject",
            headers=headers,
        )

    # ─── PSLF Trackers ───────────────────────────────
    def create_pslf_tracker(self, payload, headers):
        return self._request("POST", "/v1/pslf-trackers", payload, headers)

    def get_pslf_tracker(self, tracker_id, headers):
        return self._request("GET", f"/v1/pslf-trackers/{tracker_id}", headers=headers)

    def recount_pslf_tracker(self, tracker_id, headers):
        return self._request(
            "POST", f"/v1/pslf-trackers/{tracker_id}/recount", headers=headers
        )

    def deny_pslf_tracker(self, tracker_id, headers):
        return self._request(
            "POST", f"/v1/pslf-trackers/{tracker_id}/deny", headers=headers
        )

    # ─── Discharge Applications ──────────────────────
    def create_discharge_application(self, payload, headers):
        return self._request("POST", "/v1/discharge-applications", payload, headers)

    def get_discharge_application(self, application_id, headers):
        return self._request(
            "GET", f"/v1/discharge-applications/{application_id}", headers=headers
        )

    def list_discharge_applications(self, headers, params=None):
        return self._request(
            "GET", "/v1/discharge-applications", headers=headers, params=params
        )

    def begin_review_discharge_application(self, application_id, headers):
        return self._request(
            "POST", f"/v1/discharge-applications/{application_id}/begin-review",
            headers=headers,
        )

    def approve_discharge_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/v1/discharge-applications/{application_id}/approve",
            payload, headers,
        )

    def deny_discharge_application(self, application_id, headers):
        return self._request(
            "POST", f"/v1/discharge-applications/{application_id}/deny",
            headers=headers,
        )

    # ─── Test-driving endpoints (under /_ namespace) ─
    def advance_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/advance", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/v1/_clock", headers=headers)

    def force_pslf_tracker_state(self, tracker_id, payload, headers):
        return self._request(
            "POST", f"/v1/_pslf-trackers/{tracker_id}/force-state",
            payload, headers,
        )


api_client = ApiClient()
