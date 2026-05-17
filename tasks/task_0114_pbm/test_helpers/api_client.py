"""API client: one method per endpoint defined in PRD §4.

Subclass of ``GenericApiClient`` — the base ``_request()`` method
handles HTTP plumbing. Tests pass headers explicitly because PRD §2.1
requires ``X-User-ID`` and ``X-User-Role`` on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Plan — PRD §4 / §3.1
    # =======================================================================
    def create_plan(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/pbm/plans", payload, headers)

    def list_plans(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pbm/plans", headers=headers, params=params,
        )

    def get_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/pbm/plans/{plan_id}", headers=headers,
        )

    def patch_plan(self, plan_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/pbm/plans/{plan_id}", payload, headers,
        )

    # =======================================================================
    # Drug — PRD §4 / §3.1
    # =======================================================================
    def create_drug(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/pbm/drugs", payload, headers)

    def list_drugs(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pbm/drugs", headers=headers, params=params,
        )

    def get_drug(self, drug_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/pbm/drugs/{drug_id}", headers=headers,
        )

    # =======================================================================
    # Member — PRD §4 / §3.2
    # =======================================================================
    def create_member(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/pbm/members", payload, headers)

    def list_members(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pbm/members", headers=headers, params=params,
        )

    def get_member(self, member_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/pbm/members/{member_id}", headers=headers,
        )

    def suspend_member(self, member_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/pbm/members/{member_id}/suspend",
            payload, headers,
        )

    # =======================================================================
    # FormularyEntry — PRD §4 / §3.1
    # =======================================================================
    def create_formulary_entry(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", "/pbm/formulary-entries", payload, headers,
        )

    def list_formulary_entries(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pbm/formulary-entries",
            headers=headers, params=params,
        )

    def patch_formulary_entry(self, entry_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/pbm/formulary-entries/{entry_id}",
            payload, headers,
        )

    # =======================================================================
    # PriorAuthorization — PRD §4 / §3.3
    # =======================================================================
    def create_prior_authorization(self, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", "/pbm/prior-authorizations", payload, headers,
        )

    def list_prior_authorizations(self, headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pbm/prior-authorizations",
            headers=headers, params=params,
        )

    def get_prior_authorization(self, pa_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "GET", f"/pbm/prior-authorizations/{pa_id}",
            headers=headers,
        )

    def submit_prior_authorization(self, pa_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/pbm/prior-authorizations/{pa_id}/submit",
            payload, headers,
        )

    def approve_prior_authorization(self, pa_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/pbm/prior-authorizations/{pa_id}/approve",
            payload, headers,
        )

    def deny_prior_authorization(self, pa_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/pbm/prior-authorizations/{pa_id}/deny",
            payload, headers,
        )

    def request_info_prior_authorization(self, pa_id: str,
                                         payload: Dict[str, Any],
                                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pbm/prior-authorizations/{pa_id}/request-info",
            payload, headers,
        )

    def resubmit_prior_authorization(self, pa_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/pbm/prior-authorizations/{pa_id}/resubmit",
            payload, headers,
        )

    def revoke_prior_authorization(self, pa_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/pbm/prior-authorizations/{pa_id}/revoke",
            payload, headers,
        )

    # =======================================================================
    # Claim — PRD §4 / §3.4 / §3.5 / §3.6 / §3.7
    # =======================================================================
    def create_claim(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/pbm/claims", payload, headers)

    def list_claims(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pbm/claims", headers=headers, params=params,
        )

    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/pbm/claims/{claim_id}", headers=headers,
        )

    def adjudicate_claim(self, claim_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/pbm/claims/{claim_id}/adjudicate",
            payload, headers,
        )

    def pay_claim(self, claim_id: str, payload: Dict[str, Any],
                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/pbm/claims/{claim_id}/pay", payload, headers,
        )

    def reverse_claim(self, claim_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/pbm/claims/{claim_id}/reverse",
            payload, headers,
        )

    # =======================================================================
    # CopayCard — PRD §4 / §3.8
    # =======================================================================
    def create_copay_card(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", "/pbm/copay-cards", payload, headers,
        )

    def get_copay_card(self, card_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/pbm/copay-cards/{card_id}", headers=headers,
        )

    def terminate_copay_card(self, card_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/pbm/copay-cards/{card_id}/terminate",
            payload, headers,
        )

    # =======================================================================
    # RebateAgreement — PRD §4 / §3.6
    # =======================================================================
    def create_rebate_agreement(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/pbm/rebate-agreements", payload, headers,
        )

    def list_rebate_agreements(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pbm/rebate-agreements",
            headers=headers, params=params,
        )

    # =======================================================================
    # LedgerEntry (read-only) — PRD §4 / §3.9
    # =======================================================================
    def list_ledger_entries(self, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pbm/ledger-entries",
            headers=headers, params=params,
        )

    # =======================================================================
    # Simulated clock — PRD §4 / §2.11
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
