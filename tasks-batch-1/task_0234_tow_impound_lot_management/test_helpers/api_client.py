"""API client: one method per endpoint defined in the PRD (Tow & Impound Lot Management)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clock (test-driving) ────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set", {"to_iso8601": to_iso8601}, headers)

    # ─── ImpoundLot ──────────────────────────────────────────────────────────
    def create_impound_lot(self, payload, headers):
        return self._request("POST", "/impound-lots", payload, headers)

    def get_impound_lot(self, lot_id, headers):
        return self._request("GET", f"/impound-lots/{lot_id}", headers=headers)

    def suspend_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/impound-lots/{lot_id}/suspend", payload, headers)

    def dispatch_rotation(self, lot_id, payload, headers):
        return self._request("POST", f"/impound-lots/{lot_id}/dispatch-rotation", payload, headers)

    # ─── TowProvider ─────────────────────────────────────────────────────────
    def create_tow_provider(self, payload, headers):
        return self._request("POST", "/tow-providers", payload, headers)

    def get_tow_provider(self, provider_id, headers):
        return self._request("GET", f"/tow-providers/{provider_id}", headers=headers)

    def suspend_provider(self, provider_id, headers):
        return self._request("POST", f"/tow-providers/{provider_id}/suspend", {}, headers)

    def reinstate_provider(self, provider_id, headers):
        return self._request("POST", f"/tow-providers/{provider_id}/reinstate", {}, headers)

    # ─── Lienholder ──────────────────────────────────────────────────────────
    def create_lienholder(self, payload, headers):
        return self._request("POST", "/lienholders", payload, headers)

    def get_lienholder(self, lienholder_id, headers):
        return self._request("GET", f"/lienholders/{lienholder_id}", headers=headers)

    # ─── RotationAssignment ──────────────────────────────────────────────────
    def get_rotation_assignment(self, assignment_id, headers):
        return self._request("GET", f"/rotation-assignments/{assignment_id}", headers=headers)

    def list_rotation_assignments(self, headers, params=None):
        return self._request("GET", "/rotation-assignments", headers=headers, params=params)

    def accept_rotation(self, assignment_id, headers):
        return self._request("POST", f"/rotation-assignments/{assignment_id}/accept", {}, headers)

    def decline_rotation(self, assignment_id, headers):
        return self._request("POST", f"/rotation-assignments/{assignment_id}/decline", {}, headers)

    def expire_rotation(self, assignment_id, headers):
        return self._request("POST", f"/rotation-assignments/{assignment_id}/expire", {}, headers)

    def cancel_rotation(self, assignment_id, headers):
        return self._request("POST", f"/rotation-assignments/{assignment_id}/cancel", {}, headers)

    # ─── TowOrder ────────────────────────────────────────────────────────────
    def create_tow_order(self, payload, headers):
        return self._request("POST", "/tow-orders", payload, headers)

    def get_tow_order(self, order_id, headers):
        return self._request("GET", f"/tow-orders/{order_id}", headers=headers)

    def list_tow_orders(self, headers, params=None):
        return self._request("GET", "/tow-orders", headers=headers, params=params)

    def store_order(self, order_id, headers):
        return self._request("POST", f"/tow-orders/{order_id}/store", {}, headers)

    def authorize_release(self, order_id, headers):
        return self._request("POST", f"/tow-orders/{order_id}/authorize-release", {}, headers)

    def lapse_authorization(self, order_id, headers):
        return self._request("POST", f"/tow-orders/{order_id}/lapse-authorization", {}, headers)

    def mark_auction_eligible(self, order_id, headers):
        return self._request("POST", f"/tow-orders/{order_id}/mark-auction-eligible", {}, headers)

    def reclaim_order(self, order_id, headers):
        return self._request("POST", f"/tow-orders/{order_id}/reclaim", {}, headers)

    def void_order(self, order_id, headers):
        return self._request("POST", f"/tow-orders/{order_id}/void", {}, headers)

    def place_hold(self, order_id, payload, headers):
        return self._request("POST", f"/tow-orders/{order_id}/place-hold", payload, headers)

    def lift_hold(self, order_id, headers):
        return self._request("POST", f"/tow-orders/{order_id}/lift-hold", {}, headers)

    def list_ledger_entries(self, order_id, headers, params=None):
        return self._request("GET", f"/tow-orders/{order_id}/ledger-entries", headers=headers, params=params)

    def record_payment(self, order_id, payload, headers):
        return self._request("POST", f"/tow-orders/{order_id}/payments", payload, headers)

    # ─── Notification ────────────────────────────────────────────────────────
    def create_notification(self, order_id, payload, headers):
        return self._request("POST", f"/tow-orders/{order_id}/notifications", payload, headers)

    def list_notifications(self, order_id, headers, params=None):
        return self._request("GET", f"/tow-orders/{order_id}/notifications", headers=headers, params=params)

    def get_notification(self, order_id, notification_id, headers):
        return self._request("GET", f"/tow-orders/{order_id}/notifications/{notification_id}", headers=headers)

    def send_notification(self, order_id, notification_id, headers):
        return self._request("POST", f"/tow-orders/{order_id}/notifications/{notification_id}/send", {}, headers)

    def confirm_delivery(self, order_id, notification_id, headers):
        return self._request("POST", f"/tow-orders/{order_id}/notifications/{notification_id}/confirm-delivery", {}, headers)

    def mark_returned(self, order_id, notification_id, headers):
        return self._request("POST", f"/tow-orders/{order_id}/notifications/{notification_id}/mark-returned", {}, headers)

    def mark_undeliverable(self, order_id, notification_id, headers):
        return self._request("POST", f"/tow-orders/{order_id}/notifications/{notification_id}/mark-undeliverable", {}, headers)

    # ─── InventoryItem ───────────────────────────────────────────────────────
    def create_inventory_item(self, order_id, payload, headers):
        return self._request("POST", f"/tow-orders/{order_id}/inventory-items", payload, headers)

    def list_inventory_items(self, order_id, headers, params=None):
        return self._request("GET", f"/tow-orders/{order_id}/inventory-items", headers=headers, params=params)

    # ─── FeeWaiver ───────────────────────────────────────────────────────────
    def create_fee_waiver(self, order_id, payload, headers):
        return self._request("POST", f"/tow-orders/{order_id}/fee-waivers", payload, headers)

    def list_fee_waivers(self, order_id, headers, params=None):
        return self._request("GET", f"/tow-orders/{order_id}/fee-waivers", headers=headers, params=params)

    def get_fee_waiver(self, order_id, waiver_id, headers):
        return self._request("GET", f"/tow-orders/{order_id}/fee-waivers/{waiver_id}", headers=headers)

    def start_review(self, order_id, waiver_id, headers):
        return self._request("POST", f"/tow-orders/{order_id}/fee-waivers/{waiver_id}/start-review", {}, headers)

    def approve_waiver(self, order_id, waiver_id, headers):
        return self._request("POST", f"/tow-orders/{order_id}/fee-waivers/{waiver_id}/approve", {}, headers)

    def deny_waiver(self, order_id, waiver_id, headers):
        return self._request("POST", f"/tow-orders/{order_id}/fee-waivers/{waiver_id}/deny", {}, headers)

    def withdraw_waiver(self, order_id, waiver_id, headers):
        return self._request("POST", f"/tow-orders/{order_id}/fee-waivers/{waiver_id}/withdraw", {}, headers)

    # ─── ReleaseRecord ───────────────────────────────────────────────────────
    def create_release_record(self, order_id, payload, headers):
        return self._request("POST", f"/tow-orders/{order_id}/release-records", payload, headers)

    def list_release_records(self, order_id, headers, params=None):
        return self._request("GET", f"/tow-orders/{order_id}/release-records", headers=headers, params=params)

    # ─── Auction ─────────────────────────────────────────────────────────────
    def create_auction(self, payload, headers):
        return self._request("POST", "/auctions", payload, headers)

    def get_auction(self, auction_id, headers):
        return self._request("GET", f"/auctions/{auction_id}", headers=headers)

    def list_auctions(self, headers, params=None):
        return self._request("GET", "/auctions", headers=headers, params=params)

    def list_auction_tow_orders(self, auction_id, headers, params=None):
        return self._request("GET", f"/auctions/{auction_id}/tow-orders", headers=headers, params=params)

    def open_auction(self, auction_id, headers):
        return self._request("POST", f"/auctions/{auction_id}/open", {}, headers)

    def sweep_order(self, auction_id, payload, headers):
        return self._request("POST", f"/auctions/{auction_id}/sweep", payload, headers)

    def record_sale(self, auction_id, payload, headers):
        return self._request("POST", f"/auctions/{auction_id}/record-sale", payload, headers)

    def void_sale(self, auction_id, payload, headers):
        return self._request("POST", f"/auctions/{auction_id}/void-sale", payload, headers)

    def settle_auction(self, auction_id, headers):
        return self._request("POST", f"/auctions/{auction_id}/settle", {}, headers)

    def cancel_auction(self, auction_id, headers):
        return self._request("POST", f"/auctions/{auction_id}/cancel", {}, headers)


api_client = ApiClient()
