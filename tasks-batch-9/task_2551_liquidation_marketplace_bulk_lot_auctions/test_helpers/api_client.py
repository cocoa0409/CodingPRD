"""API client: one method per endpoint the PRD declares."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/liquidation"


class ApiClient(GenericApiClient):
    """Thin, explicit wrapper - one method per PRD endpoint."""

    # ─── Logical clock ────────────────────────────────
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Seller accounts ──────────────────────────────
    def create_seller_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/seller-accounts", payload, headers)

    def get_seller_account(self, seller_id, headers):
        return self._request("GET", f"{PREFIX}/seller-accounts/{seller_id}", headers=headers)

    def list_seller_accounts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/seller-accounts", headers=headers, params=params)

    # ─── Buyer accounts ───────────────────────────────
    def create_buyer_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/buyer-accounts", payload, headers)

    def get_buyer_account(self, buyer_id, headers):
        return self._request("GET", f"{PREFIX}/buyer-accounts/{buyer_id}", headers=headers)

    def list_buyer_accounts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/buyer-accounts", headers=headers, params=params)

    def decide_buyer_qualification(self, buyer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/buyer-accounts/{buyer_id}/qualification-decisions",
            payload, headers,
        )

    def set_buyer_credit_limit(self, buyer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/buyer-accounts/{buyer_id}/credit-limits", payload, headers
        )

    # ─── Warehouses / carriers / brand policies ───────
    def create_warehouse(self, payload, headers):
        return self._request("POST", f"{PREFIX}/warehouses", payload, headers)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"{PREFIX}/warehouses/{warehouse_id}", headers=headers)

    def create_carrier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"{PREFIX}/carriers/{carrier_id}", headers=headers)

    def create_brand_policy(self, payload, headers):
        return self._request("POST", f"{PREFIX}/brand-policies", payload, headers)

    def get_brand_policy(self, brand_policy_id, headers):
        return self._request("GET", f"{PREFIX}/brand-policies/{brand_policy_id}", headers=headers)

    # ─── Lots and manifests ───────────────────────────
    def create_lot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"{PREFIX}/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/lots", headers=headers, params=params)

    def create_manifest_line(self, lot_id, payload, headers):
        return self._request("POST", f"{PREFIX}/lots/{lot_id}/manifest-lines", payload, headers)

    def list_lot_manifest_lines(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/lots/{lot_id}/manifest-lines", headers=headers, params=params
        )

    def get_manifest_line(self, manifest_line_id, headers):
        return self._request(
            "GET", f"{PREFIX}/manifest-lines/{manifest_line_id}", headers=headers
        )

    def list_manifest_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/manifest-lines", headers=headers, params=params)

    def void_manifest_line(self, manifest_line_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/manifest-lines/{manifest_line_id}/voids", payload, headers
        )

    def submit_manifest(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/lots/{lot_id}/manifest-submissions", payload, headers
        )

    def review_manifest(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/lots/{lot_id}/manifest-reviews", payload, headers
        )

    # ─── Listings ─────────────────────────────────────
    def create_listing(self, lot_id, payload, headers):
        return self._request("POST", f"{PREFIX}/lots/{lot_id}/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"{PREFIX}/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/listings", headers=headers, params=params)

    def list_lot_listings(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/lots/{lot_id}/listings", headers=headers, params=params
        )

    def publish_listing(self, listing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/listings/{listing_id}/publications", payload, headers
        )

    # ─── Bidding ──────────────────────────────────────
    def place_bid(self, listing_id, payload, headers):
        return self._request("POST", f"{PREFIX}/listings/{listing_id}/bids", payload, headers)

    def place_proxy_bid(self, listing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/listings/{listing_id}/proxy-bids", payload, headers
        )

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"{PREFIX}/bids/{bid_id}", headers=headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/bids", headers=headers, params=params)

    def close_listing(self, listing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/listings/{listing_id}/closures", payload, headers
        )

    # ─── Negotiations and offers ──────────────────────
    def open_negotiation(self, listing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/listings/{listing_id}/negotiations", payload, headers
        )

    def get_negotiation(self, negotiation_id, headers):
        return self._request("GET", f"{PREFIX}/negotiations/{negotiation_id}", headers=headers)

    def list_negotiations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/negotiations", headers=headers, params=params)

    def create_counter_offer(self, negotiation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/negotiations/{negotiation_id}/counter-offers", payload, headers
        )

    def accept_negotiation(self, negotiation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/negotiations/{negotiation_id}/acceptances", payload, headers
        )

    def list_negotiation_offers(self, negotiation_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/negotiations/{negotiation_id}/offers",
            headers=headers, params=params,
        )

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"{PREFIX}/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/offers", headers=headers, params=params)

    # ─── Sale orders, payments, freight ───────────────
    def get_sale_order(self, sale_order_id, headers):
        return self._request("GET", f"{PREFIX}/sale-orders/{sale_order_id}", headers=headers)

    def list_sale_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sale-orders", headers=headers, params=params)

    def pay_sale_order(self, sale_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sale-orders/{sale_order_id}/payments", payload, headers
        )

    def book_pickup_appointment(self, sale_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sale-orders/{sale_order_id}/pickup-appointments",
            payload, headers,
        )

    def get_pickup_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/pickup-appointments/{appointment_id}", headers=headers
        )

    def list_pickup_appointments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/pickup-appointments", headers=headers, params=params
        )

    def complete_pickup_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pickup-appointments/{appointment_id}/completions",
            payload, headers,
        )

    def cancel_pickup_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pickup-appointments/{appointment_id}/cancellations",
            payload, headers,
        )

    # ─── Claims ───────────────────────────────────────
    def file_claim(self, sale_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sale-orders/{sale_order_id}/claims", payload, headers
        )

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims", headers=headers, params=params)

    def add_claim_evidence_item(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/evidence-items", payload, headers
        )

    def decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/decisions", payload, headers)

    def reverse_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/reversals", payload, headers)

    # ─── Sweeps and analytics ─────────────────────────
    def run_pickup_deadline_sweep(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pickup-deadline-sweeps", payload, headers)

    def run_payment_late_fee_sweep(self, payload, headers):
        return self._request("POST", f"{PREFIX}/payment-late-fee-sweeps", payload, headers)

    def get_recovery_analytics(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/recovery-analytics", headers=headers, params=params
        )


api_client = ApiClient()
