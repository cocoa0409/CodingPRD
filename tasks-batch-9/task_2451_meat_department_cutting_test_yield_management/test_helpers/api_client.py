"""API client: one method per endpoint defined in the PRD (§4).

Every endpoint is mounted under `/meat-ops`, with the single exception of the
logical-clock control which is mounted at the server root.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/meat-ops"


class ApiClient(GenericApiClient):
    """Typed access to every endpoint of the Meat Department Yield Management
    API. Every method returns the raw response so tests can assert status codes
    and error envelopes."""

    # ------------------------------------------------------------------
    # Departments
    # ------------------------------------------------------------------
    def create_department(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/departments", payload, headers)

    def get_department(self, department_id: str, headers=None):
        return self._request("GET", f"{BASE}/departments/{department_id}", headers=headers)

    # ------------------------------------------------------------------
    # Primal purchases
    # ------------------------------------------------------------------
    def create_primal_purchase(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/primal-purchases", payload, headers)

    def get_primal_purchase(self, purchase_id: str, headers=None):
        return self._request("GET", f"{BASE}/primal-purchases/{purchase_id}", headers=headers)

    def list_department_primal_purchases(self, department_id: str, headers=None, params=None):
        return self._request(
            "GET",
            f"{BASE}/departments/{department_id}/primal-purchases",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Retail items
    # ------------------------------------------------------------------
    def create_retail_item(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/retail-items", payload, headers)

    def get_retail_item(self, item_id: str, headers=None):
        return self._request("GET", f"{BASE}/retail-items/{item_id}", headers=headers)

    def list_department_retail_items(self, department_id: str, headers=None, params=None):
        return self._request(
            "GET",
            f"{BASE}/departments/{department_id}/retail-items",
            headers=headers,
            params=params,
        )

    def create_price_proposal(self, item_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/retail-items/{item_id}/price-proposals", payload, headers
        )

    def create_price_activation(self, item_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/retail-items/{item_id}/price-activations", payload, headers
        )

    def transition_retail_item(self, item_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/retail-items/{item_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # Cutting tests and their yield lines
    # ------------------------------------------------------------------
    def create_cutting_test(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/cutting-tests", payload, headers)

    def get_cutting_test(self, test_id: str, headers=None):
        return self._request("GET", f"{BASE}/cutting-tests/{test_id}", headers=headers)

    def list_purchase_cutting_tests(self, purchase_id: str, headers=None, params=None):
        return self._request(
            "GET",
            f"{BASE}/primal-purchases/{purchase_id}/cutting-tests",
            headers=headers,
            params=params,
        )

    def create_cutting_test_line(self, test_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/cutting-tests/{test_id}/lines", payload, headers
        )

    def get_cutting_test_line(self, line_id: str, headers=None):
        return self._request("GET", f"{BASE}/cutting-test-lines/{line_id}", headers=headers)

    def list_cutting_test_lines(self, headers=None, params=None):
        return self._request(
            "GET", f"{BASE}/cutting-test-lines", headers=headers, params=params
        )

    def transition_cutting_test(self, test_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/cutting-tests/{test_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # Case plans, their lines and the line events
    # ------------------------------------------------------------------
    def create_case_plan(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/case-plans", payload, headers)

    def get_case_plan(self, plan_id: str, headers=None):
        return self._request("GET", f"{BASE}/case-plans/{plan_id}", headers=headers)

    def list_department_case_plans(self, department_id: str, headers=None, params=None):
        return self._request(
            "GET",
            f"{BASE}/departments/{department_id}/case-plans",
            headers=headers,
            params=params,
        )

    def create_case_plan_line(self, plan_id: str, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/case-plans/{plan_id}/lines", payload, headers)

    def get_case_plan_line(self, line_id: str, headers=None):
        return self._request("GET", f"{BASE}/case-plan-lines/{line_id}", headers=headers)

    def list_case_plan_lines(self, headers=None, params=None):
        return self._request("GET", f"{BASE}/case-plan-lines", headers=headers, params=params)

    def transition_case_plan(self, plan_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/case-plans/{plan_id}/transitions", payload, headers
        )

    def create_fill(self, line_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/case-plan-lines/{line_id}/fills", payload, headers
        )

    def create_markdown(self, line_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/case-plan-lines/{line_id}/markdowns", payload, headers
        )

    def create_shrink_event(self, line_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/case-plan-lines/{line_id}/shrink-events", payload, headers
        )

    # ------------------------------------------------------------------
    # Trim lots
    # ------------------------------------------------------------------
    def create_trim_lot(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/trim-lots", payload, headers)

    def get_trim_lot(self, lot_id: str, headers=None):
        return self._request("GET", f"{BASE}/trim-lots/{lot_id}", headers=headers)

    def list_trim_lots(self, headers=None, params=None):
        return self._request("GET", f"{BASE}/trim-lots", headers=headers, params=params)

    def transition_trim_lot(self, lot_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/trim-lots/{lot_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # Grind runs and their inputs
    # ------------------------------------------------------------------
    def create_grind_run(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/grind-runs", payload, headers)

    def get_grind_run(self, run_id: str, headers=None):
        return self._request("GET", f"{BASE}/grind-runs/{run_id}", headers=headers)

    def list_grind_runs(self, headers=None, params=None):
        return self._request("GET", f"{BASE}/grind-runs", headers=headers, params=params)

    def create_grind_input(self, run_id: str, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/grind-runs/{run_id}/inputs", payload, headers)

    def get_grind_input(self, input_id: str, headers=None):
        return self._request("GET", f"{BASE}/grind-inputs/{input_id}", headers=headers)

    def list_grind_inputs(self, headers=None, params=None):
        return self._request("GET", f"{BASE}/grind-inputs", headers=headers, params=params)

    def transition_grind_run(self, run_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/grind-runs/{run_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # Temperature readings and case failures
    # ------------------------------------------------------------------
    def create_temperature_log(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/temperature-logs", payload, headers)

    def get_temperature_log(self, log_id: str, headers=None):
        return self._request("GET", f"{BASE}/temperature-logs/{log_id}", headers=headers)

    def list_department_temperature_logs(self, department_id: str, headers=None, params=None):
        return self._request(
            "GET",
            f"{BASE}/departments/{department_id}/temperature-logs",
            headers=headers,
            params=params,
        )

    def get_case_failure(self, failure_id: str, headers=None):
        return self._request("GET", f"{BASE}/case-failures/{failure_id}", headers=headers)

    def list_case_failures(self, headers=None, params=None):
        return self._request("GET", f"{BASE}/case-failures", headers=headers, params=params)

    def transition_case_failure(self, failure_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/case-failures/{failure_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # Pre-orders
    # ------------------------------------------------------------------
    def create_pre_order(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/pre-orders", payload, headers)

    def get_pre_order(self, order_id: str, headers=None):
        return self._request("GET", f"{BASE}/pre-orders/{order_id}", headers=headers)

    def list_pre_orders(self, headers=None, params=None):
        return self._request("GET", f"{BASE}/pre-orders", headers=headers, params=params)

    def transition_pre_order(self, order_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{BASE}/pre-orders/{order_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # Shrink reconciliations
    # ------------------------------------------------------------------
    def create_shrink_reconciliation(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{BASE}/shrink-reconciliations", payload, headers)

    def get_shrink_reconciliation(self, recon_id: str, headers=None):
        return self._request(
            "GET", f"{BASE}/shrink-reconciliations/{recon_id}", headers=headers
        )

    def list_department_shrink_reconciliations(
        self, department_id: str, headers=None, params=None
    ):
        return self._request(
            "GET",
            f"{BASE}/departments/{department_id}/shrink-reconciliations",
            headers=headers,
            params=params,
        )

    def transition_shrink_reconciliation(
        self, recon_id: str, payload: Dict[str, Any], headers=None
    ):
        return self._request(
            "POST", f"{BASE}/shrink-reconciliations/{recon_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # Logical clock (mounted at the server root, not under /meat-ops)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Raw escape hatch — lets a test send arbitrary or partial headers
    # (for example a request that omits X-User-ID entirely).
    # ------------------------------------------------------------------
    def raw_request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
