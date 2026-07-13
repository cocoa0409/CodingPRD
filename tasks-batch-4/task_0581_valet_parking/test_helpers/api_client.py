"""API client: one method per endpoint defined in the PRD (§4). All paths under /valet."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Venue ────────────────────────────────────────────────────────────
    def create_venue(self, payload, headers):
        return self._request("POST", "/valet/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/valet/venues/{venue_id}", headers=headers)

    # ── Event ────────────────────────────────────────────────────────────
    def create_event(self, payload, headers):
        return self._request("POST", "/valet/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/valet/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/valet/events", headers=headers, params=params)

    def activate_event(self, event_id, headers):
        return self._request("POST", f"/valet/events/{event_id}/activate", {}, headers)

    def close_event(self, event_id, headers):
        return self._request("POST", f"/valet/events/{event_id}/close", {}, headers)

    # ── Lot ──────────────────────────────────────────────────────────────
    def create_lot(self, payload, headers):
        return self._request("POST", "/valet/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/valet/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/valet/lots", headers=headers, params=params)

    # ── LaneAssignment ───────────────────────────────────────────────────
    def create_lane_assignment(self, payload, headers):
        return self._request("POST", "/valet/lane-assignments", payload, headers)

    def get_lane_assignment(self, lane_id, headers):
        return self._request("GET", f"/valet/lane-assignments/{lane_id}", headers=headers)

    def list_lane_assignments(self, headers, params=None):
        return self._request("GET", "/valet/lane-assignments", headers=headers, params=params)

    # ── Attendant ────────────────────────────────────────────────────────
    def create_attendant(self, payload, headers):
        return self._request("POST", "/valet/attendants", payload, headers)

    def get_attendant(self, attendant_id, headers):
        return self._request("GET", f"/valet/attendants/{attendant_id}", headers=headers)

    def list_attendants(self, headers, params=None):
        return self._request("GET", "/valet/attendants", headers=headers, params=params)

    # ── Shift ────────────────────────────────────────────────────────────
    def create_shift(self, payload, headers):
        return self._request("POST", "/valet/shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/valet/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/valet/shifts", headers=headers, params=params)

    def start_shift(self, shift_id, headers):
        return self._request("POST", f"/valet/shifts/{shift_id}/start", {}, headers)

    def close_shift(self, shift_id, headers):
        return self._request("POST", f"/valet/shifts/{shift_id}/close", {}, headers)

    def record_tips(self, shift_id, payload, headers):
        return self._request("POST", f"/valet/shifts/{shift_id}/tips", payload, headers)

    # ── Ticket ───────────────────────────────────────────────────────────
    def create_ticket(self, payload, headers):
        return self._request("POST", "/valet/tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/valet/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/valet/tickets", headers=headers, params=params)

    def checkout_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/valet/tickets/{ticket_id}/checkout", payload, headers)

    def create_validation(self, ticket_id, payload, headers):
        return self._request("POST", f"/valet/tickets/{ticket_id}/validations", payload, headers)

    # ── ValidationGrant ──────────────────────────────────────────────────
    def get_validation_grant(self, grant_id, headers):
        return self._request("GET", f"/valet/validation-grants/{grant_id}", headers=headers)

    def list_validation_grants(self, headers, params=None):
        return self._request("GET", "/valet/validation-grants", headers=headers, params=params)

    def reverse_validation_grant(self, grant_id, headers):
        return self._request("POST", f"/valet/validation-grants/{grant_id}/reverse", {}, headers)

    # ── RetrievalRequest ─────────────────────────────────────────────────
    def create_retrieval_request(self, payload, headers):
        return self._request("POST", "/valet/retrieval-requests", payload, headers)

    def get_retrieval_request(self, retrieval_id, headers):
        return self._request("GET", f"/valet/retrieval-requests/{retrieval_id}", headers=headers)

    def list_retrieval_requests(self, headers, params=None):
        return self._request("GET", "/valet/retrieval-requests", headers=headers, params=params)

    def assign_retrieval(self, retrieval_id, payload, headers):
        return self._request("POST", f"/valet/retrieval-requests/{retrieval_id}/assign", payload, headers)

    def stage_retrieval(self, retrieval_id, headers):
        return self._request("POST", f"/valet/retrieval-requests/{retrieval_id}/stage", {}, headers)

    def ready_retrieval(self, retrieval_id, payload, headers):
        return self._request("POST", f"/valet/retrieval-requests/{retrieval_id}/ready", payload, headers)

    def revert_retrieval(self, retrieval_id, headers):
        return self._request("POST", f"/valet/retrieval-requests/{retrieval_id}/revert", {}, headers)

    def complete_retrieval(self, retrieval_id, headers):
        return self._request("POST", f"/valet/retrieval-requests/{retrieval_id}/complete", {}, headers)

    # ── DamageClaim ──────────────────────────────────────────────────────
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/valet/damage-claims", payload, headers)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/valet/damage-claims/{claim_id}", headers=headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", "/valet/damage-claims", headers=headers, params=params)

    def approve_damage_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/valet/damage-claims/{claim_id}/approve", payload, headers)

    def deny_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/valet/damage-claims/{claim_id}/deny", {}, headers)

    def settle_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/valet/damage-claims/{claim_id}/settle", {}, headers)

    # ── ReconciliationReport ─────────────────────────────────────────────
    def create_reconciliation_report(self, payload, headers):
        return self._request("POST", "/valet/reconciliation-reports", payload, headers)

    def get_reconciliation_report(self, report_id, headers):
        return self._request("GET", f"/valet/reconciliation-reports/{report_id}", headers=headers)

    def list_reconciliation_reports(self, headers, params=None):
        return self._request("GET", "/valet/reconciliation-reports", headers=headers, params=params)

    def finalize_reconciliation_report(self, report_id, payload, headers):
        return self._request("POST", f"/valet/reconciliation-reports/{report_id}/finalize", payload, headers)


api_client = ApiClient()
