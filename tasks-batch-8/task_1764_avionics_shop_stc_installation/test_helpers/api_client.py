"""API client: one method per endpoint defined in the PRD (§4 endpoint map)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/avionics/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/avionics/customers/{customer_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Aircraft
    # ------------------------------------------------------------------
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/avionics/aircraft", payload, headers)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/avionics/aircraft/{aircraft_id}",
                             headers=headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/avionics/aircraft", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Work orders
    # ------------------------------------------------------------------
    def create_work_order(self, payload, headers):
        return self._request("POST", "/avionics/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/avionics/work-orders/{work_order_id}",
                             headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/avionics/work-orders", headers=headers,
                             params=params)

    def submit_quote(self, work_order_id, headers):
        return self._request("POST",
                             f"/avionics/work-orders/{work_order_id}/submit-quote",
                             {}, headers)

    def begin_installation(self, work_order_id, headers):
        return self._request(
            "POST", f"/avionics/work-orders/{work_order_id}/begin-installation",
            {}, headers)

    def begin_testing(self, work_order_id, headers):
        return self._request("POST",
                             f"/avionics/work-orders/{work_order_id}/begin-testing",
                             {}, headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST",
                             f"/avionics/work-orders/{work_order_id}/complete",
                             {}, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST",
                             f"/avionics/work-orders/{work_order_id}/cancel",
                             {}, headers)

    def acknowledge_overage(self, work_order_id, headers):
        return self._request(
            "POST", f"/avionics/work-orders/{work_order_id}/acknowledge-overage",
            {}, headers)

    # ------------------------------------------------------------------
    # Panel designs
    # ------------------------------------------------------------------
    def create_panel_design(self, payload, headers):
        return self._request("POST", "/avionics/panel-designs", payload, headers)

    def get_panel_design(self, panel_design_id, headers):
        return self._request("GET", f"/avionics/panel-designs/{panel_design_id}",
                             headers=headers)

    def list_panel_designs(self, headers, params=None):
        return self._request("GET", "/avionics/panel-designs", headers=headers,
                             params=params)

    def submit_panel_design(self, panel_design_id, headers):
        return self._request("POST",
                             f"/avionics/panel-designs/{panel_design_id}/submit",
                             {}, headers)

    def decide_panel_design(self, panel_design_id, outcome, headers):
        return self._request("POST",
                             f"/avionics/panel-designs/{panel_design_id}/decide",
                             {"outcome": outcome}, headers)

    # ------------------------------------------------------------------
    # Equipment orders
    # ------------------------------------------------------------------
    def create_equipment_order(self, payload, headers):
        return self._request("POST", "/avionics/equipment-orders", payload,
                             headers)

    def get_equipment_order(self, equipment_order_id, headers):
        return self._request("GET",
                             f"/avionics/equipment-orders/{equipment_order_id}",
                             headers=headers)

    def list_equipment_orders(self, headers, params=None):
        return self._request("GET", "/avionics/equipment-orders",
                             headers=headers, params=params)

    def mark_ordered(self, equipment_order_id, headers):
        return self._request(
            "POST",
            f"/avionics/equipment-orders/{equipment_order_id}/mark-ordered",
            {}, headers)

    def receive_equipment_order(self, equipment_order_id, headers):
        return self._request(
            "POST", f"/avionics/equipment-orders/{equipment_order_id}/receive",
            {}, headers)

    def cancel_equipment_order(self, equipment_order_id, headers):
        return self._request(
            "POST", f"/avionics/equipment-orders/{equipment_order_id}/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Install tasks
    # ------------------------------------------------------------------
    def create_install_task(self, payload, headers):
        return self._request("POST", "/avionics/install-tasks", payload, headers)

    def get_install_task(self, install_task_id, headers):
        return self._request("GET", f"/avionics/install-tasks/{install_task_id}",
                             headers=headers)

    def list_install_tasks(self, headers, params=None):
        return self._request("GET", "/avionics/install-tasks", headers=headers,
                             params=params)

    def start_task(self, install_task_id, headers):
        return self._request("POST",
                             f"/avionics/install-tasks/{install_task_id}/start",
                             {}, headers)

    def complete_task(self, install_task_id, actual_hours, headers):
        return self._request(
            "POST", f"/avionics/install-tasks/{install_task_id}/complete",
            {"actual_hours": actual_hours}, headers)

    def verify_task(self, install_task_id, headers):
        return self._request("POST",
                             f"/avionics/install-tasks/{install_task_id}/verify",
                             {}, headers)

    def void_task(self, install_task_id, headers):
        return self._request("POST",
                             f"/avionics/install-tasks/{install_task_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Test events
    # ------------------------------------------------------------------
    def create_test_event(self, payload, headers):
        return self._request("POST", "/avionics/test-events", payload, headers)

    def get_test_event(self, test_event_id, headers):
        return self._request("GET", f"/avionics/test-events/{test_event_id}",
                             headers=headers)

    def list_test_events(self, headers, params=None):
        return self._request("GET", "/avionics/test-events", headers=headers,
                             params=params)

    def record_result(self, test_event_id, result, headers):
        return self._request(
            "POST", f"/avionics/test-events/{test_event_id}/record-result",
            {"result": result}, headers)

    def reschedule_test_event(self, test_event_id, scheduled_start,
                              scheduled_end, headers):
        return self._request(
            "POST", f"/avionics/test-events/{test_event_id}/reschedule",
            {"scheduled_start": scheduled_start,
             "scheduled_end": scheduled_end}, headers)

    # ------------------------------------------------------------------
    # Regulatory packages
    # ------------------------------------------------------------------
    def create_regulatory_package(self, payload, headers):
        return self._request("POST", "/avionics/regulatory-packages", payload,
                             headers)

    def get_regulatory_package(self, regulatory_package_id, headers):
        return self._request(
            "GET", f"/avionics/regulatory-packages/{regulatory_package_id}",
            headers=headers)

    def list_regulatory_packages(self, headers, params=None):
        return self._request("GET", "/avionics/regulatory-packages",
                             headers=headers, params=params)

    def submit_regulatory_package(self, regulatory_package_id, headers):
        return self._request(
            "POST",
            f"/avionics/regulatory-packages/{regulatory_package_id}/submit",
            {}, headers)

    def record_decision(self, regulatory_package_id, decision, headers):
        return self._request(
            "POST",
            f"/avionics/regulatory-packages/{regulatory_package_id}/record-decision",
            {"decision": decision}, headers)

    # ------------------------------------------------------------------
    # Weight & balance revisions
    # ------------------------------------------------------------------
    def create_weight_balance_revision(self, payload, headers):
        return self._request("POST", "/avionics/weight-balance-revisions",
                             payload, headers)

    def get_weight_balance_revision(self, revision_id, headers):
        return self._request(
            "GET", f"/avionics/weight-balance-revisions/{revision_id}",
            headers=headers)

    def list_weight_balance_revisions(self, headers, params=None):
        return self._request("GET", "/avionics/weight-balance-revisions",
                             headers=headers, params=params)

    def accept_weight_balance_revision(self, revision_id, headers):
        return self._request(
            "POST",
            f"/avionics/weight-balance-revisions/{revision_id}/accept",
            {}, headers)


api_client = ApiClient()
