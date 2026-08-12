"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- ProgramYear ---
    def create_program_year(self, payload, headers):
        return self._request("POST", "/f2s/program-years", payload, headers)

    def list_program_years(self, headers, params=None):
        return self._request("GET", "/f2s/program-years", headers=headers, params=params)

    def get_program_year(self, year_id, headers):
        return self._request("GET", f"/f2s/program-years/{year_id}", headers=headers)

    def open_program_year(self, year_id, headers):
        return self._request("POST", f"/f2s/program-years/{year_id}/open", {}, headers)

    def close_program_year(self, year_id, headers):
        return self._request("POST", f"/f2s/program-years/{year_id}/close", {}, headers)

    def get_program_year_report(self, year_id, headers, month=None):
        params = {"month": month} if month is not None else None
        return self._request(
            "GET", f"/f2s/program-years/{year_id}/report", headers=headers, params=params
        )

    # --- Farm ---
    def create_farm(self, payload, headers):
        return self._request("POST", "/f2s/farms", payload, headers)

    def list_farms(self, headers, params=None):
        return self._request("GET", "/f2s/farms", headers=headers, params=params)

    def get_farm(self, farm_id, headers):
        return self._request("GET", f"/f2s/farms/{farm_id}", headers=headers)

    def approve_farm(self, farm_id, headers):
        return self._request("POST", f"/f2s/farms/{farm_id}/approve", {}, headers)

    def suspend_farm(self, farm_id, headers):
        return self._request("POST", f"/f2s/farms/{farm_id}/suspend", {}, headers)

    def reinstate_farm(self, farm_id, headers):
        return self._request("POST", f"/f2s/farms/{farm_id}/reinstate", {}, headers)

    # --- ComplianceDocument ---
    def create_compliance_document(self, payload, headers):
        return self._request("POST", "/f2s/compliance-documents", payload, headers)

    def list_compliance_documents(self, headers, params=None):
        return self._request(
            "GET", "/f2s/compliance-documents", headers=headers, params=params
        )

    def get_compliance_document(self, doc_id, headers):
        return self._request(
            "GET", f"/f2s/compliance-documents/{doc_id}", headers=headers
        )

    def revoke_compliance_document(self, doc_id, headers):
        return self._request(
            "POST", f"/f2s/compliance-documents/{doc_id}/revoke", {}, headers
        )

    # --- Product ---
    def create_product(self, payload, headers):
        return self._request("POST", "/f2s/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/f2s/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/f2s/products/{product_id}", headers=headers)

    def discontinue_product(self, product_id, headers):
        return self._request(
            "POST", f"/f2s/products/{product_id}/discontinue", {}, headers
        )

    # --- FarmProductOffering ---
    def create_offering(self, payload, headers):
        return self._request("POST", "/f2s/offerings", payload, headers)

    def list_offerings(self, headers, params=None):
        return self._request("GET", "/f2s/offerings", headers=headers, params=params)

    def get_offering(self, offering_id, headers):
        return self._request("GET", f"/f2s/offerings/{offering_id}", headers=headers)

    def submit_offering(self, offering_id, headers):
        return self._request("POST", f"/f2s/offerings/{offering_id}/submit", {}, headers)

    def verify_offering(self, offering_id, headers):
        return self._request("POST", f"/f2s/offerings/{offering_id}/verify", {}, headers)

    def reject_offering(self, offering_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request(
            "POST", f"/f2s/offerings/{offering_id}/reject", payload, headers
        )

    def withdraw_offering(self, offering_id, headers):
        return self._request(
            "POST", f"/f2s/offerings/{offering_id}/withdraw", {}, headers
        )

    # --- MenuForecastLine ---
    def create_forecast_line(self, payload, headers):
        return self._request("POST", "/f2s/forecast-lines", payload, headers)

    def list_forecast_lines(self, headers, params=None):
        return self._request("GET", "/f2s/forecast-lines", headers=headers, params=params)

    def get_forecast_line(self, line_id, headers):
        return self._request("GET", f"/f2s/forecast-lines/{line_id}", headers=headers)

    # --- Kitchen ---
    def create_kitchen(self, payload, headers):
        return self._request("POST", "/f2s/kitchens", payload, headers)

    def list_kitchens(self, headers, params=None):
        return self._request("GET", "/f2s/kitchens", headers=headers, params=params)

    def get_kitchen(self, kitchen_id, headers):
        return self._request("GET", f"/f2s/kitchens/{kitchen_id}", headers=headers)

    # --- ReceivingWindow ---
    def create_receiving_window(self, payload, headers):
        return self._request("POST", "/f2s/receiving-windows", payload, headers)

    def list_receiving_windows(self, headers, params=None):
        return self._request(
            "GET", "/f2s/receiving-windows", headers=headers, params=params
        )

    def get_receiving_window(self, window_id, headers):
        return self._request(
            "GET", f"/f2s/receiving-windows/{window_id}", headers=headers
        )

    def delete_receiving_window(self, window_id, headers):
        return self._request(
            "DELETE", f"/f2s/receiving-windows/{window_id}", headers=headers
        )

    # --- PlantingAgreement ---
    def create_planting_agreement(self, payload, headers):
        return self._request("POST", "/f2s/planting-agreements", payload, headers)

    def list_planting_agreements(self, headers, params=None):
        return self._request(
            "GET", "/f2s/planting-agreements", headers=headers, params=params
        )

    def get_planting_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/f2s/planting-agreements/{agreement_id}", headers=headers
        )

    def sign_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/f2s/planting-agreements/{agreement_id}/sign", {}, headers
        )

    def cancel_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/f2s/planting-agreements/{agreement_id}/cancel", {}, headers
        )

    # --- AgreementAmendment ---
    def propose_amendment(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/f2s/planting-agreements/{agreement_id}/amendments", payload, headers
        )

    def list_amendments(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/f2s/planting-agreements/{agreement_id}/amendments",
            headers=headers,
            params=params,
        )

    def get_amendment(self, amendment_id, headers):
        return self._request(
            "GET", f"/f2s/agreement-amendments/{amendment_id}", headers=headers
        )

    def accept_amendment(self, amendment_id, headers):
        return self._request(
            "POST", f"/f2s/agreement-amendments/{amendment_id}/accept", {}, headers
        )

    def reject_amendment(self, amendment_id, headers):
        return self._request(
            "POST", f"/f2s/agreement-amendments/{amendment_id}/reject", {}, headers
        )

    # --- Delivery ---
    def create_delivery(self, payload, headers):
        return self._request("POST", "/f2s/deliveries", payload, headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/f2s/deliveries", headers=headers, params=params)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/f2s/deliveries/{delivery_id}", headers=headers)

    def check_in_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/f2s/deliveries/{delivery_id}/check-in", {}, headers
        )

    def accept_delivery(self, delivery_id, payload, headers):
        return self._request(
            "POST", f"/f2s/deliveries/{delivery_id}/accept", payload, headers
        )

    def reject_delivery(self, delivery_id, payload, headers):
        return self._request(
            "POST", f"/f2s/deliveries/{delivery_id}/reject", payload, headers
        )

    def dispute_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/f2s/deliveries/{delivery_id}/dispute", {}, headers
        )

    def resolve_delivery_dispute(self, delivery_id, payload, headers):
        return self._request(
            "POST", f"/f2s/deliveries/{delivery_id}/resolve-dispute", payload, headers
        )

    def cancel_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/f2s/deliveries/{delivery_id}/cancel", {}, headers
        )

    # --- Invoice ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/f2s/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/f2s/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/f2s/invoices/{invoice_id}", headers=headers)

    def submit_invoice(self, invoice_id, headers):
        return self._request("POST", f"/f2s/invoices/{invoice_id}/submit", {}, headers)

    def approve_invoice(self, invoice_id, headers):
        return self._request("POST", f"/f2s/invoices/{invoice_id}/approve", {}, headers)

    def reject_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/f2s/invoices/{invoice_id}/reject", payload, headers
        )

    def revise_invoice(self, invoice_id, headers):
        return self._request("POST", f"/f2s/invoices/{invoice_id}/revise", {}, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/f2s/invoices/{invoice_id}/pay", {}, headers)

    # --- ReimbursementClaim / ClaimLine ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/f2s/reimbursement-claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request(
            "GET", "/f2s/reimbursement-claims", headers=headers, params=params
        )

    def get_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/f2s/reimbursement-claims/{claim_id}", headers=headers
        )

    def add_claim_line(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/f2s/reimbursement-claims/{claim_id}/lines", payload, headers
        )

    def list_claim_lines(self, headers, params=None):
        return self._request("GET", "/f2s/claim-lines", headers=headers, params=params)

    def get_claim_line(self, line_id, headers):
        return self._request("GET", f"/f2s/claim-lines/{line_id}", headers=headers)

    def submit_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/f2s/reimbursement-claims/{claim_id}/submit", {}, headers
        )

    def start_claim_review(self, claim_id, headers):
        return self._request(
            "POST", f"/f2s/reimbursement-claims/{claim_id}/start-review", {}, headers
        )

    def allow_claim_line(self, line_id, headers):
        return self._request("POST", f"/f2s/claim-lines/{line_id}/allow", {}, headers)

    def disallow_claim_line(self, line_id, payload, headers):
        return self._request(
            "POST", f"/f2s/claim-lines/{line_id}/disallow", payload, headers
        )

    def reconcile_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/f2s/reimbursement-claims/{claim_id}/reconcile", {}, headers
        )

    def reverse_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/f2s/reimbursement-claims/{claim_id}/reverse", {}, headers
        )

    # --- SubstitutionRequest ---
    def create_substitution_request(self, payload, headers):
        return self._request("POST", "/f2s/substitution-requests", payload, headers)

    def list_substitution_requests(self, headers, params=None):
        return self._request(
            "GET", "/f2s/substitution-requests", headers=headers, params=params
        )

    def get_substitution_request(self, request_id, headers):
        return self._request(
            "GET", f"/f2s/substitution-requests/{request_id}", headers=headers
        )

    def approve_substitution_request(self, request_id, headers):
        return self._request(
            "POST", f"/f2s/substitution-requests/{request_id}/approve", {}, headers
        )

    def deny_substitution_request(self, request_id, headers):
        return self._request(
            "POST", f"/f2s/substitution-requests/{request_id}/deny", {}, headers
        )

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/f2s/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
