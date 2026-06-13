"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Service addresses ---
    def create_service_address(self, payload, headers):
        return self._request("POST", "/service-addresses", payload, headers)

    def get_service_address(self, address_id, headers):
        return self._request("GET", f"/service-addresses/{address_id}", headers=headers)

    def get_serviceability(self, address_id, headers):
        return self._request("GET", f"/service-addresses/{address_id}/serviceability",
                             headers=headers)

    # --- Service plans ---
    def create_service_plan(self, payload, headers):
        return self._request("POST", "/service-plans", payload, headers)

    def get_service_plan(self, plan_id, headers):
        return self._request("GET", f"/service-plans/{plan_id}", headers=headers)

    # --- Technicians ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    # --- Equipment units ---
    def create_equipment_unit(self, payload, headers):
        return self._request("POST", "/equipment-units", payload, headers)

    def get_equipment_unit(self, unit_id, headers):
        return self._request("GET", f"/equipment-units/{unit_id}", headers=headers)

    def list_equipment_units(self, headers, params=None):
        return self._request("GET", "/equipment-units", headers=headers, params=params)

    def confirm_return_equipment(self, unit_id, headers):
        return self._request("POST", f"/equipment-units/{unit_id}/confirm-return",
                             {}, headers)

    def restock_equipment(self, unit_id, headers):
        return self._request("POST", f"/equipment-units/{unit_id}/restock", {}, headers)

    def mark_lost_equipment(self, unit_id, headers):
        return self._request("POST", f"/equipment-units/{unit_id}/mark-lost", {}, headers)

    # --- Accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def change_plan(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/change-plan", payload, headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/suspend", {}, headers)

    def resume_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/resume", {}, headers)

    def restore_speed(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/restore-speed", {}, headers)

    def disconnect_account(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/disconnect", payload, headers)

    def issue_goodwill_credit(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/credits", payload, headers)

    # --- Service orders ---
    def create_service_order(self, payload, headers):
        return self._request("POST", "/service-orders", payload, headers)

    def get_service_order(self, order_id, headers):
        return self._request("GET", f"/service-orders/{order_id}", headers=headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", "/service-orders", headers=headers, params=params)

    def ship_kit(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/ship-kit", {}, headers)

    def activate_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/activate", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/cancel", {}, headers)

    # --- Install slots ---
    def create_install_slot(self, payload, headers):
        return self._request("POST", "/install-slots", payload, headers)

    def get_install_slot(self, slot_id, headers):
        return self._request("GET", f"/install-slots/{slot_id}", headers=headers)

    def list_install_slots(self, headers, params=None):
        return self._request("GET", "/install-slots", headers=headers, params=params)

    # --- Install appointments ---
    def create_install_appointment(self, payload, headers):
        return self._request("POST", "/install-appointments", payload, headers)

    def get_install_appointment(self, appointment_id, headers):
        return self._request("GET", f"/install-appointments/{appointment_id}", headers=headers)

    def list_install_appointments(self, headers, params=None):
        return self._request("GET", "/install-appointments", headers=headers, params=params)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/install-appointments/{appointment_id}/complete",
                             {}, headers)

    def no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/install-appointments/{appointment_id}/no-show",
                             {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/install-appointments/{appointment_id}/cancel",
                             {}, headers)

    # --- Billing cycles ---
    def create_billing_cycle(self, payload, headers):
        return self._request("POST", "/billing-cycles", payload, headers)

    def get_billing_cycle(self, cycle_id, headers):
        return self._request("GET", f"/billing-cycles/{cycle_id}", headers=headers)

    def list_billing_cycles(self, headers, params=None):
        return self._request("GET", "/billing-cycles", headers=headers, params=params)

    def overage_estimate(self, cycle_id, headers, params=None):
        return self._request("GET", f"/billing-cycles/{cycle_id}/overage-estimate",
                             headers=headers, params=params)

    def close_cycle(self, cycle_id, headers):
        return self._request("POST", f"/billing-cycles/{cycle_id}/close", {}, headers)

    def finalize_cycle(self, cycle_id, headers):
        return self._request("POST", f"/billing-cycles/{cycle_id}/finalize", {}, headers)

    # --- Usage records ---
    def create_usage_record(self, payload, headers):
        return self._request("POST", "/usage-records", payload, headers)

    def get_usage_record(self, record_id, headers):
        return self._request("GET", f"/usage-records/{record_id}", headers=headers)

    def list_usage_records(self, headers, params=None):
        return self._request("GET", "/usage-records", headers=headers, params=params)

    # --- Outage events ---
    def create_outage_event(self, payload, headers):
        return self._request("POST", "/outage-events", payload, headers)

    def get_outage_event(self, outage_id, headers):
        return self._request("GET", f"/outage-events/{outage_id}", headers=headers)

    def list_outage_events(self, headers, params=None):
        return self._request("GET", "/outage-events", headers=headers, params=params)

    def resolve_outage(self, outage_id, payload, headers):
        return self._request("POST", f"/outage-events/{outage_id}/resolve", payload, headers)

    def issue_outage_credit(self, outage_id, headers):
        return self._request("POST", f"/outage-events/{outage_id}/issue-credit", {}, headers)

    def dismiss_outage(self, outage_id, headers):
        return self._request("POST", f"/outage-events/{outage_id}/dismiss", {}, headers)

    # --- Account credits ---
    def get_account_credit(self, credit_id, headers):
        return self._request("GET", f"/account-credits/{credit_id}", headers=headers)

    def list_account_credits(self, headers, params=None):
        return self._request("GET", "/account-credits", headers=headers, params=params)

    # --- Transfer requests ---
    def create_transfer_request(self, payload, headers):
        return self._request("POST", "/transfer-requests", payload, headers)

    def get_transfer_request(self, transfer_id, headers):
        return self._request("GET", f"/transfer-requests/{transfer_id}", headers=headers)

    def list_transfer_requests(self, headers, params=None):
        return self._request("GET", "/transfer-requests", headers=headers, params=params)

    def approve_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfer-requests/{transfer_id}/approve", {}, headers)

    def complete_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/transfer-requests/{transfer_id}/complete",
                             payload, headers)

    def reject_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfer-requests/{transfer_id}/reject", {}, headers)


api_client = ApiClient()
