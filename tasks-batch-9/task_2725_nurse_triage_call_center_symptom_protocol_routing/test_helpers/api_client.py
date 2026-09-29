"""One method per endpoint in the PRD §4 inventory.

PRD §4: "Every collection is mounted at the top level of the API; there is no
shared path prefix." Every method returns the raw response so tests can assert
status codes themselves.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Endpoint surface of the Nurse Triage Call Center API."""

    # ── The logical clock (PRD §2.4) ───────────────────────────────────────
    def set_clock(self, to_iso8601: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ── Practices (PRD §3.1) ───────────────────────────────────────────────
    def create_practice(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/practices", payload, headers)

    def get_practice(self, practice_id: str, headers: Headers = None):
        return self._request("GET", f"/practices/{practice_id}", None, headers)

    def patch_practice_status(
        self, practice_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "PATCH", f"/practices/{practice_id}/status", payload, headers
        )

    def create_patient(
        self, practice_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/practices/{practice_id}/patients", payload, headers
        )

    def list_patients(
        self, practice_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET", f"/practices/{practice_id}/patients", params, headers
        )

    def get_patient(self, patient_id: str, headers: Headers = None):
        return self._request("GET", f"/patients/{patient_id}", None, headers)

    def get_compliance_summary(self, practice_id: str, headers: Headers = None):
        return self._request(
            "GET", f"/practices/{practice_id}/compliance-summary", None, headers
        )

    def get_after_hours_invoice(self, practice_id: str, headers: Headers = None):
        return self._request(
            "GET", f"/practices/{practice_id}/after-hours-invoice", None, headers
        )

    # ── Coverage windows (PRD §3.2) ────────────────────────────────────────
    def create_coverage_window(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/coverage-windows", payload, headers)

    def activate_coverage_window(
        self, window_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/coverage-windows/{window_id}/activate", payload or {}, headers
        )

    def get_coverage_window(self, window_id: str, headers: Headers = None):
        return self._request("GET", f"/coverage-windows/{window_id}", None, headers)

    def list_practice_coverage_windows(
        self, practice_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET", f"/practices/{practice_id}/coverage-windows", params, headers
        )

    # ── Nurses, licences and shifts (PRD §3.2) ─────────────────────────────
    def create_nurse(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/nurses", payload, headers)

    def get_nurse(self, nurse_id: str, headers: Headers = None):
        return self._request("GET", f"/nurses/{nurse_id}", None, headers)

    def create_license(self, nurse_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"/nurses/{nurse_id}/licenses", payload, headers
        )

    def list_licenses(
        self, nurse_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request("GET", f"/nurses/{nurse_id}/licenses", params, headers)

    def create_shift(self, nurse_id: str, payload: Payload, headers: Headers = None):
        return self._request("POST", f"/nurses/{nurse_id}/shifts", payload, headers)

    def list_shifts(
        self, nurse_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request("GET", f"/nurses/{nurse_id}/shifts", params, headers)

    # ── Symptom protocols (PRD §3.1) ───────────────────────────────────────
    def create_protocol(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/symptom-protocols", payload, headers)

    def get_protocol(self, protocol_id: str, headers: Headers = None):
        return self._request("GET", f"/symptom-protocols/{protocol_id}", None, headers)

    def list_protocols(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/symptom-protocols", params, headers)

    def retire_protocol(
        self, protocol_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/symptom-protocols/{protocol_id}/retire", payload or {}, headers
        )

    # ── Triage calls (PRD §3.3, §3.4, §3.9) ────────────────────────────────
    def create_triage_call(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/triage-calls", payload, headers)

    def get_triage_call(self, call_id: str, headers: Headers = None):
        return self._request("GET", f"/triage-calls/{call_id}", None, headers)

    def list_triage_calls(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/triage-calls", params, headers)

    def match_patient(self, call_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"/triage-calls/{call_id}/match-patient", payload, headers
        )

    def record_consent(self, call_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"/triage-calls/{call_id}/consent", payload, headers
        )

    def assign_nurse(
        self, call_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/triage-calls/{call_id}/assign-nurse", payload or {}, headers
        )

    def create_assessment(
        self, call_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/triage-calls/{call_id}/assessments", payload, headers
        )

    def complete_call(self, call_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"/triage-calls/{call_id}/complete", payload, headers
        )

    def reopen_call(
        self, call_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"/triage-calls/{call_id}/reopen", payload or {}, headers
        )

    def abandon_call(self, call_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"/triage-calls/{call_id}/abandon", payload, headers
        )

    # ── Assessments (PRD §3.5) ─────────────────────────────────────────────
    def get_assessment(self, assessment_id: str, headers: Headers = None):
        return self._request(
            "GET", f"/protocol-assessments/{assessment_id}", None, headers
        )

    def list_assessments(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/protocol-assessments", params, headers)

    # ── Dispositions (PRD §3.6) ────────────────────────────────────────────
    def create_disposition(self, payload: Payload, headers: Headers = None):
        return self._request("POST", "/dispositions", payload, headers)

    def get_disposition(self, disposition_id: str, headers: Headers = None):
        return self._request("GET", f"/dispositions/{disposition_id}", None, headers)

    def list_dispositions(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/dispositions", params, headers)

    def override_disposition(
        self, disposition_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/dispositions/{disposition_id}/override", payload, headers
        )

    def create_audit_record(
        self, disposition_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/dispositions/{disposition_id}/audit-records", payload, headers
        )

    def list_audit_records(
        self, disposition_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET", f"/dispositions/{disposition_id}/audit-records", params, headers
        )

    # ── Warm transfers (PRD §3.7) ──────────────────────────────────────────
    def create_warm_transfer(
        self, call_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/triage-calls/{call_id}/warm-transfers", payload, headers
        )

    def get_warm_transfer(self, transfer_id: str, headers: Headers = None):
        return self._request("GET", f"/warm-transfers/{transfer_id}", None, headers)

    def list_call_warm_transfers(
        self, call_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET", f"/triage-calls/{call_id}/warm-transfers", params, headers
        )

    def confirm_transfer_location(
        self, transfer_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/warm-transfers/{transfer_id}/confirm-location", payload, headers
        )

    def psap_response(
        self, transfer_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/warm-transfers/{transfer_id}/psap-response", payload, headers
        )

    def complete_handoff(
        self, transfer_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"/warm-transfers/{transfer_id}/complete-handoff",
            payload or {},
            headers,
        )

    # ── Callback tasks (PRD §3.8) ──────────────────────────────────────────
    def get_callback_task(self, task_id: str, headers: Headers = None):
        return self._request("GET", f"/callback-tasks/{task_id}", None, headers)

    def list_callback_tasks(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/callback-tasks", params, headers)

    def create_callback_attempt(
        self, task_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"/callback-tasks/{task_id}/attempts", payload, headers
        )

    def verify_callback(self, task_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"/callback-tasks/{task_id}/verify", payload, headers
        )

    # ── Staffing readout (PRD §3.10) ───────────────────────────────────────
    def get_staffing_adequacy(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", "/staffing-adequacy", params, headers)


# A single shared client instance; the base URL comes from API_BASE_URL.
api_client = ApiClient()
