"""API client: one method per endpoint defined in the Lymphedema & Specialty Rehab API."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # ---- Evaluation ----
    def create_evaluation(self, payload, headers):
        return self._request("POST", "/evaluations", payload, headers)

    def list_evaluations(self, headers, params=None):
        return self._request("GET", "/evaluations", headers=headers, params=params)

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/evaluations/{evaluation_id}", headers=headers)

    def finalize_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/evaluations/{evaluation_id}/finalize", {}, headers)

    # ---- Authorization ----
    def create_authorization(self, payload, headers):
        return self._request("POST", "/authorizations", payload, headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/authorizations", headers=headers, params=params)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET", f"/authorizations/{authorization_id}", headers=headers)

    def submit_authorization(self, authorization_id, headers):
        return self._request("POST", f"/authorizations/{authorization_id}/submit", {}, headers)

    def approve_authorization(self, authorization_id, headers):
        return self._request("POST", f"/authorizations/{authorization_id}/approve", {}, headers)

    def deny_authorization(self, authorization_id, headers):
        return self._request("POST", f"/authorizations/{authorization_id}/deny", {}, headers)

    def renew_authorization(self, authorization_id, payload, headers):
        return self._request("POST", f"/authorizations/{authorization_id}/renew", payload, headers)

    # ---- TreatmentPlan ----
    def create_treatment_plan(self, payload, headers):
        return self._request("POST", "/treatment-plans", payload, headers)

    def list_treatment_plans(self, headers, params=None):
        return self._request("GET", "/treatment-plans", headers=headers, params=params)

    def get_treatment_plan(self, plan_id, headers):
        return self._request("GET", f"/treatment-plans/{plan_id}", headers=headers)

    def activate_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/activate", {}, headers)

    def complete_treatment_plan(self, plan_id, headers):
        return self._request("POST", f"/treatment-plans/{plan_id}/complete", {}, headers)

    # ---- Therapist ----
    def create_therapist(self, payload, headers):
        return self._request("POST", "/therapists", payload, headers)

    def list_therapists(self, headers, params=None):
        return self._request("GET", "/therapists", headers=headers, params=params)

    def get_therapist(self, therapist_id, headers):
        return self._request("GET", f"/therapists/{therapist_id}", headers=headers)

    # ---- Session ----
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def check_in_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/check-in", {}, headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/complete", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", {}, headers)

    def no_show_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/no-show", {}, headers)

    # ---- GarmentOrder ----
    def create_garment_order(self, payload, headers):
        return self._request("POST", "/garment-orders", payload, headers)

    def list_garment_orders(self, headers, params=None):
        return self._request("GET", "/garment-orders", headers=headers, params=params)

    def get_garment_order(self, garment_order_id, headers):
        return self._request("GET", f"/garment-orders/{garment_order_id}", headers=headers)

    def approve_garment_order(self, garment_order_id, headers):
        return self._request("POST", f"/garment-orders/{garment_order_id}/approve", {}, headers)

    def deny_garment_order(self, garment_order_id, headers):
        return self._request("POST", f"/garment-orders/{garment_order_id}/deny", {}, headers)

    # ---- DMEItem ----
    def create_dme_item(self, payload, headers):
        return self._request("POST", "/dme-items", payload, headers)

    def list_dme_items(self, headers, params=None):
        return self._request("GET", "/dme-items", headers=headers, params=params)

    def get_dme_item(self, dme_item_id, headers):
        return self._request("GET", f"/dme-items/{dme_item_id}", headers=headers)

    # ---- Dispense ----
    def create_dispense(self, payload, headers):
        return self._request("POST", "/dispenses", payload, headers)

    def list_dispenses(self, headers, params=None):
        return self._request("GET", "/dispenses", headers=headers, params=params)

    def get_dispense(self, dispense_id, headers):
        return self._request("GET", f"/dispenses/{dispense_id}", headers=headers)

    def return_dispense(self, dispense_id, headers):
        return self._request("POST", f"/dispenses/{dispense_id}/return", {}, headers)

    # ---- Reassessment ----
    def create_reassessment(self, payload, headers):
        return self._request("POST", "/reassessments", payload, headers)

    def list_reassessments(self, headers, params=None):
        return self._request("GET", "/reassessments", headers=headers, params=params)

    def get_reassessment(self, reassessment_id, headers):
        return self._request("GET", f"/reassessments/{reassessment_id}", headers=headers)

    def finalize_reassessment(self, reassessment_id, headers):
        return self._request("POST", f"/reassessments/{reassessment_id}/finalize", {}, headers)

    # ---- AdherenceLog ----
    def create_adherence_log(self, payload, headers):
        return self._request("POST", "/adherence-logs", payload, headers)

    def list_adherence_logs(self, headers, params=None):
        return self._request("GET", "/adherence-logs", headers=headers, params=params)

    def get_adherence_log(self, adherence_log_id, headers):
        return self._request("GET", f"/adherence-logs/{adherence_log_id}", headers=headers)

    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
