"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Patients ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # --- Providers ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    # --- Insurance policies ---
    def create_insurance_policy(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/insurance-policies",
                             payload, headers)

    def list_insurance_policies(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/insurance-policies",
                             headers=headers, params=params)

    # --- Intake assessments ---
    def create_intake_assessment(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/intake-assessments",
                             payload, headers)

    def submit_intake(self, intake_id, headers):
        return self._request("POST", f"/intake-assessments/{intake_id}/submit",
                             {}, headers)

    def clear_intake(self, intake_id, headers):
        return self._request("POST", f"/intake-assessments/{intake_id}/clear",
                             {}, headers)

    def get_intake(self, intake_id, headers):
        return self._request("GET", f"/intake-assessments/{intake_id}", headers=headers)

    def list_intake_assessments(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/intake-assessments",
                             headers=headers, params=params)

    # --- Visits ---
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def complete_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/complete", {}, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", {}, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    # --- Prescriptions ---
    def create_prescription(self, payload, headers):
        return self._request("POST", "/prescriptions", payload, headers)

    def suspend_prescription(self, rx_id, headers, payload=None):
        return self._request("POST", f"/prescriptions/{rx_id}/suspend",
                             payload or {}, headers)

    def reactivate_prescription(self, rx_id, headers):
        return self._request("POST", f"/prescriptions/{rx_id}/reactivate", {}, headers)

    def discontinue_prescription(self, rx_id, headers, payload=None):
        return self._request("POST", f"/prescriptions/{rx_id}/discontinue",
                             payload or {}, headers)

    def get_prescription(self, rx_id, headers):
        return self._request("GET", f"/prescriptions/{rx_id}", headers=headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/prescriptions", headers=headers, params=params)

    # --- Lab orders ---
    def create_lab_order(self, rx_id, payload, headers):
        return self._request("POST", f"/prescriptions/{rx_id}/lab-orders",
                             payload, headers)

    def resolve_lab_order(self, lab_id, payload, headers):
        return self._request("POST", f"/lab-orders/{lab_id}/resolve", payload, headers)

    def get_lab_order(self, lab_id, headers):
        return self._request("GET", f"/lab-orders/{lab_id}", headers=headers)

    def list_lab_orders(self, rx_id, headers, params=None):
        return self._request("GET", f"/prescriptions/{rx_id}/lab-orders",
                             headers=headers, params=params)

    # --- Refills ---
    def request_refill(self, rx_id, headers):
        return self._request("POST", f"/prescriptions/{rx_id}/refills", {}, headers)

    def approve_refill(self, refill_id, headers):
        return self._request("POST", f"/refills/{refill_id}/approve", {}, headers)

    def deny_refill(self, refill_id, headers, payload=None):
        return self._request("POST", f"/refills/{refill_id}/deny", payload or {}, headers)

    def fulfill_refill(self, refill_id, headers):
        return self._request("POST", f"/refills/{refill_id}/fulfill", {}, headers)

    def reverse_refill(self, refill_id, headers, payload=None):
        return self._request("POST", f"/refills/{refill_id}/reverse", payload or {}, headers)

    def get_refill(self, refill_id, headers):
        return self._request("GET", f"/refills/{refill_id}", headers=headers)

    def list_refills(self, rx_id, headers, params=None):
        return self._request("GET", f"/prescriptions/{rx_id}/refills",
                             headers=headers, params=params)

    # --- Subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def cancel_subscription(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/cancel", {}, headers)

    def mark_past_due(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/mark-past-due", {}, headers)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"/subscriptions/{sub_id}", headers=headers)

    def list_subscriptions(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/subscriptions",
                             headers=headers, params=params)

    # --- Charges ---
    def adjudicate_charge(self, charge_id, headers):
        return self._request("POST", f"/charges/{charge_id}/adjudicate", {}, headers)

    def reverse_charge(self, charge_id, headers, payload=None):
        return self._request("POST", f"/charges/{charge_id}/reverse", payload or {}, headers)

    def get_charge(self, charge_id, headers):
        return self._request("GET", f"/charges/{charge_id}", headers=headers)

    def list_charges(self, headers, params=None):
        return self._request("GET", "/charges", headers=headers, params=params)

    # --- Care plans ---
    def get_care_plan(self, cp_id, headers):
        return self._request("GET", f"/care-plans/{cp_id}", headers=headers)

    def list_care_plans(self, headers, params=None):
        return self._request("GET", "/care-plans", headers=headers, params=params)

    # --- Care-plan messages ---
    def create_care_plan_message(self, cp_id, payload, headers):
        return self._request("POST", f"/care-plans/{cp_id}/messages", payload, headers)

    def list_care_plan_messages(self, cp_id, headers, params=None):
        return self._request("GET", f"/care-plans/{cp_id}/messages",
                             headers=headers, params=params)


api_client = ApiClient()
