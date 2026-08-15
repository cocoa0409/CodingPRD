"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Patients ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/oncology/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/oncology/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/oncology/patients/{patient_id}", headers=headers)

    # --- Treatment Courses ---
    def create_course(self, patient_id, payload, headers):
        return self._request("POST", f"/oncology/patients/{patient_id}/treatment-courses", payload, headers)

    def list_patient_courses(self, patient_id, headers, params=None):
        return self._request("GET", f"/oncology/patients/{patient_id}/treatment-courses", headers=headers, params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/oncology/treatment-courses/{course_id}", headers=headers)

    def complete_course(self, course_id, headers):
        return self._request("POST", f"/oncology/treatment-courses/{course_id}/complete", {}, headers)

    def discontinue_course(self, course_id, payload, headers):
        return self._request("POST", f"/oncology/treatment-courses/{course_id}/discontinue", payload, headers)

    def adaptation_check(self, course_id, payload, headers):
        return self._request("POST", f"/oncology/treatment-courses/{course_id}/adaptation-checks", payload, headers)

    # --- Simulation Appointments ---
    def create_simulation(self, course_id, payload, headers):
        return self._request("POST", f"/oncology/treatment-courses/{course_id}/simulation-appointments", payload, headers)

    def list_simulations(self, course_id, headers, params=None):
        return self._request("GET", f"/oncology/treatment-courses/{course_id}/simulation-appointments", headers=headers, params=params)

    def complete_simulation(self, sim_id, payload, headers):
        return self._request("POST", f"/oncology/simulation-appointments/{sim_id}/complete", payload, headers)

    def cancel_simulation(self, sim_id, headers):
        return self._request("POST", f"/oncology/simulation-appointments/{sim_id}/cancel", {}, headers)

    def no_show_simulation(self, sim_id, headers):
        return self._request("POST", f"/oncology/simulation-appointments/{sim_id}/mark-no-show", {}, headers)

    # --- Contour Sets ---
    def create_contour_set(self, course_id, payload, headers):
        return self._request("POST", f"/oncology/treatment-courses/{course_id}/contour-sets", payload, headers)

    def list_contour_sets(self, course_id, headers, params=None):
        return self._request("GET", f"/oncology/treatment-courses/{course_id}/contour-sets", headers=headers, params=params)

    def get_contour_set(self, contour_id, headers):
        return self._request("GET", f"/oncology/contour-sets/{contour_id}", headers=headers)

    def submit_contour_set(self, contour_id, headers):
        return self._request("POST", f"/oncology/contour-sets/{contour_id}/submit", {}, headers)

    def approve_contour_set(self, contour_id, headers):
        return self._request("POST", f"/oncology/contour-sets/{contour_id}/approve", {}, headers)

    def return_contour_set(self, contour_id, payload, headers):
        return self._request("POST", f"/oncology/contour-sets/{contour_id}/return", payload, headers)

    # --- Treatment Plans ---
    def create_plan(self, course_id, payload, headers):
        return self._request("POST", f"/oncology/treatment-courses/{course_id}/treatment-plans", payload, headers)

    def list_plans(self, course_id, headers, params=None):
        return self._request("GET", f"/oncology/treatment-courses/{course_id}/treatment-plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/oncology/treatment-plans/{plan_id}", headers=headers)

    def list_plan_successors(self, plan_id, headers):
        return self._request("GET", f"/oncology/treatment-plans/{plan_id}/successors", headers=headers)

    def list_contour_plans(self, contour_id, headers):
        return self._request("GET", f"/oncology/contour-sets/{contour_id}/treatment-plans", headers=headers)

    def list_plan_sessions(self, plan_id, headers, params=None):
        return self._request("GET", f"/oncology/treatment-plans/{plan_id}/fraction-sessions", headers=headers, params=params)

    def create_dose_constraint(self, plan_id, payload, headers):
        return self._request("POST", f"/oncology/treatment-plans/{plan_id}/dose-constraints", payload, headers)

    def list_dose_constraints(self, plan_id, headers, params=None):
        return self._request("GET", f"/oncology/treatment-plans/{plan_id}/dose-constraints", headers=headers, params=params)

    def submit_plan_for_check(self, plan_id, headers):
        return self._request("POST", f"/oncology/treatment-plans/{plan_id}/submit-for-check", {}, headers)

    def revise_plan(self, plan_id, headers):
        return self._request("POST", f"/oncology/treatment-plans/{plan_id}/revise", {}, headers)

    def create_physics_check(self, plan_id, payload, headers):
        return self._request("POST", f"/oncology/treatment-plans/{plan_id}/physics-checks", payload, headers)

    def list_physics_checks(self, plan_id, headers):
        return self._request("GET", f"/oncology/treatment-plans/{plan_id}/physics-checks", headers=headers)

    # --- Fraction Sessions ---
    def create_fraction_session(self, course_id, payload, headers):
        return self._request("POST", f"/oncology/treatment-courses/{course_id}/fraction-sessions", payload, headers)

    def list_fraction_sessions(self, course_id, headers, params=None):
        return self._request("GET", f"/oncology/treatment-courses/{course_id}/fraction-sessions", headers=headers, params=params)

    def deliver_fraction(self, session_id, headers):
        return self._request("POST", f"/oncology/fraction-sessions/{session_id}/deliver", {}, headers)

    def cancel_fraction(self, session_id, payload, headers):
        return self._request("POST", f"/oncology/fraction-sessions/{session_id}/cancel", payload, headers)

    def no_show_fraction(self, session_id, headers):
        return self._request("POST", f"/oncology/fraction-sessions/{session_id}/mark-no-show", {}, headers)

    # --- Machines ---
    def create_machine(self, payload, headers):
        return self._request("POST", "/oncology/machines", payload, headers)

    def list_machines(self, headers, params=None):
        return self._request("GET", "/oncology/machines", headers=headers, params=params)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"/oncology/machines/{machine_id}", headers=headers)

    def set_machine_status(self, machine_id, payload, headers):
        return self._request("PUT", f"/oncology/machines/{machine_id}/status", payload, headers)

    def list_machine_sessions(self, machine_id, headers, params=None):
        return self._request("GET", f"/oncology/machines/{machine_id}/fraction-sessions", headers=headers, params=params)

    def list_machine_simulations(self, machine_id, headers, params=None):
        return self._request("GET", f"/oncology/machines/{machine_id}/simulation-appointments", headers=headers, params=params)

    # --- Interruptions ---
    def create_interruption(self, course_id, payload, headers):
        return self._request("POST", f"/oncology/treatment-courses/{course_id}/interruptions", payload, headers)

    def list_interruptions(self, course_id, headers, params=None):
        return self._request("GET", f"/oncology/treatment-courses/{course_id}/interruptions", headers=headers, params=params)

    def compensate_interruption(self, interruption_id, payload, headers):
        return self._request("POST", f"/oncology/interruptions/{interruption_id}/compensate", payload, headers)

    # --- Chart Reviews ---
    def create_chart_review(self, course_id, payload, headers):
        return self._request("POST", f"/oncology/treatment-courses/{course_id}/chart-reviews", payload, headers)

    def list_chart_reviews(self, course_id, headers):
        return self._request("GET", f"/oncology/treatment-courses/{course_id}/chart-reviews", headers=headers)

    # --- Billing ---
    def create_claim(self, course_id, headers):
        return self._request("POST", f"/oncology/treatment-courses/{course_id}/billing-claims", {}, headers)

    def list_claims(self, course_id, headers, params=None):
        return self._request("GET", f"/oncology/treatment-courses/{course_id}/billing-claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/oncology/billing-claims/{claim_id}", headers=headers)

    def list_charge_lines(self, claim_id, headers, params=None):
        return self._request("GET", f"/oncology/billing-claims/{claim_id}/charge-lines", headers=headers, params=params)

    def finalize_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/oncology/billing-claims/{claim_id}/finalize", payload, headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/oncology/billing-claims/{claim_id}/submit", {}, headers)

    def reopen_claim(self, claim_id, headers):
        return self._request("POST", f"/oncology/billing-claims/{claim_id}/reopen", {}, headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/oncology/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
