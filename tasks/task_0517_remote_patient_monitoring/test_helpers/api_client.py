"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Payer ----
    def create_payer(self, payload, headers):
        return self._request("POST", "/payers", payload, headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/payers/{payer_id}", headers=headers)

    def list_payers(self, headers, params=None):
        return self._request("GET", "/payers", headers=headers, params=params)

    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def enroll_patient(self, patient_id, headers):
        return self._request("POST", f"/patients/{patient_id}/enroll", {}, headers)

    def suspend_patient(self, patient_id, headers):
        return self._request("POST", f"/patients/{patient_id}/suspend", {}, headers)

    def discharge_patient(self, patient_id, headers):
        return self._request("POST", f"/patients/{patient_id}/discharge", {}, headers)

    # ---- ConsentRecord ----
    def create_consent(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/consents", payload, headers)

    def list_consents(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/consents", headers=headers, params=params)

    def revoke_consent(self, patient_id, consent_id, headers):
        return self._request("POST", f"/patients/{patient_id}/consents/{consent_id}/revoke", {}, headers)

    # ---- CarePlan ----
    def create_care_plan(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/care-plans", payload, headers)

    def list_care_plans(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/care-plans", headers=headers, params=params)

    def get_care_plan(self, plan_id, headers):
        return self._request("GET", f"/care-plans/{plan_id}", headers=headers)

    def activate_care_plan(self, patient_id, plan_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/care-plans/{plan_id}/activate", payload, headers)

    # ---- Device ----
    def create_device(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/devices", payload, headers)

    def list_devices(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/devices", headers=headers, params=params)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/devices/{device_id}", headers=headers)

    def activate_device(self, patient_id, device_id, headers):
        return self._request("POST", f"/patients/{patient_id}/devices/{device_id}/activate", {}, headers)

    def return_device(self, patient_id, device_id, headers):
        return self._request("POST", f"/patients/{patient_id}/devices/{device_id}/return", {}, headers)

    # ---- VitalsReading ----
    def create_vitals(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/vitals", payload, headers)

    def list_patient_vitals(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/vitals", headers=headers, params=params)

    def list_device_vitals(self, device_id, headers, params=None):
        return self._request("GET", f"/devices/{device_id}/vitals", headers=headers, params=params)

    # ---- ThresholdAlert ----
    def list_alerts(self, headers, params=None):
        return self._request("GET", "/alerts", headers=headers, params=params)

    def get_alert(self, alert_id, headers):
        return self._request("GET", f"/alerts/{alert_id}", headers=headers)

    def acknowledge_alert(self, alert_id, headers):
        return self._request("POST", f"/alerts/{alert_id}/acknowledge", {}, headers)

    def escalate_alert(self, alert_id, headers):
        return self._request("POST", f"/alerts/{alert_id}/escalate", {}, headers)

    def resolve_alert(self, alert_id, headers):
        return self._request("POST", f"/alerts/{alert_id}/resolve", {}, headers)

    # ---- ReviewTask ----
    def list_review_tasks(self, headers, params=None):
        return self._request("GET", "/review-tasks", headers=headers, params=params)

    def get_review_task(self, task_id, headers):
        return self._request("GET", f"/review-tasks/{task_id}", headers=headers)

    def claim_review_task(self, task_id, headers):
        return self._request("POST", f"/review-tasks/{task_id}/claim", {}, headers)

    def sign_review_task(self, task_id, headers):
        return self._request("POST", f"/review-tasks/{task_id}/sign", {}, headers)

    def escalate_review_task(self, task_id, headers):
        return self._request("POST", f"/review-tasks/{task_id}/escalate", {}, headers)

    # ---- BillingPeriod ----
    def create_billing_period(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/billing-periods", payload, headers)

    def list_billing_periods(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/billing-periods", headers=headers, params=params)

    def get_billing_period(self, period_id, headers):
        return self._request("GET", f"/billing-periods/{period_id}", headers=headers)

    def finalize_billing_period(self, period_id, payload, headers):
        return self._request("POST", f"/billing-periods/{period_id}/finalize", payload, headers)

    def reopen_billing_period(self, period_id, headers):
        return self._request("POST", f"/billing-periods/{period_id}/reopen", {}, headers)

    # ---- BillingLineItem ----
    def list_line_items(self, period_id, headers, params=None):
        return self._request("GET", f"/billing-periods/{period_id}/line-items", headers=headers, params=params)

    # ---- CareActivity ----
    def create_care_activity(self, patient_id, payload, headers):
        return self._request("POST", f"/patients/{patient_id}/care-activities", payload, headers)

    def list_patient_care_activities(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/care-activities", headers=headers, params=params)

    def list_period_care_activities(self, period_id, headers, params=None):
        return self._request("GET", f"/billing-periods/{period_id}/care-activities", headers=headers, params=params)

    # ---- Claim ----
    def submit_claim(self, period_id, headers):
        return self._request("POST", f"/billing-periods/{period_id}/claims", {}, headers)

    def list_period_claims(self, period_id, headers, params=None):
        return self._request("GET", f"/billing-periods/{period_id}/claims", headers=headers, params=params)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def accept_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/accept", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", {}, headers)

    def remit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/remit", payload, headers)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
