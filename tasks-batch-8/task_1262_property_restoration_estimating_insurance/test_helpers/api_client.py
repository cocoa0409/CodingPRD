"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    # --- carriers / price lists ---
    def create_carrier(self, payload, headers):
        return self._request("POST", "/v1/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/v1/carriers/{carrier_id}", headers=headers)

    def create_price_list_entry(self, carrier_id, payload, headers):
        return self._request(
            "POST", f"/v1/carriers/{carrier_id}/price-list-entries", payload, headers
        )

    def list_price_list_entries(self, carrier_id, headers, params=None):
        return self._request(
            "GET", f"/v1/carriers/{carrier_id}/price-list-entries",
            headers=headers, params=params,
        )

    # --- customers / policies ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/v1/customers", payload, headers)

    def create_policy(self, payload, headers):
        return self._request("POST", "/v1/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/v1/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/v1/policies", headers=headers, params=params)

    # --- claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/v1/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/v1/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/v1/claims/{claim_id}", headers=headers)

    def transition_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/v1/claims/{claim_id}/transition", payload, headers
        )

    def start_work(self, claim_id, headers):
        return self._request("POST", f"/v1/claims/{claim_id}/start-work", None, headers)

    def complete_work(self, claim_id, headers):
        return self._request(
            "POST", f"/v1/claims/{claim_id}/complete-work", None, headers
        )

    def get_financial_summary(self, claim_id, headers):
        return self._request(
            "GET", f"/v1/claims/{claim_id}/financial-summary", headers=headers
        )

    # --- inspections / readings ---
    def create_inspection(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/v1/claims/{claim_id}/inspections", payload, headers
        )

    def list_inspections(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/v1/claims/{claim_id}/inspections", headers=headers, params=params
        )

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/v1/inspections/{inspection_id}", headers=headers)

    def complete_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"/v1/inspections/{inspection_id}/complete", None, headers
        )

    def cancel_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"/v1/inspections/{inspection_id}/cancel", None, headers
        )

    def create_moisture_reading(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/v1/inspections/{inspection_id}/readings", payload, headers
        )

    def list_moisture_readings(self, inspection_id, headers, params=None):
        return self._request(
            "GET", f"/v1/inspections/{inspection_id}/readings",
            headers=headers, params=params,
        )

    # --- photos ---
    def create_photo(self, payload, headers):
        return self._request("POST", "/v1/photos", payload, headers)

    def get_photo(self, photo_id, headers):
        return self._request("GET", f"/v1/photos/{photo_id}", headers=headers)

    def list_photos(self, headers, params=None):
        return self._request("GET", "/v1/photos", headers=headers, params=params)

    # --- estimates / lines ---
    def create_estimate(self, claim_id, payload, headers):
        return self._request("POST", f"/v1/claims/{claim_id}/estimates", payload, headers)

    def list_estimates(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/v1/claims/{claim_id}/estimates", headers=headers, params=params
        )

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/v1/estimates/{estimate_id}", headers=headers)

    def create_estimate_line(self, estimate_id, payload, headers):
        return self._request(
            "POST", f"/v1/estimates/{estimate_id}/lines", payload, headers
        )

    def list_estimate_lines(self, estimate_id, headers, params=None):
        return self._request(
            "GET", f"/v1/estimates/{estimate_id}/lines", headers=headers, params=params
        )

    def patch_estimate_line(self, estimate_id, line_id, payload, headers):
        return self._request(
            "PATCH", f"/v1/estimates/{estimate_id}/lines/{line_id}", payload, headers
        )

    def remove_estimate_line(self, estimate_id, line_id, headers):
        return self._request(
            "POST", f"/v1/estimates/{estimate_id}/lines/{line_id}/remove", None, headers
        )

    def submit_estimate(self, estimate_id, headers):
        return self._request("POST", f"/v1/estimates/{estimate_id}/submit", None, headers)

    def revise_estimate(self, estimate_id, headers):
        return self._request("POST", f"/v1/estimates/{estimate_id}/revise", None, headers)

    def concede_estimate(self, estimate_id, headers):
        return self._request("POST", f"/v1/estimates/{estimate_id}/concede", None, headers)

    def approve_estimate(self, estimate_id, headers):
        return self._request("POST", f"/v1/estimates/{estimate_id}/approve", None, headers)

    def deny_estimate(self, estimate_id, headers):
        return self._request("POST", f"/v1/estimates/{estimate_id}/deny", None, headers)

    def record_actuals(self, estimate_id, payload, headers):
        return self._request(
            "POST", f"/v1/estimates/{estimate_id}/record-actuals", payload, headers
        )

    # --- negotiation rounds / dispositions ---
    def create_negotiation_round(self, estimate_id, payload, headers):
        return self._request(
            "POST", f"/v1/estimates/{estimate_id}/negotiation-rounds", payload, headers
        )

    def list_negotiation_rounds(self, estimate_id, headers, params=None):
        return self._request(
            "GET", f"/v1/estimates/{estimate_id}/negotiation-rounds",
            headers=headers, params=params,
        )

    def get_negotiation_round(self, round_id, headers):
        return self._request(
            "GET", f"/v1/negotiation-rounds/{round_id}", headers=headers
        )

    def append_dispositions(self, round_id, payload, headers):
        return self._request(
            "POST", f"/v1/negotiation-rounds/{round_id}/dispositions", payload, headers
        )

    def list_dispositions(self, round_id, headers, params=None):
        return self._request(
            "GET", f"/v1/negotiation-rounds/{round_id}/dispositions",
            headers=headers, params=params,
        )

    def respond_to_disposition(self, disposition_id, payload, headers):
        return self._request(
            "POST", f"/v1/dispositions/{disposition_id}/respond", payload, headers
        )

    # --- supplements ---
    def create_supplement(self, claim_id, payload, headers):
        return self._request("POST", f"/v1/claims/{claim_id}/supplements", payload, headers)

    def list_supplements(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/v1/claims/{claim_id}/supplements", headers=headers, params=params
        )

    def get_supplement(self, supplement_id, headers):
        return self._request("GET", f"/v1/supplements/{supplement_id}", headers=headers)

    def submit_supplement(self, supplement_id, headers):
        return self._request(
            "POST", f"/v1/supplements/{supplement_id}/submit", None, headers
        )

    def approve_supplement(self, supplement_id, headers):
        return self._request(
            "POST", f"/v1/supplements/{supplement_id}/approve", None, headers
        )

    def deny_supplement(self, supplement_id, headers):
        return self._request("POST", f"/v1/supplements/{supplement_id}/deny", None, headers)

    def list_supplement_estimates(self, supplement_id, headers, params=None):
        return self._request(
            "GET", f"/v1/supplements/{supplement_id}/estimates",
            headers=headers, params=params,
        )

    # --- code upgrades ---
    def create_code_upgrade(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/v1/claims/{claim_id}/code-upgrades", payload, headers
        )

    def list_code_upgrades(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/v1/claims/{claim_id}/code-upgrades", headers=headers, params=params
        )

    def approve_code_upgrade(self, upgrade_id, payload, headers):
        return self._request(
            "POST", f"/v1/code-upgrades/{upgrade_id}/approve", payload, headers
        )

    def deny_code_upgrade(self, upgrade_id, headers):
        return self._request("POST", f"/v1/code-upgrades/{upgrade_id}/deny", None, headers)

    def withdraw_code_upgrade(self, upgrade_id, headers):
        return self._request(
            "POST", f"/v1/code-upgrades/{upgrade_id}/withdraw", None, headers
        )

    # --- work authorizations ---
    def create_work_authorization(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/v1/claims/{claim_id}/work-authorizations", payload, headers
        )

    def list_work_authorizations(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/v1/claims/{claim_id}/work-authorizations",
            headers=headers, params=params,
        )

    def sign_work_authorization(self, wa_id, headers):
        return self._request(
            "POST", f"/v1/work-authorizations/{wa_id}/sign", None, headers
        )

    # --- invoices ---
    def create_invoice(self, claim_id, headers):
        return self._request("POST", f"/v1/claims/{claim_id}/invoices", None, headers)

    def list_invoices(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/v1/claims/{claim_id}/invoices", headers=headers, params=params
        )

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/v1/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/v1/invoices/{invoice_id}/issue", None, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/v1/invoices/{invoice_id}/void", None, headers)

    def list_invoice_payments(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/v1/invoices/{invoice_id}/payments", headers=headers, params=params
        )

    # --- payments ---
    def create_payment(self, claim_id, payload, headers):
        return self._request("POST", f"/v1/claims/{claim_id}/payments", payload, headers)

    def list_payments(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/v1/claims/{claim_id}/payments", headers=headers, params=params
        )

    def approve_payment(self, payment_id, headers):
        return self._request("POST", f"/v1/payments/{payment_id}/approve", None, headers)

    def issue_payment(self, payment_id, headers):
        return self._request("POST", f"/v1/payments/{payment_id}/issue", None, headers)

    def clear_payment(self, payment_id, headers):
        return self._request("POST", f"/v1/payments/{payment_id}/clear", None, headers)

    def return_payment(self, payment_id, headers):
        return self._request("POST", f"/v1/payments/{payment_id}/return", None, headers)

    def requeue_payment(self, payment_id, headers):
        return self._request("POST", f"/v1/payments/{payment_id}/requeue", None, headers)


api_client = ApiClient()
