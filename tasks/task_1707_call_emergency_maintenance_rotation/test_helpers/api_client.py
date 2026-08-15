"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Technician ---
    def create_technician(self, payload, headers=None):
        return self._request("POST", "/v1/technicians", payload, headers)

    def get_technician(self, technician_id, headers=None):
        return self._request("GET", f"/v1/technicians/{technician_id}", headers=headers)

    def deactivate_technician(self, technician_id, headers=None):
        return self._request("POST", f"/v1/technicians/{technician_id}/deactivate", headers=headers)

    # --- Unit ---
    def create_unit(self, payload, headers=None):
        return self._request("POST", "/v1/units", payload, headers)

    def get_unit(self, unit_id, headers=None):
        return self._request("GET", f"/v1/units/{unit_id}", headers=headers)

    # --- Vendor ---
    def create_vendor(self, payload, headers=None):
        return self._request("POST", "/v1/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers=None):
        return self._request("GET", f"/v1/vendors/{vendor_id}", headers=headers)

    def suspend_vendor(self, vendor_id, headers=None):
        return self._request("POST", f"/v1/vendors/{vendor_id}/suspend", headers=headers)

    # --- RotationShift ---
    def create_rotation_shift(self, payload, headers=None):
        return self._request("POST", "/v1/rotation-shifts", payload, headers)

    def list_rotation_shifts(self, headers=None, params=None):
        return self._request("GET", "/v1/rotation-shifts", headers=headers, params=params)

    def get_rotation_shift(self, shift_id, headers=None):
        return self._request("GET", f"/v1/rotation-shifts/{shift_id}", headers=headers)

    def start_rotation_shift(self, shift_id, headers=None):
        return self._request("POST", f"/v1/rotation-shifts/{shift_id}/start", headers=headers)

    def complete_rotation_shift(self, shift_id, headers=None):
        return self._request("POST", f"/v1/rotation-shifts/{shift_id}/complete", headers=headers)

    def transfer_rotation_shift(self, shift_id, payload, headers=None):
        return self._request("POST", f"/v1/rotation-shifts/{shift_id}/transfer", payload, headers)

    def cancel_rotation_shift(self, shift_id, headers=None):
        return self._request("POST", f"/v1/rotation-shifts/{shift_id}/cancel", headers=headers)

    # --- CallTicket ---
    def create_call_ticket(self, payload, headers=None):
        return self._request("POST", "/v1/call-tickets", payload, headers)

    def list_call_tickets(self, headers=None, params=None):
        return self._request("GET", "/v1/call-tickets", headers=headers, params=params)

    def get_call_ticket(self, ticket_id, headers=None):
        return self._request("GET", f"/v1/call-tickets/{ticket_id}", headers=headers)

    def triage_call_ticket(self, ticket_id, payload, headers=None):
        return self._request("POST", f"/v1/call-tickets/{ticket_id}/triage", payload, headers)

    def dispatch_call_ticket(self, ticket_id, payload, headers=None):
        return self._request("POST", f"/v1/call-tickets/{ticket_id}/dispatch", payload, headers)

    def arrive_call_ticket(self, ticket_id, headers=None):
        return self._request("POST", f"/v1/call-tickets/{ticket_id}/arrive", headers=headers)

    def escalate_call_ticket(self, ticket_id, headers=None):
        return self._request("POST", f"/v1/call-tickets/{ticket_id}/escalate", headers=headers)

    def mitigate_call_ticket(self, ticket_id, payload, headers=None):
        return self._request("POST", f"/v1/call-tickets/{ticket_id}/mitigate", payload, headers)

    def close_call_ticket(self, ticket_id, headers=None):
        return self._request("POST", f"/v1/call-tickets/{ticket_id}/close", headers=headers)

    # --- VendorAuthorization ---
    def create_vendor_authorization(self, ticket_id, payload, headers=None):
        return self._request(
            "POST", f"/v1/call-tickets/{ticket_id}/vendor-authorizations", payload, headers
        )

    def list_vendor_authorizations(self, headers=None, params=None):
        return self._request("GET", "/v1/vendor-authorizations", headers=headers, params=params)

    def get_vendor_authorization(self, authorization_id, headers=None):
        return self._request(
            "GET", f"/v1/vendor-authorizations/{authorization_id}", headers=headers
        )

    def authorize_vendor_authorization(self, authorization_id, headers=None):
        return self._request(
            "POST", f"/v1/vendor-authorizations/{authorization_id}/authorize", headers=headers
        )

    def reject_vendor_authorization(self, authorization_id, payload=None, headers=None):
        return self._request(
            "POST", f"/v1/vendor-authorizations/{authorization_id}/reject", payload, headers
        )

    def void_vendor_authorization(self, authorization_id, headers=None):
        return self._request(
            "POST", f"/v1/vendor-authorizations/{authorization_id}/void", headers=headers
        )

    def invoice_vendor_authorization(self, authorization_id, payload, headers=None):
        return self._request(
            "POST", f"/v1/vendor-authorizations/{authorization_id}/invoice", payload, headers
        )

    def mark_paid_vendor_authorization(self, authorization_id, headers=None):
        return self._request(
            "POST", f"/v1/vendor-authorizations/{authorization_id}/mark-paid", headers=headers
        )

    # --- WorkOrder ---
    def create_work_order(self, payload, headers=None):
        return self._request("POST", "/v1/work-orders", payload, headers)

    def list_work_orders(self, headers=None, params=None):
        return self._request("GET", "/v1/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers=None):
        return self._request("GET", f"/v1/work-orders/{work_order_id}", headers=headers)

    def assign_work_order(self, work_order_id, payload, headers=None):
        return self._request("POST", f"/v1/work-orders/{work_order_id}/assign", payload, headers)

    def begin_work_order(self, work_order_id, headers=None):
        return self._request("POST", f"/v1/work-orders/{work_order_id}/begin", headers=headers)

    def complete_work_order(self, work_order_id, headers=None):
        return self._request("POST", f"/v1/work-orders/{work_order_id}/complete", headers=headers)

    def verify_work_order(self, work_order_id, headers=None):
        return self._request("POST", f"/v1/work-orders/{work_order_id}/verify", headers=headers)

    def reopen_work_order(self, work_order_id, payload=None, headers=None):
        return self._request("POST", f"/v1/work-orders/{work_order_id}/reopen", payload, headers)

    def cancel_work_order(self, work_order_id, headers=None):
        return self._request("POST", f"/v1/work-orders/{work_order_id}/cancel", headers=headers)

    # --- RelocationCase ---
    def create_relocation_case(self, payload, headers=None):
        return self._request("POST", "/v1/relocation-cases", payload, headers)

    def list_relocation_cases(self, headers=None, params=None):
        return self._request("GET", "/v1/relocation-cases", headers=headers, params=params)

    def get_relocation_case(self, case_id, headers=None):
        return self._request("GET", f"/v1/relocation-cases/{case_id}", headers=headers)

    def approve_relocation_case(self, case_id, headers=None):
        return self._request("POST", f"/v1/relocation-cases/{case_id}/approve", headers=headers)

    def reject_relocation_case(self, case_id, payload, headers=None):
        return self._request("POST", f"/v1/relocation-cases/{case_id}/reject", payload, headers)

    def resubmit_relocation_case(self, case_id, payload, headers=None):
        return self._request("POST", f"/v1/relocation-cases/{case_id}/resubmit", payload, headers)

    def activate_relocation_case(self, case_id, headers=None):
        return self._request("POST", f"/v1/relocation-cases/{case_id}/activate", headers=headers)

    def end_relocation_case(self, case_id, payload, headers=None):
        return self._request("POST", f"/v1/relocation-cases/{case_id}/end", payload, headers)

    # --- IncidentRecord ---
    def create_incident_record(self, ticket_id, payload, headers=None):
        return self._request(
            "POST", f"/v1/call-tickets/{ticket_id}/incident-record", payload, headers
        )

    def list_incident_records(self, headers=None, params=None):
        return self._request("GET", "/v1/incident-records", headers=headers, params=params)

    def get_incident_record(self, record_id, headers=None):
        return self._request("GET", f"/v1/incident-records/{record_id}", headers=headers)

    def submit_incident_record(self, record_id, headers=None):
        return self._request("POST", f"/v1/incident-records/{record_id}/submit", headers=headers)

    def begin_review_incident_record(self, record_id, headers=None):
        return self._request(
            "POST", f"/v1/incident-records/{record_id}/begin-review", headers=headers
        )

    def return_incident_record(self, record_id, payload, headers=None):
        return self._request("POST", f"/v1/incident-records/{record_id}/return", payload, headers)

    def revise_incident_record(self, record_id, payload, headers=None):
        return self._request("POST", f"/v1/incident-records/{record_id}/revise", payload, headers)

    def notify_insurance_incident_record(self, record_id, payload, headers=None):
        return self._request(
            "POST", f"/v1/incident-records/{record_id}/notify-insurance", payload, headers
        )

    def finalize_incident_record(self, record_id, payload=None, headers=None):
        return self._request(
            "POST", f"/v1/incident-records/{record_id}/finalize", payload, headers
        )

    # --- PayPeriod / PayStatement ---
    def create_pay_period(self, payload, headers=None):
        return self._request("POST", "/v1/pay-periods", payload, headers)

    def get_pay_period(self, pay_period_id, headers=None):
        return self._request("GET", f"/v1/pay-periods/{pay_period_id}", headers=headers)

    def close_pay_period(self, pay_period_id, headers=None):
        return self._request("POST", f"/v1/pay-periods/{pay_period_id}/close", headers=headers)

    def list_pay_statements(self, headers=None, params=None):
        return self._request("GET", "/v1/pay-statements", headers=headers, params=params)

    def get_pay_statement(self, pay_statement_id, headers=None):
        return self._request("GET", f"/v1/pay-statements/{pay_statement_id}", headers=headers)

    # --- Ops / clock utilities ---
    def set_clock(self, to_iso8601, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def evaluate_escalations(self, headers=None):
        return self._request("POST", "/_ops/evaluate-escalations", headers=headers)


api_client = ApiClient()
