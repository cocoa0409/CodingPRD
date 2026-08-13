"""API client: one method per endpoint defined in the PRD endpoint catalogue (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Farms ---
    def create_farm(self, payload, headers):
        return self._request("POST", "/glean/farms", payload, headers)

    def list_farms(self, headers, params=None):
        return self._request("GET", "/glean/farms", headers=headers, params=params)

    def get_farm(self, farm_id, headers):
        return self._request("GET", f"/glean/farms/{farm_id}", headers=headers)

    def list_farm_receipts(self, farm_id, headers, params=None):
        return self._request("GET", f"/glean/farms/{farm_id}/receipts", headers=headers, params=params)

    def list_farm_offers(self, farm_id, headers, params=None):
        return self._request("GET", f"/glean/farms/{farm_id}/offers", headers=headers, params=params)

    # --- Surplus offers ---
    def create_offer(self, payload, headers):
        return self._request("POST", "/glean/offers", payload, headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/glean/offers", headers=headers, params=params)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/glean/offers/{offer_id}", headers=headers)

    def cancel_offer(self, offer_id, headers):
        return self._request("POST", f"/glean/offers/{offer_id}/cancel", {}, headers)

    def close_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/glean/offers/{offer_id}/close", payload, headers)

    def get_offer_receipt(self, offer_id, headers):
        return self._request("GET", f"/glean/offers/{offer_id}/receipt", headers=headers)

    # --- Volunteers ---
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/glean/volunteers", payload, headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/glean/volunteers", headers=headers, params=params)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/glean/volunteers/{volunteer_id}", headers=headers)

    def reinstate_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/glean/volunteers/{volunteer_id}/reinstate", {}, headers)

    def list_volunteer_waivers(self, volunteer_id, headers, params=None):
        return self._request("GET", f"/glean/volunteers/{volunteer_id}/waivers", headers=headers, params=params)

    # --- Waivers ---
    def create_waiver(self, payload, headers):
        return self._request("POST", "/glean/waivers", payload, headers)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/glean/waivers/{waiver_id}", headers=headers)

    def list_event_waivers(self, event_id, headers, params=None):
        return self._request("GET", f"/glean/events/{event_id}/waivers", headers=headers, params=params)

    # --- Agencies ---
    def create_agency(self, payload, headers):
        return self._request("POST", "/glean/agencies", payload, headers)

    def list_agencies(self, headers, params=None):
        return self._request("GET", "/glean/agencies", headers=headers, params=params)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/glean/agencies/{agency_id}", headers=headers)

    def list_agency_distributions(self, agency_id, headers, params=None):
        return self._request("GET", f"/glean/agencies/{agency_id}/distributions", headers=headers, params=params)

    # --- Containers ---
    def create_container(self, payload, headers):
        return self._request("POST", "/glean/containers", payload, headers)

    def list_containers(self, headers, params=None):
        return self._request("GET", "/glean/containers", headers=headers, params=params)

    def get_container(self, container_id, headers):
        return self._request("GET", f"/glean/containers/{container_id}", headers=headers)

    # --- Vehicles ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/glean/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/glean/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/glean/vehicles/{vehicle_id}", headers=headers)

    # --- Glean events ---
    def create_event(self, payload, headers):
        return self._request("POST", "/glean/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/glean/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/glean/events/{event_id}", headers=headers)

    def publish_event(self, event_id, headers):
        return self._request("POST", f"/glean/events/{event_id}/publish", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/glean/events/{event_id}/cancel", {}, headers)

    def start_event(self, event_id, headers):
        return self._request("POST", f"/glean/events/{event_id}/start", {}, headers)

    def finish_event(self, event_id, headers):
        return self._request("POST", f"/glean/events/{event_id}/finish", {}, headers)

    def reconcile_event(self, event_id, headers):
        return self._request("POST", f"/glean/events/{event_id}/reconcile", {}, headers)

    # --- Crew assignments ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/glean/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/glean/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/glean/assignments/{assignment_id}", headers=headers)

    def confirm_assignment(self, assignment_id, headers):
        return self._request("POST", f"/glean/assignments/{assignment_id}/confirm", {}, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/glean/assignments/{assignment_id}/decline", {}, headers)

    def complete_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/glean/assignments/{assignment_id}/complete", payload, headers)

    # --- Harvest lots ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/glean/lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/glean/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/glean/lots/{lot_id}", headers=headers)

    def verify_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/glean/lots/{lot_id}/verify", payload, headers)

    def reject_lot(self, lot_id, headers):
        return self._request("POST", f"/glean/lots/{lot_id}/reject", {}, headers)

    # --- Distributions ---
    def create_distribution(self, payload, headers):
        return self._request("POST", "/glean/distributions", payload, headers)

    def list_distributions(self, headers, params=None):
        return self._request("GET", "/glean/distributions", headers=headers, params=params)

    def get_distribution(self, distribution_id, headers):
        return self._request("GET", f"/glean/distributions/{distribution_id}", headers=headers)

    def deliver_distribution(self, distribution_id, payload, headers):
        return self._request("POST", f"/glean/distributions/{distribution_id}/deliver", payload, headers)

    def cancel_distribution(self, distribution_id, headers):
        return self._request("POST", f"/glean/distributions/{distribution_id}/cancel", {}, headers)

    # --- Temperature logs ---
    def create_templog(self, payload, headers):
        return self._request("POST", "/glean/templogs", payload, headers)

    def list_templogs(self, headers, params=None):
        return self._request("GET", "/glean/templogs", headers=headers, params=params)

    def get_templog(self, templog_id, headers):
        return self._request("GET", f"/glean/templogs/{templog_id}", headers=headers)

    # --- Food-safety incidents ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/glean/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/glean/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/glean/incidents/{incident_id}", headers=headers)

    def resolve_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/glean/incidents/{incident_id}/resolve", payload, headers)

    # --- Grant reports ---
    def create_report(self, payload, headers):
        return self._request("POST", "/glean/reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/glean/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/glean/reports/{report_id}", headers=headers)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/glean/reports/{report_id}/submit", {}, headers)

    def accept_report(self, report_id, headers):
        return self._request("POST", f"/glean/reports/{report_id}/accept", {}, headers)

    def return_report(self, report_id, headers):
        return self._request("POST", f"/glean/reports/{report_id}/return", {}, headers)

    # --- Logical clock (test-driving capability, PRD §2.5) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
