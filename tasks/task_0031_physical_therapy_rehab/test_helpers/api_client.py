"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Patients (PRD §3.1) ────────────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", "/rehab/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/rehab/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/rehab/patients", headers=headers, params=params)

    # ─── Therapists (PRD §3.1) ──────────────────────────────────────
    def create_therapist(self, payload, headers):
        return self._request("POST", "/rehab/therapists", payload, headers)

    def get_therapist(self, therapist_id, headers):
        return self._request("GET", f"/rehab/therapists/{therapist_id}", headers=headers)

    def list_therapists(self, headers, params=None):
        return self._request("GET", "/rehab/therapists", headers=headers, params=params)

    # ─── Veteran Referrals (PRD §3.2, §3.9) ─────────────────────────
    def create_veteran_referral(self, payload, headers):
        return self._request("POST", "/rehab/veteran-referrals", payload, headers)

    def get_veteran_referral(self, referral_id, headers):
        return self._request(
            "GET", f"/rehab/veteran-referrals/{referral_id}", headers=headers
        )

    def list_veteran_referrals(self, headers, params=None):
        return self._request(
            "GET", "/rehab/veteran-referrals", headers=headers, params=params
        )

    def cancel_veteran_referral(self, referral_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rehab/veteran-referrals/{referral_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ─── Plans of Care (PRD §3.2, §3.6) ─────────────────────────────
    def create_plan_of_care(self, payload, headers):
        return self._request("POST", "/rehab/plans-of-care", payload, headers)

    def get_plan_of_care(self, plan_id, headers):
        return self._request("GET", f"/rehab/plans-of-care/{plan_id}", headers=headers)

    def list_plans_of_care(self, headers, params=None):
        return self._request("GET", "/rehab/plans-of-care", headers=headers, params=params)

    def activate_plan_of_care(self, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rehab/plans-of-care/{plan_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def recertify_plan_of_care(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/rehab/plans-of-care/{plan_id}/recertify", payload, headers
        )

    def discharge_plan_of_care(self, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rehab/plans-of-care/{plan_id}/discharge",
            payload if payload is not None else {},
            headers,
        )

    # ─── Evaluations (PRD §3.3) ─────────────────────────────────────
    def create_evaluation(self, payload, headers):
        return self._request("POST", "/rehab/evaluations", payload, headers)

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/rehab/evaluations/{evaluation_id}", headers=headers)

    def list_evaluations(self, headers, params=None):
        return self._request("GET", "/rehab/evaluations", headers=headers, params=params)

    # ─── Authorization Grants (PRD §3.4) ────────────────────────────
    def create_authorization_grant(self, payload, headers):
        return self._request("POST", "/rehab/authorization-grants", payload, headers)

    def get_authorization_grant(self, grant_id, headers):
        return self._request(
            "GET", f"/rehab/authorization-grants/{grant_id}", headers=headers
        )

    def list_authorization_grants(self, headers, params=None):
        return self._request(
            "GET", "/rehab/authorization-grants", headers=headers, params=params
        )

    # ─── Visits (PRD §3.5) ──────────────────────────────────────────
    def create_visit(self, payload, headers):
        return self._request("POST", "/rehab/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/rehab/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/rehab/visits", headers=headers, params=params)

    def complete_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/rehab/visits/{visit_id}/complete", payload, headers
        )

    def finalize_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/rehab/visits/{visit_id}/finalize", payload, headers
        )

    def cancel_visit(self, visit_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rehab/visits/{visit_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    def no_show_visit(self, visit_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rehab/visits/{visit_id}/no-show",
            payload if payload is not None else {},
            headers,
        )

    # ─── Home Exercise Programs (PRD §3.7) ──────────────────────────
    def create_home_exercise_program(self, payload, headers):
        return self._request("POST", "/rehab/home-exercise-programs", payload, headers)

    def get_home_exercise_program(self, hep_id, headers):
        return self._request(
            "GET", f"/rehab/home-exercise-programs/{hep_id}", headers=headers
        )

    def list_home_exercise_programs(self, headers, params=None):
        return self._request(
            "GET", "/rehab/home-exercise-programs", headers=headers, params=params
        )

    # ─── MIPS Quality Measures (PRD §3.7) ───────────────────────────
    def create_mips_measure(self, payload, headers):
        return self._request("POST", "/rehab/mips-measures", payload, headers)

    def get_mips_measure(self, mips_id, headers):
        return self._request("GET", f"/rehab/mips-measures/{mips_id}", headers=headers)

    def list_mips_measures(self, headers, params=None):
        return self._request("GET", "/rehab/mips-measures", headers=headers, params=params)

    def revise_mips_measure(self, mips_id, payload, headers):
        return self._request(
            "POST", f"/rehab/mips-measures/{mips_id}/revise", payload, headers
        )

    def submit_mips_measure(self, mips_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rehab/mips-measures/{mips_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def adjudicate_mips_measure(self, mips_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rehab/mips-measures/{mips_id}/adjudicate",
            payload if payload is not None else {},
            headers,
        )

    # ─── Discharge Assessments (PRD §3.8) ───────────────────────────
    def create_discharge_assessment(self, payload, headers):
        return self._request("POST", "/rehab/discharge-assessments", payload, headers)

    def get_discharge_assessment(self, da_id, headers):
        return self._request(
            "GET", f"/rehab/discharge-assessments/{da_id}", headers=headers
        )

    def list_discharge_assessments(self, headers, params=None):
        return self._request(
            "GET", "/rehab/discharge-assessments", headers=headers, params=params
        )

    # ─── Test-driving clock (PRD §2.10) ─────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
