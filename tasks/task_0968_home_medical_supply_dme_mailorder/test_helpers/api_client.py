"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- payer plans ----
    def create_payer_plan(self, payload, headers):
        return self._request("POST", "/api/payer-plans", payload, headers)

    def get_payer_plan(self, plan_id, headers):
        return self._request("GET", f"/api/payer-plans/{plan_id}", headers=headers)

    def list_plan_patients(self, plan_id, headers, params=None):
        return self._request("GET", f"/api/payer-plans/{plan_id}/patients", headers=headers, params=params)

    # ---- formulary items ----
    def create_formulary_item(self, payload, headers):
        return self._request("POST", "/api/formulary-items", payload, headers)

    def get_formulary_item(self, item_id, headers):
        return self._request("GET", f"/api/formulary-items/{item_id}", headers=headers)

    def list_formulary_items(self, headers, params=None):
        return self._request("GET", "/api/formulary-items", headers=headers, params=params)

    def list_item_order_lines(self, item_id, headers, params=None):
        return self._request("GET", f"/api/formulary-items/{item_id}/order-lines", headers=headers, params=params)

    def list_item_stock_levels(self, item_id, headers):
        return self._request("GET", f"/api/formulary-items/{item_id}/stock-levels", headers=headers)

    # ---- patients ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/api/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/api/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/api/patients", headers=headers, params=params)

    def verify_eligibility(self, patient_id, payload, headers):
        return self._request("POST", f"/api/patients/{patient_id}/verify-eligibility", payload, headers)

    def list_patient_prescriptions(self, patient_id, headers, params=None):
        return self._request("GET", f"/api/patients/{patient_id}/prescriptions", headers=headers, params=params)

    def list_patient_fit_profiles(self, patient_id, headers, params=None):
        return self._request("GET", f"/api/patients/{patient_id}/fit-profiles", headers=headers, params=params)

    def list_patient_resupply_programs(self, patient_id, headers, params=None):
        return self._request("GET", f"/api/patients/{patient_id}/resupply-programs", headers=headers, params=params)

    def list_patient_orders(self, patient_id, headers, params=None):
        return self._request("GET", f"/api/patients/{patient_id}/orders", headers=headers, params=params)

    def list_patient_prior_authorizations(self, patient_id, headers, params=None):
        return self._request("GET", f"/api/patients/{patient_id}/prior-authorizations", headers=headers, params=params)

    def list_patient_hsa_accounts(self, patient_id, headers):
        return self._request("GET", f"/api/patients/{patient_id}/hsa-accounts", headers=headers)

    def list_patient_fitting_samples(self, patient_id, headers, params=None):
        return self._request("GET", f"/api/patients/{patient_id}/fitting-samples", headers=headers, params=params)

    # ---- prescriptions ----
    def create_prescription(self, payload, headers):
        return self._request("POST", "/api/prescriptions", payload, headers)

    def get_prescription(self, rx_id, headers):
        return self._request("GET", f"/api/prescriptions/{rx_id}", headers=headers)

    def cancel_prescription(self, rx_id, headers):
        return self._request("POST", f"/api/prescriptions/{rx_id}/cancel", {}, headers)

    # ---- fit profiles ----
    def create_fit_profile(self, payload, headers):
        return self._request("POST", "/api/fit-profiles", payload, headers)

    def get_fit_profile(self, profile_id, headers):
        return self._request("GET", f"/api/fit-profiles/{profile_id}", headers=headers)

    # ---- resupply programs ----
    def create_resupply_program(self, payload, headers):
        return self._request("POST", "/api/resupply-programs", payload, headers)

    def get_resupply_program(self, program_id, headers):
        return self._request("GET", f"/api/resupply-programs/{program_id}", headers=headers)

    def confirm_cycle(self, program_id, headers):
        return self._request("POST", f"/api/resupply-programs/{program_id}/confirm-cycle", {}, headers)

    def suspend_program(self, program_id, payload, headers):
        return self._request("POST", f"/api/resupply-programs/{program_id}/suspend", payload, headers)

    def resume_program(self, program_id, headers):
        return self._request("POST", f"/api/resupply-programs/{program_id}/resume", {}, headers)

    def list_program_orders(self, program_id, headers, params=None):
        return self._request("GET", f"/api/resupply-programs/{program_id}/orders", headers=headers, params=params)

    # ---- orders & lines ----
    def create_order(self, payload, headers):
        return self._request("POST", "/api/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/api/orders/{order_id}/lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/api/order-lines/{line_id}", headers=headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/submit", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/cancel", {}, headers)

    # ---- shipments & stock ----
    def create_shipment(self, payload, headers):
        return self._request("POST", "/api/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/api/shipments/{shipment_id}", headers=headers)

    def list_order_shipments(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}/shipments", headers=headers)

    def release_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/release", {}, headers)

    def ship_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/ship", {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/deliver", {}, headers)

    def return_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/return", {}, headers)

    def create_stock_level(self, payload, headers):
        return self._request("POST", "/api/stock-levels", payload, headers)

    def get_stock_level(self, stock_id, headers):
        return self._request("GET", f"/api/stock-levels/{stock_id}", headers=headers)

    def restock_stock_level(self, stock_id, payload, headers):
        return self._request("POST", f"/api/stock-levels/{stock_id}/restock", payload, headers)

    def list_line_backorder_reservations(self, line_id, headers):
        return self._request("GET", f"/api/order-lines/{line_id}/backorder-reservations", headers=headers)

    # ---- prior authorizations ----
    def create_prior_authorization(self, payload, headers):
        return self._request("POST", "/api/prior-authorizations", payload, headers)

    def get_prior_authorization(self, pa_id, headers):
        return self._request("GET", f"/api/prior-authorizations/{pa_id}", headers=headers)

    def decide_prior_authorization(self, pa_id, payload, headers):
        return self._request("POST", f"/api/prior-authorizations/{pa_id}/decision", payload, headers)

    def appeal_prior_authorization(self, pa_id, headers):
        return self._request("POST", f"/api/prior-authorizations/{pa_id}/appeal", {}, headers)

    # ---- claims & HSA ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/api/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}", headers=headers)

    def list_order_claims(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}/claims", headers=headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/submit", {}, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/adjudicate", payload, headers)

    def appeal_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/appeal", {}, headers)

    def get_hsa_account(self, account_id, headers):
        return self._request("GET", f"/api/hsa-accounts/{account_id}", headers=headers)

    def post_hsa_debit(self, account_id, payload, headers):
        return self._request("POST", f"/api/hsa-accounts/{account_id}/debits", payload, headers)

    def post_hsa_credit(self, account_id, payload, headers):
        return self._request("POST", f"/api/hsa-accounts/{account_id}/credits", payload, headers)

    def list_hsa_entries(self, account_id, headers, params=None):
        return self._request("GET", f"/api/hsa-accounts/{account_id}/entries", headers=headers, params=params)

    # ---- fitting samples ----
    def create_fitting_sample(self, payload, headers):
        return self._request("POST", "/api/fitting-samples", payload, headers)

    def get_fitting_sample(self, sample_id, headers):
        return self._request("GET", f"/api/fitting-samples/{sample_id}", headers=headers)

    def ship_fitting_sample(self, sample_id, headers):
        return self._request("POST", f"/api/fitting-samples/{sample_id}/ship", {}, headers)

    def record_sample_outcome(self, sample_id, payload, headers):
        return self._request("POST", f"/api/fitting-samples/{sample_id}/record-outcome", payload, headers)

    # ---- logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
