"""API client: one method per endpoint defined in the PRD endpoint summary."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Sellers ---
    def create_seller(self, payload, headers):
        return self._request("POST", "/sellers", payload, headers)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"/sellers/{seller_id}", headers=headers)

    def list_seller_buy_offers(self, seller_id, headers):
        return self._request("GET", f"/sellers/{seller_id}/buy-offers", headers=headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # --- Storage bins ---
    def create_storage_bin(self, payload, headers):
        return self._request("POST", "/storage-bins", payload, headers)

    def get_storage_bin(self, bin_id, headers):
        return self._request("GET", f"/storage-bins/{bin_id}", headers=headers)

    # --- Buy offers ---
    def create_buy_offer(self, payload, headers):
        return self._request("POST", "/buy-offers", payload, headers)

    def get_buy_offer(self, offer_id, headers):
        return self._request("GET", f"/buy-offers/{offer_id}", headers=headers)

    def accept_buy_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/buy-offers/{offer_id}/accept", payload, headers)

    def reject_buy_offer(self, offer_id, headers):
        return self._request("POST", f"/buy-offers/{offer_id}/reject", {}, headers)

    def cancel_buy_offer(self, offer_id, headers):
        return self._request("POST", f"/buy-offers/{offer_id}/cancel", {}, headers)

    def receive_buy_offer(self, offer_id, headers):
        return self._request("POST", f"/buy-offers/{offer_id}/receive", {}, headers)

    def inspect_buy_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/buy-offers/{offer_id}/inspect", payload, headers)

    def convert_buy_offer_to_lot(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/buy-offers/{offer_id}/convert-to-lot", payload, headers
        )

    def initiate_buy_offer_return(self, offer_id, headers):
        return self._request(
            "POST", f"/buy-offers/{offer_id}/initiate-return", {}, headers
        )

    def mark_buy_offer_returned(self, offer_id, headers):
        return self._request(
            "POST", f"/buy-offers/{offer_id}/mark-returned", {}, headers
        )

    # --- Lots ---
    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def flag_lot_counterfeit_suspect(self, lot_id, headers):
        return self._request(
            "POST", f"/lots/{lot_id}/flag-counterfeit-suspect", {}, headers
        )

    def quarantine_lot(self, lot_id, headers, payload=None):
        return self._request(
            "POST", f"/lots/{lot_id}/quarantine", payload or {}, headers
        )

    def release_lot_quarantine(self, lot_id, headers):
        return self._request(
            "POST", f"/lots/{lot_id}/release-quarantine", {}, headers
        )

    # --- Market price snapshots ---
    def create_market_price_snapshot(self, payload, headers):
        return self._request("POST", "/market-price-snapshots", payload, headers)

    def list_market_price_snapshots(self, headers, params=None):
        return self._request(
            "GET", "/market-price-snapshots", headers=headers, params=params
        )

    # --- Consignment agreements ---
    def create_consignment_agreement(self, payload, headers):
        return self._request("POST", "/consignment-agreements", payload, headers)

    def list_consignment_agreements(self, headers, params=None):
        return self._request(
            "GET", "/consignment-agreements", headers=headers, params=params
        )

    def get_consignment_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/consignment-agreements/{agreement_id}", headers=headers
        )

    def terminate_consignment_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/consignment-agreements/{agreement_id}/terminate", {}, headers
        )

    # --- Listings ---
    def create_listing(self, payload, headers):
        return self._request("POST", "/listings", payload, headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def patch_listing(self, listing_id, payload, headers):
        return self._request("PATCH", f"/listings/{listing_id}", payload, headers)

    def activate_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/activate", {}, headers)

    def pause_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/pause", {}, headers)

    def withdraw_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/withdraw", {}, headers)

    # --- Sales orders ---
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/sales-orders", payload, headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/sales-orders", headers=headers, params=params)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/sales-orders/{order_id}", headers=headers)

    def deposit_escrow(self, order_id, payload, headers):
        return self._request(
            "POST", f"/sales-orders/{order_id}/escrow/deposit", payload, headers
        )

    def fulfill_sales_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/fulfill", {}, headers)

    def ship_sales_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/ship", {}, headers)

    def deliver_sales_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/deliver", {}, headers)

    def settle_sales_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/settle", {}, headers)

    def cancel_sales_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/cancel", {}, headers)

    # --- Escrow ledger ---
    def list_escrow_entries(self, order_id, headers):
        return self._request(
            "GET", f"/sales-orders/{order_id}/escrow-entries", headers=headers
        )

    # --- Return cases ---
    def create_return_case(self, payload, headers):
        return self._request("POST", "/return-cases", payload, headers)

    def get_return_case(self, return_case_id, headers):
        return self._request("GET", f"/return-cases/{return_case_id}", headers=headers)

    def list_order_return_cases(self, order_id, headers):
        return self._request(
            "GET", f"/sales-orders/{order_id}/return-cases", headers=headers
        )

    def start_return_case_review(self, return_case_id, headers):
        return self._request(
            "POST", f"/return-cases/{return_case_id}/start-review", {}, headers
        )

    def approve_return_case(self, return_case_id, headers):
        return self._request(
            "POST", f"/return-cases/{return_case_id}/approve", {}, headers
        )

    def reject_return_case(self, return_case_id, headers, payload=None):
        return self._request(
            "POST", f"/return-cases/{return_case_id}/reject", payload or {}, headers
        )

    def issue_return_case_refund(self, return_case_id, headers):
        return self._request(
            "POST", f"/return-cases/{return_case_id}/issue-refund", {}, headers
        )


api_client = ApiClient()
