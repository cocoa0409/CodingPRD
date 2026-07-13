"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Program ----
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def update_program_funding(self, program_id, payload, headers):
        return self._request("PATCH", f"/programs/{program_id}/funding", payload, headers)

    # ---- Tenant ----
    def create_tenant(self, payload, headers=None):
        return self._request("POST", "/tenants", payload, headers)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    # ---- Landlord ----
    def create_landlord(self, payload, headers=None):
        return self._request("POST", "/landlords", payload, headers)

    def get_landlord(self, landlord_id, headers):
        return self._request("GET", f"/landlords/{landlord_id}", headers=headers)

    def submit_w9(self, landlord_id, payload, headers):
        return self._request("POST", f"/landlords/{landlord_id}/w9", payload, headers)

    def verify_w9(self, landlord_id, payload, headers):
        return self._request("POST", f"/landlords/{landlord_id}/w9/verify", payload, headers)

    # ---- Unit ----
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    # ---- Application ----
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def complete_tenant_section(self, application_id, payload, headers):
        return self._request("PATCH", f"/applications/{application_id}/tenant-section", payload, headers)

    def complete_landlord_section(self, application_id, payload, headers):
        return self._request("PATCH", f"/applications/{application_id}/landlord-section", payload, headers)

    def submit_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/applications/{application_id}/submit", payload or {}, headers)

    def review_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/applications/{application_id}/review", payload or {}, headers)

    def request_info(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/request-info", payload, headers)

    def resubmit_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/applications/{application_id}/resubmit", payload or {}, headers)

    def approve_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/approve", payload, headers)

    def deny_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/deny", payload, headers)

    # ---- IncomeSource ----
    def add_income_source(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/income-sources", payload, headers)

    def list_income_sources(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/income-sources", headers=headers, params=params)

    def get_income_source(self, income_source_id, headers):
        return self._request("GET", f"/income-sources/{income_source_id}", headers=headers)

    # ---- RentLedger / LedgerLine ----
    def create_ledger(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/ledger", payload, headers)

    def get_ledger(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}/ledger", headers=headers)

    def verify_ledger(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/ledger/verify", payload, headers)

    def get_ledger_line(self, ledger_line_id, headers):
        return self._request("GET", f"/ledger-lines/{ledger_line_id}", headers=headers)

    def list_ledger_lines(self, headers, params=None):
        return self._request("GET", "/ledger-lines", headers=headers, params=params)

    # ---- Disbursement ----
    def create_disbursement(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/disbursements", payload, headers)

    def list_disbursements(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/disbursements", headers=headers, params=params)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/disbursements/{disbursement_id}", headers=headers)

    def send_disbursement(self, disbursement_id, payload, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/send", payload, headers)

    def clear_disbursement(self, disbursement_id, headers, payload=None):
        return self._request("POST", f"/disbursements/{disbursement_id}/clear", payload or {}, headers)

    def fail_disbursement(self, disbursement_id, payload, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/fail", payload, headers)

    def retry_disbursement(self, disbursement_id, headers, payload=None):
        return self._request("POST", f"/disbursements/{disbursement_id}/retry", payload or {}, headers)

    # ---- Recertification ----
    def create_recertification(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/recertifications", payload, headers)

    def list_recertifications(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/recertifications", headers=headers, params=params)

    def decide_recertification(self, recertification_id, payload, headers):
        return self._request("POST", f"/recertifications/{recertification_id}/decide", payload, headers)

    # ---- RecaptureCase ----
    def create_recapture_case(self, payload, headers):
        return self._request("POST", "/recapture-cases", payload, headers)

    def get_recapture_case(self, recapture_case_id, headers):
        return self._request("GET", f"/recapture-cases/{recapture_case_id}", headers=headers)

    def list_recapture_cases(self, headers, params=None):
        return self._request("GET", "/recapture-cases", headers=headers, params=params)

    def substantiate_recapture(self, recapture_case_id, payload, headers):
        return self._request("POST", f"/recapture-cases/{recapture_case_id}/substantiate", payload, headers)

    def recover_recapture(self, recapture_case_id, headers, payload=None):
        return self._request("POST", f"/recapture-cases/{recapture_case_id}/recover", payload or {}, headers)

    def dismiss_recapture(self, recapture_case_id, payload, headers):
        return self._request("POST", f"/recapture-cases/{recapture_case_id}/dismiss", payload, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
