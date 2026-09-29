"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------- halls ----------------
    def create_hall(self, payload, headers):
        return self._request("POST", "/halls", payload, headers)

    def list_halls(self, headers, params=None):
        return self._request("GET", "/halls", headers=headers, params=params)

    def get_hall(self, hall_id, headers):
        return self._request("GET", f"/halls/{hall_id}", headers=headers)

    def advance_hall_phase(self, hall_id, payload, headers):
        return self._request(
            "POST", f"/halls/{hall_id}/advance-phase", payload, headers
        )

    def get_capacity_summary(self, hall_id, headers):
        return self._request(
            "GET", f"/halls/{hall_id}/capacity-summary", headers=headers
        )

    # ---------------- tenants ----------------
    def create_tenant(self, payload, headers):
        return self._request("POST", "/tenants", payload, headers)

    def list_tenants(self, headers, params=None):
        return self._request("GET", "/tenants", headers=headers, params=params)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    # ---------------- power distribution units ----------------
    def create_pdu(self, payload, headers):
        return self._request("POST", "/pdus", payload, headers)

    def list_pdus(self, headers, params=None):
        return self._request("GET", "/pdus", headers=headers, params=params)

    def get_pdu(self, pdu_id, headers):
        return self._request("GET", f"/pdus/{pdu_id}", headers=headers)

    def patch_pdu(self, pdu_id, payload, headers):
        return self._request("PATCH", f"/pdus/{pdu_id}", payload, headers)

    # ---------------- busway runs ----------------
    def create_busway(self, payload, headers):
        return self._request("POST", "/busways", payload, headers)

    def list_busways(self, headers, params=None):
        return self._request("GET", "/busways", headers=headers, params=params)

    def get_busway(self, busway_id, headers):
        return self._request("GET", f"/busways/{busway_id}", headers=headers)

    def energize_busway(self, busway_id, headers, payload=None):
        return self._request(
            "POST", f"/busways/{busway_id}/energize", payload or {}, headers
        )

    # ---------------- containment zones ----------------
    def create_containment_zone(self, payload, headers):
        return self._request("POST", "/containment-zones", payload, headers)

    def list_containment_zones(self, headers, params=None):
        return self._request(
            "GET", "/containment-zones", headers=headers, params=params
        )

    def get_containment_zone(self, zone_id, headers):
        return self._request("GET", f"/containment-zones/{zone_id}", headers=headers)

    def leakage_test(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/containment-zones/{zone_id}/leakage-test", payload, headers
        )

    def remediate_zone(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/containment-zones/{zone_id}/remediate", payload or {}, headers
        )

    # ---------------- cooling units ----------------
    def create_cooling_unit(self, payload, headers):
        return self._request("POST", "/cooling-units", payload, headers)

    def list_cooling_units(self, headers, params=None):
        return self._request("GET", "/cooling-units", headers=headers, params=params)

    def get_cooling_unit(self, unit_id, headers):
        return self._request("GET", f"/cooling-units/{unit_id}", headers=headers)

    def commission_cooling_unit(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/cooling-units/{unit_id}/commission", payload, headers
        )

    def place_cooling_unit_in_service(self, unit_id, headers, payload=None):
        return self._request(
            "POST", f"/cooling-units/{unit_id}/place-in-service", payload or {}, headers
        )

    # ---------------- cages ----------------
    def create_cage(self, payload, headers):
        return self._request("POST", "/cages", payload, headers)

    def list_cages(self, headers, params=None):
        return self._request("GET", "/cages", headers=headers, params=params)

    def get_cage(self, cage_id, headers):
        return self._request("GET", f"/cages/{cage_id}", headers=headers)

    # ---------------- security devices ----------------
    def create_security_device(self, payload, headers):
        return self._request("POST", "/security-devices", payload, headers)

    def list_security_devices(self, headers, params=None):
        return self._request(
            "GET", "/security-devices", headers=headers, params=params
        )

    def get_security_device(self, device_id, headers):
        return self._request("GET", f"/security-devices/{device_id}", headers=headers)

    def commission_security_device(self, device_id, headers, payload=None):
        return self._request(
            "POST", f"/security-devices/{device_id}/commission", payload or {}, headers
        )

    # ---------------- racks ----------------
    def create_rack(self, payload, headers):
        return self._request("POST", "/racks", payload, headers)

    def list_racks(self, headers, params=None):
        return self._request("GET", "/racks", headers=headers, params=params)

    def get_rack(self, rack_id, headers):
        return self._request("GET", f"/racks/{rack_id}", headers=headers)

    def patch_rack(self, rack_id, payload, headers):
        return self._request("PATCH", f"/racks/{rack_id}", payload, headers)

    def install_rack(self, rack_id, payload, headers):
        return self._request(
            "POST", f"/racks/{rack_id}/install", payload or {}, headers
        )

    def power_on_rack(self, rack_id, headers, payload=None):
        return self._request(
            "POST", f"/racks/{rack_id}/power-on", payload or {}, headers
        )

    # ---------------- rack feeds ----------------
    def create_rack_feed(self, payload, headers):
        return self._request("POST", "/rack-feeds", payload, headers)

    def list_rack_feeds(self, headers, params=None):
        return self._request("GET", "/rack-feeds", headers=headers, params=params)

    def get_rack_feed(self, feed_id, headers):
        return self._request("GET", f"/rack-feeds/{feed_id}", headers=headers)

    def delete_rack_feed(self, feed_id, headers):
        return self._request("DELETE", f"/rack-feeds/{feed_id}", headers=headers)

    # ---------------- commissioning packages ----------------
    def create_commissioning_package(self, payload, headers):
        return self._request("POST", "/commissioning-packages", payload, headers)

    def list_commissioning_packages(self, headers, params=None):
        return self._request(
            "GET", "/commissioning-packages", headers=headers, params=params
        )

    def get_commissioning_package(self, package_id, headers):
        return self._request(
            "GET", f"/commissioning-packages/{package_id}", headers=headers
        )

    def approve_script(self, package_id, payload, headers):
        return self._request(
            "POST",
            f"/commissioning-packages/{package_id}/approve-script",
            payload,
            headers,
        )

    def execute_script(self, package_id, headers, payload=None):
        return self._request(
            "POST",
            f"/commissioning-packages/{package_id}/execute-script",
            payload or {},
            headers,
        )

    def witness_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/commissioning-packages/{package_id}/witness", payload, headers
        )

    # ---------------- load bank tests ----------------
    def create_load_bank_test(self, payload, headers):
        return self._request("POST", "/load-bank-tests", payload, headers)

    def list_load_bank_tests(self, headers, params=None):
        return self._request("GET", "/load-bank-tests", headers=headers, params=params)

    def get_load_bank_test(self, test_id, headers):
        return self._request("GET", f"/load-bank-tests/{test_id}", headers=headers)

    def start_load_bank_test(self, test_id, headers, payload=None):
        return self._request(
            "POST", f"/load-bank-tests/{test_id}/start", payload or {}, headers
        )

    def complete_load_bank_test(self, test_id, payload, headers):
        return self._request(
            "POST", f"/load-bank-tests/{test_id}/complete", payload, headers
        )

    def abort_load_bank_test(self, test_id, payload, headers):
        return self._request(
            "POST", f"/load-bank-tests/{test_id}/abort", payload or {}, headers
        )

    # ---------------- methods of procedure ----------------
    def create_mop(self, payload, headers):
        return self._request("POST", "/mops", payload, headers)

    def list_mops(self, headers, params=None):
        return self._request("GET", "/mops", headers=headers, params=params)

    def get_mop(self, mop_id, headers):
        return self._request("GET", f"/mops/{mop_id}", headers=headers)

    def submit_mop(self, mop_id, headers, payload=None):
        return self._request("POST", f"/mops/{mop_id}/submit", payload or {}, headers)

    def create_mop_approval(self, mop_id, payload, headers):
        return self._request("POST", f"/mops/{mop_id}/approvals", payload, headers)

    def list_mop_approvals(self, mop_id, headers, params=None):
        return self._request(
            "GET", f"/mops/{mop_id}/approvals", headers=headers, params=params
        )

    def revise_mop(self, mop_id, payload, headers):
        return self._request("POST", f"/mops/{mop_id}/revise", payload or {}, headers)

    def schedule_mop(self, mop_id, payload, headers):
        return self._request(
            "POST", f"/mops/{mop_id}/schedule", payload or {}, headers
        )

    def execute_mop(self, mop_id, headers, payload=None):
        return self._request("POST", f"/mops/{mop_id}/execute", payload or {}, headers)

    def close_mop(self, mop_id, payload, headers):
        return self._request("POST", f"/mops/{mop_id}/close", payload or {}, headers)

    def back_out_mop(self, mop_id, payload, headers):
        return self._request(
            "POST", f"/mops/{mop_id}/back-out", payload or {}, headers
        )

    # ---------------- release packets ----------------
    def create_release_packet(self, payload, headers):
        return self._request("POST", "/release-packets", payload, headers)

    def list_release_packets(self, headers, params=None):
        return self._request("GET", "/release-packets", headers=headers, params=params)

    def get_release_packet(self, packet_id, headers):
        return self._request("GET", f"/release-packets/{packet_id}", headers=headers)

    def submit_release_packet(self, packet_id, headers, payload=None):
        return self._request(
            "POST", f"/release-packets/{packet_id}/submit", payload or {}, headers
        )

    def accept_release_packet(self, packet_id, headers, payload=None):
        return self._request(
            "POST", f"/release-packets/{packet_id}/accept", payload or {}, headers
        )

    def reject_release_packet(self, packet_id, payload, headers):
        return self._request(
            "POST", f"/release-packets/{packet_id}/reject", payload, headers
        )


api_client = ApiClient()
