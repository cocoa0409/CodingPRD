"""API client: one method per endpoint defined in the PRD.

Subclass of GenericApiClient — the base `_request()` handles HTTP
plumbing. All endpoints are mounted under `/transit` per PRD §4.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Rider — PRD §3.1
    # ======================================================================
    def create_rider(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/transit/riders", payload, headers)

    def get_rider(self, rider_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/transit/riders/{rider_id}", headers=headers,
        )

    # ======================================================================
    # Employer — PRD §3.1
    # ======================================================================
    def create_employer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/transit/employers", payload, headers)

    def suspend_employer(self, employer_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/transit/employers/{employer_id}/suspend",
            payload, headers,
        )

    # ======================================================================
    # FareCard — PRD §3.2
    # ======================================================================
    def create_card(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/transit/cards", payload, headers)

    def get_card(self, card_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/transit/cards/{card_id}", headers=headers,
        )

    def topup_card(self, card_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/transit/cards/{card_id}/top-up", payload, headers,
        )

    def suspend_card(self, card_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/transit/cards/{card_id}/suspend",
            payload, headers,
        )

    def reactivate_card(self, card_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/transit/cards/{card_id}/reactivate",
            payload, headers,
        )

    def close_card(self, card_id: str,
                   headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/transit/cards/{card_id}/close",
            payload, headers,
        )

    # ======================================================================
    # ReducedFareCertificate — PRD §3.2
    # ======================================================================
    def create_reduced_fare_certificate(self, payload: Dict[str, Any],
                                        headers: Dict[str, str]):
        return self._request(
            "POST", "/transit/reduced-fare-certificates", payload, headers,
        )

    def approve_reduced_fare_certificate(self, cert_id: str,
                                         headers: Dict[str, str],
                                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/transit/reduced-fare-certificates/{cert_id}/approve",
            payload, headers,
        )

    def revoke_reduced_fare_certificate(self, cert_id: str,
                                        headers: Dict[str, str],
                                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/transit/reduced-fare-certificates/{cert_id}/revoke",
            payload, headers,
        )

    # ======================================================================
    # LowIncomeVerification — PRD §3.3
    # ======================================================================
    def create_low_income_verification(self, payload: Dict[str, Any],
                                       headers: Dict[str, str]):
        return self._request(
            "POST", "/transit/low-income-verifications", payload, headers,
        )

    def approve_low_income_verification(self, verif_id: str,
                                        payload: Dict[str, Any],
                                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/transit/low-income-verifications/{verif_id}/approve",
            payload, headers,
        )

    # ======================================================================
    # MobilePaymentToken — PRD §3.4
    # ======================================================================
    def create_mobile_token(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", "/transit/mobile-tokens", payload, headers,
        )

    def revoke_mobile_token(self, token_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/transit/mobile-tokens/{token_id}/revoke",
            payload, headers,
        )

    # ======================================================================
    # Trip — PRD §3.5, §3.6
    # ======================================================================
    def create_trip(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/transit/trips", payload, headers)

    def get_trip(self, trip_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/transit/trips/{trip_id}", headers=headers,
        )

    def list_trips(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/transit/trips", headers=headers, params=params,
        )

    def tap_out(self, trip_id: str, payload: Dict[str, Any],
                headers: Dict[str, str]):
        return self._request(
            "POST", f"/transit/trips/{trip_id}/tap-out", payload, headers,
        )

    # ======================================================================
    # FareCapPeriod — PRD §2.9
    # ======================================================================
    def list_cap_periods(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/transit/cap-periods", headers=headers, params=params,
        )

    # ======================================================================
    # CommuterBenefitAccount + FSAContribution — PRD §3.9
    # ======================================================================
    def create_fsa_account(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", "/transit/fsa-accounts", payload, headers,
        )

    def create_fsa_contribution(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/transit/fsa-contributions", payload, headers,
        )

    def reverse_fsa_contribution(self, contrib_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/transit/fsa-contributions/{contrib_id}/reverse",
            payload, headers,
        )

    # ======================================================================
    # Dispute — PRD §3.7
    # ======================================================================
    def create_dispute(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/transit/disputes", payload, headers)

    def claim_dispute(self, dispute_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/transit/disputes/{dispute_id}/claim",
            payload, headers,
        )

    def request_evidence_dispute(self, dispute_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/transit/disputes/{dispute_id}/request-evidence",
            payload, headers,
        )

    def resolve_dispute(self, dispute_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/transit/disputes/{dispute_id}/resolve",
            payload, headers,
        )

    # ======================================================================
    # Logical clock / sweeps — PRD §3.10
    # ======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/transit/_clock/advance", payload, headers,
        )

    def sweep_incomplete_trips(self, headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/transit/_sweep/incomplete-trips", payload, headers,
        )

    def sweep_settle(self, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/transit/_sweep/settle", payload, headers,
        )

    def sweep_low_income_expiry(self, headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/transit/_sweep/low-income-expiry", payload, headers,
        )


# Module-level singleton used by tests + fixtures.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
