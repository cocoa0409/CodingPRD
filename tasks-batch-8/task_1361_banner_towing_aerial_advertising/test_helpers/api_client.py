"""API client: one method per endpoint defined in the PRD (§4)."""
import time

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        """Transport-hardened request.

        The harness restarts the server before every test (per-test-server
        isolation). Under concurrent load a restart can race an in-flight
        request: the kernel resets the socket mid-response
        (ChunkedEncodingError) or the pooled keep-alive connection is already
        dead (ConnectionError). Sending `Connection: close` pins every request
        to a fresh TCP connection to the *current* server, and a bounded
        retry absorbs the residual restart race. No assertion logic lives
        here — this is pure HTTP transport.
        """
        hdrs = dict(headers or {})
        hdrs["Connection"] = "close"
        last_exc = None
        for attempt in range(3):
            try:
                return super()._request(method, path, payload, hdrs, params)
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ChunkedEncodingError) as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(0.25)
        raise last_exc


    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/btaa/_clock/set_current_utc", payload, headers)

    # --- Bases ---
    def create_base(self, payload, headers):
        return self._request("POST", "/btaa/bases", payload, headers)

    def get_base(self, base_id, headers):
        return self._request("GET", f"/btaa/bases/{base_id}", headers=headers)

    # --- Aircraft ---
    def create_aircraft(self, base_id, payload, headers):
        return self._request("POST", f"/btaa/bases/{base_id}/aircraft", payload, headers)

    def list_aircraft(self, base_id, headers, params=None):
        return self._request("GET", f"/btaa/bases/{base_id}/aircraft",
                             headers=headers, params=params)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/btaa/aircraft/{aircraft_id}", headers=headers)

    def ground_aircraft(self, aircraft_id, headers):
        return self._request("POST", f"/btaa/aircraft/{aircraft_id}/ground",
                             headers=headers)

    def return_aircraft_to_service(self, aircraft_id, headers):
        return self._request("POST", f"/btaa/aircraft/{aircraft_id}/return_to_service",
                             headers=headers)

    def retire_aircraft(self, aircraft_id, headers):
        return self._request("POST", f"/btaa/aircraft/{aircraft_id}/retire",
                             headers=headers)

    # --- Pilots ---
    def create_pilot(self, base_id, payload, headers):
        return self._request("POST", f"/btaa/bases/{base_id}/pilots", payload, headers)

    def list_pilots(self, base_id, headers, params=None):
        return self._request("GET", f"/btaa/bases/{base_id}/pilots",
                             headers=headers, params=params)

    def get_pilot(self, pilot_id, headers):
        return self._request("GET", f"/btaa/pilots/{pilot_id}", headers=headers)

    def reinstate_pilot(self, pilot_id, headers):
        return self._request("POST", f"/btaa/pilots/{pilot_id}/reinstate",
                             headers=headers)

    def deactivate_pilot(self, pilot_id, headers):
        return self._request("POST", f"/btaa/pilots/{pilot_id}/deactivate",
                             headers=headers)

    # --- Routes ---
    def create_route(self, payload, headers):
        return self._request("POST", "/btaa/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/btaa/routes/{route_id}", headers=headers)

    def list_routes(self, base_id, headers, params=None):
        return self._request("GET", f"/btaa/bases/{base_id}/routes",
                             headers=headers, params=params)

    # --- Clients ---
    def create_client(self, payload, headers):
        return self._request("POST", "/btaa/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/btaa/clients/{client_id}", headers=headers)

    def set_credit_hold(self, client_id, payload, headers):
        return self._request("POST", f"/btaa/clients/{client_id}/set_credit_hold",
                             payload, headers)

    # --- Campaigns ---
    def create_campaign(self, client_id, payload, headers):
        return self._request("POST", f"/btaa/clients/{client_id}/campaigns",
                             payload, headers)

    def list_campaigns(self, client_id, headers, params=None):
        return self._request("GET", f"/btaa/clients/{client_id}/campaigns",
                             headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/btaa/campaigns/{campaign_id}", headers=headers)

    def book_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/btaa/campaigns/{campaign_id}/book",
                             payload, headers)

    def cancel_campaign(self, campaign_id, headers):
        return self._request("POST", f"/btaa/campaigns/{campaign_id}/cancel",
                             headers=headers)

    def get_billing_preview(self, campaign_id, headers, params=None):
        return self._request("GET", f"/btaa/campaigns/{campaign_id}/billing_preview",
                             headers=headers, params=params)

    # --- Banners ---
    def create_banner(self, campaign_id, payload, headers):
        return self._request("POST", f"/btaa/campaigns/{campaign_id}/banners",
                             payload, headers)

    def list_banners(self, campaign_id, headers, params=None):
        return self._request("GET", f"/btaa/campaigns/{campaign_id}/banners",
                             headers=headers, params=params)

    def get_banner(self, banner_id, headers):
        return self._request("GET", f"/btaa/banners/{banner_id}", headers=headers)

    def fabricate_banner(self, banner_id, payload, headers):
        return self._request("POST", f"/btaa/banners/{banner_id}/fabricate",
                             payload, headers)

    def mark_banner_ready(self, banner_id, headers):
        return self._request("POST", f"/btaa/banners/{banner_id}/mark_ready",
                             headers=headers)

    def retire_banner(self, banner_id, headers):
        return self._request("POST", f"/btaa/banners/{banner_id}/retire",
                             headers=headers)

    def list_banners_filtered(self, headers, params=None):
        return self._request("GET", "/btaa/banners", headers=headers, params=params)

    # --- Banner revisions ---
    def propose_banner_revision(self, banner_id, payload, headers):
        return self._request("POST", f"/btaa/banners/{banner_id}/revisions",
                             payload, headers)

    def list_banner_revisions(self, banner_id, headers, params=None):
        return self._request("GET", f"/btaa/banners/{banner_id}/revisions",
                             headers=headers, params=params)

    def get_banner_revision(self, revision_id, headers):
        return self._request("GET", f"/btaa/banner_revisions/{revision_id}",
                             headers=headers)

    def approve_banner_revision(self, revision_id, headers):
        return self._request("POST", f"/btaa/banner_revisions/{revision_id}/approve",
                             headers=headers)

    def reject_banner_revision(self, revision_id, headers):
        return self._request("POST", f"/btaa/banner_revisions/{revision_id}/reject",
                             headers=headers)

    def list_banner_revisions_filtered(self, headers, params=None):
        return self._request("GET", "/btaa/banner_revisions",
                             headers=headers, params=params)

    # --- Airspace approvals ---
    def create_airspace_approval(self, route_id, payload, headers):
        return self._request("POST", f"/btaa/routes/{route_id}/airspace_approvals",
                             payload, headers)

    def list_airspace_approvals(self, route_id, headers, params=None):
        return self._request("GET", f"/btaa/routes/{route_id}/airspace_approvals",
                             headers=headers, params=params)

    def get_airspace_approval(self, approval_id, headers):
        return self._request("GET", f"/btaa/airspace_approvals/{approval_id}",
                             headers=headers)

    def grant_airspace_approval(self, approval_id, headers):
        return self._request("POST", f"/btaa/airspace_approvals/{approval_id}/grant",
                             headers=headers)

    def deny_airspace_approval(self, approval_id, headers):
        return self._request("POST", f"/btaa/airspace_approvals/{approval_id}/deny",
                             headers=headers)

    def revoke_airspace_approval(self, approval_id, headers):
        return self._request("POST", f"/btaa/airspace_approvals/{approval_id}/revoke",
                             headers=headers)

    # --- TFR restrictions ---
    def create_tfr_restriction(self, payload, headers):
        return self._request("POST", "/btaa/tfr_restrictions", payload, headers)

    def list_tfr_restrictions(self, route_id, headers, params=None):
        return self._request("GET", f"/btaa/routes/{route_id}/tfr_restrictions",
                             headers=headers, params=params)

    def get_tfr_restriction(self, tfr_id, headers):
        return self._request("GET", f"/btaa/tfr_restrictions/{tfr_id}", headers=headers)

    def cancel_tfr_restriction(self, tfr_id, headers):
        return self._request("POST", f"/btaa/tfr_restrictions/{tfr_id}/cancel",
                             headers=headers)

    # --- Seasonal capacity ---
    def create_seasonal_capacity(self, base_id, payload, headers):
        return self._request("POST", f"/btaa/bases/{base_id}/seasonal_capacities",
                             payload, headers)

    def list_seasonal_capacities(self, base_id, headers, params=None):
        return self._request("GET", f"/btaa/bases/{base_id}/seasonal_capacities",
                             headers=headers, params=params)

    def get_seasonal_capacity(self, capacity_id, headers):
        return self._request("GET", f"/btaa/seasonal_capacities/{capacity_id}",
                             headers=headers)

    # --- Flight slots ---
    def create_flight_slot(self, campaign_id, payload, headers):
        return self._request("POST", f"/btaa/campaigns/{campaign_id}/flight_slots",
                             payload, headers)

    def list_flight_slots(self, campaign_id, headers, params=None):
        return self._request("GET", f"/btaa/campaigns/{campaign_id}/flight_slots",
                             headers=headers, params=params)

    def get_flight_slot(self, slot_id, headers):
        return self._request("GET", f"/btaa/flight_slots/{slot_id}", headers=headers)

    def schedule_flight_slot(self, slot_id, headers):
        return self._request("POST", f"/btaa/flight_slots/{slot_id}/schedule",
                             headers=headers)

    def record_weather_assessment(self, slot_id, payload, headers):
        return self._request("POST", f"/btaa/flight_slots/{slot_id}/weather_assessments",
                             payload, headers)

    def reschedule_after_hold(self, slot_id, payload, headers):
        return self._request("POST",
                             f"/btaa/flight_slots/{slot_id}/reschedule_after_hold",
                             payload, headers)

    def file_flight_log(self, slot_id, payload, headers):
        return self._request("POST", f"/btaa/flight_slots/{slot_id}/flight_log",
                             payload, headers)

    def cancel_slot_by_client(self, slot_id, headers):
        return self._request("POST", f"/btaa/flight_slots/{slot_id}/cancel_by_client",
                             headers=headers)

    def list_weather_assessments(self, slot_id, headers, params=None):
        return self._request("GET",
                             f"/btaa/flight_slots/{slot_id}/weather_assessments",
                             headers=headers, params=params)

    def list_flight_logs(self, slot_id, headers, params=None):
        return self._request("GET", f"/btaa/flight_slots/{slot_id}/flight_logs",
                             headers=headers, params=params)

    def list_flight_slots_filtered(self, headers, params=None):
        return self._request("GET", "/btaa/flight_slots", headers=headers, params=params)

    def get_weather_assessment(self, assessment_id, headers):
        return self._request("GET", f"/btaa/weather_assessments/{assessment_id}",
                             headers=headers)

    def get_flight_log(self, log_id, headers):
        return self._request("GET", f"/btaa/flight_logs/{log_id}", headers=headers)

    def list_weather_assessments_filtered(self, headers, params=None):
        return self._request("GET", "/btaa/weather_assessments",
                             headers=headers, params=params)

    def list_flight_logs_filtered(self, headers, params=None):
        return self._request("GET", "/btaa/flight_logs", headers=headers, params=params)

    # --- Proof of flight ---
    def submit_proof_of_flight(self, slot_id, payload, headers):
        return self._request("POST", f"/btaa/flight_slots/{slot_id}/proof_of_flight",
                             payload, headers)

    def list_proof_of_flight(self, slot_id, headers, params=None):
        return self._request("GET", f"/btaa/flight_slots/{slot_id}/proof_of_flight",
                             headers=headers, params=params)

    def finalize_proof_of_flight(self, proof_id, headers):
        return self._request("POST", f"/btaa/proof_of_flight/{proof_id}/finalize",
                             headers=headers)

    # --- Make-good credits ---
    def list_make_good_credits(self, campaign_id, headers, params=None):
        return self._request("GET", f"/btaa/campaigns/{campaign_id}/make_good_credits",
                             headers=headers, params=params)

    def get_make_good_credit(self, credit_id, headers):
        return self._request("GET", f"/btaa/make_good_credits/{credit_id}",
                             headers=headers)

    def list_make_good_credits_filtered(self, headers, params=None):
        return self._request("GET", "/btaa/make_good_credits",
                             headers=headers, params=params)

    # --- Invoices ---
    def issue_invoice(self, campaign_id, payload, headers):
        return self._request("POST", f"/btaa/campaigns/{campaign_id}/invoices",
                             payload, headers)

    def list_invoices(self, campaign_id, headers, params=None):
        return self._request("GET", f"/btaa/campaigns/{campaign_id}/invoices",
                             headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/btaa/invoices/{invoice_id}", headers=headers)

    def mark_invoice_paid(self, invoice_id, headers):
        return self._request("POST", f"/btaa/invoices/{invoice_id}/mark_paid",
                             headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/btaa/invoices/{invoice_id}/void",
                             headers=headers)

    # --- Ops checkpoint ---
    def run_ops(self, base_id, headers):
        return self._request("POST", f"/btaa/bases/{base_id}/run_ops", headers=headers)


api_client = ApiClient()
