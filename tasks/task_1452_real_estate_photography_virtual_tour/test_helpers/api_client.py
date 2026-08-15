"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (PRD §2.10) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Markets ---
    def create_market(self, payload, headers):
        return self._request("POST", "/markets", payload, headers)

    def list_markets(self, headers, params=None):
        return self._request("GET", "/markets", headers=headers, params=params)

    def get_market(self, market_id, headers):
        return self._request("GET", f"/markets/{market_id}", headers=headers)

    def patch_market(self, market_id, payload, headers):
        return self._request("PATCH", f"/markets/{market_id}", payload, headers)

    # --- Photographers ---
    def create_photographer(self, payload, headers):
        return self._request("POST", "/photographers", payload, headers)

    def list_photographers(self, headers, params=None):
        return self._request("GET", "/photographers", headers=headers, params=params)

    def get_photographer(self, photographer_id, headers):
        return self._request("GET", f"/photographers/{photographer_id}", headers=headers)

    def patch_photographer(self, photographer_id, payload, headers):
        return self._request("PATCH", f"/photographers/{photographer_id}", payload, headers)

    def list_photographer_bookings(self, photographer_id, headers, params=None):
        return self._request("GET", f"/photographers/{photographer_id}/shoot-bookings", headers=headers, params=params)

    # --- ClientAgents ---
    def create_client_agent(self, payload, headers):
        return self._request("POST", "/client-agents", payload, headers)

    def list_client_agents(self, headers, params=None):
        return self._request("GET", "/client-agents", headers=headers, params=params)

    def get_client_agent(self, agent_id, headers):
        return self._request("GET", f"/client-agents/{agent_id}", headers=headers)

    def list_agent_bookings(self, agent_id, headers, params=None):
        return self._request("GET", f"/client-agents/{agent_id}/shoot-bookings", headers=headers, params=params)

    # --- ShootBookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/shoot-bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/shoot-bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/shoot-bookings/{booking_id}", headers=headers)

    def patch_booking(self, booking_id, payload, headers):
        return self._request("PATCH", f"/shoot-bookings/{booking_id}", payload, headers)

    def submit_booking(self, booking_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/submit", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/cancel", {}, headers)

    def assign_booking(self, booking_id, photographer_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/assign", {"photographer_id": photographer_id}, headers)

    def unassign_booking(self, booking_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/unassign", {}, headers)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/confirm", {}, headers)

    def mark_shot(self, booking_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/mark-shot", {}, headers)

    def deliver(self, booking_id, payload, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/deliver", payload, headers)

    def accept_booking(self, booking_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/accept", {}, headers)

    def reschedule_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/reschedule", payload, headers)

    # --- ReadinessChecklistItems ---
    def list_checklist_items(self, booking_id, headers, params=None):
        return self._request("GET", f"/shoot-bookings/{booking_id}/checklist-items", headers=headers, params=params)

    def patch_checklist_item(self, booking_id, item_id, checked, headers):
        return self._request("PATCH", f"/shoot-bookings/{booking_id}/checklist-items/{item_id}", {"checked": checked}, headers)

    # --- AddOns ---
    def create_addon(self, booking_id, kind, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/addons", {"kind": kind}, headers)

    def list_addons(self, booking_id, headers, params=None):
        return self._request("GET", f"/shoot-bookings/{booking_id}/addons", headers=headers, params=params)

    def get_addon(self, booking_id, addon_id, headers):
        return self._request("GET", f"/shoot-bookings/{booking_id}/addons/{addon_id}", headers=headers)

    def cancel_addon(self, booking_id, addon_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/addons/{addon_id}/cancel", {}, headers)

    # --- AirspaceAuthorizations ---
    def list_authorizations_global(self, headers, params=None):
        return self._request("GET", "/airspace-authorizations", headers=headers, params=params)

    def get_authorization_global(self, auth_id, headers):
        return self._request("GET", f"/airspace-authorizations/{auth_id}", headers=headers)

    def list_authorizations(self, booking_id, headers, params=None):
        return self._request("GET", f"/shoot-bookings/{booking_id}/airspace-authorizations", headers=headers, params=params)

    def get_authorization(self, booking_id, auth_id, headers):
        return self._request("GET", f"/shoot-bookings/{booking_id}/airspace-authorizations/{auth_id}", headers=headers)

    def approve_authorization(self, booking_id, auth_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/airspace-authorizations/{auth_id}/approve", {}, headers)

    def reject_authorization(self, booking_id, auth_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/airspace-authorizations/{auth_id}/reject", {}, headers)

    def resubmit_authorization(self, booking_id, auth_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/airspace-authorizations/{auth_id}/resubmit", {}, headers)

    # --- AssetBundles ---
    def list_bundles(self, booking_id, headers, params=None):
        return self._request("GET", f"/shoot-bookings/{booking_id}/asset-bundles", headers=headers, params=params)

    def get_bundle(self, booking_id, bundle_id, headers):
        return self._request("GET", f"/shoot-bookings/{booking_id}/asset-bundles/{bundle_id}", headers=headers)

    # --- RevisionRequests ---
    def list_revisions_global(self, headers, params=None):
        return self._request("GET", "/revisions", headers=headers, params=params)

    def get_revision_global(self, revision_id, headers):
        return self._request("GET", f"/revisions/{revision_id}", headers=headers)

    def create_revision(self, booking_id, bundle_id, notes, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/revisions", {"bundle_id": bundle_id, "notes": notes}, headers)

    def list_revisions(self, booking_id, headers, params=None):
        return self._request("GET", f"/shoot-bookings/{booking_id}/revisions", headers=headers, params=params)

    def get_revision(self, booking_id, revision_id, headers):
        return self._request("GET", f"/shoot-bookings/{booking_id}/revisions/{revision_id}", headers=headers)

    def claim_revision(self, booking_id, revision_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/revisions/{revision_id}/claim", {}, headers)

    def dismiss_revision(self, booking_id, revision_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/revisions/{revision_id}/dismiss", {}, headers)

    # --- VirtualTour ---
    def get_virtual_tour(self, booking_id, headers):
        return self._request("GET", f"/shoot-bookings/{booking_id}/virtual-tour", headers=headers)

    def suspend_tour(self, booking_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/virtual-tour/suspend", {}, headers)

    def resume_tour(self, booking_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/virtual-tour/resume", {}, headers)

    def unpublish_tour(self, booking_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/virtual-tour/unpublish", {}, headers)

    # --- LicenseGrant ---
    def get_license(self, booking_id, headers):
        return self._request("GET", f"/shoot-bookings/{booking_id}/license", headers=headers)

    def suspend_license(self, booking_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/license/suspend", {}, headers)

    def reinstate_license(self, booking_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/license/reinstate", {}, headers)

    def revoke_license(self, booking_id, headers):
        return self._request("POST", f"/shoot-bookings/{booking_id}/license/revoke", {}, headers)

    # --- RescheduleEvents ---
    def list_reschedule_events(self, booking_id, headers, params=None):
        return self._request("GET", f"/shoot-bookings/{booking_id}/reschedule-events", headers=headers, params=params)


api_client = ApiClient()
