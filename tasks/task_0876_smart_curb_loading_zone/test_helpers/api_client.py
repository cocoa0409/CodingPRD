"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Permittee ----
    def create_permittee(self, payload, headers):
        return self._request("POST", "/curb/permittees", payload, headers)

    def get_permittee(self, permittee_id, headers):
        return self._request("GET", f"/curb/permittees/{permittee_id}", headers=headers)

    # ---- PricingPolicy ----
    def create_pricing_policy(self, payload, headers):
        return self._request("POST", "/curb/pricing-policies", payload, headers)

    def get_pricing_policy(self, policy_id, headers):
        return self._request("GET", f"/curb/pricing-policies/{policy_id}", headers=headers)

    # ---- CurbZone ----
    def create_zone(self, payload, headers):
        return self._request("POST", "/curb/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/curb/zones/{zone_id}", headers=headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/curb/zones", headers=headers, params=params)

    def redesignate_zone(self, zone_id, payload, headers):
        return self._request("POST", f"/curb/zones/{zone_id}/redesignate", payload, headers)

    def set_zone_status(self, zone_id, target_status, headers):
        return self._request("POST", f"/curb/zones/{zone_id}/status", {"target_status": target_status}, headers)

    def get_map(self, headers, params=None):
        return self._request("GET", "/curb/map", headers=headers, params=params)

    # ---- CurbPermit ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/curb/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/curb/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/curb/permits", headers=headers, params=params)

    def submit_permit(self, permit_id, headers):
        return self._request("POST", f"/curb/permits/{permit_id}/submit", {}, headers)

    def review_permit(self, permit_id, headers):
        return self._request("POST", f"/curb/permits/{permit_id}/review", {}, headers)

    def request_changes_permit(self, permit_id, note, headers):
        return self._request("POST", f"/curb/permits/{permit_id}/request-changes", {"note": note}, headers)

    def approve_permit(self, permit_id, headers):
        return self._request("POST", f"/curb/permits/{permit_id}/approve", {}, headers)

    def deny_permit(self, permit_id, reason, headers):
        return self._request("POST", f"/curb/permits/{permit_id}/deny", {"reason": reason}, headers)

    def revoke_permit(self, permit_id, reason, headers):
        return self._request("POST", f"/curb/permits/{permit_id}/revoke", {"reason": reason}, headers)

    # ---- ScheduleWindow ----
    def create_schedule_window(self, payload, headers):
        return self._request("POST", "/curb/schedule-windows", payload, headers)

    def get_schedule_window(self, window_id, headers):
        return self._request("GET", f"/curb/schedule-windows/{window_id}", headers=headers)

    def list_schedule_windows(self, headers, params=None):
        return self._request("GET", "/curb/schedule-windows", headers=headers, params=params)

    # ---- Reservation ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/curb/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/curb/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/curb/reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, headers):
        return self._request("POST", f"/curb/reservations/{reservation_id}/confirm", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/curb/reservations/{reservation_id}/cancel", {}, headers)

    def fulfill_reservation(self, reservation_id, headers):
        return self._request("POST", f"/curb/reservations/{reservation_id}/fulfill", {}, headers)

    def no_show_reservation(self, reservation_id, headers):
        return self._request("POST", f"/curb/reservations/{reservation_id}/no-show", {}, headers)

    # ---- OccupancySession (sensor / system) ----
    def occupancy_enter(self, payload, headers):
        return self._request("POST", "/_sensor/occupancy-enter", payload, headers)

    def occupancy_exit(self, session_id, headers):
        return self._request("POST", "/_sensor/occupancy-exit", {"session_id": session_id}, headers)

    def get_occupancy_session(self, session_id, headers):
        return self._request("GET", f"/curb/occupancy-sessions/{session_id}", headers=headers)

    def list_occupancy_sessions(self, headers, params=None):
        return self._request("GET", "/curb/occupancy-sessions", headers=headers, params=params)

    # ---- Citation ----
    def create_citation(self, payload, headers):
        return self._request("POST", "/curb/citations", payload, headers)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/curb/citations/{citation_id}", headers=headers)

    def list_citations(self, headers, params=None):
        return self._request("GET", "/curb/citations", headers=headers, params=params)

    def pay_citation(self, citation_id, headers):
        return self._request("POST", f"/curb/citations/{citation_id}/pay", {}, headers)

    def dispute_citation(self, citation_id, reason, headers):
        return self._request("POST", f"/curb/citations/{citation_id}/dispute", {"reason": reason}, headers)

    def adjudicate_citation(self, citation_id, decision, headers):
        return self._request("POST", f"/curb/citations/{citation_id}/adjudicate", {"decision": decision}, headers)

    # ---- CurbEvent ----
    def create_event(self, payload, headers):
        return self._request("POST", "/curb/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/curb/events/{event_id}", headers=headers)

    def activate_event(self, event_id, headers):
        return self._request("POST", f"/curb/events/{event_id}/activate", {}, headers)

    def close_event(self, event_id, headers):
        return self._request("POST", f"/curb/events/{event_id}/close", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/curb/events/{event_id}/cancel", {}, headers)

    # ---- LedgerEntry / Revenue ----
    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/curb/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/curb/ledger-entries", headers=headers, params=params)

    def get_revenue(self, headers, params=None):
        return self._request("GET", "/curb/revenue", headers=headers, params=params)


api_client = ApiClient()
