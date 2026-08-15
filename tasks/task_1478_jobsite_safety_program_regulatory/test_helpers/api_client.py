"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock (PRD §2.5) ───
    def set_clock(self, payload, headers):
        return self._request("POST", "/safety/_clock/set_current_utc", payload, headers)

    # ─── Projects (PRD §3.1) ───
    def create_project(self, payload, headers):
        return self._request("POST", "/safety/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/safety/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/safety/projects/{project_id}", headers=headers)

    def get_osha_summary(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/safety/projects/{project_id}/osha-summary",
            headers=headers, params=params,
        )

    # ─── Safety plans (PRD §3.1) ───
    def create_safety_plan(self, payload, headers):
        return self._request("POST", "/safety/safety-plans", payload, headers)

    def list_safety_plans(self, headers, params=None):
        return self._request("GET", "/safety/safety-plans", headers=headers, params=params)

    def get_safety_plan(self, plan_id, headers):
        return self._request("GET", f"/safety/safety-plans/{plan_id}", headers=headers)

    def activate_safety_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/safety/safety-plans/{plan_id}/activate", payload, headers
        )

    # ─── Workers (PRD §3.2) ───
    def create_worker(self, payload, headers):
        return self._request("POST", "/safety/workers", payload, headers)

    def list_workers(self, headers, params=None):
        return self._request("GET", "/safety/workers", headers=headers, params=params)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/safety/workers/{worker_id}", headers=headers)

    def complete_orientation(self, worker_id, payload, headers):
        return self._request(
            "POST", f"/safety/workers/{worker_id}/complete-orientation", payload, headers
        )

    def clear_worker(self, worker_id, payload, headers):
        return self._request(
            "POST", f"/safety/workers/{worker_id}/clear", payload, headers
        )

    def suspend_worker(self, worker_id, payload, headers):
        return self._request(
            "POST", f"/safety/workers/{worker_id}/suspend", payload, headers
        )

    def reinstate_worker(self, worker_id, payload, headers):
        return self._request(
            "POST", f"/safety/workers/{worker_id}/reinstate", payload, headers
        )

    # ─── Training certificates (PRD §3.2) ───
    def create_certificate(self, payload, headers):
        return self._request("POST", "/safety/training-certificates", payload, headers)

    def list_certificates(self, headers, params=None):
        return self._request(
            "GET", "/safety/training-certificates", headers=headers, params=params
        )

    def get_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"/safety/training-certificates/{certificate_id}", headers=headers
        )

    def verify_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/safety/training-certificates/{certificate_id}/verify",
            payload, headers,
        )

    # ─── Subcontractors (PRD §3.7) ───
    def create_subcontractor(self, payload, headers):
        return self._request("POST", "/safety/subcontractors", payload, headers)

    def list_subcontractors(self, headers, params=None):
        return self._request("GET", "/safety/subcontractors", headers=headers, params=params)

    def get_subcontractor(self, subcontractor_id, headers):
        return self._request(
            "GET", f"/safety/subcontractors/{subcontractor_id}", headers=headers
        )

    def probation_review(self, subcontractor_id, payload, headers):
        return self._request(
            "POST", f"/safety/subcontractors/{subcontractor_id}/probation-review",
            payload, headers,
        )

    def remove_subcontractor(self, subcontractor_id, payload, headers):
        return self._request(
            "POST", f"/safety/subcontractors/{subcontractor_id}/remove", payload, headers
        )

    # ─── Huddles (PRD §3.3) ───
    def create_huddle(self, payload, headers):
        return self._request("POST", "/safety/huddles", payload, headers)

    def list_huddles(self, headers, params=None):
        return self._request("GET", "/safety/huddles", headers=headers, params=params)

    def get_huddle(self, huddle_id, headers):
        return self._request("GET", f"/safety/huddles/{huddle_id}", headers=headers)

    def conduct_huddle(self, huddle_id, payload, headers):
        return self._request(
            "POST", f"/safety/huddles/{huddle_id}/conduct", payload, headers
        )

    # ─── Job hazard analyses (PRD §3.3) ───
    def create_jha(self, payload, headers):
        return self._request("POST", "/safety/jhas", payload, headers)

    def list_jhas(self, headers, params=None):
        return self._request("GET", "/safety/jhas", headers=headers, params=params)

    def get_jha(self, jha_id, headers):
        return self._request("GET", f"/safety/jhas/{jha_id}", headers=headers)

    def approve_jha(self, jha_id, payload, headers):
        return self._request("POST", f"/safety/jhas/{jha_id}/approve", payload, headers)

    # ─── Inspections (PRD §3.5) ───
    def create_inspection(self, payload, headers):
        return self._request("POST", "/safety/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/safety/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"/safety/inspections/{inspection_id}", headers=headers
        )

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/safety/inspections/{inspection_id}/complete", payload, headers
        )

    # ─── Deficiencies (PRD §3.5) ───
    def create_deficiency(self, payload, headers):
        return self._request("POST", "/safety/deficiencies", payload, headers)

    def list_deficiencies(self, headers, params=None):
        return self._request("GET", "/safety/deficiencies", headers=headers, params=params)

    def get_deficiency(self, deficiency_id, headers):
        return self._request(
            "GET", f"/safety/deficiencies/{deficiency_id}", headers=headers
        )

    def submit_correction(self, deficiency_id, payload, headers):
        return self._request(
            "POST", f"/safety/deficiencies/{deficiency_id}/submit-correction",
            payload, headers,
        )

    def verify_deficiency(self, deficiency_id, payload, headers):
        return self._request(
            "POST", f"/safety/deficiencies/{deficiency_id}/verify", payload, headers
        )

    # ─── Incidents (PRD §3.6) ───
    def create_incident(self, payload, headers):
        return self._request("POST", "/safety/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/safety/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/safety/incidents/{incident_id}", headers=headers)

    def investigate_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/safety/incidents/{incident_id}/investigate", payload, headers
        )

    def record_determination(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/safety/incidents/{incident_id}/determination", payload, headers
        )

    def close_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/safety/incidents/{incident_id}/close", payload, headers
        )

    # ─── Permits (PRD §3.4) ───
    def create_permit(self, payload, headers):
        return self._request("POST", "/safety/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/safety/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/safety/permits/{permit_id}", headers=headers)

    def issue_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/safety/permits/{permit_id}/issue", payload, headers)

    def close_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/safety/permits/{permit_id}/close", payload, headers)

    def reinstate_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/safety/permits/{permit_id}/reinstate", payload, headers
        )

    # ─── Drug test records (PRD §3.8) ───
    def create_drug_test(self, payload, headers):
        return self._request("POST", "/safety/drug-tests", payload, headers)

    def list_drug_tests(self, headers, params=None):
        return self._request("GET", "/safety/drug-tests", headers=headers, params=params)

    def get_drug_test(self, drug_test_id, headers):
        return self._request("GET", f"/safety/drug-tests/{drug_test_id}", headers=headers)

    def record_drug_test_result(self, drug_test_id, payload, headers):
        return self._request(
            "POST", f"/safety/drug-tests/{drug_test_id}/record-result", payload, headers
        )


api_client = ApiClient()
