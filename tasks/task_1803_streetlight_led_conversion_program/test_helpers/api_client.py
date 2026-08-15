"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- programs ----
    def create_program(self, payload, headers):
        return self._request("POST", "/streetlights/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/streetlights/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/streetlights/programs/{program_id}", headers=headers)

    def get_program_summary(self, program_id, headers):
        return self._request("GET", f"/streetlights/programs/{program_id}/summary", headers=headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/streetlights/programs/{program_id}/activate", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/streetlights/programs/{program_id}/close", {}, headers)

    # ---- districts ----
    def create_district(self, payload, headers):
        return self._request("POST", "/streetlights/districts", payload, headers)

    def list_districts(self, headers, params=None):
        return self._request("GET", "/streetlights/districts", headers=headers, params=params)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/streetlights/districts/{district_id}", headers=headers)

    # ---- poles ----
    def create_pole(self, payload, headers):
        return self._request("POST", "/streetlights/poles", payload, headers)

    def list_poles(self, headers, params=None):
        return self._request("GET", "/streetlights/poles", headers=headers, params=params)

    def get_pole(self, pole_id, headers):
        return self._request("GET", f"/streetlights/poles/{pole_id}", headers=headers)

    def attest_nameplate(self, pole_id, headers):
        return self._request("POST", f"/streetlights/poles/{pole_id}/attest-nameplate", {}, headers)

    # ---- wattage audits ----
    def submit_audit(self, pole_id, payload, headers):
        return self._request("POST", f"/streetlights/poles/{pole_id}/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/streetlights/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/streetlights/audits/{audit_id}", headers=headers)

    def accept_audit(self, audit_id, headers):
        return self._request("POST", f"/streetlights/audits/{audit_id}/accept", {}, headers)

    def dispute_audit(self, audit_id, headers):
        return self._request("POST", f"/streetlights/audits/{audit_id}/dispute", {}, headers)

    def resubmit_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/streetlights/audits/{audit_id}/resubmit", payload, headers)

    # ---- crews ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/streetlights/crews", payload, headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/streetlights/crews", headers=headers, params=params)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/streetlights/crews/{crew_id}", headers=headers)

    # ---- conversion routes & stops ----
    def create_route(self, payload, headers):
        return self._request("POST", "/streetlights/conversion-routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/streetlights/conversion-routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/streetlights/conversion-routes/{route_id}", headers=headers)

    def add_stop(self, route_id, payload, headers):
        return self._request("POST", f"/streetlights/conversion-routes/{route_id}/stops", payload, headers)

    def list_stops(self, headers, params=None):
        return self._request("GET", "/streetlights/route-stops", headers=headers, params=params)

    def get_stop(self, stop_id, headers):
        return self._request("GET", f"/streetlights/route-stops/{stop_id}", headers=headers)

    def skip_stop(self, stop_id, headers):
        return self._request("POST", f"/streetlights/route-stops/{stop_id}/skip", {}, headers)

    def release_route(self, route_id, headers):
        return self._request("POST", f"/streetlights/conversion-routes/{route_id}/release", {}, headers)

    def suspend_route(self, route_id, headers):
        return self._request("POST", f"/streetlights/conversion-routes/{route_id}/suspend", {}, headers)

    def resume_route(self, route_id, headers):
        return self._request("POST", f"/streetlights/conversion-routes/{route_id}/resume", {}, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/streetlights/conversion-routes/{route_id}/cancel", {}, headers)

    # ---- work orders ----
    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/streetlights/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/streetlights/work-orders/{work_order_id}", headers=headers)

    def dispatch_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/streetlights/work-orders/{work_order_id}/dispatch", payload, headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/streetlights/work-orders/{work_order_id}/complete", {}, headers)

    def fail_work_order(self, work_order_id, headers):
        return self._request("POST", f"/streetlights/work-orders/{work_order_id}/fail", {}, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/streetlights/work-orders/{work_order_id}/cancel", {}, headers)

    def qc_pass_work_order(self, work_order_id, headers):
        return self._request("POST", f"/streetlights/work-orders/{work_order_id}/qc-pass", {}, headers)

    def qc_fail_work_order(self, work_order_id, headers):
        return self._request("POST", f"/streetlights/work-orders/{work_order_id}/qc-fail", {}, headers)

    # ---- rate schedules ----
    def create_rate_schedule(self, payload, headers):
        return self._request("POST", "/streetlights/rate-schedules", payload, headers)

    def list_rate_schedules(self, headers, params=None):
        return self._request("GET", "/streetlights/rate-schedules", headers=headers, params=params)

    def get_rate_schedule(self, schedule_id, headers):
        return self._request("GET", f"/streetlights/rate-schedules/{schedule_id}", headers=headers)

    def file_rate_schedule(self, schedule_id, headers):
        return self._request("POST", f"/streetlights/rate-schedules/{schedule_id}/file", {}, headers)

    def activate_rate_schedule(self, schedule_id, headers):
        return self._request("POST", f"/streetlights/rate-schedules/{schedule_id}/activate", {}, headers)

    def retire_rate_schedule(self, schedule_id, payload, headers):
        return self._request("POST", f"/streetlights/rate-schedules/{schedule_id}/retire", payload, headers)

    # ---- tariff accounts & billing lines ----
    def create_tariff_account(self, payload, headers):
        return self._request("POST", "/streetlights/tariff-accounts", payload, headers)

    def list_tariff_accounts(self, headers, params=None):
        return self._request("GET", "/streetlights/tariff-accounts", headers=headers, params=params)

    def get_tariff_account(self, account_id, headers):
        return self._request("GET", f"/streetlights/tariff-accounts/{account_id}", headers=headers)

    def freeze_tariff_account(self, account_id, headers):
        return self._request("POST", f"/streetlights/tariff-accounts/{account_id}/freeze", {}, headers)

    def unfreeze_tariff_account(self, account_id, headers):
        return self._request("POST", f"/streetlights/tariff-accounts/{account_id}/unfreeze", {}, headers)

    def generate_lines(self, account_id, headers):
        return self._request("POST", f"/streetlights/tariff-accounts/{account_id}/generate-lines", {}, headers)

    def close_period(self, account_id, headers):
        return self._request("POST", f"/streetlights/tariff-accounts/{account_id}/close-period", {}, headers)

    def list_billing_lines(self, headers, params=None):
        return self._request("GET", "/streetlights/billing-lines", headers=headers, params=params)

    def get_billing_line(self, line_id, headers):
        return self._request("GET", f"/streetlights/billing-lines/{line_id}", headers=headers)

    # ---- outage tickets ----
    def create_outage_ticket(self, payload, headers):
        return self._request("POST", "/streetlights/outage-tickets", payload, headers)

    def list_outage_tickets(self, headers, params=None):
        return self._request("GET", "/streetlights/outage-tickets", headers=headers, params=params)

    def get_outage_ticket(self, ticket_id, headers):
        return self._request("GET", f"/streetlights/outage-tickets/{ticket_id}", headers=headers)

    def triage_ticket(self, ticket_id, headers):
        return self._request("POST", f"/streetlights/outage-tickets/{ticket_id}/triage", {}, headers)

    def dispatch_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/streetlights/outage-tickets/{ticket_id}/dispatch", payload, headers)

    def resolve_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/streetlights/outage-tickets/{ticket_id}/resolve", payload, headers)

    def verify_ticket(self, ticket_id, headers):
        return self._request("POST", f"/streetlights/outage-tickets/{ticket_id}/verify", {}, headers)

    def reopen_ticket(self, ticket_id, headers):
        return self._request("POST", f"/streetlights/outage-tickets/{ticket_id}/reopen", {}, headers)

    # ---- salvage ----
    def create_salvage_batch(self, payload, headers):
        return self._request("POST", "/streetlights/salvage-batches", payload, headers)

    def list_salvage_batches(self, headers, params=None):
        return self._request("GET", "/streetlights/salvage-batches", headers=headers, params=params)

    def get_salvage_batch(self, batch_id, headers):
        return self._request("GET", f"/streetlights/salvage-batches/{batch_id}", headers=headers)

    def add_salvage_item(self, batch_id, payload, headers):
        return self._request("POST", f"/streetlights/salvage-batches/{batch_id}/items", payload, headers)

    def list_salvage_items(self, headers, params=None):
        return self._request("GET", "/streetlights/salvage-items", headers=headers, params=params)

    def get_salvage_item(self, item_id, headers):
        return self._request("GET", f"/streetlights/salvage-items/{item_id}", headers=headers)

    def seal_salvage_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/streetlights/salvage-batches/{batch_id}/seal", payload, headers)

    def manifest_salvage_batch(self, batch_id, headers):
        return self._request("POST", f"/streetlights/salvage-batches/{batch_id}/manifest", {}, headers)

    def settle_salvage_batch(self, batch_id, headers):
        return self._request("POST", f"/streetlights/salvage-batches/{batch_id}/settle", {}, headers)

    def reject_salvage_batch(self, batch_id, headers):
        return self._request("POST", f"/streetlights/salvage-batches/{batch_id}/reject", {}, headers)

    # ---- savings reports ----
    def create_savings_report(self, payload, headers):
        return self._request("POST", "/streetlights/savings-reports", payload, headers)

    def list_savings_reports(self, headers, params=None):
        return self._request("GET", "/streetlights/savings-reports", headers=headers, params=params)

    def get_savings_report(self, report_id, headers):
        return self._request("GET", f"/streetlights/savings-reports/{report_id}", headers=headers)

    def submit_savings_report(self, report_id, headers):
        return self._request("POST", f"/streetlights/savings-reports/{report_id}/submit", {}, headers)

    def attest_savings_report(self, report_id, headers):
        return self._request("POST", f"/streetlights/savings-reports/{report_id}/attest", {}, headers)

    def reject_savings_report(self, report_id, headers):
        return self._request("POST", f"/streetlights/savings-reports/{report_id}/reject", {}, headers)

    def revise_savings_report(self, report_id, headers):
        return self._request("POST", f"/streetlights/savings-reports/{report_id}/revise", {}, headers)

    # ---- compliance exceptions ----
    def create_compliance_exception(self, payload, headers):
        return self._request("POST", "/streetlights/compliance-exceptions", payload, headers)

    def list_compliance_exceptions(self, headers, params=None):
        return self._request("GET", "/streetlights/compliance-exceptions", headers=headers, params=params)

    def get_compliance_exception(self, exception_id, headers):
        return self._request("GET", f"/streetlights/compliance-exceptions/{exception_id}", headers=headers)

    def approve_compliance_exception(self, exception_id, headers):
        return self._request("POST", f"/streetlights/compliance-exceptions/{exception_id}/approve", {}, headers)

    def deny_compliance_exception(self, exception_id, headers):
        return self._request("POST", f"/streetlights/compliance-exceptions/{exception_id}/deny", {}, headers)

    def refresh_compliance_exception(self, exception_id, headers):
        return self._request("POST", f"/streetlights/compliance-exceptions/{exception_id}/refresh", {}, headers)

    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
