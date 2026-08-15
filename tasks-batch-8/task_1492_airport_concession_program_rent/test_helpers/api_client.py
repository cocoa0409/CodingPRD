"""API client: one method per endpoint defined in the PRD endpoint table (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Tenants ---
    def create_tenant(self, payload, headers):
        return self._request("POST", "/concessions/tenants", payload, headers)

    def list_tenants(self, headers, params=None):
        return self._request("GET", "/concessions/tenants", headers=headers, params=params)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/concessions/tenants/{tenant_id}", headers=headers)

    # --- Leases ---
    def create_lease(self, payload, headers):
        return self._request("POST", "/concessions/leases", payload, headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/concessions/leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/concessions/leases/{lease_id}", headers=headers)

    def patch_lease(self, lease_id, payload, headers):
        return self._request("PATCH", f"/concessions/leases/{lease_id}", payload, headers)

    def transition_lease(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/concessions/leases/{lease_id}/transition", payload, headers
        )

    def get_lease_performance(self, lease_id, headers):
        return self._request(
            "GET", f"/concessions/leases/{lease_id}/performance", headers=headers
        )

    # --- Sales reports ---
    def create_sales_report(self, payload, headers):
        return self._request("POST", "/concessions/sales-reports", payload, headers)

    def list_sales_reports(self, headers, params=None):
        return self._request(
            "GET", "/concessions/sales-reports", headers=headers, params=params
        )

    def get_sales_report(self, report_id, headers):
        return self._request(
            "GET", f"/concessions/sales-reports/{report_id}", headers=headers
        )

    def patch_sales_report(self, report_id, payload, headers):
        return self._request(
            "PATCH", f"/concessions/sales-reports/{report_id}", payload, headers
        )

    def transition_sales_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/concessions/sales-reports/{report_id}/transition", payload, headers
        )

    # --- Rent settlements ---
    def create_settlement(self, payload, headers):
        return self._request("POST", "/concessions/settlements", payload, headers)

    def list_settlements(self, headers, params=None):
        return self._request(
            "GET", "/concessions/settlements", headers=headers, params=params
        )

    def get_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"/concessions/settlements/{settlement_id}", headers=headers
        )

    def recalculate_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/concessions/settlements/{settlement_id}/recalculate", {}, headers
        )

    def invoice_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/concessions/settlements/{settlement_id}/invoice", {}, headers
        )

    def create_payment(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/concessions/settlements/{settlement_id}/payments", payload, headers
        )

    def list_payments(self, settlement_id, headers, params=None):
        return self._request(
            "GET",
            f"/concessions/settlements/{settlement_id}/payments",
            headers=headers,
            params=params,
        )

    def void_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/concessions/payments/{payment_id}/void", {}, headers
        )

    # --- Audit cases ---
    def create_audit(self, payload, headers):
        return self._request("POST", "/concessions/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/concessions/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/concessions/audits/{audit_id}", headers=headers)

    def issue_findings(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/concessions/audits/{audit_id}/issue-findings", payload, headers
        )

    def close_audit(self, audit_id, headers):
        return self._request(
            "POST", f"/concessions/audits/{audit_id}/close", {}, headers
        )

    # --- ACDBE reviews ---
    def create_acdbe_review(self, payload, headers):
        return self._request("POST", "/concessions/acdbe-reviews", payload, headers)

    def list_acdbe_reviews(self, headers, params=None):
        return self._request(
            "GET", "/concessions/acdbe-reviews", headers=headers, params=params
        )

    def get_acdbe_review(self, review_id, headers):
        return self._request(
            "GET", f"/concessions/acdbe-reviews/{review_id}", headers=headers
        )

    def evaluate_acdbe_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/concessions/acdbe-reviews/{review_id}/evaluate", payload, headers
        )

    def cure_acdbe_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/concessions/acdbe-reviews/{review_id}/cure", payload, headers
        )

    # --- TI draws ---
    def create_ti_draw(self, payload, headers):
        return self._request("POST", "/concessions/ti-draws", payload, headers)

    def list_ti_draws(self, headers, params=None):
        return self._request("GET", "/concessions/ti-draws", headers=headers, params=params)

    def get_ti_draw(self, draw_id, headers):
        return self._request("GET", f"/concessions/ti-draws/{draw_id}", headers=headers)

    def transition_ti_draw(self, draw_id, payload, headers):
        return self._request(
            "POST", f"/concessions/ti-draws/{draw_id}/transition", payload, headers
        )

    # --- Policy violations ---
    def create_violation(self, payload, headers):
        return self._request("POST", "/concessions/violations", payload, headers)

    def list_violations(self, headers, params=None):
        return self._request(
            "GET", "/concessions/violations", headers=headers, params=params
        )

    def get_violation(self, violation_id, headers):
        return self._request(
            "GET", f"/concessions/violations/{violation_id}", headers=headers
        )

    def resolve_violation(self, violation_id, headers):
        return self._request(
            "POST", f"/concessions/violations/{violation_id}/resolve", {}, headers
        )

    # --- Operating-hours waivers ---
    def create_waiver(self, payload, headers):
        return self._request("POST", "/concessions/waivers", payload, headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/concessions/waivers", headers=headers, params=params)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/concessions/waivers/{waiver_id}", headers=headers)

    def transition_waiver(self, waiver_id, payload, headers):
        return self._request(
            "POST", f"/concessions/waivers/{waiver_id}/transition", payload, headers
        )

    # --- Enplanement snapshots ---
    def create_enplanement_snapshot(self, payload, headers):
        return self._request(
            "POST", "/concessions/enplanement-snapshots", payload, headers
        )

    def list_enplanement_snapshots(self, headers, params=None):
        return self._request(
            "GET", "/concessions/enplanement-snapshots", headers=headers, params=params
        )


api_client = ApiClient()
