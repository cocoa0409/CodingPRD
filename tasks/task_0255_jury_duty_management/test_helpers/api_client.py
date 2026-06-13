"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- ServiceTerm ----
    def create_service_term(self, payload, headers):
        return self._request("POST", "/service-terms", payload, headers)

    def list_service_terms(self, headers, params=None):
        return self._request("GET", "/service-terms", headers=headers, params=params)

    def get_service_term(self, term_id, headers):
        return self._request("GET", f"/service-terms/{term_id}", headers=headers)

    def open_service_term(self, term_id, headers):
        return self._request("POST", f"/service-terms/{term_id}/open", {}, headers)

    def close_service_term(self, term_id, headers):
        return self._request("POST", f"/service-terms/{term_id}/close", {}, headers)

    def draw(self, term_id, payload, headers):
        return self._request("POST", f"/service-terms/{term_id}/draw", payload, headers)

    def pool_projection(self, term_id, headers):
        return self._request("GET", f"/service-terms/{term_id}/pool-projection", headers=headers)

    # ---- Juror (pool) ----
    def create_juror(self, term_id, payload, headers):
        return self._request("POST", f"/service-terms/{term_id}/jurors", payload, headers)

    def list_term_jurors(self, term_id, headers, params=None):
        return self._request("GET", f"/service-terms/{term_id}/jurors", headers=headers, params=params)

    def get_juror(self, juror_id, headers):
        return self._request("GET", f"/jurors/{juror_id}", headers=headers)

    def list_juror_summonses(self, juror_id, headers, params=None):
        return self._request("GET", f"/jurors/{juror_id}/summonses", headers=headers, params=params)

    def qualify_juror(self, juror_id, headers):
        return self._request("POST", f"/jurors/{juror_id}/qualify", {}, headers)

    # ---- Summons ----
    def list_term_summonses(self, term_id, headers, params=None):
        return self._request("GET", f"/service-terms/{term_id}/summonses", headers=headers, params=params)

    def get_summons(self, summons_id, headers):
        return self._request("GET", f"/summonses/{summons_id}", headers=headers)

    def submit_qualification(self, summons_id, payload, headers):
        return self._request("POST", f"/summonses/{summons_id}/qualification", payload, headers)

    def get_qualification(self, summons_id, headers):
        return self._request("GET", f"/summonses/{summons_id}/qualification", headers=headers)

    def check_in(self, summons_id, payload, headers):
        return self._request("POST", f"/summonses/{summons_id}/check-in", payload, headers)

    def list_check_ins(self, summons_id, headers, params=None):
        return self._request("GET", f"/summonses/{summons_id}/check-ins", headers=headers, params=params)

    def release_summons(self, summons_id, headers):
        return self._request("POST", f"/summonses/{summons_id}/release", {}, headers)

    def mark_fta(self, summons_id, headers):
        return self._request("POST", f"/summonses/{summons_id}/mark-fta", {}, headers)

    def list_pay_vouchers(self, summons_id, headers, params=None):
        return self._request("GET", f"/summonses/{summons_id}/pay-vouchers", headers=headers, params=params)

    # ---- Disposition ----
    def create_disposition(self, summons_id, payload, headers):
        return self._request("POST", f"/summonses/{summons_id}/dispositions", payload, headers)

    def list_summons_dispositions(self, summons_id, headers, params=None):
        return self._request("GET", f"/summonses/{summons_id}/dispositions", headers=headers, params=params)

    def decide_disposition(self, disposition_id, payload, headers):
        return self._request("POST", f"/dispositions/{disposition_id}/decide", payload, headers)

    def get_disposition(self, disposition_id, headers):
        return self._request("GET", f"/dispositions/{disposition_id}", headers=headers)

    def list_dispositions(self, headers, params=None):
        return self._request("GET", "/dispositions", headers=headers, params=params)

    # ---- Trial ----
    def create_trial(self, term_id, payload, headers):
        return self._request("POST", f"/service-terms/{term_id}/trials", payload, headers)

    def list_term_trials(self, term_id, headers, params=None):
        return self._request("GET", f"/service-terms/{term_id}/trials", headers=headers, params=params)

    def get_trial(self, trial_id, headers):
        return self._request("GET", f"/trials/{trial_id}", headers=headers)

    def ready_trial(self, trial_id, headers):
        return self._request("POST", f"/trials/{trial_id}/ready", {}, headers)

    # ---- Panel ----
    def create_panel(self, trial_id, payload, headers):
        return self._request("POST", f"/trials/{trial_id}/panels", payload, headers)

    def list_trial_panels(self, trial_id, headers, params=None):
        return self._request("GET", f"/trials/{trial_id}/panels", headers=headers, params=params)

    def list_term_panels(self, term_id, headers, params=None):
        return self._request("GET", f"/service-terms/{term_id}/panels", headers=headers, params=params)

    def get_panel(self, panel_id, headers):
        return self._request("GET", f"/panels/{panel_id}", headers=headers)

    def seat(self, panel_id, payload, headers):
        return self._request("POST", f"/panels/{panel_id}/seat", payload, headers)

    def dismiss_panel(self, panel_id, headers):
        return self._request("POST", f"/panels/{panel_id}/dismiss", {}, headers)

    def list_panel_assignments(self, panel_id, headers, params=None):
        return self._request("GET", f"/panels/{panel_id}/assignments", headers=headers, params=params)

    def list_summons_assignments(self, summons_id, headers, params=None):
        return self._request("GET", f"/summonses/{summons_id}/assignments", headers=headers, params=params)

    def excuse_from_panel(self, assignment_id, headers):
        return self._request("POST", f"/panel-assignments/{assignment_id}/excuse-from-panel", {}, headers)

    def get_panel_assignment(self, assignment_id, headers):
        return self._request("GET", f"/panel-assignments/{assignment_id}", headers=headers)

    # ---- Strike (FTA history) ----
    def list_juror_strikes(self, juror_id, headers, params=None):
        return self._request("GET", f"/jurors/{juror_id}/strikes", headers=headers, params=params)

    def list_summons_strikes(self, summons_id, headers, params=None):
        return self._request("GET", f"/summonses/{summons_id}/strikes", headers=headers, params=params)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
