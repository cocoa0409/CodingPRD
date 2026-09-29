"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the fire protection hydraulic design API."""

    # --- Directory ---------------------------------------------------------
    def create_engineer(self, payload, headers):
        return self._request("POST", "/engineers", payload, headers)

    def create_ahj_reviewer(self, payload, headers):
        return self._request("POST", "/ahj-reviewers", payload, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Projects ----------------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def pay_review_fee(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/fee-payments", payload, headers
        )

    # --- Hazard areas ------------------------------------------------------
    def create_hazard_area(self, payload, headers):
        return self._request("POST", "/hazard-areas", payload, headers)

    def get_hazard_area(self, hazard_area_id, headers):
        return self._request("GET", f"/hazard-areas/{hazard_area_id}", headers=headers)

    def list_hazard_areas(self, headers, params=None):
        return self._request("GET", "/hazard-areas", headers=headers, params=params)

    def reclassify_hazard_area(self, hazard_area_id, payload, headers):
        return self._request(
            "POST", f"/hazard-areas/{hazard_area_id}/reclassify", payload, headers
        )

    # --- Flow tests --------------------------------------------------------
    def create_flow_test(self, payload, headers):
        return self._request("POST", "/flow-tests", payload, headers)

    def list_project_flow_tests(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/flow-tests", headers=headers, params=params
        )

    # --- Water supply evaluations -----------------------------------------
    def create_water_supply_evaluation(self, payload, headers):
        return self._request("POST", "/water-supply-evaluations", payload, headers)

    def get_water_supply_evaluation(self, evaluation_id, headers):
        return self._request(
            "GET", f"/water-supply-evaluations/{evaluation_id}", headers=headers
        )

    def list_water_supply_evaluations(self, headers, params=None):
        return self._request(
            "GET", "/water-supply-evaluations", headers=headers, params=params
        )

    # --- Hydraulic calculations -------------------------------------------
    def create_hydraulic_calculation(self, payload, headers):
        return self._request("POST", "/hydraulic-calculations", payload, headers)

    def get_hydraulic_calculation(self, calculation_id, headers):
        return self._request(
            "GET", f"/hydraulic-calculations/{calculation_id}", headers=headers
        )

    def list_hydraulic_calculations(self, headers, params=None):
        return self._request(
            "GET", "/hydraulic-calculations", headers=headers, params=params
        )

    def append_iteration(self, calculation_id, payload, headers):
        return self._request(
            "POST",
            f"/hydraulic-calculations/{calculation_id}/iterations",
            payload,
            headers,
        )

    def list_iterations(self, calculation_id, headers, params=None):
        return self._request(
            "GET",
            f"/hydraulic-calculations/{calculation_id}/iterations",
            headers=headers,
            params=params,
        )

    def list_calculation_submittals(self, calculation_id, headers, params=None):
        return self._request(
            "GET",
            f"/hydraulic-calculations/{calculation_id}/submittals",
            headers=headers,
            params=params,
        )

    def qc_review_calculation(self, calculation_id, payload, headers):
        return self._request(
            "POST", f"/hydraulic-calculations/{calculation_id}/qc-review", payload, headers
        )

    def seal_calculation(self, calculation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/hydraulic-calculations/{calculation_id}/seal",
            payload if payload is not None else {},
            headers,
        )

    # --- Fire pumps --------------------------------------------------------
    def create_fire_pump(self, payload, headers):
        return self._request("POST", "/fire-pumps", payload, headers)

    def get_fire_pump(self, fire_pump_id, headers):
        return self._request("GET", f"/fire-pumps/{fire_pump_id}", headers=headers)

    def list_fire_pumps(self, headers, params=None):
        return self._request("GET", "/fire-pumps", headers=headers, params=params)

    # --- Auxiliary systems -------------------------------------------------
    def create_auxiliary_system(self, payload, headers):
        return self._request("POST", "/auxiliary-systems", payload, headers)

    def get_auxiliary_system(self, system_id, headers):
        return self._request("GET", f"/auxiliary-systems/{system_id}", headers=headers)

    def list_auxiliary_systems(self, headers, params=None):
        return self._request("GET", "/auxiliary-systems", headers=headers, params=params)

    def commission_auxiliary_system(self, system_id, payload, headers):
        return self._request(
            "POST", f"/auxiliary-systems/{system_id}/commission", payload, headers
        )

    def withdraw_auxiliary_system(self, system_id, headers, payload=None):
        return self._request(
            "POST",
            f"/auxiliary-systems/{system_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    # --- Shop drawings and trade clearances --------------------------------
    def create_shop_drawing(self, payload, headers):
        return self._request("POST", "/shop-drawings", payload, headers)

    def get_shop_drawing(self, shop_drawing_id, headers):
        return self._request("GET", f"/shop-drawings/{shop_drawing_id}", headers=headers)

    def list_shop_drawings(self, headers, params=None):
        return self._request("GET", "/shop-drawings", headers=headers, params=params)

    def create_trade_clearance(self, shop_drawing_id, payload, headers):
        return self._request(
            "POST", f"/shop-drawings/{shop_drawing_id}/trade-clearances", payload, headers
        )

    def list_trade_clearances(self, shop_drawing_id, headers, params=None):
        return self._request(
            "GET",
            f"/shop-drawings/{shop_drawing_id}/trade-clearances",
            headers=headers,
            params=params,
        )

    def record_trade_clearance(self, trade_clearance_id, payload, headers):
        return self._request(
            "POST", f"/trade-clearances/{trade_clearance_id}/record", payload, headers
        )

    # --- Submittals and review comments ------------------------------------
    def create_submittal(self, payload, headers):
        return self._request("POST", "/submittals", payload, headers)

    def get_submittal(self, submittal_id, headers):
        return self._request("GET", f"/submittals/{submittal_id}", headers=headers)

    def list_submittals(self, headers, params=None):
        return self._request("GET", "/submittals", headers=headers, params=params)

    def begin_review(self, submittal_id, headers, payload=None):
        return self._request(
            "POST",
            f"/submittals/{submittal_id}/begin-review",
            payload if payload is not None else {},
            headers,
        )

    def create_review_comment(self, submittal_id, payload, headers):
        return self._request(
            "POST", f"/submittals/{submittal_id}/comments", payload, headers
        )

    def complete_review(self, submittal_id, headers, payload=None):
        return self._request(
            "POST",
            f"/submittals/{submittal_id}/complete-review",
            payload if payload is not None else {},
            headers,
        )

    def resubmit(self, submittal_id, payload, headers):
        return self._request(
            "POST", f"/submittals/{submittal_id}/resubmit", payload, headers
        )

    def get_review_comment(self, comment_id, headers):
        return self._request("GET", f"/review-comments/{comment_id}", headers=headers)

    def list_review_comments(self, headers, params=None):
        return self._request("GET", "/review-comments", headers=headers, params=params)

    def respond_to_review_comment(self, comment_id, payload, headers):
        return self._request(
            "POST", f"/review-comments/{comment_id}/respond", payload, headers
        )

    def close_review_comment(self, comment_id, payload, headers):
        return self._request(
            "POST", f"/review-comments/{comment_id}/close", payload, headers
        )

    # --- Acceptance tests --------------------------------------------------
    def create_acceptance_test(self, payload, headers):
        return self._request("POST", "/acceptance-tests", payload, headers)

    def get_acceptance_test(self, acceptance_test_id, headers):
        return self._request(
            "GET", f"/acceptance-tests/{acceptance_test_id}", headers=headers
        )

    def list_acceptance_tests(self, headers, params=None):
        return self._request("GET", "/acceptance-tests", headers=headers, params=params)

    def schedule_witness(self, acceptance_test_id, payload, headers):
        return self._request(
            "POST",
            f"/acceptance-tests/{acceptance_test_id}/schedule-witness",
            payload,
            headers,
        )

    def record_witness(self, acceptance_test_id, payload, headers):
        return self._request(
            "POST",
            f"/acceptance-tests/{acceptance_test_id}/record-witness",
            payload,
            headers,
        )

    def submit_as_built(self, acceptance_test_id, payload, headers):
        return self._request(
            "POST",
            f"/acceptance-tests/{acceptance_test_id}/submit-as-built",
            payload,
            headers,
        )

    def accept_as_built(self, acceptance_test_id, payload, headers):
        return self._request(
            "POST",
            f"/acceptance-tests/{acceptance_test_id}/accept-as-built",
            payload,
            headers,
        )


api_client = ApiClient()
