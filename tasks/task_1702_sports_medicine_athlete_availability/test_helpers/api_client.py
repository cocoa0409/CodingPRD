"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/sports-med"


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --- Teams ---
    def create_team(self, payload, headers):
        return self._request("POST", f"{PREFIX}/teams", payload, headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/teams", headers=headers, params=params)

    def get_team(self, team_id, headers):
        return self._request("GET", f"{PREFIX}/teams/{team_id}", headers=headers)

    # --- Diagnosis codes ---
    def create_diagnosis_code(self, payload, headers):
        return self._request("POST", f"{PREFIX}/diagnosis-codes", payload, headers)

    def list_diagnosis_codes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/diagnosis-codes", headers=headers, params=params)

    def get_diagnosis_code(self, code_id, headers):
        return self._request("GET", f"{PREFIX}/diagnosis-codes/{code_id}", headers=headers)

    # --- Athletes ---
    def create_athlete(self, payload, headers):
        return self._request("POST", f"{PREFIX}/athletes", payload, headers)

    def list_athletes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/athletes", headers=headers, params=params)

    def get_athlete(self, athlete_id, headers):
        return self._request("GET", f"{PREFIX}/athletes/{athlete_id}", headers=headers)

    def deactivate_athlete(self, athlete_id, headers):
        return self._request("POST", f"{PREFIX}/athletes/{athlete_id}/deactivate", {}, headers)

    def reactivate_athlete(self, athlete_id, headers):
        return self._request("POST", f"{PREFIX}/athletes/{athlete_id}/reactivate", {}, headers)

    def release_athlete(self, athlete_id, headers):
        return self._request("POST", f"{PREFIX}/athletes/{athlete_id}/release", {}, headers)

    # --- Injury cases ---
    def create_injury_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/injury-cases", payload, headers)

    def list_injury_cases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/injury-cases", headers=headers, params=params)

    def get_injury_case(self, case_id, headers):
        return self._request("GET", f"{PREFIX}/injury-cases/{case_id}", headers=headers)

    def start_rehab(self, case_id, headers):
        return self._request("POST", f"{PREFIX}/injury-cases/{case_id}/start-rehab", {}, headers)

    def mark_long_term(self, case_id, headers):
        return self._request("POST", f"{PREFIX}/injury-cases/{case_id}/mark-long-term", {}, headers)

    def resume_rehab(self, case_id, headers):
        return self._request("POST", f"{PREFIX}/injury-cases/{case_id}/resume-rehab", {}, headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"{PREFIX}/injury-cases/{case_id}/close", {}, headers)

    # --- Treatment plans ---
    def create_treatment_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/treatment-plans", payload, headers)

    def list_treatment_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/treatment-plans", headers=headers, params=params)

    def get_treatment_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/treatment-plans/{plan_id}", headers=headers)

    def activate_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/treatment-plans/{plan_id}/activate", {}, headers)

    def suspend_plan(self, plan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/treatment-plans/{plan_id}/suspend", payload, headers)

    def resume_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/treatment-plans/{plan_id}/resume", {}, headers)

    def complete_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/treatment-plans/{plan_id}/complete", {}, headers)

    # --- Daily status entries ---
    def create_daily_status_entry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/daily-status-entries", payload, headers)

    def list_daily_status_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/daily-status-entries", headers=headers, params=params)

    def get_daily_status_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/daily-status-entries/{entry_id}", headers=headers)

    # --- RTP protocols ---
    def create_rtp_protocol(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rtp-protocols", payload, headers)

    def list_rtp_protocols(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rtp-protocols", headers=headers, params=params)

    def get_rtp_protocol(self, protocol_id, headers):
        return self._request("GET", f"{PREFIX}/rtp-protocols/{protocol_id}", headers=headers)

    def advance_rtp_protocol(self, protocol_id, payload, headers):
        return self._request("POST", f"{PREFIX}/rtp-protocols/{protocol_id}/advances", payload, headers)

    def list_protocol_advances(self, protocol_id, headers):
        return self._request("GET", f"{PREFIX}/rtp-protocols/{protocol_id}/advances", headers=headers)

    def list_rtp_stage_advances(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rtp-stage-advances", headers=headers, params=params)

    def get_rtp_stage_advance(self, advance_id, headers):
        return self._request("GET", f"{PREFIX}/rtp-stage-advances/{advance_id}", headers=headers)

    def regress_rtp_protocol(self, protocol_id, payload, headers):
        return self._request("POST", f"{PREFIX}/rtp-protocols/{protocol_id}/regress", payload, headers)

    # --- Clearances ---
    def request_clearance(self, protocol_id, payload, headers):
        return self._request("POST", f"{PREFIX}/rtp-protocols/{protocol_id}/clearances", payload, headers)

    def list_clearances(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/clearances", headers=headers, params=params)

    def get_clearance(self, clearance_id, headers):
        return self._request("GET", f"{PREFIX}/clearances/{clearance_id}", headers=headers)

    def decide_clearance(self, clearance_id, payload, headers):
        return self._request("POST", f"{PREFIX}/clearances/{clearance_id}/decide", payload, headers)

    # --- Workload sessions ---
    def create_workload_session(self, payload, headers):
        return self._request("POST", f"{PREFIX}/workload-sessions", payload, headers)

    def list_workload_sessions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/workload-sessions", headers=headers, params=params)

    def get_workload_session(self, session_id, headers):
        return self._request("GET", f"{PREFIX}/workload-sessions/{session_id}", headers=headers)

    # --- Insurance policies ---
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", f"{PREFIX}/insurance-policies", payload, headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/insurance-policies", headers=headers, params=params)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"{PREFIX}/insurance-policies/{policy_id}", headers=headers)

    def cancel_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"{PREFIX}/insurance-policies/{policy_id}/cancel", {}, headers)

    # --- Claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def submit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/submit", payload, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/adjudicate", payload, headers)

    def appeal_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/appeal", payload, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/void", {}, headers)

    # --- Disclosure grants ---
    def create_disclosure_grant(self, payload, headers):
        return self._request("POST", f"{PREFIX}/disclosure-grants", payload, headers)

    def list_disclosure_grants(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/disclosure-grants", headers=headers, params=params)

    def get_disclosure_grant(self, grant_id, headers):
        return self._request("GET", f"{PREFIX}/disclosure-grants/{grant_id}", headers=headers)

    def revoke_disclosure_grant(self, grant_id, headers):
        return self._request("POST", f"{PREFIX}/disclosure-grants/{grant_id}/revoke", {}, headers)

    # --- Availability reports & analytics ---
    def create_availability_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/availability-reports", payload, headers)

    def list_availability_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/availability-reports", headers=headers, params=params)

    def get_availability_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/availability-reports/{report_id}", headers=headers)

    def get_injury_rates(self, team_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/teams/{team_id}/analytics/injury-rates",
            headers=headers, params=params,
        )


api_client = ApiClient()
