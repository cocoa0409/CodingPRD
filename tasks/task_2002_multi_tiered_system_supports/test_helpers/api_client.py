"""API client: one method per endpoint defined in the PRD (§4 endpoint index)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.7)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Districts
    # ------------------------------------------------------------------
    def create_district(self, payload, headers):
        return self._request("POST", "/districts", payload, headers)

    def list_districts(self, headers, params=None):
        return self._request("GET", "/districts", headers=headers, params=params)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/districts/{district_id}", headers=headers)

    # ------------------------------------------------------------------
    # Schools
    # ------------------------------------------------------------------
    def create_school(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/schools",
                             payload, headers)

    def list_schools(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/schools",
                             headers=headers, params=params)

    def get_school(self, district_id, school_id, headers):
        return self._request("GET", f"/districts/{district_id}/schools/{school_id}",
                             headers=headers)

    def get_school_flat(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}", headers=headers)

    # ------------------------------------------------------------------
    # Screening windows
    # ------------------------------------------------------------------
    def create_screening_window(self, district_id, school_id, payload, headers):
        return self._request(
            "POST", f"/districts/{district_id}/schools/{school_id}/screening-windows",
            payload, headers)

    def get_screening_window(self, district_id, school_id, window_id, headers):
        return self._request(
            "GET",
            f"/districts/{district_id}/schools/{school_id}/screening-windows/{window_id}",
            headers=headers)

    def list_screening_windows(self, district_id, school_id, headers, params=None):
        return self._request(
            "GET", f"/districts/{district_id}/schools/{school_id}/screening-windows",
            headers=headers, params=params)

    def close_screening_window(self, district_id, school_id, window_id, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/screening-windows/{window_id}/close",
            {}, headers)

    def score_screening_window(self, district_id, school_id, window_id, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/screening-windows/{window_id}/score",
            {}, headers)

    def get_screening_window_flat(self, window_id, headers):
        return self._request("GET", f"/screening-windows/{window_id}", headers=headers)

    # ------------------------------------------------------------------
    # Benchmark cut points
    # ------------------------------------------------------------------
    def create_benchmark_cut_point(self, district_id, school_id, payload, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/benchmark-cut-points",
            payload, headers)

    def list_benchmark_cut_points(self, district_id, school_id, headers, params=None):
        return self._request(
            "GET",
            f"/districts/{district_id}/schools/{school_id}/benchmark-cut-points",
            headers=headers, params=params)

    def get_benchmark_cut_point_flat(self, cutpoint_id, headers):
        return self._request("GET", f"/benchmark-cut-points/{cutpoint_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Students
    # ------------------------------------------------------------------
    def create_student(self, district_id, school_id, payload, headers):
        return self._request(
            "POST", f"/districts/{district_id}/schools/{school_id}/students",
            payload, headers)

    def get_student(self, district_id, school_id, student_id, headers):
        return self._request(
            "GET",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}",
            headers=headers)

    def list_students(self, district_id, school_id, headers, params=None):
        return self._request(
            "GET", f"/districts/{district_id}/schools/{school_id}/students",
            headers=headers, params=params)

    def get_student_flat(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    # ------------------------------------------------------------------
    # Screening scores
    # ------------------------------------------------------------------
    def record_screening_score(self, district_id, school_id, window_id, payload, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/screening-windows/{window_id}/scores",
            payload, headers)

    def list_screening_scores(self, district_id, school_id, window_id, headers,
                              params=None):
        return self._request(
            "GET",
            f"/districts/{district_id}/schools/{school_id}/screening-windows/{window_id}/scores",
            headers=headers, params=params)

    def get_screening_score_flat(self, score_id, headers):
        return self._request("GET", f"/screening-scores/{score_id}", headers=headers)

    # ------------------------------------------------------------------
    # Intervention catalog
    # ------------------------------------------------------------------
    def create_catalog_entry(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/intervention-catalog",
                             payload, headers)

    def list_catalog_entries(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/intervention-catalog",
                             headers=headers, params=params)

    def get_catalog_entry(self, district_id, entry_id, headers):
        return self._request(
            "GET", f"/districts/{district_id}/intervention-catalog/{entry_id}",
            headers=headers)

    def get_catalog_entry_flat(self, entry_id, headers):
        return self._request("GET", f"/intervention-catalog/{entry_id}", headers=headers)

    # ------------------------------------------------------------------
    # Interventionists
    # ------------------------------------------------------------------
    def create_interventionist(self, district_id, school_id, payload, headers):
        return self._request(
            "POST", f"/districts/{district_id}/schools/{school_id}/interventionists",
            payload, headers)

    def get_interventionist(self, district_id, school_id, interventionist_id, headers):
        return self._request(
            "GET",
            f"/districts/{district_id}/schools/{school_id}/interventionists/{interventionist_id}",
            headers=headers)

    def list_interventionists(self, district_id, school_id, headers, params=None):
        return self._request(
            "GET", f"/districts/{district_id}/schools/{school_id}/interventionists",
            headers=headers, params=params)

    def get_interventionist_flat(self, interventionist_id, headers):
        return self._request("GET", f"/interventionists/{interventionist_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Student plans
    # ------------------------------------------------------------------
    def create_plan(self, district_id, school_id, student_id, payload, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/plans",
            payload, headers)

    def get_plan(self, district_id, school_id, student_id, plan_id, headers):
        return self._request(
            "GET",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/plans/{plan_id}",
            headers=headers)

    def list_plans(self, district_id, school_id, student_id, headers, params=None):
        return self._request(
            "GET",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/plans",
            headers=headers, params=params)

    def pause_plan(self, district_id, school_id, student_id, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/plans/{plan_id}/pause",
            payload, headers)

    def resume_plan(self, district_id, school_id, student_id, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/plans/{plan_id}/resume",
            payload, headers)

    def exit_plan(self, district_id, school_id, student_id, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/plans/{plan_id}/exit",
            payload, headers)

    def cancel_plan(self, district_id, school_id, student_id, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/plans/{plan_id}/cancel",
            payload, headers)

    def get_plan_flat(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    # ------------------------------------------------------------------
    # Progress probes
    # ------------------------------------------------------------------
    def record_probe(self, district_id, school_id, student_id, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/plans/{plan_id}/probes",
            payload, headers)

    def list_probes(self, district_id, school_id, student_id, plan_id, headers,
                    params=None):
        return self._request(
            "GET",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/plans/{plan_id}/probes",
            headers=headers, params=params)

    def get_probe_flat(self, probe_id, headers):
        return self._request("GET", f"/probes/{probe_id}", headers=headers)

    # ------------------------------------------------------------------
    # Intervention sessions
    # ------------------------------------------------------------------
    def record_session(self, district_id, school_id, student_id, plan_id, payload,
                       headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/plans/{plan_id}/sessions",
            payload, headers)

    def list_sessions(self, district_id, school_id, student_id, plan_id, headers,
                      params=None):
        return self._request(
            "GET",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/plans/{plan_id}/sessions",
            headers=headers, params=params)

    def get_session_flat(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    # ------------------------------------------------------------------
    # Tier movements
    # ------------------------------------------------------------------
    def propose_tier_movement(self, district_id, school_id, student_id, payload, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/tier-movements",
            payload, headers)

    def list_tier_movements(self, district_id, school_id, student_id, headers,
                            params=None):
        return self._request(
            "GET",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/tier-movements",
            headers=headers, params=params)

    def get_tier_movement(self, district_id, school_id, student_id, movement_id, headers):
        return self._request(
            "GET",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/tier-movements/{movement_id}",
            headers=headers)

    def get_tier_movement_flat(self, movement_id, headers):
        return self._request("GET", f"/tier-movements/{movement_id}", headers=headers)

    # ------------------------------------------------------------------
    # Team meetings
    # ------------------------------------------------------------------
    def create_team_meeting(self, district_id, school_id, payload, headers):
        return self._request(
            "POST", f"/districts/{district_id}/schools/{school_id}/team-meetings",
            payload, headers)

    def get_team_meeting(self, district_id, school_id, meeting_id, headers):
        return self._request(
            "GET",
            f"/districts/{district_id}/schools/{school_id}/team-meetings/{meeting_id}",
            headers=headers)

    def list_team_meetings(self, district_id, school_id, headers, params=None):
        return self._request(
            "GET", f"/districts/{district_id}/schools/{school_id}/team-meetings",
            headers=headers, params=params)

    def convene_team_meeting(self, district_id, school_id, meeting_id, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/team-meetings/{meeting_id}/convene",
            {}, headers)

    def ratify_movement(self, district_id, school_id, meeting_id, payload, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/team-meetings/{meeting_id}/ratify",
            payload, headers)

    def reject_movement(self, district_id, school_id, meeting_id, payload, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/team-meetings/{meeting_id}/reject",
            payload, headers)

    def minute_team_meeting(self, district_id, school_id, meeting_id, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/team-meetings/{meeting_id}/minute",
            {}, headers)

    def get_team_meeting_flat(self, meeting_id, headers):
        return self._request("GET", f"/team-meetings/{meeting_id}", headers=headers)

    # ------------------------------------------------------------------
    # Special-education referrals
    # ------------------------------------------------------------------
    def create_sped_referral(self, district_id, school_id, student_id, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/sped-referrals",
            {}, headers)

    def get_sped_referral(self, district_id, school_id, student_id, referral_id, headers):
        return self._request(
            "GET",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/sped-referrals/{referral_id}",
            headers=headers)

    def list_sped_referrals(self, district_id, school_id, student_id, headers,
                            params=None):
        return self._request(
            "GET",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/sped-referrals",
            headers=headers, params=params)

    def record_consent(self, district_id, school_id, student_id, referral_id, payload,
                       headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/sped-referrals/{referral_id}/record-consent",
            payload, headers)

    def start_evaluation(self, district_id, school_id, student_id, referral_id, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/sped-referrals/{referral_id}/start-evaluation",
            {}, headers)

    def determine_eligibility(self, district_id, school_id, student_id, referral_id,
                              payload, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/sped-referrals/{referral_id}/determine",
            payload, headers)

    def withdraw_referral(self, district_id, school_id, student_id, referral_id, headers):
        return self._request(
            "POST",
            f"/districts/{district_id}/schools/{school_id}/students/{student_id}/sped-referrals/{referral_id}/withdraw",
            {}, headers)

    def get_sped_referral_flat(self, referral_id, headers):
        return self._request("GET", f"/sped-referrals/{referral_id}", headers=headers)

    # ------------------------------------------------------------------
    # Outcome report
    # ------------------------------------------------------------------
    def get_outcome_report(self, district_id, window_id, headers):
        return self._request("GET", f"/districts/{district_id}/outcome-report",
                             headers=headers, params={"window_id": window_id})


api_client = ApiClient()
