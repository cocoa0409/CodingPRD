"""
Typed endpoint client for the Cruise Revenue Management & Cabin Inventory API.

One method per endpoint of the PRD endpoint table, plus the logical-clock
control endpoint. Every method returns the raw ``requests.Response`` so tests
can assert on status codes as well as bodies.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """HTTP surface of the cruise revenue API."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # -------------------------------------------------------------- sailings
    def create_sailing(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/sailings", payload, headers)

    def get_sailing(self, sailing_id: str, headers) -> requests.Response:
        return self._request("GET", f"/sailings/{sailing_id}", None, headers)

    def list_sailings(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/sailings", params, headers)

    def open_for_sale(self, sailing_id: str, headers) -> requests.Response:
        return self._request("POST", f"/sailings/{sailing_id}/open-for-sale", {}, headers)

    def suspend_sales(
        self, sailing_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/sailings/{sailing_id}/suspend-sales", payload, headers
        )

    def resume_sales(self, sailing_id: str, headers) -> requests.Response:
        return self._request("POST", f"/sailings/{sailing_id}/resume-sales", {}, headers)

    def close_inventory(self, sailing_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/sailings/{sailing_id}/close-inventory", {}, headers
        )

    def ops_run(self, sailing_id: str, headers) -> requests.Response:
        return self._request("POST", f"/sailings/{sailing_id}/ops-run", {}, headers)

    def revenue_summary(self, sailing_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"/sailings/{sailing_id}/revenue-summary", None, headers
        )

    # ------------------------------------------------------- cabin categories
    def create_cabin_category(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/cabin-categories", payload, headers)

    def get_cabin_category(self, category_id: str, headers) -> requests.Response:
        return self._request("GET", f"/cabin-categories/{category_id}", None, headers)

    def list_cabin_categories(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/cabin-categories", params, headers)

    # ---------------------------------------------------- sailing inventories
    def create_sailing_inventory(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", "/sailing-inventories", payload, headers)

    def get_sailing_inventory(self, inventory_id: str, headers) -> requests.Response:
        return self._request("GET", f"/sailing-inventories/{inventory_id}", None, headers)

    def list_sailing_inventories(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/sailing-inventories", params, headers)

    def patch_sailing_inventory(
        self, inventory_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/sailing-inventories/{inventory_id}", payload, headers
        )

    # ------------------------------------------------------------ fare rules
    def create_fare_rule(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/fare-rules", payload, headers)

    def get_fare_rule(self, fare_rule_id: str, headers) -> requests.Response:
        return self._request("GET", f"/fare-rules/{fare_rule_id}", None, headers)

    def list_fare_rules(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/fare-rules", params, headers)

    # ------------------------------------------------------------ promotions
    def create_promotion(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/promotions", payload, headers)

    def get_promotion(self, promotion_id: str, headers) -> requests.Response:
        return self._request("GET", f"/promotions/{promotion_id}", None, headers)

    def list_promotions(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/promotions", params, headers)

    def activate_promotion(self, promotion_id: str, headers) -> requests.Response:
        return self._request("POST", f"/promotions/{promotion_id}/activate", {}, headers)

    def withdraw_promotion(
        self, promotion_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/promotions/{promotion_id}/withdraw", payload, headers
        )

    # ----------------------------------------------------------- group blocks
    def create_group_block(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/group-blocks", payload, headers)

    def get_group_block(self, block_id: str, headers) -> requests.Response:
        return self._request("GET", f"/group-blocks/{block_id}", None, headers)

    def list_group_blocks(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/group-blocks", params, headers)

    def confirm_definite(
        self, block_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/group-blocks/{block_id}/confirm-definite", payload, headers
        )

    def review_group_block(self, block_id: str, headers) -> requests.Response:
        return self._request("POST", f"/group-blocks/{block_id}/review", {}, headers)

    def extend_review(
        self, block_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/group-blocks/{block_id}/extend-review", payload, headers
        )

    # ---------------------------------------------------------------- guests
    def create_guest(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/guests", payload, headers)

    def get_guest(self, guest_id: str, headers) -> requests.Response:
        return self._request("GET", f"/guests/{guest_id}", None, headers)

    def list_guests(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/guests", params, headers)

    # -------------------------------------------------------------- bookings
    def create_booking(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id: str, headers) -> requests.Response:
        return self._request("GET", f"/bookings/{booking_id}", None, headers)

    def list_bookings(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/bookings", params, headers)

    def confirm_booking(self, booking_id: str, headers) -> requests.Response:
        return self._request("POST", f"/bookings/{booking_id}/confirm", {}, headers)

    def post_payment(
        self, booking_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", f"/bookings/{booking_id}/payments", payload, headers)

    def list_payment_events(
        self, booking_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/bookings/{booking_id}/payment-events", params, headers
        )

    def cancel_booking(
        self, booking_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", f"/bookings/{booking_id}/cancel", payload, headers)

    def settle_cancellation(self, booking_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/bookings/{booking_id}/settle-cancellation", {}, headers
        )

    def assign_guarantee(
        self, booking_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/bookings/{booking_id}/assign-guarantee", payload, headers
        )

    # ---------------------------------------------------------- upgrade bids
    def submit_upgrade_bid(
        self, booking_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/bookings/{booking_id}/upgrade-bids", payload, headers
        )

    def get_upgrade_bid(self, bid_id: str, headers) -> requests.Response:
        return self._request("GET", f"/upgrade-bids/{bid_id}", None, headers)

    def list_upgrade_bids(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/upgrade-bids", params, headers)

    def counter_bid(self, bid_id: str, headers) -> requests.Response:
        return self._request("POST", f"/upgrade-bids/{bid_id}/counter", {}, headers)

    def rebid(self, bid_id: str, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"/upgrade-bids/{bid_id}/rebid", payload, headers)

    def accept_bid(self, bid_id: str, headers) -> requests.Response:
        return self._request("POST", f"/upgrade-bids/{bid_id}/accept", {}, headers)

    def decline_bid(
        self, bid_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", f"/upgrade-bids/{bid_id}/decline", payload, headers)

    # ------------------------------------------------------ itinerary changes
    def create_itinerary_change(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", "/itinerary-changes", payload, headers)

    def get_itinerary_change(self, change_id: str, headers) -> requests.Response:
        return self._request("GET", f"/itinerary-changes/{change_id}", None, headers)

    def list_itinerary_changes(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/itinerary-changes", params, headers)

    def publish_itinerary_change(self, change_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/itinerary-changes/{change_id}/publish", {}, headers
        )
