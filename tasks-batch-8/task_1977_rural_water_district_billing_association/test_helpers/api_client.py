"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Districts ---
    def create_district(self, payload, headers):
        return self._request("POST", "/districts", payload, headers)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/districts/{district_id}", headers=headers)

    def list_districts(self, headers, params=None):
        return self._request("GET", "/districts", headers=headers, params=params)

    # --- Service areas ---
    def create_service_area(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/service-areas", payload, headers)

    def list_service_areas(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/service-areas", headers=headers, params=params)

    def get_service_area(self, district_id, area_id, headers):
        return self._request("GET", f"/districts/{district_id}/service-areas/{area_id}", headers=headers)

    def retire_service_area(self, district_id, area_id, headers):
        return self._request("POST", f"/districts/{district_id}/service-areas/{area_id}/retire", {}, headers)

    # --- Members ---
    def create_member(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/members", payload, headers)

    def list_members(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/members", headers=headers, params=params)

    def get_member(self, district_id, member_id, headers):
        return self._request("GET", f"/districts/{district_id}/members/{member_id}", headers=headers)

    def approve_member(self, district_id, member_id, headers):
        return self._request("POST", f"/districts/{district_id}/members/{member_id}/approve", {}, headers)

    def terminate_member(self, district_id, member_id, headers):
        return self._request("POST", f"/districts/{district_id}/members/{member_id}/terminate", {}, headers)

    # --- Taps ---
    def create_tap(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/taps", payload, headers)

    def list_taps(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/taps", headers=headers, params=params)

    def get_tap(self, district_id, tap_id, headers):
        return self._request("GET", f"/districts/{district_id}/taps/{tap_id}", headers=headers)

    def pay_tap_fee(self, district_id, tap_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/taps/{tap_id}/pay-tap-fee", payload, headers)

    def install_meter(self, district_id, tap_id, headers):
        return self._request("POST", f"/districts/{district_id}/taps/{tap_id}/install-meter", {}, headers)

    def disconnect_tap(self, district_id, tap_id, headers):
        return self._request("POST", f"/districts/{district_id}/taps/{tap_id}/disconnect", {}, headers)

    def reconnect_tap(self, district_id, tap_id, headers):
        return self._request("POST", f"/districts/{district_id}/taps/{tap_id}/reconnect", {}, headers)

    def abandon_tap(self, district_id, tap_id, headers):
        return self._request("POST", f"/districts/{district_id}/taps/{tap_id}/abandon", {}, headers)

    # --- Rate schedules ---
    def create_rate_schedule(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/rate-schedules", payload, headers)

    def list_rate_schedules(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/rate-schedules", headers=headers, params=params)

    def get_rate_schedule(self, district_id, schedule_id, headers):
        return self._request("GET", f"/districts/{district_id}/rate-schedules/{schedule_id}", headers=headers)

    # --- Billing cycles ---
    def create_billing_cycle(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/billing-cycles", payload, headers)

    def list_billing_cycles(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/billing-cycles", headers=headers, params=params)

    def get_billing_cycle(self, district_id, cycle_id, headers):
        return self._request("GET", f"/districts/{district_id}/billing-cycles/{cycle_id}", headers=headers)

    def mark_readings_complete(self, district_id, cycle_id, headers):
        return self._request("POST", f"/districts/{district_id}/billing-cycles/{cycle_id}/mark-readings-complete", {}, headers)

    def bill_cycle(self, district_id, cycle_id, headers):
        return self._request("POST", f"/districts/{district_id}/billing-cycles/{cycle_id}/bill", {}, headers)

    def close_cycle(self, district_id, cycle_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/billing-cycles/{cycle_id}/close", payload, headers)

    # --- Meter readings ---
    def create_meter_reading(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/meter-readings", payload, headers)

    def list_meter_readings(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/meter-readings", headers=headers, params=params)

    # --- Master meter readings ---
    def create_master_meter_reading(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/master-meter-readings", payload, headers)

    def list_master_meter_readings(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/master-meter-readings", headers=headers, params=params)

    # --- Invoices ---
    def list_invoices(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/invoices", headers=headers, params=params)

    def get_invoice(self, district_id, invoice_id, headers):
        return self._request("GET", f"/districts/{district_id}/invoices/{invoice_id}", headers=headers)

    def issue_notice(self, district_id, invoice_id, headers):
        return self._request("POST", f"/districts/{district_id}/invoices/{invoice_id}/issue-notice", {}, headers)

    # --- Payments ---
    def create_payment(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/payments", payload, headers)

    def list_payments(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/payments", headers=headers, params=params)

    def reverse_payment(self, district_id, payment_id, headers):
        return self._request("POST", f"/districts/{district_id}/payments/{payment_id}/reverse", {}, headers)

    # --- Reserve entries ---
    def list_reserve_entries(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/reserve-entries", headers=headers, params=params)

    # --- Board resolutions ---
    def create_board_resolution(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/board-resolutions", payload, headers)

    def list_board_resolutions(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/board-resolutions", headers=headers, params=params)

    def record_vote(self, district_id, resolution_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/board-resolutions/{resolution_id}/record-vote", payload, headers)

    # --- Annexation petitions ---
    def create_annexation_petition(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/annexation-petitions", payload, headers)

    def list_annexation_petitions(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/annexation-petitions", headers=headers, params=params)

    def begin_petition_review(self, district_id, petition_id, headers):
        return self._request("POST", f"/districts/{district_id}/annexation-petitions/{petition_id}/begin-review", {}, headers)

    def recommend_petition(self, district_id, petition_id, headers):
        return self._request("POST", f"/districts/{district_id}/annexation-petitions/{petition_id}/recommend", {}, headers)

    def withdraw_petition(self, district_id, petition_id, headers):
        return self._request("POST", f"/districts/{district_id}/annexation-petitions/{petition_id}/withdraw", {}, headers)

    def resubmit_petition(self, district_id, petition_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/annexation-petitions/{petition_id}/resubmit", payload, headers)

    # --- Boil orders ---
    def create_boil_order(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/boil-orders", payload, headers)

    def list_boil_orders(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/boil-orders", headers=headers, params=params)

    def create_notification(self, district_id, order_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/boil-orders/{order_id}/notifications", payload, headers)

    def list_notifications(self, district_id, order_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/boil-orders/{order_id}/notifications", headers=headers, params=params)

    def begin_sampling(self, district_id, order_id, headers):
        return self._request("POST", f"/districts/{district_id}/boil-orders/{order_id}/begin-sampling", {}, headers)

    # --- Compliance samples ---
    def create_compliance_sample(self, district_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/compliance-samples", payload, headers)

    def list_compliance_samples(self, district_id, headers, params=None):
        return self._request("GET", f"/districts/{district_id}/compliance-samples", headers=headers, params=params)

    def record_sample_result(self, district_id, sample_id, payload, headers):
        return self._request("POST", f"/districts/{district_id}/compliance-samples/{sample_id}/record-result", payload, headers)

    # --- Reverse-reachability reads ---
    def get_rate_schedule_by_id(self, schedule_id, headers):
        return self._request("GET", f"/rate-schedules/{schedule_id}", headers=headers)

    def get_service_area_by_id(self, area_id, headers):
        return self._request("GET", f"/service-areas/{area_id}", headers=headers)

    def get_member_by_id(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def get_tap_by_id(self, tap_id, headers):
        return self._request("GET", f"/taps/{tap_id}", headers=headers)

    def get_billing_cycle_by_id(self, cycle_id, headers):
        return self._request("GET", f"/billing-cycles/{cycle_id}", headers=headers)

    def get_invoice_by_id(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def get_boil_order_by_id(self, order_id, headers):
        return self._request("GET", f"/boil-orders/{order_id}", headers=headers)

    def list_area_members(self, area_id, headers, params=None):
        return self._request("GET", f"/service-areas/{area_id}/members", headers=headers, params=params)

    def list_area_petitions(self, area_id, headers, params=None):
        return self._request("GET", f"/service-areas/{area_id}/annexation-petitions", headers=headers, params=params)

    def list_member_taps(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/taps", headers=headers, params=params)

    def list_member_invoices(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/invoices", headers=headers, params=params)

    def list_member_payments(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/payments", headers=headers, params=params)

    def list_member_notifications(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/notifications", headers=headers, params=params)

    def list_tap_meter_readings(self, tap_id, headers, params=None):
        return self._request("GET", f"/taps/{tap_id}/meter-readings", headers=headers, params=params)

    def list_tap_invoices(self, tap_id, headers, params=None):
        return self._request("GET", f"/taps/{tap_id}/invoices", headers=headers, params=params)

    def list_cycle_meter_readings(self, cycle_id, headers, params=None):
        return self._request("GET", f"/billing-cycles/{cycle_id}/meter-readings", headers=headers, params=params)

    def list_cycle_master_readings(self, cycle_id, headers, params=None):
        return self._request("GET", f"/billing-cycles/{cycle_id}/master-meter-readings", headers=headers, params=params)

    def list_cycle_invoices(self, cycle_id, headers, params=None):
        return self._request("GET", f"/billing-cycles/{cycle_id}/invoices", headers=headers, params=params)

    def list_cycle_reserve_entries(self, cycle_id, headers, params=None):
        return self._request("GET", f"/billing-cycles/{cycle_id}/reserve-entries", headers=headers, params=params)

    def list_invoice_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/payments", headers=headers, params=params)

    def list_order_notifications(self, order_id, headers, params=None):
        return self._request("GET", f"/boil-orders/{order_id}/notifications", headers=headers, params=params)

    def list_order_samples(self, order_id, headers, params=None):
        return self._request("GET", f"/boil-orders/{order_id}/compliance-samples", headers=headers, params=params)

    def list_schedule_invoices(self, schedule_id, headers, params=None):
        return self._request("GET", f"/rate-schedules/{schedule_id}/invoices", headers=headers, params=params)


api_client = ApiClient()
