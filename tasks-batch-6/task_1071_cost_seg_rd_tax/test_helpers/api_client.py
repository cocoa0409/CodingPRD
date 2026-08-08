"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def activate_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/activate", {}, headers)

    # ---- Property ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    # ---- Engineer ----
    def create_engineer(self, payload, headers):
        return self._request("POST", "/engineers", payload, headers)

    def get_engineer(self, engineer_id, headers):
        return self._request("GET", f"/engineers/{engineer_id}", headers=headers)

    # ---- Study ----
    def create_study(self, payload, headers):
        return self._request("POST", "/studies", payload, headers)

    def get_study(self, study_id, headers):
        return self._request("GET", f"/studies/{study_id}", headers=headers)

    def list_studies(self, headers, params=None):
        return self._request("GET", "/studies", headers=headers, params=params)

    def scope_study(self, study_id, payload, headers):
        return self._request("POST", f"/studies/{study_id}/scope", payload, headers)

    def assign_engineer(self, study_id, payload, headers):
        return self._request("POST", f"/studies/{study_id}/assign-engineer", payload, headers)

    def submit_review(self, study_id, headers):
        return self._request("POST", f"/studies/{study_id}/submit-review", {}, headers)

    def reject_study(self, study_id, headers, payload=None):
        return self._request("POST", f"/studies/{study_id}/reject", payload or {}, headers)

    def finalize_study(self, study_id, headers):
        return self._request("POST", f"/studies/{study_id}/finalize", {}, headers)

    def deliver_study(self, study_id, headers):
        return self._request("POST", f"/studies/{study_id}/deliver", {}, headers)

    def cancel_study(self, study_id, headers):
        return self._request("POST", f"/studies/{study_id}/cancel", {}, headers)

    # ---- AssetComponent ----
    def add_asset_component(self, study_id, payload, headers):
        return self._request("POST", f"/studies/{study_id}/asset-components", payload, headers)

    def list_asset_components(self, study_id, headers, params=None):
        return self._request("GET", f"/studies/{study_id}/asset-components", headers=headers, params=params)

    def allocate_component(self, component_id, headers):
        return self._request("POST", f"/asset-components/{component_id}/allocate", {}, headers)

    def exclude_component(self, component_id, headers):
        return self._request("POST", f"/asset-components/{component_id}/exclude", {}, headers)

    # ---- QreLineItem ----
    def add_qre_line_item(self, study_id, payload, headers):
        return self._request("POST", f"/studies/{study_id}/qre-line-items", payload, headers)

    def list_qre_line_items(self, study_id, headers, params=None):
        return self._request("GET", f"/studies/{study_id}/qre-line-items", headers=headers, params=params)

    def qualify_qre(self, qre_id, headers):
        return self._request("POST", f"/qre-line-items/{qre_id}/qualify", {}, headers)

    # ---- Report ----
    def list_reports(self, study_id, headers, params=None):
        return self._request("GET", f"/studies/{study_id}/reports", headers=headers, params=params)

    # ---- AuditSupportCase ----
    def create_audit_case(self, study_id, payload, headers):
        return self._request("POST", f"/studies/{study_id}/audit-cases", payload, headers)

    def list_audit_cases(self, study_id, headers, params=None):
        return self._request("GET", f"/studies/{study_id}/audit-cases", headers=headers, params=params)

    def resolve_audit_case(self, case_id, payload, headers):
        return self._request("POST", f"/audit-cases/{case_id}/resolve", payload, headers)

    # ---- AmendedReturn ----
    def create_amended_return(self, study_id, payload, headers):
        return self._request("POST", f"/studies/{study_id}/amended-returns", payload, headers)

    def list_amended_returns(self, study_id, headers, params=None):
        return self._request("GET", f"/studies/{study_id}/amended-returns", headers=headers, params=params)

    def file_amended_return(self, amended_id, headers):
        return self._request("POST", f"/amended-returns/{amended_id}/file", {}, headers)

    # ---- FeeInvoice ----
    def list_fee_invoices(self, study_id, headers, params=None):
        return self._request("GET", f"/studies/{study_id}/fee-invoices", headers=headers, params=params)

    def pay_fee_invoice(self, invoice_id, headers):
        return self._request("POST", f"/fee-invoices/{invoice_id}/pay", {}, headers)

    def void_fee_invoice(self, invoice_id, headers):
        return self._request("POST", f"/fee-invoices/{invoice_id}/void", {}, headers)


api_client = ApiClient()
