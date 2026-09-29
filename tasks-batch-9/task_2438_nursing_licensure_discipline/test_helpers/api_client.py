"""API client: one method per endpoint defined in the PRD.

Every collection is mounted at the root of the API; there is no shared path
prefix. Creating endpoints answer HTTP 201, everything else HTTP 200.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # State board configurations
    # ------------------------------------------------------------------
    def create_board_config(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/state-board-configs", payload, headers)

    def get_board_config(self, board_config_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/state-board-configs/{board_config_id}", headers=headers)

    def patch_board_config(self, board_config_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/state-board-configs/{board_config_id}", payload, headers)

    def list_board_education_programs(self, board_config_id: str, headers: Dict[str, str],
                                      params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/state-board-configs/{board_config_id}/education-programs",
                            headers=headers, params=params)

    def list_board_nurses(self, board_config_id: str, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/state-board-configs/{board_config_id}/nurses",
                            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Education programs
    # ------------------------------------------------------------------
    def create_education_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/education-programs", payload, headers)

    def get_education_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/education-programs/{program_id}", headers=headers)

    def patch_education_program(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/education-programs/{program_id}", payload, headers)

    # ------------------------------------------------------------------
    # Nurses
    # ------------------------------------------------------------------
    def create_nurse(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/nurses", payload, headers)

    def get_nurse(self, nurse_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/nurses/{nurse_id}", headers=headers)

    def patch_nurse(self, nurse_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/nurses/{nurse_id}", payload, headers)

    # ------------------------------------------------------------------
    # Licence applications
    # ------------------------------------------------------------------
    def create_license_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/license-applications", payload, headers)

    def list_license_applications(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/license-applications", headers=headers, params=params)

    def get_license_application(self, application_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/license-applications/{application_id}", headers=headers)

    def submit_license_application(self, application_id: str, headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/license-applications/{application_id}/submit",
                            payload or {}, headers)

    def return_license_application_deficient(self, application_id: str, payload: Dict[str, Any],
                                             headers: Dict[str, str]):
        return self._request("POST", f"/license-applications/{application_id}/deficiency",
                            payload, headers)

    def verify_license_application_qualification(self, application_id: str, headers: Dict[str, str],
                                                 payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/license-applications/{application_id}/qualification-verification",
                            payload or {}, headers)

    def record_screening_result(self, application_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"/license-applications/{application_id}/screening-result",
                            payload, headers)

    def record_board_decision(self, application_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"/license-applications/{application_id}/board-decision",
                            payload, headers)

    def withdraw_license_application(self, application_id: str, headers: Dict[str, str],
                                     payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/license-applications/{application_id}/withdrawal",
                            payload or {}, headers)

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------
    def create_license(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/licenses", payload, headers)

    def list_licenses(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/licenses", headers=headers, params=params)

    def get_license(self, license_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def change_license_status(self, license_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/licenses/{license_id}/status-change", payload, headers)

    def run_privilege_determination(self, license_id: str, payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request("POST", f"/licenses/{license_id}/privilege-determination",
                            payload, headers)

    def get_privilege_summary(self, license_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/licenses/{license_id}/privilege-summary", headers=headers)

    def list_license_renewal_applications(self, license_id: str, headers: Dict[str, str],
                                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/licenses/{license_id}/renewal-applications",
                            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Renewal filings
    # ------------------------------------------------------------------
    def create_renewal_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/renewal-applications", payload, headers)

    def get_renewal_application(self, renewal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/renewal-applications/{renewal_id}", headers=headers)

    def pay_renewal_application(self, renewal_id: str, headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/renewal-applications/{renewal_id}/payment",
                            payload or {}, headers)

    def create_ce_record(self, renewal_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/renewal-applications/{renewal_id}/ce-records",
                            payload, headers)

    def list_renewal_ce_records(self, renewal_id: str, headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/renewal-applications/{renewal_id}/ce-records",
                            headers=headers, params=params)

    def submit_renewal_application(self, renewal_id: str, headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/renewal-applications/{renewal_id}/submit",
                            payload or {}, headers)

    def verify_renewal_ce(self, renewal_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/renewal-applications/{renewal_id}/ce-verification",
                            payload or {}, headers)

    def finalize_renewal_application(self, renewal_id: str, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request("POST", f"/renewal-applications/{renewal_id}/finalization",
                            payload, headers)

    # ------------------------------------------------------------------
    # Practice-hour audit
    # ------------------------------------------------------------------
    def run_audit_sampling(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_ops/run-audit-sampling", payload, headers)

    def request_audit_documentation(self, renewal_id: str, headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/renewal-applications/{renewal_id}/audit-doc-request",
                            payload or {}, headers)

    def submit_audit_documentation(self, renewal_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request("POST", f"/renewal-applications/{renewal_id}/audit-doc-submission",
                            payload, headers)

    def decide_audit(self, renewal_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/renewal-applications/{renewal_id}/audit-decision",
                            payload or {}, headers)

    # ------------------------------------------------------------------
    # Continuing-education claims
    # ------------------------------------------------------------------
    def get_ce_record(self, ce_record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/ce-records/{ce_record_id}", headers=headers)

    def verify_ce_record(self, ce_record_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/ce-records/{ce_record_id}/verification", payload, headers)

    # ------------------------------------------------------------------
    # Complaints
    # ------------------------------------------------------------------
    def create_complaint(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/complaints", payload, headers)

    def list_complaints(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def triage_complaint(self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/complaints/{complaint_id}/triage", payload, headers)

    def open_investigation(self, complaint_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/complaints/{complaint_id}/investigation",
                            payload or {}, headers)

    def create_evidence_request(self, complaint_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"/complaints/{complaint_id}/evidence-requests",
                            payload, headers)

    def list_complaint_evidence_requests(self, complaint_id: str, headers: Dict[str, str],
                                         params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/complaints/{complaint_id}/evidence-requests",
                            headers=headers, params=params)

    def get_evidence_request(self, evidence_request_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/evidence-requests/{evidence_request_id}", headers=headers)

    def record_evidence_production(self, evidence_request_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request("POST", f"/evidence-requests/{evidence_request_id}/production",
                            payload, headers)

    def complete_complaint_evidence(self, complaint_id: str, headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/complaints/{complaint_id}/evidence-completion",
                            payload or {}, headers)

    def dispose_complaint(self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/complaints/{complaint_id}/disposition", payload, headers)

    def list_complaint_disciplinary_proceedings(self, complaint_id: str, headers: Dict[str, str],
                                                params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/complaints/{complaint_id}/disciplinary-proceedings",
                            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Monitoring agreements
    # ------------------------------------------------------------------
    def create_monitoring_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/monitoring-agreements", payload, headers)

    def list_monitoring_agreements(self, headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/monitoring-agreements", headers=headers, params=params)

    def get_monitoring_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/monitoring-agreements/{agreement_id}", headers=headers)

    def execute_monitoring_agreement(self, agreement_id: str, headers: Dict[str, str],
                                     payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/monitoring-agreements/{agreement_id}/execution",
                            payload or {}, headers)

    def record_monitoring_event(self, agreement_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"/monitoring-agreements/{agreement_id}/monitoring-events",
                            payload, headers)

    # ------------------------------------------------------------------
    # Disciplinary proceedings
    # ------------------------------------------------------------------
    def create_disciplinary_proceeding(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/disciplinary-proceedings", payload, headers)

    def get_disciplinary_proceeding(self, proceeding_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/disciplinary-proceedings/{proceeding_id}", headers=headers)

    def record_hearing_event(self, proceeding_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", f"/disciplinary-proceedings/{proceeding_id}/hearing-events",
                            payload, headers)

    def cast_vote(self, proceeding_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/disciplinary-proceedings/{proceeding_id}/votes",
                            payload, headers)

    def issue_order(self, proceeding_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/disciplinary-proceedings/{proceeding_id}/order",
                            payload or {}, headers)

    # ------------------------------------------------------------------
    # Notification reports
    # ------------------------------------------------------------------
    def list_notification_reports(self, headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/notification-reports", headers=headers, params=params)

    def get_notification_report(self, report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/notification-reports/{report_id}", headers=headers)

    def change_notification_report_status(self, report_id: str, payload: Dict[str, Any],
                                          headers: Dict[str, str]):
        return self._request("POST", f"/notification-reports/{report_id}/status", payload, headers)


api_client = ApiClient()
