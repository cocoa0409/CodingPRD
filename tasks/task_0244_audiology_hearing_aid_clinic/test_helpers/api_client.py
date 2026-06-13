"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/clinic/_clock/set", {"to_iso8601": to_iso8601}, headers)

    # ---- Patients ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/clinic/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/clinic/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/clinic/patients", headers=headers, params=params)

    # ---- Device models ----
    def create_device_model(self, payload, headers):
        return self._request("POST", "/clinic/device-models", payload, headers)

    def get_device_model(self, model_id, headers):
        return self._request("GET", f"/clinic/device-models/{model_id}", headers=headers)

    def list_device_models(self, headers, params=None):
        return self._request("GET", "/clinic/device-models", headers=headers, params=params)

    def patch_device_model(self, model_id, payload, headers):
        return self._request("PATCH", f"/clinic/device-models/{model_id}", payload, headers)

    # ---- Allowance benefits ----
    def create_allowance_benefit(self, payload, headers):
        return self._request("POST", "/clinic/allowance-benefits", payload, headers)

    def get_allowance_benefit(self, benefit_id, headers):
        return self._request("GET", f"/clinic/allowance-benefits/{benefit_id}", headers=headers)

    def list_allowance_benefits(self, headers, params=None):
        return self._request("GET", "/clinic/allowance-benefits", headers=headers, params=params)

    # ---- Hearing evaluations ----
    def create_evaluation(self, payload, headers):
        return self._request("POST", "/clinic/evaluations", payload, headers)

    def finalize_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/clinic/evaluations/{evaluation_id}/finalize", {}, headers)

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/clinic/evaluations/{evaluation_id}", headers=headers)

    def list_patient_evaluations(self, patient_id, headers, params=None):
        return self._request("GET", f"/clinic/patients/{patient_id}/evaluations", headers=headers, params=params)

    # ---- Fitting orders ----
    def create_order(self, payload, headers):
        return self._request("POST", "/clinic/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/clinic/orders/{order_id}", headers=headers)

    def list_patient_orders(self, patient_id, headers, params=None):
        return self._request("GET", f"/clinic/patients/{patient_id}/orders", headers=headers, params=params)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/clinic/orders", headers=headers, params=params)

    def start_trial(self, order_id, headers):
        return self._request("POST", f"/clinic/orders/{order_id}/start-trial", {}, headers)

    def purchase_order(self, order_id, headers):
        return self._request("POST", f"/clinic/orders/{order_id}/purchase", {}, headers)

    def return_order(self, order_id, headers):
        return self._request("POST", f"/clinic/orders/{order_id}/return", {}, headers)

    def activate_warranty(self, order_id, headers):
        return self._request("POST", f"/clinic/orders/{order_id}/activate-warranty", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/clinic/orders/{order_id}/cancel", {}, headers)

    # ---- Adjustment sessions ----
    def create_adjustment(self, order_id, payload, headers):
        return self._request("POST", f"/clinic/orders/{order_id}/adjustments", payload, headers)

    def list_order_adjustments(self, order_id, headers, params=None):
        return self._request("GET", f"/clinic/orders/{order_id}/adjustments", headers=headers, params=params)

    # ---- Warranty claims ----
    def create_warranty_claim(self, order_id, payload, headers):
        return self._request("POST", f"/clinic/orders/{order_id}/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/clinic/warranty-claims/{claim_id}", headers=headers)

    def list_order_warranty_claims(self, order_id, headers, params=None):
        return self._request("GET", f"/clinic/orders/{order_id}/warranty-claims", headers=headers, params=params)

    def approve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/clinic/warranty-claims/{claim_id}/approve", {}, headers)

    def deny_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/clinic/warranty-claims/{claim_id}/deny", {}, headers)

    def appeal_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/clinic/warranty-claims/{claim_id}/appeal", {}, headers)

    def replace_warranty_claim(self, claim_id, expected_warranty_claim_version, headers):
        payload = {"expected_warranty_claim_version": expected_warranty_claim_version}
        return self._request("POST", f"/clinic/warranty-claims/{claim_id}/replace", payload, headers)

    # ---- Supply subscriptions ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/clinic/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/clinic/subscriptions/{subscription_id}", headers=headers)

    def list_patient_subscriptions(self, patient_id, headers, params=None):
        return self._request("GET", f"/clinic/patients/{patient_id}/subscriptions", headers=headers, params=params)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/clinic/subscriptions", headers=headers, params=params)

    def pause_subscription(self, subscription_id, headers):
        return self._request("POST", f"/clinic/subscriptions/{subscription_id}/pause", {}, headers)

    def resume_subscription(self, subscription_id, headers):
        return self._request("POST", f"/clinic/subscriptions/{subscription_id}/resume", {}, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/clinic/subscriptions/{subscription_id}/cancel", {}, headers)

    def schedule_cycle(self, subscription_id, headers):
        return self._request("POST", f"/clinic/subscriptions/{subscription_id}/cycles", {}, headers)

    def list_subscription_cycles(self, subscription_id, headers, params=None):
        return self._request("GET", f"/clinic/subscriptions/{subscription_id}/cycles", headers=headers, params=params)

    # ---- Supply cycles ----
    def get_supply_cycle(self, cycle_id, headers):
        return self._request("GET", f"/clinic/supply-cycles/{cycle_id}", headers=headers)

    def ship_cycle(self, cycle_id, headers):
        return self._request("POST", f"/clinic/supply-cycles/{cycle_id}/ship", {}, headers)

    def skip_cycle(self, cycle_id, headers):
        return self._request("POST", f"/clinic/supply-cycles/{cycle_id}/skip", {}, headers)

    # ---- Recalls ----
    def create_recall(self, payload, headers):
        return self._request("POST", "/clinic/recalls", payload, headers)

    def issue_recall(self, recall_id, expected_recall_notice_version, headers):
        payload = {"expected_recall_notice_version": expected_recall_notice_version}
        return self._request("POST", f"/clinic/recalls/{recall_id}/issue", payload, headers)

    def close_recall(self, recall_id, headers):
        return self._request("POST", f"/clinic/recalls/{recall_id}/close", {}, headers)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/clinic/recalls/{recall_id}", headers=headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/clinic/recalls", headers=headers, params=params)

    def list_recall_adjustments(self, recall_id, headers, params=None):
        return self._request("GET", f"/clinic/recalls/{recall_id}/adjustments", headers=headers, params=params)

    # ---- Ledger ----
    def list_patient_ledger(self, patient_id, headers, params=None):
        return self._request("GET", f"/clinic/patients/{patient_id}/ledger", headers=headers, params=params)


api_client = ApiClient()
