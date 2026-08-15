"""API client: one method per endpoint declared in PRD 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Residential Appraisal Practice API."""

    # --- Logical clock (server root, outside the /appraisal mount) ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Clients ---
    def create_client(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/appraisal/clients", payload, headers)

    def get_client(self, client_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/appraisal/clients/{client_id}", headers=headers)

    def list_clients(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/appraisal/clients", headers=headers, params=params)

    def suspend_client(self, client_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/clients/{client_id}/suspend", {}, headers
        )

    def reactivate_client(self, client_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/clients/{client_id}/reactivate", {}, headers
        )

    def terminate_client(self, client_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/clients/{client_id}/terminate", {}, headers
        )

    # --- Appraisers ---
    def create_appraiser(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/appraisal/appraisers", payload, headers)

    def get_appraiser(self, appraiser_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/appraisal/appraisers/{appraiser_id}", headers=headers
        )

    def list_appraisers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/appraisal/appraisers", headers=headers, params=params
        )

    def deactivate_appraiser(self, appraiser_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/appraisers/{appraiser_id}/deactivate", {}, headers
        )

    def reactivate_appraiser(self, appraiser_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/appraisers/{appraiser_id}/reactivate", {}, headers
        )

    def clear_sanction(self, appraiser_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/appraisers/{appraiser_id}/clear-sanction", {}, headers
        )

    def get_scorecard(self, appraiser_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/appraisal/appraisers/{appraiser_id}/scorecard", headers=headers
        )

    # --- Panel memberships ---
    def create_panel_membership(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/appraisal/panel-memberships", payload, headers)

    def get_panel_membership(self, membership_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/appraisal/panel-memberships/{membership_id}", headers=headers
        )

    def remove_panel_membership(self, membership_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/panel-memberships/{membership_id}/remove", {}, headers
        )

    def list_panel_memberships(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/appraisal/panel-memberships", headers=headers, params=params
        )

    # --- Fee schedules ---
    def create_fee_schedule(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/appraisal/fee-schedules", payload, headers)

    def get_fee_schedule(self, schedule_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/appraisal/fee-schedules/{schedule_id}", headers=headers
        )

    def list_fee_schedules(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/appraisal/fee-schedules", headers=headers, params=params
        )

    # --- Orders ---
    def create_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/appraisal/orders", payload, headers)

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/appraisal/orders/{order_id}", headers=headers)

    def list_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/appraisal/orders", headers=headers, params=params)

    def determine_scope(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/appraisal/orders/{order_id}/determine-scope", payload, headers
        )

    def accept_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/appraisal/orders/{order_id}/accept", payload, headers
        )

    def assign_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/appraisal/orders/{order_id}/assign", payload, headers
        )

    def cancel_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/appraisal/orders/{order_id}/cancel", payload, headers
        )

    def start_analysis(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/orders/{order_id}/start-analysis", {}, headers
        )

    def complete_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/orders/{order_id}/complete", {}, headers
        )

    def create_fee_adjustment(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/appraisal/orders/{order_id}/fee-adjustments", payload, headers
        )

    # --- Appointments ---
    def create_appointment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/appraisal/appointments", payload, headers)

    def get_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/appraisal/appointments/{appointment_id}", headers=headers
        )

    def list_appointments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/appraisal/appointments", headers=headers, params=params
        )

    def confirm_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/appointments/{appointment_id}/confirm", {}, headers
        )

    def reschedule_appointment(
        self, appointment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/appraisal/appointments/{appointment_id}/reschedule",
            payload,
            headers,
        )

    def complete_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/appointments/{appointment_id}/complete", {}, headers
        )

    def no_show_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/appointments/{appointment_id}/no-show", {}, headers
        )

    def cancel_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/appointments/{appointment_id}/cancel", {}, headers
        )

    # --- Comparables ---
    def create_comparable(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/appraisal/comparables", payload, headers)

    def get_comparable(self, comparable_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/appraisal/comparables/{comparable_id}", headers=headers
        )

    def list_comparables(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/appraisal/comparables", headers=headers, params=params
        )

    def patch_comparable(
        self, comparable_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/appraisal/comparables/{comparable_id}", payload, headers
        )

    def verify_comparable(self, comparable_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/comparables/{comparable_id}/verify", {}, headers
        )

    def lock_comparable(self, comparable_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/comparables/{comparable_id}/lock", {}, headers
        )

    def exclude_comparable(self, comparable_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/comparables/{comparable_id}/exclude", {}, headers
        )

    # --- Reports ---
    def create_report(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/appraisal/reports", payload, headers)

    def get_report(self, report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/appraisal/reports/{report_id}", headers=headers)

    def list_reports(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/appraisal/reports", headers=headers, params=params
        )

    def submit_report_for_qc(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/reports/{report_id}/submit-for-qc", {}, headers
        )

    def qc_pass_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/reports/{report_id}/qc-pass", {}, headers
        )

    def qc_fail_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/appraisal/reports/{report_id}/qc-fail", payload, headers
        )

    def co_sign_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/reports/{report_id}/co-sign", {}, headers
        )

    def deliver_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/reports/{report_id}/deliver", {}, headers
        )

    # --- Revision requests ---
    def create_revision_request(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/appraisal/orders/{order_id}/revision-requests",
            payload,
            headers,
        )

    def get_revision_request(self, request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/appraisal/revision-requests/{request_id}", headers=headers
        )

    def list_revision_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/appraisal/revision-requests", headers=headers, params=params
        )

    def accept_revision_request(self, request_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/revision-requests/{request_id}/accept", {}, headers
        )

    def rebut_revision_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/appraisal/revision-requests/{request_id}/rebut", payload, headers
        )

    # --- Workfile records ---
    def create_workfile_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/appraisal/workfile-records", payload, headers)

    def get_workfile_record(self, record_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/appraisal/workfile-records/{record_id}", headers=headers
        )

    def list_workfile_records(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/appraisal/workfile-records", headers=headers, params=params
        )

    def purge_workfile_record(self, record_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/appraisal/workfile-records/{record_id}/purge", {}, headers
        )

    # --- Complaints ---
    def create_complaint(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/appraisal/complaints", payload, headers)

    def get_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/appraisal/complaints/{complaint_id}", headers=headers
        )

    def list_complaints(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/appraisal/complaints", headers=headers, params=params
        )

    def draft_complaint_response(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/appraisal/complaints/{complaint_id}/draft-response",
            payload,
            headers,
        )

    def submit_complaint_response(self, complaint_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/appraisal/complaints/{complaint_id}/submit-response",
            {},
            headers,
        )

    def close_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/appraisal/complaints/{complaint_id}/close", payload, headers
        )


api_client = ApiClient()
