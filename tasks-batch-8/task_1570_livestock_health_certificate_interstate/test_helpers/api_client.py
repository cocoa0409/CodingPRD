"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (test-driving; outside the /api business surface) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Premises ---
    def create_premises(self, payload, headers):
        return self._request("POST", "/api/premises", payload, headers)

    def get_premises(self, premises_id, headers):
        return self._request("GET", f"/api/premises/{premises_id}", headers=headers)

    def accredit_premises(self, premises_id, headers):
        return self._request(
            "POST", f"/api/premises/{premises_id}/accredit", headers=headers
        )

    # --- Veterinarians ---
    def create_veterinarian(self, payload, headers):
        return self._request("POST", "/api/veterinarians", payload, headers)

    def suspend_veterinarian(self, vet_id, headers):
        return self._request(
            "POST", f"/api/veterinarians/{vet_id}/suspend", headers=headers
        )

    # --- Entry requirements ---
    def create_entry_requirement(self, payload, headers):
        return self._request("POST", "/api/entry-requirements", payload, headers)

    def amend_entry_requirement(self, requirement_id, payload, headers):
        return self._request(
            "PATCH", f"/api/entry-requirements/{requirement_id}", payload, headers
        )

    def list_entry_requirements(self, headers, params=None):
        return self._request(
            "GET", "/api/entry-requirements", headers=headers, params=params
        )

    # --- Test records ---
    def create_test_record(self, payload, headers):
        return self._request("POST", "/api/test-records", payload, headers)

    def report_test_result(self, test_id, payload, headers):
        return self._request(
            "POST", f"/api/test-records/{test_id}/result", payload, headers
        )

    def list_test_records_for_premises(self, premises_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/premises/{premises_id}/test-records",
            headers=headers,
            params=params,
        )

    # --- Certificates ---
    def create_certificate(self, payload, headers):
        return self._request("POST", "/api/certificates", payload, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"/api/certificates/{certificate_id}", headers=headers
        )

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/api/certificates", headers=headers, params=params)

    def submit_certificate(self, certificate_id, headers):
        return self._request(
            "POST", f"/api/certificates/{certificate_id}/submit", headers=headers
        )

    def issue_certificate(self, certificate_id, headers):
        return self._request(
            "POST", f"/api/certificates/{certificate_id}/issue", headers=headers
        )

    def reject_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/api/certificates/{certificate_id}/reject", payload, headers
        )

    def revise_certificate(self, certificate_id, headers):
        return self._request(
            "POST", f"/api/certificates/{certificate_id}/revise", headers=headers
        )

    def void_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/api/certificates/{certificate_id}/void", payload, headers
        )

    def transmit_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/api/certificates/{certificate_id}/transmit", payload, headers
        )

    # --- Movement permits ---
    def create_movement_permit(self, payload, headers):
        return self._request("POST", "/api/movement-permits", payload, headers)

    def get_movement_permit(self, permit_id, headers):
        return self._request(
            "GET", f"/api/movement-permits/{permit_id}", headers=headers
        )

    def list_permits_for_certificate(self, certificate_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/certificates/{certificate_id}/movement-permits",
            headers=headers,
            params=params,
        )

    def issue_movement_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/api/movement-permits/{permit_id}/issue", headers=headers
        )

    def adjust_movement_permit(self, permit_id, payload, headers):
        return self._request(
            "PATCH", f"/api/movement-permits/{permit_id}", payload, headers
        )

    # --- Movement records ---
    def create_movement_record(self, payload, headers):
        return self._request("POST", "/api/movement-records", payload, headers)

    def depart_movement_record(self, record_id, headers):
        return self._request(
            "POST", f"/api/movement-records/{record_id}/depart", headers=headers
        )

    def arrive_movement_record(self, record_id, headers):
        return self._request(
            "POST", f"/api/movement-records/{record_id}/arrive", headers=headers
        )

    def cancel_movement_record(self, record_id, headers):
        return self._request(
            "POST", f"/api/movement-records/{record_id}/cancel", headers=headers
        )

    def list_movement_records_for_permit(self, permit_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/movement-permits/{permit_id}/movement-records",
            headers=headers,
            params=params,
        )

    # --- Outbreak zones ---
    def create_outbreak_zone(self, payload, headers):
        return self._request("POST", "/api/outbreak-zones", payload, headers)

    def escalate_outbreak_zone(self, zone_id, headers):
        return self._request(
            "POST", f"/api/outbreak-zones/{zone_id}/escalate", headers=headers
        )

    def contain_outbreak_zone(self, zone_id, headers):
        return self._request(
            "POST", f"/api/outbreak-zones/{zone_id}/contain", headers=headers
        )

    def resolve_outbreak_zone(self, zone_id, headers):
        return self._request(
            "POST", f"/api/outbreak-zones/{zone_id}/resolve", headers=headers
        )

    # --- Quarantine orders ---
    def create_quarantine_order(self, payload, headers):
        return self._request("POST", "/api/quarantine-orders", payload, headers)

    def lift_quarantine_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/quarantine-orders/{order_id}/lift", headers=headers
        )

    def list_quarantine_orders_for_premises(self, premises_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/premises/{premises_id}/quarantine-orders",
            headers=headers,
            params=params,
        )

    # --- Transmission audits ---
    def list_transmissions_for_certificate(self, certificate_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/certificates/{certificate_id}/transmissions",
            headers=headers,
            params=params,
        )

    def acknowledge_transmission(self, audit_id, headers):
        return self._request(
            "POST", f"/api/transmission-audits/{audit_id}/acknowledge", headers=headers
        )

    def fail_transmission(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/api/transmission-audits/{audit_id}/fail", payload, headers
        )


api_client = ApiClient()
