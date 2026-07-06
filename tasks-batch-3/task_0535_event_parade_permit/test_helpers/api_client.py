"""API client: one method per endpoint defined in the Event Parade Permit PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # ---- Applicant ----
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers=headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    # ---- Venue ----
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/venues", headers=headers, params=params)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def decommission_venue(self, venue_id, headers):
        return self._request("POST", f"/venues/{venue_id}/decommission", headers=headers)

    # ---- ClosureSchedule ----
    def create_closure_schedule(self, payload, headers):
        return self._request("POST", "/closure-schedules", payload, headers=headers)

    def list_closure_schedules(self, headers, params=None):
        return self._request("GET", "/closure-schedules", headers=headers, params=params)

    def get_closure_schedule(self, schedule_id, headers):
        return self._request("GET", f"/closure-schedules/{schedule_id}", headers=headers)

    def suspend_closure_schedule(self, schedule_id, headers):
        return self._request("POST", f"/closure-schedules/{schedule_id}/suspend", headers=headers)

    # ---- PermitApplication ----
    def create_application(self, payload, headers):
        return self._request("POST", "/permit-applications", payload, headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/permit-applications", headers=headers, params=params)

    def get_application(self, app_id, headers):
        return self._request("GET", f"/permit-applications/{app_id}", headers=headers)

    def edit_application(self, app_id, payload, headers):
        return self._request("PATCH", f"/permit-applications/{app_id}", payload, headers=headers)

    def submit_for_review(self, app_id, payload, headers):
        return self._request("POST", f"/permit-applications/{app_id}/submit-for-review",
                             payload, headers=headers)

    def cancel_application(self, app_id, headers):
        return self._request("POST", f"/permit-applications/{app_id}/cancel", headers=headers)

    def issue_application(self, app_id, headers):
        return self._request("POST", f"/permit-applications/{app_id}/issue", headers=headers)

    # ---- RouteSegment ----
    def add_route_segment(self, app_id, payload, headers):
        return self._request("POST", f"/permit-applications/{app_id}/route-segments",
                             payload, headers=headers)

    def list_route_segments(self, app_id, headers, params=None):
        return self._request("GET", f"/permit-applications/{app_id}/route-segments",
                             headers=headers, params=params)

    def get_route_segment(self, app_id, segment_id, headers):
        return self._request("GET",
                             f"/permit-applications/{app_id}/route-segments/{segment_id}",
                             headers=headers)

    def list_route_segments_global(self, headers, params=None):
        return self._request("GET", "/route-segments", headers=headers, params=params)

    def get_route_segment_global(self, segment_id, headers):
        return self._request("GET", f"/route-segments/{segment_id}", headers=headers)

    # ---- DepartmentReview ----
    def list_reviews(self, app_id, headers, params=None):
        return self._request("GET", f"/permit-applications/{app_id}/reviews",
                             headers=headers, params=params)

    def get_review(self, app_id, review_id, headers):
        return self._request("GET", f"/permit-applications/{app_id}/reviews/{review_id}",
                             headers=headers)

    def approve_review(self, app_id, review_id, payload, headers):
        return self._request("POST",
                             f"/permit-applications/{app_id}/reviews/{review_id}/approve",
                             payload, headers=headers)

    def request_changes_review(self, app_id, review_id, payload, headers):
        return self._request("POST",
                             f"/permit-applications/{app_id}/reviews/{review_id}/request-changes",
                             payload, headers=headers)

    def veto_review(self, app_id, review_id, payload, headers):
        return self._request("POST",
                             f"/permit-applications/{app_id}/reviews/{review_id}/veto",
                             payload, headers=headers)

    def log_actuals(self, app_id, review_id, payload, headers):
        return self._request("POST",
                             f"/permit-applications/{app_id}/reviews/{review_id}/log-actuals",
                             payload, headers=headers)

    def list_reviews_global(self, headers, params=None):
        return self._request("GET", "/department-reviews", headers=headers, params=params)

    def get_review_global(self, review_id, headers):
        return self._request("GET", f"/department-reviews/{review_id}", headers=headers)

    # ---- PermitCondition ----
    def add_condition(self, app_id, review_id, payload, headers):
        return self._request("POST",
                             f"/permit-applications/{app_id}/reviews/{review_id}/conditions",
                             payload, headers=headers)

    def list_conditions(self, app_id, headers, params=None):
        return self._request("GET", f"/permit-applications/{app_id}/conditions",
                             headers=headers, params=params)

    def list_review_conditions(self, app_id, review_id, headers, params=None):
        return self._request("GET",
                             f"/permit-applications/{app_id}/reviews/{review_id}/conditions",
                             headers=headers, params=params)

    def acknowledge_condition(self, app_id, condition_id, headers):
        return self._request("POST",
                             f"/permit-applications/{app_id}/conditions/{condition_id}/acknowledge",
                             headers=headers)

    def list_conditions_global(self, headers, params=None):
        return self._request("GET", "/permit-conditions", headers=headers, params=params)

    def get_condition_global(self, condition_id, headers):
        return self._request("GET", f"/permit-conditions/{condition_id}", headers=headers)

    # ---- InsuranceCertificate (COI) ----
    def submit_coi(self, app_id, payload, headers):
        return self._request("POST", f"/permit-applications/{app_id}/coi",
                             payload, headers=headers)

    def list_coi(self, app_id, headers, params=None):
        return self._request("GET", f"/permit-applications/{app_id}/coi",
                             headers=headers, params=params)

    def accept_coi(self, app_id, coi_id, headers):
        return self._request("POST", f"/permit-applications/{app_id}/coi/{coi_id}/accept",
                             headers=headers)

    def reject_coi(self, app_id, coi_id, headers):
        return self._request("POST", f"/permit-applications/{app_id}/coi/{coi_id}/reject",
                             headers=headers)

    def list_coi_global(self, headers, params=None):
        return self._request("GET", "/insurance-certificates", headers=headers, params=params)

    def get_coi_global(self, coi_id, headers):
        return self._request("GET", f"/insurance-certificates/{coi_id}", headers=headers)

    # ---- Deposit ----
    def pay_deposit(self, app_id, payload, headers):
        return self._request("POST", f"/permit-applications/{app_id}/deposit",
                             payload, headers=headers)

    def list_deposits(self, app_id, headers, params=None):
        return self._request("GET", f"/permit-applications/{app_id}/deposit",
                             headers=headers, params=params)

    def list_deposits_global(self, headers, params=None):
        return self._request("GET", "/deposits", headers=headers, params=params)

    def get_deposit_global(self, deposit_id, headers):
        return self._request("GET", f"/deposits/{deposit_id}", headers=headers)

    # ---- Invoice ----
    def list_invoices(self, app_id, headers, params=None):
        return self._request("GET", f"/permit-applications/{app_id}/invoice",
                             headers=headers, params=params)

    def list_invoices_global(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice_global(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    # ---- CleanupDebrief ----
    def open_debrief(self, app_id, payload, headers):
        return self._request("POST", f"/permit-applications/{app_id}/debrief",
                             payload, headers=headers)

    def list_debriefs(self, app_id, headers, params=None):
        return self._request("GET", f"/permit-applications/{app_id}/debrief",
                             headers=headers, params=params)

    def finalize_debrief(self, app_id, debrief_id, headers):
        return self._request("POST",
                             f"/permit-applications/{app_id}/debrief/{debrief_id}/finalize",
                             headers=headers)

    def list_debriefs_global(self, headers, params=None):
        return self._request("GET", "/cleanup-debriefs", headers=headers, params=params)

    def get_debrief_global(self, debrief_id, headers):
        return self._request("GET", f"/cleanup-debriefs/{debrief_id}", headers=headers)


api_client = ApiClient()
