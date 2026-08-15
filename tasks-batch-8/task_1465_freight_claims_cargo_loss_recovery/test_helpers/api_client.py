"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Carrier ---
    def create_carrier(self, payload, headers):
        return self._request("POST", "/freight-claims/carriers", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/freight-claims/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/freight-claims/carriers/{carrier_id}", headers=headers)

    def suspend_carrier(self, carrier_id, headers):
        return self._request("POST", f"/freight-claims/carriers/{carrier_id}/suspend", headers=headers)

    def reinstate_carrier(self, carrier_id, headers):
        return self._request("POST", f"/freight-claims/carriers/{carrier_id}/reinstate", headers=headers)

    def terminate_carrier(self, carrier_id, headers):
        return self._request("POST", f"/freight-claims/carriers/{carrier_id}/terminate", headers=headers)

    # --- Lane ---
    def create_lane(self, payload, headers):
        return self._request("POST", "/freight-claims/lanes", payload, headers)

    def list_lanes(self, headers, params=None):
        return self._request("GET", "/freight-claims/lanes", headers=headers, params=params)

    def get_lane(self, lane_id, headers):
        return self._request("GET", f"/freight-claims/lanes/{lane_id}", headers=headers)

    def retire_lane(self, lane_id, headers):
        return self._request("POST", f"/freight-claims/lanes/{lane_id}/retire", headers=headers)

    # --- CarrierLaneAssignment ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/freight-claims/carrier-lane-assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/freight-claims/carrier-lane-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/freight-claims/carrier-lane-assignments/{assignment_id}", headers=headers)

    # --- Shipment ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/freight-claims/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/freight-claims/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/freight-claims/shipments/{shipment_id}", headers=headers)

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/freight-claims/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/freight-claims/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/freight-claims/claims/{claim_id}", headers=headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/submit", headers=headers)

    def acknowledge_claim(self, claim_id, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/acknowledge", headers=headers)

    def decline_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/decline", payload, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/withdraw", headers=headers)

    def close_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/close", payload, headers)

    def get_liability_preview(self, claim_id, headers):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/liability-preview", headers=headers)

    # --- ClaimDocument ---
    def attach_document(self, claim_id, payload, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/documents", payload, headers)

    def list_documents(self, claim_id, headers, params=None):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/documents", headers=headers, params=params)

    def get_document(self, claim_id, doc_id, headers):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/documents/{doc_id}", headers=headers)

    def verify_document(self, claim_id, doc_id, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/documents/{doc_id}/verify", headers=headers)

    def reject_document(self, claim_id, doc_id, payload, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/documents/{doc_id}/reject", payload, headers)

    # --- LiabilityAssessment ---
    def create_assessment(self, claim_id, payload, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/assessments", payload, headers)

    def list_assessments(self, claim_id, headers, params=None):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/assessments", headers=headers, params=params)

    def get_assessment(self, claim_id, assessment_id, headers):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/assessments/{assessment_id}", headers=headers)

    def approve_assessment(self, claim_id, assessment_id, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/assessments/{assessment_id}/approve", headers=headers)

    # --- SalvageDisposition ---
    def schedule_salvage(self, claim_id, payload, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/salvage", payload, headers)

    def list_salvage(self, claim_id, headers, params=None):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/salvage", headers=headers, params=params)

    def get_salvage(self, claim_id, salvage_id, headers):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/salvage/{salvage_id}", headers=headers)

    def execute_salvage(self, claim_id, salvage_id, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/salvage/{salvage_id}/execute", headers=headers)

    def cancel_salvage(self, claim_id, salvage_id, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/salvage/{salvage_id}/cancel", headers=headers)

    # --- Appeal ---
    def open_appeal(self, claim_id, payload, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/appeals", payload, headers)

    def list_appeals(self, claim_id, headers, params=None):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/appeals", headers=headers, params=params)

    def get_appeal(self, claim_id, appeal_id, headers):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/appeals/{appeal_id}", headers=headers)

    def escalate_appeal(self, claim_id, appeal_id, payload, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/appeals/{appeal_id}/escalate", payload, headers)

    def decide_appeal(self, claim_id, appeal_id, payload, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/appeals/{appeal_id}/decide", payload, headers)

    # --- Settlement ---
    def create_settlement(self, claim_id, payload, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/settlements", payload, headers)

    def list_settlements(self, claim_id, headers, params=None):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/settlements", headers=headers, params=params)

    def get_settlement(self, claim_id, settlement_id, headers):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/settlements/{settlement_id}", headers=headers)

    def accept_settlement(self, claim_id, settlement_id, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/settlements/{settlement_id}/accept", headers=headers)

    def counter_settlement(self, claim_id, settlement_id, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/settlements/{settlement_id}/counter", headers=headers)

    def reject_settlement(self, claim_id, settlement_id, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/settlements/{settlement_id}/reject", headers=headers)

    def withdraw_settlement(self, claim_id, settlement_id, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/settlements/{settlement_id}/withdraw", headers=headers)

    # --- SubrogationCase ---
    def open_subrogation(self, claim_id, payload, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/subrogation", payload, headers)

    def list_subrogation(self, claim_id, headers, params=None):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/subrogation", headers=headers, params=params)

    def get_subrogation(self, claim_id, case_id, headers):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/subrogation/{case_id}", headers=headers)

    def send_demand(self, claim_id, case_id, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/subrogation/{case_id}/send-demand", headers=headers)

    def litigate_subrogation(self, claim_id, case_id, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/subrogation/{case_id}/litigate", headers=headers)

    def settle_subrogation(self, claim_id, case_id, payload, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/subrogation/{case_id}/settle", payload, headers)

    def close_unrecoverable(self, claim_id, case_id, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/subrogation/{case_id}/close-unrecoverable", headers=headers)

    # --- Reserve ---
    def post_reserve(self, claim_id, payload, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/reserves", payload, headers)

    def list_reserves(self, claim_id, headers, params=None):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/reserves", headers=headers, params=params)

    def get_reserve(self, claim_id, reserve_id, headers):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/reserves/{reserve_id}", headers=headers)

    def release_reserve(self, claim_id, reserve_id, headers):
        return self._request("POST", f"/freight-claims/claims/{claim_id}/reserves/{reserve_id}/release", headers=headers)

    # --- ClaimEvent log ---
    def list_claim_events(self, claim_id, headers, params=None):
        return self._request("GET", f"/freight-claims/claims/{claim_id}/events", headers=headers, params=params)

    # --- ClaimsCalendar ---
    def create_calendar_row(self, payload, headers):
        return self._request("POST", "/freight-claims/calendar", payload, headers)

    def list_calendar(self, headers, params=None):
        return self._request("GET", "/freight-claims/calendar", headers=headers, params=params)

    # --- Analytics ---
    def get_carrier_claim_ratio(self, headers, params=None):
        return self._request("GET", "/freight-claims/analytics/carrier-claim-ratio", headers=headers, params=params)

    def get_lane_claim_ratio(self, headers, params=None):
        return self._request("GET", "/freight-claims/analytics/lane-claim-ratio", headers=headers, params=params)

    def get_claim_aging(self, headers, params=None):
        return self._request("GET", "/freight-claims/analytics/claim-aging", headers=headers, params=params)


api_client = ApiClient()
