"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    def create_property(self, payload, headers):
        return self._request("POST", "/leasing/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/leasing/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/leasing/properties/{property_id}", headers=headers)

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------
    def create_agent(self, payload, headers):
        return self._request("POST", "/leasing/agents", payload, headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/leasing/agents", headers=headers, params=params)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/leasing/agents/{agent_id}", headers=headers)

    # ------------------------------------------------------------------
    # Floorplans
    # ------------------------------------------------------------------
    def create_floorplan(self, payload, headers):
        return self._request("POST", "/leasing/floorplans", payload, headers)

    def list_floorplans(self, headers, params=None):
        return self._request("GET", "/leasing/floorplans", headers=headers, params=params)

    def get_floorplan(self, floorplan_id, headers):
        return self._request("GET", f"/leasing/floorplans/{floorplan_id}", headers=headers)

    # ------------------------------------------------------------------
    # Pricing offers
    # ------------------------------------------------------------------
    def create_pricing_offer(self, payload, headers):
        return self._request("POST", "/leasing/pricing-offers", payload, headers)

    def list_pricing_offers(self, headers, params=None):
        return self._request("GET", "/leasing/pricing-offers", headers=headers, params=params)

    def get_pricing_offer(self, pricing_offer_id, headers):
        return self._request("GET", f"/leasing/pricing-offers/{pricing_offer_id}",
                             headers=headers)

    def publish_pricing_offer(self, pricing_offer_id, headers):
        return self._request("POST", f"/leasing/pricing-offers/{pricing_offer_id}/publish",
                             {}, headers)

    def retire_pricing_offer(self, pricing_offer_id, headers):
        return self._request("POST", f"/leasing/pricing-offers/{pricing_offer_id}/retire",
                             {}, headers)

    # ------------------------------------------------------------------
    # Inquiries
    # ------------------------------------------------------------------
    def create_inquiry(self, payload, headers):
        return self._request("POST", "/leasing/inquiries", payload, headers)

    def list_inquiries(self, headers, params=None):
        return self._request("GET", "/leasing/inquiries", headers=headers, params=params)

    def get_inquiry(self, inquiry_id, headers):
        return self._request("GET", f"/leasing/inquiries/{inquiry_id}", headers=headers)

    def claim_inquiry(self, inquiry_id, headers):
        return self._request("POST", f"/leasing/inquiries/{inquiry_id}/claim", {}, headers)

    def respond_inquiry(self, inquiry_id, headers):
        return self._request("POST", f"/leasing/inquiries/{inquiry_id}/respond", {}, headers)

    def mark_inquiry_lost(self, inquiry_id, headers):
        return self._request("POST", f"/leasing/inquiries/{inquiry_id}/mark-lost", {}, headers)

    # ------------------------------------------------------------------
    # Tours
    # ------------------------------------------------------------------
    def create_tour(self, payload, headers):
        return self._request("POST", "/leasing/tours", payload, headers)

    def list_tours(self, headers, params=None):
        return self._request("GET", "/leasing/tours", headers=headers, params=params)

    def get_tour(self, tour_id, headers):
        return self._request("GET", f"/leasing/tours/{tour_id}", headers=headers)

    def reschedule_tour(self, tour_id, payload, headers):
        return self._request("POST", f"/leasing/tours/{tour_id}/reschedule", payload, headers)

    def complete_tour(self, tour_id, outcome, headers):
        return self._request("POST", f"/leasing/tours/{tour_id}/complete",
                             {"outcome": outcome}, headers)

    def cancel_tour(self, tour_id, headers):
        return self._request("POST", f"/leasing/tours/{tour_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Waitlist entries
    # ------------------------------------------------------------------
    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/leasing/waitlist-entries", payload, headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/leasing/waitlist-entries", headers=headers, params=params)

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/leasing/waitlist-entries/{entry_id}", headers=headers)

    def promote_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/leasing/waitlist-entries/{entry_id}/promote",
                             {}, headers)

    def decline_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/leasing/waitlist-entries/{entry_id}/decline",
                             {}, headers)

    def cancel_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/leasing/waitlist-entries/{entry_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/leasing/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/leasing/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/leasing/applications/{application_id}", headers=headers)

    def decide_application(self, application_id, decision, headers):
        return self._request("POST", f"/leasing/applications/{application_id}/decide",
                             {"decision": decision}, headers)

    def rescreen_application(self, application_id, payload, headers):
        return self._request("POST", f"/leasing/applications/{application_id}/rescreen",
                             payload, headers)

    def clear_application_conditions(self, application_id, deposit_paid_cents, headers):
        return self._request("POST",
                             f"/leasing/applications/{application_id}/clear-conditions",
                             {"deposit_paid_cents": deposit_paid_cents}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/leasing/applications/{application_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # Leases
    # ------------------------------------------------------------------
    def create_lease(self, payload, headers):
        return self._request("POST", "/leasing/leases", payload, headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leasing/leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leasing/leases/{lease_id}", headers=headers)

    def sign_lease(self, lease_id, headers):
        return self._request("POST", f"/leasing/leases/{lease_id}/sign", {}, headers)

    def countersign_lease(self, lease_id, headers):
        return self._request("POST", f"/leasing/leases/{lease_id}/countersign", {}, headers)

    def cancel_lease(self, lease_id, headers):
        return self._request("POST", f"/leasing/leases/{lease_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Move-ins
    # ------------------------------------------------------------------
    def create_move_in(self, payload, headers):
        return self._request("POST", "/leasing/move-ins", payload, headers)

    def list_move_ins(self, headers, params=None):
        return self._request("GET", "/leasing/move-ins", headers=headers, params=params)

    def get_move_in(self, move_in_id, headers):
        return self._request("GET", f"/leasing/move-ins/{move_in_id}", headers=headers)

    def confirm_move_in_utilities(self, move_in_id, headers):
        return self._request("POST", f"/leasing/move-ins/{move_in_id}/confirm-utilities",
                             {}, headers)

    def complete_move_in(self, move_in_id, headers):
        return self._request("POST", f"/leasing/move-ins/{move_in_id}/complete", {}, headers)

    def cancel_move_in(self, move_in_id, headers):
        return self._request("POST", f"/leasing/move-ins/{move_in_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------
    def get_closing_report(self, headers, params=None):
        return self._request("GET", "/leasing/reports/closing", headers=headers, params=params)


api_client = ApiClient()
