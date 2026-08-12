"""API client: one method per endpoint defined in the PRD (section 4).

Everything is mounted under the /toy-rental prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

P = "/toy-rental"


class ApiClient(GenericApiClient):
    # ---------------- Logical clock / ops ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{P}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_allocation(self, headers):
        return self._request("POST", f"{P}/ops/allocation-runs", {}, headers)

    # ---------------- Members / children / wallet ----------------
    def register_member(self, payload, headers):
        return self._request("POST", f"{P}/members/register", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"{P}/members/{member_id}", headers=headers)

    def close_member(self, member_id, headers):
        return self._request("POST", f"{P}/members/{member_id}/close", {}, headers)

    def create_child(self, member_id, payload, headers):
        return self._request("POST", f"{P}/members/{member_id}/children", payload, headers)

    def list_children(self, member_id, headers, params=None):
        return self._request("GET", f"{P}/members/{member_id}/children",
                             headers=headers, params=params)

    def create_wallet_adjustment(self, member_id, payload, headers):
        return self._request("POST", f"{P}/members/{member_id}/wallet/adjustments",
                             payload, headers)

    def list_wallet_ledger(self, member_id, headers, params=None):
        return self._request("GET", f"{P}/members/{member_id}/wallet/ledger",
                             headers=headers, params=params)

    def list_reserved_copies(self, member_id, headers, params=None):
        return self._request("GET", f"{P}/members/{member_id}/reserved-copies",
                             headers=headers, params=params)

    def create_subscription(self, member_id, payload, headers):
        return self._request("POST", f"{P}/members/{member_id}/subscriptions",
                             payload, headers)

    def list_subscriptions(self, member_id, headers, params=None):
        return self._request("GET", f"{P}/members/{member_id}/subscriptions",
                             headers=headers, params=params)

    def create_wishlist_entry(self, member_id, payload, headers):
        return self._request("POST", f"{P}/members/{member_id}/wishlist-entries",
                             payload, headers)

    def list_wishlist_entries(self, member_id, headers, params=None):
        return self._request("GET", f"{P}/members/{member_id}/wishlist-entries",
                             headers=headers, params=params)

    # ---------------- Plans ----------------
    def create_plan(self, payload, headers):
        return self._request("POST", f"{P}/subscription-plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", f"{P}/subscription-plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"{P}/subscription-plans/{plan_id}", headers=headers)

    def list_plan_subscriptions(self, plan_id, headers, params=None):
        return self._request("GET", f"{P}/subscription-plans/{plan_id}/subscriptions",
                             headers=headers, params=params)

    # ---------------- Subscriptions ----------------
    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"{P}/subscriptions/{subscription_id}", headers=headers)

    def change_plan(self, subscription_id, payload, headers):
        return self._request("PATCH", f"{P}/subscriptions/{subscription_id}/plan",
                             payload, headers)

    def pause_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"{P}/subscriptions/{subscription_id}/pause",
                             payload, headers)

    def resume_subscription(self, subscription_id, headers):
        return self._request("POST", f"{P}/subscriptions/{subscription_id}/resume",
                             {}, headers)

    def cancel_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"{P}/subscriptions/{subscription_id}/cancel",
                             payload, headers)

    def create_rotation_box(self, subscription_id, payload, headers):
        return self._request("POST", f"{P}/subscriptions/{subscription_id}/rotation-boxes",
                             payload, headers)

    def list_rotation_boxes(self, subscription_id, headers, params=None):
        return self._request("GET", f"{P}/subscriptions/{subscription_id}/rotation-boxes",
                             headers=headers, params=params)

    def list_subscription_fees(self, subscription_id, headers, params=None):
        return self._request("GET", f"{P}/subscriptions/{subscription_id}/fees",
                             headers=headers, params=params)

    # ---------------- Catalog / copies ----------------
    def create_catalog_item(self, payload, headers):
        return self._request("POST", f"{P}/catalog-items", payload, headers)

    def list_catalog_items(self, headers, params=None):
        return self._request("GET", f"{P}/catalog-items", headers=headers, params=params)

    def get_catalog_item(self, catalog_item_id, headers):
        return self._request("GET", f"{P}/catalog-items/{catalog_item_id}", headers=headers)

    def retire_catalog_item(self, catalog_item_id, headers):
        return self._request("POST", f"{P}/catalog-items/{catalog_item_id}/retire",
                             {}, headers)

    def mint_copy(self, catalog_item_id, payload, headers):
        return self._request("POST", f"{P}/catalog-items/{catalog_item_id}/copies",
                             payload, headers)

    def list_copies(self, catalog_item_id, headers, params=None):
        return self._request("GET", f"{P}/catalog-items/{catalog_item_id}/copies",
                             headers=headers, params=params)

    def list_catalog_item_wishlist_entries(self, catalog_item_id, headers, params=None):
        return self._request("GET", f"{P}/catalog-items/{catalog_item_id}/wishlist-entries",
                             headers=headers, params=params)

    def get_copy(self, copy_id, headers):
        return self._request("GET", f"{P}/copies/{copy_id}", headers=headers)

    def complete_sanitization(self, copy_id, headers):
        return self._request("POST", f"{P}/copies/{copy_id}/complete-sanitization",
                             {}, headers)

    def retire_copy(self, copy_id, headers):
        return self._request("POST", f"{P}/copies/{copy_id}/retire", {}, headers)

    def list_copy_wishlist_entries(self, copy_id, headers, params=None):
        return self._request("GET", f"{P}/copies/{copy_id}/wishlist-entries",
                             headers=headers, params=params)

    def list_copy_box_items(self, copy_id, headers, params=None):
        return self._request("GET", f"{P}/copies/{copy_id}/box-items",
                             headers=headers, params=params)

    # ---------------- Wishlist holds ----------------
    def cancel_wishlist_entry(self, entry_id, headers):
        return self._request("POST", f"{P}/wishlist-entries/{entry_id}/cancel",
                             {}, headers)

    def accept_hold(self, entry_id, payload, headers):
        return self._request("POST", f"{P}/wishlist-entries/{entry_id}/accept-hold",
                             payload, headers)

    # ---------------- Rotation boxes / items ----------------
    def get_rotation_box(self, box_id, headers):
        return self._request("GET", f"{P}/rotation-boxes/{box_id}", headers=headers)

    def add_box_item(self, box_id, payload, headers):
        return self._request("POST", f"{P}/rotation-boxes/{box_id}/items", payload, headers)

    def list_box_items(self, box_id, headers, params=None):
        return self._request("GET", f"{P}/rotation-boxes/{box_id}/items",
                             headers=headers, params=params)

    def ship_box(self, box_id, payload, headers):
        return self._request("POST", f"{P}/rotation-boxes/{box_id}/ship", payload, headers)

    def initiate_return(self, box_id, payload, headers):
        return self._request("POST", f"{P}/rotation-boxes/{box_id}/initiate-return",
                             payload, headers)

    def list_box_shipments(self, box_id, headers, params=None):
        return self._request("GET", f"{P}/rotation-boxes/{box_id}/shipments",
                             headers=headers, params=params)

    def inspect_box(self, box_id, payload, headers):
        return self._request("POST", f"{P}/rotation-boxes/{box_id}/inspect",
                             payload, headers)

    def close_box(self, box_id, headers):
        return self._request("POST", f"{P}/rotation-boxes/{box_id}/close", {}, headers)

    def list_box_fees(self, box_id, headers, params=None):
        return self._request("GET", f"{P}/rotation-boxes/{box_id}/fees",
                             headers=headers, params=params)

    # ---------------- Box items ----------------
    def get_box_item(self, box_item_id, headers):
        return self._request("GET", f"{P}/box-items/{box_item_id}", headers=headers)

    def list_box_item_fees(self, box_item_id, headers, params=None):
        return self._request("GET", f"{P}/box-items/{box_item_id}/fees",
                             headers=headers, params=params)

    def list_box_item_swaps(self, box_item_id, headers, params=None):
        return self._request("GET", f"{P}/box-items/{box_item_id}/swaps",
                             headers=headers, params=params)

    def swap_box_item(self, box_item_id, payload, headers):
        return self._request("POST", f"{P}/box-items/{box_item_id}/swap", payload, headers)

    def buyout_box_item(self, box_item_id, headers):
        return self._request("POST", f"{P}/box-items/{box_item_id}/buyout", {}, headers)

    def report_lost(self, box_item_id, payload, headers):
        return self._request("POST", f"{P}/box-items/{box_item_id}/report-lost",
                             payload, headers)

    # ---------------- Shipments ----------------
    def record_shipment_event(self, shipment_id, payload, headers):
        return self._request("POST", f"{P}/shipments/{shipment_id}/events",
                             payload, headers)

    # ---------------- Fees ----------------
    def pay_fee(self, fee_id, payload, headers):
        return self._request("POST", f"{P}/fees/{fee_id}/pay", payload, headers)

    def waive_fee(self, fee_id, payload, headers):
        return self._request("POST", f"{P}/fees/{fee_id}/waive", payload, headers)

    def dispute_fee(self, fee_id, payload, headers):
        return self._request("POST", f"{P}/fees/{fee_id}/dispute", payload, headers)

    def resolve_dispute(self, fee_id, payload, headers):
        return self._request("POST", f"{P}/fees/{fee_id}/resolve-dispute",
                             payload, headers)


api_client = ApiClient()
