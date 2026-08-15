"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Dealership & clock ---
    def create_dealership(self, payload, headers):
        return self._request("POST", "/api/dealerships", payload, headers)

    def list_dealerships(self, headers, params=None):
        return self._request("GET", "/api/dealerships", headers=headers, params=params)

    def get_dealership(self, dealership_id, headers):
        return self._request("GET", f"/api/dealerships/{dealership_id}", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/api/_clock", headers=headers)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/api/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def hold_customer(self, customer_id, headers):
        return self._request("POST", f"/api/customers/{customer_id}/hold", {}, headers)

    def release_customer_hold(self, customer_id, headers):
        return self._request("POST", f"/api/customers/{customer_id}/release_hold", {}, headers)

    def close_customer(self, customer_id, headers):
        return self._request("POST", f"/api/customers/{customer_id}/close", {}, headers)

    # --- PricingContract ---
    def create_pricing_contract(self, payload, headers):
        return self._request("POST", "/api/pricing-contracts", payload, headers)

    def list_pricing_contracts(self, headers, params=None):
        return self._request("GET", "/api/pricing-contracts", headers=headers, params=params)

    def get_pricing_contract(self, contract_id, headers):
        return self._request("GET", f"/api/pricing-contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/api/pricing-contracts/{contract_id}/activate", {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/api/pricing-contracts/{contract_id}/terminate", {}, headers)

    def amend_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/api/pricing-contracts/{contract_id}/amend", payload, headers)

    # --- SpacePlan & Typical ---
    def create_space_plan(self, payload, headers):
        return self._request("POST", "/api/space-plans", payload, headers)

    def list_space_plans(self, headers, params=None):
        return self._request("GET", "/api/space-plans", headers=headers, params=params)

    def get_space_plan(self, plan_id, headers):
        return self._request("GET", f"/api/space-plans/{plan_id}", headers=headers)

    def submit_plan(self, plan_id, headers):
        return self._request("POST", f"/api/space-plans/{plan_id}/submit", {}, headers)

    def approve_plan(self, plan_id, headers):
        return self._request("POST", f"/api/space-plans/{plan_id}/approve", {}, headers)

    def revise_plan(self, plan_id, headers):
        return self._request("POST", f"/api/space-plans/{plan_id}/revise", {}, headers)

    def create_typical(self, payload, headers):
        return self._request("POST", "/api/typicals", payload, headers)

    def list_typicals(self, headers, params=None):
        return self._request("GET", "/api/typicals", headers=headers, params=params)

    def get_typical(self, typical_id, headers):
        return self._request("GET", f"/api/typicals/{typical_id}", headers=headers)

    def patch_typical(self, typical_id, payload, headers):
        return self._request("PATCH", f"/api/typicals/{typical_id}", payload, headers)

    # --- ProductSeries ---
    def create_product_series(self, payload, headers):
        return self._request("POST", "/api/product-series", payload, headers)

    def list_product_series(self, headers, params=None):
        return self._request("GET", "/api/product-series", headers=headers, params=params)

    def get_product_series(self, series_id, headers):
        return self._request("GET", f"/api/product-series/{series_id}", headers=headers)

    def discontinue_series(self, series_id, headers):
        return self._request("POST", f"/api/product-series/{series_id}/discontinue", {}, headers)

    def clear_quality_hold(self, series_id, headers):
        return self._request("POST", f"/api/product-series/{series_id}/clear_quality_hold", {}, headers)

    # --- ProjectOrder & OrderLine ---
    def create_project_order(self, payload, headers):
        return self._request("POST", "/api/project-orders", payload, headers)

    def list_project_orders(self, headers, params=None):
        return self._request("GET", "/api/project-orders", headers=headers, params=params)

    def get_project_order(self, order_id, headers):
        return self._request("GET", f"/api/project-orders/{order_id}", headers=headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/api/project-orders/{order_id}/submit", {}, headers)

    def revise_order(self, order_id, headers):
        return self._request("POST", f"/api/project-orders/{order_id}/revise", {}, headers)

    def acknowledge_order(self, order_id, headers):
        return self._request("POST", f"/api/project-orders/{order_id}/acknowledge", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/api/project-orders/{order_id}/cancel", {}, headers)

    def apply_credit(self, order_id, payload, headers):
        return self._request("POST", f"/api/project-orders/{order_id}/apply_credit", payload, headers)

    def close_order(self, order_id, headers):
        return self._request("POST", f"/api/project-orders/{order_id}/close", {}, headers)

    def create_order_line(self, payload, headers):
        return self._request("POST", "/api/order-lines", payload, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/api/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/api/order-lines/{line_id}", headers=headers)

    def cancel_order_line(self, line_id, headers):
        return self._request("POST", f"/api/order-lines/{line_id}/cancel", {}, headers)

    # --- Crew & InstallEvent ---
    def create_crew(self, payload, headers):
        return self._request("POST", "/api/crews", payload, headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/api/crews", headers=headers, params=params)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/api/crews/{crew_id}", headers=headers)

    def suspend_crew(self, crew_id, headers):
        return self._request("POST", f"/api/crews/{crew_id}/suspend", {}, headers)

    def activate_crew(self, crew_id, headers):
        return self._request("POST", f"/api/crews/{crew_id}/activate", {}, headers)

    def create_install_event(self, payload, headers):
        return self._request("POST", "/api/install-events", payload, headers)

    def list_install_events(self, headers, params=None):
        return self._request("GET", "/api/install-events", headers=headers, params=params)

    def get_install_event(self, event_id, headers):
        return self._request("GET", f"/api/install-events/{event_id}", headers=headers)

    def confirm_event(self, event_id, headers):
        return self._request("POST", f"/api/install-events/{event_id}/confirm", {}, headers)

    def unconfirm_event(self, event_id, headers):
        return self._request("POST", f"/api/install-events/{event_id}/unconfirm", {}, headers)

    def start_event(self, event_id, headers):
        return self._request("POST", f"/api/install-events/{event_id}/start", {}, headers)

    def complete_event(self, event_id, payload, headers):
        return self._request("POST", f"/api/install-events/{event_id}/complete", payload, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/api/install-events/{event_id}/cancel", {}, headers)

    # --- StagingReservation ---
    def create_staging_reservation(self, payload, headers):
        return self._request("POST", "/api/staging-reservations", payload, headers)

    def list_staging_reservations(self, headers, params=None):
        return self._request("GET", "/api/staging-reservations", headers=headers, params=params)

    def get_staging_reservation(self, reservation_id, headers):
        return self._request("GET", f"/api/staging-reservations/{reservation_id}", headers=headers)

    def receive_staging(self, reservation_id, payload, headers):
        return self._request("POST", f"/api/staging-reservations/{reservation_id}/receive", payload, headers)

    def release_staging(self, reservation_id, headers):
        return self._request("POST", f"/api/staging-reservations/{reservation_id}/release", {}, headers)

    def cancel_staging(self, reservation_id, headers):
        return self._request("POST", f"/api/staging-reservations/{reservation_id}/cancel", {}, headers)

    # --- PunchItem & ManufacturerClaim ---
    def create_punch_item(self, payload, headers):
        return self._request("POST", "/api/punch-items", payload, headers)

    def list_punch_items(self, headers, params=None):
        return self._request("GET", "/api/punch-items", headers=headers, params=params)

    def get_punch_item(self, punch_id, headers):
        return self._request("GET", f"/api/punch-items/{punch_id}", headers=headers)

    def ready_punch_for_verify(self, punch_id, headers):
        return self._request("POST", f"/api/punch-items/{punch_id}/ready_for_verify", {}, headers)

    def verify_punch(self, punch_id, payload, headers):
        return self._request("POST", f"/api/punch-items/{punch_id}/verify", payload, headers)

    def close_punch(self, punch_id, headers):
        return self._request("POST", f"/api/punch-items/{punch_id}/close", {}, headers)

    def create_manufacturer_claim(self, payload, headers):
        return self._request("POST", "/api/manufacturer-claims", payload, headers)

    def list_manufacturer_claims(self, headers, params=None):
        return self._request("GET", "/api/manufacturer-claims", headers=headers, params=params)

    def get_manufacturer_claim(self, claim_id, headers):
        return self._request("GET", f"/api/manufacturer-claims/{claim_id}", headers=headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/api/manufacturer-claims/{claim_id}/submit", {}, headers)

    def acknowledge_claim(self, claim_id, headers):
        return self._request("POST", f"/api/manufacturer-claims/{claim_id}/acknowledge", {}, headers)

    def offer_settlement(self, claim_id, payload, headers):
        return self._request("POST", f"/api/manufacturer-claims/{claim_id}/offer_settlement", payload, headers)

    def accept_settlement(self, claim_id, headers):
        return self._request("POST", f"/api/manufacturer-claims/{claim_id}/accept_settlement", {}, headers)

    def counter_claim(self, claim_id, headers):
        return self._request("POST", f"/api/manufacturer-claims/{claim_id}/counter", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/api/manufacturer-claims/{claim_id}/deny", {}, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/api/manufacturer-claims/{claim_id}/withdraw", {}, headers)

    # --- AssetTag ---
    def create_asset_tag(self, payload, headers):
        return self._request("POST", "/api/asset-tags", payload, headers)

    def list_asset_tags(self, headers, params=None):
        return self._request("GET", "/api/asset-tags", headers=headers, params=params)

    def get_asset_tag(self, asset_id, headers):
        return self._request("GET", f"/api/asset-tags/{asset_id}", headers=headers)

    def dispose_asset(self, asset_id, headers):
        return self._request("POST", f"/api/asset-tags/{asset_id}/dispose", {}, headers)

    # --- LiquidationLot ---
    def create_liquidation_lot(self, payload, headers):
        return self._request("POST", "/api/liquidation-lots", payload, headers)

    def list_liquidation_lots(self, headers, params=None):
        return self._request("GET", "/api/liquidation-lots", headers=headers, params=params)

    def get_liquidation_lot(self, lot_id, headers):
        return self._request("GET", f"/api/liquidation-lots/{lot_id}", headers=headers)

    def appraise_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/liquidation-lots/{lot_id}/appraise", payload, headers)

    def issue_credit(self, lot_id, headers):
        return self._request("POST", f"/api/liquidation-lots/{lot_id}/issue_credit", {}, headers)

    def redeem_lot(self, lot_id, headers):
        return self._request("POST", f"/api/liquidation-lots/{lot_id}/redeem", {}, headers)

    def decline_lot(self, lot_id, headers):
        return self._request("POST", f"/api/liquidation-lots/{lot_id}/decline", {}, headers)


api_client = ApiClient()
# The harness restarts the server before every test (per-test-server
# isolation): SIGKILL on the old listener RSTs any pooled keep-alive
# connection this session still holds, and a request written into that dead
# socket fails with ECONNRESET. Advertising Connection: close means the pool
# never retains a connection across a server restart, eliminating the race.
api_client.session.headers.update({"Connection": "close"})
