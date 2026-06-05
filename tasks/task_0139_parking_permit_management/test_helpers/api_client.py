"""API client: one method per endpoint defined in the Parking & Permit PRD.

Subclasses GenericApiClient; the base _request() handles envelope transport.
All paths are rooted at the /parking prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- administrative clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/parking/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Garage ----
    def create_garage(self, payload, headers):
        return self._request("POST", "/parking/garages", payload, headers)

    def get_garage(self, garage_id, headers):
        return self._request("GET", f"/parking/garages/{garage_id}", headers=headers)

    def update_garage(self, garage_id, payload, headers):
        return self._request("PATCH", f"/parking/garages/{garage_id}", payload, headers)

    def list_garage_zones(self, garage_id, headers, params=None):
        return self._request("GET", f"/parking/garages/{garage_id}/zones", headers=headers, params=params)

    def list_garage_event_pricing(self, garage_id, headers, params=None):
        return self._request("GET", f"/parking/garages/{garage_id}/event-pricing", headers=headers, params=params)

    def list_garage_merchants(self, garage_id, headers, params=None):
        return self._request("GET", f"/parking/garages/{garage_id}/merchants", headers=headers, params=params)

    def list_garage_sessions(self, garage_id, headers, params=None):
        return self._request("GET", f"/parking/garages/{garage_id}/sessions", headers=headers, params=params)

    def list_garage_citations(self, garage_id, headers, params=None):
        return self._request("GET", f"/parking/garages/{garage_id}/citations", headers=headers, params=params)

    def list_garage_validations(self, garage_id, headers, params=None):
        return self._request("GET", f"/parking/garages/{garage_id}/validations", headers=headers, params=params)

    def list_garage_plate_reads(self, garage_id, headers, params=None):
        return self._request("GET", f"/parking/garages/{garage_id}/plate-reads", headers=headers, params=params)

    # ---- Zone ----
    def create_zone(self, payload, headers):
        return self._request("POST", "/parking/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/parking/zones/{zone_id}", headers=headers)

    def list_zone_spaces(self, zone_id, headers, params=None):
        return self._request("GET", f"/parking/zones/{zone_id}/spaces", headers=headers, params=params)

    def list_zone_permits(self, zone_id, headers, params=None):
        return self._request("GET", f"/parking/zones/{zone_id}/permits", headers=headers, params=params)

    def list_zone_waitlist(self, zone_id, headers, params=None):
        return self._request("GET", f"/parking/zones/{zone_id}/waitlist", headers=headers, params=params)

    def add_waitlist_entry(self, zone_id, payload, headers):
        return self._request("POST", f"/parking/zones/{zone_id}/waitlist", payload, headers)

    def promote_waitlist(self, zone_id, headers):
        return self._request("POST", f"/parking/zones/{zone_id}/promote-waitlist", {}, headers)

    def list_zone_plate_reads(self, zone_id, headers, params=None):
        return self._request("GET", f"/parking/zones/{zone_id}/plate-reads", headers=headers, params=params)

    # ---- Waitlist entry ----
    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/parking/waitlist-entries/{entry_id}", headers=headers)

    def cancel_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/parking/waitlist-entries/{entry_id}/cancel", {}, headers)

    # ---- Space ----
    def create_space(self, payload, headers):
        return self._request("POST", "/parking/spaces", payload, headers)

    def get_space(self, space_id, headers):
        return self._request("GET", f"/parking/spaces/{space_id}", headers=headers)

    def list_space_sessions(self, space_id, headers, params=None):
        return self._request("GET", f"/parking/spaces/{space_id}/sessions", headers=headers, params=params)

    # ---- RatePlan ----
    def create_rate_plan(self, payload, headers):
        return self._request("POST", "/parking/rate-plans", payload, headers)

    def get_rate_plan(self, rate_plan_id, headers):
        return self._request("GET", f"/parking/rate-plans/{rate_plan_id}", headers=headers)

    def list_rate_plan_zones(self, rate_plan_id, headers, params=None):
        return self._request("GET", f"/parking/rate-plans/{rate_plan_id}/zones", headers=headers, params=params)

    # ---- EventPricing ----
    def create_event_pricing(self, payload, headers):
        return self._request("POST", "/parking/event-pricing", payload, headers)

    def get_event_pricing(self, ep_id, headers):
        return self._request("GET", f"/parking/event-pricing/{ep_id}", headers=headers)

    def publish_event_pricing(self, ep_id, headers):
        return self._request("POST", f"/parking/event-pricing/{ep_id}/publish", {}, headers)

    # ---- Motorist ----
    def create_motorist(self, payload, headers):
        return self._request("POST", "/parking/motorists", payload, headers)

    def get_motorist(self, motorist_id, headers):
        return self._request("GET", f"/parking/motorists/{motorist_id}", headers=headers)

    def list_motorist_permits(self, motorist_id, headers, params=None):
        return self._request("GET", f"/parking/motorists/{motorist_id}/permits", headers=headers, params=params)

    def list_motorist_waitlist_entries(self, motorist_id, headers, params=None):
        return self._request("GET", f"/parking/motorists/{motorist_id}/waitlist-entries", headers=headers, params=params)

    def list_motorist_citations(self, motorist_id, headers, params=None):
        return self._request("GET", f"/parking/motorists/{motorist_id}/citations", headers=headers, params=params)

    def list_motorist_appeals(self, motorist_id, headers, params=None):
        return self._request("GET", f"/parking/motorists/{motorist_id}/appeals", headers=headers, params=params)

    # ---- Permit ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/parking/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/parking/permits/{permit_id}", headers=headers)

    def activate_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/parking/permits/{permit_id}/activate", payload, headers)

    def reject_permit(self, permit_id, headers):
        return self._request("POST", f"/parking/permits/{permit_id}/reject", {}, headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/parking/permits/{permit_id}/revoke", {}, headers)

    def expire_check_permit(self, permit_id, headers):
        return self._request("POST", f"/parking/permits/{permit_id}/expire-check", {}, headers)

    def list_permit_waitlist_entry(self, permit_id, headers, params=None):
        return self._request("GET", f"/parking/permits/{permit_id}/waitlist-entry", headers=headers, params=params)

    def list_permit_sessions(self, permit_id, headers, params=None):
        return self._request("GET", f"/parking/permits/{permit_id}/sessions", headers=headers, params=params)

    def list_permit_plate_reads(self, permit_id, headers, params=None):
        return self._request("GET", f"/parking/permits/{permit_id}/plate-reads", headers=headers, params=params)

    # ---- Merchant + Validation ----
    def create_merchant(self, payload, headers):
        return self._request("POST", "/parking/merchants", payload, headers)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/parking/merchants/{merchant_id}", headers=headers)

    def list_merchant_validations(self, merchant_id, headers, params=None):
        return self._request("GET", f"/parking/merchants/{merchant_id}/validations", headers=headers, params=params)

    def create_validation(self, payload, headers):
        return self._request("POST", "/parking/validations", payload, headers)

    def get_validation(self, validation_id, headers):
        return self._request("GET", f"/parking/validations/{validation_id}", headers=headers)

    def list_validation_sessions(self, validation_id, headers, params=None):
        return self._request("GET", f"/parking/validations/{validation_id}/sessions", headers=headers, params=params)

    # ---- AccessSession ----
    def create_session(self, payload, headers):
        return self._request("POST", "/parking/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/parking/sessions/{session_id}", headers=headers)

    def exit_session(self, session_id, payload, headers):
        return self._request("POST", f"/parking/sessions/{session_id}/exit", payload, headers)

    def void_session(self, session_id, headers):
        return self._request("POST", f"/parking/sessions/{session_id}/void", {}, headers)

    # ---- LPR / PlateRead ----
    def create_plate_read(self, payload, headers):
        return self._request("POST", "/parking/plate-reads", payload, headers)

    def get_plate_read(self, plate_read_id, headers):
        return self._request("GET", f"/parking/plate-reads/{plate_read_id}", headers=headers)

    def list_plate_read_citations(self, plate_read_id, headers, params=None):
        return self._request("GET", f"/parking/plate-reads/{plate_read_id}/citations", headers=headers, params=params)

    # ---- Citation + Appeal ----
    def create_citation(self, payload, headers):
        return self._request("POST", "/parking/citations", payload, headers)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/parking/citations/{citation_id}", headers=headers)

    def pay_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/parking/citations/{citation_id}/pay", payload, headers)

    def list_citation_appeals(self, citation_id, headers, params=None):
        return self._request("GET", f"/parking/citations/{citation_id}/appeals", headers=headers, params=params)

    def create_appeal(self, payload, headers):
        return self._request("POST", "/parking/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/parking/appeals/{appeal_id}", headers=headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/parking/appeals/{appeal_id}/decide", payload, headers)


api_client = ApiClient()
