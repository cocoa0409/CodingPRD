"""
Endpoint client for the Neurodiagnostic EMU API.

One method per endpoint in PRD §4. Every method returns the raw
`requests.Response` so tests can assert on status codes and envelopes through
the framework validators.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class ApiClient(GenericApiClient):
    """Thin, complete binding of every documented endpoint."""

    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Monitoring units and beds (PRD §3.1)
    # ------------------------------------------------------------------

    def create_unit(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/units", payload, headers)

    def get_unit(self, unit_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/units/{unit_id}", None, headers)

    def run_retention_sweep(self, unit_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/units/{unit_id}/retention-sweep", {}, headers
        )

    def create_bed(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/beds", payload, headers)

    def list_unit_beds(self, unit_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/units/{unit_id}/beds", params, headers
        )

    # ------------------------------------------------------------------
    # Technologist coverage windows (PRD §3.1)
    # ------------------------------------------------------------------

    def create_shift(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/technologist-shifts", payload, headers
        )

    def list_unit_shifts(self, unit_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/units/{unit_id}/technologist-shifts", params, headers
        )

    def get_shift(self, shift_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/technologist-shifts/{shift_id}", None, headers
        )

    def activate_shift(self, shift_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/technologist-shifts/{shift_id}/activate", {}, headers
        )

    def close_shift(self, shift_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/technologist-shifts/{shift_id}/close", {}, headers
        )

    # ------------------------------------------------------------------
    # Patients and payer authorization (PRD §3.2)
    # ------------------------------------------------------------------

    def create_patient(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/patients", payload, headers)

    def get_patient(self, patient_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/patients/{patient_id}", None, headers)

    def create_authorization(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/authorizations", payload, headers)

    def list_patient_authorizations(
        self, patient_id: str, headers, params=None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/patients/{patient_id}/authorizations", params, headers
        )

    def get_authorization(self, authorization_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/authorizations/{authorization_id}", None, headers
        )

    def submit_authorization(self, authorization_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/authorizations/{authorization_id}/submit", {}, headers
        )

    def record_payer_decision(
        self, authorization_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/authorizations/{authorization_id}/payer-decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Admissions (PRD §3.3)
    # ------------------------------------------------------------------

    def create_admission(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/admissions", payload, headers)

    def list_admissions(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/admissions", params, headers)

    def get_admission(self, admission_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/admissions/{admission_id}", None, headers
        )

    def admit(
        self, admission_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/admissions/{admission_id}/admit", payload, headers
        )

    def record_extension_decision(
        self, admission_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/admissions/{admission_id}/extension-decisions",
            payload,
            headers,
        )

    def discharge(
        self, admission_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/admissions/{admission_id}/discharge", payload, headers
        )

    def get_capture_summary(self, admission_id: str, headers) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/admissions/{admission_id}/capture-summary",
            None,
            headers,
        )

    # ------------------------------------------------------------------
    # Taper plans (PRD §3.4)
    # ------------------------------------------------------------------

    def create_taper_plan(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/taper-plans", payload, headers)

    def list_admission_taper_plans(
        self, admission_id: str, headers, params=None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/admissions/{admission_id}/taper-plans",
            params,
            headers,
        )

    def get_taper_plan(self, taper_plan_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/taper-plans/{taper_plan_id}", None, headers
        )

    def advance_taper_step(self, taper_plan_id: str, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/taper-plans/{taper_plan_id}/advance-step",
            {},
            headers,
        )

    def hold_taper_plan(
        self, taper_plan_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/taper-plans/{taper_plan_id}/hold", payload, headers
        )

    def resume_taper_plan(self, taper_plan_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/taper-plans/{taper_plan_id}/resume", {}, headers
        )

    # ------------------------------------------------------------------
    # Studies (PRD §3.5, §3.9)
    # ------------------------------------------------------------------

    def create_study(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/studies", payload, headers)

    def list_studies(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/studies", params, headers)

    def get_study(self, study_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/studies/{study_id}", None, headers)

    def start_study(
        self, study_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/studies/{study_id}/start", payload, headers
        )

    def pause_study(
        self, study_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/studies/{study_id}/pause", payload, headers
        )

    def resume_study(self, study_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/studies/{study_id}/resume", {}, headers
        )

    def complete_study(self, study_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/studies/{study_id}/complete", {}, headers
        )

    def archive_study(self, study_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/studies/{study_id}/archive", {}, headers
        )

    def place_export_hold(
        self, study_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/studies/{study_id}/export-hold", payload, headers
        )

    def release_export_hold(self, study_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/studies/{study_id}/export-release", {}, headers
        )

    # ------------------------------------------------------------------
    # Seizure alerts and bedside response (PRD §3.6)
    # ------------------------------------------------------------------

    def raise_alert(
        self, study_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/studies/{study_id}/alerts", payload, headers
        )

    def list_study_alerts(self, study_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/studies/{study_id}/alerts", params, headers
        )

    def get_alert(self, alert_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/alerts/{alert_id}", None, headers)

    def adjudicate_alert(
        self, alert_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/alerts/{alert_id}/adjudicate", payload, headers
        )

    def close_alert(self, alert_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/alerts/{alert_id}/close", {}, headers
        )

    def record_intervention(
        self, alert_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/alerts/{alert_id}/interventions", payload, headers
        )

    def list_alert_interventions(
        self, alert_id: str, headers, params=None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/alerts/{alert_id}/interventions", params, headers
        )

    # ------------------------------------------------------------------
    # Event markings (PRD §3.7)
    # ------------------------------------------------------------------

    def create_marking(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/markings", payload, headers)

    def list_markings(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/markings", params, headers)

    def get_marking(self, marking_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/markings/{marking_id}", None, headers)

    def adjudicate_marking(self, marking_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/markings/{marking_id}/adjudicate", {}, headers
        )

    def retract_marking(
        self, marking_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/markings/{marking_id}/retract", payload, headers
        )

    # ------------------------------------------------------------------
    # Review reports (PRD §3.8)
    # ------------------------------------------------------------------

    def list_study_reports(
        self, study_id: str, headers, params=None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/studies/{study_id}/reports", params, headers
        )

    def get_report(self, report_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/reports/{report_id}", None, headers)

    def issue_prelim(
        self, report_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/reports/{report_id}/issue-prelim", payload, headers
        )

    def open_addendum(
        self, report_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/reports/{report_id}/open-addendum", payload, headers
        )

    def issue_final(
        self, report_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/reports/{report_id}/issue-final", payload, headers
        )

    # ------------------------------------------------------------------
    # Export packages (PRD §3.9)
    # ------------------------------------------------------------------

    def create_export(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/exports", payload, headers)

    def list_exports(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/exports", params, headers)

    def get_export(self, export_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/exports/{export_id}", None, headers)

    def build_export(self, export_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/exports/{export_id}/build", {}, headers
        )

    def deliver_export(
        self, export_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/exports/{export_id}/deliver", payload, headers
        )

    def revoke_export(
        self, export_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/exports/{export_id}/revoke", payload, headers
        )

    # ------------------------------------------------------------------
    # Surgical conference (PRD §3.9)
    # ------------------------------------------------------------------

    def create_conference_case(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/conference-cases", payload, headers
        )

    def list_conference_cases(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/conference-cases", params, headers)

    def get_conference_case(self, case_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/conference-cases/{case_id}", None, headers
        )

    def present_case(self, case_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/conference-cases/{case_id}/present", {}, headers
        )

    def cast_vote(
        self, case_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/conference-cases/{case_id}/votes", payload, headers
        )

    def list_case_votes(self, case_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/conference-cases/{case_id}/votes", params, headers
        )

    def close_vote(self, case_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/conference-cases/{case_id}/close-vote", {}, headers
        )

    # ------------------------------------------------------------------
    # Raw escape hatch for negative-path probes
    # ------------------------------------------------------------------

    def raw(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(method, path, payload, headers)
