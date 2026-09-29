"""Thin, one-method-per-endpoint client for the RV share marketplace API.

Every method below corresponds to exactly one row of the PRD's endpoint table.
Nothing here interprets a response; tests do that with the framework
validators.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .constants import API_PREFIX

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]

# The runner restarts the API server on the same port before every test, which
# leaves the keep-alive socket in this process' connection pool pointing at a
# process that no longer exists. Reusing it surfaces as
# ConnectionResetError(104) on the first call a test makes, which has nothing to
# do with the behaviour under test. Both guards below are purely transport-level.
_TRANSPORT_RETRY = Retry(
    total=4,
    connect=4,
    read=4,
    status=0,
    allowed_methods=False,  # retry every verb, not just the idempotent ones
    backoff_factor=0.05,
    raise_on_status=False,
)


class ApiClient(GenericApiClient):
    """Endpoint-per-method wrapper. Paths carry the marketplace prefix."""

    def __init__(self, base_url: Optional[str] = None):
        super().__init__(base_url)
        self._mount_transport_retries()

    def _mount_transport_retries(self) -> None:
        adapter = HTTPAdapter(max_retries=_TRANSPORT_RETRY)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def reset_session(self) -> None:
        """Drop every pooled socket and start from a clean connection pool."""
        try:
            self.session.close()
        except Exception:  # pragma: no cover - best-effort teardown
            pass
        self.session = requests.Session()
        self._mount_transport_retries()

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ------------------------------------------------------------------
    # Owners
    # ------------------------------------------------------------------
    def create_owner(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/owners", payload, headers)

    def get_owner(self, owner_id: str, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/owners/{owner_id}", None, headers)

    def adjust_owner_penalty_points(
        self, owner_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/owners/{owner_id}/penalty-adjustments", payload, headers
        )

    # ------------------------------------------------------------------
    # Renters
    # ------------------------------------------------------------------
    def create_renter(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/renters", payload, headers)

    def get_renter(self, renter_id: str, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/renters/{renter_id}", None, headers)

    def adjust_renter_wallet(
        self, renter_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/renters/{renter_id}/wallet-adjustments", payload, headers
        )

    def adjust_renter_penalty_points(
        self, renter_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/renters/{renter_id}/penalty-adjustments",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Renter qualifications
    # ------------------------------------------------------------------
    def create_renter_qualification(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/renter-qualifications", payload, headers
        )

    def get_renter_qualification(self, qualification_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/renter-qualifications/{qualification_id}", None, headers
        )

    def list_renter_qualifications(self, params: Payload = None, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/renter-qualifications", params, headers
        )

    # ------------------------------------------------------------------
    # Protection plans / cancellation policies / pricing seasons
    # ------------------------------------------------------------------
    def create_protection_plan(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/protection-plans", payload, headers)

    def create_cancellation_policy(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/cancellation-policies", payload, headers
        )

    def create_pricing_season(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/pricing-seasons", payload, headers)

    def list_pricing_seasons(self, params: Payload = None, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/pricing-seasons", params, headers)

    # ------------------------------------------------------------------
    # Campgrounds
    # ------------------------------------------------------------------
    def create_campground(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/campgrounds", payload, headers)

    def get_campground(self, campground_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/campgrounds/{campground_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Listings
    # ------------------------------------------------------------------
    def create_listing(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/listings", payload, headers)

    def get_listing(self, listing_id: str, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/listings/{listing_id}", None, headers)

    def list_listings(self, params: Payload = None, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/listings", params, headers)

    def submit_listing_for_review(self, listing_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/listings/{listing_id}/submit-for-review", {}, headers
        )

    def decide_listing(self, listing_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/listings/{listing_id}/decision", payload, headers
        )

    def suspend_listing(self, listing_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/listings/{listing_id}/suspend", payload, headers
        )

    def reinstate_listing(self, listing_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/listings/{listing_id}/reinstate", {}, headers
        )

    def archive_listing(self, listing_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/listings/{listing_id}/archive", {}, headers
        )

    def get_pricing_guidance(self, listing_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/listings/{listing_id}/pricing-guidance", None, headers
        )

    # ------------------------------------------------------------------
    # Vehicle documents
    # ------------------------------------------------------------------
    def create_vehicle_document(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/vehicle-documents", payload, headers)

    def get_vehicle_document(self, document_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/vehicle-documents/{document_id}", None, headers
        )

    def list_vehicle_documents(self, params: Payload = None, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/vehicle-documents", params, headers)

    def verify_vehicle_document(self, document_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/vehicle-documents/{document_id}/verify", {}, headers
        )

    # ------------------------------------------------------------------
    # Bookings
    # ------------------------------------------------------------------
    def create_booking(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/bookings", payload, headers)

    def get_booking(self, booking_id: str, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/bookings/{booking_id}", None, headers)

    def list_bookings(self, params: Payload = None, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/bookings", params, headers)

    def approve_booking(self, booking_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/bookings/{booking_id}/approve", {}, headers
        )

    def confirm_booking(self, booking_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/bookings/{booking_id}/confirm", {}, headers
        )

    def start_booking(self, booking_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/bookings/{booking_id}/start", {}, headers
        )

    def return_booking(self, booking_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/bookings/{booking_id}/return", {}, headers
        )

    def settle_booking(self, booking_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/bookings/{booking_id}/settle", {}, headers
        )

    def reverse_settlement(
        self, booking_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/bookings/{booking_id}/settlement/reverse",
            payload,
            headers,
        )

    def cancel_booking(self, booking_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/bookings/{booking_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Delivery assignments
    # ------------------------------------------------------------------
    def create_delivery_assignment(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/delivery-assignments", payload, headers
        )

    def get_delivery_assignment(self, assignment_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/delivery-assignments/{assignment_id}", None, headers
        )

    def list_delivery_assignments(self, params: Payload = None, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/delivery-assignments", params, headers
        )

    def void_delivery_assignment(
        self, assignment_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/delivery-assignments/{assignment_id}/void",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Meter readings
    # ------------------------------------------------------------------
    def create_meter_reading(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/meter-readings", payload, headers)

    def get_meter_reading(self, reading_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/meter-readings/{reading_id}", None, headers
        )

    def list_meter_readings(self, params: Payload = None, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/meter-readings", params, headers)

    # ------------------------------------------------------------------
    # Trip photos
    # ------------------------------------------------------------------
    def create_trip_photo(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/trip-photos", payload, headers)

    def get_trip_photo(self, photo_id: str, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/trip-photos/{photo_id}", None, headers)

    def list_trip_photos(self, params: Payload = None, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/trip-photos", params, headers)

    # ------------------------------------------------------------------
    # Damage claims
    # ------------------------------------------------------------------
    def create_damage_claim(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{API_PREFIX}/damage-claims", payload, headers)

    def get_damage_claim(self, claim_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/damage-claims/{claim_id}", None, headers
        )

    def list_damage_claims(self, params: Payload = None, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/damage-claims", params, headers)

    def start_claim_review(self, claim_id: str, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/damage-claims/{claim_id}/start-review", {}, headers
        )

    def request_claim_info(self, claim_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/damage-claims/{claim_id}/request-info", payload, headers
        )

    def respond_to_claim_info(
        self, claim_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/damage-claims/{claim_id}/respond", payload, headers
        )

    def adjudicate_claim(self, claim_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/damage-claims/{claim_id}/adjudicate", payload, headers
        )

    def withdraw_claim(self, claim_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{API_PREFIX}/damage-claims/{claim_id}/withdraw", payload, headers
        )

    # ------------------------------------------------------------------
    # Ledger entries
    # ------------------------------------------------------------------
    def get_ledger_entry(self, entry_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{API_PREFIX}/ledger-entries/{entry_id}", None, headers
        )

    def list_ledger_entries(self, params: Payload = None, headers: Headers = None):
        return self._request("GET", f"{API_PREFIX}/ledger-entries", params, headers)


api_client = ApiClient()
