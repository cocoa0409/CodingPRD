"""API client: one method per endpoint defined in the PRD.

Every path is mounted under ``/home-oxygen``.
"""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/home-oxygen"


class ApiClient(GenericApiClient):
    """One method per endpoint row of the PRD endpoint table."""

    # ─── Branches ─────────────────────────────────────

    def create_branch(self, payload, headers):
        return self._request("POST", f"{BASE}/branches", payload, headers)

    def list_branches(self, headers, params=None):
        return self._request("GET", f"{BASE}/branches", headers=headers, params=params)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"{BASE}/branches/{branch_id}", headers=headers)

    def update_branch(self, branch_id, payload, headers):
        return self._request("PATCH", f"{BASE}/branches/{branch_id}", payload, headers)

    # ─── Patients ─────────────────────────────────────

    def create_patient(self, payload, headers):
        return self._request("POST", f"{BASE}/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", f"{BASE}/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"{BASE}/patients/{patient_id}", headers=headers)

    def update_patient(self, patient_id, payload, headers):
        return self._request("PATCH", f"{BASE}/patients/{patient_id}", payload, headers)

    def get_patient_risk_assessment(self, patient_id, headers):
        return self._request(
            "GET", f"{BASE}/patients/{patient_id}/risk-assessment", headers=headers
        )

    def create_risk_reassessment(self, patient_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/patients/{patient_id}/risk-reassessments", payload, headers
        )

    def create_transfer_request(self, patient_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/patients/{patient_id}/transfer-requests", payload, headers
        )

    def complete_transfer_request(self, patient_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/patients/{patient_id}/transfer-requests/complete",
            payload,
            headers,
        )

    def cancel_transfer_request(self, patient_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/patients/{patient_id}/transfer-requests/cancel",
            payload,
            headers,
        )

    def discharge_patient(self, patient_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/patients/{patient_id}/discharge", payload, headers
        )

    # ─── Qualifying tests ─────────────────────────────

    def create_qualifying_test(self, payload, headers):
        return self._request("POST", f"{BASE}/qualifying-tests", payload, headers)

    def list_qualifying_tests(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/qualifying-tests", headers=headers, params=params
        )

    def get_qualifying_test(self, qualifying_test_id, headers):
        return self._request(
            "GET", f"{BASE}/qualifying-tests/{qualifying_test_id}", headers=headers
        )

    # ─── Certificates of medical necessity ────────────

    def create_cmn(self, payload, headers):
        return self._request("POST", f"{BASE}/cmns", payload, headers)

    def list_cmns(self, headers, params=None):
        return self._request("GET", f"{BASE}/cmns", headers=headers, params=params)

    def get_cmn(self, cmn_id, headers):
        return self._request("GET", f"{BASE}/cmns/{cmn_id}", headers=headers)

    def update_cmn(self, cmn_id, payload, headers):
        return self._request("PATCH", f"{BASE}/cmns/{cmn_id}", payload, headers)

    def submit_cmn(self, cmn_id, headers, payload=None):
        return self._request("POST", f"{BASE}/cmns/{cmn_id}/submit", payload, headers)

    def sign_cmn(self, cmn_id, headers, payload=None):
        return self._request("POST", f"{BASE}/cmns/{cmn_id}/sign", payload, headers)

    def approve_cmn(self, cmn_id, headers, payload=None):
        return self._request("POST", f"{BASE}/cmns/{cmn_id}/approve", payload, headers)

    def return_cmn_for_correction(self, cmn_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/cmns/{cmn_id}/return-for-correction", payload, headers
        )

    def void_cmn(self, cmn_id, payload, headers):
        return self._request("POST", f"{BASE}/cmns/{cmn_id}/void", payload, headers)

    # ─── Rental contracts ─────────────────────────────

    def create_rental_contract(self, payload, headers):
        return self._request("POST", f"{BASE}/rental-contracts", payload, headers)

    def list_rental_contracts(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/rental-contracts", headers=headers, params=params
        )

    def get_rental_contract(self, contract_id, headers):
        return self._request(
            "GET", f"{BASE}/rental-contracts/{contract_id}", headers=headers
        )

    def get_cap_summary(self, contract_id, headers):
        return self._request(
            "GET", f"{BASE}/rental-contracts/{contract_id}/cap-summary", headers=headers
        )

    def post_billing_month(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/rental-contracts/{contract_id}/billing-months",
            payload,
            headers,
        )

    def reverse_billing_month(self, contract_id, service_month, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/rental-contracts/{contract_id}/billing-months/{service_month}/reverse",
            payload,
            headers,
        )

    def resume_billing(self, contract_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/rental-contracts/{contract_id}/resume-billing",
            payload,
            headers,
        )

    def close_rental_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/rental-contracts/{contract_id}/close", payload, headers
        )

    def create_equipment_assignment(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/rental-contracts/{contract_id}/equipment-assignments",
            payload,
            headers,
        )

    def create_travel_authorization(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/rental-contracts/{contract_id}/travel-authorizations",
            payload,
            headers,
        )

    # ─── Equipment units ──────────────────────────────

    def create_equipment_unit(self, payload, headers):
        return self._request("POST", f"{BASE}/equipment-units", payload, headers)

    def list_equipment_units(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/equipment-units", headers=headers, params=params
        )

    def get_equipment_unit(self, equipment_unit_id, headers):
        return self._request(
            "GET", f"{BASE}/equipment-units/{equipment_unit_id}", headers=headers
        )

    def service_equipment_unit(self, equipment_unit_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/equipment-units/{equipment_unit_id}/service",
            payload,
            headers,
        )

    def retire_equipment_unit(self, equipment_unit_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/equipment-units/{equipment_unit_id}/retire",
            payload,
            headers,
        )

    # ─── Placements ───────────────────────────────────

    def list_placements(self, headers, params=None):
        return self._request("GET", f"{BASE}/placements", headers=headers, params=params)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"{BASE}/placements/{placement_id}", headers=headers)

    def release_placement(self, placement_id, headers):
        return self._request(
            "DELETE", f"{BASE}/placements/{placement_id}", headers=headers
        )

    def report_malfunction(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/placements/{placement_id}/malfunction", payload, headers
        )

    # ─── Delivery routes ──────────────────────────────

    def create_delivery_route(self, payload, headers):
        return self._request("POST", f"{BASE}/delivery-routes", payload, headers)

    def list_delivery_routes(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/delivery-routes", headers=headers, params=params
        )

    def get_delivery_route(self, route_id, headers):
        return self._request(
            "GET", f"{BASE}/delivery-routes/{route_id}", headers=headers
        )

    def get_route_manifest(self, route_id, headers):
        return self._request(
            "GET", f"{BASE}/delivery-routes/{route_id}/manifest", headers=headers
        )

    def lock_route(self, route_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/delivery-routes/{route_id}/lock", payload, headers
        )

    def unlock_route(self, route_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/delivery-routes/{route_id}/unlock", payload, headers
        )

    def dispatch_route(self, route_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/delivery-routes/{route_id}/dispatch", payload, headers
        )

    # ─── Route stops ──────────────────────────────────

    def create_route_stop(self, payload, headers):
        return self._request("POST", f"{BASE}/route-stops", payload, headers)

    def list_route_stops(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/route-stops", headers=headers, params=params
        )

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"{BASE}/route-stops/{stop_id}", headers=headers)

    def complete_route_stop(self, stop_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/route-stops/{stop_id}/complete", payload, headers
        )

    def complete_setup(self, stop_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/route-stops/{stop_id}/complete-setup", payload, headers
        )

    def miss_route_stop(self, stop_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/route-stops/{stop_id}/miss", payload, headers
        )

    def cancel_route_stop(self, stop_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/route-stops/{stop_id}/cancel", payload, headers
        )

    # ─── Recall notices ───────────────────────────────

    def create_recall_notice(self, payload, headers):
        return self._request("POST", f"{BASE}/recall-notices", payload, headers)

    def list_recall_notices(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/recall-notices", headers=headers, params=params
        )

    def get_recall_notice(self, recall_notice_id, headers):
        return self._request(
            "GET", f"{BASE}/recall-notices/{recall_notice_id}", headers=headers
        )

    def start_recall_remediation(self, recall_notice_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/recall-notices/{recall_notice_id}/start-remediation",
            payload,
            headers,
        )

    def close_recall_notice(self, recall_notice_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/recall-notices/{recall_notice_id}/close", payload, headers
        )

    # ─── Travel authorizations ────────────────────────

    def list_travel_authorizations(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/travel-authorizations", headers=headers, params=params
        )

    def get_travel_authorization(self, travel_authorization_id, headers):
        return self._request(
            "GET",
            f"{BASE}/travel-authorizations/{travel_authorization_id}",
            headers=headers,
        )

    def approve_travel_authorization(
        self, travel_authorization_id, headers, payload=None
    ):
        return self._request(
            "POST",
            f"{BASE}/travel-authorizations/{travel_authorization_id}/approve",
            payload,
            headers,
        )

    def deny_travel_authorization(self, travel_authorization_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/travel-authorizations/{travel_authorization_id}/deny",
            payload,
            headers,
        )

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
