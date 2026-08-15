"""API client: one method per endpoint defined in the PRD endpoint table.

All methods return the raw requests.Response so tests can assert status
codes and envelope contents via the framework validators.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD section 2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- FieldTechnician ---
    def create_field_technician(self, payload, headers):
        return self._request("POST", "/field-technicians", payload, headers)

    def list_field_technicians(self, headers, params=None):
        return self._request("GET", "/field-technicians", headers=headers, params=params)

    def get_field_technician(self, technician_id, headers):
        return self._request("GET", f"/field-technicians/{technician_id}", headers=headers)

    def deactivate_field_technician(self, technician_id, headers):
        return self._request("POST", f"/field-technicians/{technician_id}/deactivate", {}, headers)

    # --- ServiceAccount ---
    def create_service_account(self, payload, headers):
        return self._request("POST", "/service-accounts", payload, headers)

    def list_service_accounts(self, headers, params=None):
        return self._request("GET", "/service-accounts", headers=headers, params=params)

    def get_service_account(self, account_id, headers):
        return self._request("GET", f"/service-accounts/{account_id}", headers=headers)

    def suspend_service_account(self, account_id, headers):
        return self._request("POST", f"/service-accounts/{account_id}/suspend", {}, headers)

    def reactivate_service_account(self, account_id, headers):
        return self._request("POST", f"/service-accounts/{account_id}/reactivate", {}, headers)

    def close_service_account(self, account_id, headers):
        return self._request("POST", f"/service-accounts/{account_id}/close", {}, headers)

    # --- Meter ---
    def create_meter(self, payload, headers):
        return self._request("POST", "/meters", payload, headers)

    def list_meters(self, headers, params=None):
        return self._request("GET", "/meters", headers=headers, params=params)

    def get_meter(self, meter_id, headers):
        return self._request("GET", f"/meters/{meter_id}", headers=headers)

    def install_meter(self, meter_id, payload, headers):
        return self._request("POST", f"/meters/{meter_id}/install", payload, headers)

    def retire_meter(self, meter_id, headers):
        return self._request("POST", f"/meters/{meter_id}/retire", {}, headers)

    def ingest_ami_read(self, meter_id, payload, headers):
        return self._request("POST", f"/meters/{meter_id}/ami-reads", payload, headers)

    # --- BillingCyclePeriod ---
    def create_billing_cycle_period(self, payload, headers):
        return self._request("POST", "/billing-cycle-periods", payload, headers)

    def list_billing_cycle_periods(self, headers, params=None):
        return self._request("GET", "/billing-cycle-periods", headers=headers, params=params)

    def get_billing_cycle_period(self, period_id, headers):
        return self._request("GET", f"/billing-cycle-periods/{period_id}", headers=headers)

    def open_read_window(self, period_id, headers):
        return self._request("POST", f"/billing-cycle-periods/{period_id}/open-read-window", {}, headers)

    def close_read_window(self, period_id, headers):
        return self._request("POST", f"/billing-cycle-periods/{period_id}/close-read-window", {}, headers)

    def finalize_billing(self, period_id, headers):
        return self._request("POST", f"/billing-cycle-periods/{period_id}/finalize-billing", {}, headers)

    def close_billing_period(self, period_id, headers):
        return self._request("POST", f"/billing-cycle-periods/{period_id}/close", {}, headers)

    # --- Route ---
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/routes/{route_id}/stops", headers=headers, params=params)

    def assign_route(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/assign", payload, headers)

    def reassign_route(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/reassign", payload, headers)

    def unassign_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/unassign", {}, headers)

    def start_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/start", {}, headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/complete", {}, headers)

    def reconcile_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/reconcile", {}, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/cancel", {}, headers)

    # --- RouteStop ---
    def list_stops(self, headers, params=None):
        return self._request("GET", "/route-stops", headers=headers, params=params)

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/route-stops/{stop_id}", headers=headers)

    def capture_read(self, stop_id, payload, headers):
        return self._request("POST", f"/route-stops/{stop_id}/reads", payload, headers)

    def mark_no_read(self, stop_id, payload, headers):
        return self._request("POST", f"/route-stops/{stop_id}/mark-no-read", payload, headers)

    def skip_hazard(self, stop_id, payload, headers):
        return self._request("POST", f"/route-stops/{stop_id}/skip-hazard", payload, headers)

    def generate_estimate(self, stop_id, headers):
        return self._request("POST", f"/route-stops/{stop_id}/generate-estimate", {}, headers)

    # --- MeterRead ---
    def list_reads(self, headers, params=None):
        return self._request("GET", "/reads", headers=headers, params=params)

    def get_read(self, read_id, headers):
        return self._request("GET", f"/reads/{read_id}", headers=headers)

    def validate_read(self, read_id, headers):
        return self._request("POST", f"/reads/{read_id}/validate", {}, headers)

    def reject_read(self, read_id, payload, headers):
        return self._request("POST", f"/reads/{read_id}/reject", payload, headers)

    # --- HazardFlag ---
    def report_hazard_flag(self, payload, headers):
        return self._request("POST", "/hazard-flags", payload, headers)

    def list_hazard_flags(self, headers, params=None):
        return self._request("GET", "/hazard-flags", headers=headers, params=params)

    def get_hazard_flag(self, flag_id, headers):
        return self._request("GET", f"/hazard-flags/{flag_id}", headers=headers)

    def clear_hazard_flag(self, flag_id, headers):
        return self._request("POST", f"/hazard-flags/{flag_id}/clear", {}, headers)

    def renew_hazard_flag(self, flag_id, headers):
        return self._request("POST", f"/hazard-flags/{flag_id}/renew", {}, headers)

    # --- WorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def dispatch_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/dispatch", payload, headers)

    def reschedule_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/reschedule", payload, headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/start", {}, headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", payload, headers)

    def verify_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/verify", {}, headers)

    def request_work_order_rework(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/request-rework", payload, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", {}, headers)

    # --- Investigation ---
    def create_investigation(self, payload, headers):
        return self._request("POST", "/investigations", payload, headers)

    def list_investigations(self, headers, params=None):
        return self._request("GET", "/investigations", headers=headers, params=params)

    def get_investigation(self, investigation_id, headers):
        return self._request("GET", f"/investigations/{investigation_id}", headers=headers)

    def begin_evidence(self, investigation_id, headers):
        return self._request("POST", f"/investigations/{investigation_id}/begin-evidence", {}, headers)

    def submit_disposition(self, investigation_id, headers):
        return self._request("POST", f"/investigations/{investigation_id}/submit-disposition", {}, headers)

    def request_more_evidence(self, investigation_id, headers):
        return self._request("POST", f"/investigations/{investigation_id}/request-more-evidence", {}, headers)

    def confirm_theft(self, investigation_id, payload, headers):
        return self._request("POST", f"/investigations/{investigation_id}/confirm-theft", payload, headers)

    def clear_investigation(self, investigation_id, headers):
        return self._request("POST", f"/investigations/{investigation_id}/clear", {}, headers)

    def close_investigation(self, investigation_id, headers):
        return self._request("POST", f"/investigations/{investigation_id}/close", {}, headers)

    # --- ReplacementCampaign / CampaignEnrollment ---
    def create_replacement_campaign(self, payload, headers):
        return self._request("POST", "/replacement-campaigns", payload, headers)

    def list_replacement_campaigns(self, headers, params=None):
        return self._request("GET", "/replacement-campaigns", headers=headers, params=params)

    def get_replacement_campaign(self, campaign_id, headers):
        return self._request("GET", f"/replacement-campaigns/{campaign_id}", headers=headers)

    def open_campaign(self, campaign_id, headers):
        return self._request("POST", f"/replacement-campaigns/{campaign_id}/open", {}, headers)

    def enroll_meters(self, campaign_id, payload, headers):
        return self._request("POST", f"/replacement-campaigns/{campaign_id}/enroll", payload, headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"/replacement-campaigns/{campaign_id}/close", {}, headers)

    def list_campaign_enrollments(self, headers, params=None):
        return self._request("GET", "/campaign-enrollments", headers=headers, params=params)

    def get_campaign_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/campaign-enrollments/{enrollment_id}", headers=headers)

    # --- OpsSnapshot ---
    def create_ops_snapshot(self, payload, headers):
        return self._request("POST", "/ops-snapshots", payload, headers)

    def list_ops_snapshots(self, headers, params=None):
        return self._request("GET", "/ops-snapshots", headers=headers, params=params)

    def get_ops_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/ops-snapshots/{snapshot_id}", headers=headers)

    def finalize_ops_snapshot(self, snapshot_id, headers):
        return self._request("POST", f"/ops-snapshots/{snapshot_id}/finalize", {}, headers)


api_client = ApiClient()
