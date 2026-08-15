"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Distributors
    # ------------------------------------------------------------------
    def create_distributor(self, payload, headers):
        return self._request("POST", "/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"/distributors/{distributor_id}",
                             headers=headers)

    def patch_distributor(self, distributor_id, payload, headers):
        return self._request("PATCH", f"/distributors/{distributor_id}",
                             payload, headers)

    # ------------------------------------------------------------------
    # Core returns & deposits
    # ------------------------------------------------------------------
    def create_core_return(self, payload, headers):
        return self._request("POST", "/core-returns", payload, headers)

    def list_core_returns(self, headers, params=None):
        return self._request("GET", "/core-returns", headers=headers,
                             params=params)

    def get_core_return(self, return_id, headers):
        return self._request("GET", f"/core-returns/{return_id}",
                             headers=headers)

    def grade_core_return(self, return_id, payload, headers):
        return self._request("POST", f"/core-returns/{return_id}/grade",
                             payload, headers)

    def respond_core_return(self, return_id, payload, headers):
        return self._request("POST", f"/core-returns/{return_id}/respond",
                             payload, headers)

    def list_core_deposits(self, headers, params=None):
        return self._request("GET", "/core-deposits", headers=headers,
                             params=params)

    def get_core_deposit(self, deposit_id, headers):
        return self._request("GET", f"/core-deposits/{deposit_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Build specs
    # ------------------------------------------------------------------
    def create_build_spec(self, payload, headers):
        return self._request("POST", "/build-specs", payload, headers)

    def list_build_specs(self, headers, params=None):
        return self._request("GET", "/build-specs", headers=headers,
                             params=params)

    def get_build_spec(self, spec_id, headers):
        return self._request("GET", f"/build-specs/{spec_id}", headers=headers)

    def activate_build_spec(self, spec_id, headers):
        return self._request("POST", f"/build-specs/{spec_id}/activate",
                             {}, headers)

    def retire_build_spec(self, spec_id, headers):
        return self._request("POST", f"/build-specs/{spec_id}/retire",
                             {}, headers)

    # ------------------------------------------------------------------
    # Work orders, route, components
    # ------------------------------------------------------------------
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers,
                             params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}",
                             headers=headers)

    def advance_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/advance",
                             payload, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel",
                             {}, headers)

    def declare_operation(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/operations",
                             payload, headers)

    def list_operations(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/operations",
                             headers=headers, params=params)

    def perform_operation(self, operation_id, payload, headers):
        return self._request("POST", f"/operations/{operation_id}/perform",
                             payload, headers)

    def salvage_component(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/components",
                             payload, headers)

    def list_components(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/components",
                             headers=headers, params=params)

    def get_component(self, component_id, headers):
        return self._request("GET", f"/components/{component_id}",
                             headers=headers)

    def inspect_component(self, component_id, payload, headers):
        return self._request("POST", f"/components/{component_id}/inspect",
                             payload, headers)

    def consume_component(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/consume",
                             payload, headers)

    # ------------------------------------------------------------------
    # Engines, dyno, seal, sale
    # ------------------------------------------------------------------
    def list_reman_engines(self, headers, params=None):
        return self._request("GET", "/reman-engines", headers=headers,
                             params=params)

    def get_reman_engine(self, engine_id, headers):
        return self._request("GET", f"/reman-engines/{engine_id}",
                             headers=headers)

    def record_dyno_test(self, engine_id, payload, headers):
        return self._request("POST", f"/reman-engines/{engine_id}/dyno-tests",
                             payload, headers)

    def list_dyno_tests(self, engine_id, headers, params=None):
        return self._request("GET", f"/reman-engines/{engine_id}/dyno-tests",
                             headers=headers, params=params)

    def seal_reman_engine(self, engine_id, headers):
        return self._request("POST", f"/reman-engines/{engine_id}/seal",
                             {}, headers)

    def sell_reman_engine(self, payload, headers):
        return self._request("POST", "/reman-engines/sell", payload, headers)

    # ------------------------------------------------------------------
    # Warranty claims
    # ------------------------------------------------------------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers,
                             params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}",
                             headers=headers)

    def teardown_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/teardown",
                             payload, headers)

    def adjudicate_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/adjudicate",
                             payload, headers)

    # ------------------------------------------------------------------
    # Aging sweep
    # ------------------------------------------------------------------
    def run_aging(self, headers):
        return self._request("POST", "/aging-runs", {}, headers)


api_client = ApiClient()
