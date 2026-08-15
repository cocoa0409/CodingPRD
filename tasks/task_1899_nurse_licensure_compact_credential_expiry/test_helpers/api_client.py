"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/credentialing"


class ApiClient(GenericApiClient):
    # --- Nurses ---
    def create_nurse(self, payload, headers):
        return self._request("POST", f"{BASE}/nurses", payload, headers)

    def list_nurses(self, headers, params=None):
        return self._request("GET", f"{BASE}/nurses", headers=headers, params=params)

    def get_nurse(self, nurse_id, headers):
        return self._request("GET", f"{BASE}/nurses/{nurse_id}", headers=headers)

    def patch_nurse(self, nurse_id, payload, headers):
        return self._request("PATCH", f"{BASE}/nurses/{nurse_id}", payload, headers)

    def activate_nurse(self, nurse_id, headers):
        return self._request("POST", f"{BASE}/nurses/{nurse_id}/activate", {}, headers)

    def terminate_nurse(self, nurse_id, headers):
        return self._request("POST", f"{BASE}/nurses/{nurse_id}/terminate", {}, headers)

    # --- State Licenses ---
    def create_state_license(self, payload, headers):
        return self._request("POST", f"{BASE}/state-licenses", payload, headers)

    def list_state_licenses(self, headers, params=None):
        return self._request("GET", f"{BASE}/state-licenses", headers=headers, params=params)

    def get_state_license(self, license_id, headers):
        return self._request("GET", f"{BASE}/state-licenses/{license_id}", headers=headers)

    def submit_license(self, license_id, headers):
        return self._request("POST", f"{BASE}/state-licenses/{license_id}/submit", {}, headers)

    def attest_license(self, license_id, headers):
        return self._request("POST", f"{BASE}/state-licenses/{license_id}/attest", {}, headers)

    def renew_license(self, license_id, payload, headers):
        return self._request("POST", f"{BASE}/state-licenses/{license_id}/renew", payload, headers)

    def surrender_license(self, license_id, headers):
        return self._request("POST", f"{BASE}/state-licenses/{license_id}/surrender", {}, headers)

    # --- Primary Source Verifications ---
    def create_psv(self, payload, headers):
        return self._request("POST", f"{BASE}/primary-source-verifications", payload, headers)

    def list_psvs(self, headers, params=None):
        return self._request("GET", f"{BASE}/primary-source-verifications", headers=headers, params=params)

    def get_psv(self, psv_id, headers):
        return self._request("GET", f"{BASE}/primary-source-verifications/{psv_id}", headers=headers)

    def record_psv_result(self, psv_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/primary-source-verifications/{psv_id}/record-result", payload, headers
        )

    # --- Certifications ---
    def create_certification(self, payload, headers):
        return self._request("POST", f"{BASE}/certifications", payload, headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", f"{BASE}/certifications", headers=headers, params=params)

    def get_certification(self, cert_id, headers):
        return self._request("GET", f"{BASE}/certifications/{cert_id}", headers=headers)

    def renew_certification(self, cert_id, payload, headers):
        return self._request("POST", f"{BASE}/certifications/{cert_id}/renew", payload, headers)

    def revoke_certification(self, cert_id, headers):
        return self._request("POST", f"{BASE}/certifications/{cert_id}/revoke", {}, headers)

    # --- Disciplinary Actions ---
    def create_disciplinary_action(self, payload, headers):
        return self._request("POST", f"{BASE}/disciplinary-actions", payload, headers)

    def list_disciplinary_actions(self, headers, params=None):
        return self._request("GET", f"{BASE}/disciplinary-actions", headers=headers, params=params)

    def get_disciplinary_action(self, action_id, headers):
        return self._request("GET", f"{BASE}/disciplinary-actions/{action_id}", headers=headers)

    def acknowledge_disciplinary_action(self, action_id, headers):
        return self._request(
            "POST", f"{BASE}/disciplinary-actions/{action_id}/acknowledge", {}, headers
        )

    def adjudicate_disciplinary_action(self, action_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/disciplinary-actions/{action_id}/adjudicate", payload, headers
        )

    def resolve_disciplinary_action(self, action_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/disciplinary-actions/{action_id}/resolve", payload, headers
        )

    # --- Credential Packets ---
    def create_credential_packet(self, payload, headers):
        return self._request("POST", f"{BASE}/credential-packets", payload, headers)

    def list_credential_packets(self, headers, params=None):
        return self._request("GET", f"{BASE}/credential-packets", headers=headers, params=params)

    def get_credential_packet(self, packet_id, headers):
        return self._request("GET", f"{BASE}/credential-packets/{packet_id}", headers=headers)

    def submit_packet(self, packet_id, headers):
        return self._request("POST", f"{BASE}/credential-packets/{packet_id}/submit", {}, headers)

    def start_packet_review(self, packet_id, headers):
        return self._request(
            "POST", f"{BASE}/credential-packets/{packet_id}/start-review", {}, headers
        )

    def approve_packet(self, packet_id, headers):
        return self._request("POST", f"{BASE}/credential-packets/{packet_id}/approve", {}, headers)

    def reject_packet(self, packet_id, payload, headers):
        return self._request("POST", f"{BASE}/credential-packets/{packet_id}/reject", payload, headers)

    def resubmit_packet(self, packet_id, headers):
        return self._request(
            "POST", f"{BASE}/credential-packets/{packet_id}/resubmit", {}, headers
        )

    # --- Packet Items ---
    def list_packet_items(self, headers, params=None):
        return self._request("GET", f"{BASE}/packet-items", headers=headers, params=params)

    def get_packet_item(self, item_id, headers):
        return self._request("GET", f"{BASE}/packet-items/{item_id}", headers=headers)

    def submit_item_evidence(self, item_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/packet-items/{item_id}/submit-evidence", payload, headers
        )

    def verify_packet_item(self, item_id, headers):
        return self._request("POST", f"{BASE}/packet-items/{item_id}/verify", {}, headers)

    def waive_packet_item(self, item_id, payload, headers):
        return self._request("POST", f"{BASE}/packet-items/{item_id}/waive", payload, headers)

    # --- Competency Requirements & Completions ---
    def create_competency_requirement(self, payload, headers):
        return self._request("POST", f"{BASE}/competency-requirements", payload, headers)

    def list_competency_requirements(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/competency-requirements", headers=headers, params=params
        )

    def get_competency_requirement(self, req_id, headers):
        return self._request("GET", f"{BASE}/competency-requirements/{req_id}", headers=headers)

    def create_competency_completion(self, payload, headers):
        return self._request("POST", f"{BASE}/competency-completions", payload, headers)

    def list_competency_completions(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/competency-completions", headers=headers, params=params
        )

    def get_competency_completion(self, completion_id, headers):
        return self._request(
            "GET", f"{BASE}/competency-completions/{completion_id}", headers=headers
        )

    # --- Units ---
    def create_unit(self, payload, headers):
        return self._request("POST", f"{BASE}/units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", f"{BASE}/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"{BASE}/units/{unit_id}", headers=headers)

    # --- Shift Assignments ---
    def create_shift_assignment(self, payload, headers):
        return self._request("POST", f"{BASE}/shift-assignments", payload, headers)

    def list_shift_assignments(self, headers, params=None):
        return self._request("GET", f"{BASE}/shift-assignments", headers=headers, params=params)

    def get_shift_assignment(self, shift_id, headers):
        return self._request("GET", f"{BASE}/shift-assignments/{shift_id}", headers=headers)

    def start_shift(self, shift_id, headers):
        return self._request("POST", f"{BASE}/shift-assignments/{shift_id}/start", {}, headers)

    def complete_shift(self, shift_id, headers):
        return self._request("POST", f"{BASE}/shift-assignments/{shift_id}/complete", {}, headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"{BASE}/shift-assignments/{shift_id}/cancel", {}, headers)

    # --- Competency Sessions & Bookings ---
    def create_competency_session(self, payload, headers):
        return self._request("POST", f"{BASE}/competency-sessions", payload, headers)

    def list_competency_sessions(self, headers, params=None):
        return self._request("GET", f"{BASE}/competency-sessions", headers=headers, params=params)

    def get_competency_session(self, session_id, headers):
        return self._request("GET", f"{BASE}/competency-sessions/{session_id}", headers=headers)

    def book_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/competency-sessions/{session_id}/bookings", payload, headers
        )

    def list_session_bookings(self, headers, params=None):
        return self._request("GET", f"{BASE}/session-bookings", headers=headers, params=params)

    def get_session_booking(self, booking_id, headers):
        return self._request("GET", f"{BASE}/session-bookings/{booking_id}", headers=headers)

    def complete_session_booking(self, booking_id, headers):
        return self._request(
            "POST", f"{BASE}/session-bookings/{booking_id}/complete", {}, headers
        )

    def delete_session_booking(self, booking_id, headers):
        return self._request("DELETE", f"{BASE}/session-bookings/{booking_id}", headers=headers)

    # --- Privilege Evaluations ---
    def create_privilege_evaluation(self, payload, headers):
        return self._request("POST", f"{BASE}/privilege-evaluations", payload, headers)

    def list_privilege_evaluations(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/privilege-evaluations", headers=headers, params=params
        )

    def get_privilege_evaluation(self, eval_id, headers):
        return self._request("GET", f"{BASE}/privilege-evaluations/{eval_id}", headers=headers)

    # --- Audit Runs & Findings ---
    def create_audit_run(self, payload, headers):
        return self._request("POST", f"{BASE}/audit-runs", payload, headers)

    def list_audit_runs(self, headers, params=None):
        return self._request("GET", f"{BASE}/audit-runs", headers=headers, params=params)

    def get_audit_run(self, run_id, headers):
        return self._request("GET", f"{BASE}/audit-runs/{run_id}", headers=headers)

    def begin_audit_fieldwork(self, run_id, headers):
        return self._request("POST", f"{BASE}/audit-runs/{run_id}/begin-fieldwork", {}, headers)

    def issue_audit_findings(self, run_id, headers):
        return self._request("POST", f"{BASE}/audit-runs/{run_id}/issue-findings", {}, headers)

    def close_audit_run(self, run_id, headers):
        return self._request("POST", f"{BASE}/audit-runs/{run_id}/close", {}, headers)

    def list_audit_findings(self, headers, params=None):
        return self._request("GET", f"{BASE}/audit-findings", headers=headers, params=params)

    def get_audit_finding(self, finding_id, headers):
        return self._request("GET", f"{BASE}/audit-findings/{finding_id}", headers=headers)

    def remediate_audit_finding(self, finding_id, headers):
        return self._request("POST", f"{BASE}/audit-findings/{finding_id}/remediate", {}, headers)

    def accept_risk_audit_finding(self, finding_id, headers):
        return self._request("POST", f"{BASE}/audit-findings/{finding_id}/accept-risk", {}, headers)

    # --- Monitoring & Ops ---
    def get_expiry_report(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/monitoring/expiry-report", headers=headers, params=params
        )

    def set_logical_clock(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    def run_expiry_sweep(self, headers):
        return self._request("POST", f"{BASE}/_ops/expiry-sweep", {}, headers)


api_client = ApiClient()
