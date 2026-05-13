"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
both X-User-Role and X-User-ID on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Rights-holders (PRD §3.5)
    # =======================================================================
    def create_rights_holder(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", "/royalty/rights-holders", payload, headers)

    def get_rights_holder(self, holder_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/royalty/rights-holders/{holder_id}", headers=headers,
        )

    def list_rights_holders(self, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/royalty/rights-holders", headers=headers, params=params,
        )

    def get_dispute_exposure(self, holder_id: str, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/royalty/rights-holders/{holder_id}/dispute-exposure",
            headers=headers, params=params,
        )

    def get_micro_balance(self, holder_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/royalty/rights-holders/{holder_id}/micro-balance",
            headers=headers,
        )

    # =======================================================================
    # Agency bindings (PRD §3.4)
    # =======================================================================
    def create_agency_binding(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/royalty/agency-bindings", payload, headers)

    def terminate_agency_binding(self, binding_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/agency-bindings/{binding_id}/terminate",
            payload or {}, headers,
        )

    # =======================================================================
    # Works (PRD §3.1, §3.2)
    # =======================================================================
    def create_work(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/royalty/works", payload, headers)

    def get_work(self, work_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/royalty/works/{work_id}", headers=headers)

    def list_works(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/royalty/works", headers=headers, params=params,
        )

    def submit_work(self, work_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/works/{work_id}/submit",
            payload or {}, headers,
        )

    def take_review_work(self, work_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/works/{work_id}/take-review",
            payload or {}, headers,
        )

    def approve_work(self, work_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/works/{work_id}/approve",
            payload or {}, headers,
        )

    def reject_work(self, work_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/royalty/works/{work_id}/reject",
            payload, headers,
        )

    def withdraw_work(self, work_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/works/{work_id}/withdraw",
            payload or {}, headers,
        )

    def return_to_draft_work(self, work_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/works/{work_id}/return-to-draft",
            payload or {}, headers,
        )

    # =======================================================================
    # Rights shares (PRD §3.3)
    # =======================================================================
    def create_share(self, work_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/royalty/works/{work_id}/shares", payload, headers,
        )

    def patch_share(self, work_id: str, share_id: str,
                    payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/royalty/works/{work_id}/shares/{share_id}",
            payload, headers,
        )

    def list_share_audit(self, work_id: str, share_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/royalty/works/{work_id}/shares/{share_id}/audit",
            headers=headers, params=params,
        )

    # =======================================================================
    # Playback (PRD §3.6)
    # =======================================================================
    def create_playback_batch(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/royalty/playback-batches", payload, headers,
        )

    def get_playback_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/royalty/playback-batches/{batch_id}", headers=headers,
        )

    def list_playback_events(self, batch_id: str, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/royalty/playback-batches/{batch_id}/events",
            headers=headers, params=params,
        )

    # =======================================================================
    # Distribution rules (PRD §3.7)
    # =======================================================================
    def create_distribution_rule(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", "/royalty/distribution-rules", payload, headers,
        )

    def list_distribution_rules(self, headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/royalty/distribution-rules",
            headers=headers, params=params,
        )

    # =======================================================================
    # Royalty pools (PRD §3.8, §3.9, §3.10)
    # =======================================================================
    def create_pool(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/royalty/pools", payload, headers)

    def patch_pool(self, pool_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/royalty/pools/{pool_id}", payload, headers,
        )

    def close_pool(self, pool_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/pools/{pool_id}/close",
            payload or {}, headers,
        )

    def finalize_pool(self, pool_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/pools/{pool_id}/finalize",
            payload or {}, headers,
        )

    def get_pool(self, pool_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/royalty/pools/{pool_id}", headers=headers,
        )

    def list_pool_distributions(self, pool_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/royalty/pools/{pool_id}/distributions",
            headers=headers, params=params,
        )

    def forfeit_distribution(self, distribution_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/distributions/{distribution_id}/forfeit",
            payload or {}, headers,
        )

    # =======================================================================
    # Disputes (PRD §3.11)
    # =======================================================================
    def create_dispute(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/royalty/disputes", payload, headers)

    def submit_evidence(self, dispute_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/royalty/disputes/{dispute_id}/submit-evidence",
            payload, headers,
        )

    def start_investigation(self, dispute_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/disputes/{dispute_id}/start-investigation",
            payload or {}, headers,
        )

    def advance_to_mediation(self, dispute_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/disputes/{dispute_id}/advance-to-mediation",
            payload or {}, headers,
        )

    def reopen_investigation(self, dispute_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/disputes/{dispute_id}/reopen-investigation",
            payload or {}, headers,
        )

    def advance_to_arbitration(self, dispute_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/disputes/{dispute_id}/advance-to-arbitration",
            payload or {}, headers,
        )

    def resolve_dispute(self, dispute_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/royalty/disputes/{dispute_id}/resolve",
            payload, headers,
        )

    def withdraw_dispute(self, dispute_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/disputes/{dispute_id}/withdraw",
            payload or {}, headers,
        )

    # =======================================================================
    # Payouts (PRD §3.12, §3.13)
    # =======================================================================
    def create_payout_batch(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", "/royalty/payout-batches", payload, headers,
        )

    def execute_payout_batch(self, batch_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/payout-batches/{batch_id}/execute",
            payload or {}, headers,
        )

    def get_payout_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/royalty/payout-batches/{batch_id}", headers=headers,
        )

    def list_batch_payments(self, batch_id: str, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/royalty/payout-batches/{batch_id}/payments",
            headers=headers, params=params,
        )

    def retry_payment(self, payment_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/royalty/payments/{payment_id}/retry",
            payload or {}, headers,
        )

    def abandon_payment(self, payment_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/royalty/payments/{payment_id}/abandon",
            payload, headers,
        )

    # =======================================================================
    # External sync / test-driving (PRD §3.13, §3.14)
    # =======================================================================
    def psp_callback(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", "/royalty/_events/psp-callback", payload, headers,
        )

    def list_external_sync(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/royalty/_events/external-sync",
            headers=headers, params=params,
        )

    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/royalty/_clock/advance", payload, headers,
        )

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/royalty/_sweep/run", payload or {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
