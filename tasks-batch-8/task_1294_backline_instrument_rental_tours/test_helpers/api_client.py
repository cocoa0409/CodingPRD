"""API client: one method per endpoint defined in the PRD."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Backline tour-rental API client. All mutating methods default to an
    empty JSON body so action endpoints can be called with just an id."""

    def __init__(self, base_url=None):
        super().__init__(base_url)
        # The runner restarts the API server before every test
        # (per-test-server isolation). A pooled keep-alive connection would
        # point at the dead pre-restart server and surface as ECONNRESET on
        # the first request of the next test — disable keep-alive and retry
        # transient connection resets so transport noise cannot flake a test.
        self.session.headers.update({"Connection": "close"})
        retry = Retry(total=5, connect=5, read=5, backoff_factor=0.05,
                      allowed_methods=None, raise_on_status=False)
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    # --- clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/backline/_clock/set_current_utc", payload, headers)

    # --- artists ---
    def create_artist(self, payload, headers):
        return self._request("POST", "/backline/artists", payload, headers)

    def create_deposit_topup(self, artist_id, payload, headers):
        return self._request("POST", f"/backline/artists/{artist_id}/deposit-topups", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"/backline/artists/{artist_id}", headers=headers)

    def list_artists(self, headers, params=None):
        return self._request("GET", "/backline/artists", headers=headers, params=params)

    def update_artist(self, artist_id, payload, headers):
        return self._request("PATCH", f"/backline/artists/{artist_id}", payload, headers)

    # --- tours ---
    def create_tour(self, payload, headers):
        return self._request("POST", "/backline/tours", payload, headers)

    def get_tour(self, tour_id, headers):
        return self._request("GET", f"/backline/tours/{tour_id}", headers=headers)

    def list_tours(self, headers, params=None):
        return self._request("GET", "/backline/tours", headers=headers, params=params)

    def activate_tour(self, tour_id, payload, headers):
        return self._request("POST", f"/backline/tours/{tour_id}/activate", payload, headers)

    def complete_tour(self, tour_id, headers, payload=None):
        return self._request("POST", f"/backline/tours/{tour_id}/complete", payload or {}, headers)

    def cancel_tour(self, tour_id, headers, payload=None):
        return self._request("POST", f"/backline/tours/{tour_id}/cancel", payload or {}, headers)

    # --- tour stops ---
    def create_tour_stop(self, tour_id, payload, headers):
        return self._request("POST", f"/backline/tours/{tour_id}/stops", payload, headers)

    def list_tour_stops(self, tour_id, headers, params=None):
        return self._request("GET", f"/backline/tours/{tour_id}/stops", headers=headers, params=params)

    def get_tour_stop(self, stop_id, headers):
        return self._request("GET", f"/backline/tour-stops/{stop_id}", headers=headers)

    def stage_tour_stop(self, stop_id, headers, payload=None):
        return self._request("POST", f"/backline/tour-stops/{stop_id}/stage", payload or {}, headers)

    def show_ready_tour_stop(self, stop_id, headers, payload=None):
        return self._request("POST", f"/backline/tour-stops/{stop_id}/show-ready", payload or {}, headers)

    def load_out_tour_stop(self, stop_id, headers, payload=None):
        return self._request("POST", f"/backline/tour-stops/{stop_id}/load-out", payload or {}, headers)

    def settle_tour_stop(self, stop_id, headers, payload=None):
        return self._request("POST", f"/backline/tour-stops/{stop_id}/settle", payload or {}, headers)

    def cancel_tour_stop(self, stop_id, headers, payload=None):
        return self._request("POST", f"/backline/tour-stops/{stop_id}/cancel", payload or {}, headers)

    # --- rider lines ---
    def create_rider_line(self, stop_id, payload, headers):
        return self._request("POST", f"/backline/tour-stops/{stop_id}/rider-lines", payload, headers)

    def list_stop_rider_lines(self, stop_id, headers, params=None):
        return self._request("GET", f"/backline/tour-stops/{stop_id}/rider-lines", headers=headers, params=params)

    def list_rider_lines(self, headers, params=None):
        return self._request("GET", "/backline/rider-lines", headers=headers, params=params)

    def get_rider_line(self, line_id, headers):
        return self._request("GET", f"/backline/rider-lines/{line_id}", headers=headers)

    def source_rider_line(self, line_id, payload, headers):
        return self._request("POST", f"/backline/rider-lines/{line_id}/source", payload, headers)

    def propose_substitution(self, line_id, payload, headers):
        return self._request("POST", f"/backline/rider-lines/{line_id}/propose-substitution", payload, headers)

    def approve_substitution(self, line_id, payload, headers):
        return self._request("POST", f"/backline/rider-lines/{line_id}/approve-substitution", payload, headers)

    def reject_substitution(self, line_id, headers, payload=None):
        return self._request("POST", f"/backline/rider-lines/{line_id}/reject-substitution", payload or {}, headers)

    def mark_rider_line_fulfilled(self, line_id, headers, payload=None):
        return self._request("POST", f"/backline/rider-lines/{line_id}/mark-fulfilled", payload or {}, headers)

    def mark_rider_line_shorted(self, line_id, headers, payload=None):
        return self._request("POST", f"/backline/rider-lines/{line_id}/mark-shorted", payload or {}, headers)

    def cancel_rider_line(self, line_id, headers, payload=None):
        return self._request("POST", f"/backline/rider-lines/{line_id}/cancel", payload or {}, headers)

    # --- gear catalog ---
    def create_gear_model(self, payload, headers):
        return self._request("POST", "/backline/gear-models", payload, headers)

    def get_gear_model(self, model_id, headers):
        return self._request("GET", f"/backline/gear-models/{model_id}", headers=headers)

    def list_gear_models(self, headers, params=None):
        return self._request("GET", "/backline/gear-models", headers=headers, params=params)

    def create_gear_unit(self, payload, headers):
        return self._request("POST", "/backline/gear-units", payload, headers)

    def get_gear_unit(self, unit_id, headers):
        return self._request("GET", f"/backline/gear-units/{unit_id}", headers=headers)

    def list_gear_units(self, headers, params=None):
        return self._request("GET", "/backline/gear-units", headers=headers, params=params)

    def list_gear_unit_shipment_lines(self, unit_id, headers, params=None):
        return self._request("GET", f"/backline/gear-units/{unit_id}/shipment-lines", headers=headers, params=params)

    def retire_gear_unit(self, unit_id, headers, payload=None):
        return self._request("POST", f"/backline/gear-units/{unit_id}/retire", payload or {}, headers)

    def get_gear_unit_availability(self, unit_id, headers, params=None):
        return self._request("GET", f"/backline/gear-units/{unit_id}/availability", headers=headers, params=params)

    # --- reservations ---
    def get_reservation_line(self, reservation_id, headers):
        return self._request("GET", f"/backline/reservation-lines/{reservation_id}", headers=headers)

    def list_reservation_lines(self, headers, params=None):
        return self._request("GET", "/backline/reservation-lines", headers=headers, params=params)

    def dispatch_reservation(self, reservation_id, headers, payload=None):
        return self._request("POST", f"/backline/reservation-lines/{reservation_id}/dispatch", payload or {}, headers)

    def mark_reservation_delivered(self, reservation_id, headers, payload=None):
        return self._request("POST", f"/backline/reservation-lines/{reservation_id}/mark-delivered", payload or {}, headers)

    def check_in_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/backline/reservation-lines/{reservation_id}/check-in", payload, headers)

    def inspect_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/backline/reservation-lines/{reservation_id}/inspect", payload, headers)

    def settle_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/backline/reservation-lines/{reservation_id}/settle", payload, headers)

    def cancel_reservation(self, reservation_id, headers, payload=None):
        return self._request("POST", f"/backline/reservation-lines/{reservation_id}/cancel", payload or {}, headers)

    # --- shipments / cartage ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/backline/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/backline/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/backline/shipments", headers=headers, params=params)

    def create_shipment_line(self, shipment_id, payload, headers):
        return self._request("POST", f"/backline/shipments/{shipment_id}/lines", payload, headers)

    def list_shipment_lines(self, shipment_id, headers, params=None):
        return self._request("GET", f"/backline/shipments/{shipment_id}/lines", headers=headers, params=params)

    def begin_loading_shipment(self, shipment_id, headers, payload=None):
        return self._request("POST", f"/backline/shipments/{shipment_id}/begin-loading", payload or {}, headers)

    def load_shipment_line(self, line_id, headers, payload=None):
        return self._request("POST", f"/backline/shipment-lines/{line_id}/load", payload or {}, headers)

    def cancel_shipment_line(self, line_id, headers, payload=None):
        return self._request("POST", f"/backline/shipment-lines/{line_id}/cancel", payload or {}, headers)

    def depart_shipment(self, shipment_id, headers, payload=None):
        return self._request("POST", f"/backline/shipments/{shipment_id}/depart", payload or {}, headers)

    def mark_shipment_delivered(self, shipment_id, headers, payload=None):
        return self._request("POST", f"/backline/shipments/{shipment_id}/mark-delivered", payload or {}, headers)

    def close_shipment(self, shipment_id, headers, payload=None):
        return self._request("POST", f"/backline/shipments/{shipment_id}/close", payload or {}, headers)

    def cancel_shipment(self, shipment_id, headers, payload=None):
        return self._request("POST", f"/backline/shipments/{shipment_id}/cancel", payload or {}, headers)

    # --- flight cases ---
    def create_flight_case(self, payload, headers):
        return self._request("POST", "/backline/flight-cases", payload, headers)

    def get_flight_case(self, case_id, headers):
        return self._request("GET", f"/backline/flight-cases/{case_id}", headers=headers)

    def list_flight_cases(self, headers, params=None):
        return self._request("GET", "/backline/flight-cases", headers=headers, params=params)

    def list_flight_case_shipment_lines(self, case_id, headers, params=None):
        return self._request("GET", f"/backline/flight-cases/{case_id}/shipment-lines", headers=headers, params=params)

    def send_flight_case_to_maintenance(self, case_id, headers, payload=None):
        return self._request("POST", f"/backline/flight-cases/{case_id}/send-to-maintenance", payload or {}, headers)

    def return_flight_case_to_service(self, case_id, headers, payload=None):
        return self._request("POST", f"/backline/flight-cases/{case_id}/return-to-service", payload or {}, headers)

    def retire_flight_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/backline/flight-cases/{case_id}/retire", payload or {}, headers)

    # --- partner vendors / cross-rental ---
    def create_partner_vendor(self, payload, headers):
        return self._request("POST", "/backline/partner-vendors", payload, headers)

    def get_partner_vendor(self, vendor_id, headers):
        return self._request("GET", f"/backline/partner-vendors/{vendor_id}", headers=headers)

    def list_partner_vendors(self, headers, params=None):
        return self._request("GET", "/backline/partner-vendors", headers=headers, params=params)

    def approve_partner_vendor(self, vendor_id, headers, payload=None):
        return self._request("POST", f"/backline/partner-vendors/{vendor_id}/approve", payload or {}, headers)

    def suspend_partner_vendor(self, vendor_id, headers, payload=None):
        return self._request("POST", f"/backline/partner-vendors/{vendor_id}/suspend", payload or {}, headers)

    def create_cross_rental_request(self, payload, headers):
        return self._request("POST", "/backline/cross-rental-requests", payload, headers)

    def get_cross_rental_request(self, request_id, headers):
        return self._request("GET", f"/backline/cross-rental-requests/{request_id}", headers=headers)

    def list_cross_rental_requests(self, headers, params=None):
        return self._request("GET", "/backline/cross-rental-requests", headers=headers, params=params)

    def accept_cross_rental_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/backline/cross-rental-requests/{request_id}/accept", payload or {}, headers)

    def reject_cross_rental_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/backline/cross-rental-requests/{request_id}/reject", payload or {}, headers)

    def fulfill_cross_rental_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/backline/cross-rental-requests/{request_id}/mark-fulfilled", payload or {}, headers)

    def settle_cross_rental_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/backline/cross-rental-requests/{request_id}/settle", payload or {}, headers)

    def cancel_cross_rental_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/backline/cross-rental-requests/{request_id}/cancel", payload or {}, headers)

    # --- maintenance ---
    def create_maintenance_ticket(self, payload, headers):
        return self._request("POST", "/backline/maintenance-tickets", payload, headers)

    def get_maintenance_ticket(self, ticket_id, headers):
        return self._request("GET", f"/backline/maintenance-tickets/{ticket_id}", headers=headers)

    def list_maintenance_tickets(self, headers, params=None):
        return self._request("GET", "/backline/maintenance-tickets", headers=headers, params=params)

    def start_maintenance_ticket(self, ticket_id, headers, payload=None):
        return self._request("POST", f"/backline/maintenance-tickets/{ticket_id}/start", payload or {}, headers)

    def await_parts_maintenance_ticket(self, ticket_id, headers, payload=None):
        return self._request("POST", f"/backline/maintenance-tickets/{ticket_id}/await-parts", payload or {}, headers)

    def resume_maintenance_ticket(self, ticket_id, headers, payload=None):
        return self._request("POST", f"/backline/maintenance-tickets/{ticket_id}/resume", payload or {}, headers)

    def complete_maintenance_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/backline/maintenance-tickets/{ticket_id}/complete", payload, headers)

    def cancel_maintenance_ticket(self, ticket_id, headers, payload=None):
        return self._request("POST", f"/backline/maintenance-tickets/{ticket_id}/cancel", payload or {}, headers)

    # --- damage claims ---
    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/backline/damage-claims/{claim_id}", headers=headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", "/backline/damage-claims", headers=headers, params=params)

    def assess_damage_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/backline/damage-claims/{claim_id}/assess", payload or {}, headers)

    def charge_damage_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/backline/damage-claims/{claim_id}/charge", payload or {}, headers)

    def dispute_damage_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/backline/damage-claims/{claim_id}/dispute", payload or {}, headers)

    def waive_damage_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/backline/damage-claims/{claim_id}/waive", payload or {}, headers)

    def mark_damage_claim_paid(self, claim_id, headers, payload=None):
        return self._request("POST", f"/backline/damage-claims/{claim_id}/mark-paid", payload or {}, headers)


api_client = ApiClient()
