"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() handles the HTTP envelope.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Intersection ---
    def create_intersection(self, payload, headers):
        return self._request("POST", "/intersections", payload, headers)

    def get_intersection(self, intersection_id, headers):
        return self._request("GET", f"/intersections/{intersection_id}", headers=headers)

    def get_intersection_summary(self, intersection_id, headers):
        return self._request("GET", f"/intersections/{intersection_id}/summary", headers=headers)

    # --- Pole ---
    def create_pole(self, payload, headers):
        return self._request("POST", "/poles", payload, headers)

    def get_pole(self, pole_id, headers):
        return self._request("GET", f"/poles/{pole_id}", headers=headers)

    def list_poles(self, headers, params=None):
        return self._request("GET", "/poles", headers=headers, params=params)

    # --- Device ---
    def create_device(self, payload, headers):
        return self._request("POST", "/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/devices", headers=headers, params=params)

    def decommission_device(self, device_id, headers):
        return self._request("POST", f"/devices/{device_id}/decommission", {}, headers)

    # --- Crew ---
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    # --- PoleAttachment ---
    def create_pole_attachment(self, payload, headers):
        return self._request("POST", "/pole-attachments", payload, headers)

    def get_pole_attachment(self, attachment_id, headers):
        return self._request("GET", f"/pole-attachments/{attachment_id}", headers=headers)

    def list_pole_attachments(self, headers, params=None):
        return self._request("GET", "/pole-attachments", headers=headers, params=params)

    def approve_pole_attachment(self, attachment_id, headers):
        return self._request("POST", f"/pole-attachments/{attachment_id}/approve", {}, headers)

    def deny_pole_attachment(self, attachment_id, headers):
        return self._request("POST", f"/pole-attachments/{attachment_id}/deny", {}, headers)

    def revoke_pole_attachment(self, attachment_id, headers):
        return self._request("POST", f"/pole-attachments/{attachment_id}/revoke", {}, headers)

    # --- Ticket ---
    def create_ticket(self, payload, headers):
        return self._request("POST", "/tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def triage_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/triage", {}, headers)

    def resolve_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/resolve", {}, headers)

    def reopen_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/reopen", {}, headers)

    def close_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/close", {}, headers)

    # --- WorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def schedule_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/schedule", payload, headers)

    def dispatch_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/dispatch", {}, headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", payload, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", {}, headers)

    # --- TimingPlanChangeRequest ---
    def create_timing_change_request(self, payload, headers):
        return self._request("POST", "/timing-change-requests", payload, headers)

    def get_timing_change_request(self, tcr_id, headers):
        return self._request("GET", f"/timing-change-requests/{tcr_id}", headers=headers)

    def list_timing_change_requests(self, headers, params=None):
        return self._request("GET", "/timing-change-requests", headers=headers, params=params)

    def start_review_timing_change_request(self, tcr_id, headers):
        return self._request("POST", f"/timing-change-requests/{tcr_id}/start-review", {}, headers)

    def approve_timing_change_request(self, tcr_id, headers):
        return self._request("POST", f"/timing-change-requests/{tcr_id}/approve", {}, headers)

    def reject_timing_change_request(self, tcr_id, headers):
        return self._request("POST", f"/timing-change-requests/{tcr_id}/reject", {}, headers)

    def request_changes_timing_change_request(self, tcr_id, headers):
        return self._request("POST", f"/timing-change-requests/{tcr_id}/request-changes", {}, headers)

    def resubmit_timing_change_request(self, tcr_id, payload, headers):
        return self._request("POST", f"/timing-change-requests/{tcr_id}/resubmit", payload, headers)

    # --- LocateRequest ---
    def create_locate_request(self, payload, headers):
        return self._request("POST", "/locate-requests", payload, headers)

    def get_locate_request(self, locate_id, headers):
        return self._request("GET", f"/locate-requests/{locate_id}", headers=headers)

    def list_locate_requests(self, headers, params=None):
        return self._request("GET", "/locate-requests", headers=headers, params=params)

    def mark_locate_request(self, locate_id, headers):
        return self._request("POST", f"/locate-requests/{locate_id}/mark", {}, headers)

    def clear_locate_request(self, locate_id, headers):
        return self._request("POST", f"/locate-requests/{locate_id}/clear", {}, headers)

    # --- WarrantyClaim ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def approve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/approve", {}, headers)

    def deny_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/deny", {}, headers)

    # --- Reporting ---
    def get_device_availability_report(self, headers, params=None):
        return self._request("GET", "/reports/device-availability", headers=headers, params=params)


api_client = ApiClient()
