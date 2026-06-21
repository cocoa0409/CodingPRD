"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Property ─────────────────────────────────────────────────────────
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def list_property_leases(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/leases", headers=headers, params=params)

    def list_property_expense_pools(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/expense-pools", headers=headers, params=params)

    # ─── Tenant ───────────────────────────────────────────────────────────
    def create_tenant(self, payload, headers):
        return self._request("POST", "/tenants", payload, headers)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    def list_tenant_leases(self, tenant_id, headers, params=None):
        return self._request("GET", f"/tenants/{tenant_id}/leases", headers=headers, params=params)

    # ─── ExpensePool / line items ─────────────────────────────────────────
    def create_expense_pool(self, payload, headers):
        return self._request("POST", "/expense-pools", payload, headers)

    def get_expense_pool(self, pool_id, headers):
        return self._request("GET", f"/expense-pools/{pool_id}", headers=headers)

    def add_line_item(self, pool_id, payload, headers):
        return self._request("POST", f"/expense-pools/{pool_id}/line-items", payload, headers)

    def list_line_items(self, pool_id, headers, params=None):
        return self._request("GET", f"/expense-pools/{pool_id}/line-items", headers=headers, params=params)

    def delete_line_item(self, pool_id, item_id, headers):
        return self._request("DELETE", f"/expense-pools/{pool_id}/line-items/{item_id}", headers=headers)

    # ─── Lease ────────────────────────────────────────────────────────────
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def activate_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/activate", headers=headers)

    def holdover_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/holdover", headers=headers)

    def terminate_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/terminate", headers=headers)

    def escalate_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/escalate", payload, headers)

    def run_percentage_rent(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/percentage-rent-run", payload, headers)

    def list_ledger(self, lease_id, headers, params=None):
        return self._request("GET", f"/leases/{lease_id}/ledger", headers=headers, params=params)

    def create_payment(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/payments", payload, headers)

    # ─── SalesReport ──────────────────────────────────────────────────────
    def create_sales_report(self, payload, headers):
        return self._request("POST", "/sales-reports", payload, headers)

    def get_sales_report(self, sr_id, headers):
        return self._request("GET", f"/sales-reports/{sr_id}", headers=headers)

    def list_sales_reports(self, headers, params=None):
        return self._request("GET", "/sales-reports", headers=headers, params=params)

    # ─── TiDraw ───────────────────────────────────────────────────────────
    def create_ti_draw(self, payload, headers):
        return self._request("POST", "/ti-draws", payload, headers)

    def get_ti_draw(self, draw_id, headers):
        return self._request("GET", f"/ti-draws/{draw_id}", headers=headers)

    def list_ti_draws(self, headers, params=None):
        return self._request("GET", "/ti-draws", headers=headers, params=params)

    def approve_ti_draw(self, draw_id, headers):
        return self._request("POST", f"/ti-draws/{draw_id}/approve", headers=headers)

    def reject_ti_draw(self, draw_id, headers):
        return self._request("POST", f"/ti-draws/{draw_id}/reject", headers=headers)

    # ─── Reconciliation ───────────────────────────────────────────────────
    def create_reconciliation(self, payload, headers):
        return self._request("POST", "/reconciliations", payload, headers)

    def get_reconciliation(self, recon_id, headers):
        return self._request("GET", f"/reconciliations/{recon_id}", headers=headers)

    def list_reconciliations(self, headers, params=None):
        return self._request("GET", "/reconciliations", headers=headers, params=params)

    def preview_reconciliation(self, recon_id, headers):
        return self._request("GET", f"/reconciliations/{recon_id}/preview", headers=headers)

    def submit_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/reconciliations/{recon_id}/submit", headers=headers)

    def return_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/reconciliations/{recon_id}/return", headers=headers)

    def post_reconciliation(self, recon_id, payload, headers):
        return self._request("POST", f"/reconciliations/{recon_id}/post", payload, headers)

    def dispute_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/reconciliations/{recon_id}/dispute", headers=headers)

    def resolve_dispute(self, recon_id, headers):
        return self._request("POST", f"/reconciliations/{recon_id}/resolve-dispute", headers=headers)

    def void_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/reconciliations/{recon_id}/void", headers=headers)

    def list_reconciliation_ledger_entries(self, recon_id, headers, params=None):
        return self._request("GET", f"/reconciliations/{recon_id}/ledger-entries", headers=headers, params=params)

    # ─── Estoppel ─────────────────────────────────────────────────────────
    def create_estoppel(self, payload, headers):
        return self._request("POST", "/estoppels", payload, headers)

    def get_estoppel(self, est_id, headers):
        return self._request("GET", f"/estoppels/{est_id}", headers=headers)

    def list_estoppels(self, headers, params=None):
        return self._request("GET", "/estoppels", headers=headers, params=params)

    def respond_estoppel(self, est_id, payload, headers):
        return self._request("POST", f"/estoppels/{est_id}/respond", payload, headers)


api_client = ApiClient()
