"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Stores ──────────────────────────────────────────────────────────────
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers=headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    # ─── Cash drawer sessions ────────────────────────────────────────────────
    def create_cash_session(self, payload, headers):
        return self._request("POST", "/cash-sessions", payload, headers=headers)

    def get_cash_session(self, session_id, headers):
        return self._request("GET", f"/cash-sessions/{session_id}", headers=headers)

    def list_cash_sessions(self, headers, params=None):
        return self._request("GET", "/cash-sessions", headers=headers, params=params)

    def request_close_cash_session(self, session_id, headers):
        return self._request("POST", f"/cash-sessions/{session_id}/request-close", {}, headers=headers)

    def reconcile_cash_session(self, session_id, payload, headers):
        return self._request("POST", f"/cash-sessions/{session_id}/reconcile", payload, headers=headers)

    def reopen_cash_session(self, session_id, headers):
        return self._request("POST", f"/cash-sessions/{session_id}/reopen", {}, headers=headers)

    def force_close_cash_session(self, session_id, headers):
        return self._request("POST", f"/cash-sessions/{session_id}/force-close", {}, headers=headers)

    # ─── Products ────────────────────────────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers=headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/discontinue", {}, headers=headers)

    # ─── Inventory items ─────────────────────────────────────────────────────
    def create_inventory_item(self, payload, headers):
        return self._request("POST", "/inventory-items", payload, headers=headers)

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"/inventory-items/{item_id}", headers=headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", "/inventory-items", headers=headers, params=params)

    # ─── Count sheets ────────────────────────────────────────────────────────
    def create_count_sheet(self, payload, headers):
        return self._request("POST", "/count-sheets", payload, headers=headers)

    def get_count_sheet(self, sheet_id, headers):
        return self._request("GET", f"/count-sheets/{sheet_id}", headers=headers)

    def list_count_sheets(self, headers, params=None):
        return self._request("GET", "/count-sheets", headers=headers, params=params)

    def post_count_sheet(self, sheet_id, headers):
        return self._request("POST", f"/count-sheets/{sheet_id}/post", {}, headers=headers)

    def discard_count_sheet(self, sheet_id, headers):
        return self._request("POST", f"/count-sheets/{sheet_id}/discard", {}, headers=headers)

    # ─── Loyalty accounts ────────────────────────────────────────────────────
    def create_loyalty_account(self, payload, headers):
        return self._request("POST", "/loyalty-accounts", payload, headers=headers)

    def get_loyalty_account(self, account_id, headers):
        return self._request("GET", f"/loyalty-accounts/{account_id}", headers=headers)

    def grant_loyalty(self, payload, headers):
        return self._request("POST", "/_loyalty/grant", payload, headers=headers)

    # ─── Promotions ──────────────────────────────────────────────────────────
    def create_promotion(self, payload, headers):
        return self._request("POST", "/promotions", payload, headers=headers)

    def get_promotion(self, promo_id, headers):
        return self._request("GET", f"/promotions/{promo_id}", headers=headers)

    def disable_promotion(self, promo_id, headers):
        return self._request("POST", f"/promotions/{promo_id}/disable", {}, headers=headers)

    # ─── Sales ───────────────────────────────────────────────────────────────
    def create_sale(self, payload, headers):
        return self._request("POST", "/sales", payload, headers=headers)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/sales/{sale_id}", headers=headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/sales", headers=headers, params=params)

    def replace_sale_lines(self, sale_id, payload, headers):
        return self._request("PUT", f"/sales/{sale_id}/lines", payload, headers=headers)

    def create_tender(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/tenders", payload, headers=headers)

    def list_tenders(self, sale_id, headers, params=None):
        return self._request("GET", f"/sales/{sale_id}/tenders", headers=headers, params=params)

    def void_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/void", {}, headers=headers)

    # ─── Layaways ────────────────────────────────────────────────────────────
    def create_layaway(self, payload, headers):
        return self._request("POST", "/layaways", payload, headers=headers)

    def get_layaway(self, layaway_id, headers):
        return self._request("GET", f"/layaways/{layaway_id}", headers=headers)

    def list_layaways(self, headers, params=None):
        return self._request("GET", "/layaways", headers=headers, params=params)

    def create_layaway_payment(self, layaway_id, payload, headers):
        return self._request("POST", f"/layaways/{layaway_id}/payments", payload, headers=headers)

    def forfeit_layaway(self, layaway_id, headers):
        return self._request("POST", f"/layaways/{layaway_id}/forfeit", {}, headers=headers)

    def cancel_layaway(self, layaway_id, headers):
        return self._request("POST", f"/layaways/{layaway_id}/cancel", {}, headers=headers)

    # ─── Transfers ───────────────────────────────────────────────────────────
    def create_transfer(self, payload, headers):
        return self._request("POST", "/transfers", payload, headers=headers)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/transfers/{transfer_id}", headers=headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/transfers", headers=headers, params=params)

    def dispatch_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/transfers/{transfer_id}/dispatch", payload, headers=headers)

    def receive_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/transfers/{transfer_id}/receive", payload, headers=headers)

    def reject_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/reject", {}, headers=headers)

    def cancel_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/cancel", {}, headers=headers)

    # ─── Test-driving clock ──────────────────────────────────────────────────
    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers=headers)


api_client = ApiClient()
