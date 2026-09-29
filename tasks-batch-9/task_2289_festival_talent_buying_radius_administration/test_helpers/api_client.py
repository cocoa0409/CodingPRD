"""One method per endpoint of the festival talent-buying API.

Every path is rooted at the `/festival-ops` prefix. Methods return the raw
response object so tests can assert status codes as well as bodies.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the festival talent-buying API."""

    # ------------------------------------------------------------ logical clock
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    # ---------------------------------------------------------------- festivals
    def create_festival(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/festivals", payload, headers)

    def get_festival(self, festival_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/festivals/{festival_id}", None, headers)

    def allocate_tiers(
        self, festival_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/festivals/{festival_id}/allocate-tiers", payload, headers
        )

    def advance_phase(
        self, festival_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/festivals/{festival_id}/advance-phase", payload, headers
        )

    def get_budget_summary(self, festival_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/festivals/{festival_id}/budget-summary", None, headers
        )

    def list_festival_budget_tiers(
        self, festival_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/festivals/{festival_id}/budget-tiers", params, headers
        )

    def list_festival_stages(
        self, festival_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/festivals/{festival_id}/stages", params, headers
        )

    # ------------------------------------------------------------- budget tiers
    def create_budget_tier(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/budget-tiers", payload, headers)

    def get_budget_tier(self, tier_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/budget-tiers/{tier_id}", None, headers)

    # ------------------------------------------------------------------- stages
    def create_stage(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/stages", payload, headers)

    def get_stage(self, stage_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/stages/{stage_id}", None, headers)

    # ------------------------------------------------------------------ artists
    def create_artist(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/artists", payload, headers)

    def get_artist(self, artist_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/artists/{artist_id}", None, headers)

    def get_radius_risk(
        self, artist_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/artists/{artist_id}/radius-risk", params, headers
        )

    # ------------------------------------------------------------------- offers
    def create_offer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/offers", payload, headers)

    def get_offer(self, offer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/offers/{offer_id}", None, headers)

    def list_offers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/offers", params, headers)

    def issue_offer(
        self, offer_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/offers/{offer_id}/issue", payload or {}, headers
        )

    def counter_offer(
        self, offer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/offers/{offer_id}/counter", payload, headers
        )

    def revise_offer(
        self, offer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/offers/{offer_id}/revise", payload, headers
        )

    def accept_offer(
        self, offer_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/offers/{offer_id}/accept", payload or {}, headers
        )

    def decline_offer(
        self, offer_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/offers/{offer_id}/decline", payload or {}, headers
        )

    def sweep_expired_offers(
        self, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/offers/sweep-expired", payload or {}, headers
        )

    # ----------------------------------------------------------- radius clauses
    def get_radius_clause(self, clause_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/radius-clauses/{clause_id}", None, headers
        )

    def list_radius_clauses(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/radius-clauses", params, headers)

    def request_waiver(
        self, clause_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/radius-clauses/{clause_id}/waiver-request", payload, headers
        )

    def decide_waiver(
        self, clause_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/radius-clauses/{clause_id}/waiver-decision",
            payload,
            headers,
        )

    # ---------------------------------------------------- competing performances
    def create_competing_performance(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/competing-performances", payload, headers
        )

    def get_competing_performance(self, performance_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/competing-performances/{performance_id}", None, headers
        )

    def list_competing_performances(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/competing-performances", params, headers
        )

    def adjudicate_performance(
        self, performance_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/competing-performances/{performance_id}/adjudicate",
            payload,
            headers,
        )

    # ----------------------------------------------------------------- bookings
    def get_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/bookings/{booking_id}", None, headers)

    def list_bookings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/bookings", params, headers)

    def get_rider_estimate(
        self, booking_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/bookings/{booking_id}/rider-estimate", params, headers
        )

    def get_settlement(self, booking_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/bookings/{booking_id}/settlement", None, headers
        )

    def countersign_booking(
        self, booking_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/bookings/{booking_id}/countersign", payload or {}, headers
        )

    def amend_guarantee(
        self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH",
            f"{API_PREFIX}/bookings/{booking_id}/guarantee-amendment",
            payload,
            headers,
        )

    def cancel_booking(
        self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/bookings/{booking_id}/cancel", payload, headers
        )

    # -------------------------------------------------------------- rider items
    def create_rider_item(
        self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/bookings/{booking_id}/rider-items", payload, headers
        )

    def list_rider_items(
        self, booking_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/bookings/{booking_id}/rider-items", params, headers
        )

    def get_rider_item(self, rider_item_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/rider-items/{rider_item_id}", None, headers
        )

    def decide_rider_item(
        self, rider_item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/rider-items/{rider_item_id}/decision", payload, headers
        )

    # ----------------------------------------------------------- advance packets
    def create_advance_packet(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/advance-packets", payload, headers)

    def get_advance_packet(self, packet_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/advance-packets/{packet_id}", None, headers
        )

    def list_advance_packets(
        self, booking_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/bookings/{booking_id}/advance-packets", params, headers
        )

    def submit_advance_packet(
        self, packet_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/advance-packets/{packet_id}/submit", payload or {}, headers
        )

    def return_advance_packet(
        self, packet_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/advance-packets/{packet_id}/return", payload, headers
        )

    def approve_advance_packet(
        self, packet_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/advance-packets/{packet_id}/approve",
            payload or {},
            headers,
        )

    # ------------------------------------------------------ payment installments
    def list_payment_installments(
        self, booking_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/bookings/{booking_id}/payment-installments",
            params,
            headers,
        )

    def get_payment_installment(self, installment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/payment-installments/{installment_id}", None, headers
        )

    def release_installment(
        self, installment_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/payment-installments/{installment_id}/release",
            payload or {},
            headers,
        )

    def mark_installment_paid(
        self, installment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/payment-installments/{installment_id}/mark-paid",
            payload,
            headers,
        )

    def clawback_installment(
        self, installment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/payment-installments/{installment_id}/clawback",
            payload,
            headers,
        )

    # ------------------------------------------------------- announcement waves
    def create_announcement_wave(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/announcement-waves", payload, headers
        )

    def get_announcement_wave(self, wave_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/announcement-waves/{wave_id}", None, headers
        )

    def list_announcement_waves(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/announcement-waves", params, headers)

    def assign_booking_to_wave(
        self, wave_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/announcement-waves/{wave_id}/assignments", payload, headers
        )

    def lock_wave(
        self, wave_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/announcement-waves/{wave_id}/lock", payload or {}, headers
        )

    def publish_wave(
        self, wave_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/announcement-waves/{wave_id}/publish",
            payload or {},
            headers,
        )
