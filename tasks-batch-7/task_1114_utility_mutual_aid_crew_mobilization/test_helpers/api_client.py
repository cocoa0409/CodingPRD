"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/mutual-aid/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- UtilityCompany ---
    def create_utility_company(self, payload, headers):
        return self._request("POST", "/mutual-aid/utility-companies", payload, headers)

    def get_utility_company(self, company_id, headers):
        return self._request("GET", f"/mutual-aid/utility-companies/{company_id}", headers=headers)

    # --- MutualAidEvent ---
    def create_event(self, payload, headers):
        return self._request("POST", "/mutual-aid/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/mutual-aid/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/mutual-aid/events", headers=headers, params=params)

    def activate_event(self, event_id, headers):
        return self._request("POST", f"/mutual-aid/events/{event_id}/activate", {}, headers)

    def begin_demobilization(self, event_id, headers):
        return self._request("POST", f"/mutual-aid/events/{event_id}/begin_demobilization", {}, headers)

    def close_event(self, event_id, headers):
        return self._request("POST", f"/mutual-aid/events/{event_id}/close", {}, headers)

    # --- BillingRateSchedule ---
    def create_billing_rate_schedule(self, payload, headers):
        return self._request("POST", "/mutual-aid/billing-rate-schedules", payload, headers)

    def get_billing_rate_schedule(self, schedule_id, headers):
        return self._request("GET", f"/mutual-aid/billing-rate-schedules/{schedule_id}", headers=headers)

    def list_billing_rate_schedules(self, headers, params=None):
        return self._request("GET", "/mutual-aid/billing-rate-schedules", headers=headers, params=params)

    def publish_billing_rate_schedule(self, schedule_id, payload, headers):
        return self._request(
            "POST", f"/mutual-aid/billing-rate-schedules/{schedule_id}/publish",
            payload or {}, headers,
        )

    def lock_billing_rate_schedule(self, schedule_id, headers):
        return self._request("POST", f"/mutual-aid/billing-rate-schedules/{schedule_id}/lock", {}, headers)

    # --- AssistanceRequest ---
    def create_assistance_request(self, payload, headers):
        return self._request("POST", "/mutual-aid/assistance-requests", payload, headers)

    def get_assistance_request(self, request_id, headers):
        return self._request("GET", f"/mutual-aid/assistance-requests/{request_id}", headers=headers)

    def list_assistance_requests(self, headers, params=None):
        return self._request("GET", "/mutual-aid/assistance-requests", headers=headers, params=params)

    def submit_assistance_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/mutual-aid/assistance-requests/{request_id}/submit",
            payload or {}, headers,
        )

    def counter_assistance_request(self, request_id, payload, headers):
        return self._request("POST", f"/mutual-aid/assistance-requests/{request_id}/counter", payload, headers)

    def accept_assistance_request(self, request_id, headers):
        return self._request("POST", f"/mutual-aid/assistance-requests/{request_id}/accept", {}, headers)

    def decline_assistance_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/mutual-aid/assistance-requests/{request_id}/decline",
            payload or {}, headers,
        )

    def cancel_assistance_request(self, request_id, headers):
        return self._request("POST", f"/mutual-aid/assistance-requests/{request_id}/cancel", {}, headers)

    # --- Crew ---
    def create_crew(self, payload, headers):
        return self._request("POST", "/mutual-aid/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/mutual-aid/crews/{crew_id}", headers=headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/mutual-aid/crews", headers=headers, params=params)

    def confirm_arrival(self, crew_id, headers):
        return self._request("POST", f"/mutual-aid/crews/{crew_id}/confirm_arrival", {}, headers)

    def release_crew(self, crew_id, headers):
        return self._request("POST", f"/mutual-aid/crews/{crew_id}/release", {}, headers)

    def complete_return(self, crew_id, headers):
        return self._request("POST", f"/mutual-aid/crews/{crew_id}/complete_return", {}, headers)

    def withdraw_crew(self, crew_id, headers):
        return self._request("POST", f"/mutual-aid/crews/{crew_id}/withdraw", {}, headers)

    def suspend_crew(self, crew_id, payload, headers):
        return self._request("POST", f"/mutual-aid/crews/{crew_id}/suspend", payload or {}, headers)

    # --- SafetyBriefing ---
    def create_safety_briefing(self, payload, headers):
        return self._request("POST", "/mutual-aid/safety-briefings", payload, headers)

    def get_safety_briefing(self, briefing_id, headers):
        return self._request("GET", f"/mutual-aid/safety-briefings/{briefing_id}", headers=headers)

    def list_safety_briefings(self, headers, params=None):
        return self._request("GET", "/mutual-aid/safety-briefings", headers=headers, params=params)

    def acknowledge_safety_briefing(self, briefing_id, payload, headers):
        return self._request(
            "POST", f"/mutual-aid/safety-briefings/{briefing_id}/acknowledge",
            payload, headers,
        )

    # --- TimeSheet ---
    def create_timesheet(self, payload, headers):
        return self._request("POST", "/mutual-aid/timesheets", payload, headers)

    def get_timesheet(self, timesheet_id, headers):
        return self._request("GET", f"/mutual-aid/timesheets/{timesheet_id}", headers=headers)

    def list_timesheets(self, headers, params=None):
        return self._request("GET", "/mutual-aid/timesheets", headers=headers, params=params)

    def submit_timesheet(self, timesheet_id, payload, headers):
        return self._request("POST", f"/mutual-aid/timesheets/{timesheet_id}/submit", payload, headers)

    def certify_timesheet(self, timesheet_id, payload, headers):
        return self._request("POST", f"/mutual-aid/timesheets/{timesheet_id}/certify", payload, headers)

    def recertify_timesheet(self, timesheet_id, payload, headers):
        return self._request("POST", f"/mutual-aid/timesheets/{timesheet_id}/recertify", payload, headers)

    def reject_timesheet(self, timesheet_id, payload, headers):
        return self._request(
            "POST", f"/mutual-aid/timesheets/{timesheet_id}/reject",
            payload or {}, headers,
        )

    def revise_timesheet(self, timesheet_id, payload, headers):
        return self._request(
            "POST", f"/mutual-aid/timesheets/{timesheet_id}/revise",
            payload or {}, headers,
        )

    # --- LodgingBlock ---
    def create_lodging_block(self, payload, headers):
        return self._request("POST", "/mutual-aid/lodging-blocks", payload, headers)

    def get_lodging_block(self, block_id, headers):
        return self._request("GET", f"/mutual-aid/lodging-blocks/{block_id}", headers=headers)

    def list_lodging_blocks(self, headers, params=None):
        return self._request("GET", "/mutual-aid/lodging-blocks", headers=headers, params=params)

    # --- LodgingAssignment ---
    def create_lodging_assignment(self, payload, headers):
        return self._request("POST", "/mutual-aid/lodging-assignments", payload, headers)

    def get_lodging_assignment(self, assignment_id, headers):
        return self._request("GET", f"/mutual-aid/lodging-assignments/{assignment_id}", headers=headers)

    def list_lodging_assignments(self, headers, params=None):
        return self._request("GET", "/mutual-aid/lodging-assignments", headers=headers, params=params)

    def cancel_lodging_assignment(self, assignment_id, headers):
        return self._request("POST", f"/mutual-aid/lodging-assignments/{assignment_id}/cancel", {}, headers)

    # --- PerDiemClaim ---
    def create_per_diem_claim(self, payload, headers):
        return self._request("POST", "/mutual-aid/per-diem-claims", payload, headers)

    def get_per_diem_claim(self, claim_id, headers):
        return self._request("GET", f"/mutual-aid/per-diem-claims/{claim_id}", headers=headers)

    def list_per_diem_claims(self, headers, params=None):
        return self._request("GET", "/mutual-aid/per-diem-claims", headers=headers, params=params)

    def approve_per_diem_claim(self, claim_id, headers):
        return self._request("POST", f"/mutual-aid/per-diem-claims/{claim_id}/approve", {}, headers)

    def reject_per_diem_claim(self, claim_id, headers):
        return self._request("POST", f"/mutual-aid/per-diem-claims/{claim_id}/reject", {}, headers)

    # --- Invoice ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/mutual-aid/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/mutual-aid/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/mutual-aid/invoices", headers=headers, params=params)

    def submit_invoice(self, invoice_id, headers):
        return self._request("POST", f"/mutual-aid/invoices/{invoice_id}/submit", {}, headers)

    def approve_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/mutual-aid/invoices/{invoice_id}/approve", payload, headers)

    def mark_invoice_paid(self, invoice_id, payload, headers):
        return self._request("POST", f"/mutual-aid/invoices/{invoice_id}/mark_paid", payload, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/mutual-aid/invoices/{invoice_id}/void", {}, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/mutual-aid/invoices/{invoice_id}/dispute", payload, headers)

    def propose_credit(self, invoice_id, payload, headers):
        return self._request("POST", f"/mutual-aid/invoices/{invoice_id}/propose_credit", payload, headers)

    def accept_credit(self, invoice_id, headers):
        return self._request("POST", f"/mutual-aid/invoices/{invoice_id}/accept_credit", {}, headers)

    def reject_credit(self, invoice_id, headers):
        return self._request("POST", f"/mutual-aid/invoices/{invoice_id}/reject_credit", {}, headers)

    def arbitrate_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/mutual-aid/invoices/{invoice_id}/arbitrate", payload, headers)

    # --- AfterActionReport ---
    def create_after_action_report(self, payload, headers):
        return self._request("POST", "/mutual-aid/after-action-reports", payload, headers)

    def get_after_action_report(self, report_id, headers):
        return self._request("GET", f"/mutual-aid/after-action-reports/{report_id}", headers=headers)

    def list_after_action_reports(self, headers, params=None):
        return self._request("GET", "/mutual-aid/after-action-reports", headers=headers, params=params)

    def submit_after_action_report(self, report_id, headers):
        return self._request("POST", f"/mutual-aid/after-action-reports/{report_id}/submit", {}, headers)

    def accept_after_action_report(self, report_id, headers):
        return self._request("POST", f"/mutual-aid/after-action-reports/{report_id}/accept", {}, headers)


api_client = ApiClient()
