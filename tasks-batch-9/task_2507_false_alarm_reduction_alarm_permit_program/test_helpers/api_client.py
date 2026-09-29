"""Typed endpoint client: one method per route in the PRD endpoint table.

Every method returns the raw ``requests.Response`` so that tests can assert on
the HTTP status as well as the envelope.
"""
from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class ApiClient(GenericApiClient):
    """One method per route under the program prefix."""

    # ---------------------------------------------------------------- system
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers)

    def run_nightly(self, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/_program-runs/nightly", payload or {}, headers)

    # --------------------------------------------------------- fee schedules
    def create_fee_schedule(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/fee-schedules", payload, headers)

    def activate_fee_schedule(
        self, schedule_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/fee-schedules/{schedule_id}/activate", payload or {}, headers
        )

    def get_fee_schedule(self, schedule_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/fee-schedules/{schedule_id}", None, headers)

    def list_fee_schedules(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/fee-schedules", params, headers)

    # -------------------------------------------------------- alarm companies
    def create_alarm_company(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/alarm-companies", payload, headers)

    def company_status_action(
        self, company_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/alarm-companies/{company_id}/status-actions", payload, headers
        )

    def get_alarm_company(self, company_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/alarm-companies/{company_id}", None, headers)

    def list_alarm_companies(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/alarm-companies", params, headers)

    # ------------------------------------------------------------ alarm sites
    def create_alarm_site(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/alarm-sites", payload, headers)

    def get_alarm_site(self, site_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/alarm-sites/{site_id}", None, headers)

    def list_alarm_sites(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/alarm-sites", params, headers)

    def get_false_alarm_summary(self, site_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/alarm-sites/{site_id}/false-alarm-summary", None, headers
        )

    # ---------------------------------------------------------- site contacts
    def create_site_contact(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/site-contacts", payload, headers)

    def delete_site_contact(
        self, contact_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("DELETE", f"{API_PREFIX}/site-contacts/{contact_id}", params, headers)

    def get_site_contact(self, contact_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/site-contacts/{contact_id}", None, headers)

    def list_site_contacts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/site-contacts", params, headers)

    # ---------------------------------------------------------- alarm systems
    def create_alarm_system(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/alarm-systems", payload, headers)

    def patch_alarm_system(
        self, system_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{API_PREFIX}/alarm-systems/{system_id}", payload, headers)

    def approve_registration(
        self, system_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/alarm-systems/{system_id}/approve-registration", payload or {}, headers
        )

    def reject_registration(
        self, system_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/alarm-systems/{system_id}/reject-registration", payload, headers
        )

    def decommission_system(
        self, system_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/alarm-systems/{system_id}/decommission", payload or {}, headers
        )

    def get_alarm_system(self, system_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/alarm-systems/{system_id}", None, headers)

    def list_alarm_systems(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/alarm-systems", params, headers)

    # ---------------------------------------------------------- alarm permits
    def renew_permit(
        self, permit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/alarm-permits/{permit_id}/renewals", payload, headers
        )

    def revoke_permit(
        self, permit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/alarm-permits/{permit_id}/revoke", payload, headers
        )

    def get_alarm_permit(self, permit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/alarm-permits/{permit_id}", None, headers)

    def list_alarm_permits(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/alarm-permits", params, headers)

    # ------------------------------------------------------- dispatch requests
    def create_dispatch_request(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/dispatch-requests", payload, headers)

    def validate_dispatch_request(
        self, request_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/dispatch-requests/{request_id}/validate", payload or {}, headers
        )

    def refuse_dispatch_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/dispatch-requests/{request_id}/refuse", payload, headers
        )

    def record_dispatch(
        self, request_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/dispatch-requests/{request_id}/record-dispatch", payload or {}, headers
        )

    def cancel_dispatch_request(
        self, request_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/dispatch-requests/{request_id}/cancel", payload or {}, headers
        )

    def close_valid_dispatch_request(
        self, request_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/dispatch-requests/{request_id}/close-valid", payload or {}, headers
        )

    def get_dispatch_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/dispatch-requests/{request_id}", None, headers)

    def list_dispatch_requests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/dispatch-requests", params, headers)

    # --------------------------------------------------- false alarm incidents
    def create_false_alarm_incident(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/false-alarm-incidents", payload, headers)

    def determine_incident(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/false-alarm-incidents/{incident_id}/determination", payload, headers
        )

    def void_incident(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/false-alarm-incidents/{incident_id}/void", payload, headers
        )

    def get_false_alarm_incident(self, incident_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/false-alarm-incidents/{incident_id}", None, headers)

    def list_false_alarm_incidents(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/false-alarm-incidents", params, headers)

    # --------------------------------------------------------- hearing dockets
    def create_hearing_docket(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/hearing-dockets", payload, headers)

    def hold_session(
        self, docket_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/hearing-dockets/{docket_id}/hold-session", payload, headers
        )

    def cancel_docket(
        self, docket_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/hearing-dockets/{docket_id}/cancel", payload, headers
        )

    def get_hearing_docket(self, docket_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/hearing-dockets/{docket_id}", None, headers)

    def list_hearing_dockets(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/hearing-dockets", params, headers)

    # ----------------------------------------------------------------- appeals
    def create_appeal(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/appeals", payload, headers)

    def schedule_appeal(
        self, appeal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/appeals/{appeal_id}/schedule", payload, headers)

    def decide_appeal(
        self, appeal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/appeals/{appeal_id}/decide", payload, headers)

    def withdraw_appeal(
        self, appeal_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/appeals/{appeal_id}/withdraw", payload or {}, headers
        )

    def get_appeal(self, appeal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/appeals/{appeal_id}", None, headers)

    def list_appeals(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/appeals", params, headers)

    # ------------------------------------------------------- suspension orders
    def create_suspension_order(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/suspension-orders", payload, headers)

    def serve_suspension_order(
        self, order_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/suspension-orders/{order_id}/serve", payload or {}, headers
        )

    def request_reinstatement(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/suspension-orders/{order_id}/reinstatement-requests", payload, headers
        )

    def lift_suspension_order(
        self, order_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/suspension-orders/{order_id}/lift", payload or {}, headers
        )

    def vacate_suspension_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/suspension-orders/{order_id}/vacate", payload, headers
        )

    def get_suspension_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/suspension-orders/{order_id}", None, headers)

    def list_suspension_orders(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/suspension-orders", params, headers)

    # -------------------------------------------------------- penalty invoices
    def adjust_invoice(
        self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/penalty-invoices/{invoice_id}/adjustments", payload, headers
        )

    def refer_invoice_to_collections(
        self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/penalty-invoices/{invoice_id}/collections-referral", payload, headers
        )

    def get_penalty_invoice(self, invoice_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/penalty-invoices/{invoice_id}", None, headers)

    def list_penalty_invoices(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/penalty-invoices", params, headers)

    # --------------------------------------------------------- payment records
    def create_payment_record(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/payment-records", payload, headers)

    def void_payment_record(
        self, payment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/payment-records/{payment_id}/void", payload, headers
        )

    def get_payment_record(self, payment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/payment-records/{payment_id}", None, headers)

    def list_payment_records(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/payment-records", params, headers)

    # ----------------------------------------------------- payment allocations
    def get_payment_allocation(self, allocation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/payment-allocations/{allocation_id}", None, headers)

    def list_payment_allocations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/payment-allocations", params, headers)

    # ------------------------------------------------------ compliance reports
    def create_compliance_report(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/compliance-reports", payload, headers)

    def review_compliance_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/compliance-reports/{report_id}/review", payload, headers
        )

    def correct_compliance_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/compliance-reports/{report_id}/correct", payload, headers
        )

    def get_compliance_report(self, report_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/compliance-reports/{report_id}", None, headers)

    def list_compliance_reports(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/compliance-reports", params, headers)


api_client = ApiClient()
