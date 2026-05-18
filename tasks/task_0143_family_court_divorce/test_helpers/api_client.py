"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-Role and X-User-ID on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Clock — PRD §2.6 / §4
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)

    # =======================================================================
    # Cases — PRD §3.1 / §4
    # =======================================================================
    def create_case(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cases/{case_id}", headers=headers,
        )

    def list_cases(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/cases", headers=headers, params=params,
        )

    def answer_case(self, case_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/cases/{case_id}/answer",
            payload if payload is not None else {}, headers,
        )

    def default_case(self, case_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/cases/{case_id}/default",
            payload if payload is not None else {}, headers,
        )

    def start_mediation(self, case_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/cases/{case_id}/start-mediation",
            payload if payload is not None else {}, headers,
        )

    def issue_temp_order(self, case_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/issue-temp-order",
            payload, headers,
        )

    def issue_final_judgment(self, case_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/issue-final-judgment",
            payload, headers,
        )

    def dismiss_case(self, case_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/dismiss",
            payload, headers,
        )

    # =======================================================================
    # Parties — PRD §4 (read-only)
    # =======================================================================
    def list_parties(self, case_id: str, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/cases/{case_id}/parties",
            headers=headers, params=params,
        )

    def get_party(self, case_id: str, party_id: str,
                  headers: Dict[str, str]):
        return self._request(
            "GET", f"/cases/{case_id}/parties/{party_id}",
            headers=headers,
        )

    # =======================================================================
    # FinancialDisclosure — PRD §3.2 / §4
    # =======================================================================
    def create_disclosure(self, case_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/disclosures",
            payload, headers,
        )

    def patch_disclosure(self, case_id: str, disclosure_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/cases/{case_id}/disclosures/{disclosure_id}",
            payload, headers,
        )

    def submit_disclosure(self, case_id: str, disclosure_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/cases/{case_id}/disclosures/{disclosure_id}/submit",
            payload if payload is not None else {}, headers,
        )

    def accept_disclosure(self, case_id: str, disclosure_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/cases/{case_id}/disclosures/{disclosure_id}/accept",
            payload if payload is not None else {}, headers,
        )

    def reject_disclosure(self, case_id: str, disclosure_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cases/{case_id}/disclosures/{disclosure_id}/reject",
            payload, headers,
        )

    def list_disclosures(self, case_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/cases/{case_id}/disclosures",
            headers=headers, params=params,
        )

    def get_disclosure(self, case_id: str, disclosure_id: str,
                       headers: Dict[str, str]):
        # Not in §4 endpoint table, but the typical list+get pattern is
        # safe; tests do not rely on this if absent.
        return self._request(
            "GET", f"/cases/{case_id}/disclosures/{disclosure_id}",
            headers=headers,
        )

    # =======================================================================
    # ParentingPlan — PRD §3.3 / §4
    # =======================================================================
    def create_parenting_plan(self, case_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/parenting-plans",
            payload, headers,
        )

    def accept_parenting_plan(self, case_id: str, plan_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/cases/{case_id}/parenting-plans/{plan_id}/accept",
            payload if payload is not None else {}, headers,
        )

    def impose_parenting_plan(self, case_id: str, plan_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/cases/{case_id}/parenting-plans/{plan_id}/impose",
            payload if payload is not None else {}, headers,
        )

    def list_parenting_plans(self, case_id: str,
                             headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/cases/{case_id}/parenting-plans",
            headers=headers, params=params,
        )

    def get_parenting_plan(self, case_id: str, plan_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/cases/{case_id}/parenting-plans/{plan_id}",
            headers=headers,
        )

    # =======================================================================
    # MediationSession — PRD §3.4 / §4
    # =======================================================================
    def schedule_mediation_session(self, case_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/mediation-sessions",
            payload, headers,
        )

    def start_mediation_session(self, case_id: str, session_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cases/{case_id}/mediation-sessions/{session_id}/start",
            {}, headers,
        )

    def complete_mediation_session(self, case_id: str,
                                   session_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cases/{case_id}/mediation-sessions/{session_id}/complete",
            payload, headers,
        )

    def cancel_mediation_session(self, case_id: str, session_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cases/{case_id}/mediation-sessions/{session_id}/cancel",
            {}, headers,
        )

    def no_show_mediation_session(self, case_id: str,
                                  session_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cases/{case_id}/mediation-sessions/{session_id}/no-show",
            {}, headers,
        )

    def list_mediation_sessions(self, case_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/cases/{case_id}/mediation-sessions",
            headers=headers, params=params,
        )

    # =======================================================================
    # SupportOrder — PRD §3.5 / §4
    # =======================================================================
    def create_support_order(self, case_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/support-orders",
            payload, headers,
        )

    def get_support_order(self, case_id: str, order_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/cases/{case_id}/support-orders/{order_id}",
            headers=headers,
        )

    def terminate_support_order(self, case_id: str, order_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/cases/{case_id}/support-orders/{order_id}/terminate",
            payload, headers,
        )

    def list_support_orders(self, case_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/cases/{case_id}/support-orders",
            headers=headers, params=params,
        )

    # =======================================================================
    # TemporaryOrder — PRD §3.6 / §4
    # =======================================================================
    def create_temp_order(self, case_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/temp-orders",
            payload, headers,
        )

    def get_temp_order(self, case_id: str, temp_order_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/cases/{case_id}/temp-orders/{temp_order_id}",
            headers=headers,
        )

    # =======================================================================
    # FinalJudgment — PRD §3.6 / §4
    # =======================================================================
    def create_final_judgment(self, case_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/cases/{case_id}/final-judgments",
            payload, headers,
        )

    def get_final_judgment(self, case_id: str, judgment_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/cases/{case_id}/final-judgments/{judgment_id}",
            headers=headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
