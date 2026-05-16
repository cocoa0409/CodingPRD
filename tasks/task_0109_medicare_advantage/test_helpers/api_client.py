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
    # Beneficiary — PRD §4
    # =======================================================================
    def create_beneficiary(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/beneficiaries", payload, headers)

    def get_beneficiary(self, beneficiary_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/beneficiaries/{beneficiary_id}", headers=headers,
        )

    def list_beneficiaries(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/beneficiaries", headers=headers, params=params,
        )

    def mark_beneficiary_deceased(self, beneficiary_id: str,
                                  payload: Optional[Dict[str, Any]],
                                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/beneficiaries/{beneficiary_id}/mark-deceased",
            payload if payload is not None else {},
            headers,
        )

    # =======================================================================
    # Plan — PRD §4
    # =======================================================================
    def create_plan(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/plans/{plan_id}", headers=headers,
        )

    def list_plans(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/plans", headers=headers, params=params,
        )

    def publish_star_rating(self, plan_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/plans/{plan_id}/star-ratings", payload, headers,
        )

    # =======================================================================
    # EnrollmentPeriod — PRD §4
    # =======================================================================
    def create_enrollment_period(self, beneficiary_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/beneficiaries/{beneficiary_id}/enrollment-periods",
            payload, headers,
        )

    def list_enrollment_periods(self, beneficiary_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/beneficiaries/{beneficiary_id}/enrollment-periods",
            headers=headers, params=params,
        )

    # =======================================================================
    # Enrollment — PRD §4
    # =======================================================================
    def create_enrollment(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/enrollments", payload, headers)

    def activate_enrollment(self, enrollment_id: str,
                            payload: Optional[Dict[str, Any]],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/activate",
            payload if payload is not None else {}, headers,
        )

    def reject_enrollment(self, enrollment_id: str,
                          payload: Optional[Dict[str, Any]],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/reject",
            payload if payload is not None else {}, headers,
        )

    def terminate_enrollment(self, enrollment_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/terminate",
            payload, headers,
        )

    def transfer_enrollment(self, enrollment_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/transfer",
            payload, headers,
        )

    def get_enrollment(self, enrollment_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}", headers=headers,
        )

    def list_enrollments(self, beneficiary_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/beneficiaries/{beneficiary_id}/enrollments",
            headers=headers, params=params,
        )

    def get_cost_summary(self, enrollment_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/cost-summary",
            headers=headers,
        )

    # =======================================================================
    # LateEnrollmentPenalty — PRD §4
    # =======================================================================
    def get_late_enrollment_penalty(self, lep_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "GET", f"/late-enrollment-penalties/{lep_id}",
            headers=headers,
        )

    def list_late_enrollment_penalties(self, beneficiary_id: str,
                                       headers: Dict[str, str],
                                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/beneficiaries/{beneficiary_id}/late-enrollment-penalties",
            headers=headers, params=params,
        )

    # =======================================================================
    # MedigapPolicy — PRD §4
    # =======================================================================
    def create_medigap_policy(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/medigap-policies", payload, headers,
        )

    def evaluate_gi_medigap(self, policy_id: str,
                            payload: Optional[Dict[str, Any]],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/medigap-policies/{policy_id}/evaluate-gi",
            payload if payload is not None else {}, headers,
        )

    def begin_underwriting_medigap(self, policy_id: str,
                                   payload: Optional[Dict[str, Any]],
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/medigap-policies/{policy_id}/begin-underwriting",
            payload if payload is not None else {}, headers,
        )

    def revise_medigap_application(self, policy_id: str,
                                   payload: Optional[Dict[str, Any]],
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/medigap-policies/{policy_id}/revise-application",
            payload if payload is not None else {}, headers,
        )

    def issue_medigap(self, policy_id: str,
                      payload: Optional[Dict[str, Any]],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/medigap-policies/{policy_id}/issue",
            payload if payload is not None else {}, headers,
        )

    def deny_medigap(self, policy_id: str,
                     payload: Optional[Dict[str, Any]],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/medigap-policies/{policy_id}/deny",
            payload if payload is not None else {}, headers,
        )

    def cancel_medigap(self, policy_id: str,
                       payload: Optional[Dict[str, Any]],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/medigap-policies/{policy_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def get_medigap_policy(self, policy_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/medigap-policies/{policy_id}", headers=headers,
        )

    # =======================================================================
    # DrugClaim & DrugPhaseLedger — PRD §4
    # =======================================================================
    def create_drug_claim(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/drug-claims", payload, headers)

    def adjudicate_drug_claim(self, claim_id: str,
                              payload: Optional[Dict[str, Any]],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/drug-claims/{claim_id}/adjudicate",
            payload if payload is not None else {}, headers,
        )

    def reverse_drug_claim(self, claim_id: str,
                           payload: Optional[Dict[str, Any]],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/drug-claims/{claim_id}/reverse",
            payload if payload is not None else {}, headers,
        )

    def get_drug_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/drug-claims/{claim_id}", headers=headers,
        )

    def get_drug_phase_ledger(self, beneficiary_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/beneficiaries/{beneficiary_id}/drug-phase-ledger",
            headers=headers, params=params,
        )

    def get_drug_cost_estimate(self, beneficiary_id: str,
                               headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/beneficiaries/{beneficiary_id}/drug-cost-estimate",
            headers=headers, params=params,
        )

    # =======================================================================
    # Clock — PRD §4
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
