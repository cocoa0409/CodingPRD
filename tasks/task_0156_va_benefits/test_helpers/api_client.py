"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request (except the two test-only
driver endpoints, which still accept the headers but only PlatformAdmin
is authorized to invoke them).

Paths are verbatim from PRD §4 endpoint table.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Veterans — PRD §3.1, §4
    # =======================================================================
    def create_veteran(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/veterans", payload, headers)

    def get_veteran(self, veteran_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/veterans/{veteran_id}", headers=headers,
        )

    def patch_veteran(self, veteran_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/veterans/{veteran_id}", payload, headers,
        )

    def get_entitlement_projection(self, veteran_id: str,
                                   headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/veterans/{veteran_id}/entitlement-projection",
            headers=headers, params=params,
        )

    # =======================================================================
    # Dependents — PRD §3.2, §4
    # =======================================================================
    def create_dependent(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/dependents", payload, headers)

    def patch_dependent(self, dependent_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/dependents/{dependent_id}", payload, headers,
        )

    def delete_dependent(self, dependent_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/dependents/{dependent_id}", headers=headers,
        )

    def list_dependents(self, veteran_id: str, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/veterans/{veteran_id}/dependents",
            headers=headers, params=params,
        )

    # =======================================================================
    # Claims — PRD §3.3, §4
    # =======================================================================
    def create_claim(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/claims", payload, headers)

    def start_review_claim(self, claim_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/claims/{claim_id}/start-review",
            payload, headers,
        )

    def grant_claim(self, claim_id: str,
                    payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/claims/{claim_id}/grant", payload, headers,
        )

    def deny_claim(self, claim_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/claims/{claim_id}/deny", payload, headers,
        )

    def appeal_claim(self, claim_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/claims/{claim_id}/appeal", payload, headers,
        )

    def reopen_claim(self, claim_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/claims/{claim_id}/reopen", payload, headers,
        )

    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/claims/{claim_id}", headers=headers,
        )

    def list_claims(self, veteran_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/veterans/{veteran_id}/claims",
            headers=headers, params=params,
        )

    # =======================================================================
    # Schools — PRD §3.5, §4
    # =======================================================================
    def create_school(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/schools", payload, headers)

    def get_school(self, school_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/schools/{school_id}", headers=headers,
        )

    # =======================================================================
    # Enrollments — PRD §3.6–3.10, §4
    # =======================================================================
    def create_enrollment(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/enrollments", payload, headers)

    def certify_enrollment(self, enrollment_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/certify",
            payload, headers,
        )

    def cancel_enrollment(self, enrollment_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/cancel",
            payload, headers,
        )

    def complete_enrollment(self, enrollment_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/complete",
            payload, headers,
        )

    def withdraw_enrollment(self, enrollment_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/withdraw",
            payload, headers,
        )

    def create_housing_payment(self, enrollment_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/housing-payments",
            payload, headers,
        )

    def get_enrollment(self, enrollment_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}", headers=headers,
        )

    def get_yellow_ribbon(self, enrollment_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/yellow-ribbon",
            headers=headers,
        )

    def list_housing_payments(self, enrollment_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/housing-payments",
            headers=headers, params=params,
        )

    # =======================================================================
    # Voc Rehab plans — PRD §3.11, §4
    # =======================================================================
    def create_voc_rehab_plan(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/voc-rehab-plans", payload, headers)

    def approve_voc_rehab_plan(self, plan_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/voc-rehab-plans/{plan_id}/approve",
            payload, headers,
        )

    def start_voc_rehab_plan(self, plan_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/voc-rehab-plans/{plan_id}/start",
            payload, headers,
        )

    def suspend_voc_rehab_plan(self, plan_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/voc-rehab-plans/{plan_id}/suspend",
            payload, headers,
        )

    def resume_voc_rehab_plan(self, plan_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/voc-rehab-plans/{plan_id}/resume",
            payload, headers,
        )

    def complete_voc_rehab_plan(self, plan_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/voc-rehab-plans/{plan_id}/complete",
            payload, headers,
        )

    def get_voc_rehab_plan(self, plan_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/voc-rehab-plans/{plan_id}", headers=headers,
        )

    # =======================================================================
    # Payment ledger — PRD §3.12, §4
    # =======================================================================
    def list_ledger(self, veteran_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/veterans/{veteran_id}/ledger",
            headers=headers, params=params,
        )

    # =======================================================================
    # Test driver endpoints — PRD §3.8, §4
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", "/_sweep/run", payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
