"""API client: one method per endpoint defined in the PRD.

All paths are mounted under /api. Server lifecycle and API_BASE_URL are
managed by the runner framework; this client only issues requests.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- SpotRate ----
    def create_spot_rate(self, payload, headers):
        return self._request("POST", "/api/spot-rates", payload, headers)

    def update_spot_rate(self, spot_rate_id, payload, headers):
        return self._request("PUT", f"/api/spot-rates/{spot_rate_id}", payload, headers)

    def get_spot_rate(self, spot_rate_id, headers):
        return self._request("GET", f"/api/spot-rates/{spot_rate_id}", headers=headers)

    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", "/api/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/api/products/{product_id}", headers=headers)

    # ---- InventoryLot ----
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/api/inventory-lots", payload, headers)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/api/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/api/inventory-lots", headers=headers, params=params)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def patch_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/api/customers/{customer_id}", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    # ---- IRAAccount ----
    def create_ira_account(self, payload, headers):
        return self._request("POST", "/api/ira-accounts", payload, headers)

    def approve_ira_account(self, ira_id, headers):
        return self._request("POST", f"/api/ira-accounts/{ira_id}/approve", headers=headers)

    def close_ira_account(self, ira_id, headers):
        return self._request("POST", f"/api/ira-accounts/{ira_id}/close", headers=headers)

    def get_ira_account(self, ira_id, headers):
        return self._request("GET", f"/api/ira-accounts/{ira_id}", headers=headers)

    def list_ira_accounts(self, headers, params=None):
        return self._request("GET", "/api/ira-accounts", headers=headers, params=params)

    # ---- SellOrder ----
    def create_sell_order(self, payload, headers):
        return self._request("POST", "/api/sell-orders", payload, headers)

    def settle_sell_order(self, so_id, headers):
        return self._request("POST", f"/api/sell-orders/{so_id}/settle", headers=headers)

    def cancel_sell_order(self, so_id, headers):
        return self._request("POST", f"/api/sell-orders/{so_id}/cancel", headers=headers)

    def get_sell_order(self, so_id, headers):
        return self._request("GET", f"/api/sell-orders/{so_id}", headers=headers)

    def list_sell_orders(self, headers, params=None):
        return self._request("GET", "/api/sell-orders", headers=headers, params=params)

    # ---- BuyOrder ----
    def create_buy_order(self, payload, headers):
        return self._request("POST", "/api/buy-orders", payload, headers)

    def approve_reportable_buy_order(self, bo_id, headers):
        return self._request("POST", f"/api/buy-orders/{bo_id}/approve-reportable", headers=headers)

    def settle_buy_order(self, bo_id, headers):
        return self._request("POST", f"/api/buy-orders/{bo_id}/settle", headers=headers)

    def reject_buy_order(self, bo_id, headers):
        return self._request("POST", f"/api/buy-orders/{bo_id}/reject", headers=headers)

    def get_buy_order(self, bo_id, headers):
        return self._request("GET", f"/api/buy-orders/{bo_id}", headers=headers)

    def list_buy_orders(self, headers, params=None):
        return self._request("GET", "/api/buy-orders", headers=headers, params=params)

    # ---- Layaway ----
    def create_layaway(self, payload, headers):
        return self._request("POST", "/api/layaways", payload, headers)

    def deposit_layaway(self, lay_id, payload, headers):
        return self._request("POST", f"/api/layaways/{lay_id}/deposit", payload, headers)

    def complete_layaway(self, lay_id, headers):
        return self._request("POST", f"/api/layaways/{lay_id}/complete", headers=headers)

    def default_layaway(self, lay_id, headers):
        return self._request("POST", f"/api/layaways/{lay_id}/default", headers=headers)

    def cancel_layaway(self, lay_id, headers):
        return self._request("POST", f"/api/layaways/{lay_id}/cancel", headers=headers)

    def get_layaway(self, lay_id, headers):
        return self._request("GET", f"/api/layaways/{lay_id}", headers=headers)

    def list_layaways(self, headers, params=None):
        return self._request("GET", "/api/layaways", headers=headers, params=params)

    # ---- Consignment ----
    def create_consignment(self, payload, headers):
        return self._request("POST", "/api/consignments", payload, headers)

    def list_consignment(self, cons_id, payload, headers):
        return self._request("POST", f"/api/consignments/{cons_id}/list", payload, headers)

    def record_sale_consignment(self, cons_id, payload, headers):
        return self._request("POST", f"/api/consignments/{cons_id}/record-sale", payload, headers)

    def return_consignment(self, cons_id, headers):
        return self._request("POST", f"/api/consignments/{cons_id}/return", headers=headers)

    def get_consignment(self, cons_id, headers):
        return self._request("GET", f"/api/consignments/{cons_id}", headers=headers)

    def list_consignments(self, headers, params=None):
        return self._request("GET", "/api/consignments", headers=headers, params=params)

    # ---- HedgePosition ----
    def create_hedge_position(self, payload, headers):
        return self._request("POST", "/api/hedge-positions", payload, headers)

    def close_hedge_position(self, hedge_id, headers):
        return self._request("POST", f"/api/hedge-positions/{hedge_id}/close", headers=headers)

    def get_hedge_position(self, hedge_id, headers):
        return self._request("GET", f"/api/hedge-positions/{hedge_id}", headers=headers)

    # ---- Settlement ----
    def create_settlement(self, payload, headers):
        return self._request("POST", "/api/settlements", payload, headers)

    def get_settlement(self, settle_id, headers):
        return self._request("GET", f"/api/settlements/{settle_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/api/settlements", headers=headers, params=params)

    # ---- Appraiser ----
    def create_appraiser(self, payload, headers):
        return self._request("POST", "/api/appraisers", payload, headers)

    def get_appraiser(self, appraiser_id, headers):
        return self._request("GET", f"/api/appraisers/{appraiser_id}", headers=headers)

    # ---- AppraisalAppointment ----
    def create_appraisal_appointment(self, payload, headers):
        return self._request("POST", "/api/appraisal-appointments", payload, headers)

    def cancel_appraisal_appointment(self, appt_id, headers):
        return self._request("POST", f"/api/appraisal-appointments/{appt_id}/cancel", headers=headers)

    def get_appraisal_appointment(self, appt_id, headers):
        return self._request("GET", f"/api/appraisal-appointments/{appt_id}", headers=headers)

    def list_appraisal_appointments(self, headers, params=None):
        return self._request("GET", "/api/appraisal-appointments", headers=headers, params=params)

    # ---- AuctionSession ----
    def create_auction_session(self, payload, headers):
        return self._request("POST", "/api/auction-sessions", payload, headers)

    def close_auction_session(self, sess_id, headers):
        return self._request("POST", f"/api/auction-sessions/{sess_id}/close", headers=headers)

    def get_auction_session(self, sess_id, headers):
        return self._request("GET", f"/api/auction-sessions/{sess_id}", headers=headers)


api_client = ApiClient()
