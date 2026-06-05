"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- ServiceCategory ----
    def create_category(self, payload, headers):
        return self._request("POST", "/categories", payload, headers)

    def get_category(self, category_id, headers):
        return self._request("GET", f"/categories/{category_id}", headers=headers)

    def list_categories(self, headers, params=None):
        return self._request("GET", "/categories", headers=headers, params=params)

    def list_category_sla_policies(self, category_id, headers, params=None):
        return self._request(
            "GET", f"/categories/{category_id}/sla-policies", headers=headers, params=params
        )

    # ---- Jurisdiction ----
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    def list_jurisdiction_blackout_windows(self, jurisdiction_id, headers, params=None):
        return self._request(
            "GET", f"/jurisdictions/{jurisdiction_id}/blackout-windows", headers=headers, params=params
        )

    # ---- Department ----
    def create_department(self, payload, headers):
        return self._request("POST", "/departments", payload, headers)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/departments/{department_id}", headers=headers)

    def get_department_satisfaction(self, department_id, headers):
        return self._request(
            "GET", f"/departments/{department_id}/satisfaction", headers=headers
        )

    def list_department_jurisdictions(self, department_id, headers, params=None):
        return self._request(
            "GET", f"/departments/{department_id}/jurisdictions", headers=headers, params=params
        )

    def list_department_agents(self, department_id, headers, params=None):
        return self._request(
            "GET", f"/departments/{department_id}/agents", headers=headers, params=params
        )

    def list_department_maintenance_windows(self, department_id, headers, params=None):
        return self._request(
            "GET", f"/departments/{department_id}/maintenance-windows", headers=headers, params=params
        )

    # ---- SlaPolicy ----
    def create_sla_policy(self, payload, headers):
        return self._request("POST", "/sla-policies", payload, headers)

    # ---- Citizen ----
    def create_citizen(self, payload, headers):
        return self._request("POST", "/citizens", payload, headers)

    # ---- Agent ----
    def create_agent(self, payload, headers):
        return self._request("POST", "/agents", payload, headers)

    # ---- ServiceRequest ----
    def create_service_request(self, payload, headers):
        return self._request("POST", "/service-requests", payload, headers)

    def get_service_request(self, request_id, headers):
        return self._request("GET", f"/service-requests/{request_id}", headers=headers)

    def list_service_requests(self, headers, params=None):
        return self._request("GET", "/service-requests", headers=headers, params=params)

    def triage_service_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/service-requests/{request_id}/triage", payload, headers
        )

    def route_service_request(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/service-requests/{request_id}/route", payload or {}, headers
        )

    def reopen_service_request(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/service-requests/{request_id}/reopen", payload or {}, headers
        )

    def close_service_request(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/service-requests/{request_id}/close", payload or {}, headers
        )

    def list_request_notifications(self, request_id, headers, params=None):
        return self._request(
            "GET", f"/service-requests/{request_id}/notifications", headers=headers, params=params
        )

    def list_request_escalations(self, request_id, headers, params=None):
        return self._request(
            "GET", f"/service-requests/{request_id}/escalations", headers=headers, params=params
        )

    # ---- DuplicateCluster ----
    def create_duplicate_cluster(self, payload, headers):
        return self._request("POST", "/duplicate-clusters", payload, headers)

    def get_duplicate_cluster(self, cluster_id, headers):
        return self._request("GET", f"/duplicate-clusters/{cluster_id}", headers=headers)

    def list_duplicate_clusters(self, headers, params=None):
        return self._request("GET", "/duplicate-clusters", headers=headers, params=params)

    def add_cluster_member(self, cluster_id, payload, headers):
        return self._request(
            "POST", f"/duplicate-clusters/{cluster_id}/members", payload, headers
        )

    def close_duplicate_cluster(self, cluster_id, headers, payload=None):
        return self._request(
            "POST", f"/duplicate-clusters/{cluster_id}/close", payload or {}, headers
        )

    # ---- WorkOrder ----
    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def assign_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/assign", payload, headers
        )

    def start_work_order(self, work_order_id, headers, payload=None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/start", payload or {}, headers
        )

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/complete", payload, headers
        )

    def cancel_work_order(self, work_order_id, headers, payload=None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/cancel", payload or {}, headers
        )

    # ---- Escalation ----
    def create_escalation(self, payload, headers):
        return self._request("POST", "/escalations", payload, headers)

    def resolve_escalation(self, escalation_id, headers, payload=None):
        return self._request(
            "POST", f"/escalations/{escalation_id}/resolve", payload or {}, headers
        )

    # ---- SatisfactionSurvey ----
    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/surveys/{survey_id}", headers=headers)

    def list_surveys(self, headers, params=None):
        return self._request("GET", "/surveys", headers=headers, params=params)

    def respond_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/surveys/{survey_id}/respond", payload, headers)

    # ---- ServiceWindow ----
    def create_service_window(self, payload, headers):
        return self._request("POST", "/service-windows", payload, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
