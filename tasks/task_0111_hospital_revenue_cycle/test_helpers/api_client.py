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

    # =======================================================================
    # InsurancePolicy — PRD §4
    # =======================================================================
    def create_policy(self, patient_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/patients/{patient_id}/policies",
            payload, headers,
        )

    def list_policies(self, patient_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/patients/{patient_id}/policies",
            headers=headers, params=params,
        )

    # =======================================================================
    # Encounter — PRD §4
    # =======================================================================
    def create_encounter(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/encounters", payload, headers)

    def get_encounter(self, encounter_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET", f"/encounters/{encounter_id}", headers=headers,
        )

    def list_encounters(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/encounters", headers=headers, params=params,
        )

    def patch_encounter(self, encounter_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/encounters/{encounter_id}", payload, headers,
        )

    def verify_eligibility(self, encounter_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/encounters/{encounter_id}/verify-eligibility",
            payload, headers,
        )

    def discharge_encounter(self, encounter_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/encounters/{encounter_id}/discharge", {}, headers,
        )

    # =======================================================================
    # ChargeItem — PRD §4
    # =======================================================================
    def create_charge(self, encounter_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/encounters/{encounter_id}/charges",
            payload, headers,
        )

    def post_charge(self, encounter_id: str, charge_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/encounters/{encounter_id}/charges/{charge_id}/post",
            {}, headers,
        )

    def void_charge(self, encounter_id: str, charge_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/encounters/{encounter_id}/charges/{charge_id}/void",
            {}, headers,
        )

    def list_charges(self, encounter_id: str, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/encounters/{encounter_id}/charges",
            headers=headers, params=params,
        )

    # =======================================================================
    # CodingRecord — PRD §4
    # =======================================================================
    def submit_coding(self, encounter_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/encounters/{encounter_id}/coding",
            payload, headers,
        )

    def get_coding(self, encounter_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/encounters/{encounter_id}/coding", headers=headers,
        )

    # =======================================================================
    # ClearanceDecision — PRD §4
    # =======================================================================
    def submit_clearance(self, encounter_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/encounters/{encounter_id}/clearance",
            payload, headers,
        )

    # =======================================================================
    # Billing — PRD §4
    # =======================================================================
    def issue_bill(self, encounter_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/encounters/{encounter_id}/issue-bill", {}, headers,
        )

    # =======================================================================
    # PatientPayment — PRD §4
    # =======================================================================
    def post_payment(self, encounter_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/encounters/{encounter_id}/payments",
            payload, headers,
        )

    def list_payments(self, encounter_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/encounters/{encounter_id}/payments",
            headers=headers, params=params,
        )

    # =======================================================================
    # BadDebtRecord — PRD §4
    # =======================================================================
    def write_off_encounter(self, encounter_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/encounters/{encounter_id}/write-off", {}, headers,
        )

    # =======================================================================
    # Clock — PRD §4 / §2.11
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
