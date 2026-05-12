"""API client: one method per endpoint defined in the PRD §4.

PRD §2.1 requires X-User-ID and X-User-Role headers on every request, so
every method takes an explicit ``headers`` argument.

PRD §4: 'The base path for letters of credit is /letters-of-credit.
Resources reachable directly by id (presentations, examinations,
settlements, reimbursement claims, banks, applicants, beneficiaries,
swift messages, external events, the clock) are mounted at their own
top-level paths.'
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =====================================================================
    # Reference data — Bank / Applicant / Beneficiary
    # =====================================================================
    def create_bank(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/banks", payload, headers)

    def get_bank(self, bank_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/banks/{bank_id}", headers=headers)

    def create_applicant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/applicants", payload, headers)

    def create_beneficiary(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/beneficiaries", payload, headers)

    # =====================================================================
    # Letter of Credit
    # =====================================================================
    def create_lc(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/letters-of-credit", payload, headers)

    def get_lc(self, lc_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/letters-of-credit/{lc_id}", headers=headers)

    def list_lcs(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/letters-of-credit", headers=headers, params=params)

    def submit_lc(self, lc_id: str, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/letters-of-credit/{lc_id}/submit", payload or {}, headers,
        )

    def return_lc_to_applicant(self, lc_id: str, headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/letters-of-credit/{lc_id}/return-to-applicant",
            payload or {}, headers,
        )

    def issue_lc(self, lc_id: str, headers: Dict[str, str],
                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/letters-of-credit/{lc_id}/issue", payload or {}, headers,
        )

    def advise_lc(self, lc_id: str, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/letters-of-credit/{lc_id}/advise", payload or {}, headers,
        )

    def confirm_lc(self, lc_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/letters-of-credit/{lc_id}/confirm", payload or {}, headers,
        )

    def cancel_lc(self, lc_id: str, payload: Dict[str, Any],
                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/letters-of-credit/{lc_id}/cancel", payload, headers,
        )

    # =====================================================================
    # Amendments
    # =====================================================================
    def create_amendment(self, lc_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/letters-of-credit/{lc_id}/amendments", payload, headers,
        )

    def get_amendment(self, lc_id: str, amendment_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET", f"/letters-of-credit/{lc_id}/amendments/{amendment_id}",
            headers=headers,
        )

    def list_amendments(self, lc_id: str, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/letters-of-credit/{lc_id}/amendments",
            headers=headers, params=params,
        )

    def applicant_consent(self, lc_id: str, amendment_id: str,
                          payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/letters-of-credit/{lc_id}/amendments/{amendment_id}/applicant-consent",
            payload, headers,
        )

    def beneficiary_consent(self, lc_id: str, amendment_id: str,
                            payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/letters-of-credit/{lc_id}/amendments/{amendment_id}/beneficiary-consent",
            payload, headers,
        )

    def confirming_bank_consent(self, lc_id: str, amendment_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/letters-of-credit/{lc_id}/amendments/{amendment_id}/confirming-bank-consent",
            payload, headers,
        )

    def withdraw_amendment(self, lc_id: str, amendment_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/letters-of-credit/{lc_id}/amendments/{amendment_id}/withdraw",
            payload or {}, headers,
        )

    # =====================================================================
    # Presentation
    # =====================================================================
    def create_presentation(self, lc_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/letters-of-credit/{lc_id}/presentations", payload, headers,
        )

    def get_presentation(self, presentation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/presentations/{presentation_id}", headers=headers,
        )

    def list_presentations(self, lc_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/letters-of-credit/{lc_id}/presentations",
            headers=headers, params=params,
        )

    def attach_document(self, presentation_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/presentations/{presentation_id}/documents",
            payload, headers,
        )

    def start_examination(self, presentation_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/presentations/{presentation_id}/start-examination",
            payload, headers,
        )

    def primary_review(self, examination_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/examinations/{examination_id}/primary-review",
            payload, headers,
        )

    def cross_check(self, examination_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/examinations/{examination_id}/cross-check",
            payload, headers,
        )

    def reset_examination(self, examination_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/examinations/{examination_id}/reset",
            payload or {}, headers,
        )

    def finalize_examination(self, examination_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/examinations/{examination_id}/finalize",
            payload or {}, headers,
        )

    def get_examination(self, examination_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/examinations/{examination_id}", headers=headers,
        )

    def list_discrepancies(self, examination_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/examinations/{examination_id}/discrepancies",
            headers=headers, params=params,
        )

    # =====================================================================
    # Discrepancy / refusal flow
    # =====================================================================
    def applicant_decision(self, presentation_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/presentations/{presentation_id}/applicant-decision",
            payload, headers,
        )

    def refuse_presentation(self, presentation_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/presentations/{presentation_id}/refuse",
            payload, headers,
        )

    def applicant_override(self, presentation_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/presentations/{presentation_id}/applicant-override",
            payload or {}, headers,
        )

    def return_documents(self, presentation_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/presentations/{presentation_id}/return-documents",
            payload or {}, headers,
        )

    # =====================================================================
    # Settlement
    # =====================================================================
    def create_settlement(self, presentation_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/presentations/{presentation_id}/settlements",
            payload, headers,
        )

    def execute_sight(self, settlement_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/settlements/{settlement_id}/execute-sight",
            payload or {}, headers,
        )

    def record_acceptance(self, settlement_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/settlements/{settlement_id}/record-acceptance",
            payload or {}, headers,
        )

    def negotiation_advance(self, settlement_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/settlements/{settlement_id}/negotiation-advance",
            payload or {}, headers,
        )

    def compensate_settlement(self, settlement_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/settlements/{settlement_id}/compensate",
            payload, headers,
        )

    def get_settlement(self, settlement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/settlements/{settlement_id}", headers=headers,
        )

    # =====================================================================
    # Reimbursement claims
    # =====================================================================
    def get_reimbursement_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/reimbursement-claims/{claim_id}", headers=headers,
        )

    def honor_claim(self, claim_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/reimbursement-claims/{claim_id}/honor",
            payload or {}, headers,
        )

    def dispute_claim(self, claim_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/reimbursement-claims/{claim_id}/dispute",
            payload, headers,
        )

    def extinguish_claim(self, claim_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/reimbursement-claims/{claim_id}/extinguish",
            payload or {}, headers,
        )

    # =====================================================================
    # SWIFT messages / expiry alerts
    # =====================================================================
    def get_swift_message(self, message_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/swift-messages/{message_id}", headers=headers,
        )

    def list_swift_messages(self, lc_id: str, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/letters-of-credit/{lc_id}/swift-messages",
            headers=headers, params=params,
        )

    def list_expiry_alerts(self, lc_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/letters-of-credit/{lc_id}/expiry-alerts",
            headers=headers, params=params,
        )

    # =====================================================================
    # External events & audit log
    # =====================================================================
    def create_external_event(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/external-events", payload, headers)

    def get_external_event(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/external-events/{event_id}", headers=headers,
        )

    def list_audit_log(self, lc_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/letters-of-credit/{lc_id}/audit-log",
            headers=headers, params=params,
        )

    # =====================================================================
    # Clock (test driving)
    # =====================================================================
    def advance_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
