"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's ``GenericApiClient``; the base ``_request`` handles
the HTTP envelope, so each method here only shapes the method/path/body.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Applicants ──────────────────────────────────────────────────────
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    def sign_master_agreement(self, applicant_id, headers):
        return self._request(
            "POST", f"/applicants/{applicant_id}/sign-master-agreement", {}, headers
        )

    # ─── Support structures ──────────────────────────────────────────────
    def create_support_structure(self, payload, headers):
        return self._request("POST", "/support-structures", payload, headers)

    def get_support_structure(self, structure_id, headers):
        return self._request(
            "GET", f"/support-structures/{structure_id}", headers=headers
        )

    def retire_support_structure(self, structure_id, headers):
        return self._request(
            "POST", f"/support-structures/{structure_id}/retire", {}, headers
        )

    def list_structure_nodes(self, structure_id, headers, params=None):
        return self._request(
            "GET", f"/support-structures/{structure_id}/nodes", headers=headers, params=params
        )

    # ─── ROW segments ────────────────────────────────────────────────────
    def create_row_segment(self, payload, headers):
        return self._request("POST", "/row-segments", payload, headers)

    def get_row_segment(self, segment_id, headers):
        return self._request("GET", f"/row-segments/{segment_id}", headers=headers)

    def list_segment_nodes(self, segment_id, headers, params=None):
        return self._request(
            "GET", f"/row-segments/{segment_id}/nodes", headers=headers, params=params
        )

    # ─── Applications ────────────────────────────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def add_node(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/nodes", payload, headers
        )

    def list_application_nodes(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/nodes", headers=headers, params=params
        )

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/submit", {}, headers
        )

    def completeness_review(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/completeness-review", payload, headers
        )

    def list_incompleteness_notices(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/incompleteness-notices",
            headers=headers, params=params,
        )

    def cure_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/cure", {}, headers
        )

    def decide_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/decision", payload, headers
        )

    def evaluate_deadline(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/evaluate-deadline", {}, headers
        )

    def create_appeal(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/appeal", payload, headers
        )

    def list_appeals(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/appeals", headers=headers, params=params
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/withdraw", {}, headers
        )

    def get_application_fee_invoice(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/applications/{application_id}/fee-invoice", headers=headers, params=params
        )

    # ─── Nodes ───────────────────────────────────────────────────────────
    def get_node(self, node_id, headers):
        return self._request("GET", f"/nodes/{node_id}", headers=headers)

    def design_review(self, node_id, payload, headers):
        return self._request("POST", f"/nodes/{node_id}/design-review", payload, headers)

    def aesthetic_review(self, node_id, payload, headers):
        return self._request("POST", f"/nodes/{node_id}/aesthetic-review", payload, headers)

    def list_node_reviews(self, node_id, headers, params=None):
        return self._request(
            "GET", f"/nodes/{node_id}/reviews", headers=headers, params=params
        )

    def create_inspection(self, node_id, payload, headers):
        return self._request("POST", f"/nodes/{node_id}/inspection", payload, headers)

    def list_inspections(self, node_id, headers, params=None):
        return self._request(
            "GET", f"/nodes/{node_id}/inspections", headers=headers, params=params
        )

    def activate_node(self, node_id, headers):
        return self._request("POST", f"/nodes/{node_id}/activate", {}, headers)

    def list_node_rentals(self, node_id, headers, params=None):
        return self._request(
            "GET", f"/nodes/{node_id}/rentals", headers=headers, params=params
        )

    # ─── Rentals ─────────────────────────────────────────────────────────
    def renew_rental(self, rental_id, payload, headers):
        return self._request("POST", f"/rentals/{rental_id}/renew", payload, headers)

    # ─── Fee invoices & payments ─────────────────────────────────────────
    def create_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/fee-invoices/{invoice_id}/payments", payload, headers
        )

    def get_fee_invoice(self, invoice_id, headers):
        return self._request("GET", f"/fee-invoices/{invoice_id}", headers=headers)

    def list_payments(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/fee-invoices/{invoice_id}/payments", headers=headers, params=params
        )

    # ─── Appeals ─────────────────────────────────────────────────────────
    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decision", payload, headers)

    # ─── Logical clock ───────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
