"""API client: one method per endpoint defined in the PRD.

All business resources live under the /registry prefix; the logical-clock
test-driving capability lives at /_clock/set_current_utc.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/registry"


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------- registries ----------------
    def create_registry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/registries", payload, headers)

    def get_registry(self, registry_id, headers):
        return self._request("GET", f"{PREFIX}/registries/{registry_id}", headers=headers)

    def update_registry(self, registry_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/registries/{registry_id}", payload, headers
        )

    # ---------------- collection centers ----------------
    def create_collection_center(self, payload, headers):
        return self._request("POST", f"{PREFIX}/collection-centers", payload, headers)

    def get_collection_center(self, center_id, headers):
        return self._request(
            "GET", f"{PREFIX}/collection-centers/{center_id}", headers=headers
        )

    # ---------------- patients ----------------
    def create_patient(self, payload, headers):
        return self._request("POST", f"{PREFIX}/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"{PREFIX}/patients/{patient_id}", headers=headers)

    def list_patient_search_requests(self, patient_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/patients/{patient_id}/search-requests",
            headers=headers,
            params=params,
        )

    def drive_conditioning(self, patient_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/patients/{patient_id}/conditioning", payload, headers
        )

    # ---------------- search requests ----------------
    def create_search_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/search-requests", payload, headers)

    def get_search_request(self, search_request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/search-requests/{search_request_id}", headers=headers
        )

    def run_deadline_sweep(self, search_request_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/search-requests/{search_request_id}/deadline-sweep",
            {},
            headers,
        )

    # ---------------- donors ----------------
    def create_donor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/donors", payload, headers)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"{PREFIX}/donors/{donor_id}", headers=headers)

    def list_donors(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/donors", headers=headers, params=params)

    # ---------------- donor calendar windows ----------------
    def create_unavailability_window(self, donor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/donors/{donor_id}/unavailability-windows", payload, headers
        )

    def list_unavailability_windows(self, donor_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/donors/{donor_id}/unavailability-windows",
            headers=headers,
            params=params,
        )

    def release_unavailability_window(self, donor_id, window_id, headers):
        return self._request(
            "DELETE",
            f"{PREFIX}/donors/{donor_id}/unavailability-windows/{window_id}",
            headers=headers,
        )

    # ---------------- donor follow-ups ----------------
    def create_follow_up(self, donor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/donors/{donor_id}/follow-ups", payload, headers
        )

    def list_follow_ups(self, donor_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/donors/{donor_id}/follow-ups", headers=headers, params=params
        )

    # ---------------- match candidates ----------------
    def list_match_candidates(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/match-candidates", headers=headers, params=params
        )

    def get_match_candidate(self, candidate_id, headers):
        return self._request(
            "GET", f"{PREFIX}/match-candidates/{candidate_id}", headers=headers
        )

    def list_typing_requests(self, candidate_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/match-candidates/{candidate_id}/typing-requests",
            headers=headers,
            params=params,
        )

    def create_typing_request(self, candidate_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/match-candidates/{candidate_id}/typing-requests",
            payload,
            headers,
        )

    def record_screening(self, candidate_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/match-candidates/{candidate_id}/screening", payload, headers
        )

    def list_workup_cases(self, candidate_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/match-candidates/{candidate_id}/workup-cases",
            headers=headers,
            params=params,
        )

    def open_workup_case(self, candidate_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/match-candidates/{candidate_id}/workup-cases",
            payload if payload is not None else {},
            headers,
        )

    # ---------------- typing request response ----------------
    def respond_typing_request(self, typing_request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/typing-requests/{typing_request_id}/response", payload, headers
        )

    # ---------------- workup cases ----------------
    def get_workup_case(self, workup_case_id, headers):
        return self._request(
            "GET", f"{PREFIX}/workup-cases/{workup_case_id}", headers=headers
        )

    def list_clearance_items(self, workup_case_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/workup-cases/{workup_case_id}/clearance-items",
            headers=headers,
            params=params,
        )

    def decide_collection_method(self, workup_case_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/workup-cases/{workup_case_id}/collection-method",
            payload,
            headers,
        )

    # ---------------- clearance items ----------------
    def get_clearance_item(self, clearance_item_id, headers):
        return self._request(
            "GET", f"{PREFIX}/clearance-items/{clearance_item_id}", headers=headers
        )

    def record_clearance_result(self, clearance_item_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/clearance-items/{clearance_item_id}/result", payload, headers
        )

    # ---------------- collection bookings ----------------
    def create_collection_booking(self, payload, headers):
        return self._request("POST", f"{PREFIX}/collection-bookings", payload, headers)

    def list_collection_bookings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/collection-bookings", headers=headers, params=params
        )

    def get_collection_booking(self, booking_id, headers):
        return self._request(
            "GET", f"{PREFIX}/collection-bookings/{booking_id}", headers=headers
        )

    def confirm_collection_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/collection-bookings/{booking_id}/confirm",
            payload if payload is not None else {},
            headers,
        )

    def cancel_collection_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/collection-bookings/{booking_id}/cancel", payload, headers
        )

    def list_booking_shipments(self, booking_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/collection-bookings/{booking_id}/shipments",
            headers=headers,
            params=params,
        )

    def create_shipment(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/collection-bookings/{booking_id}/shipments", payload, headers
        )

    def list_booking_unavailability_windows(self, booking_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/collection-bookings/{booking_id}/unavailability-windows",
            headers=headers,
            params=params,
        )

    # ---------------- shipments ----------------
    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"{PREFIX}/shipments/{shipment_id}", headers=headers)

    def create_shipment_event(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/shipments/{shipment_id}/events", payload, headers
        )

    # ---------------- reimbursement claims ----------------
    def list_reimbursement_claims(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/reimbursement-claims", headers=headers, params=params
        )

    def get_reimbursement_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{PREFIX}/reimbursement-claims/{claim_id}", headers=headers
        )

    def finalize_reimbursement_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/reimbursement-claims/{claim_id}/finalize",
            payload if payload is not None else {},
            headers,
        )


api_client = ApiClient()
