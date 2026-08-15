"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/coop/_clock/set_current_utc", payload, headers)

    # --- Cooperative ---
    def create_cooperative(self, payload, headers):
        return self._request("POST", "/coop/cooperatives", payload, headers)

    def get_cooperative(self, coop_id, headers):
        return self._request("GET", f"/coop/cooperatives/{coop_id}", headers=headers)

    def list_cooperatives(self, headers, params=None):
        return self._request("GET", "/coop/cooperatives", headers=headers, params=params)

    def post_margin(self, coop_id, payload, headers):
        return self._request("POST", f"/coop/cooperatives/{coop_id}/post-margin", payload, headers)

    # --- Member ---
    def create_member(self, payload, headers):
        return self._request("POST", "/coop/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/coop/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/coop/members", headers=headers, params=params)

    def activate_member(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/activate", {}, headers)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/suspend", {}, headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/reinstate", {}, headers)

    def terminate_member(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/terminate", {}, headers)

    def list_member_service_locations(self, member_id, headers):
        return self._request("GET", f"/coop/members/{member_id}/service-locations", headers=headers)

    def list_member_payouts(self, member_id, headers):
        return self._request("GET", f"/coop/members/{member_id}/capital-credit-payouts", headers=headers)

    # --- ServiceLocation ---
    def create_service_location(self, payload, headers):
        return self._request("POST", "/coop/service-locations", payload, headers)

    def get_service_location(self, loc_id, headers):
        return self._request("GET", f"/coop/service-locations/{loc_id}", headers=headers)

    def energize_location(self, loc_id, headers):
        return self._request("POST", f"/coop/service-locations/{loc_id}/energize", {}, headers)

    def disconnect_location(self, loc_id, headers):
        return self._request("POST", f"/coop/service-locations/{loc_id}/disconnect", {}, headers)

    def remove_location(self, loc_id, headers):
        return self._request("POST", f"/coop/service-locations/{loc_id}/remove", {}, headers)

    # --- RateSchedule ---
    def create_rate_schedule(self, payload, headers):
        return self._request("POST", "/coop/rate-schedules", payload, headers)

    def get_rate_schedule(self, rs_id, headers):
        return self._request("GET", f"/coop/rate-schedules/{rs_id}", headers=headers)

    def publish_rate_schedule(self, rs_id, headers):
        return self._request("POST", f"/coop/rate-schedules/{rs_id}/publish", {}, headers)

    def supersede_rate_schedule(self, rs_id, payload, headers):
        return self._request("POST", f"/coop/rate-schedules/{rs_id}/supersede", payload, headers)

    # --- MeterReading ---
    def create_meter_reading(self, payload, headers):
        return self._request("POST", "/coop/meter-readings", payload, headers)

    def get_meter_reading(self, mr_id, headers):
        return self._request("GET", f"/coop/meter-readings/{mr_id}", headers=headers)

    def list_meter_readings(self, headers, params=None):
        return self._request("GET", "/coop/meter-readings", headers=headers, params=params)

    # --- Invoice ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/coop/invoices", payload, headers)

    def get_invoice(self, inv_id, headers):
        return self._request("GET", f"/coop/invoices/{inv_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/coop/invoices", headers=headers, params=params)

    def finalize_invoice(self, inv_id, headers):
        return self._request("POST", f"/coop/invoices/{inv_id}/finalize", {}, headers)

    def pay_invoice(self, inv_id, headers):
        return self._request("POST", f"/coop/invoices/{inv_id}/pay", {}, headers)

    def write_off_invoice(self, inv_id, headers):
        return self._request("POST", f"/coop/invoices/{inv_id}/write-off", {}, headers)

    def void_invoice(self, inv_id, headers):
        return self._request("POST", f"/coop/invoices/{inv_id}/void", {}, headers)

    # --- CapitalCreditAllocation ---
    def create_allocation(self, payload, headers):
        return self._request("POST", "/coop/capital-credit-allocations", payload, headers)

    def get_allocation(self, alloc_id, headers):
        return self._request("GET", f"/coop/capital-credit-allocations/{alloc_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/coop/capital-credit-allocations", headers=headers, params=params)

    def list_allocation_lines(self, alloc_id, headers):
        return self._request("GET", f"/coop/capital-credit-allocations/{alloc_id}/lines", headers=headers)

    def get_allocation_line(self, line_id, headers):
        return self._request("GET", f"/coop/capital-credit-allocation-lines/{line_id}", headers=headers)

    def list_allocation_lines_index(self, headers, params=None):
        return self._request("GET", "/coop/capital-credit-allocation-lines", headers=headers, params=params)

    def approve_allocation(self, alloc_id, headers):
        return self._request("POST", f"/coop/capital-credit-allocations/{alloc_id}/approve", {}, headers)

    def post_allocation(self, alloc_id, payload, headers):
        return self._request("POST", f"/coop/capital-credit-allocations/{alloc_id}/post", payload, headers)

    def void_allocation(self, alloc_id, headers):
        return self._request("POST", f"/coop/capital-credit-allocations/{alloc_id}/void", {}, headers)

    # --- CapitalCreditRetirement ---
    def create_retirement(self, payload, headers):
        return self._request("POST", "/coop/capital-credit-retirements", payload, headers)

    def get_retirement(self, ret_id, headers):
        return self._request("GET", f"/coop/capital-credit-retirements/{ret_id}", headers=headers)

    def list_retirements(self, headers, params=None):
        return self._request("GET", "/coop/capital-credit-retirements", headers=headers, params=params)

    def board_approve_retirement(self, ret_id, headers):
        return self._request("POST", f"/coop/capital-credit-retirements/{ret_id}/board-approve", {}, headers)

    def execute_retirement(self, ret_id, payload, headers):
        return self._request("POST", f"/coop/capital-credit-retirements/{ret_id}/execute", payload, headers)

    def abort_retirement(self, ret_id, headers):
        return self._request("POST", f"/coop/capital-credit-retirements/{ret_id}/abort", {}, headers)

    def list_retirement_payouts(self, ret_id, headers):
        return self._request("GET", f"/coop/capital-credit-retirements/{ret_id}/payouts", headers=headers)

    # --- CapitalCreditPayout ---
    def cash_payout(self, payout_id, headers):
        return self._request("POST", f"/coop/capital-credit-payouts/{payout_id}/cash", {}, headers)

    def mark_payout_unclaimed(self, payout_id, headers):
        return self._request("POST", f"/coop/capital-credit-payouts/{payout_id}/mark-unclaimed", {}, headers)

    # --- OutageReport ---
    def create_outage_report(self, payload, headers):
        return self._request("POST", "/coop/outage-reports", payload, headers)

    def get_outage_report(self, out_id, headers):
        return self._request("GET", f"/coop/outage-reports/{out_id}", headers=headers)

    def list_outage_reports(self, headers, params=None):
        return self._request("GET", "/coop/outage-reports", headers=headers, params=params)

    def acknowledge_outage(self, out_id, headers):
        return self._request("POST", f"/coop/outage-reports/{out_id}/acknowledge", {}, headers)

    def dispatch_outage(self, out_id, headers):
        return self._request("POST", f"/coop/outage-reports/{out_id}/dispatch", {}, headers)

    def restore_outage(self, out_id, headers):
        return self._request("POST", f"/coop/outage-reports/{out_id}/restore", {}, headers)

    def mark_outage_duplicate(self, out_id, payload, headers):
        return self._request("POST", f"/coop/outage-reports/{out_id}/mark-duplicate", payload, headers)

    def cancel_outage(self, out_id, headers):
        return self._request("POST", f"/coop/outage-reports/{out_id}/cancel", {}, headers)

    # --- RightOfWayAgreement ---
    def create_row_agreement(self, payload, headers):
        return self._request("POST", "/coop/right-of-way-agreements", payload, headers)

    def get_row_agreement(self, row_id, headers):
        return self._request("GET", f"/coop/right-of-way-agreements/{row_id}", headers=headers)

    def list_row_agreements(self, headers, params=None):
        return self._request("GET", "/coop/right-of-way-agreements", headers=headers, params=params)

    def consent_row(self, row_id, headers):
        return self._request("POST", f"/coop/right-of-way-agreements/{row_id}/consent", {}, headers)

    def record_row(self, row_id, headers):
        return self._request("POST", f"/coop/right-of-way-agreements/{row_id}/record", {}, headers)

    def contest_row(self, row_id, headers):
        return self._request("POST", f"/coop/right-of-way-agreements/{row_id}/contest", {}, headers)

    def condemn_row(self, row_id, headers):
        return self._request("POST", f"/coop/right-of-way-agreements/{row_id}/condemn", {}, headers)

    def release_row(self, row_id, headers):
        return self._request("POST", f"/coop/right-of-way-agreements/{row_id}/release", {}, headers)

    # --- LoadManagementDevice ---
    def enroll_device(self, payload, headers):
        return self._request("POST", "/coop/load-management-devices", payload, headers)

    def get_device(self, dev_id, headers):
        return self._request("GET", f"/coop/load-management-devices/{dev_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/coop/load-management-devices", headers=headers, params=params)

    def activate_device(self, dev_id, headers):
        return self._request("POST", f"/coop/load-management-devices/{dev_id}/activate", {}, headers)

    def suspend_device(self, dev_id, headers):
        return self._request("POST", f"/coop/load-management-devices/{dev_id}/suspend", {}, headers)

    def reactivate_device(self, dev_id, headers):
        return self._request("POST", f"/coop/load-management-devices/{dev_id}/reactivate", {}, headers)

    def unenroll_device(self, dev_id, headers):
        return self._request("POST", f"/coop/load-management-devices/{dev_id}/unenroll", {}, headers)

    # --- ServiceOrder ---
    def create_service_order(self, payload, headers):
        return self._request("POST", "/coop/service-orders", payload, headers)

    def get_service_order(self, so_id, headers):
        return self._request("GET", f"/coop/service-orders/{so_id}", headers=headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", "/coop/service-orders", headers=headers, params=params)

    def estimate_service_order(self, so_id, headers):
        return self._request("POST", f"/coop/service-orders/{so_id}/estimate", {}, headers)

    def invoice_atc(self, so_id, headers):
        return self._request("POST", f"/coop/service-orders/{so_id}/invoice-atc", {}, headers)

    def mark_order_paid(self, so_id, headers):
        return self._request("POST", f"/coop/service-orders/{so_id}/mark-paid", {}, headers)

    def schedule_service_order(self, so_id, headers):
        return self._request("POST", f"/coop/service-orders/{so_id}/schedule", {}, headers)

    def construct_service_order(self, so_id, headers):
        return self._request("POST", f"/coop/service-orders/{so_id}/construct", {}, headers)

    def cancel_service_order(self, so_id, headers):
        return self._request("POST", f"/coop/service-orders/{so_id}/cancel", {}, headers)

    # --- BoardElection ---
    def create_election(self, payload, headers):
        return self._request("POST", "/coop/board-elections", payload, headers)

    def get_election(self, el_id, headers):
        return self._request("GET", f"/coop/board-elections/{el_id}", headers=headers)

    def list_elections(self, headers, params=None):
        return self._request("GET", "/coop/board-elections", headers=headers, params=params)

    def open_nominations(self, el_id, headers):
        return self._request("POST", f"/coop/board-elections/{el_id}/open-nominations", {}, headers)

    def close_nominations(self, el_id, payload, headers):
        return self._request("POST", f"/coop/board-elections/{el_id}/close-nominations", payload, headers)

    def open_voting(self, el_id, payload, headers):
        return self._request("POST", f"/coop/board-elections/{el_id}/open-voting", payload, headers)

    def close_voting(self, el_id, headers):
        return self._request("POST", f"/coop/board-elections/{el_id}/close-voting", {}, headers)

    def certify_election(self, el_id, headers):
        return self._request("POST", f"/coop/board-elections/{el_id}/certify", {}, headers)

    def void_election(self, el_id, headers):
        return self._request("POST", f"/coop/board-elections/{el_id}/void", {}, headers)

    # --- Ballot ---
    def cast_ballot(self, payload, headers):
        return self._request("POST", "/coop/ballots", payload, headers)

    def get_ballot(self, ballot_id, headers):
        return self._request("GET", f"/coop/ballots/{ballot_id}", headers=headers)

    def list_ballots(self, headers, params=None):
        return self._request("GET", "/coop/ballots", headers=headers, params=params)


api_client = ApiClient()
