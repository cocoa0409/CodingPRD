"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Facilities ----
    def create_facility(self, payload, headers):
        return self._request("POST", "/edt/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/edt/facilities", headers=headers, params=params)

    def get_facility(self, fid, headers):
        return self._request("GET", f"/edt/facilities/{fid}", headers=headers)

    # ---- Programs ----
    def create_program(self, payload, headers):
        return self._request("POST", "/edt/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/edt/programs", headers=headers, params=params)

    def get_program(self, pgid, headers):
        return self._request("GET", f"/edt/programs/{pgid}", headers=headers)

    def close_program(self, pgid, headers):
        return self._request("POST", f"/edt/programs/{pgid}/close", headers=headers)

    # ---- Cohorts ----
    def create_cohort(self, payload, headers):
        return self._request("POST", "/edt/cohorts", payload, headers)

    def list_cohorts(self, headers, params=None):
        return self._request("GET", "/edt/cohorts", headers=headers, params=params)

    def get_cohort(self, cid, headers):
        return self._request("GET", f"/edt/cohorts/{cid}", headers=headers)

    # ---- Patients ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/edt/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/edt/patients", headers=headers, params=params)

    def get_patient(self, pid, headers):
        return self._request("GET", f"/edt/patients/{pid}", headers=headers)

    # ---- Assessments ----
    def create_assessment(self, payload, headers):
        return self._request("POST", "/edt/assessments", payload, headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/edt/assessments", headers=headers, params=params)

    def get_assessment(self, asid, headers):
        return self._request("GET", f"/edt/assessments/{asid}", headers=headers)

    def finalize_assessment(self, asid, payload, headers):
        return self._request(
            "POST", f"/edt/assessments/{asid}/finalize", payload, headers
        )

    # ---- Admissions ----
    def create_admission(self, payload, headers):
        return self._request("POST", "/edt/admissions", payload, headers)

    def list_admissions(self, headers, params=None):
        return self._request("GET", "/edt/admissions", headers=headers, params=params)

    def get_admission(self, aid, headers):
        return self._request("GET", f"/edt/admissions/{aid}", headers=headers)

    def promote_admission(self, aid, headers):
        return self._request("POST", f"/edt/admissions/{aid}/promote", headers=headers)

    def admit_admission(self, aid, headers):
        return self._request("POST", f"/edt/admissions/{aid}/admit", headers=headers)

    def medical_hold_admission(self, aid, headers):
        return self._request(
            "POST", f"/edt/admissions/{aid}/medical-hold", headers=headers
        )

    def clear_hold_admission(self, aid, headers):
        return self._request(
            "POST", f"/edt/admissions/{aid}/clear-hold", headers=headers
        )

    def step_down_admission(self, aid, headers):
        return self._request(
            "POST", f"/edt/admissions/{aid}/step-down", headers=headers
        )

    def begin_discharge_admission(self, aid, headers):
        return self._request(
            "POST", f"/edt/admissions/{aid}/begin-discharge", headers=headers
        )

    def discharge_admission(self, aid, headers):
        return self._request(
            "POST", f"/edt/admissions/{aid}/discharge", headers=headers
        )

    def admin_discharge_admission(self, aid, headers):
        return self._request(
            "POST", f"/edt/admissions/{aid}/admin-discharge", headers=headers
        )

    # ---- Insurance Authorizations ----
    def create_authorization(self, payload, headers):
        return self._request("POST", "/edt/authorizations", payload, headers)

    def list_authorizations(self, headers, params=None):
        return self._request(
            "GET", "/edt/authorizations", headers=headers, params=params
        )

    def get_authorization(self, auth_id, headers):
        return self._request("GET", f"/edt/authorizations/{auth_id}", headers=headers)

    def get_billing_summary(self, auth_id, headers):
        return self._request(
            "GET", f"/edt/authorizations/{auth_id}/billing-summary", headers=headers
        )

    def appeal_authorization(self, auth_id, headers):
        return self._request(
            "POST", f"/edt/authorizations/{auth_id}/appeal", headers=headers
        )

    def expire_authorization(self, auth_id, headers):
        return self._request(
            "POST", f"/edt/authorizations/{auth_id}/expire", headers=headers
        )

    # ---- Concurrent Reviews ----
    def create_review(self, payload, headers):
        return self._request("POST", "/edt/reviews", payload, headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/edt/reviews", headers=headers, params=params)

    def get_review(self, rid, headers):
        return self._request("GET", f"/edt/reviews/{rid}", headers=headers)

    # ---- Treatment Plans ----
    def create_treatment_plan(self, payload, headers):
        return self._request("POST", "/edt/treatment-plans", payload, headers)

    def list_treatment_plans(self, headers, params=None):
        return self._request(
            "GET", "/edt/treatment-plans", headers=headers, params=params
        )

    def get_treatment_plan(self, tp_id, headers):
        return self._request("GET", f"/edt/treatment-plans/{tp_id}", headers=headers)

    def sign_treatment_plan(self, tp_id, payload, headers):
        return self._request(
            "POST", f"/edt/treatment-plans/{tp_id}/sign", payload, headers
        )

    def mark_goal_met(self, tp_id, headers):
        return self._request(
            "POST", f"/edt/treatment-plans/{tp_id}/goals/met", headers=headers
        )

    def activate_treatment_plan(self, tp_id, headers):
        return self._request(
            "POST", f"/edt/treatment-plans/{tp_id}/activate", headers=headers
        )

    def revise_treatment_plan(self, tp_id, payload, headers):
        return self._request(
            "POST", f"/edt/treatment-plans/{tp_id}/revise", payload, headers
        )

    # ---- Meal Plans + Events ----
    def create_meal_plan(self, payload, headers):
        return self._request("POST", "/edt/meal-plans", payload, headers)

    def list_meal_plans(self, headers, params=None):
        return self._request("GET", "/edt/meal-plans", headers=headers, params=params)

    def get_meal_plan(self, mp_id, headers):
        return self._request("GET", f"/edt/meal-plans/{mp_id}", headers=headers)

    def close_meal_plan(self, mp_id, headers):
        return self._request(
            "POST", f"/edt/meal-plans/{mp_id}/close", headers=headers
        )

    def create_meal_event(self, payload, headers):
        return self._request("POST", "/edt/meal-events", payload, headers)

    def list_meal_events(self, headers, params=None):
        return self._request("GET", "/edt/meal-events", headers=headers, params=params)

    def get_meal_event(self, me_id, headers):
        return self._request("GET", f"/edt/meal-events/{me_id}", headers=headers)

    # ---- Family Program ----
    def create_family_program(self, payload, headers):
        return self._request("POST", "/edt/family-programs", payload, headers)

    def list_family_programs(self, headers, params=None):
        return self._request(
            "GET", "/edt/family-programs", headers=headers, params=params
        )

    def get_family_program(self, fp_id, headers):
        return self._request("GET", f"/edt/family-programs/{fp_id}", headers=headers)

    def complete_family_session(self, fp_id, headers):
        return self._request(
            "POST", f"/edt/family-programs/{fp_id}/complete-session", headers=headers
        )

    def waive_family_program(self, fp_id, headers):
        return self._request(
            "POST", f"/edt/family-programs/{fp_id}/waive", headers=headers
        )

    # ---- Discharge Plans ----
    def create_discharge_plan(self, payload, headers):
        return self._request("POST", "/edt/discharge-plans", payload, headers)

    def list_discharge_plans(self, headers, params=None):
        return self._request(
            "GET", "/edt/discharge-plans", headers=headers, params=params
        )

    def get_discharge_plan(self, dp_id, headers):
        return self._request("GET", f"/edt/discharge-plans/{dp_id}", headers=headers)

    def finalize_discharge_plan(self, dp_id, headers):
        return self._request(
            "POST", f"/edt/discharge-plans/{dp_id}/finalize", headers=headers
        )


api_client = ApiClient()
