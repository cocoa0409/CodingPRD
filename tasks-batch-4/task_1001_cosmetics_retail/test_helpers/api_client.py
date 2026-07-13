"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        self._harden_transport()

    def _harden_transport(self):
        """Retry only at the transport layer — never on an HTTP status.

        Under `--isolation per-test-server` the runner SIGKILLs the server and
        reboots it before every test, and it hands the server a port drawn from
        the OS *ephemeral* range (it calls bind(host, 0) and reuses whatever the
        kernel returns). The pytest client's own outbound sockets draw their
        source ports from that very same sequential pool.

        So a request issued during the brief window in which the port has no
        listener can be assigned a source port equal to the destination port. On
        loopback that is a TCP simultaneous open: the socket connects to itself,
        echoes our request line back, and http.client parses "POST /orders
        HTTP/1.1" as the status line -> BadStatusLine. The request never reaches
        the app, so this is pure transport noise, not an API defect.

        `status_forcelist` stays empty, so no 4xx/5xx response is ever retried —
        the error_id / status assertions in the suite see exactly the first
        response the server sent. Each retry dials a fresh connection (and thus a
        fresh source port), which is what clears a self-connect. A server that is
        genuinely down or broken fails every attempt, so this can never mask an
        implementation bug.
        """
        retry = Retry(
            total=5,
            connect=5,
            read=5,              # BadStatusLine surfaces as a urllib3 ProtocolError
            status=0,            # never retry on an HTTP status code
            status_forcelist=(),
            allowed_methods=None,  # retry POST too: the self-connect never delivered it
            backoff_factor=0.2,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    # ── Logical clock (PRD §2.4) ──────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ── Stores (PRD §3.1) ─────────────────────────────
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def update_store(self, store_id, payload, headers):
        return self._request("PATCH", f"/stores/{store_id}", payload, headers)

    # ── Products & variants (PRD §3.1) ────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def create_variant(self, product_id, payload, headers):
        return self._request(
            "POST", f"/products/{product_id}/variants", payload, headers
        )

    def get_variant(self, variant_id, headers):
        return self._request("GET", f"/variants/{variant_id}", headers=headers)

    def list_variants(self, headers, params=None):
        return self._request("GET", "/variants", headers=headers, params=params)

    def update_variant(self, variant_id, payload, headers):
        return self._request("PATCH", f"/variants/{variant_id}", payload, headers)

    # ── Shade finder (PRD §3.3) ───────────────────────
    def recommend_shade(self, payload, headers):
        return self._request("POST", "/shade-recommendations", payload, headers)

    # ── Inventory lots & testers (PRD §3.2) ───────────
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/inventory-lots", payload, headers)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/inventory-lots", headers=headers, params=params)

    def convert_testers(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/inventory-lots/{lot_id}/tester-conversions", payload, headers
        )

    # ── Customers & loyalty (PRD §3.4) ────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def tier_checkpoint(self, customer_id, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/tier-checkpoint", {}, headers
        )

    def get_points_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/points-ledger/{entry_id}", headers=headers)

    def list_points_ledger(self, headers, params=None):
        return self._request("GET", "/points-ledger", headers=headers, params=params)

    # ── Promotions (PRD §3.5) ─────────────────────────
    def create_promotion(self, payload, headers):
        return self._request("POST", "/promotions", payload, headers)

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"/promotions/{promotion_id}", headers=headers)

    def list_promotions(self, headers, params=None):
        return self._request("GET", "/promotions", headers=headers, params=params)

    # ── Orders (PRD §3.5 – §3.7) ──────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def reserve_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/reserve", {}, headers)

    def pay_order(self, order_id, action, headers):
        return self._request(
            "POST", f"/orders/{order_id}/payments", {"action": action}, headers
        )

    def fulfill_order(self, order_id, action, headers):
        return self._request(
            "POST", f"/orders/{order_id}/fulfillment", {"action": action}, headers
        )

    def cancel_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/orders/{order_id}/cancel", payload or {}, headers
        )

    # ── Artists & service bookings (PRD §3.8) ─────────
    def create_artist(self, payload, headers):
        return self._request("POST", "/artists", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"/artists/{artist_id}", headers=headers)

    def list_artists(self, headers, params=None):
        return self._request("GET", "/artists", headers=headers, params=params)

    def create_service_booking(self, payload, headers):
        return self._request("POST", "/service-bookings", payload, headers)

    def get_service_booking(self, booking_id, headers):
        return self._request("GET", f"/service-bookings/{booking_id}", headers=headers)

    def list_service_bookings(self, headers, params=None):
        return self._request(
            "GET", "/service-bookings", headers=headers, params=params
        )

    def reschedule_booking(self, booking_id, proposed_start_at, headers):
        return self._request(
            "POST",
            f"/service-bookings/{booking_id}/reschedule",
            {"proposed_start_at": proposed_start_at},
            headers,
        )

    def confirm_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/service-bookings/{booking_id}/confirm", {}, headers
        )

    def complete_booking(self, booking_id, outcome, headers):
        return self._request(
            "POST",
            f"/service-bookings/{booking_id}/complete",
            {"outcome": outcome},
            headers,
        )

    def cancel_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/service-bookings/{booking_id}/cancel", {}, headers
        )

    # ── Returns (PRD §3.9) ────────────────────────────
    def create_return_request(self, payload, headers):
        return self._request("POST", "/return-requests", payload, headers)

    def get_return_request(self, return_id, headers):
        return self._request("GET", f"/return-requests/{return_id}", headers=headers)

    def list_return_requests(self, headers, params=None):
        return self._request("GET", "/return-requests", headers=headers, params=params)

    def decide_return_request(self, return_id, payload, headers):
        return self._request(
            "POST", f"/return-requests/{return_id}/decision", payload, headers
        )

    # ── Raw escape hatch (used only for the no-auth-header test) ──
    def raw_get(self, path, headers):
        return self._request("GET", path, headers=headers)


api_client = ApiClient()
