"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Program ----------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def patch_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/programs/{program_id}", payload, headers)

    # ---- Cohort -----------------------------------------------------------
    def create_cohort(self, payload, headers):
        return self._request("POST", "/cohorts", payload, headers)

    def list_cohorts(self, headers, params=None):
        return self._request("GET", "/cohorts", payload=params, headers=headers)

    def get_cohort(self, cohort_id, headers):
        return self._request("GET", f"/cohorts/{cohort_id}", headers=headers)

    def advance_cohort(self, cohort_id, payload, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/advance", payload, headers)

    # ---- Curriculum module ------------------------------------------------
    def create_curriculum_module(self, payload, headers):
        return self._request("POST", "/curriculum-modules", payload, headers)

    def list_curriculum_modules(self, headers, params=None):
        return self._request("GET", "/curriculum-modules", payload=params, headers=headers)

    def get_curriculum_module(self, module_id, headers):
        return self._request("GET", f"/curriculum-modules/{module_id}", headers=headers)

    def patch_curriculum_module(self, module_id, payload, headers):
        return self._request("PATCH", f"/curriculum-modules/{module_id}", payload, headers)

    # ---- Facility / Instructor -------------------------------------------
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def patch_instructor(self, instructor_id, payload, headers):
        return self._request("PATCH", f"/instructors/{instructor_id}", payload, headers)

    # ---- Class session ----------------------------------------------------
    def create_class_session(self, payload, headers):
        return self._request("POST", "/class-sessions", payload, headers)

    def list_class_sessions(self, headers, params=None):
        return self._request("GET", "/class-sessions", payload=params, headers=headers)

    def get_class_session(self, session_id, headers):
        return self._request("GET", f"/class-sessions/{session_id}", headers=headers)

    def deliver_class_session(self, session_id, headers, payload=None):
        return self._request("POST", f"/class-sessions/{session_id}/deliver", payload or {}, headers)

    def cancel_class_session(self, session_id, payload, headers):
        return self._request("POST", f"/class-sessions/{session_id}/cancel", payload, headers)

    # ---- Trainee ----------------------------------------------------------
    def create_trainee(self, payload, headers):
        return self._request("POST", "/trainees", payload, headers)

    def list_trainees(self, headers, params=None):
        return self._request("GET", "/trainees", payload=params, headers=headers)

    def get_trainee(self, trainee_id, headers):
        return self._request("GET", f"/trainees/{trainee_id}", headers=headers)

    def trainee_enrollment(self, trainee_id, payload, headers):
        return self._request("POST", f"/trainees/{trainee_id}/enrollment", payload, headers)

    def get_trainee_readiness(self, trainee_id, headers):
        return self._request("GET", f"/trainees/{trainee_id}/readiness", headers=headers)

    # ---- Module completion ------------------------------------------------
    def create_module_completion(self, payload, headers):
        return self._request("POST", "/module-completions", payload, headers)

    def list_module_completions(self, headers, params=None):
        return self._request("GET", "/module-completions", payload=params, headers=headers)

    def get_module_completion(self, completion_id, headers):
        return self._request("GET", f"/module-completions/{completion_id}", headers=headers)

    def sign_skills_demo(self, completion_id, payload, headers):
        return self._request("POST", f"/module-completions/{completion_id}/skills-demo", payload, headers)

    def void_module_completion(self, completion_id, payload, headers):
        return self._request("POST", f"/module-completions/{completion_id}/void", payload, headers)

    # ---- Credential -------------------------------------------------------
    def create_credential(self, payload, headers):
        return self._request("POST", "/credentials", payload, headers)

    def list_credentials(self, headers, params=None):
        return self._request("GET", "/credentials", payload=params, headers=headers)

    def get_credential(self, credential_id, headers):
        return self._request("GET", f"/credentials/{credential_id}", headers=headers)

    def credential_status_action(self, credential_id, payload, headers):
        return self._request("POST", f"/credentials/{credential_id}/status", payload, headers)

    # ---- Equipment --------------------------------------------------------
    def create_equipment_asset(self, payload, headers):
        return self._request("POST", "/equipment-assets", payload, headers)

    def list_equipment_assets(self, headers, params=None):
        return self._request("GET", "/equipment-assets", payload=params, headers=headers)

    def get_equipment_asset(self, asset_id, headers):
        return self._request("GET", f"/equipment-assets/{asset_id}", headers=headers)

    def create_equipment_issuance(self, payload, headers):
        return self._request("POST", "/equipment-issuances", payload, headers)

    def list_equipment_issuances(self, headers, params=None):
        return self._request("GET", "/equipment-issuances", payload=params, headers=headers)

    def get_equipment_issuance(self, issuance_id, headers):
        return self._request("GET", f"/equipment-issuances/{issuance_id}", headers=headers)

    def return_equipment_issuance(self, issuance_id, payload, headers):
        return self._request("POST", f"/equipment-issuances/{issuance_id}/return", payload, headers)

    def report_lost_equipment_issuance(self, issuance_id, payload, headers):
        return self._request("POST", f"/equipment-issuances/{issuance_id}/report-lost", payload, headers)

    # ---- Exercise ---------------------------------------------------------
    def create_exercise(self, payload, headers):
        return self._request("POST", "/exercises", payload, headers)

    def list_exercises(self, headers, params=None):
        return self._request("GET", "/exercises", payload=params, headers=headers)

    def get_exercise(self, exercise_id, headers):
        return self._request("GET", f"/exercises/{exercise_id}", headers=headers)

    def advance_exercise(self, exercise_id, payload, headers):
        return self._request("POST", f"/exercises/{exercise_id}/advance", payload, headers)

    def create_exercise_participation(self, payload, headers):
        return self._request("POST", "/exercise-participations", payload, headers)

    def list_exercise_participations(self, headers, params=None):
        return self._request("GET", "/exercise-participations", payload=params, headers=headers)

    def get_exercise_participation(self, participation_id, headers):
        return self._request("GET", f"/exercise-participations/{participation_id}", headers=headers)

    # ---- Activation / roster ---------------------------------------------
    def create_activation(self, payload, headers):
        return self._request("POST", "/activations", payload, headers)

    def list_activations(self, headers, params=None):
        return self._request("GET", "/activations", payload=params, headers=headers)

    def get_activation(self, activation_id, headers):
        return self._request("GET", f"/activations/{activation_id}", headers=headers)

    def build_roster(self, activation_id, headers, payload=None):
        return self._request("POST", f"/activations/{activation_id}/roster", payload or {}, headers)

    def add_roster_assignment(self, activation_id, payload, headers):
        return self._request("POST", f"/activations/{activation_id}/roster-assignments", payload, headers)

    def advance_activation(self, activation_id, payload, headers):
        return self._request("POST", f"/activations/{activation_id}/advance", payload, headers)

    def list_roster_assignments(self, headers, params=None):
        return self._request("GET", "/roster-assignments", payload=params, headers=headers)

    def get_roster_assignment(self, assignment_id, headers):
        return self._request("GET", f"/roster-assignments/{assignment_id}", headers=headers)

    def respond_roster_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/roster-assignments/{assignment_id}/respond", payload, headers)

    def advance_roster_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/roster-assignments/{assignment_id}/advance", payload, headers)

    # ---- Test-driving operations -----------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_currency_sweep(self, payload, headers):
        return self._request("POST", "/_ops/run-currency-sweep", payload, headers)

    # ---- Raw helpers for negative path tests ------------------------------
    def raw_get(self, path, headers, params=None):
        return self._request("GET", path, payload=params, headers=headers)

    def raw_post(self, path, payload, headers):
        return self._request("POST", path, payload, headers)

    def raw_patch(self, path, payload, headers):
        return self._request("PATCH", path, payload, headers)


api_client = ApiClient()
