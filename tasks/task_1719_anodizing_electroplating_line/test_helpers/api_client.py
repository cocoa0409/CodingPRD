"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def patch_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/customers/{customer_id}", payload, headers)

    # --- Fixtures ---
    def create_fixture(self, payload, headers):
        return self._request("POST", "/fixtures", payload, headers)

    def list_fixtures(self, headers, params=None):
        return self._request("GET", "/fixtures", headers=headers, params=params)

    # --- Alloy compatibility rules ---
    def create_alloy_rule(self, payload, headers):
        return self._request("POST", "/alloy-compatibility-rules", payload, headers)

    def list_alloy_rules(self, headers, params=None):
        return self._request("GET", "/alloy-compatibility-rules", headers=headers, params=params)

    def delete_alloy_rule(self, rule_id, headers):
        return self._request("DELETE", f"/alloy-compatibility-rules/{rule_id}", headers=headers)

    # --- Baths ---
    def create_bath(self, payload, headers):
        return self._request("POST", "/baths", payload, headers)

    def get_bath(self, bath_id, headers):
        return self._request("GET", f"/baths/{bath_id}", headers=headers)

    def create_titration(self, bath_id, payload, headers):
        return self._request("POST", f"/baths/{bath_id}/titrations", payload, headers)

    def list_titrations(self, bath_id, headers, params=None):
        return self._request("GET", f"/baths/{bath_id}/titrations", headers=headers, params=params)

    def create_dose(self, bath_id, payload, headers):
        return self._request("POST", f"/baths/{bath_id}/doses", payload, headers)

    def list_doses(self, bath_id, headers, params=None):
        return self._request("GET", f"/baths/{bath_id}/doses", headers=headers, params=params)

    def quarantine_bath(self, bath_id, headers):
        return self._request("POST", f"/baths/{bath_id}/quarantine", headers=headers)

    def release_quarantine(self, bath_id, headers):
        return self._request("POST", f"/baths/{bath_id}/release-quarantine", headers=headers)

    def dump_bath(self, bath_id, payload, headers):
        return self._request("POST", f"/baths/{bath_id}/dump", payload, headers)

    def renew_bath(self, bath_id, payload, headers):
        return self._request("POST", f"/baths/{bath_id}/renew", payload, headers)

    def list_bath_load_runs(self, bath_id, headers, params=None):
        return self._request("GET", f"/baths/{bath_id}/load-runs", headers=headers, params=params)

    # --- Work orders ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def patch_work_order(self, work_order_id, payload, headers):
        return self._request("PATCH", f"/work-orders/{work_order_id}", payload, headers)

    def prepare_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/prepare", payload, headers)

    def complete_predip(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete-predip", headers=headers)

    def route_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/route", payload, headers)

    def start_load_run(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/load-runs", payload, headers)

    def list_work_order_load_runs(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/load-runs", headers=headers, params=params)

    def complete_load_run(self, load_run_id, headers):
        return self._request("POST", f"/load-runs/{load_run_id}/complete", headers=headers)

    def abort_load_run(self, load_run_id, headers):
        return self._request("POST", f"/load-runs/{load_run_id}/abort", headers=headers)

    def create_inspection(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/inspections", payload, headers)

    def list_inspections(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/inspections", headers=headers, params=params)

    def start_strip(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/start-strip", payload, headers)

    def complete_strip(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete-strip", headers=headers)

    def ship_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/ship", headers=headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", headers=headers)

    # --- Salt spray lots ---
    def create_salt_spray_lot(self, payload, headers):
        return self._request("POST", "/salt-spray-lots", payload, headers)

    def evaluate_salt_spray_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/salt-spray-lots/{lot_id}/evaluate", payload, headers)

    def list_work_order_salt_spray_lots(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/salt-spray-lots", headers=headers, params=params)

    # --- Discharge permits & samples ---
    def create_discharge_permit(self, payload, headers):
        return self._request("POST", "/discharge-permits", payload, headers)

    def get_discharge_permit(self, permit_id, headers):
        return self._request("GET", f"/discharge-permits/{permit_id}", headers=headers)

    def create_waste_sample(self, permit_id, payload, headers):
        return self._request("POST", f"/discharge-permits/{permit_id}/samples", payload, headers)

    def list_waste_samples(self, permit_id, headers, params=None):
        return self._request("GET", f"/discharge-permits/{permit_id}/samples", headers=headers, params=params)

    def clear_exceedance(self, permit_id, headers):
        return self._request("POST", f"/discharge-permits/{permit_id}/clear-exceedance", headers=headers)

    # --- Waste manifests ---
    def create_waste_manifest(self, payload, headers):
        return self._request("POST", "/waste-manifests", payload, headers)

    def get_waste_manifest(self, manifest_id, headers):
        return self._request("GET", f"/waste-manifests/{manifest_id}", headers=headers)

    def add_manifest_line_item(self, manifest_id, payload, headers):
        return self._request("POST", f"/waste-manifests/{manifest_id}/line-items", payload, headers)

    def delete_manifest_line_item(self, manifest_id, line_item_id, headers):
        return self._request(
            "DELETE",
            f"/waste-manifests/{manifest_id}/line-items/{line_item_id}",
            headers=headers,
        )

    def list_manifest_line_items(self, manifest_id, headers, params=None):
        return self._request(
            "GET", f"/waste-manifests/{manifest_id}/line-items", headers=headers, params=params
        )

    def finalize_manifest(self, manifest_id, headers):
        return self._request("POST", f"/waste-manifests/{manifest_id}/finalize", headers=headers)

    def ship_manifest(self, manifest_id, payload, headers):
        return self._request("POST", f"/waste-manifests/{manifest_id}/ship", payload, headers)

    def receive_manifest(self, manifest_id, headers):
        return self._request("POST", f"/waste-manifests/{manifest_id}/receive", headers=headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
