"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Jurisdictions ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/hotline/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/hotline/jurisdictions/{jurisdiction_id}", headers=headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/hotline/jurisdictions", headers=headers, params=params)

    # --- Rights scripts ---
    def create_script(self, payload, headers):
        return self._request("POST", "/hotline/scripts", payload, headers)

    def get_script(self, script_id, headers):
        return self._request("GET", f"/hotline/scripts/{script_id}", headers=headers)

    def list_scripts(self, headers, params=None):
        return self._request("GET", "/hotline/scripts", headers=headers, params=params)

    def transition_script(self, script_id, payload, headers):
        return self._request("POST", f"/hotline/scripts/{script_id}/state", payload, headers)

    # --- Self-help resources ---
    def create_self_help_resource(self, payload, headers):
        return self._request("POST", "/hotline/self-help-resources", payload, headers)

    def get_self_help_resource(self, resource_id, headers):
        return self._request("GET", f"/hotline/self-help-resources/{resource_id}", headers=headers)

    def list_self_help_resources(self, headers, params=None):
        return self._request("GET", "/hotline/self-help-resources", headers=headers, params=params)

    def transition_self_help_resource(self, resource_id, payload, headers):
        return self._request("POST", f"/hotline/self-help-resources/{resource_id}/state", payload, headers)

    # --- Counselors ---
    def create_counselor(self, payload, headers):
        return self._request("POST", "/hotline/counselors", payload, headers)

    def get_counselor(self, counselor_id, headers):
        return self._request("GET", f"/hotline/counselors/{counselor_id}", headers=headers)

    def update_counselor(self, counselor_id, payload, headers):
        return self._request("PATCH", f"/hotline/counselors/{counselor_id}", payload, headers)

    def create_training_certification(self, counselor_id, payload, headers):
        return self._request("POST", f"/hotline/counselors/{counselor_id}/training-certifications", payload, headers)

    # --- Interpreters ---
    def create_interpreter(self, payload, headers):
        return self._request("POST", "/hotline/interpreters", payload, headers)

    def get_interpreter(self, interpreter_id, headers):
        return self._request("GET", f"/hotline/interpreters/{interpreter_id}", headers=headers)

    # --- Callers & consents ---
    def create_caller(self, payload, headers):
        return self._request("POST", "/hotline/callers", payload, headers)

    def get_caller(self, caller_id, headers):
        return self._request("GET", f"/hotline/callers/{caller_id}", headers=headers)

    def grant_consent(self, caller_id, payload, headers):
        return self._request("POST", f"/hotline/callers/{caller_id}/consents", payload, headers)

    def list_consents(self, caller_id, headers, params=None):
        return self._request("GET", f"/hotline/callers/{caller_id}/consents", headers=headers, params=params)

    def revoke_consent(self, consent_id, headers):
        return self._request("POST", f"/hotline/consents/{consent_id}/revoke", {}, headers)

    # --- Call sessions ---
    def create_session(self, payload, headers):
        return self._request("POST", "/hotline/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/hotline/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/hotline/sessions", headers=headers, params=params)

    def transition_session(self, session_id, payload, headers):
        return self._request("POST", f"/hotline/sessions/{session_id}/state", payload, headers)

    def transition_interpretation(self, session_id, payload, headers):
        return self._request("POST", f"/hotline/sessions/{session_id}/interpretation", payload, headers)

    # --- Cases ---
    def create_case(self, payload, headers):
        return self._request("POST", "/hotline/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/hotline/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/hotline/cases", headers=headers, params=params)

    def update_case(self, case_id, payload, headers):
        return self._request("PATCH", f"/hotline/cases/{case_id}", payload, headers)

    def verify_case(self, case_id, headers):
        return self._request("POST", f"/hotline/cases/{case_id}/verify", {}, headers)

    def transition_case(self, case_id, payload, headers):
        return self._request("POST", f"/hotline/cases/{case_id}/state", payload, headers)

    def create_case_note(self, case_id, payload, headers):
        return self._request("POST", f"/hotline/cases/{case_id}/notes", payload, headers)

    def list_case_notes(self, case_id, headers, params=None):
        return self._request("GET", f"/hotline/cases/{case_id}/notes", headers=headers, params=params)

    def list_counselor_notes(self, counselor_id, headers, params=None):
        return self._request("GET", f"/hotline/counselors/{counselor_id}/notes", headers=headers, params=params)

    # --- Follow-ups ---
    def create_follow_up(self, case_id, payload, headers):
        return self._request("POST", f"/hotline/cases/{case_id}/follow-ups", payload, headers)

    def list_case_follow_ups(self, case_id, headers, params=None):
        return self._request("GET", f"/hotline/cases/{case_id}/follow-ups", headers=headers, params=params)

    def transition_follow_up(self, follow_up_id, payload, headers):
        return self._request("POST", f"/hotline/follow-ups/{follow_up_id}/state", payload, headers)

    # --- Legal-aid organizations ---
    def create_legal_aid_org(self, payload, headers):
        return self._request("POST", "/hotline/legal-aid-orgs", payload, headers)

    def get_legal_aid_org(self, org_id, headers):
        return self._request("GET", f"/hotline/legal-aid-orgs/{org_id}", headers=headers)

    def update_legal_aid_org(self, org_id, payload, headers):
        return self._request("PATCH", f"/hotline/legal-aid-orgs/{org_id}", payload, headers)

    # --- Referrals ---
    def create_referral(self, case_id, payload, headers):
        return self._request("POST", f"/hotline/cases/{case_id}/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/hotline/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/hotline/referrals", headers=headers, params=params)

    def transition_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/hotline/referrals/{referral_id}/state", payload, headers)

    # --- Retention policies ---
    def create_retention_policy(self, payload, headers):
        return self._request("POST", "/hotline/retention-policies", payload, headers)

    def get_retention_policy(self, policy_id, headers):
        return self._request("GET", f"/hotline/retention-policies/{policy_id}", headers=headers)

    def list_retention_policies(self, headers, params=None):
        return self._request("GET", "/hotline/retention-policies", headers=headers, params=params)

    # --- Purge jobs ---
    def get_purge_job(self, purge_job_id, headers):
        return self._request("GET", f"/hotline/purge-jobs/{purge_job_id}", headers=headers)

    def list_purge_jobs(self, headers, params=None):
        return self._request("GET", "/hotline/purge-jobs", headers=headers, params=params)

    def execute_purge_job(self, purge_job_id, headers):
        return self._request("POST", f"/hotline/purge-jobs/{purge_job_id}/execute", {}, headers)

    # --- Analytics ---
    def get_call_volume(self, headers, params=None):
        return self._request("GET", "/hotline/analytics/call-volume", headers=headers, params=params)

    # --- Operator clock & sweep (outside /hotline) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_time_sweep(self, headers):
        return self._request("POST", "/_ops/run_time_sweep", {}, headers)


api_client = ApiClient()
