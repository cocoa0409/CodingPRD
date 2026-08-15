"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Vendors & products ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/sam/vendors", payload, headers)

    def create_product(self, payload, headers):
        return self._request("POST", "/sam/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/sam/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/sam/products/{product_id}", headers=headers)

    def patch_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/sam/products/{product_id}", payload, headers)

    # --- Entitlements ---
    def create_entitlement(self, payload, headers):
        return self._request("POST", "/sam/entitlements", payload, headers)

    def list_entitlements(self, product_id, headers, params=None):
        return self._request("GET", f"/sam/products/{product_id}/entitlements",
                             headers=headers, params=params)

    def void_entitlement(self, entitlement_id, headers):
        return self._request("POST", f"/sam/entitlements/{entitlement_id}/void", {}, headers)

    # --- Deployments ---
    def create_deployment(self, payload, headers):
        return self._request("POST", "/sam/deployments", payload, headers)

    def list_deployments(self, product_id, headers, params=None):
        return self._request("GET", f"/sam/products/{product_id}/deployments",
                             headers=headers, params=params)

    def confirm_deployment(self, deployment_id, headers):
        return self._request("POST", f"/sam/deployments/{deployment_id}/confirm", {}, headers)

    def reject_deployment(self, deployment_id, payload, headers):
        return self._request("POST", f"/sam/deployments/{deployment_id}/reject", payload, headers)

    # --- License positions ---
    def list_license_positions(self, product_id, headers):
        return self._request("GET", f"/sam/products/{product_id}/license-positions",
                             headers=headers)

    def recalculate_license_position(self, position_id, headers):
        return self._request("POST", f"/sam/license-positions/{position_id}/recalculate",
                             {}, headers)

    # --- Audit cases ---
    def create_audit_case(self, payload, headers):
        return self._request("POST", "/sam/audit-cases", payload, headers)

    def list_audit_cases(self, headers, params=None):
        return self._request("GET", "/sam/audit-cases", headers=headers, params=params)

    def get_audit_case(self, audit_case_id, headers):
        return self._request("GET", f"/sam/audit-cases/{audit_case_id}", headers=headers)

    def advance_audit_case(self, audit_case_id, payload, headers):
        return self._request("POST", f"/sam/audit-cases/{audit_case_id}/advance", payload, headers)

    def reopen_evidence(self, audit_case_id, headers):
        return self._request("POST", f"/sam/audit-cases/{audit_case_id}/reopen-evidence",
                             {}, headers)

    def withdraw_audit_case(self, audit_case_id, headers):
        return self._request("POST", f"/sam/audit-cases/{audit_case_id}/withdraw", {}, headers)

    # --- Scope items ---
    def create_scope_item(self, payload, headers):
        return self._request("POST", "/sam/audit-scope-items", payload, headers)

    def list_scope_items(self, audit_case_id, headers, params=None):
        return self._request("GET", f"/sam/audit-cases/{audit_case_id}/scope-items",
                             headers=headers, params=params)

    def list_product_scope_items(self, product_id, headers, params=None):
        return self._request("GET", f"/sam/products/{product_id}/audit-scope-items",
                             headers=headers, params=params)

    def confirm_scope_item(self, scope_item_id, headers):
        return self._request("POST", f"/sam/audit-scope-items/{scope_item_id}/confirm",
                             {}, headers)

    def dispute_scope_item(self, scope_item_id, payload, headers):
        return self._request("POST", f"/sam/audit-scope-items/{scope_item_id}/dispute",
                             payload, headers)

    def repropose_scope_item(self, scope_item_id, payload, headers):
        return self._request("POST", f"/sam/audit-scope-items/{scope_item_id}/repropose",
                             payload, headers)

    def exclude_scope_item(self, scope_item_id, headers):
        return self._request("POST", f"/sam/audit-scope-items/{scope_item_id}/exclude",
                             {}, headers)

    def record_vendor_finding(self, scope_item_id, headers):
        return self._request("POST", f"/sam/audit-scope-items/{scope_item_id}/vendor-finding",
                             {}, headers)

    # --- Data submissions ---
    def create_data_submission(self, payload, headers):
        return self._request("POST", "/sam/data-submissions", payload, headers)

    def list_data_submissions(self, audit_case_id, headers, params=None):
        return self._request("GET", f"/sam/audit-cases/{audit_case_id}/data-submissions",
                             headers=headers, params=params)

    def submit_for_review(self, submission_id, headers):
        return self._request("POST", f"/sam/data-submissions/{submission_id}/submit-for-review",
                             {}, headers)

    def approve_submission(self, submission_id, headers):
        return self._request("POST", f"/sam/data-submissions/{submission_id}/approve",
                             {}, headers)

    def return_submission(self, submission_id, payload, headers):
        return self._request("POST", f"/sam/data-submissions/{submission_id}/return",
                             payload, headers)

    def release_submission(self, submission_id, payload, headers):
        return self._request("POST", f"/sam/data-submissions/{submission_id}/release",
                             payload, headers)

    # --- Settlement offers ---
    def create_settlement_offer(self, payload, headers):
        return self._request("POST", "/sam/settlement-offers", payload, headers)

    def list_settlement_offers(self, headers, params=None):
        return self._request("GET", "/sam/settlement-offers", headers=headers, params=params)

    def get_settlement_offer(self, offer_id, headers):
        return self._request("GET", f"/sam/settlement-offers/{offer_id}", headers=headers)

    def accept_offer(self, offer_id, headers):
        return self._request("POST", f"/sam/settlement-offers/{offer_id}/accept", {}, headers)

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/sam/settlement-offers/{offer_id}/withdraw", {}, headers)

    # --- Remediation actions ---
    def create_remediation_action(self, payload, headers):
        return self._request("POST", "/sam/remediation-actions", payload, headers)

    def get_remediation_action(self, action_id, headers):
        return self._request("GET", f"/sam/remediation-actions/{action_id}", headers=headers)

    def list_remediation_actions(self, product_id, headers, params=None):
        return self._request("GET", f"/sam/products/{product_id}/remediation-actions",
                             headers=headers, params=params)

    def list_remediation_deployments(self, action_id, headers, params=None):
        return self._request("GET", f"/sam/remediation-actions/{action_id}/deployments",
                             headers=headers, params=params)

    def start_remediation(self, action_id, headers):
        return self._request("POST", f"/sam/remediation-actions/{action_id}/start", {}, headers)

    def complete_remediation(self, action_id, headers):
        return self._request("POST", f"/sam/remediation-actions/{action_id}/complete", {}, headers)

    def cancel_remediation(self, action_id, headers):
        return self._request("POST", f"/sam/remediation-actions/{action_id}/cancel", {}, headers)

    def fail_verification(self, action_id, payload, headers):
        return self._request("POST", f"/sam/remediation-actions/{action_id}/fail-verification",
                             payload, headers)

    # --- Monitoring alerts ---
    def list_monitoring_alerts(self, product_id, headers, params=None):
        return self._request("GET", f"/sam/products/{product_id}/monitoring-alerts",
                             headers=headers, params=params)

    def suppress_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/sam/monitoring-alerts/{alert_id}/suppress",
                             payload, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
