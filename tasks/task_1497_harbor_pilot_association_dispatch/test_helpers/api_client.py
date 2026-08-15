"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Pilots / endorsements / rotation board ----
    def create_pilot(self, payload, headers):
        return self._request("POST", "/pilotage/pilots", payload, headers)

    def get_pilot(self, pilot_id, headers):
        return self._request("GET", f"/pilotage/pilots/{pilot_id}", headers=headers)

    def create_endorsement(self, pilot_id, payload, headers):
        return self._request("POST", f"/pilotage/pilots/{pilot_id}/endorsements", payload, headers)

    def list_endorsements(self, pilot_id, headers, params=None):
        return self._request("GET", f"/pilotage/pilots/{pilot_id}/endorsements", headers=headers, params=params)

    def list_pilot_rotation_entries(self, pilot_id, headers, params=None):
        return self._request("GET", f"/pilotage/pilots/{pilot_id}/rotation-entries", headers=headers, params=params)

    def list_rotation_entries(self, headers, params=None):
        return self._request("GET", "/pilotage/rotation-entries", headers=headers, params=params)

    # ---- Vessel orders ----
    def create_order(self, payload, headers):
        return self._request("POST", "/pilotage/vessel-orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/pilotage/vessel-orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/pilotage/vessel-orders/{order_id}", headers=headers)

    def patch_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/pilotage/vessel-orders/{order_id}", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/pilotage/vessel-orders/{order_id}/cancel", headers=headers)

    def dispatch_order(self, order_id, payload, headers):
        return self._request("POST", f"/pilotage/vessel-orders/{order_id}/dispatch", payload, headers)

    # ---- Assignments ----
    def list_assignments(self, headers, params=None):
        return self._request("GET", "/pilotage/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/pilotage/assignments/{assignment_id}", headers=headers)

    def start_assignment(self, assignment_id, headers):
        return self._request("POST", f"/pilotage/assignments/{assignment_id}/start", headers=headers)

    def board_assignment(self, assignment_id, headers):
        return self._request("POST", f"/pilotage/assignments/{assignment_id}/board", headers=headers)

    def complete_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/pilotage/assignments/{assignment_id}/complete", payload, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/pilotage/assignments/{assignment_id}/cancel", headers=headers)

    def recall_assignment(self, assignment_id, headers):
        return self._request("POST", f"/pilotage/assignments/{assignment_id}/recall", headers=headers)

    def reassign_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/pilotage/assignments/{assignment_id}/reassign", payload, headers)

    # ---- Pilot boats ----
    def create_boat(self, payload, headers):
        return self._request("POST", "/pilotage/pilot-boats", payload, headers)

    def list_boats(self, headers, params=None):
        return self._request("GET", "/pilotage/pilot-boats", headers=headers, params=params)

    # ---- Tariff schedules ----
    def create_tariff_schedule(self, payload, headers):
        return self._request("POST", "/pilotage/tariff-schedules", payload, headers)

    def list_tariff_schedules(self, headers, params=None):
        return self._request("GET", "/pilotage/tariff-schedules", headers=headers, params=params)

    # ---- Invoices ----
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/pilotage/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/pilotage/invoices/{invoice_id}", headers=headers)

    def finalize_invoice(self, invoice_id, headers):
        return self._request("POST", f"/pilotage/invoices/{invoice_id}/finalize", headers=headers)

    # ---- Incidents ----
    def create_incident(self, payload, headers):
        return self._request("POST", "/pilotage/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/pilotage/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/pilotage/incidents/{incident_id}", headers=headers)

    def open_incident_review(self, incident_id, headers):
        return self._request("POST", f"/pilotage/incidents/{incident_id}/open-review", headers=headers)

    def dismiss_incident(self, incident_id, headers):
        return self._request("POST", f"/pilotage/incidents/{incident_id}/dismiss", headers=headers)

    def substantiate_incident(self, incident_id, headers):
        return self._request("POST", f"/pilotage/incidents/{incident_id}/substantiate", headers=headers)

    def close_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/pilotage/incidents/{incident_id}/close", payload, headers)

    # ---- Apprentices ----
    def create_apprentice(self, payload, headers):
        return self._request("POST", "/pilotage/apprentices", payload, headers)

    def list_apprentices(self, headers, params=None):
        return self._request("GET", "/pilotage/apprentices", headers=headers, params=params)

    def record_apprentice_progress(self, apprentice_id, payload, headers):
        return self._request("POST", f"/pilotage/apprentices/{apprentice_id}/record-progress", payload, headers)

    def advance_apprentice(self, apprentice_id, payload, headers):
        return self._request("POST", f"/pilotage/apprentices/{apprentice_id}/advance", payload, headers)

    # ---- Revenue distribution ----
    def create_distribution_run(self, payload, headers):
        return self._request("POST", "/pilotage/distribution-runs", payload, headers)

    def get_distribution_run(self, run_id, headers):
        return self._request("GET", f"/pilotage/distribution-runs/{run_id}", headers=headers)

    def settle_distribution_run(self, run_id, headers):
        return self._request("POST", f"/pilotage/distribution-runs/{run_id}/settle", headers=headers)

    def void_distribution_run(self, run_id, headers):
        return self._request("POST", f"/pilotage/distribution-runs/{run_id}/void", headers=headers)

    # ---- Logical clock ----
    def set_logical_clock(self, payload, headers):
        return self._request("POST", "/pilotage/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
