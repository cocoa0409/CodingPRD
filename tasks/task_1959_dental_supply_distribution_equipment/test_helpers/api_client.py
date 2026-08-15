"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Practices ──────────────────────────────────────────────
    def create_practice(self, payload, headers):
        return self._request("POST", "/api/practices", payload, headers)

    def get_practice(self, practice_id, headers):
        return self._request("GET", f"/api/practices/{practice_id}", headers=headers)

    def suspend_practice(self, practice_id, headers):
        return self._request("POST", f"/api/practices/{practice_id}/suspend", {}, headers)

    def reinstate_practice(self, practice_id, headers):
        return self._request("POST", f"/api/practices/{practice_id}/reinstate", {}, headers)

    # ── Products ───────────────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/api/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/api/products/{product_id}", headers=headers)

    # ── Usage profiles ─────────────────────────────────────────
    def upsert_usage_profile(self, payload, headers):
        return self._request("PUT", "/api/usage-profiles", payload, headers)

    def get_usage_profile(self, profile_id, headers):
        return self._request("GET", f"/api/usage-profiles/{profile_id}", headers=headers)

    def list_usage_profiles(self, headers, params=None):
        return self._request("GET", "/api/usage-profiles", headers=headers, params=params)

    # ── Orders ─────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/api/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/orders", headers=headers, params=params)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/submit", {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/deliver", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/cancel", {}, headers)

    # ── Replenishment sweep ────────────────────────────────────
    def run_replenishment(self, headers):
        return self._request("POST", "/api/_replenishment/run", {}, headers)

    # ── Equipment sales ────────────────────────────────────────
    def create_equipment_sale(self, payload, headers):
        return self._request("POST", "/api/equipment-sales", payload, headers)

    def get_equipment_sale(self, sale_id, headers):
        return self._request("GET", f"/api/equipment-sales/{sale_id}", headers=headers)

    def list_equipment_sales(self, headers, params=None):
        return self._request("GET", "/api/equipment-sales", headers=headers, params=params)

    def confirm_equipment_sale(self, sale_id, headers):
        return self._request("POST", f"/api/equipment-sales/{sale_id}/confirm", {}, headers)

    def schedule_install(self, sale_id, payload, headers):
        return self._request("POST", f"/api/equipment-sales/{sale_id}/schedule-install", payload, headers)

    def complete_install(self, sale_id, headers):
        return self._request("POST", f"/api/equipment-sales/{sale_id}/complete-install", {}, headers)

    def complete_training(self, sale_id, payload, headers):
        return self._request("POST", f"/api/equipment-sales/{sale_id}/complete-training", payload, headers)

    def accept_equipment_sale(self, sale_id, headers):
        return self._request("POST", f"/api/equipment-sales/{sale_id}/accept", {}, headers)

    # ── Technicians ────────────────────────────────────────────
    def create_technician(self, payload, headers):
        return self._request("POST", "/api/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/api/technicians/{technician_id}", headers=headers)

    def load_van_stock(self, technician_id, payload, headers):
        return self._request("PUT", f"/api/technicians/{technician_id}/van-stock", payload, headers)

    # ── Service tickets ────────────────────────────────────────
    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/api/service-tickets", payload, headers)

    def get_service_ticket(self, ticket_id, headers):
        return self._request("GET", f"/api/service-tickets/{ticket_id}", headers=headers)

    def list_service_tickets(self, headers, params=None):
        return self._request("GET", "/api/service-tickets", headers=headers, params=params)

    def assess_coverage(self, ticket_id, headers):
        return self._request("POST", f"/api/service-tickets/{ticket_id}/assess-coverage", {}, headers)

    def approve_estimate(self, ticket_id, headers):
        return self._request("POST", f"/api/service-tickets/{ticket_id}/approve-estimate", {}, headers)

    def dispatch_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/api/service-tickets/{ticket_id}/dispatch", payload, headers)

    def resolve_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/api/service-tickets/{ticket_id}/resolve", payload, headers)

    def reopen_ticket(self, ticket_id, headers):
        return self._request("POST", f"/api/service-tickets/{ticket_id}/reopen", {}, headers)

    def close_ticket(self, ticket_id, headers):
        return self._request("POST", f"/api/service-tickets/{ticket_id}/close", {}, headers)

    # ── Dispatch jobs ──────────────────────────────────────────
    def get_dispatch_job(self, job_id, headers):
        return self._request("GET", f"/api/dispatch-jobs/{job_id}", headers=headers)

    def list_dispatch_jobs(self, headers, params=None):
        return self._request("GET", "/api/dispatch-jobs", headers=headers, params=params)

    # ── Coverage agreements ────────────────────────────────────
    def create_coverage_agreement(self, payload, headers):
        return self._request("POST", "/api/coverage-agreements", payload, headers)

    def get_coverage_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/coverage-agreements/{agreement_id}", headers=headers)

    def list_coverage_agreements(self, headers, params=None):
        return self._request("GET", "/api/coverage-agreements", headers=headers, params=params)

    # ── Promotions ─────────────────────────────────────────────
    def create_promotion(self, payload, headers):
        return self._request("POST", "/api/promotions", payload, headers)

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"/api/promotions/{promotion_id}", headers=headers)

    # ── Rebate claims ──────────────────────────────────────────
    def create_rebate_claim(self, payload, headers):
        return self._request("POST", "/api/rebate-claims", payload, headers)

    def get_rebate_claim(self, claim_id, headers):
        return self._request("GET", f"/api/rebate-claims/{claim_id}", headers=headers)

    def list_rebate_claims(self, headers, params=None):
        return self._request("GET", "/api/rebate-claims", headers=headers, params=params)

    def submit_rebate_claim(self, claim_id, headers):
        return self._request("POST", f"/api/rebate-claims/{claim_id}/submit", {}, headers)

    def revise_rebate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/rebate-claims/{claim_id}/revise", payload, headers)

    def deny_rebate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/rebate-claims/{claim_id}/deny", payload, headers)

    def settle_rebate_claim(self, claim_id, headers):
        return self._request("POST", f"/api/rebate-claims/{claim_id}/settle", {}, headers)

    # ── Trade-ins ──────────────────────────────────────────────
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/api/trade-ins", payload, headers)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/api/trade-ins/{trade_in_id}", headers=headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/api/trade-ins", headers=headers, params=params)

    def appraise_trade_in(self, trade_in_id, payload, headers):
        return self._request("POST", f"/api/trade-ins/{trade_in_id}/appraise", payload, headers)

    def accept_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/api/trade-ins/{trade_in_id}/accept", {}, headers)

    def apply_trade_in_to_sale(self, trade_in_id, payload, headers):
        return self._request("POST", f"/api/trade-ins/{trade_in_id}/apply-to-sale", payload, headers)

    def dispose_trade_in(self, trade_in_id, payload, headers):
        return self._request("POST", f"/api/trade-ins/{trade_in_id}/dispose", payload, headers)

    # ── Logical clock (test-driving) ───────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
