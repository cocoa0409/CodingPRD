"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Branch ---
    def create_branch(self, payload, headers):
        return self._request("POST", "/vault/branches", payload, headers)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/vault/branches/{branch_id}", headers=headers)

    def list_branches(self, headers, params=None):
        return self._request("GET", "/vault/branches", headers=headers, params=params)

    # --- BoxType ---
    def create_box_type(self, payload, headers):
        return self._request("POST", "/vault/box-types", payload, headers)

    def get_box_type(self, box_type_id, headers):
        return self._request("GET", f"/vault/box-types/{box_type_id}", headers=headers)

    def list_box_types(self, headers, params=None):
        return self._request("GET", "/vault/box-types", headers=headers, params=params)

    # --- Box ---
    def create_box(self, payload, headers):
        return self._request("POST", "/vault/boxes", payload, headers)

    def get_box(self, box_id, headers):
        return self._request("GET", f"/vault/boxes/{box_id}", headers=headers)

    def list_boxes(self, headers, params=None):
        return self._request("GET", "/vault/boxes", headers=headers, params=params)

    def decommission_box(self, box_id, headers):
        return self._request("POST", f"/vault/boxes/{box_id}/decommission", headers=headers)

    def return_box_to_service(self, box_id, headers):
        return self._request("POST", f"/vault/boxes/{box_id}/return-to-service", headers=headers)

    # --- Renter ---
    def create_renter(self, payload, headers):
        return self._request("POST", "/vault/renters", payload, headers)

    def get_renter(self, renter_id, headers):
        return self._request("GET", f"/vault/renters/{renter_id}", headers=headers)

    def list_renters(self, headers, params=None):
        return self._request("GET", "/vault/renters", headers=headers, params=params)

    def verify_kyc(self, renter_id, payload, headers):
        return self._request("POST", f"/vault/renters/{renter_id}/verify-kyc", payload, headers)

    # --- Rental ---
    def create_rental(self, payload, headers):
        return self._request("POST", "/vault/rentals", payload, headers)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/vault/rentals/{rental_id}", headers=headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/vault/rentals", headers=headers, params=params)

    def activate_rental(self, rental_id, headers):
        return self._request("POST", f"/vault/rentals/{rental_id}/activate", headers=headers)

    def adjust_plan(self, rental_id, payload, headers):
        return self._request("POST", f"/vault/rentals/{rental_id}/adjust-plan", payload, headers)

    def request_surrender(self, rental_id, headers):
        return self._request("POST", f"/vault/rentals/{rental_id}/request-surrender", headers=headers)

    def close_rental(self, rental_id, headers):
        return self._request("POST", f"/vault/rentals/{rental_id}/close", headers=headers)

    # --- Invoice ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/vault/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/vault/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/vault/invoices", headers=headers, params=params)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/vault/invoices/{invoice_id}/void", headers=headers)

    def write_off_invoice(self, invoice_id, headers):
        return self._request("POST", f"/vault/invoices/{invoice_id}/write-off", headers=headers)

    # --- Payment ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/vault/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/vault/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/vault/payments", headers=headers, params=params)

    def clear_payment(self, payment_id, headers):
        return self._request("POST", f"/vault/payments/{payment_id}/clear", headers=headers)

    def fail_payment(self, payment_id, headers):
        return self._request("POST", f"/vault/payments/{payment_id}/fail", headers=headers)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/vault/payments/{payment_id}/reverse", headers=headers)

    # --- AccessGrant ---
    def create_access_grant(self, payload, headers):
        return self._request("POST", "/vault/access-grants", payload, headers)

    def get_access_grant(self, grant_id, headers):
        return self._request("GET", f"/vault/access-grants/{grant_id}", headers=headers)

    def list_access_grants(self, headers, params=None):
        return self._request("GET", "/vault/access-grants", headers=headers, params=params)

    def activate_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/vault/access-grants/{grant_id}/activate", payload, headers)

    def suspend_grant(self, grant_id, headers):
        return self._request("POST", f"/vault/access-grants/{grant_id}/suspend", headers=headers)

    def resume_grant(self, grant_id, headers):
        return self._request("POST", f"/vault/access-grants/{grant_id}/resume", headers=headers)

    def revoke_grant(self, grant_id, headers):
        return self._request("POST", f"/vault/access-grants/{grant_id}/revoke", headers=headers)

    # --- AccessAppointment ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/vault/access-appointments", payload, headers)

    def get_appointment(self, appt_id, headers):
        return self._request("GET", f"/vault/access-appointments/{appt_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/vault/access-appointments", headers=headers, params=params)

    def check_in_appointment(self, appt_id, headers):
        return self._request("POST", f"/vault/access-appointments/{appt_id}/check-in", headers=headers)

    def complete_appointment(self, appt_id, headers):
        return self._request("POST", f"/vault/access-appointments/{appt_id}/complete", headers=headers)

    def cancel_appointment(self, appt_id, headers):
        return self._request("POST", f"/vault/access-appointments/{appt_id}/cancel", headers=headers)

    def no_show_appointment(self, appt_id, headers):
        return self._request("POST", f"/vault/access-appointments/{appt_id}/no-show", headers=headers)

    # --- AccessEvent ---
    def create_access_event(self, payload, headers):
        return self._request("POST", "/vault/access-events", payload, headers)

    def get_access_event(self, event_id, headers):
        return self._request("GET", f"/vault/access-events/{event_id}", headers=headers)

    def list_access_events(self, headers, params=None):
        return self._request("GET", "/vault/access-events", headers=headers, params=params)

    # --- InventoryItem ---
    def create_inventory_item(self, payload, headers):
        return self._request("POST", "/vault/inventory-items", payload, headers)

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"/vault/inventory-items/{item_id}", headers=headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", "/vault/inventory-items", headers=headers, params=params)

    def appraise_item(self, item_id, payload, headers):
        return self._request("POST", f"/vault/inventory-items/{item_id}/appraise", payload, headers)

    def insure_item(self, item_id, headers):
        return self._request("POST", f"/vault/inventory-items/{item_id}/insure", headers=headers)

    # --- DrillingOrder ---
    def create_drilling_order(self, payload, headers):
        return self._request("POST", "/vault/drilling-orders", payload, headers)

    def get_drilling_order(self, order_id, headers):
        return self._request("GET", f"/vault/drilling-orders/{order_id}", headers=headers)

    def list_drilling_orders(self, headers, params=None):
        return self._request("GET", "/vault/drilling-orders", headers=headers, params=params)

    def approve_drilling_order(self, order_id, headers):
        return self._request("POST", f"/vault/drilling-orders/{order_id}/approve", headers=headers)

    def schedule_drilling_order(self, order_id, payload, headers):
        return self._request("POST", f"/vault/drilling-orders/{order_id}/schedule", payload, headers)

    def complete_drilling_order(self, order_id, payload, headers):
        return self._request("POST", f"/vault/drilling-orders/{order_id}/complete", payload, headers)

    def cancel_drilling_order(self, order_id, headers):
        return self._request("POST", f"/vault/drilling-orders/{order_id}/cancel", headers=headers)

    # --- ComplianceCase ---
    def create_compliance_case(self, payload, headers):
        return self._request("POST", "/vault/compliance-cases", payload, headers)

    def get_compliance_case(self, case_id, headers):
        return self._request("GET", f"/vault/compliance-cases/{case_id}", headers=headers)

    def list_compliance_cases(self, headers, params=None):
        return self._request("GET", "/vault/compliance-cases", headers=headers, params=params)

    def escalate_compliance_case(self, case_id, headers):
        return self._request("POST", f"/vault/compliance-cases/{case_id}/escalate", headers=headers)

    def clear_compliance_case(self, case_id, headers):
        return self._request("POST", f"/vault/compliance-cases/{case_id}/clear", headers=headers)

    # --- System / ops ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/vault/_clock/set_current_utc", payload, headers)

    def run_billing_cycle(self, headers):
        return self._request("POST", "/vault/_billing/run_cycle", headers=headers)


api_client = ApiClient()
