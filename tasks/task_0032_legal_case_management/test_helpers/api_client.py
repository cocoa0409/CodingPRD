"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient. Every method delegates to ``_request`` and
returns the raw Response — tests pass headers explicitly because PRD §2.1
makes ``X-User-ID`` and ``X-User-Role`` mandatory for every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # Lawyers
    # =====================================================================
    def create_lawyer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/lawyers", payload, headers)

    def get_lawyer(self, lawyer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/lawyers/{lawyer_id}", headers=headers)

    # =====================================================================
    # Cases
    # =====================================================================
    def create_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def activate_case(self, case_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/cases/{case_id}/activate",
                             payload or {}, headers)

    def hold_case(self, case_id: str, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/cases/{case_id}/hold",
                             payload or {}, headers)

    def resume_case(self, case_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/cases/{case_id}/resume",
                             payload or {}, headers)

    def await_settlement(self, case_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/cases/{case_id}/await-settlement",
                             payload or {}, headers)

    def close_case(self, case_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/cases/{case_id}/close",
                             payload or {}, headers)

    # =====================================================================
    # Parties
    # =====================================================================
    def create_party(self, case_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", f"/cases/{case_id}/parties",
                             payload, headers)

    def list_parties(self, case_id: str, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/cases/{case_id}/parties",
                             headers=headers, params=params)

    def verify_party_identity(self, party_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/parties/{party_id}/verify-identity",
                             payload or {}, headers)

    # =====================================================================
    # Document templates
    # =====================================================================
    def create_template(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/document-templates", payload, headers)

    def list_templates(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/document-templates",
                             headers=headers, params=params)

    # =====================================================================
    # Document drafts
    # =====================================================================
    def create_draft(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/document-drafts", payload, headers)

    def get_draft(self, draft_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/document-drafts/{draft_id}",
                             headers=headers)

    def submit_draft_for_review(self, draft_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/document-drafts/{draft_id}/submit-for-review",
            payload or {}, headers,
        )

    def senior_pass(self, draft_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/document-drafts/{draft_id}/senior-pass",
            payload or {}, headers,
        )

    def request_revisions(self, draft_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/document-drafts/{draft_id}/request-revisions",
            payload or {}, headers,
        )

    def resume_drafting(self, draft_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/document-drafts/{draft_id}/resume-drafting",
            payload or {}, headers,
        )

    def partner_signoff(self, draft_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/document-drafts/{draft_id}/partner-signoff",
            payload or {}, headers,
        )

    def lock_draft(self, draft_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/document-drafts/{draft_id}/lock",
            payload or {}, headers,
        )

    # =====================================================================
    # Hearings
    # =====================================================================
    def create_hearing(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/hearings", payload, headers)

    def reschedule_hearing(self, hearing_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/hearings/{hearing_id}/reschedule",
            payload, headers,
        )

    def cancel_hearing(self, hearing_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/hearings/{hearing_id}/cancel",
            payload or {}, headers,
        )

    def complete_hearing(self, hearing_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/hearings/{hearing_id}/complete",
            payload or {}, headers,
        )

    def get_prep_tasks(self, hearing_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/hearings/{hearing_id}/prep-tasks",
                             headers=headers)

    def list_case_hearings(self, case_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/cases/{case_id}/hearings",
                             headers=headers, params=params)

    # =====================================================================
    # Evidence
    # =====================================================================
    def create_evidence(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/evidence", payload, headers)

    def get_evidence(self, evidence_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/evidence/{evidence_id}",
                             headers=headers)

    def append_custody_event(self, evidence_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/evidence/{evidence_id}/custody-events",
            payload, headers,
        )

    def submit_evidence(self, evidence_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/evidence/{evidence_id}/submit",
            payload or {}, headers,
        )

    def exclude_evidence(self, evidence_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/evidence/{evidence_id}/exclude",
            payload or {}, headers,
        )

    def file_rebuttal(self, evidence_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/evidence/{evidence_id}/rebuttals",
            payload, headers,
        )

    def uphold_rebuttal(self, rebuttal_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/rebuttals/{rebuttal_id}/uphold",
            payload or {}, headers,
        )

    def dismiss_rebuttal(self, rebuttal_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/rebuttals/{rebuttal_id}/dismiss",
            payload or {}, headers,
        )

    # =====================================================================
    # Time entries & bills
    # =====================================================================
    def create_time_entry(self, case_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"/cases/{case_id}/time-entries",
                             payload, headers)

    def adjust_time_entry(self, time_entry_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/time-entries/{time_entry_id}/adjust",
            payload, headers,
        )

    def write_off_time_entry(self, time_entry_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/time-entries/{time_entry_id}/write-off",
            payload or {}, headers,
        )

    def get_time_entry_summary(self, case_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET", f"/cases/{case_id}/time-entries/summary",
            headers=headers,
        )

    def create_bill(self, case_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", f"/cases/{case_id}/bills",
                             payload, headers)

    def issue_bill(self, bill_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/bills/{bill_id}/issue",
                             payload or {}, headers)

    def mark_bill_settled(self, bill_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/bills/{bill_id}/mark-settled",
                             payload or {}, headers)

    def void_bill(self, bill_id: str, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/bills/{bill_id}/void",
                             payload or {}, headers)

    # =====================================================================
    # External event endpoints
    # =====================================================================
    def emit_payment(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/_events/payment-received",
                             payload, headers)

    def emit_signature(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/_events/document-signed",
                             payload, headers)

    def emit_court_filing(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/_events/court-filed",
                             payload, headers)

    # =====================================================================
    # Audit log
    # =====================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/audit-logs",
                             headers=headers, params=params)

    # =====================================================================
    # Test-driving (clock + sweep)
    # =====================================================================
    def advance_clock(self, target_timestamp: str,
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance",
                             {"target_timestamp": target_timestamp}, headers)

    def run_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run", {}, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
