"""API client: one method per endpoint defined in the Coffee Roaster Wholesale PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- PriceTier ----
    def create_price_tier(self, payload, headers):
        return self._request("POST", "/price-tiers", payload, headers)

    def list_price_tiers(self, headers, params=None):
        return self._request("GET", "/price-tiers", headers=headers, params=params)

    def get_price_tier(self, tier_id, headers):
        return self._request("GET", f"/price-tiers/{tier_id}", headers=headers)

    # ---- WholesaleAccount ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    # ---- RoastProfile ----
    def create_roast_profile(self, payload, headers):
        return self._request("POST", "/roast-profiles", payload, headers)

    def list_roast_profiles(self, headers, params=None):
        return self._request("GET", "/roast-profiles", headers=headers, params=params)

    def get_roast_profile(self, profile_id, headers):
        return self._request("GET", f"/roast-profiles/{profile_id}", headers=headers)

    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def archive_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/archive", headers=headers)

    # ---- GreenLot ----
    def create_green_lot(self, payload, headers):
        return self._request("POST", "/green-lots", payload, headers)

    def list_green_lots(self, headers, params=None):
        return self._request("GET", "/green-lots", headers=headers, params=params)

    def get_green_lot(self, green_lot_id, headers):
        return self._request("GET", f"/green-lots/{green_lot_id}", headers=headers)

    def list_green_lot_roast_batches(self, green_lot_id, headers, params=None):
        return self._request("GET", f"/green-lots/{green_lot_id}/roast-batches",
                             headers=headers, params=params)

    # ---- RoastBatch ----
    def create_roast_batch(self, payload, headers):
        return self._request("POST", "/roast-batches", payload, headers)

    def list_roast_batches(self, headers, params=None):
        return self._request("GET", "/roast-batches", headers=headers, params=params)

    def get_roast_batch(self, batch_id, headers):
        return self._request("GET", f"/roast-batches/{batch_id}", headers=headers)

    def start_roast_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/roast-batches/{batch_id}/start", payload, headers)

    def drop_roast_batch(self, batch_id, headers):
        return self._request("POST", f"/roast-batches/{batch_id}/drop", headers=headers)

    def reroast_roast_batch(self, batch_id, headers):
        return self._request("POST", f"/roast-batches/{batch_id}/reroast", headers=headers)

    def complete_roast_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/roast-batches/{batch_id}/complete", payload, headers)

    def cancel_roast_batch(self, batch_id, headers):
        return self._request("POST", f"/roast-batches/{batch_id}/cancel", headers=headers)

    def list_batch_roasted_lots(self, batch_id, headers, params=None):
        return self._request("GET", f"/roast-batches/{batch_id}/roasted-lots",
                             headers=headers, params=params)

    # ---- RoastedLot ----
    def list_roasted_lots(self, headers, params=None):
        return self._request("GET", "/roasted-lots", headers=headers, params=params)

    def get_roasted_lot(self, roasted_lot_id, headers):
        return self._request("GET", f"/roasted-lots/{roasted_lot_id}", headers=headers)

    # ---- StandingOrder ----
    def create_standing_order(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/standing-orders", payload, headers)

    def list_account_standing_orders(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/standing-orders",
                             headers=headers, params=params)

    def list_standing_orders(self, headers, params=None):
        return self._request("GET", "/standing-orders", headers=headers, params=params)

    def get_standing_order(self, so_id, headers):
        return self._request("GET", f"/standing-orders/{so_id}", headers=headers)

    def release_standing_order(self, so_id, headers):
        return self._request("POST", f"/standing-orders/{so_id}/release", headers=headers)

    def pause_standing_order(self, so_id, headers):
        return self._request("POST", f"/standing-orders/{so_id}/pause", headers=headers)

    def resume_standing_order(self, so_id, headers):
        return self._request("POST", f"/standing-orders/{so_id}/resume", headers=headers)

    def cancel_standing_order(self, so_id, headers):
        return self._request("POST", f"/standing-orders/{so_id}/cancel", headers=headers)

    # ---- Order ----
    def create_order(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/orders", payload, headers)

    def list_account_orders(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/orders",
                             headers=headers, params=params)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", headers=headers)

    def invoice_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/invoice", headers=headers)

    # ---- Fulfillment ----
    def create_fulfillment(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/fulfillments", payload, headers)

    def list_order_fulfillments(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/fulfillments",
                             headers=headers, params=params)

    def list_fulfillments(self, headers, params=None):
        return self._request("GET", "/fulfillments", headers=headers, params=params)

    def get_fulfillment(self, fulfillment_id, headers):
        return self._request("GET", f"/fulfillments/{fulfillment_id}", headers=headers)

    def ship_fulfillment(self, fulfillment_id, headers):
        return self._request("POST", f"/fulfillments/{fulfillment_id}/ship", headers=headers)

    def cancel_fulfillment(self, fulfillment_id, headers):
        return self._request("POST", f"/fulfillments/{fulfillment_id}/cancel", headers=headers)

    # ---- SampleRequest ----
    def create_sample_request(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/sample-requests", payload, headers)

    def list_account_sample_requests(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/sample-requests",
                             headers=headers, params=params)

    def list_sample_requests(self, headers, params=None):
        return self._request("GET", "/sample-requests", headers=headers, params=params)

    def get_sample_request(self, sr_id, headers):
        return self._request("GET", f"/sample-requests/{sr_id}", headers=headers)

    def review_sample_request(self, sr_id, payload, headers):
        return self._request("POST", f"/sample-requests/{sr_id}/review", payload, headers)

    def convert_sample_request(self, sr_id, payload, headers):
        return self._request("POST", f"/sample-requests/{sr_id}/convert", payload, headers)

    # ---- Invoice + Payment ----
    def list_account_invoices(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/invoices",
                             headers=headers, params=params)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def create_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers)

    def list_invoice_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/payments",
                             headers=headers, params=params)

    # ---- Test-driving clock ----
    def clock_set(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def clock_advance(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
