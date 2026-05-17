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
    # Patient — PRD §4
    # =======================================================================
    def create_patient(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/patients/{patient_id}", headers=headers,
        )

    def list_patients(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/patients", headers=headers, params=params,
        )

    def patch_patient(self, patient_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/patients/{patient_id}", payload, headers,
        )

    # =======================================================================
    # Clinician — PRD §4
    # =======================================================================
    def create_clinician(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/clinicians", payload, headers)

    def get_clinician(self, clinician_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET", f"/clinicians/{clinician_id}", headers=headers,
        )

    def patch_clinician(self, clinician_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/clinicians/{clinician_id}", payload, headers,
        )

    def list_clinicians(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/clinicians", headers=headers, params=params,
        )

    # =======================================================================
    # OASIS — PRD §4
    # =======================================================================
    def create_oasis(self, patient_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/patients/{patient_id}/oasis", payload, headers,
        )

    def lock_oasis(self, patient_id: str, oasis_id: str,
                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/patients/{patient_id}/oasis/{oasis_id}/lock",
            {}, headers,
        )

    def get_oasis(self, patient_id: str, oasis_id: str,
                  headers: Dict[str, str]):
        return self._request(
            "GET", f"/patients/{patient_id}/oasis/{oasis_id}",
            headers=headers,
        )

    # =======================================================================
    # Episode — PRD §4
    # =======================================================================
    def create_episode(self, patient_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/patients/{patient_id}/episodes",
            payload, headers,
        )

    def get_episode(self, episode_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/episodes/{episode_id}", headers=headers,
        )

    def list_episodes(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/episodes", headers=headers, params=params,
        )

    def close_episode(self, episode_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/episodes/{episode_id}/close", {}, headers,
        )

    # =======================================================================
    # Visit — PRD §4
    # =======================================================================
    def create_visit(self, episode_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/episodes/{episode_id}/visits",
            payload, headers,
        )

    def list_visits(self, episode_id: str,
                    headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/episodes/{episode_id}/visits",
            headers=headers, params=params,
        )

    def get_visit(self, visit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/visits/{visit_id}", headers=headers,
        )

    def complete_visit(self, visit_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/visits/{visit_id}/complete", {}, headers,
        )

    def cancel_visit(self, visit_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/visits/{visit_id}/cancel", {}, headers,
        )

    # =======================================================================
    # Mileage — PRD §4
    # =======================================================================
    def create_mileage(self, visit_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/visits/{visit_id}/mileage", payload, headers,
        )

    def list_mileage(self, visit_id: str,
                     headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/visits/{visit_id}/mileage",
            headers=headers, params=params,
        )

    # =======================================================================
    # PDGMClaim — PRD §4
    # =======================================================================
    def get_claim(self, episode_id: str,
                  headers: Dict[str, str]):
        return self._request(
            "GET", f"/episodes/{episode_id}/claim", headers=headers,
        )

    # =======================================================================
    # Clock / Sweep — PRD §2.7 / §4
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)

    def sweep_expire_episodes(self, headers: Dict[str, str]):
        return self._request(
            "POST", "/_sweep/expire-episodes", {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
