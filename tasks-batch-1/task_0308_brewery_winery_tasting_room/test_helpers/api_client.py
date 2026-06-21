"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test clock ───────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Winery ───────────────────────────────────────
    def create_winery(self, payload, headers):
        return self._request("POST", "/wineries", payload, headers)

    def get_winery(self, winery_id, headers):
        return self._request("GET", f"/wineries/{winery_id}", headers=headers)

    def transition_winery(self, winery_id, payload, headers):
        return self._request("POST", f"/wineries/{winery_id}/transitions", payload, headers)

    # ─── ProductionBatch ──────────────────────────────
    def create_batch(self, payload, headers):
        return self._request("POST", "/batches", payload, headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/batches/{batch_id}", headers=headers)

    def transition_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/batches/{batch_id}/transitions", payload, headers)

    def create_bottling_run(self, batch_id, payload, headers):
        return self._request("POST", f"/batches/{batch_id}/bottling-runs", payload, headers)

    # ─── Product ──────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def transition_product(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/transitions", payload, headers)

    # ─── AllocationRelease ────────────────────────────
    def create_release(self, payload, headers):
        return self._request("POST", "/releases", payload, headers)

    def list_releases(self, headers, params=None):
        return self._request("GET", "/releases", headers=headers, params=params)

    def get_release(self, release_id, headers):
        return self._request("GET", f"/releases/{release_id}", headers=headers)

    def transition_release(self, release_id, payload, headers):
        return self._request("POST", f"/releases/{release_id}/transitions", payload, headers)

    # ─── Member ───────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def transition_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/transitions", payload, headers)

    # ─── Membership ───────────────────────────────────
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def transition_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/transitions", payload, headers)

    def set_membership_billing(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/billing", payload, headers)

    # ─── Shipment ─────────────────────────────────────
    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def transition_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/transitions", payload, headers)

    # ─── TastingOrder ─────────────────────────────────
    def create_tasting_order(self, payload, headers):
        return self._request("POST", "/tasting-orders", payload, headers)

    def list_tasting_orders(self, headers, params=None):
        return self._request("GET", "/tasting-orders", headers=headers, params=params)

    def get_tasting_order(self, order_id, headers):
        return self._request("GET", f"/tasting-orders/{order_id}", headers=headers)

    def transition_tasting_order(self, order_id, payload, headers):
        return self._request("POST", f"/tasting-orders/{order_id}/transitions", payload, headers)

    # ─── Reservation ──────────────────────────────────
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def transition_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/transitions", payload, headers)

    # ─── DistributionOrder ────────────────────────────
    def create_distribution_order(self, payload, headers):
        return self._request("POST", "/distribution-orders", payload, headers)

    def list_distribution_orders(self, headers, params=None):
        return self._request("GET", "/distribution-orders", headers=headers, params=params)

    def get_distribution_order(self, dist_order_id, headers):
        return self._request("GET", f"/distribution-orders/{dist_order_id}", headers=headers)

    def transition_distribution_order(self, dist_order_id, payload, headers):
        return self._request("POST", f"/distribution-orders/{dist_order_id}/transitions", payload, headers)

    # ─── ComplianceLedgerEntry (read-only) ────────────
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)


api_client = ApiClient()
