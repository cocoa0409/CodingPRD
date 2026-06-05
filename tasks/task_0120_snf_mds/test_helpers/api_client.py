"""API client for the SNF-MDS API: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Facility ───────────────────────────────────────
    def create_facility(self, payload, headers):
        return self._request("POST", "/snf/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/snf/facilities/{facility_id}", headers=headers)

    def get_facility_star_summary(self, facility_id, headers):
        return self._request("GET", f"/snf/facilities/{facility_id}/star-summary", headers=headers)

    def create_quality_measure(self, facility_id, payload, headers):
        return self._request("POST", f"/snf/facilities/{facility_id}/quality-measures", payload, headers)

    def list_quality_measures(self, facility_id, headers, params=None):
        return self._request("GET", f"/snf/facilities/{facility_id}/quality-measures", headers=headers, params=params)

    # ─── PdpmRate ───────────────────────────────────────
    def create_pdpm_rate(self, payload, headers):
        return self._request("POST", "/snf/pdpm-rates", payload, headers)

    def list_pdpm_rates(self, headers, params=None):
        return self._request("GET", "/snf/pdpm-rates", headers=headers, params=params)

    # ─── Resident ───────────────────────────────────────
    def create_resident(self, payload, headers):
        return self._request("POST", "/snf/residents", payload, headers)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/snf/residents/{resident_id}", headers=headers)

    def list_residents(self, headers, params=None):
        return self._request("GET", "/snf/residents", headers=headers, params=params)

    # ─── QualifyingStay ─────────────────────────────────
    def create_qualifying_stay(self, resident_id, payload, headers):
        return self._request("POST", f"/snf/residents/{resident_id}/qualifying-stays", payload, headers)

    def get_qualifying_stay(self, stay_id, headers):
        return self._request("GET", f"/snf/qualifying-stays/{stay_id}", headers=headers)

    def list_qualifying_stays(self, headers, params=None):
        return self._request("GET", "/snf/qualifying-stays", headers=headers, params=params)

    # ─── PasrrScreening ─────────────────────────────────
    def create_pasrr_screening(self, resident_id, payload, headers):
        return self._request("POST", f"/snf/residents/{resident_id}/pasrr-screenings", payload, headers)

    def resolve_pasrr_screening(self, screening_id, payload, headers):
        return self._request("POST", f"/snf/pasrr-screenings/{screening_id}/resolve", payload, headers)

    def get_pasrr_screening(self, screening_id, headers):
        return self._request("GET", f"/snf/pasrr-screenings/{screening_id}", headers=headers)

    def list_pasrr_screenings(self, headers, params=None):
        return self._request("GET", "/snf/pasrr-screenings", headers=headers, params=params)

    # ─── Admission ──────────────────────────────────────
    def create_admission(self, payload, headers):
        return self._request("POST", "/snf/admissions", payload, headers)

    def get_admission(self, admission_id, headers):
        return self._request("GET", f"/snf/admissions/{admission_id}", headers=headers)

    def list_admissions(self, headers, params=None):
        return self._request("GET", "/snf/admissions", headers=headers, params=params)

    def activate_admission(self, admission_id, payload, headers):
        return self._request("POST", f"/snf/admissions/{admission_id}/activate", payload, headers)

    def plan_discharge_admission(self, admission_id, payload, headers):
        return self._request("POST", f"/snf/admissions/{admission_id}/plan-discharge", payload, headers)

    def discharge_admission(self, admission_id, payload, headers):
        return self._request("POST", f"/snf/admissions/{admission_id}/discharge", payload, headers)

    # ─── MdsAssessment (under admission + lifecycle) ────
    def create_assessment(self, admission_id, payload, headers):
        return self._request("POST", f"/snf/admissions/{admission_id}/assessments", payload, headers)

    def list_assessments_for_admission(self, admission_id, headers, params=None):
        return self._request("GET", f"/snf/admissions/{admission_id}/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/snf/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/snf/assessments", headers=headers, params=params)

    def start_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/snf/assessments/{assessment_id}/start", payload, headers)

    def complete_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/snf/assessments/{assessment_id}/complete", payload, headers)

    def reopen_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/snf/assessments/{assessment_id}/reopen", payload, headers)

    def submit_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/snf/assessments/{assessment_id}/submit", payload, headers)

    def correct_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/snf/assessments/{assessment_id}/correct", payload, headers)

    # ─── BedHold ────────────────────────────────────────
    def create_bed_hold(self, admission_id, payload, headers):
        return self._request("POST", f"/snf/admissions/{admission_id}/bed-holds", payload, headers)

    def list_bed_holds(self, admission_id, headers, params=None):
        return self._request("GET", f"/snf/admissions/{admission_id}/bed-holds", headers=headers, params=params)

    def get_bed_hold(self, bed_hold_id, headers):
        return self._request("GET", f"/snf/bed-holds/{bed_hold_id}", headers=headers)

    def close_bed_hold(self, bed_hold_id, payload, headers):
        return self._request("POST", f"/snf/bed-holds/{bed_hold_id}/close", payload, headers)

    # ─── TherapyLog ─────────────────────────────────────
    def create_therapy_log(self, admission_id, payload, headers):
        return self._request("POST", f"/snf/admissions/{admission_id}/therapy-logs", payload, headers)

    def list_therapy_logs(self, admission_id, headers, params=None):
        return self._request("GET", f"/snf/admissions/{admission_id}/therapy-logs", headers=headers, params=params)

    def get_therapy_summary(self, admission_id, discipline, headers):
        return self._request(
            "GET",
            f"/snf/admissions/{admission_id}/therapy-summary",
            headers=headers,
            params={"discipline": discipline},
        )

    # ─── Claim ──────────────────────────────────────────
    def create_claim(self, admission_id, payload, headers):
        return self._request("POST", f"/snf/admissions/{admission_id}/claims", payload, headers)

    def list_claims_for_admission(self, admission_id, headers, params=None):
        return self._request("GET", f"/snf/admissions/{admission_id}/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/snf/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/snf/claims", headers=headers, params=params)

    def estimate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/snf/claims/{claim_id}/estimate", payload, headers)

    def finalize_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/snf/claims/{claim_id}/finalize", payload, headers)

    def submit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/snf/claims/{claim_id}/submit", payload, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/snf/claims/{claim_id}/adjudicate", payload, headers)

    # ─── CarePlan / CarePlanGoal ────────────────────────
    def create_care_plan(self, admission_id, payload, headers):
        return self._request("POST", f"/snf/admissions/{admission_id}/care-plans", payload, headers)

    def list_care_plans(self, admission_id, headers, params=None):
        return self._request("GET", f"/snf/admissions/{admission_id}/care-plans", headers=headers, params=params)

    def get_care_plan(self, care_plan_id, headers):
        return self._request("GET", f"/snf/care-plans/{care_plan_id}", headers=headers)

    def create_goal(self, care_plan_id, payload, headers):
        return self._request("POST", f"/snf/care-plans/{care_plan_id}/goals", payload, headers)

    def list_goals(self, care_plan_id, headers, params=None):
        return self._request("GET", f"/snf/care-plans/{care_plan_id}/goals", headers=headers, params=params)

    def activate_care_plan(self, care_plan_id, payload, headers):
        return self._request("POST", f"/snf/care-plans/{care_plan_id}/activate", payload, headers)

    def begin_review_care_plan(self, care_plan_id, payload, headers):
        return self._request("POST", f"/snf/care-plans/{care_plan_id}/begin-review", payload, headers)

    def complete_review_care_plan(self, care_plan_id, payload, headers):
        return self._request("POST", f"/snf/care-plans/{care_plan_id}/complete-review", payload, headers)

    def close_care_plan(self, care_plan_id, payload, headers):
        return self._request("POST", f"/snf/care-plans/{care_plan_id}/close", payload, headers)

    def update_goal(self, goal_id, payload, headers):
        return self._request("PATCH", f"/snf/goals/{goal_id}", payload, headers)


api_client = ApiClient()
