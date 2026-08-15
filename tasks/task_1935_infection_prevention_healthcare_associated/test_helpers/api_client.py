"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Facilities ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/api/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/api/facilities/{facility_id}", headers=headers)

    def update_facility(self, facility_id, payload, headers):
        return self._request("PUT", f"/api/facilities/{facility_id}", payload, headers)

    # --- Units ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/api/units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/api/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/api/units/{unit_id}", headers=headers)

    def get_hand_hygiene_rate(self, unit_id, month, headers):
        return self._request(
            "GET",
            f"/api/units/{unit_id}/hand-hygiene-rate",
            headers=headers,
            params={"month": month},
        )

    # --- Patients ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/api/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/api/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/api/patients/{patient_id}", headers=headers)

    def transfer_patient(self, patient_id, payload, headers):
        return self._request("POST", f"/api/patients/{patient_id}/transfer", payload, headers)

    def discharge_patient(self, patient_id, payload, headers):
        return self._request("POST", f"/api/patients/{patient_id}/discharge", payload, headers)

    # --- Employees ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/api/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/api/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/api/employees/{employee_id}", headers=headers)

    # --- Device episodes ---
    def create_device_episode(self, payload, headers):
        return self._request("POST", "/api/device-episodes", payload, headers)

    def list_device_episodes(self, headers, params=None):
        return self._request("GET", "/api/device-episodes", headers=headers, params=params)

    def get_device_episode(self, episode_id, headers):
        return self._request("GET", f"/api/device-episodes/{episode_id}", headers=headers)

    def remove_device_episode(self, episode_id, payload, headers):
        return self._request("POST", f"/api/device-episodes/{episode_id}/remove", payload, headers)

    # --- Surgical procedures ---
    def create_surgical_procedure(self, payload, headers):
        return self._request("POST", "/api/surgical-procedures", payload, headers)

    def list_surgical_procedures(self, headers, params=None):
        return self._request("GET", "/api/surgical-procedures", headers=headers, params=params)

    def get_surgical_procedure(self, procedure_id, headers):
        return self._request("GET", f"/api/surgical-procedures/{procedure_id}", headers=headers)

    # --- Infection cases ---
    def create_infection_case(self, payload, headers):
        return self._request("POST", "/api/infection-cases", payload, headers)

    def list_infection_cases(self, headers, params=None):
        return self._request("GET", "/api/infection-cases", headers=headers, params=params)

    def get_infection_case(self, case_id, headers):
        return self._request("GET", f"/api/infection-cases/{case_id}", headers=headers)

    def begin_review(self, case_id, headers):
        return self._request("POST", f"/api/infection-cases/{case_id}/begin-review", {}, headers)

    def adjudicate_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/infection-cases/{case_id}/adjudicate", payload, headers)

    def reopen_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/infection-cases/{case_id}/reopen", payload, headers)

    # --- Device day counts ---
    def create_device_day_count(self, payload, headers):
        return self._request("POST", "/api/device-day-counts", payload, headers)

    def list_device_day_counts(self, headers, params=None):
        return self._request("GET", "/api/device-day-counts", headers=headers, params=params)

    def reconcile_device_day_counts(self, unit_id, device_type, count_date, headers):
        return self._request(
            "GET",
            "/api/device-day-counts/reconcile",
            headers=headers,
            params={"unit_id": unit_id, "device_type": device_type, "count_date": count_date},
        )

    def get_device_day_count(self, count_id, headers):
        return self._request("GET", f"/api/device-day-counts/{count_id}", headers=headers)

    def update_device_day_count(self, count_id, payload, headers):
        return self._request("PUT", f"/api/device-day-counts/{count_id}", payload, headers)

    # --- Monthly summaries ---
    def create_monthly_summary(self, payload, headers):
        return self._request("POST", "/api/monthly-summaries", payload, headers)

    def list_monthly_summaries(self, headers, params=None):
        return self._request("GET", "/api/monthly-summaries", headers=headers, params=params)

    def get_monthly_summary(self, summary_id, headers):
        return self._request("GET", f"/api/monthly-summaries/{summary_id}", headers=headers)

    def submit_summary(self, summary_id, headers):
        return self._request("POST", f"/api/monthly-summaries/{summary_id}/submit", {}, headers)

    def accept_summary(self, summary_id, headers):
        return self._request("POST", f"/api/monthly-summaries/{summary_id}/accept", {}, headers)

    def reject_summary(self, summary_id, payload, headers):
        return self._request("POST", f"/api/monthly-summaries/{summary_id}/reject", payload, headers)

    def amend_summary(self, summary_id, payload, headers):
        return self._request("POST", f"/api/monthly-summaries/{summary_id}/amend", payload, headers)

    # --- Outbreak investigations ---
    def create_outbreak_investigation(self, payload, headers):
        return self._request("POST", "/api/outbreak-investigations", payload, headers)

    def list_outbreak_investigations(self, headers, params=None):
        return self._request("GET", "/api/outbreak-investigations", headers=headers, params=params)

    def get_outbreak_investigation(self, investigation_id, headers):
        return self._request(
            "GET", f"/api/outbreak-investigations/{investigation_id}", headers=headers
        )

    def confirm_investigation(self, investigation_id, headers):
        return self._request(
            "POST", f"/api/outbreak-investigations/{investigation_id}/confirm", {}, headers
        )

    def rule_out_investigation(self, investigation_id, payload, headers):
        return self._request(
            "POST", f"/api/outbreak-investigations/{investigation_id}/rule-out", payload, headers
        )

    def close_investigation(self, investigation_id, headers):
        return self._request(
            "POST", f"/api/outbreak-investigations/{investigation_id}/close", {}, headers
        )

    # --- Isolation orders ---
    def create_isolation_order(self, payload, headers):
        return self._request("POST", "/api/isolation-orders", payload, headers)

    def list_isolation_orders(self, headers, params=None):
        return self._request("GET", "/api/isolation-orders", headers=headers, params=params)

    def get_isolation_order(self, order_id, headers):
        return self._request("GET", f"/api/isolation-orders/{order_id}", headers=headers)

    def start_isolation_order(self, order_id, headers):
        return self._request("POST", f"/api/isolation-orders/{order_id}/start", {}, headers)

    def discontinue_isolation_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/isolation-orders/{order_id}/discontinue", {}, headers
        )

    # --- Isolation compliance audits ---
    def create_isolation_audit(self, payload, headers):
        return self._request("POST", "/api/isolation-compliance-audits", payload, headers)

    def list_isolation_audits(self, headers, params=None):
        return self._request("GET", "/api/isolation-compliance-audits", headers=headers, params=params)

    def get_isolation_audit(self, audit_id, headers):
        return self._request("GET", f"/api/isolation-compliance-audits/{audit_id}", headers=headers)

    # --- Hand hygiene observations ---
    def create_hand_hygiene_observation(self, payload, headers):
        return self._request("POST", "/api/hand-hygiene-observations", payload, headers)

    def list_hand_hygiene_observations(self, headers, params=None):
        return self._request("GET", "/api/hand-hygiene-observations", headers=headers, params=params)

    def get_hand_hygiene_observation(self, observation_id, headers):
        return self._request(
            "GET", f"/api/hand-hygiene-observations/{observation_id}", headers=headers
        )

    # --- Employee exposures ---
    def create_employee_exposure(self, payload, headers):
        return self._request("POST", "/api/employee-exposures", payload, headers)

    def list_employee_exposures(self, headers, params=None):
        return self._request("GET", "/api/employee-exposures", headers=headers, params=params)

    def get_employee_exposure(self, exposure_id, headers):
        return self._request("GET", f"/api/employee-exposures/{exposure_id}", headers=headers)

    def record_source_serologies(self, exposure_id, payload, headers):
        return self._request(
            "POST",
            f"/api/employee-exposures/{exposure_id}/record-source-serologies",
            payload,
            headers,
        )

    def record_draw(self, exposure_id, payload, headers):
        return self._request(
            "POST", f"/api/employee-exposures/{exposure_id}/record-draw", payload, headers
        )

    def mark_lost_to_followup(self, exposure_id, headers):
        return self._request(
            "POST", f"/api/employee-exposures/{exposure_id}/mark-lost-to-followup", {}, headers
        )

    # --- Corrective action plans ---
    def create_corrective_action_plan(self, payload, headers):
        return self._request("POST", "/api/corrective-action-plans", payload, headers)

    def list_corrective_action_plans(self, headers, params=None):
        return self._request("GET", "/api/corrective-action-plans", headers=headers, params=params)

    def get_corrective_action_plan(self, cap_id, headers):
        return self._request("GET", f"/api/corrective-action-plans/{cap_id}", headers=headers)

    def activate_cap(self, cap_id, headers):
        return self._request(
            "POST", f"/api/corrective-action-plans/{cap_id}/activate", {}, headers
        )

    def submit_cap_for_verification(self, cap_id, payload, headers):
        return self._request(
            "POST",
            f"/api/corrective-action-plans/{cap_id}/submit-for-verification",
            payload,
            headers,
        )

    def verify_cap(self, cap_id, headers):
        return self._request("POST", f"/api/corrective-action-plans/{cap_id}/verify", {}, headers)

    def fail_cap_verification(self, cap_id, payload, headers):
        return self._request(
            "POST", f"/api/corrective-action-plans/{cap_id}/fail-verification", payload, headers
        )


api_client = ApiClient()
