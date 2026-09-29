"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Jurisdictions ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/jurisdictions", headers=headers, params=params)

    # --- Modernization projects ---
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def get_project_posture(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}/posture", headers=headers)

    def patch_project(self, project_id, payload, headers):
        return self._request("PATCH", f"/projects/{project_id}", payload, headers)

    # --- Elevator groups ---
    def create_elevator_group(self, payload, headers):
        return self._request("POST", "/elevator-groups", payload, headers)

    def get_elevator_group(self, group_id, headers):
        return self._request("GET", f"/elevator-groups/{group_id}", headers=headers)

    def list_elevator_groups(self, headers, params=None):
        return self._request("GET", "/elevator-groups", headers=headers, params=params)

    def patch_elevator_group(self, group_id, payload, headers):
        return self._request("PATCH", f"/elevator-groups/{group_id}", payload, headers)

    # --- Elevator cars ---
    def create_elevator_car(self, payload, headers):
        return self._request("POST", "/elevator-cars", payload, headers)

    def get_elevator_car(self, car_id, headers):
        return self._request("GET", f"/elevator-cars/{car_id}", headers=headers)

    def list_elevator_cars(self, headers, params=None):
        return self._request("GET", "/elevator-cars", headers=headers, params=params)

    def begin_testing_elevator_car(self, car_id, headers, payload=None):
        return self._request(
            "POST", f"/elevator-cars/{car_id}/begin-testing", payload, headers
        )

    # --- Equipment surveys ---
    def create_equipment_survey(self, payload, headers):
        return self._request("POST", "/equipment-surveys", payload, headers)

    def get_equipment_survey(self, survey_id, headers):
        return self._request("GET", f"/equipment-surveys/{survey_id}", headers=headers)

    def list_equipment_surveys(self, headers, params=None):
        return self._request("GET", "/equipment-surveys", headers=headers, params=params)

    def get_survey_score_preview(self, survey_id, headers, params=None):
        return self._request(
            "GET", f"/equipment-surveys/{survey_id}/score-preview",
            headers=headers, params=params,
        )

    def countersign_equipment_survey(self, survey_id, headers, payload=None):
        return self._request(
            "POST", f"/equipment-surveys/{survey_id}/countersign", payload, headers
        )

    # --- Scope options ---
    def create_scope_option(self, payload, headers):
        return self._request("POST", "/scope-options", payload, headers)

    def get_scope_option(self, scope_option_id, headers):
        return self._request("GET", f"/scope-options/{scope_option_id}", headers=headers)

    def list_scope_options(self, headers, params=None):
        return self._request("GET", "/scope-options", headers=headers, params=params)

    def submit_scope_option(self, scope_option_id, headers, payload=None):
        return self._request(
            "POST", f"/scope-options/{scope_option_id}/submit", payload, headers
        )

    def approve_scope_option(self, scope_option_id, headers, payload=None):
        return self._request(
            "POST", f"/scope-options/{scope_option_id}/approve", payload, headers
        )

    def reject_scope_option(self, scope_option_id, headers, payload=None):
        return self._request(
            "POST", f"/scope-options/{scope_option_id}/reject", payload, headers
        )

    def revise_scope_option(self, scope_option_id, headers, payload=None):
        return self._request(
            "POST", f"/scope-options/{scope_option_id}/revise", payload, headers
        )

    def rescind_scope_option(self, scope_option_id, headers, payload=None):
        return self._request(
            "POST", f"/scope-options/{scope_option_id}/rescind", payload, headers
        )

    # --- Code triggers ---
    def get_code_trigger(self, code_trigger_id, headers):
        return self._request("GET", f"/code-triggers/{code_trigger_id}", headers=headers)

    def list_code_triggers(self, headers, params=None):
        return self._request("GET", "/code-triggers", headers=headers, params=params)

    def price_code_trigger(self, code_trigger_id, payload, headers):
        return self._request(
            "POST", f"/code-triggers/{code_trigger_id}/price", payload, headers
        )

    def waive_code_trigger(self, code_trigger_id, payload, headers):
        return self._request(
            "POST", f"/code-triggers/{code_trigger_id}/waive", payload, headers
        )

    # --- Procurement orders ---
    def create_procurement_order(self, payload, headers):
        return self._request("POST", "/procurement-orders", payload, headers)

    def get_procurement_order(self, procurement_order_id, headers):
        return self._request(
            "GET", f"/procurement-orders/{procurement_order_id}", headers=headers
        )

    def list_procurement_orders(self, headers, params=None):
        return self._request("GET", "/procurement-orders", headers=headers, params=params)

    def issue_procurement_order(self, procurement_order_id, headers, payload=None):
        return self._request(
            "POST", f"/procurement-orders/{procurement_order_id}/issue", payload, headers
        )

    def receive_procurement_order(self, procurement_order_id, payload, headers):
        return self._request(
            "POST", f"/procurement-orders/{procurement_order_id}/receive",
            payload, headers,
        )

    def install_procurement_order(self, procurement_order_id, headers, payload=None):
        return self._request(
            "POST", f"/procurement-orders/{procurement_order_id}/install",
            payload, headers,
        )

    def cancel_procurement_order(self, procurement_order_id, headers, payload=None):
        return self._request(
            "POST", f"/procurement-orders/{procurement_order_id}/cancel",
            payload, headers,
        )

    # --- Staging reservations ---
    def create_staging_reservation(self, payload, headers):
        return self._request("POST", "/staging-reservations", payload, headers)

    def get_staging_reservation(self, staging_reservation_id, headers):
        return self._request(
            "GET", f"/staging-reservations/{staging_reservation_id}", headers=headers
        )

    def list_staging_reservations(self, headers, params=None):
        return self._request(
            "GET", "/staging-reservations", headers=headers, params=params
        )

    def release_staging_reservation(self, staging_reservation_id, headers, payload=None):
        return self._request(
            "POST", f"/staging-reservations/{staging_reservation_id}/release",
            payload, headers,
        )

    # --- Outage windows ---
    def create_outage_window(self, payload, headers):
        return self._request("POST", "/outage-windows", payload, headers)

    def get_outage_window(self, outage_window_id, headers):
        return self._request("GET", f"/outage-windows/{outage_window_id}", headers=headers)

    def list_outage_windows(self, headers, params=None):
        return self._request("GET", "/outage-windows", headers=headers, params=params)

    def send_outage_notice(self, outage_window_id, headers, payload=None):
        return self._request(
            "POST", f"/outage-windows/{outage_window_id}/send-notice", payload, headers
        )

    def activate_outage_window(self, outage_window_id, headers, payload=None):
        return self._request(
            "POST", f"/outage-windows/{outage_window_id}/activate", payload, headers
        )

    def complete_outage_window(self, outage_window_id, headers, payload=None):
        return self._request(
            "POST", f"/outage-windows/{outage_window_id}/complete", payload, headers
        )

    def cancel_outage_window(self, outage_window_id, headers, payload=None):
        return self._request(
            "POST", f"/outage-windows/{outage_window_id}/cancel", payload, headers
        )

    # --- Inspection appointments ---
    def create_inspection_appointment(self, payload, headers):
        return self._request("POST", "/inspection-appointments", payload, headers)

    def get_inspection_appointment(self, inspection_appointment_id, headers):
        return self._request(
            "GET", f"/inspection-appointments/{inspection_appointment_id}",
            headers=headers,
        )

    def list_inspection_appointments(self, headers, params=None):
        return self._request(
            "GET", "/inspection-appointments", headers=headers, params=params
        )

    def schedule_inspection_appointment(self, inspection_appointment_id, payload, headers):
        return self._request(
            "POST", f"/inspection-appointments/{inspection_appointment_id}/schedule",
            payload, headers,
        )

    def reschedule_inspection_appointment(
        self, inspection_appointment_id, payload, headers
    ):
        return self._request(
            "POST", f"/inspection-appointments/{inspection_appointment_id}/reschedule",
            payload, headers,
        )

    def record_inspection_result(self, inspection_appointment_id, payload, headers):
        return self._request(
            "POST",
            f"/inspection-appointments/{inspection_appointment_id}/record-result",
            payload, headers,
        )

    # --- Warranty transitions ---
    def create_warranty_transition(self, payload, headers):
        return self._request("POST", "/warranty-transitions", payload, headers)

    def get_warranty_transition(self, warranty_transition_id, headers):
        return self._request(
            "GET", f"/warranty-transitions/{warranty_transition_id}", headers=headers
        )

    def list_warranty_transitions(self, headers, params=None):
        return self._request(
            "GET", "/warranty-transitions", headers=headers, params=params
        )

    def get_warranty_credit_preview(self, warranty_transition_id, headers, params=None):
        return self._request(
            "GET", f"/warranty-transitions/{warranty_transition_id}/credit-preview",
            headers=headers, params=params,
        )

    def enroll_warranty_transition(self, warranty_transition_id, payload, headers):
        return self._request(
            "POST", f"/warranty-transitions/{warranty_transition_id}/enroll",
            payload, headers,
        )

    # --- Maintenance contracts ---
    def create_maintenance_contract(self, payload, headers):
        return self._request("POST", "/maintenance-contracts", payload, headers)

    def get_maintenance_contract(self, maintenance_contract_id, headers):
        return self._request(
            "GET", f"/maintenance-contracts/{maintenance_contract_id}", headers=headers
        )

    def list_maintenance_contracts(self, headers, params=None):
        return self._request(
            "GET", "/maintenance-contracts", headers=headers, params=params
        )

    def activate_maintenance_contract(
        self, maintenance_contract_id, headers, payload=None
    ):
        return self._request(
            "POST", f"/maintenance-contracts/{maintenance_contract_id}/activate",
            payload, headers,
        )

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
