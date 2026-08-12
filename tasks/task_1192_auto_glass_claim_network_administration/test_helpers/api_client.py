"""API client: one method per endpoint defined in the PRD §4 endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Policyholder ---
    def create_policyholder(self, payload, headers):
        return self._request("POST", "/policyholders", payload, headers)

    def get_policyholder(self, policyholder_id, headers):
        return self._request("GET", f"/policyholders/{policyholder_id}", headers=headers)

    # --- StateRegulation ---
    def create_state_regulation(self, payload, headers):
        return self._request("POST", "/state-regulations", payload, headers)

    def list_state_regulations(self, headers, params=None):
        return self._request("GET", "/state-regulations", headers=headers, params=params)

    # --- Policy ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    # --- GlassShop ---
    def create_glass_shop(self, payload, headers):
        return self._request("POST", "/glass-shops", payload, headers)

    def get_glass_shop(self, shop_id, headers):
        return self._request("GET", f"/glass-shops/{shop_id}", headers=headers)

    def update_glass_shop(self, shop_id, payload, headers):
        return self._request("PATCH", f"/glass-shops/{shop_id}", payload, headers)

    def list_shop_work_orders(self, shop_id, headers, params=None):
        return self._request("GET", f"/glass-shops/{shop_id}/work-orders", headers=headers, params=params)

    def get_shop_capacity(self, shop_id, date, headers):
        return self._request("GET", f"/glass-shops/{shop_id}/capacity", headers=headers, params={"date": date})

    # --- PartCatalogEntry ---
    def create_part_catalog_entry(self, payload, headers):
        return self._request("POST", "/part-catalog-entries", payload, headers)

    def get_part_catalog_entry(self, entry_id, headers):
        return self._request("GET", f"/part-catalog-entries/{entry_id}", headers=headers)

    def list_part_catalog_entries(self, headers, params=None):
        return self._request("GET", "/part-catalog-entries", headers=headers, params=params)

    def update_part_catalog_entry(self, entry_id, payload, headers):
        return self._request("PATCH", f"/part-catalog-entries/{entry_id}", payload, headers)

    def list_part_line_items(self, entry_id, headers, params=None):
        return self._request("GET", f"/part-catalog-entries/{entry_id}/line-items", headers=headers, params=params)

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def verify_coverage(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/verify-coverage", payload, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    def cancel_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/cancel", payload, headers)

    def supplement_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/supplement", payload, headers)

    def create_choice_disclosure(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/choice-disclosures", payload, headers)

    def list_choice_disclosures(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/choice-disclosures", headers=headers, params=params)

    def create_routing_decision(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/routing-decisions", payload, headers)

    # --- WorkOrder ---
    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_claim_work_orders(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/work-orders", headers=headers, params=params)

    def accept_work_order(self, work_order_id, headers, payload=None):
        return self._request("POST", f"/work-orders/{work_order_id}/accept", payload or {}, headers)

    def decline_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/decline", payload, headers)

    def schedule_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/schedule", payload, headers)

    def mark_no_show(self, work_order_id, headers, payload=None):
        return self._request("POST", f"/work-orders/{work_order_id}/mark-no-show", payload or {}, headers)

    def complete_work_order(self, work_order_id, headers, payload=None):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", payload or {}, headers)

    def cancel_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", payload, headers)

    # --- CalibrationEvent ---
    def create_calibration_event(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/calibration-events", payload, headers)

    def list_calibration_events(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/calibration-events", headers=headers, params=params)

    def verify_calibration_event(self, event_id, payload, headers):
        return self._request("POST", f"/calibration-events/{event_id}/verify", payload, headers)

    # --- Invoice ---
    def create_invoice(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_work_order_invoices(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/invoices", headers=headers, params=params)

    def list_invoice_line_items(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/line-items", headers=headers, params=params)

    def submit_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/submit", payload, headers)

    def create_audit_decision(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/audit-decisions", payload, headers)

    def pay_invoice(self, invoice_id, headers, payload=None):
        return self._request("POST", f"/invoices/{invoice_id}/pay", payload or {}, headers)

    # --- FraudAlert ---
    def get_fraud_alert(self, alert_id, headers):
        return self._request("GET", f"/fraud-alerts/{alert_id}", headers=headers)

    def list_fraud_alerts(self, headers, params=None):
        return self._request("GET", "/fraud-alerts", headers=headers, params=params)

    def resolve_fraud_alert(self, alert_id, payload, headers):
        return self._request("POST", f"/fraud-alerts/{alert_id}/resolve", payload, headers)

    # --- WarrantyClaim ---
    def create_warranty_claim(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/warranty-claims", payload, headers)

    def list_work_order_warranty_claims(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, warranty_claim_id, headers):
        return self._request("GET", f"/warranty-claims/{warranty_claim_id}", headers=headers)

    def list_warranty_work_orders(self, warranty_claim_id, headers, params=None):
        return self._request("GET", f"/warranty-claims/{warranty_claim_id}/work-orders", headers=headers, params=params)

    def decide_warranty_claim(self, warranty_claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{warranty_claim_id}/decide", payload, headers)

    # --- Test-driving logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
