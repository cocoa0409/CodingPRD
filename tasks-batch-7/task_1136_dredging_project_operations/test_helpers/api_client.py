"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- projects ---
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def activate_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/activate", {}, headers)

    def close_out_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/close-out", {}, headers)

    # --- permits ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    # --- reaches ---
    def create_reach(self, payload, headers):
        return self._request("POST", "/reaches", payload, headers)

    def get_reach(self, reach_id, headers):
        return self._request("GET", f"/reaches/{reach_id}", headers=headers)

    def list_reaches(self, headers, params=None):
        return self._request("GET", "/reaches", headers=headers, params=params)

    def begin_dredging(self, reach_id, headers):
        return self._request("POST", f"/reaches/{reach_id}/begin-dredging", {}, headers)

    # --- dredge plants ---
    def create_plant(self, payload, headers):
        return self._request("POST", "/plants", payload, headers)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"/plants/{plant_id}", headers=headers)

    def list_plants(self, headers, params=None):
        return self._request("GET", "/plants", headers=headers, params=params)

    def patch_plant(self, plant_id, payload, headers):
        return self._request("PATCH", f"/plants/{plant_id}", payload, headers)

    # --- dredge plans ---
    def create_dredge_plan(self, payload, headers):
        return self._request("POST", "/dredge-plans", payload, headers)

    def get_dredge_plan(self, plan_id, headers):
        return self._request("GET", f"/dredge-plans/{plan_id}", headers=headers)

    def list_dredge_plans(self, headers, params=None):
        return self._request("GET", "/dredge-plans", headers=headers, params=params)

    def submit_dredge_plan(self, plan_id, headers):
        return self._request("POST", f"/dredge-plans/{plan_id}/submit", {}, headers)

    def request_changes_dredge_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/dredge-plans/{plan_id}/request-changes", {}, headers
        )

    def approve_dredge_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/dredge-plans/{plan_id}/approve", payload, headers)

    # --- surveys ---
    def create_survey(self, payload, headers):
        return self._request("POST", "/surveys", payload, headers)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/surveys/{survey_id}", headers=headers)

    def list_surveys(self, headers, params=None):
        return self._request("GET", "/surveys", headers=headers, params=params)

    def accept_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/surveys/{survey_id}/accept", payload, headers)

    def reject_survey(self, survey_id, headers):
        return self._request("POST", f"/surveys/{survey_id}/reject", {}, headers)

    # --- dredge events ---
    def create_dredge_event(self, payload, headers):
        return self._request("POST", "/dredge-events", payload, headers)

    def get_dredge_event(self, event_id, headers):
        return self._request("GET", f"/dredge-events/{event_id}", headers=headers)

    def list_dredge_events(self, headers, params=None):
        return self._request("GET", "/dredge-events", headers=headers, params=params)

    def complete_dredge_event(self, event_id, headers):
        return self._request("POST", f"/dredge-events/{event_id}/complete", {}, headers)

    def resume_dredge_event(self, event_id, headers):
        return self._request("POST", f"/dredge-events/{event_id}/resume", {}, headers)

    # --- turbidity readings ---
    def create_turbidity_reading(self, payload, headers):
        return self._request("POST", "/turbidity-readings", payload, headers)

    def get_turbidity_reading(self, reading_id, headers):
        return self._request("GET", f"/turbidity-readings/{reading_id}", headers=headers)

    def list_turbidity_readings(self, headers, params=None):
        return self._request("GET", "/turbidity-readings", headers=headers, params=params)

    # --- species sightings ---
    def create_species_sighting(self, payload, headers):
        return self._request("POST", "/species-sightings", payload, headers)

    def get_species_sighting(self, sighting_id, headers):
        return self._request("GET", f"/species-sightings/{sighting_id}", headers=headers)

    def list_species_sightings(self, headers, params=None):
        return self._request("GET", "/species-sightings", headers=headers, params=params)

    def clear_species_sighting(self, sighting_id, headers):
        return self._request(
            "POST", f"/species-sightings/{sighting_id}/clear", {}, headers
        )

    # --- disposal sites ---
    def create_disposal_site(self, payload, headers):
        return self._request("POST", "/disposal-sites", payload, headers)

    def get_disposal_site(self, site_id, headers):
        return self._request("GET", f"/disposal-sites/{site_id}", headers=headers)

    def list_disposal_sites(self, headers, params=None):
        return self._request("GET", "/disposal-sites", headers=headers, params=params)

    def close_disposal_site(self, site_id, headers):
        return self._request("POST", f"/disposal-sites/{site_id}/close", {}, headers)

    # --- placement tickets ---
    def create_placement_ticket(self, payload, headers):
        return self._request("POST", "/placement-tickets", payload, headers)

    def get_placement_ticket(self, ticket_id, headers):
        return self._request("GET", f"/placement-tickets/{ticket_id}", headers=headers)

    def list_placement_tickets(self, headers, params=None):
        return self._request("GET", "/placement-tickets", headers=headers, params=params)

    def confirm_placement_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/placement-tickets/{ticket_id}/confirm", payload, headers
        )

    def reject_placement_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/placement-tickets/{ticket_id}/reject", {}, headers
        )

    def void_placement_ticket(self, ticket_id, headers):
        return self._request("POST", f"/placement-tickets/{ticket_id}/void", {}, headers)

    # --- standby claims ---
    def create_standby_claim(self, payload, headers):
        return self._request("POST", "/standby-claims", payload, headers)

    def get_standby_claim(self, claim_id, headers):
        return self._request("GET", f"/standby-claims/{claim_id}", headers=headers)

    def list_standby_claims(self, headers, params=None):
        return self._request("GET", "/standby-claims", headers=headers, params=params)

    def approve_standby_claim(self, claim_id, headers):
        return self._request("POST", f"/standby-claims/{claim_id}/approve", {}, headers)

    def deny_standby_claim(self, claim_id, headers):
        return self._request("POST", f"/standby-claims/{claim_id}/deny", {}, headers)

    # --- payment certificates ---
    def create_payment_certificate(self, payload, headers):
        return self._request("POST", "/payment-certificates", payload, headers)

    def get_payment_certificate(self, cert_id, headers):
        return self._request("GET", f"/payment-certificates/{cert_id}", headers=headers)

    def list_payment_certificates(self, headers, params=None):
        return self._request(
            "GET", "/payment-certificates", headers=headers, params=params
        )

    def submit_payment_certificate(self, cert_id, headers):
        return self._request(
            "POST", f"/payment-certificates/{cert_id}/submit", {}, headers
        )

    def certify_payment_certificate(self, cert_id, payload, headers):
        return self._request(
            "POST", f"/payment-certificates/{cert_id}/certify", payload, headers
        )

    def dispute_payment_certificate(self, cert_id, headers):
        return self._request(
            "POST", f"/payment-certificates/{cert_id}/dispute", {}, headers
        )

    def revise_payment_certificate(self, cert_id, headers):
        return self._request(
            "POST", f"/payment-certificates/{cert_id}/revise", {}, headers
        )

    def void_payment_certificate(self, cert_id, headers):
        return self._request("POST", f"/payment-certificates/{cert_id}/void", {}, headers)

    def pay_payment_certificate(self, cert_id, headers):
        return self._request("POST", f"/payment-certificates/{cert_id}/pay", {}, headers)


api_client = ApiClient()
