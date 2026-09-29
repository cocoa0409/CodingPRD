"""API client: one method per endpoint defined in the PRD.

Every path is mounted beneath the /energy-ops prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/energy-ops"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_current_utc(self, current_utc, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    # ------------------------------------------------------------------
    # Stores
    # ------------------------------------------------------------------
    def create_store(self, payload, headers):
        return self._request("POST", f"{PREFIX}/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"{PREFIX}/stores/{store_id}", headers=headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/stores", headers=headers, params=params)

    def commission_bms(self, store_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/bms-commissioning", payload, headers,
        )

    def activate_bms(self, store_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/bms-activation", payload or {}, headers,
        )

    # ------------------------------------------------------------------
    # Setpoint standards
    # ------------------------------------------------------------------
    def create_setpoint_standard(self, payload, headers):
        return self._request("POST", f"{PREFIX}/setpoint-standards", payload, headers)

    def get_setpoint_standard(self, standard_id, headers):
        return self._request(
            "GET", f"{PREFIX}/setpoint-standards/{standard_id}", headers=headers,
        )

    def list_setpoint_standards(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/setpoint-standards", headers=headers, params=params,
        )

    def publish_setpoint_standard(self, standard_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/setpoint-standards/{standard_id}/publish",
            payload or {}, headers,
        )

    # ------------------------------------------------------------------
    # Utility accounts
    # ------------------------------------------------------------------
    def create_utility_account(self, store_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/utility-accounts", payload, headers,
        )

    def get_utility_account(self, account_id, headers):
        return self._request(
            "GET", f"{PREFIX}/utility-accounts/{account_id}", headers=headers,
        )

    def list_store_utility_accounts(self, store_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/stores/{store_id}/utility-accounts",
            headers=headers, params=params,
        )

    def tariff_switch(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/utility-accounts/{account_id}/tariff-switch",
            payload, headers,
        )

    def get_tariff_comparison(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/utility-accounts/{account_id}/tariff-comparison",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Demand intervals
    # ------------------------------------------------------------------
    def ingest_demand_intervals(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/utility-accounts/{account_id}/demand-intervals",
            payload, headers,
        )

    def list_demand_intervals(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/utility-accounts/{account_id}/demand-intervals",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Utility bills
    # ------------------------------------------------------------------
    def create_utility_bill(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/utility-accounts/{account_id}/utility-bills",
            payload, headers,
        )

    def list_utility_bills(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/utility-accounts/{account_id}/utility-bills",
            headers=headers, params=params,
        )

    def recompute_utility_bill(self, bill_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/utility-bills/{bill_id}/recompute", payload or {}, headers,
        )

    def dispute_utility_bill(self, bill_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/utility-bills/{bill_id}/dispute", payload, headers,
        )

    def adjust_utility_bill(self, bill_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/utility-bills/{bill_id}/adjustment", payload, headers,
        )

    # ------------------------------------------------------------------
    # Demand response events
    # ------------------------------------------------------------------
    def create_demand_response_event(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/utility-accounts/{account_id}/demand-response-events",
            payload, headers,
        )

    def list_demand_response_events(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/utility-accounts/{account_id}/demand-response-events",
            headers=headers, params=params,
        )

    def notify_demand_response_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/demand-response-events/{event_id}/notify",
            payload or {}, headers,
        )

    def activate_demand_response_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/demand-response-events/{event_id}/activate",
            payload or {}, headers,
        )

    def settle_demand_response_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/demand-response-events/{event_id}/settle",
            payload or {}, headers,
        )

    def reverse_demand_response_settlement(self, event_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/demand-response-events/{event_id}/reverse-settlement",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Refrigeration cases and readings
    # ------------------------------------------------------------------
    def create_refrigeration_case(self, store_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/refrigeration-cases", payload, headers,
        )

    def get_refrigeration_case(self, case_id, headers):
        return self._request(
            "GET", f"{PREFIX}/refrigeration-cases/{case_id}", headers=headers,
        )

    def list_store_refrigeration_cases(self, store_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/stores/{store_id}/refrigeration-cases",
            headers=headers, params=params,
        )

    def post_reading(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/refrigeration-cases/{case_id}/readings", payload, headers,
        )

    def set_monitoring_state(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/refrigeration-cases/{case_id}/monitoring-state",
            payload, headers,
        )

    def list_case_excursions(self, case_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/refrigeration-cases/{case_id}/excursions",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Excursions
    # ------------------------------------------------------------------
    def get_excursion(self, excursion_id, headers):
        return self._request(
            "GET", f"{PREFIX}/excursions/{excursion_id}", headers=headers,
        )

    def acknowledge_excursion(self, excursion_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/excursions/{excursion_id}/acknowledge",
            payload or {}, headers,
        )

    def document_excursion_disposition(self, excursion_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/excursions/{excursion_id}/document-disposition",
            payload, headers,
        )

    def close_excursion(self, excursion_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/excursions/{excursion_id}/close", payload or {}, headers,
        )

    # ------------------------------------------------------------------
    # Lighting overrides
    # ------------------------------------------------------------------
    def create_lighting_override(self, store_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/lighting-overrides", payload, headers,
        )

    def list_store_lighting_overrides(self, store_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/stores/{store_id}/lighting-overrides",
            headers=headers, params=params,
        )

    def revoke_lighting_override(self, override_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/lighting-overrides/{override_id}/revoke",
            payload or {}, headers,
        )

    # ------------------------------------------------------------------
    # Fault diagnostics and work orders
    # ------------------------------------------------------------------
    def create_fault_diagnostic(self, store_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/fault-diagnostics", payload, headers,
        )

    def get_fault_diagnostic(self, fault_id, headers):
        return self._request(
            "GET", f"{PREFIX}/fault-diagnostics/{fault_id}", headers=headers,
        )

    def list_store_fault_diagnostics(self, store_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/stores/{store_id}/fault-diagnostics",
            headers=headers, params=params,
        )

    def triage_fault(self, fault_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/fault-diagnostics/{fault_id}/triage", payload, headers,
        )

    def list_fault_work_orders(self, fault_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/fault-diagnostics/{fault_id}/work-orders",
            headers=headers, params=params,
        )

    def schedule_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/schedule", payload, headers,
        )

    def complete_work_order(self, work_order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/complete",
            payload or {}, headers,
        )

    # ------------------------------------------------------------------
    # Retrofit projects and benchmarking
    # ------------------------------------------------------------------
    def create_retrofit_project(self, store_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/retrofit-projects", payload, headers,
        )

    def list_store_retrofit_projects(self, store_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/stores/{store_id}/retrofit-projects",
            headers=headers, params=params,
        )

    def approve_retrofit_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/retrofit-projects/{project_id}/approve", payload, headers,
        )

    def submit_retrofit_measurement(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/retrofit-projects/{project_id}/submit-measurement",
            payload, headers,
        )

    def revoke_retrofit_verification(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/retrofit-projects/{project_id}/revoke-verification",
            payload or {}, headers,
        )

    def get_benchmark_report(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/benchmark-report", headers=headers, params=params,
        )


api_client = ApiClient()
