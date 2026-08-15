"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/gifted/_clock/set_current_utc", payload, headers)

    # --- SchoolSite ---
    def create_school_site(self, payload, headers):
        return self._request("POST", "/gifted/school-sites", payload, headers)

    def get_school_site(self, site_id, headers):
        return self._request("GET", f"/gifted/school-sites/{site_id}", headers=headers)

    def list_site_students(self, site_id, headers, params=None):
        return self._request("GET", f"/gifted/school-sites/{site_id}/students",
                             headers=headers, params=params)

    def list_site_placements(self, site_id, headers, params=None):
        return self._request("GET", f"/gifted/school-sites/{site_id}/placements",
                             headers=headers, params=params)

    # --- Student ---
    def create_student(self, payload, headers):
        return self._request("POST", "/gifted/students", payload, headers)

    def bulk_enroll_students(self, payload, headers):
        return self._request("POST", "/gifted/students/bulk-enroll", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/gifted/students/{student_id}", headers=headers)

    # --- SpedPlan ---
    def create_sped_plan(self, student_id, payload, headers):
        return self._request("POST", f"/gifted/students/{student_id}/sped-plans",
                             payload, headers)

    def list_sped_plans(self, student_id, headers):
        return self._request("GET", f"/gifted/students/{student_id}/sped-plans",
                             headers=headers)

    # --- ScreeningCycle ---
    def create_screening_cycle(self, payload, headers):
        return self._request("POST", "/gifted/screening-cycles", payload, headers)

    def get_screening_cycle(self, cycle_id, headers):
        return self._request("GET", f"/gifted/screening-cycles/{cycle_id}",
                             headers=headers)

    def advance_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/gifted/screening-cycles/{cycle_id}/advance",
                             payload, headers)

    # --- CutScoreProfile ---
    def create_cut_score_profile(self, cycle_id, payload, headers):
        return self._request("POST",
                             f"/gifted/screening-cycles/{cycle_id}/cut-score-profiles",
                             payload, headers)

    def list_cut_score_profiles(self, cycle_id, headers, params=None):
        return self._request("GET",
                             f"/gifted/screening-cycles/{cycle_id}/cut-score-profiles",
                             headers=headers, params=params)

    def publish_cut_score_profile(self, profile_id, payload, headers):
        return self._request("POST", f"/gifted/cut-score-profiles/{profile_id}/publish",
                             payload, headers)

    # --- GiftedCase ---
    def create_case(self, payload, headers):
        return self._request("POST", "/gifted/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/gifted/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/gifted/cases/{case_id}", headers=headers)

    # --- MeasureScore ---
    def create_measure_score(self, case_id, payload, headers):
        return self._request("POST", f"/gifted/cases/{case_id}/measure-scores",
                             payload, headers)

    def list_measure_scores(self, case_id, headers):
        return self._request("GET", f"/gifted/cases/{case_id}/measure-scores",
                             headers=headers)

    def finalize_scoring(self, case_id, headers, payload=None):
        return self._request("POST", f"/gifted/cases/{case_id}/finalize-scoring",
                             payload or {}, headers)

    # --- CommitteeReview / votes ---
    def create_committee_review(self, case_id, payload, headers):
        return self._request("POST", f"/gifted/cases/{case_id}/committee-reviews",
                             payload, headers)

    def list_case_reviews(self, case_id, headers):
        return self._request("GET", f"/gifted/cases/{case_id}/committee-reviews",
                             headers=headers)

    def get_committee_review(self, review_id, headers):
        return self._request("GET", f"/gifted/committee-reviews/{review_id}",
                             headers=headers)

    def cast_vote(self, review_id, payload, headers):
        return self._request("POST", f"/gifted/committee-reviews/{review_id}/votes",
                             payload, headers)

    def list_votes(self, review_id, headers):
        return self._request("GET", f"/gifted/committee-reviews/{review_id}/votes",
                             headers=headers)

    def conclude_review(self, review_id, headers, payload=None):
        return self._request("POST", f"/gifted/committee-reviews/{review_id}/conclude",
                             payload or {}, headers)

    # --- ServicePlacement ---
    def create_placement(self, case_id, payload, headers):
        return self._request("POST", f"/gifted/cases/{case_id}/placements",
                             payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/gifted/placements/{placement_id}",
                             headers=headers)

    def list_case_placements(self, case_id, headers):
        return self._request("GET", f"/gifted/cases/{case_id}/placements",
                             headers=headers)

    def accept_placement(self, placement_id, headers, payload=None):
        return self._request("POST", f"/gifted/placements/{placement_id}/accept",
                             payload or {}, headers)

    def decline_placement(self, placement_id, headers, payload=None):
        return self._request("POST", f"/gifted/placements/{placement_id}/decline",
                             payload or {}, headers)

    def withdraw_placement(self, placement_id, headers, payload=None):
        return self._request("POST", f"/gifted/placements/{placement_id}/withdraw",
                             payload or {}, headers)

    # --- ReEvaluation ---
    def create_re_evaluation(self, placement_id, payload, headers):
        return self._request("POST",
                             f"/gifted/placements/{placement_id}/re-evaluations",
                             payload, headers)

    def list_re_evaluations(self, placement_id, headers):
        return self._request("GET",
                             f"/gifted/placements/{placement_id}/re-evaluations",
                             headers=headers)

    def conclude_re_evaluation(self, re_eval_id, payload, headers):
        return self._request("POST",
                             f"/gifted/re-evaluations/{re_eval_id}/conclude",
                             payload, headers)

    # --- Disproportionality report ---
    def get_disproportionality_report(self, cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"/gifted/screening-cycles/{cycle_id}/disproportionality-report",
            headers=headers, params=params)


api_client = ApiClient()
# The runner restarts the server process before every test (per-test-server
# isolation). A pooled keep-alive connection to the previous server process
# can survive the readiness probe and then be reused by the next test's first
# request, surfacing as RemoteDisconnected / ConnectionResetError under load.
# Disable keep-alive so every request opens a fresh connection to the live
# server. Transport-only change; no assertion semantics are affected.
api_client.session.headers["Connection"] = "close"
