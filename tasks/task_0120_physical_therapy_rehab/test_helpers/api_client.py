"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the inherited _request() handles HTTP
plumbing. Headers are passed explicitly because PRD §2.1 requires both
X-User-ID and X-User-Role on every request (except GET /_health).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Therapists — PRD §3.1 / §4.
    # =======================================================================
    def create_therapist(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/therapists", payload, headers)

    def get_therapist(self, therapist_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/therapists/{therapist_id}", headers=headers,
        )

    def list_therapists(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/therapists", headers=headers, params=params,
        )

    # =======================================================================
    # Patients — PRD §3.1 / §4.
    # =======================================================================
    def create_patient(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/patients/{patient_id}", headers=headers,
        )

    def get_patient_cap_status(self, patient_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET", f"/patients/{patient_id}/cap-status", headers=headers,
        )

    # =======================================================================
    # Veteran Referrals — PRD §3.1 / §4.
    # =======================================================================
    def create_veteran_referral(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/veteran-referrals", payload, headers,
        )

    def get_veteran_referral(self, referral_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/veteran-referrals/{referral_id}", headers=headers,
        )

    # =======================================================================
    # Episodes — PRD §3.2 / §4.
    # =======================================================================
    def create_episode(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/episodes", payload, headers)

    def get_episode(self, episode_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/episodes/{episode_id}", headers=headers,
        )

    def list_episodes(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/episodes", headers=headers, params=params,
        )

    def delete_episode(self, episode_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/episodes/{episode_id}", headers=headers,
        )

    # =======================================================================
    # Evaluations — PRD §3.2 / §4.
    # =======================================================================
    def create_evaluation(self, episode_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/episodes/{episode_id}/evaluations",
            payload, headers,
        )

    def finalize_evaluation(self, evaluation_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/evaluations/{evaluation_id}/finalize",
            payload if payload is not None else {}, headers,
        )

    def amend_evaluation(self, evaluation_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/evaluations/{evaluation_id}/amend",
            payload, headers,
        )

    # =======================================================================
    # Plan of Care — PRD §3.3 / §4.
    # =======================================================================
    def create_plan_of_care(self, episode_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/episodes/{episode_id}/plan-of-cares",
            payload, headers,
        )

    def certify_plan_of_care(self, poc_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/plan-of-cares/{poc_id}/certify",
            payload if payload is not None else {}, headers,
        )

    def revoke_plan_of_care(self, poc_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/plan-of-cares/{poc_id}/revoke",
            payload if payload is not None else {}, headers,
        )

    def get_plan_of_care(self, poc_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/plan-of-cares/{poc_id}", headers=headers,
        )

    # =======================================================================
    # Authorizations — PRD §3.4 / §4.
    # =======================================================================
    def create_authorization(self, episode_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/episodes/{episode_id}/authorizations",
            payload, headers,
        )

    def get_authorization(self, authorization_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/authorizations/{authorization_id}",
            headers=headers,
        )

    # =======================================================================
    # Visits — PRD §3.5 / §4.
    # =======================================================================
    def create_visit(self, episode_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/episodes/{episode_id}/visits", payload, headers,
        )

    def get_visit(self, visit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/visits/{visit_id}", headers=headers,
        )

    def list_visits_on_episode(self, episode_id: str,
                               headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/episodes/{episode_id}/visits",
            headers=headers, params=params,
        )

    def start_visit(self, visit_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/visits/{visit_id}/start",
            payload if payload is not None else {}, headers,
        )

    def sign_visit(self, visit_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/visits/{visit_id}/sign", payload, headers,
        )

    def submit_claim(self, visit_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/visits/{visit_id}/submit-claim",
            payload if payload is not None else {}, headers,
        )

    def cancel_visit(self, visit_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/visits/{visit_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Home Exercise Programs — PRD §3.7 / §4.
    # =======================================================================
    def create_home_exercise_program(self, episode_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/episodes/{episode_id}/home-exercise-programs",
            payload, headers,
        )

    def issue_home_exercise_program(self, hep_id: str,
                                    headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/home-exercise-programs/{hep_id}/issue",
            payload if payload is not None else {}, headers,
        )

    def acknowledge_home_exercise_program(self, hep_id: str,
                                          headers: Dict[str, str],
                                          payload: Optional[
                                              Dict[str, Any]] = None):
        return self._request(
            "POST", f"/home-exercise-programs/{hep_id}/acknowledge",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # MIPS — PRD §3.8 / §4.
    # =======================================================================
    def create_mips_measure(self, episode_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/episodes/{episode_id}/mips-measures",
            payload, headers,
        )

    def list_mips_measures(self, episode_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/episodes/{episode_id}/mips-measures",
            headers=headers, params=params,
        )

    # =======================================================================
    # Discharge — PRD §3.9 / §4.
    # =======================================================================
    def create_discharge_assessment(self, episode_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/episodes/{episode_id}/discharge-assessments",
            payload, headers,
        )

    def sign_discharge_assessment(self, discharge_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[
                                      Dict[str, Any]] = None):
        return self._request(
            "POST", f"/discharge-assessments/{discharge_id}/sign",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Test-only — PRD §3.10 / §4.
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
