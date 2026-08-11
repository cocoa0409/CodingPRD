"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/sharpening"


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------- configuration ----------------
    def create_plan_tier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/plan-tiers", payload, headers)

    def create_item_class_spec(self, payload, headers):
        return self._request("POST", f"{PREFIX}/item-class-specs", payload, headers)

    def create_technician(self, payload, headers):
        return self._request("POST", f"{PREFIX}/technicians", payload, headers)

    def create_van(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vans", payload, headers)

    def create_bench_day(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bench-days", payload, headers)

    def get_bench_day(self, bench_day_id, headers):
        return self._request("GET", f"{PREFIX}/bench-days/{bench_day_id}", headers=headers)

    def create_locker_compartment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/locker-compartments", payload, headers)

    # ---------------- accounts ----------------
    def create_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}", headers=headers)

    def update_account(self, account_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/accounts/{account_id}", payload, headers)

    def suspend_account(self, account_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/accounts/{account_id}/suspend", payload or {}, headers)

    def reinstate_account(self, account_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/accounts/{account_id}/reinstate", payload or {}, headers)

    def get_account_statement(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}/statement", headers=headers)

    # ---------------- subscriptions ----------------
    def create_subscription(self, payload, headers):
        return self._request("POST", f"{PREFIX}/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"{PREFIX}/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/subscriptions", headers=headers, params=params)

    def pause_subscription(self, subscription_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/subscriptions/{subscription_id}/pause", payload or {}, headers)

    def resume_subscription(self, subscription_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/subscriptions/{subscription_id}/resume", payload or {}, headers)

    def change_subscription_cadence(self, subscription_id, payload, headers):
        return self._request("POST", f"{PREFIX}/subscriptions/{subscription_id}/cadence", payload, headers)

    def skip_subscription(self, subscription_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/subscriptions/{subscription_id}/skip", payload or {}, headers)

    def cancel_subscription(self, subscription_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/subscriptions/{subscription_id}/cancel", payload or {}, headers)

    def advance_subscription_cycle(self, subscription_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/subscriptions/{subscription_id}/advance-cycle", payload or {}, headers)

    # ---------------- allowance ledger ----------------
    def get_allowance_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/allowance-entries/{entry_id}", headers=headers)

    def list_allowance_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/allowance-entries", headers=headers, params=params)

    # ---------------- route runs and stops ----------------
    def create_route_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/route-runs", payload, headers)

    def get_route_run(self, run_id, headers):
        return self._request("GET", f"{PREFIX}/route-runs/{run_id}", headers=headers)

    def list_route_runs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/route-runs", headers=headers, params=params)

    def add_route_stop(self, run_id, payload, headers):
        return self._request("POST", f"{PREFIX}/route-runs/{run_id}/stops", payload, headers)

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"{PREFIX}/route-stops/{stop_id}", headers=headers)

    def list_route_stops(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/route-stops", headers=headers, params=params)

    def delete_route_stop(self, stop_id, headers):
        return self._request("DELETE", f"{PREFIX}/route-stops/{stop_id}", headers=headers)

    def spill_route_stop(self, stop_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/route-stops/{stop_id}/spill", payload or {}, headers)

    def reschedule_route_stop(self, stop_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/route-stops/{stop_id}/reschedule", payload or {}, headers)

    def arrive_route_stop(self, stop_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/route-stops/{stop_id}/arrive", payload or {}, headers)

    def dispatch_route_run(self, run_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/route-runs/{run_id}/dispatch", payload or {}, headers)

    def complete_route_run(self, run_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/route-runs/{run_id}/complete", payload or {}, headers)

    def cancel_route_run(self, run_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/route-runs/{run_id}/cancel", payload or {}, headers)

    # ---------------- service requests and items ----------------
    def create_service_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/service-requests", payload, headers)

    def get_service_request(self, request_id, headers):
        return self._request("GET", f"{PREFIX}/service-requests/{request_id}", headers=headers)

    def list_service_requests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/service-requests", headers=headers, params=params)

    def add_request_item(self, request_id, payload, headers):
        return self._request("POST", f"{PREFIX}/service-requests/{request_id}/items", payload, headers)

    def get_request_item(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/request-items/{item_id}", headers=headers)

    def list_request_items(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/request-items", headers=headers, params=params)

    def submit_service_request(self, request_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/service-requests/{request_id}/submit", payload or {}, headers)

    def cancel_service_request(self, request_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/service-requests/{request_id}/cancel", payload or {}, headers)

    def pickup_service_request(self, request_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/service-requests/{request_id}/pickup", payload or {}, headers)

    def bench_intake_service_request(self, request_id, payload, headers):
        return self._request("POST", f"{PREFIX}/service-requests/{request_id}/bench-intake", payload, headers)

    def deliver_service_request(self, request_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/service-requests/{request_id}/deliver", payload or {}, headers)

    def locker_assign_service_request(self, request_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/service-requests/{request_id}/locker-assign", payload or {}, headers)

    def assess_request_item(self, item_id, payload, headers):
        return self._request("POST", f"{PREFIX}/request-items/{item_id}/assess", payload, headers)

    def authorize_request_item(self, item_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/request-items/{item_id}/authorize", payload or {}, headers)

    def decline_request_item(self, item_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/request-items/{item_id}/decline", payload or {}, headers)

    def start_work_request_item(self, item_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/request-items/{item_id}/start-work", payload or {}, headers)

    def complete_work_request_item(self, item_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/request-items/{item_id}/complete-work", payload or {}, headers)

    # ---------------- locker compartments ----------------
    def get_locker_compartment(self, compartment_id, headers):
        return self._request("GET", f"{PREFIX}/locker-compartments/{compartment_id}", headers=headers)

    def list_locker_compartments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/locker-compartments", headers=headers, params=params)

    def deposit_locker_compartment(self, compartment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/locker-compartments/{compartment_id}/deposit", payload, headers)

    def release_locker_compartment(self, compartment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/locker-compartments/{compartment_id}/release", payload, headers)

    def expire_hold_locker_compartment(self, compartment_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/locker-compartments/{compartment_id}/expire-hold", payload or {}, headers)

    def abandon_locker_compartment(self, compartment_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/locker-compartments/{compartment_id}/abandon", payload or {}, headers)

    # ---------------- loaners ----------------
    def create_loaner_unit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/loaner-units", payload, headers)

    def get_loaner_unit(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/loaner-units/{unit_id}", headers=headers)

    def list_loaner_units(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/loaner-units", headers=headers, params=params)

    def create_loaner_issue(self, payload, headers):
        return self._request("POST", f"{PREFIX}/loaner-issues", payload, headers)

    def get_loaner_issue(self, issue_id, headers):
        return self._request("GET", f"{PREFIX}/loaner-issues/{issue_id}", headers=headers)

    def list_loaner_issues(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/loaner-issues", headers=headers, params=params)

    def return_loaner_issue(self, issue_id, payload, headers):
        return self._request("POST", f"{PREFIX}/loaner-issues/{issue_id}/return", payload, headers)

    # ---------------- warranty ----------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/warranty-claims", headers=headers, params=params)

    def approve_warranty_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/warranty-claims/{claim_id}/approve", payload or {}, headers)

    def deny_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims/{claim_id}/deny", payload, headers)

    def resubmit_warranty_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/warranty-claims/{claim_id}/resubmit", payload or {}, headers)

    # ---------------- billing ----------------
    def create_invoice(self, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices", headers=headers, params=params)

    def list_invoice_lines_of_invoice(self, invoice_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}/lines", headers=headers, params=params)

    def get_invoice_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/invoice-lines/{line_id}", headers=headers)

    def list_invoice_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoice-lines", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/issue", payload or {}, headers)

    def void_invoice(self, invoice_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/void", payload or {}, headers)

    def create_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"{PREFIX}/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/payments", headers=headers, params=params)


api_client = ApiClient()
