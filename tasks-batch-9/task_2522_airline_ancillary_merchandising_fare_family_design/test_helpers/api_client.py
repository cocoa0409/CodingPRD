"""One method per API endpoint.

Every method returns the raw HTTP response so a test can assert on the status
code as well as the body.  Read endpoints accept ``params`` for filters and
pagination; write endpoints take the JSON payload.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed access to the airline ancillary merchandising API."""

    # -----------------------------------------------------------------
    # Logical clock
    # -----------------------------------------------------------------
    def set_current_utc(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -----------------------------------------------------------------
    # Ancillary products
    # -----------------------------------------------------------------
    def create_ancillary_product(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/ancillary-products", payload, headers)

    def get_ancillary_product(self, product_id: str, headers=None):
        return self._request("GET", f"/ancillary-products/{product_id}", None, headers)

    def list_ancillary_products(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/ancillary-products", params, headers)

    def list_product_family_attributes(
        self, product_id: str, headers=None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/ancillary-products/{product_id}/family-attributes", params, headers
        )

    # -----------------------------------------------------------------
    # Fare families
    # -----------------------------------------------------------------
    def create_fare_family(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/fare-families", payload, headers)

    def get_fare_family(self, family_id: str, headers=None):
        return self._request("GET", f"/fare-families/{family_id}", None, headers)

    def list_fare_families(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/fare-families", params, headers)

    def submit_fare_family(self, family_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"/fare-families/{family_id}/submit", payload or {}, headers
        )

    def review_fare_family(self, family_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/fare-families/{family_id}/review-decision", payload, headers
        )

    def change_fare_family_status(
        self, family_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/fare-families/{family_id}/status-change", payload, headers
        )

    def update_fare_family(self, family_id: str, payload: Dict[str, Any], headers=None):
        return self._request("PATCH", f"/fare-families/{family_id}", payload, headers)

    def list_family_attributes_of_family(
        self, family_id: str, headers=None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/fare-families/{family_id}/attributes", params, headers
        )

    def add_family_attribute(
        self, family_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/fare-families/{family_id}/attributes", payload, headers
        )

    # -----------------------------------------------------------------
    # Family attributes
    # -----------------------------------------------------------------
    def get_family_attribute(self, attribute_id: str, headers=None):
        return self._request("GET", f"/family-attributes/{attribute_id}", None, headers)

    def list_family_attributes(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/family-attributes", params, headers)

    def update_family_attribute(
        self, attribute_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "PATCH", f"/family-attributes/{attribute_id}", payload, headers
        )

    # -----------------------------------------------------------------
    # Flights
    # -----------------------------------------------------------------
    def create_flight(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/flights", payload, headers)

    def get_flight(self, flight_id: str, headers=None):
        return self._request("GET", f"/flights/{flight_id}", None, headers)

    def list_flights(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/flights", params, headers)

    def advance_flight_phase(self, flight_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"/flights/{flight_id}/phase-advance", payload or {}, headers
        )

    def post_demand_snapshot(
        self, flight_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/flights/{flight_id}/demand-snapshot", payload, headers
        )

    # -----------------------------------------------------------------
    # Seat inventory segments
    # -----------------------------------------------------------------
    def create_seat_segment(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/seat-segments", payload, headers)

    def get_seat_segment(self, segment_id: str, headers=None):
        return self._request("GET", f"/seat-segments/{segment_id}", None, headers)

    def list_seat_segments(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/seat-segments", params, headers)

    # -----------------------------------------------------------------
    # Distribution channels
    # -----------------------------------------------------------------
    def create_distribution_channel(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/distribution-channels", payload, headers)

    def get_distribution_channel(self, channel_id: str, headers=None):
        return self._request(
            "GET", f"/distribution-channels/{channel_id}", None, headers
        )

    def list_distribution_channels(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/distribution-channels", params, headers)

    # -----------------------------------------------------------------
    # Channel publications
    # -----------------------------------------------------------------
    def create_channel_publication(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/channel-publications", payload, headers)

    def get_channel_publication(self, publication_id: str, headers=None):
        return self._request(
            "GET", f"/channel-publications/{publication_id}", None, headers
        )

    def list_channel_publications(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/channel-publications", params, headers)

    def resync_channel_publication(self, publication_id: str, payload=None, headers=None):
        return self._request(
            "POST",
            f"/channel-publications/{publication_id}/resync",
            payload or {},
            headers,
        )

    # -----------------------------------------------------------------
    # Bookings
    # -----------------------------------------------------------------
    def create_booking(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id: str, headers=None):
        return self._request("GET", f"/bookings/{booking_id}", None, headers)

    def list_bookings(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/bookings", params, headers)

    def issue_disclosure(self, booking_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"/bookings/{booking_id}/disclosure", payload or {}, headers
        )

    def acknowledge_disclosure(
        self, booking_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/bookings/{booking_id}/disclosure-ack", payload, headers
        )

    def ticket_booking(self, booking_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"/bookings/{booking_id}/ticket", payload or {}, headers
        )

    def open_booking_change(self, booking_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"/bookings/{booking_id}/change-open", payload or {}, headers
        )

    def settle_booking_change(
        self, booking_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/bookings/{booking_id}/change-settle", payload, headers
        )

    def cancel_booking(self, booking_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"/bookings/{booking_id}/cancel", payload or {}, headers
        )

    def create_offer_session(self, booking_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/bookings/{booking_id}/offer-sessions", payload, headers
        )

    # -----------------------------------------------------------------
    # Ancillary offers
    # -----------------------------------------------------------------
    def get_ancillary_offer(self, offer_id: str, headers=None):
        return self._request("GET", f"/ancillary-offers/{offer_id}", None, headers)

    def list_ancillary_offers(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/ancillary-offers", params, headers)

    def accept_offer(self, offer_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/ancillary-offers/{offer_id}/accept", payload, headers
        )

    def decline_offer(self, offer_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"/ancillary-offers/{offer_id}/decline", payload or {}, headers
        )

    # -----------------------------------------------------------------
    # Seat assignments
    # -----------------------------------------------------------------
    def create_seat_assignment(
        self, booking_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/bookings/{booking_id}/seat-assignments", payload, headers
        )

    def get_seat_assignment(self, assignment_id: str, headers=None):
        return self._request("GET", f"/seat-assignments/{assignment_id}", None, headers)

    def list_seat_assignments(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/seat-assignments", params, headers)

    def release_seat_assignment(
        self, assignment_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"/seat-assignments/{assignment_id}/release", payload, headers
        )

    # -----------------------------------------------------------------
    # Irregular operations waivers
    # -----------------------------------------------------------------
    def declare_irops_waiver(self, flight_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/flights/{flight_id}/irops-waivers", payload, headers
        )

    def get_irops_waiver(self, waiver_id: str, headers=None):
        return self._request("GET", f"/irops-waivers/{waiver_id}", None, headers)

    def list_irops_waivers(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/irops-waivers", params, headers)

    def list_flight_irops_waivers(
        self, flight_id: str, headers=None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/flights/{flight_id}/irops-waivers", params, headers
        )

    def rescind_irops_waiver(self, waiver_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/irops-waivers/{waiver_id}/rescind", payload, headers
        )

    # -----------------------------------------------------------------
    # Revenue ledger
    # -----------------------------------------------------------------
    def get_revenue_entry(self, entry_id: str, headers=None):
        return self._request("GET", f"/revenue-entries/{entry_id}", None, headers)

    def list_revenue_entries(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/revenue-entries", params, headers)

    def list_booking_revenue_entries(
        self, booking_id: str, headers=None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/bookings/{booking_id}/revenue-entries", params, headers
        )
