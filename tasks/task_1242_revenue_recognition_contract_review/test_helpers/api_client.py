"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving capability, PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/revrec/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/revrec/customers/{customer_id}", headers=headers)

    # --- Contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/revrec/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/revrec/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/revrec/contracts", headers=headers, params=params)

    def submit_contract(self, contract_id, headers, payload=None):
        return self._request("POST", f"/revrec/contracts/{contract_id}/submit", payload or {}, headers)

    def return_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/revrec/contracts/{contract_id}/return", payload, headers)

    def approve_contract(self, contract_id, headers):
        return self._request("POST", f"/revrec/contracts/{contract_id}/approve", {}, headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/revrec/contracts/{contract_id}/activate", {}, headers)

    def hold_contract(self, contract_id, headers):
        return self._request("POST", f"/revrec/contracts/{contract_id}/hold", {}, headers)

    def resume_contract(self, contract_id, headers):
        return self._request("POST", f"/revrec/contracts/{contract_id}/resume", {}, headers)

    def cancel_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/revrec/contracts/{contract_id}/cancel", payload, headers)

    def absorb_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/revrec/contracts/{contract_id}/absorb", payload, headers)

    def get_rollforward(self, contract_id, headers, params=None):
        return self._request("GET", f"/revrec/contracts/{contract_id}/rollforward", headers=headers, params=params)

    # --- Performance obligations ---
    def create_pob(self, contract_id, payload, headers):
        return self._request("POST", f"/revrec/contracts/{contract_id}/pobs", payload, headers)

    def list_pobs(self, contract_id, headers, params=None):
        return self._request("GET", f"/revrec/contracts/{contract_id}/pobs", headers=headers, params=params)

    def get_pob(self, pob_id, headers):
        return self._request("GET", f"/revrec/pobs/{pob_id}", headers=headers)

    def satisfy_pob(self, pob_id, headers):
        return self._request("POST", f"/revrec/pobs/{pob_id}/satisfy", {}, headers)

    def recognize_pob(self, pob_id, headers):
        return self._request("POST", f"/revrec/pobs/{pob_id}/recognize", {}, headers)

    # --- Cost entries ---
    def create_cost_entry(self, pob_id, payload, headers):
        return self._request("POST", f"/revrec/pobs/{pob_id}/cost-entries", payload, headers)

    def list_cost_entries(self, pob_id, headers, params=None):
        return self._request("GET", f"/revrec/pobs/{pob_id}/cost-entries", headers=headers, params=params)

    # --- Variable consideration estimates ---
    def create_vc_estimate(self, contract_id, payload, headers):
        return self._request("POST", f"/revrec/contracts/{contract_id}/vc-estimates", payload, headers)

    def list_vc_estimates(self, contract_id, headers, params=None):
        return self._request("GET", f"/revrec/contracts/{contract_id}/vc-estimates", headers=headers, params=params)

    def approve_vc_estimate(self, estimate_id, headers):
        return self._request("POST", f"/revrec/vc-estimates/{estimate_id}/approve", {}, headers)

    def reject_vc_estimate(self, estimate_id, headers):
        return self._request("POST", f"/revrec/vc-estimates/{estimate_id}/reject", {}, headers)

    # --- Contract modifications ---
    def create_modification(self, contract_id, payload, headers):
        return self._request("POST", f"/revrec/contracts/{contract_id}/modifications", payload, headers)

    def list_modifications(self, contract_id, headers, params=None):
        return self._request("GET", f"/revrec/contracts/{contract_id}/modifications", headers=headers, params=params)

    def approve_modification(self, modification_id, headers):
        return self._request("POST", f"/revrec/modifications/{modification_id}/approve", {}, headers)

    def reject_modification(self, modification_id, headers):
        return self._request("POST", f"/revrec/modifications/{modification_id}/reject", {}, headers)

    # --- Contract clauses ---
    def create_clause(self, contract_id, payload, headers):
        return self._request("POST", f"/revrec/contracts/{contract_id}/clauses", payload, headers)

    def list_clauses(self, contract_id, headers, params=None):
        return self._request("GET", f"/revrec/contracts/{contract_id}/clauses", headers=headers, params=params)

    # --- Review tasks ---
    def list_review_tasks(self, headers, params=None):
        return self._request("GET", "/revrec/review-tasks", headers=headers, params=params)

    def get_review_task(self, task_id, headers):
        return self._request("GET", f"/revrec/review-tasks/{task_id}", headers=headers)

    def start_review_task(self, task_id, headers):
        return self._request("POST", f"/revrec/review-tasks/{task_id}/start", {}, headers)

    def recommend_review_task(self, task_id, payload, headers):
        return self._request("POST", f"/revrec/review-tasks/{task_id}/recommend", payload, headers)

    def decide_review_task(self, task_id, payload, headers):
        return self._request("POST", f"/revrec/review-tasks/{task_id}/decide", payload, headers)

    # --- Invoices ---
    def create_invoice(self, contract_id, payload, headers):
        return self._request("POST", f"/revrec/contracts/{contract_id}/invoices", payload, headers)

    def list_invoices(self, contract_id, headers, params=None):
        return self._request("GET", f"/revrec/contracts/{contract_id}/invoices", headers=headers, params=params)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/revrec/invoices/{invoice_id}/void", {}, headers)

    # --- Accounting periods ---
    def create_accounting_period(self, payload, headers):
        return self._request("POST", "/revrec/accounting-periods", payload, headers)

    def get_accounting_period(self, period_id, headers):
        return self._request("GET", f"/revrec/accounting-periods/{period_id}", headers=headers)

    def close_accounting_period(self, period_id, headers):
        return self._request("POST", f"/revrec/accounting-periods/{period_id}/close", {}, headers)

    def reopen_accounting_period(self, period_id, headers):
        return self._request("POST", f"/revrec/accounting-periods/{period_id}/reopen", {}, headers)

    # --- Revenue entries ---
    def get_revenue_entry(self, entry_id, headers):
        return self._request("GET", f"/revrec/revenue-entries/{entry_id}", headers=headers)

    def list_revenue_entries(self, headers, params=None):
        return self._request("GET", "/revrec/revenue-entries", headers=headers, params=params)

    def reverse_revenue_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/revrec/revenue-entries/{entry_id}/reverse", payload, headers)

    # --- Disclosure packs ---
    def create_disclosure_pack(self, period_id, headers):
        return self._request("POST", f"/revrec/accounting-periods/{period_id}/disclosure-packs", {}, headers)

    def list_disclosure_packs(self, period_id, headers, params=None):
        return self._request("GET", f"/revrec/accounting-periods/{period_id}/disclosure-packs", headers=headers, params=params)

    def assemble_disclosure_pack(self, pack_id, headers):
        return self._request("POST", f"/revrec/disclosure-packs/{pack_id}/assemble", {}, headers)

    def finalize_disclosure_pack(self, pack_id, headers):
        return self._request("POST", f"/revrec/disclosure-packs/{pack_id}/finalize", {}, headers)

    # --- Standalone selling prices ---
    def create_ssp_price(self, payload, headers):
        return self._request("POST", "/revrec/ssp-prices", payload, headers)

    def retire_ssp_price(self, ssp_id, headers):
        return self._request("POST", f"/revrec/ssp-prices/{ssp_id}/retire", {}, headers)


api_client = ApiClient()
