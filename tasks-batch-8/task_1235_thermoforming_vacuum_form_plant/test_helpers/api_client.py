"""API client: one method per endpoint defined in the PRD (§4 endpoint table).

The resource topology is flat (PRD §2.8): every resource is addressed at the
top level by its own id; cross-references travel in request bodies and query
parameters.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Material lots ---
    def create_material_lot(self, payload, headers):
        return self._request("POST", "/material-lots", payload, headers)

    def list_material_lots(self, headers, params=None):
        return self._request("GET", "/material-lots", headers=headers, params=params)

    def get_material_lot(self, lot_id, headers):
        return self._request("GET", f"/material-lots/{lot_id}", headers=headers)

    def block_material_lot(self, lot_id, headers):
        return self._request("POST", f"/material-lots/{lot_id}/block", {}, headers)

    # --- Regrind batches ---
    def create_regrind_batch(self, payload, headers):
        return self._request("POST", "/regrind-batches", payload, headers)

    def list_regrind_batches(self, headers, params=None):
        return self._request("GET", "/regrind-batches", headers=headers, params=params)

    def get_regrind_batch(self, batch_id, headers):
        return self._request("GET", f"/regrind-batches/{batch_id}", headers=headers)

    def decide_regrind_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/regrind-batches/{batch_id}/decide", payload, headers)

    # --- Tools ---
    def create_tool(self, payload, headers):
        return self._request("POST", "/tools", payload, headers)

    def list_tools(self, headers, params=None):
        return self._request("GET", "/tools", headers=headers, params=params)

    def get_tool(self, tool_id, headers):
        return self._request("GET", f"/tools/{tool_id}", headers=headers)

    def complete_prototype(self, tool_id, headers):
        return self._request("POST", f"/tools/{tool_id}/complete-prototype", {}, headers)

    def submit_qualification(self, tool_id, headers):
        return self._request("POST", f"/tools/{tool_id}/submit-qualification", {}, headers)

    def approve_production(self, tool_id, payload, headers):
        return self._request("POST", f"/tools/{tool_id}/approve-production", payload, headers)

    def revise_tool(self, tool_id, headers):
        return self._request("POST", f"/tools/{tool_id}/revise", {}, headers)

    # --- Packaging specs ---
    def create_packaging_spec(self, payload, headers):
        return self._request("POST", "/packaging-specs", payload, headers)

    def list_packaging_specs(self, headers, params=None):
        return self._request("GET", "/packaging-specs", headers=headers, params=params)

    def decide_packaging_spec(self, spec_id, payload, headers):
        return self._request("POST", f"/packaging-specs/{spec_id}/decide", payload, headers)

    # --- Production orders ---
    def create_production_order(self, payload, headers):
        return self._request("POST", "/production-orders", payload, headers)

    def list_production_orders(self, headers, params=None):
        return self._request("GET", "/production-orders", headers=headers, params=params)

    def get_production_order(self, order_id, headers):
        return self._request("GET", f"/production-orders/{order_id}", headers=headers)

    def stage_order(self, order_id, payload, headers):
        return self._request("POST", f"/production-orders/{order_id}/stage", payload, headers)

    def hold_order(self, order_id, headers):
        return self._request("POST", f"/production-orders/{order_id}/hold", {}, headers)

    def resume_order(self, order_id, headers):
        return self._request("POST", f"/production-orders/{order_id}/resume", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/production-orders/{order_id}/cancel", {}, headers)

    # --- Material allocations ---
    def create_material_allocation(self, payload, headers):
        return self._request("POST", "/material-allocations", payload, headers)

    def list_material_allocations(self, headers, params=None):
        return self._request("GET", "/material-allocations", headers=headers, params=params)

    def get_material_allocation(self, allocation_id, headers):
        return self._request("GET", f"/material-allocations/{allocation_id}", headers=headers)

    def release_allocation(self, allocation_id, headers):
        return self._request("POST", f"/material-allocations/{allocation_id}/release", {}, headers)

    # --- Machine resources ---
    def create_machine_resource(self, payload, headers):
        return self._request("POST", "/machine-resources", payload, headers)

    def list_machine_resources(self, headers, params=None):
        return self._request("GET", "/machine-resources", headers=headers, params=params)

    def get_machine_resource(self, resource_id, headers):
        return self._request("GET", f"/machine-resources/{resource_id}", headers=headers)

    # --- Forming runs ---
    def create_forming_run(self, payload, headers):
        return self._request("POST", "/forming-runs", payload, headers)

    def list_forming_runs(self, headers, params=None):
        return self._request("GET", "/forming-runs", headers=headers, params=params)

    def get_forming_run(self, run_id, headers):
        return self._request("GET", f"/forming-runs/{run_id}", headers=headers)

    def complete_forming_run(self, run_id, payload, headers):
        return self._request("POST", f"/forming-runs/{run_id}/complete", payload, headers)

    # --- Scrap records ---
    def list_scrap_records(self, headers, params=None):
        return self._request("GET", "/scrap-records", headers=headers, params=params)

    def get_scrap_record(self, scrap_id, headers):
        return self._request("GET", f"/scrap-records/{scrap_id}", headers=headers)

    def certify_scrap_record(self, scrap_id, payload, headers):
        return self._request("POST", f"/scrap-records/{scrap_id}/certify", payload, headers)

    # --- Quality inspections ---
    def create_quality_inspection(self, payload, headers):
        return self._request("POST", "/quality-inspections", payload, headers)

    def list_quality_inspections(self, headers, params=None):
        return self._request("GET", "/quality-inspections", headers=headers, params=params)

    def get_quality_inspection(self, inspection_id, headers):
        return self._request("GET", f"/quality-inspections/{inspection_id}", headers=headers)

    def disposition_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/quality-inspections/{inspection_id}/disposition", payload, headers
        )

    # --- Assembly tasks ---
    def create_assembly_task(self, payload, headers):
        return self._request("POST", "/assembly-tasks", payload, headers)

    def list_assembly_tasks(self, headers, params=None):
        return self._request("GET", "/assembly-tasks", headers=headers, params=params)

    def get_assembly_task(self, task_id, headers):
        return self._request("GET", f"/assembly-tasks/{task_id}", headers=headers)

    def complete_assembly_task(self, task_id, headers):
        return self._request("POST", f"/assembly-tasks/{task_id}/complete", {}, headers)

    # --- Cleanliness certificates ---
    def create_cleanliness_certificate(self, payload, headers):
        return self._request("POST", "/cleanliness-certificates", payload, headers)

    def list_cleanliness_certificates(self, headers, params=None):
        return self._request("GET", "/cleanliness-certificates", headers=headers, params=params)

    def get_cleanliness_certificate(self, cert_id, headers):
        return self._request("GET", f"/cleanliness-certificates/{cert_id}", headers=headers)

    # --- Logical clock (PRD §2.5; test-driving capability) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
