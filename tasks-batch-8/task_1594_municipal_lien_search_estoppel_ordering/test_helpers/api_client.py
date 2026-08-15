"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Jurisdictions ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    def list_jurisdiction_search_orders(self, jurisdiction_id, headers, params=None):
        return self._request(
            "GET", f"/jurisdictions/{jurisdiction_id}/search-orders",
            headers=headers, params=params,
        )

    def deactivate_jurisdiction(self, jurisdiction_id, headers):
        return self._request(
            "POST", f"/jurisdictions/{jurisdiction_id}/deactivate", {}, headers
        )

    # --- Statutes ---
    def create_statute(self, payload, headers):
        return self._request("POST", "/statutes", payload, headers)

    def get_statute(self, statute_id, headers):
        return self._request("GET", f"/statutes/{statute_id}", headers=headers)

    def list_jurisdiction_statutes(self, jurisdiction_id, headers, params=None):
        return self._request(
            "GET", f"/jurisdictions/{jurisdiction_id}/statutes",
            headers=headers, params=params,
        )

    def list_statute_search_orders(self, statute_id, headers, params=None):
        return self._request(
            "GET", f"/statutes/{statute_id}/search-orders",
            headers=headers, params=params,
        )

    # --- Departments ---
    def create_department(self, payload, headers):
        return self._request("POST", "/departments", payload, headers)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/departments/{department_id}", headers=headers)

    def list_jurisdiction_departments(self, jurisdiction_id, headers, params=None):
        return self._request(
            "GET", f"/jurisdictions/{jurisdiction_id}/departments",
            headers=headers, params=params,
        )

    def list_department_research_tasks(self, department_id, headers, params=None):
        return self._request(
            "GET", f"/departments/{department_id}/research-tasks",
            headers=headers, params=params,
        )

    def deactivate_department(self, department_id, headers):
        return self._request(
            "POST", f"/departments/{department_id}/deactivate", {}, headers
        )

    # --- Associations ---
    def create_association(self, payload, headers):
        return self._request("POST", "/associations", payload, headers)

    def get_association(self, association_id, headers):
        return self._request("GET", f"/associations/{association_id}", headers=headers)

    def list_jurisdiction_associations(self, jurisdiction_id, headers, params=None):
        return self._request(
            "GET", f"/jurisdictions/{jurisdiction_id}/associations",
            headers=headers, params=params,
        )

    def list_association_search_orders(self, association_id, headers, params=None):
        return self._request(
            "GET", f"/associations/{association_id}/search-orders",
            headers=headers, params=params,
        )

    def list_association_estoppel_orders(self, association_id, headers, params=None):
        return self._request(
            "GET", f"/associations/{association_id}/estoppel-orders",
            headers=headers, params=params,
        )

    # --- Search orders ---
    def create_search_order(self, payload, headers):
        return self._request("POST", "/search-orders", payload, headers)

    def get_search_order(self, order_id, headers):
        return self._request("GET", f"/search-orders/{order_id}", headers=headers)

    def patch_search_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/search-orders/{order_id}", payload, headers)

    def identify_jurisdiction(self, order_id, payload, headers):
        return self._request(
            "POST", f"/search-orders/{order_id}/identify-jurisdiction", payload, headers
        )

    def cancel_search_order(self, order_id, headers):
        return self._request("POST", f"/search-orders/{order_id}/cancel", {}, headers)

    def submit_for_verification(self, order_id, headers):
        return self._request(
            "POST", f"/search-orders/{order_id}/submit-for-verification", {}, headers
        )

    def verify_payoff(self, order_id, payload, headers):
        return self._request(
            "POST", f"/search-orders/{order_id}/verify-payoff", payload, headers
        )

    def reject_verification(self, order_id, payload, headers):
        return self._request(
            "POST", f"/search-orders/{order_id}/reject-verification", payload, headers
        )

    def get_search_order_summary(self, order_id, headers):
        return self._request(
            "GET", f"/search-orders/{order_id}/summary", headers=headers
        )

    # --- Research tasks ---
    def list_order_research_tasks(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/search-orders/{order_id}/research-tasks",
            headers=headers, params=params,
        )

    def get_research_task(self, task_id, headers):
        return self._request("GET", f"/research-tasks/{task_id}", headers=headers)

    def record_findings(self, task_id, payload, headers):
        return self._request(
            "POST", f"/research-tasks/{task_id}/record-findings", payload, headers
        )

    def complete_task(self, task_id, headers):
        return self._request("POST", f"/research-tasks/{task_id}/complete", {}, headers)

    def mark_unreachable(self, task_id, payload, headers):
        return self._request(
            "POST", f"/research-tasks/{task_id}/mark-unreachable", payload, headers
        )

    # --- Estoppel orders ---
    def list_order_estoppel_orders(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/search-orders/{order_id}/estoppel-orders",
            headers=headers, params=params,
        )

    def get_estoppel_order(self, estoppel_id, headers):
        return self._request("GET", f"/estoppel-orders/{estoppel_id}", headers=headers)

    def place_estoppel(self, estoppel_id, payload, headers):
        return self._request(
            "POST", f"/estoppel-orders/{estoppel_id}/place", payload, headers
        )

    def receive_estoppel(self, estoppel_id, payload, headers):
        return self._request(
            "POST", f"/estoppel-orders/{estoppel_id}/receive", payload, headers
        )

    def cancel_estoppel(self, estoppel_id, headers):
        return self._request(
            "POST", f"/estoppel-orders/{estoppel_id}/cancel", {}, headers
        )

    # --- Discrepancies ---
    def create_discrepancy(self, payload, headers):
        return self._request("POST", "/discrepancies", payload, headers)

    def get_discrepancy(self, discrepancy_id, headers):
        return self._request("GET", f"/discrepancies/{discrepancy_id}", headers=headers)

    def list_order_discrepancies(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/search-orders/{order_id}/discrepancies",
            headers=headers, params=params,
        )

    def start_review(self, discrepancy_id, headers):
        return self._request(
            "POST", f"/discrepancies/{discrepancy_id}/start-review", {}, headers
        )

    def resolve_discrepancy(self, discrepancy_id, payload, headers):
        return self._request(
            "POST", f"/discrepancies/{discrepancy_id}/resolve", payload, headers
        )

    # --- Deliveries ---
    def create_delivery(self, payload, headers):
        return self._request("POST", "/deliveries", payload, headers)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/deliveries/{delivery_id}", headers=headers)

    def list_order_deliveries(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/search-orders/{order_id}/deliveries",
            headers=headers, params=params,
        )

    def deliver_delivery(self, delivery_id, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/deliver", {}, headers)

    def acknowledge_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/deliveries/{delivery_id}/acknowledge", {}, headers
        )


api_client = ApiClient()
