"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fulfillment"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Marketplace Fulfillment Inventory & Storage Cost API."""

    # ----------------------------------------------------------------- clock #
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --------------------------------------------------------------- sellers #
    def create_seller(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sellers", payload, headers)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"{PREFIX}/sellers/{seller_id}", headers=headers)

    def list_seller_sku_listings(self, seller_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sellers/{seller_id}/sku-listings",
            headers=headers, params=params,
        )

    def list_restock_quotas(self, seller_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sellers/{seller_id}/restock-quotas",
            headers=headers, params=params,
        )

    def create_restock_quota(self, seller_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sellers/{seller_id}/restock-quotas", payload, headers
        )

    # --------------------------------------------------- fulfillment centers #
    def create_fulfillment_center(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fulfillment-centers", payload, headers)

    def get_fulfillment_center(self, fc_id, headers):
        return self._request(
            "GET", f"{PREFIX}/fulfillment-centers/{fc_id}", headers=headers
        )

    def update_fulfillment_center(self, fc_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/fulfillment-centers/{fc_id}", payload, headers
        )

    # ---------------------------------------------------------- sku listings #
    def create_sku_listing(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sku-listings", payload, headers)

    def get_sku_listing(self, listing_id, headers):
        return self._request(
            "GET", f"{PREFIX}/sku-listings/{listing_id}", headers=headers
        )

    def reinstate_sku_listing(self, listing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sku-listings/{listing_id}/reinstate", payload, headers
        )

    def list_listing_line_items(self, listing_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sku-listings/{listing_id}/line-items",
            headers=headers, params=params,
        )

    def list_velocity_forecasts(self, listing_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sku-listings/{listing_id}/velocity-forecasts",
            headers=headers, params=params,
        )

    def create_velocity_forecast(self, listing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sku-listings/{listing_id}/velocity-forecasts",
            payload, headers,
        )

    def list_listing_multi_channel_orders(self, listing_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sku-listings/{listing_id}/multi-channel-orders",
            headers=headers, params=params,
        )

    # ------------------------------------------------ inbound shipment plans #
    def create_inbound_shipment_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inbound-shipment-plans", payload, headers)

    def list_inbound_shipment_plans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/inbound-shipment-plans", headers=headers, params=params
        )

    def get_inbound_shipment_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/inbound-shipment-plans/{plan_id}", headers=headers
        )

    def create_line_item(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inbound-shipment-plans/{plan_id}/line-items",
            payload, headers,
        )

    def list_plan_line_items(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/inbound-shipment-plans/{plan_id}/line-items",
            headers=headers, params=params,
        )

    def confirm_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inbound-shipment-plans/{plan_id}/confirm", payload, headers
        )

    def revert_plan_to_draft(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inbound-shipment-plans/{plan_id}/revert-to-draft",
            payload, headers,
        )

    def ship_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inbound-shipment-plans/{plan_id}/ship", payload, headers
        )

    def receive_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inbound-shipment-plans/{plan_id}/receive", payload, headers
        )

    def cancel_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inbound-shipment-plans/{plan_id}/cancel", payload, headers
        )

    # -------------------------------------------------------- inventory lots #
    def list_inventory_lots(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/inventory-lots", headers=headers, params=params
        )

    def get_inventory_lot(self, lot_id, headers):
        return self._request(
            "GET", f"{PREFIX}/inventory-lots/{lot_id}", headers=headers
        )

    def classify_unfulfillable(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inventory-lots/{lot_id}/unfulfillable-classification",
            payload, headers,
        )

    def list_storage_fee_assessments(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/inventory-lots/{lot_id}/storage-fee-assessments",
            headers=headers, params=params,
        )

    def list_lot_removal_orders(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/inventory-lots/{lot_id}/removal-orders",
            headers=headers, params=params,
        )

    def list_lot_reimbursement_claims(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/inventory-lots/{lot_id}/reimbursement-claims",
            headers=headers, params=params,
        )

    # --------------------------------------------------------- removal orders #
    def create_removal_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/removal-orders", payload, headers)

    def get_removal_order(self, removal_order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/removal-orders/{removal_order_id}", headers=headers
        )

    def complete_removal_order(self, removal_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/removal-orders/{removal_order_id}/complete",
            payload, headers,
        )

    def cancel_removal_order(self, removal_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/removal-orders/{removal_order_id}/cancel", payload, headers
        )

    # --------------------------------------------------- reimbursement claims #
    def file_reimbursement_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/reimbursement-claims", payload, headers)

    def get_reimbursement_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{PREFIX}/reimbursement-claims/{claim_id}", headers=headers
        )

    def request_claim_info(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/reimbursement-claims/{claim_id}/request-info",
            payload, headers,
        )

    def resubmit_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/reimbursement-claims/{claim_id}/resubmit", payload, headers
        )

    def decide_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/reimbursement-claims/{claim_id}/decide", payload, headers
        )

    # ---------------------------------------------------- multi-channel orders #
    def create_multi_channel_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/multi-channel-orders", payload, headers)

    # ----------------------------------------------------- storage billing run #
    def create_storage_billing_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/storage-billing-runs", payload, headers)


api_client = ApiClient()
