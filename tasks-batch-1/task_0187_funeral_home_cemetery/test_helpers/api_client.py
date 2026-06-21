"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- FuneralHome ----
    def create_funeral_home(self, payload, headers):
        return self._request("POST", "/funeral-homes", payload, headers)

    def get_funeral_home(self, home_id, headers):
        return self._request("GET", f"/funeral-homes/{home_id}", headers=headers)

    # ---- GplItem ----
    def create_gpl_item(self, payload, headers):
        return self._request("POST", "/gpl-items", payload, headers)

    def get_gpl_item(self, item_id, headers):
        return self._request("GET", f"/gpl-items/{item_id}", headers=headers)

    def list_gpl_items(self, headers, params=None):
        return self._request("GET", "/gpl-items", headers=headers, params=params)

    def update_gpl_item(self, item_id, payload, headers):
        return self._request("PATCH", f"/gpl-items/{item_id}", payload, headers)

    # ---- Case ----
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def acknowledge_disclosure(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/acknowledge-disclosure", {}, headers)

    def issue_gfs(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/issue-gfs", {}, headers)

    def complete_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/complete", {}, headers)

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/cancel", {}, headers)

    # ---- StatementLine ----
    def add_statement_line(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/statement-lines", payload, headers)

    def list_case_statement_lines(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/statement-lines", headers=headers, params=params)

    def get_statement_line(self, line_id, headers):
        return self._request("GET", f"/statement-lines/{line_id}", headers=headers)

    def list_statement_lines(self, headers, params=None):
        return self._request("GET", "/statement-lines", headers=headers, params=params)

    def select_statement_line(self, case_id, line_id, headers):
        return self._request("POST", f"/cases/{case_id}/statement-lines/{line_id}/select", {}, headers)

    def remove_statement_line(self, case_id, line_id, headers):
        return self._request("POST", f"/cases/{case_id}/statement-lines/{line_id}/remove", {}, headers)

    # ---- Contract ----
    def create_contract(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/contract", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def submit_for_funding(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/submit-for-funding", {}, headers)

    def reopen_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/reopen", {}, headers)

    def mark_funded(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/mark-funded", payload, headers)

    # ---- TrustDeposit ----
    def post_trust_deposit(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/trust-deposits", payload, headers)

    def list_contract_trust_deposits(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/trust-deposits", headers=headers, params=params)

    def get_trust_deposit(self, deposit_id, headers):
        return self._request("GET", f"/trust-deposits/{deposit_id}", headers=headers)

    def list_trust_deposits(self, headers, params=None):
        return self._request("GET", "/trust-deposits", headers=headers, params=params)

    # ---- InsuranceAssignment ----
    def attach_insurance_assignment(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/insurance-assignments", payload, headers)

    def get_insurance_assignment(self, assignment_id, headers):
        return self._request("GET", f"/insurance-assignments/{assignment_id}", headers=headers)

    def list_insurance_assignments(self, headers, params=None):
        return self._request("GET", "/insurance-assignments", headers=headers, params=params)

    def verify_insurance_assignment(self, assignment_id, headers):
        return self._request("POST", f"/insurance-assignments/{assignment_id}/verify", {}, headers)

    def decline_insurance_assignment(self, assignment_id, headers):
        return self._request("POST", f"/insurance-assignments/{assignment_id}/decline", {}, headers)

    # ---- Plot ----
    def create_plot(self, payload, headers):
        return self._request("POST", "/plots", payload, headers)

    def get_plot(self, plot_id, headers):
        return self._request("GET", f"/plots/{plot_id}", headers=headers)

    def list_plots(self, headers, params=None):
        return self._request("GET", "/plots", headers=headers, params=params)

    def reserve_plot(self, plot_id, payload, headers):
        return self._request("POST", f"/plots/{plot_id}/reserve", payload, headers)

    def release_plot(self, plot_id, headers):
        return self._request("POST", f"/plots/{plot_id}/release", {}, headers)

    def inter_plot(self, plot_id, headers):
        return self._request("POST", f"/plots/{plot_id}/inter", {}, headers)

    # ---- Venue ----
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/venues", headers=headers, params=params)

    # ---- Event ----
    def create_event(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/events", payload, headers)

    def list_case_events(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def cancel_event(self, case_id, event_id, headers):
        return self._request("POST", f"/cases/{case_id}/events/{event_id}/cancel", {}, headers)

    # ---- Permit ----
    def apply_permit(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/permits", payload, headers)

    def list_case_permits(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def issue_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/issue", payload, headers)

    def reject_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/reject", {}, headers)

    def reapply_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/reapply", {}, headers)


api_client = ApiClient()
