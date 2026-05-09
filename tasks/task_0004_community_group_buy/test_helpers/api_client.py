"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Test-driving infrastructure ---
    def advance_clock(self, by_periods, headers):
        return self._request("POST", "/_clock/advance", {"by_periods": by_periods}, headers)

    def run_payouts_sweep(self, headers):
        return self._request("POST", "/_sweep/run-payouts", {}, headers)

    def auto_close_campaigns_sweep(self, headers):
        return self._request("POST", "/_sweep/auto-close-campaigns", {}, headers)

    def recompute_risk_sweep(self, headers):
        return self._request("POST", "/_sweep/recompute-risk", {}, headers)

    # --- Communities ---
    def create_community(self, payload, headers):
        return self._request("POST", "/communities", payload, headers)

    def list_communities(self, headers, params=None):
        return self._request("GET", "/communities", headers=headers, params=params)

    # --- Group Leaders ---
    def create_group_leader(self, community_id, payload, headers):
        return self._request("POST", f"/communities/{community_id}/group-leaders", payload, headers)

    def get_group_leader(self, leader_id, headers):
        return self._request("GET", f"/group-leaders/{leader_id}", headers=headers)

    def approve_leader(self, leader_id, headers):
        return self._request("POST", f"/group-leaders/{leader_id}/approve", {}, headers)

    def suspend_leader(self, leader_id, headers):
        return self._request("POST", f"/group-leaders/{leader_id}/suspend", {}, headers)

    def reinstate_leader(self, leader_id, headers):
        return self._request("POST", f"/group-leaders/{leader_id}/reinstate", {}, headers)

    def deactivate_leader(self, leader_id, headers):
        return self._request("POST", f"/group-leaders/{leader_id}/deactivate", {}, headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # --- Suppliers / Warehouses ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/suppliers", payload, headers)

    def create_warehouse(self, supplier_id, payload, headers):
        return self._request("POST", f"/suppliers/{supplier_id}/warehouses", payload, headers)

    def list_warehouses(self, supplier_id, headers, params=None):
        return self._request("GET", f"/suppliers/{supplier_id}/warehouses", headers=headers, params=params)

    # --- Flash Campaigns ---
    def create_flash_campaign(self, supplier_id, payload, headers):
        return self._request("POST", f"/suppliers/{supplier_id}/flash-campaigns", payload, headers)

    def get_flash_campaign(self, flash_campaign_id, headers):
        return self._request("GET", f"/flash-campaigns/{flash_campaign_id}", headers=headers)

    def flash_purchase(self, flash_campaign_id, payload, headers):
        return self._request("POST", f"/flash-campaigns/{flash_campaign_id}/purchase", payload, headers)

    # --- Group-Buy Campaigns ---
    def create_group_buy_campaign(self, leader_id, payload, headers):
        return self._request("POST", f"/group-leaders/{leader_id}/group-buy-campaigns", payload, headers)

    def join_group_buy(self, campaign_id, payload, headers):
        return self._request("POST", f"/group-buy-campaigns/{campaign_id}/orders", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pay", {}, headers)

    def extend_campaign(self, campaign_id, headers):
        return self._request("POST", f"/group-buy-campaigns/{campaign_id}/extend", {}, headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"/group-buy-campaigns/{campaign_id}/close", {}, headers)

    def finalize_campaign(self, campaign_id, headers):
        return self._request("POST", f"/group-buy-campaigns/{campaign_id}/finalize", {}, headers)

    def get_group_buy_campaign(self, campaign_id, headers):
        return self._request("GET", f"/group-buy-campaigns/{campaign_id}", headers=headers)

    # --- Orders / Shipments / Pickup ---
    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def plan_shipments(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/plan-shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/dispatch", {}, headers)

    def arrive_at_pickup(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/arrive-at-pickup", {}, headers)

    def report_mispick(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/report-mispick", {}, headers)

    def reconcile_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/reconcile", {}, headers)

    def pickup_confirm(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pickup-confirm", {}, headers)

    # --- Pickup Points ---
    def create_pickup_point(self, community_id, payload, headers):
        return self._request("POST", f"/communities/{community_id}/pickup-points", payload, headers)

    def get_pickup_point_summary(self, pickup_point_id, headers):
        return self._request("GET", f"/pickup-points/{pickup_point_id}/summary", headers=headers)

    def create_consolidation_batch(self, pickup_point_id, payload, headers):
        return self._request("POST", f"/pickup-points/{pickup_point_id}/consolidation-batches", payload, headers)

    # --- After-Sales ---
    def get_after_sales_case(self, case_id, headers):
        return self._request("GET", f"/after-sales/{case_id}", headers=headers)

    def file_after_sales(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/after-sales-cases", payload, headers)

    def start_review(self, case_id, headers):
        return self._request("POST", f"/after-sales/{case_id}/start-review", {}, headers)

    def request_evidence(self, case_id, headers):
        return self._request("POST", f"/after-sales/{case_id}/request-evidence", {}, headers)

    def submit_evidence(self, case_id, headers):
        return self._request("POST", f"/after-sales/{case_id}/submit-evidence", {}, headers)

    def escalate_case(self, case_id, headers):
        return self._request("POST", f"/after-sales/{case_id}/escalate", {}, headers)

    def resolve_case(self, case_id, payload, headers):
        return self._request("POST", f"/after-sales/{case_id}/resolve", payload, headers)

    # --- Commission / Payouts ---
    def list_commission_entries(self, leader_id, headers, params=None):
        return self._request("GET", f"/group-leaders/{leader_id}/commission-entries",
                             headers=headers, params=params)

    def create_payout(self, leader_id, payload, headers):
        return self._request("POST", f"/group-leaders/{leader_id}/payouts", payload, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def release_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/release", {}, headers)

    def cancel_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/cancel", {}, headers)

    # --- Risk Alerts ---
    def create_risk_alert(self, payload, headers):
        return self._request("POST", "/risk-alerts", payload, headers)

    def confirm_alert(self, alert_id, headers):
        return self._request("POST", f"/risk-alerts/{alert_id}/confirm", {}, headers)

    def dismiss_alert(self, alert_id, headers):
        return self._request("POST", f"/risk-alerts/{alert_id}/dismiss", {}, headers)


api_client = ApiClient()
