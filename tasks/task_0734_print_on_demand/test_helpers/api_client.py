"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Creator ----
    def register_creator(self, payload, headers):
        return self._request("POST", "/pod/creators/register", payload, headers)

    def get_creator(self, creator_id, headers):
        return self._request("GET", f"/pod/creators/{creator_id}", headers=headers)

    def verify_creator(self, creator_id, payload, headers):
        return self._request("POST", f"/pod/creators/{creator_id}/verify", payload, headers)

    # ---- Storefront ----
    def create_storefront(self, payload, headers):
        return self._request("POST", "/pod/storefronts", payload, headers)

    def get_storefront(self, storefront_id, headers):
        return self._request("GET", f"/pod/storefronts/{storefront_id}", headers=headers)

    def list_storefronts(self, headers, params=None):
        return self._request("GET", "/pod/storefronts", headers=headers, params=params)

    def update_storefront(self, storefront_id, payload, headers):
        return self._request("PUT", f"/pod/storefronts/{storefront_id}", payload, headers)

    def link_channel(self, storefront_id, payload, headers):
        return self._request("POST", f"/pod/storefronts/{storefront_id}/link-channel", payload, headers)

    def suspend_channel(self, storefront_id, headers):
        return self._request("POST", f"/pod/storefronts/{storefront_id}/suspend-channel", {}, headers)

    def resume_channel(self, storefront_id, headers):
        return self._request("POST", f"/pod/storefronts/{storefront_id}/resume-channel", {}, headers)

    # ---- Product / Variant ----
    def create_product(self, payload, headers):
        return self._request("POST", "/pod/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/pod/products/{product_id}", headers=headers)

    def get_variant(self, variant_id, headers):
        return self._request("GET", f"/pod/variants/{variant_id}", headers=headers)

    def list_variants(self, headers, params=None):
        return self._request("GET", "/pod/variants", headers=headers, params=params)

    def create_variant(self, product_id, payload, headers):
        return self._request("POST", f"/pod/products/{product_id}/variants", payload, headers)

    # ---- Design ----
    def upload_design(self, creator_id, payload, headers):
        return self._request("POST", f"/pod/creators/{creator_id}/designs", payload, headers)

    def get_design(self, design_id, headers):
        return self._request("GET", f"/pod/designs/{design_id}", headers=headers)

    def list_creator_designs(self, creator_id, headers, params=None):
        return self._request("GET", f"/pod/creators/{creator_id}/designs", headers=headers, params=params)

    def generate_mockup(self, design_id, headers):
        return self._request("POST", f"/pod/designs/{design_id}/mockup", {}, headers)

    def approve_design(self, design_id, headers):
        return self._request("POST", f"/pod/designs/{design_id}/approve", {}, headers)

    def reject_design(self, design_id, headers):
        return self._request("POST", f"/pod/designs/{design_id}/reject", {}, headers)

    # ---- Listing ----
    def create_listing(self, payload, headers):
        return self._request("POST", "/pod/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/pod/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/pod/listings", headers=headers, params=params)

    def publish_listing(self, listing_id, headers):
        return self._request("POST", f"/pod/listings/{listing_id}/publish", {}, headers)

    # ---- Order ----
    def create_order(self, payload, headers):
        return self._request("POST", "/pod/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/pod/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/pod/orders", headers=headers, params=params)

    def authorize_order(self, order_id, headers):
        return self._request("POST", f"/pod/orders/{order_id}/authorize", {}, headers)

    def capture_order(self, order_id, headers):
        return self._request("POST", f"/pod/orders/{order_id}/capture", {}, headers)

    def refund_order(self, order_id, payload, headers):
        return self._request("POST", f"/pod/orders/{order_id}/refund", payload, headers)

    def void_order(self, order_id, headers):
        return self._request("POST", f"/pod/orders/{order_id}/void", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/pod/orders/{order_id}/cancel", {}, headers)

    def mark_in_print(self, order_id, headers):
        return self._request("POST", f"/pod/orders/{order_id}/mark-in-print", {}, headers)

    def mark_shipped(self, order_id, headers):
        return self._request("POST", f"/pod/orders/{order_id}/mark-shipped", {}, headers)

    def mark_delivered(self, order_id, headers):
        return self._request("POST", f"/pod/orders/{order_id}/mark-delivered", {}, headers)

    # ---- FulfillmentJob / ReprintRequest ----
    def get_fulfillment_job(self, job_id, headers):
        return self._request("GET", f"/pod/fulfillment-jobs/{job_id}", headers=headers)

    def list_fulfillment_jobs(self, headers, params=None):
        return self._request("GET", "/pod/fulfillment-jobs", headers=headers, params=params)

    def mark_job_failed(self, job_id, headers):
        return self._request("POST", f"/pod/fulfillment-jobs/{job_id}/mark-failed", {}, headers)

    def open_reprint_request(self, job_id, payload, headers):
        return self._request("POST", f"/pod/fulfillment-jobs/{job_id}/reprint-requests", payload, headers)

    def get_reprint_request(self, reprint_id, headers):
        return self._request("GET", f"/pod/reprint-requests/{reprint_id}", headers=headers)

    def list_reprint_requests(self, headers, params=None):
        return self._request("GET", "/pod/reprint-requests", headers=headers, params=params)

    def approve_reprint(self, reprint_id, headers):
        return self._request("POST", f"/pod/reprint-requests/{reprint_id}/approve", {}, headers)

    def deny_reprint(self, reprint_id, headers):
        return self._request("POST", f"/pod/reprint-requests/{reprint_id}/deny", {}, headers)

    # ---- FulfillmentPartner ----
    def create_fulfillment_partner(self, payload, headers):
        return self._request("POST", "/pod/fulfillment-partners", payload, headers)

    def get_fulfillment_partner(self, partner_id, headers):
        return self._request("GET", f"/pod/fulfillment-partners/{partner_id}", headers=headers)

    def list_fulfillment_partners(self, headers, params=None):
        return self._request("GET", "/pod/fulfillment-partners", headers=headers, params=params)

    # ---- PayoutCycle ----
    def create_payout_cycle(self, creator_id, payload, headers):
        return self._request("POST", f"/pod/creators/{creator_id}/payout-cycles", payload, headers)

    def get_payout_cycle(self, cycle_id, headers):
        return self._request("GET", f"/pod/payout-cycles/{cycle_id}", headers=headers)

    def list_creator_payout_cycles(self, creator_id, headers, params=None):
        return self._request("GET", f"/pod/creators/{creator_id}/payout-cycles", headers=headers, params=params)

    def release_payout(self, cycle_id, headers):
        return self._request("POST", f"/pod/payout-cycles/{cycle_id}/release", {}, headers)

    def return_payout(self, cycle_id, headers):
        return self._request("POST", f"/pod/payout-cycles/{cycle_id}/return", {}, headers)

    # ---- ChannelSyncEvent ----
    def list_channel_sync_events(self, storefront_id, headers, params=None):
        return self._request("GET", f"/pod/storefronts/{storefront_id}/channel-sync-events", headers=headers, params=params)

    def ingest_channel_order(self, storefront_id, payload, headers):
        return self._request("POST", f"/pod/storefronts/{storefront_id}/ingest-channel-order", payload, headers)

    # ---- Test-driving endpoints ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def decay_strikes(self, headers):
        return self._request("POST", "/_ops/decay-strikes", {}, headers)


api_client = ApiClient()
