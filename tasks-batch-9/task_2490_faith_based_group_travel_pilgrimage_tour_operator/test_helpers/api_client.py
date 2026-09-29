"""HTTP client with one method per endpoint of the PRD §4 operation table."""

from __future__ import annotations

from typing import Any

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin, exhaustive wrapper over the pilgrimage tour-operator API."""

    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------

    def set_clock(self, payload: dict[str, Any], headers: dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Programs
    # ------------------------------------------------------------------

    def create_program(self, payload: dict[str, Any], headers: dict[str, str]):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id: str, headers: dict[str, str]):
        return self._request("GET", f"/programs/{program_id}", None, headers)

    # ------------------------------------------------------------------
    # Departures
    # ------------------------------------------------------------------

    def create_departure(self, payload: dict[str, Any], headers: dict[str, str]):
        return self._request("POST", "/departures", payload, headers)

    def get_departure(self, departure_id: str, headers: dict[str, str]):
        return self._request("GET", f"/departures/{departure_id}", None, headers)

    def list_departures(self, headers: dict[str, str], params: dict[str, Any] | None = None):
        return self._request("GET", "/departures", None, headers, params=params)

    def open_departure_sales(
        self, departure_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ):
        return self._request(
            "POST", f"/departures/{departure_id}/open-sales", payload or {}, headers
        )

    def close_departure_sales(
        self, departure_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ):
        return self._request(
            "POST", f"/departures/{departure_id}/close-sales", payload or {}, headers
        )

    def cancel_departure(
        self, departure_id: str, payload: dict[str, Any], headers: dict[str, str]
    ):
        return self._request("POST", f"/departures/{departure_id}/cancel", payload, headers)

    def run_payment_sweep(
        self, departure_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ):
        return self._request(
            "POST", f"/departures/{departure_id}/payment-sweep", payload or {}, headers
        )

    def propose_itinerary_modification(
        self, departure_id: str, payload: dict[str, Any], headers: dict[str, str]
    ):
        return self._request(
            "POST", f"/departures/{departure_id}/itinerary-modification", payload, headers
        )

    def ratify_itinerary_modification(
        self, departure_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ):
        return self._request(
            "POST", f"/departures/{departure_id}/ratify-modification", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Group leader agreements
    # ------------------------------------------------------------------

    def create_agreement(self, payload: dict[str, Any], headers: dict[str, str]):
        return self._request("POST", "/group-leader-agreements", payload, headers)

    def get_agreement(self, agreement_id: str, headers: dict[str, str]):
        return self._request(
            "GET", f"/group-leader-agreements/{agreement_id}", None, headers
        )

    def list_agreements(self, headers: dict[str, str], params: dict[str, Any] | None = None):
        return self._request("GET", "/group-leader-agreements", None, headers, params=params)

    def countersign_agreement(
        self, agreement_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ):
        return self._request(
            "POST",
            f"/group-leader-agreements/{agreement_id}/countersign",
            payload or {},
            headers,
        )

    def settle_agreement(
        self, agreement_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ):
        return self._request(
            "POST", f"/group-leader-agreements/{agreement_id}/settle", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Pilgrims (travelers)
    # ------------------------------------------------------------------

    def create_pilgrim(self, payload: dict[str, Any], headers: dict[str, str]):
        return self._request("POST", "/pilgrims", payload, headers)

    def get_pilgrim(self, pilgrim_id: str, headers: dict[str, str]):
        return self._request("GET", f"/pilgrims/{pilgrim_id}", None, headers)

    def list_pilgrims(self, headers: dict[str, str], params: dict[str, Any] | None = None):
        return self._request("GET", "/pilgrims", None, headers, params=params)

    def confirm_pilgrim(
        self, pilgrim_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ):
        return self._request("POST", f"/pilgrims/{pilgrim_id}/confirm", payload or {}, headers)

    def cancel_pilgrim(self, pilgrim_id: str, payload: dict[str, Any], headers: dict[str, str]):
        return self._request("POST", f"/pilgrims/{pilgrim_id}/cancel", payload, headers)

    def assign_rooming(self, pilgrim_id: str, payload: dict[str, Any], headers: dict[str, str]):
        return self._request("POST", f"/pilgrims/{pilgrim_id}/rooming", payload, headers)

    def submit_ticket_name(
        self, pilgrim_id: str, payload: dict[str, Any], headers: dict[str, str]
    ):
        return self._request("POST", f"/pilgrims/{pilgrim_id}/ticket-name", payload, headers)

    def record_air_deviation(
        self, pilgrim_id: str, payload: dict[str, Any], headers: dict[str, str]
    ):
        return self._request("POST", f"/pilgrims/{pilgrim_id}/air-deviation", payload, headers)

    # ------------------------------------------------------------------
    # Payment plans
    # ------------------------------------------------------------------

    def create_payment_plan(
        self, pilgrim_id: str, payload: dict[str, Any], headers: dict[str, str]
    ):
        return self._request("POST", f"/pilgrims/{pilgrim_id}/payment-plans", payload, headers)

    def get_payment_plan(self, payment_plan_id: str, headers: dict[str, str]):
        return self._request("GET", f"/payment-plans/{payment_plan_id}", None, headers)

    def list_payment_plans(self, headers: dict[str, str], params: dict[str, Any] | None = None):
        return self._request("GET", "/payment-plans", None, headers, params=params)

    # ------------------------------------------------------------------
    # Cash receipts
    # ------------------------------------------------------------------

    def record_payment(
        self, pilgrim_id: str, payload: dict[str, Any], headers: dict[str, str]
    ):
        return self._request("POST", f"/pilgrims/{pilgrim_id}/payments", payload, headers)

    def get_payment(self, payment_id: str, headers: dict[str, str]):
        return self._request("GET", f"/payments/{payment_id}", None, headers)

    def list_payments(self, headers: dict[str, str], params: dict[str, Any] | None = None):
        return self._request("GET", "/payments", None, headers, params=params)

    def reverse_payment(self, payment_id: str, payload: dict[str, Any], headers: dict[str, str]):
        return self._request("POST", f"/payments/{payment_id}/reverse", payload, headers)

    # ------------------------------------------------------------------
    # Air blocks
    # ------------------------------------------------------------------

    def create_air_block(self, payload: dict[str, Any], headers: dict[str, str]):
        return self._request("POST", "/air-blocks", payload, headers)

    def get_air_block(self, air_block_id: str, headers: dict[str, str]):
        return self._request("GET", f"/air-blocks/{air_block_id}", None, headers)

    def list_air_blocks(self, headers: dict[str, str], params: dict[str, Any] | None = None):
        return self._request("GET", "/air-blocks", None, headers, params=params)

    def add_negotiation_round(
        self, air_block_id: str, payload: dict[str, Any], headers: dict[str, str]
    ):
        return self._request(
            "POST", f"/air-blocks/{air_block_id}/negotiation-rounds", payload, headers
        )

    def confirm_air_block(
        self, air_block_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ):
        return self._request(
            "POST", f"/air-blocks/{air_block_id}/confirm", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Sacred sites
    # ------------------------------------------------------------------

    def create_sacred_site(self, payload: dict[str, Any], headers: dict[str, str]):
        return self._request("POST", "/sacred-sites", payload, headers)

    def get_sacred_site(self, sacred_site_id: str, headers: dict[str, str]):
        return self._request("GET", f"/sacred-sites/{sacred_site_id}", None, headers)

    # ------------------------------------------------------------------
    # Service bookings
    # ------------------------------------------------------------------

    def create_service_booking(self, payload: dict[str, Any], headers: dict[str, str]):
        return self._request("POST", "/service-bookings", payload, headers)

    def get_service_booking(self, service_booking_id: str, headers: dict[str, str]):
        return self._request("GET", f"/service-bookings/{service_booking_id}", None, headers)

    def list_service_bookings(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ):
        return self._request("GET", "/service-bookings", None, headers, params=params)

    def clergy_confirm_service_booking(
        self, service_booking_id: str, payload: dict[str, Any], headers: dict[str, str]
    ):
        return self._request(
            "POST", f"/service-bookings/{service_booking_id}/clergy-confirm", payload, headers
        )

    def confirm_service_booking(
        self,
        service_booking_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ):
        return self._request(
            "POST", f"/service-bookings/{service_booking_id}/confirm", payload or {}, headers
        )

    def cancel_service_booking(
        self, service_booking_id: str, payload: dict[str, Any], headers: dict[str, str]
    ):
        return self._request(
            "POST", f"/service-bookings/{service_booking_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Land resources and assignments
    # ------------------------------------------------------------------

    def create_land_resource(self, payload: dict[str, Any], headers: dict[str, str]):
        return self._request("POST", "/land-resources", payload, headers)

    def get_land_resource(self, land_resource_id: str, headers: dict[str, str]):
        return self._request("GET", f"/land-resources/{land_resource_id}", None, headers)

    def create_land_assignment(self, payload: dict[str, Any], headers: dict[str, str]):
        return self._request("POST", "/land-assignments", payload, headers)

    def get_land_assignment(self, land_assignment_id: str, headers: dict[str, str]):
        return self._request("GET", f"/land-assignments/{land_assignment_id}", None, headers)

    def list_land_assignments(
        self, headers: dict[str, str], params: dict[str, Any] | None = None
    ):
        return self._request("GET", "/land-assignments", None, headers, params=params)

    def countersign_land_assignment(
        self,
        land_assignment_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ):
        return self._request(
            "POST", f"/land-assignments/{land_assignment_id}/countersign", payload or {}, headers
        )

    def terminate_land_assignment(
        self, land_assignment_id: str, payload: dict[str, Any], headers: dict[str, str]
    ):
        return self._request(
            "POST", f"/land-assignments/{land_assignment_id}/terminate", payload, headers
        )

    # ------------------------------------------------------------------
    # Travel protection
    # ------------------------------------------------------------------

    def create_protection(self, payload: dict[str, Any], headers: dict[str, str]):
        return self._request("POST", "/travel-protections", payload, headers)

    def get_protection(self, travel_protection_id: str, headers: dict[str, str]):
        return self._request("GET", f"/travel-protections/{travel_protection_id}", None, headers)

    def list_protections(self, headers: dict[str, str], params: dict[str, Any] | None = None):
        return self._request("GET", "/travel-protections", None, headers, params=params)

    def medical_review_protection(
        self, travel_protection_id: str, payload: dict[str, Any], headers: dict[str, str]
    ):
        return self._request(
            "POST", f"/travel-protections/{travel_protection_id}/medical-review", payload, headers
        )

    def decide_waiver(
        self, travel_protection_id: str, payload: dict[str, Any], headers: dict[str, str]
    ):
        return self._request(
            "POST",
            f"/travel-protections/{travel_protection_id}/waiver-decision",
            payload,
            headers,
        )

    def purchase_protection(
        self,
        travel_protection_id: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ):
        return self._request(
            "POST", f"/travel-protections/{travel_protection_id}/purchase", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Risk advisories
    # ------------------------------------------------------------------

    def create_advisory(self, payload: dict[str, Any], headers: dict[str, str]):
        return self._request("POST", "/risk-advisories", payload, headers)

    def get_advisory(self, risk_advisory_id: str, headers: dict[str, str]):
        return self._request("GET", f"/risk-advisories/{risk_advisory_id}", None, headers)

    def publish_advisory(
        self, risk_advisory_id: str, headers: dict[str, str], payload: dict[str, Any] | None = None
    ):
        return self._request(
            "POST", f"/risk-advisories/{risk_advisory_id}/publish", payload or {}, headers
        )


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
