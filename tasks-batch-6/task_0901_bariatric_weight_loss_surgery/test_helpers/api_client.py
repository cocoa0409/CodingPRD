"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Configuration ----
    def create_insurance_plan(self, payload, headers):
        return self._request("POST", "/insurance-plans", payload, headers)

    def get_insurance_plan(self, plan_id, headers):
        return self._request("GET", f"/insurance-plans/{plan_id}", headers=headers)

    def create_operating_room(self, payload, headers):
        return self._request("POST", "/operating-rooms", payload, headers)

    def get_operating_room(self, room_id, headers):
        return self._request("GET", f"/operating-rooms/{room_id}", headers=headers)

    def create_surgeon(self, payload, headers):
        return self._request("POST", "/surgeons", payload, headers)

    def get_surgeon(self, surgeon_id, headers):
        return self._request("GET", f"/surgeons/{surgeon_id}", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Patients ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # ---- Programs ----
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def candidacy_review(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/candidacy-review", {}, headers)

    def request_clearance(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/request-clearance", {}, headers)

    def finalize_clearance(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/finalize-clearance", {}, headers)

    def get_program_summary(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}/summary", headers=headers)

    # ---- Supervised diet ----
    def create_diet_visit(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/diet-visits", payload, headers)

    def list_diet_visits(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/diet-visits", headers=headers, params=params)

    # ---- Psych evaluations ----
    def create_psych_evaluation(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/psych-evaluations", payload, headers)

    def list_psych_evaluations(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/psych-evaluations", headers=headers, params=params)

    def psych_decision(self, psych_id, payload, headers):
        return self._request("POST", f"/psych-evaluations/{psych_id}/decision", payload, headers)

    def psych_reevaluate(self, psych_id, headers):
        return self._request("POST", f"/psych-evaluations/{psych_id}/reevaluate", {}, headers)

    # ---- Nutrition clearances ----
    def create_nutrition_clearance(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/nutrition-clearances", payload, headers)

    def list_nutrition_clearances(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/nutrition-clearances", headers=headers, params=params)

    # ---- Education milestones ----
    def create_milestone(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/milestones", payload, headers)

    def list_milestones(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/milestones", headers=headers, params=params)

    # ---- Surgery cases ----
    def schedule_surgery_case(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/surgery-cases", payload, headers)

    def list_surgery_cases(self, headers, params=None):
        return self._request("GET", "/surgery-cases", headers=headers, params=params)

    def get_surgery_case(self, case_id, headers):
        return self._request("GET", f"/surgery-cases/{case_id}", headers=headers)

    def complete_surgery_case(self, case_id, payload, headers):
        return self._request("POST", f"/surgery-cases/{case_id}/complete", payload, headers)

    def cancel_surgery_case(self, case_id, payload, headers):
        return self._request("POST", f"/surgery-cases/{case_id}/cancel", payload, headers)

    # ---- Complications ----
    def create_complication(self, case_id, payload, headers):
        return self._request("POST", f"/surgery-cases/{case_id}/complications", payload, headers)

    def list_complications(self, case_id, headers, params=None):
        return self._request("GET", f"/surgery-cases/{case_id}/complications", headers=headers, params=params)

    def resolve_complication(self, complication_id, headers):
        return self._request("POST", f"/complications/{complication_id}/resolve", {}, headers)

    # ---- Follow-up visits ----
    def list_follow_up_visits(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/follow-up-visits", headers=headers, params=params)

    def record_follow_up_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/follow-up-visits/{visit_id}/record", payload, headers)

    # ---- Financing ----
    def create_financing_plan(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/financing-plan", payload, headers)

    def list_financing_plans(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/financing-plan", headers=headers, params=params)


api_client = ApiClient()
