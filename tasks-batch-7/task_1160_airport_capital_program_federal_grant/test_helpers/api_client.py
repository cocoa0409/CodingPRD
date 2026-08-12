"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving operational endpoints (outside /aip) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_checkpoint(self, headers):
        return self._request("POST", "/_ops/run_checkpoint", {}, headers)

    # --- Sponsors ---
    def create_sponsor(self, payload, headers):
        return self._request("POST", "/aip/sponsors", payload, headers)

    def list_sponsors(self, headers, params=None):
        return self._request("GET", "/aip/sponsors", headers=headers, params=params)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/aip/sponsors/{sponsor_id}", headers=headers)

    # --- Airfield facilities ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/aip/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/aip/facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/aip/facilities/{facility_id}", headers=headers)

    # --- Capital programs (CIP) ---
    def create_program(self, payload, headers):
        return self._request("POST", "/aip/capital-programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/aip/capital-programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/aip/capital-programs/{program_id}", headers=headers)

    def submit_program(self, program_id, headers):
        return self._request("POST", f"/aip/capital-programs/{program_id}/submit",
                             {}, headers)

    def accept_program(self, program_id, headers):
        return self._request("POST", f"/aip/capital-programs/{program_id}/accept",
                             {}, headers)

    def begin_amendment(self, program_id, headers):
        return self._request("POST", f"/aip/capital-programs/{program_id}/begin-amendment",
                             {}, headers)

    def apply_selection(self, program_id, payload, headers):
        return self._request("POST", f"/aip/capital-programs/{program_id}/apply-selection",
                             payload, headers)

    # --- CIP projects ---
    def create_project(self, payload, headers):
        return self._request("POST", "/aip/cip-projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/aip/cip-projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/aip/cip-projects/{project_id}", headers=headers)

    def drop_project(self, project_id, headers):
        return self._request("POST", f"/aip/cip-projects/{project_id}/drop", {}, headers)

    # --- Grant applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/aip/grant-applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/aip/grant-applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/aip/grant-applications/{application_id}",
                             headers=headers)

    def list_assurances(self, application_id, headers):
        return self._request("GET", f"/aip/grant-applications/{application_id}/assurances",
                             headers=headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/aip/grant-applications/{application_id}/submit",
                             {}, headers)

    def return_application(self, application_id, headers):
        return self._request("POST", f"/aip/grant-applications/{application_id}/return",
                             {}, headers)

    def offer_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/aip/grant-applications/{application_id}/offer",
                             payload or {}, headers)

    def accept_offer(self, application_id, headers):
        return self._request("POST", f"/aip/grant-applications/{application_id}/accept-offer",
                             {}, headers)

    def decline_offer(self, application_id, headers):
        return self._request("POST", f"/aip/grant-applications/{application_id}/decline-offer",
                             {}, headers)

    # --- Sponsor assurances ---
    def certify_assurance(self, assurance_id, headers):
        return self._request("POST", f"/aip/sponsor-assurances/{assurance_id}/certify",
                             {}, headers)

    def waive_assurance(self, assurance_id, headers):
        return self._request("POST", f"/aip/sponsor-assurances/{assurance_id}/waive",
                             {}, headers)

    # --- Grants ---
    def list_grants(self, headers, params=None):
        return self._request("GET", "/aip/grants", headers=headers, params=params)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/aip/grants/{grant_id}", headers=headers)

    def request_closeout(self, grant_id, headers):
        return self._request("POST", f"/aip/grants/{grant_id}/request-closeout", {}, headers)

    def begin_audit(self, grant_id, headers):
        return self._request("POST", f"/aip/grants/{grant_id}/begin-audit", {}, headers)

    def approve_closeout(self, grant_id, headers):
        return self._request("POST", f"/aip/grants/{grant_id}/approve-closeout", {}, headers)

    # --- Grant amendments ---
    def create_amendment(self, grant_id, payload, headers):
        return self._request("POST", f"/aip/grants/{grant_id}/amendments", payload, headers)

    def list_amendments(self, grant_id, headers, params=None):
        return self._request("GET", f"/aip/grants/{grant_id}/amendments",
                             headers=headers, params=params)

    def approve_amendment(self, amendment_id, headers):
        return self._request("POST", f"/aip/grant-amendments/{amendment_id}/approve",
                             {}, headers)

    def reject_amendment(self, amendment_id, headers):
        return self._request("POST", f"/aip/grant-amendments/{amendment_id}/reject",
                             {}, headers)

    # --- Contractors ---
    def create_contractor(self, payload, headers):
        return self._request("POST", "/aip/contractors", payload, headers)

    def list_contractors(self, headers, params=None):
        return self._request("GET", "/aip/contractors", headers=headers, params=params)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/aip/contractors/{contractor_id}", headers=headers)

    def suspend_contractor(self, contractor_id, headers):
        return self._request("POST", f"/aip/contractors/{contractor_id}/suspend", {}, headers)

    # --- Contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/aip/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/aip/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/aip/contracts/{contract_id}", headers=headers)

    # --- DBE reports ---
    def create_dbe_report(self, payload, headers):
        return self._request("POST", "/aip/dbe-reports", payload, headers)

    def list_dbe_reports(self, contract_id, headers, params=None):
        return self._request("GET", f"/aip/contracts/{contract_id}/dbe-reports",
                             headers=headers, params=params)

    def adjudicate_dbe_report(self, report_id, headers):
        return self._request("POST", f"/aip/dbe-reports/{report_id}/adjudicate", {}, headers)

    # --- Invoices ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/aip/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/aip/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/aip/invoices/{invoice_id}", headers=headers)

    def verify_invoice(self, invoice_id, headers):
        return self._request("POST", f"/aip/invoices/{invoice_id}/verify", {}, headers)

    def reject_invoice(self, invoice_id, headers):
        return self._request("POST", f"/aip/invoices/{invoice_id}/reject", {}, headers)

    # --- Reimbursement requests (drawdowns) ---
    def create_drawdown(self, payload, headers):
        return self._request("POST", "/aip/reimbursement-requests", payload, headers)

    def list_drawdowns(self, headers, params=None):
        return self._request("GET", "/aip/reimbursement-requests", headers=headers, params=params)

    def get_drawdown(self, request_id, headers):
        return self._request("GET", f"/aip/reimbursement-requests/{request_id}",
                             headers=headers)

    def certify_drawdown(self, request_id, headers):
        return self._request("POST", f"/aip/reimbursement-requests/{request_id}/certify",
                             {}, headers)

    def submit_drawdown(self, request_id, headers):
        return self._request("POST", f"/aip/reimbursement-requests/{request_id}/submit",
                             {}, headers)

    def approve_drawdown(self, request_id, headers):
        return self._request("POST", f"/aip/reimbursement-requests/{request_id}/approve",
                             {}, headers)

    def return_drawdown(self, request_id, headers):
        return self._request("POST", f"/aip/reimbursement-requests/{request_id}/return",
                             {}, headers)

    # --- Audit findings ---
    def create_audit_finding(self, payload, headers):
        return self._request("POST", "/aip/audit-findings", payload, headers)

    def list_audit_findings(self, grant_id, headers, params=None):
        return self._request("GET", f"/aip/grants/{grant_id}/audit-findings",
                             headers=headers, params=params)

    def resolve_audit_finding(self, finding_id, headers):
        return self._request("POST", f"/aip/audit-findings/{finding_id}/resolve", {}, headers)

    # --- Grant assets (useful life / disposal) ---
    def create_grant_asset(self, payload, headers):
        return self._request("POST", "/aip/grant-assets", payload, headers)

    def list_grant_assets(self, grant_id, headers, params=None):
        return self._request("GET", f"/aip/grants/{grant_id}/assets",
                             headers=headers, params=params)

    def request_disposal(self, asset_id, headers):
        return self._request("POST", f"/aip/grant-assets/{asset_id}/request-disposal",
                             {}, headers)

    def approve_disposal(self, asset_id, headers, payload=None):
        return self._request("POST", f"/aip/grant-assets/{asset_id}/approve-disposal",
                             payload or {}, headers)

    def return_to_service(self, asset_id, headers):
        return self._request("POST", f"/aip/grant-assets/{asset_id}/return-to-service",
                             {}, headers)

    # --- Construction phases ---
    def create_phase(self, payload, headers):
        return self._request("POST", "/aip/construction-phases", payload, headers)

    def list_phases(self, headers, params=None):
        return self._request("GET", "/aip/construction-phases", headers=headers, params=params)

    def get_phase(self, phase_id, headers):
        return self._request("GET", f"/aip/construction-phases/{phase_id}", headers=headers)

    def activate_phase(self, phase_id, headers):
        return self._request("POST", f"/aip/construction-phases/{phase_id}/activate",
                             {}, headers)

    def complete_phase(self, phase_id, headers):
        return self._request("POST", f"/aip/construction-phases/{phase_id}/complete",
                             {}, headers)

    def cancel_phase(self, phase_id, headers):
        return self._request("POST", f"/aip/construction-phases/{phase_id}/cancel",
                             {}, headers)


api_client = ApiClient()
