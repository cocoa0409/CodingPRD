"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    # ---- Engagement ----
    def list_engagements(self, headers, params=None):
        return self._request("GET", "/engagements", headers=headers, params=params)

    def create_engagement(self, payload, headers):
        return self._request("POST", "/engagements", payload, headers)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/engagements/{engagement_id}", headers=headers)

    def get_volume_actuals(self, engagement_id, headers):
        return self._request("GET", f"/engagements/{engagement_id}/volume-actuals", headers=headers)

    def start_scoping(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/start-scoping", {}, headers)

    def advance_to_reconciliation(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/advance-to-reconciliation", {}, headers)

    def quote(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/quote", {}, headers)

    def complete_engagement(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/complete", {}, headers)

    def cancel_engagement(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/cancel", {}, headers)

    def get_completion_report(self, engagement_id, headers):
        return self._request("GET", f"/engagements/{engagement_id}/completion-report", headers=headers)

    # ---- ScopeEstimate ----
    def create_scope_estimate(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/scope-estimates", payload, headers)

    def list_scope_estimates(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/scope-estimates", headers=headers, params=params)

    def accept_scope_estimate(self, engagement_id, estimate_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/scope-estimates/{estimate_id}/accept", payload, headers)

    # ---- LedgerAccount ----
    def create_account(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/accounts", payload, headers)

    def list_accounts(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def categorize_account(self, engagement_id, account_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/accounts/{account_id}/categorize", {}, headers)

    def mark_reconciled(self, engagement_id, account_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/accounts/{account_id}/mark-reconciled", {}, headers)

    def exclude_account(self, engagement_id, account_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/accounts/{account_id}/exclude", {}, headers)

    # ---- LedgerEntry ----
    def create_entry(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/entries", payload, headers)

    def list_entries(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/entries", headers=headers, params=params)

    def post_entry(self, engagement_id, entry_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/entries/{entry_id}/post", {}, headers)

    def reverse_entry(self, engagement_id, entry_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/entries/{entry_id}/reverse", {}, headers)

    # ---- BankStatement ----
    def create_statement(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/statements", payload, headers)

    def list_statements(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/statements", headers=headers, params=params)

    def finalize_statement(self, engagement_id, statement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/statements/{statement_id}/finalize", {}, headers)

    # ---- ReconciliationItem ----
    def create_reconciliation_item(self, engagement_id, statement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/statements/{statement_id}/reconciliation-items", payload, headers)

    def list_reconciliation_items(self, engagement_id, statement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/statements/{statement_id}/reconciliation-items", headers=headers, params=params)

    def list_reconciliation_items_global(self, headers, params=None):
        return self._request("GET", "/reconciliation-items", headers=headers, params=params)

    # ---- Phase / billing ----
    def create_phase(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/phases", payload, headers)

    def list_phases(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/phases", headers=headers, params=params)

    def generate_phases(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/phases/generate", {}, headers)

    def invoice_phase(self, engagement_id, phase_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/phases/{phase_id}/invoice", {}, headers)

    def pay_invoice(self, engagement_id, invoice_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/invoices/{invoice_id}/pay", {}, headers)

    def list_invoices(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/invoices", headers=headers, params=params)

    # ---- TaxPackage ----
    def build_tax_package(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/tax-packages", {}, headers)

    def list_tax_packages(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/tax-packages", headers=headers, params=params)

    def handoff_tax_package(self, engagement_id, tax_package_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/tax-packages/{tax_package_id}/handoff", {}, headers)

    def amend_tax_package(self, engagement_id, tax_package_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/tax-packages/{tax_package_id}/amend", {}, headers)

    # ---- ServicePlan ----
    def create_service_plan(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/service-plans", payload, headers)

    def list_service_plans(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/service-plans", headers=headers, params=params)

    def activate_service_plan(self, engagement_id, service_plan_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/service-plans/{service_plan_id}/activate", {}, headers)

    def cancel_service_plan(self, engagement_id, service_plan_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/service-plans/{service_plan_id}/cancel", {}, headers)

    # ---- Exception ----
    def create_exception(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/exceptions", payload, headers)

    def list_exceptions(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/exceptions", headers=headers, params=params)

    def request_docs(self, engagement_id, exception_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/exceptions/{exception_id}/request-docs", {}, headers)

    def docs_received(self, engagement_id, exception_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/exceptions/{exception_id}/docs-received", {}, headers)

    def resolve_exception(self, engagement_id, exception_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/exceptions/{exception_id}/resolve", {}, headers)

    def waive_exception(self, engagement_id, exception_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/exceptions/{exception_id}/waive", {}, headers)


api_client = ApiClient()
