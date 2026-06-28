"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles
the envelope, headers, and HTTP plumbing.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/copack/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/copack/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/copack/customers", headers=headers, params=params)

    # ---- Components ----
    def create_component(self, payload, headers):
        return self._request("POST", "/copack/components", payload, headers)

    def get_component(self, component_id, headers):
        return self._request("GET", f"/copack/components/{component_id}", headers=headers)

    def list_components(self, headers, params=None):
        return self._request("GET", "/copack/components", headers=headers, params=params)

    # ---- Component Lots ----
    def receive_lot(self, component_id, payload, headers):
        return self._request("POST", f"/copack/components/{component_id}/lots", payload, headers)

    def list_component_lots(self, component_id, headers, params=None):
        return self._request("GET", f"/copack/components/{component_id}/lots", headers=headers, params=params)

    def get_component_lot(self, lot_id, headers):
        return self._request("GET", f"/copack/component-lots/{lot_id}", headers=headers)

    # ---- Recipes & BOM ----
    def create_recipe(self, payload, headers):
        return self._request("POST", "/copack/recipes", payload, headers)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/copack/recipes/{recipe_id}", headers=headers)

    def list_recipes(self, headers, params=None):
        return self._request("GET", "/copack/recipes", headers=headers, params=params)

    def add_bom_line(self, recipe_id, payload, headers):
        return self._request("POST", f"/copack/recipes/{recipe_id}/bom-lines", payload, headers)

    def list_bom_lines(self, recipe_id, headers, params=None):
        return self._request("GET", f"/copack/recipes/{recipe_id}/bom-lines", headers=headers, params=params)

    def get_bom_line(self, bom_line_id, headers):
        return self._request("GET", f"/copack/bom-lines/{bom_line_id}", headers=headers)

    def list_all_bom_lines(self, headers, params=None):
        return self._request("GET", "/copack/bom-lines", headers=headers, params=params)

    def submit_recipe(self, recipe_id, headers, payload=None):
        return self._request("POST", f"/copack/recipes/{recipe_id}/submit", payload or {}, headers)

    def approve_recipe(self, recipe_id, headers, payload=None):
        return self._request("POST", f"/copack/recipes/{recipe_id}/approve", payload or {}, headers)

    def reject_recipe(self, recipe_id, headers, payload=None):
        return self._request("POST", f"/copack/recipes/{recipe_id}/reject", payload or {}, headers)

    def revise_recipe(self, recipe_id, headers, payload=None):
        return self._request("POST", f"/copack/recipes/{recipe_id}/revise", payload or {}, headers)

    def retire_recipe(self, recipe_id, headers, payload=None):
        return self._request("POST", f"/copack/recipes/{recipe_id}/retire", payload or {}, headers)

    # ---- Production Lines ----
    def create_production_line(self, payload, headers):
        return self._request("POST", "/copack/production-lines", payload, headers)

    def get_production_line(self, line_id, headers):
        return self._request("GET", f"/copack/production-lines/{line_id}", headers=headers)

    def list_production_lines(self, headers, params=None):
        return self._request("GET", "/copack/production-lines", headers=headers, params=params)

    def create_sanitation_event(self, line_id, headers, payload=None):
        return self._request("POST", f"/copack/production-lines/{line_id}/sanitation-events", payload or {}, headers)

    def list_sanitation_events(self, line_id, headers, params=None):
        return self._request("GET", f"/copack/production-lines/{line_id}/sanitation-events", headers=headers, params=params)

    # ---- Crews ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/copack/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/copack/crews/{crew_id}", headers=headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/copack/crews", headers=headers, params=params)

    # ---- Production Runs ----
    def schedule_run(self, payload, headers):
        return self._request("POST", "/copack/production-runs", payload, headers)

    def get_run(self, run_id, headers):
        return self._request("GET", f"/copack/production-runs/{run_id}", headers=headers)

    def list_runs(self, headers, params=None):
        return self._request("GET", "/copack/production-runs", headers=headers, params=params)

    def get_run_summary(self, run_id, headers):
        return self._request("GET", f"/copack/production-runs/{run_id}/summary", headers=headers)

    def start_run(self, run_id, payload, headers):
        return self._request("POST", f"/copack/production-runs/{run_id}/start", payload, headers)

    def complete_run(self, run_id, payload, headers):
        return self._request("POST", f"/copack/production-runs/{run_id}/complete", payload, headers)

    def add_checkweigh_sample(self, run_id, payload, headers):
        return self._request("POST", f"/copack/production-runs/{run_id}/checkweigh-samples", payload, headers)

    def list_checkweigh_samples(self, run_id, headers, params=None):
        return self._request("GET", f"/copack/production-runs/{run_id}/checkweigh-samples", headers=headers, params=params)

    def release_run(self, run_id, headers, payload=None):
        return self._request("POST", f"/copack/production-runs/{run_id}/release", payload or {}, headers)

    def quarantine_run(self, run_id, headers, payload=None):
        return self._request("POST", f"/copack/production-runs/{run_id}/quarantine", payload or {}, headers)

    def cancel_run(self, run_id, headers, payload=None):
        return self._request("POST", f"/copack/production-runs/{run_id}/cancel", payload or {}, headers)

    # ---- LotConsumption & CMR reads ----
    def list_run_lot_consumptions(self, run_id, headers, params=None):
        return self._request("GET", f"/copack/production-runs/{run_id}/lot-consumptions", headers=headers, params=params)

    def get_lot_consumption(self, consumption_id, headers):
        return self._request("GET", f"/copack/lot-consumptions/{consumption_id}", headers=headers)

    def list_lot_consumptions(self, headers, params=None):
        return self._request("GET", "/copack/lot-consumptions", headers=headers, params=params)

    def get_cmr_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/copack/cmr-ledger-entries/{entry_id}", headers=headers)

    def list_cmr_ledger_entries(self, headers, params=None):
        return self._request("GET", "/copack/cmr-ledger-entries", headers=headers, params=params)

    # ---- Test-driving: logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/copack/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
