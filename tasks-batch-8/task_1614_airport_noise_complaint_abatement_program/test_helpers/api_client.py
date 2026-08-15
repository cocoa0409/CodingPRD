"""API client: one method per endpoint declared in PRD 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Airport Noise Abatement API."""

    # --- Logical clock (outside the /noise-program mount) ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Complainants ---
    def create_complainant(self, payload, headers):
        return self._request("POST", "/noise-program/complainants", payload, headers)

    def list_complainants(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/noise-program/complainants", headers=headers, params=params)

    def get_complainant(self, complainant_id: str, headers):
        return self._request(
            "GET", f"/noise-program/complainants/{complainant_id}", headers=headers
        )

    def patch_complainant(self, complainant_id: str, payload, headers):
        return self._request(
            "PATCH", f"/noise-program/complainants/{complainant_id}", payload, headers
        )

    def list_complainant_complaints(self, complainant_id: str, headers, params=None):
        return self._request(
            "GET",
            f"/noise-program/complainants/{complainant_id}/noise-complaints",
            headers=headers,
            params=params,
        )

    def list_complainant_outreach_cases(self, complainant_id: str, headers, params=None):
        return self._request(
            "GET",
            f"/noise-program/complainants/{complainant_id}/outreach-cases",
            headers=headers,
            params=params,
        )

    # --- Noise complaints ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/noise-program/noise-complaints", payload, headers)

    def list_complaints(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/noise-program/noise-complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id: str, headers):
        return self._request(
            "GET", f"/noise-program/noise-complaints/{complaint_id}", headers=headers
        )

    def begin_review(self, complaint_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-complaints/{complaint_id}/begin-review", payload, headers
        )

    def request_info(self, complaint_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-complaints/{complaint_id}/request-info", payload, headers
        )

    def provide_info(self, complaint_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-complaints/{complaint_id}/provide-info", payload, headers
        )

    def correlate_complaint(self, complaint_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-complaints/{complaint_id}/correlate", payload, headers
        )

    def close_complaint(self, complaint_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-complaints/{complaint_id}/close", payload, headers
        )

    def reopen_complaint(self, complaint_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-complaints/{complaint_id}/reopen", payload, headers
        )

    def resume_review(self, complaint_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-complaints/{complaint_id}/resume-review", payload, headers
        )

    def withdraw_complaint(self, complaint_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-complaints/{complaint_id}/withdraw", payload, headers
        )

    # --- Flight operations ---
    def create_flight(self, payload, headers):
        return self._request("POST", "/noise-program/flight-operations", payload, headers)

    def list_flights(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/noise-program/flight-operations", headers=headers, params=params)

    def get_flight(self, flight_id: str, headers):
        return self._request(
            "GET", f"/noise-program/flight-operations/{flight_id}", headers=headers
        )

    def patch_flight(self, flight_id: str, payload, headers):
        return self._request(
            "PATCH", f"/noise-program/flight-operations/{flight_id}", payload, headers
        )

    # --- Operators ---
    def create_operator(self, payload, headers):
        return self._request("POST", "/noise-program/operators", payload, headers)

    def list_operators(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/noise-program/operators", headers=headers, params=params)

    def get_operator(self, operator_id: str, headers):
        return self._request("GET", f"/noise-program/operators/{operator_id}", headers=headers)

    def list_operator_notifications(self, operator_id: str, headers, params=None):
        return self._request(
            "GET",
            f"/noise-program/operators/{operator_id}/operator-notifications",
            headers=headers,
            params=params,
        )

    def get_compliance_summary(self, operator_id: str, headers, params=None):
        return self._request(
            "GET",
            f"/noise-program/operators/{operator_id}/compliance-summary",
            headers=headers,
            params=params,
        )

    # --- Noise monitors / outages / events / dnl ---
    def create_monitor(self, payload, headers):
        return self._request("POST", "/noise-program/noise-monitors", payload, headers)

    def list_monitors(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/noise-program/noise-monitors", headers=headers, params=params)

    def get_monitor(self, monitor_id: str, headers):
        return self._request("GET", f"/noise-program/noise-monitors/{monitor_id}", headers=headers)

    def create_outage(self, monitor_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-monitors/{monitor_id}/outages", payload, headers
        )

    def list_outages(self, monitor_id: str, headers, params=None):
        return self._request(
            "GET", f"/noise-program/noise-monitors/{monitor_id}/outages", headers=headers, params=params
        )

    def decommission_monitor(self, monitor_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-monitors/{monitor_id}/decommission", payload, headers
        )

    def ingest_event(self, monitor_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-monitors/{monitor_id}/events", payload, headers
        )

    def get_monitor_dnl(self, monitor_id: str, headers, params=None):
        return self._request(
            "GET", f"/noise-program/noise-monitors/{monitor_id}/dnl", headers=headers, params=params
        )

    # --- Noise events ---
    def list_events(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/noise-program/noise-events", headers=headers, params=params)

    def get_event(self, event_id: str, headers):
        return self._request("GET", f"/noise-program/noise-events/{event_id}", headers=headers)

    def begin_screening(self, event_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-events/{event_id}/begin-screening", payload, headers
        )

    def classify_event(self, event_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-events/{event_id}/classify", payload, headers
        )

    def verify_event(self, event_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-events/{event_id}/verify", payload, headers
        )

    def discard_event(self, event_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-events/{event_id}/discard", payload, headers
        )

    def reclassify_event(self, event_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-events/{event_id}/reclassify", payload, headers
        )

    # --- Curfew rules ---
    def create_curfew_rule(self, payload, headers):
        return self._request("POST", "/noise-program/curfew-rules", payload, headers)

    def list_curfew_rules(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/noise-program/curfew-rules", headers=headers, params=params)

    def get_curfew_rule(self, rule_id: str, headers):
        return self._request("GET", f"/noise-program/curfew-rules/{rule_id}", headers=headers)

    def suspend_curfew_rule(self, rule_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/curfew-rules/{rule_id}/suspend", payload, headers
        )

    # --- Operator notifications ---
    def create_notification(self, payload, headers):
        return self._request("POST", "/noise-program/operator-notifications", payload, headers)

    def list_notifications(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", "/noise-program/operator-notifications", headers=headers, params=params
        )

    def get_notification(self, notification_id: str, headers):
        return self._request(
            "GET", f"/noise-program/operator-notifications/{notification_id}", headers=headers
        )

    def send_notification(self, notification_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/operator-notifications/{notification_id}/send", payload, headers
        )

    def acknowledge_notification(self, notification_id: str, payload, headers):
        return self._request(
            "POST",
            f"/noise-program/operator-notifications/{notification_id}/acknowledge",
            payload,
            headers,
        )

    def respond_notification(self, notification_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/operator-notifications/{notification_id}/respond", payload, headers
        )

    def close_notification(self, notification_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/operator-notifications/{notification_id}/close", payload, headers
        )

    def escalate_notification(self, notification_id: str, payload, headers):
        return self._request(
            "POST",
            f"/noise-program/operator-notifications/{notification_id}/escalate",
            payload,
            headers,
        )

    # --- Noise studies / parcels ---
    def create_study(self, payload, headers):
        return self._request("POST", "/noise-program/noise-studies", payload, headers)

    def list_studies(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/noise-program/noise-studies", headers=headers, params=params)

    def get_study(self, study_id: str, headers):
        return self._request("GET", f"/noise-program/noise-studies/{study_id}", headers=headers)

    def start_data_collection(self, study_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-studies/{study_id}/start-data-collection", payload, headers
        )

    def release_draft(self, study_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-studies/{study_id}/release-draft", payload, headers
        )

    def open_public_comment(self, study_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-studies/{study_id}/open-public-comment", payload, headers
        )

    def request_revision(self, study_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-studies/{study_id}/request-revision", payload, headers
        )

    def adopt_study(self, study_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-studies/{study_id}/adopt", payload, headers
        )

    def create_parcel(self, study_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/noise-studies/{study_id}/parcels", payload, headers
        )

    def list_study_parcels(self, study_id: str, headers, params=None):
        return self._request(
            "GET", f"/noise-program/noise-studies/{study_id}/parcels", headers=headers, params=params
        )

    def get_parcel(self, parcel_id: str, headers):
        return self._request(
            "GET", f"/noise-program/land-use-parcels/{parcel_id}", headers=headers
        )

    def reassess_parcel(self, parcel_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/land-use-parcels/{parcel_id}/reassess", payload, headers
        )

    # --- Insulation funds ---
    def create_fund(self, payload, headers):
        return self._request("POST", "/noise-program/insulation-funds", payload, headers)

    def list_funds(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/noise-program/insulation-funds", headers=headers, params=params)

    def get_fund(self, fund_id: str, headers):
        return self._request("GET", f"/noise-program/insulation-funds/{fund_id}", headers=headers)

    def allocate_fund(self, fund_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/insulation-funds/{fund_id}/allocate", payload, headers
        )

    def close_fund(self, fund_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/insulation-funds/{fund_id}/close", payload, headers
        )

    # --- Sound insulation applications ---
    def create_application(self, payload, headers):
        return self._request(
            "POST", "/noise-program/sound-insulation-applications", payload, headers
        )

    def list_applications(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", "/noise-program/sound-insulation-applications", headers=headers, params=params
        )

    def get_application(self, application_id: str, headers):
        return self._request(
            "GET",
            f"/noise-program/sound-insulation-applications/{application_id}",
            headers=headers,
        )

    def submit_application(self, application_id: str, payload, headers):
        return self._request(
            "POST",
            f"/noise-program/sound-insulation-applications/{application_id}/submit",
            payload,
            headers,
        )

    def begin_application_screening(self, application_id: str, payload, headers):
        return self._request(
            "POST",
            f"/noise-program/sound-insulation-applications/{application_id}/begin-screening",
            payload,
            headers,
        )

    def record_decision(self, application_id: str, payload, headers):
        return self._request(
            "POST",
            f"/noise-program/sound-insulation-applications/{application_id}/record-decision",
            payload,
            headers,
        )

    def appeal_application(self, application_id: str, payload, headers):
        return self._request(
            "POST",
            f"/noise-program/sound-insulation-applications/{application_id}/appeal",
            payload,
            headers,
        )

    def issue_offer(self, application_id: str, payload, headers):
        return self._request(
            "POST",
            f"/noise-program/sound-insulation-applications/{application_id}/issue-offer",
            payload,
            headers,
        )

    def accept_offer(self, application_id: str, payload, headers):
        return self._request(
            "POST",
            f"/noise-program/sound-insulation-applications/{application_id}/accept-offer",
            payload,
            headers,
        )

    def decline_offer(self, application_id: str, payload, headers):
        return self._request(
            "POST",
            f"/noise-program/sound-insulation-applications/{application_id}/decline-offer",
            payload,
            headers,
        )

    def disburse_application(self, application_id: str, payload, headers):
        return self._request(
            "POST",
            f"/noise-program/sound-insulation-applications/{application_id}/disburse",
            payload,
            headers,
        )

    def withdraw_application(self, application_id: str, payload, headers):
        return self._request(
            "POST",
            f"/noise-program/sound-insulation-applications/{application_id}/withdraw",
            payload,
            headers,
        )

    # --- Outreach cases ---
    def create_outreach_case(self, payload, headers):
        return self._request("POST", "/noise-program/outreach-cases", payload, headers)

    def list_outreach_cases(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/noise-program/outreach-cases", headers=headers, params=params)

    def get_outreach_case(self, case_id: str, headers):
        return self._request("GET", f"/noise-program/outreach-cases/{case_id}", headers=headers)

    def log_contact(self, case_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/outreach-cases/{case_id}/log-contact", payload, headers
        )

    def resolve_case(self, case_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/outreach-cases/{case_id}/resolve", payload, headers
        )

    def mark_dormant(self, case_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/outreach-cases/{case_id}/mark-dormant", payload, headers
        )

    def reactivate_case(self, case_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/outreach-cases/{case_id}/reactivate", payload, headers
        )

    # --- Quarterly reports ---
    def create_report(self, payload, headers):
        return self._request("POST", "/noise-program/quarterly-reports", payload, headers)

    def list_reports(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/noise-program/quarterly-reports", headers=headers, params=params)

    def get_report(self, report_id: str, headers):
        return self._request(
            "GET", f"/noise-program/quarterly-reports/{report_id}", headers=headers
        )

    def patch_report(self, report_id: str, payload, headers):
        return self._request(
            "PATCH", f"/noise-program/quarterly-reports/{report_id}", payload, headers
        )

    def submit_for_review(self, report_id: str, payload, headers):
        return self._request(
            "POST",
            f"/noise-program/quarterly-reports/{report_id}/submit-for-review",
            payload,
            headers,
        )

    def approve_report(self, report_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/quarterly-reports/{report_id}/approve", payload, headers
        )

    def return_for_revision(self, report_id: str, payload, headers):
        return self._request(
            "POST",
            f"/noise-program/quarterly-reports/{report_id}/return-for-revision",
            payload,
            headers,
        )

    def publish_report(self, report_id: str, payload, headers):
        return self._request(
            "POST", f"/noise-program/quarterly-reports/{report_id}/publish", payload, headers
        )

    # --- Community zone computed read ---
    def get_annoyance_index(self, zone_code: str, headers):
        return self._request(
            "GET", f"/noise-program/community-zones/{zone_code}/annoyance-index", headers=headers
        )


api_client = ApiClient()
