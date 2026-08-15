"""API client: one method per endpoint defined in the PRD endpoint table.

All resources are mounted under the /plant prefix. Methods return the raw
requests.Response so tests can assert status codes and envelopes.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Drawings & BOM ---
    def create_drawing(self, payload, headers):
        return self._request("POST", "/plant/drawings", payload, headers)

    def get_drawing(self, drawing_id, headers):
        return self._request("GET", f"/plant/drawings/{drawing_id}", headers=headers)

    def release_drawing(self, drawing_id, headers):
        return self._request("POST", f"/plant/drawings/{drawing_id}/release", {}, headers)

    def create_component(self, payload, headers):
        return self._request("POST", "/plant/components", payload, headers)

    def get_component(self, component_id, headers):
        return self._request("GET", f"/plant/components/{component_id}", headers=headers)

    def list_components(self, headers, params=None):
        return self._request("GET", "/plant/components", headers=headers, params=params)

    # --- Consigned lots ---
    def create_consigned_lot(self, payload, headers):
        return self._request("POST", "/plant/consigned-lots", payload, headers)

    def get_consigned_lot(self, lot_id, headers):
        return self._request("GET", f"/plant/consigned-lots/{lot_id}", headers=headers)

    def return_consigned_lot(self, lot_id, headers):
        return self._request("POST", f"/plant/consigned-lots/{lot_id}/return", {}, headers)

    # --- Operators & certifications ---
    def create_operator(self, payload, headers):
        return self._request("POST", "/plant/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/plant/operators/{operator_id}", headers=headers)

    def create_operator_certification(self, payload, headers):
        return self._request("POST", "/plant/operator-certifications", payload, headers)

    def get_operator_certification(self, cert_id, headers):
        return self._request("GET", f"/plant/operator-certifications/{cert_id}", headers=headers)

    def list_operator_certifications(self, headers, params=None):
        return self._request("GET", "/plant/operator-certifications", headers=headers, params=params)

    def revoke_operator_certification(self, cert_id, headers):
        return self._request("POST", f"/plant/operator-certifications/{cert_id}/revoke", {}, headers)

    # --- Applicators, setups, machine programs ---
    def create_applicator(self, payload, headers):
        return self._request("POST", "/plant/applicators", payload, headers)

    def get_applicator(self, applicator_id, headers):
        return self._request("GET", f"/plant/applicators/{applicator_id}", headers=headers)

    def list_applicators(self, headers, params=None):
        return self._request("GET", "/plant/applicators", headers=headers, params=params)

    def create_applicator_setup(self, payload, headers):
        return self._request("POST", "/plant/applicator-setups", payload, headers)

    def get_applicator_setup(self, setup_id, headers):
        return self._request("GET", f"/plant/applicator-setups/{setup_id}", headers=headers)

    def list_applicator_setups(self, headers, params=None):
        return self._request("GET", "/plant/applicator-setups", headers=headers, params=params)

    def close_applicator_setup(self, setup_id, payload, headers):
        return self._request("POST", f"/plant/applicator-setups/{setup_id}/close", payload, headers)

    def create_machine_program(self, payload, headers):
        return self._request("POST", "/plant/machine-programs", payload, headers)

    def get_machine_program(self, program_id, headers):
        return self._request("GET", f"/plant/machine-programs/{program_id}", headers=headers)

    def list_machine_programs(self, headers, params=None):
        return self._request("GET", "/plant/machine-programs", headers=headers, params=params)

    def patch_machine_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/plant/machine-programs/{program_id}", payload, headers)

    # --- Crimp pull tests ---
    def create_crimp_pull_test(self, payload, headers):
        return self._request("POST", "/plant/crimp-pull-tests", payload, headers)

    def get_crimp_pull_test(self, test_id, headers):
        return self._request("GET", f"/plant/crimp-pull-tests/{test_id}", headers=headers)

    def list_crimp_pull_tests(self, headers, params=None):
        return self._request("GET", "/plant/crimp-pull-tests", headers=headers, params=params)

    # --- Build orders & serialized harnesses ---
    def create_build_order(self, payload, headers):
        return self._request("POST", "/plant/build-orders", payload, headers)

    def get_build_order(self, order_id, headers):
        return self._request("GET", f"/plant/build-orders/{order_id}", headers=headers)

    def list_build_orders(self, headers, params=None):
        return self._request("GET", "/plant/build-orders", headers=headers, params=params)

    def patch_build_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/plant/build-orders/{order_id}", payload, headers)

    def release_build_order_to_kitting(self, order_id, headers):
        return self._request("POST", f"/plant/build-orders/{order_id}/release-to-kitting", {}, headers)

    def cancel_build_order(self, order_id, headers):
        return self._request("POST", f"/plant/build-orders/{order_id}/cancel", {}, headers)

    def create_harness_unit(self, order_id, headers):
        return self._request("POST", f"/plant/build-orders/{order_id}/harness-units", {}, headers)

    def get_harness_unit(self, unit_id, headers):
        return self._request("GET", f"/plant/harness-units/{unit_id}", headers=headers)

    def list_harness_units(self, headers, params=None):
        return self._request("GET", "/plant/harness-units", headers=headers, params=params)

    def complete_rework(self, unit_id, headers):
        return self._request("POST", f"/plant/harness-units/{unit_id}/complete-rework", {}, headers)

    def scrap_harness_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/plant/harness-units/{unit_id}/scrap", payload, headers)

    def ship_harness_unit(self, unit_id, headers):
        return self._request("POST", f"/plant/harness-units/{unit_id}/ship", {}, headers)

    # --- Kits ---
    def get_kit(self, kit_id, headers):
        return self._request("GET", f"/plant/kits/{kit_id}", headers=headers)

    def list_kits(self, headers, params=None):
        return self._request("GET", "/plant/kits", headers=headers, params=params)

    def create_kit_issue(self, kit_id, payload, headers):
        return self._request("POST", f"/plant/kits/{kit_id}/issues", payload, headers)

    def deliver_kit(self, kit_id, headers):
        return self._request("POST", f"/plant/kits/{kit_id}/deliver", {}, headers)

    def return_kit(self, kit_id, headers):
        return self._request("POST", f"/plant/kits/{kit_id}/return", {}, headers)

    # --- Electrical test records ---
    def create_electrical_test_record(self, payload, headers):
        return self._request("POST", "/plant/electrical-test-records", payload, headers)

    def get_electrical_test_record(self, record_id, headers):
        return self._request("GET", f"/plant/electrical-test-records/{record_id}", headers=headers)

    def list_electrical_test_records(self, headers, params=None):
        return self._request("GET", "/plant/electrical-test-records", headers=headers, params=params)

    # --- Engineering change notices ---
    def create_ecn(self, payload, headers):
        return self._request("POST", "/plant/ecns", payload, headers)

    def get_ecn(self, ecn_id, headers):
        return self._request("GET", f"/plant/ecns/{ecn_id}", headers=headers)

    def list_ecns(self, headers, params=None):
        return self._request("GET", "/plant/ecns", headers=headers, params=params)

    def apply_ecn(self, ecn_id, headers):
        return self._request("POST", f"/plant/ecns/{ecn_id}/apply", {}, headers)

    def cancel_ecn(self, ecn_id, headers):
        return self._request("POST", f"/plant/ecns/{ecn_id}/cancel", {}, headers)

    # --- Test-driving: logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/plant/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
