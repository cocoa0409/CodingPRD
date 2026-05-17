"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the inherited _request() handles HTTP
plumbing. Headers are passed explicitly because PRD §2.1 requires both
X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Patient - PRD §3.1 / §4.
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

    def get_next_due(self, patient_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/patients/{patient_id}/next-due", headers=headers,
        )

    # =======================================================================
    # VaccineProduct - PRD §3.2 / §4.
    # =======================================================================
    def create_vaccine_product(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", "/vaccine-products", payload, headers)

    def get_vaccine_product(self, product_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET", f"/vaccine-products/{product_id}", headers=headers,
        )

    def list_vaccine_products(self, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/vaccine-products", headers=headers, params=params,
        )

    # =======================================================================
    # VaccineLot - PRD §3.2 / §3.5 / §4.
    # =======================================================================
    def create_vaccine_lot(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/vaccine-lots", payload, headers)

    def get_vaccine_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/vaccine-lots/{lot_id}", headers=headers,
        )

    def recall_vaccine_lot(self, lot_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/vaccine-lots/{lot_id}/recall", payload, headers,
        )

    # =======================================================================
    # AdministeredDose - PRD §3.3 / §4.
    # =======================================================================
    def schedule_dose(self, patient_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/patients/{patient_id}/doses", payload, headers,
        )

    def administer_dose(self, patient_id: str, dose_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/patients/{patient_id}/doses/{dose_id}/administer",
            payload, headers,
        )

    def cancel_dose(self, patient_id: str, dose_id: str,
                    headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/patients/{patient_id}/doses/{dose_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def invalidate_dose(self, patient_id: str, dose_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/patients/{patient_id}/doses/{dose_id}/invalidate",
            payload, headers,
        )

    def list_doses(self, patient_id: str, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/patients/{patient_id}/doses",
            headers=headers, params=params,
        )

    def get_dose(self, patient_id: str, dose_id: str,
                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/patients/{patient_id}/doses/{dose_id}",
            headers=headers,
        )

    # =======================================================================
    # AllergyRecord - PRD §3.4 / §4.
    # =======================================================================
    def create_allergy(self, patient_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/patients/{patient_id}/allergies", payload, headers,
        )

    def list_allergies(self, patient_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/patients/{patient_id}/allergies",
            headers=headers, params=params,
        )

    # =======================================================================
    # AdverseEvent - PRD §3.9 / §4.
    # =======================================================================
    def create_adverse_event(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", "/adverse-events", payload, headers)

    def start_review(self, adverse_event_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/adverse-events/{adverse_event_id}/start-review",
            payload if payload is not None else {}, headers,
        )

    def conclude_review(self, adverse_event_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/adverse-events/{adverse_event_id}/conclude-review",
            payload, headers,
        )

    def submit_vaers(self, adverse_event_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/adverse-events/{adverse_event_id}/submit-vaers",
            payload if payload is not None else {}, headers,
        )

    def get_adverse_event(self, adverse_event_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/adverse-events/{adverse_event_id}", headers=headers,
        )

    def list_adverse_events(self, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/adverse-events", headers=headers, params=params,
        )

    # =======================================================================
    # AntigenScheduleRule - PRD §3.7 / §4.
    # =======================================================================
    def create_antigen_schedule_rule(self, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", "/antigen-schedule-rules", payload, headers,
        )

    def list_antigen_schedule_rules(self, headers: Dict[str, str],
                                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/antigen-schedule-rules",
            headers=headers, params=params,
        )

    # =======================================================================
    # SchoolEnrollmentCertificate - PRD §3.8 / §4.
    # =======================================================================
    def create_certificate(self, patient_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/patients/{patient_id}/certificates",
            payload, headers,
        )

    def issue_certificate(self, patient_id: str, cert_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/patients/{patient_id}/certificates/{cert_id}/issue",
            payload if payload is not None else {}, headers,
        )

    def revoke_certificate(self, patient_id: str, cert_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/patients/{patient_id}/certificates/{cert_id}/revoke",
            payload if payload is not None else {}, headers,
        )

    def list_certificates(self, patient_id: str, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/patients/{patient_id}/certificates",
            headers=headers, params=params,
        )

    # =======================================================================
    # ProviderOrganization - PRD §3.2 / §3.6 / §4.
    # =======================================================================
    def create_provider_organization(self, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", "/provider-organizations", payload, headers,
        )

    def get_provider_organization(self, provider_org_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "GET", f"/provider-organizations/{provider_org_id}",
            headers=headers,
        )

    def suspend_provider_organization(self, provider_org_id: str,
                                      headers: Dict[str, str],
                                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/provider-organizations/{provider_org_id}/suspend",
            payload if payload is not None else {}, headers,
        )

    def reinstate_provider_organization(self, provider_org_id: str,
                                        headers: Dict[str, str],
                                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/provider-organizations/{provider_org_id}/reinstate",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Test-only endpoints - PRD §2.10 / §4.
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def vaers_ack(self, payload: Dict[str, Any],
                  headers: Dict[str, str]):
        return self._request(
            "POST", "/_events/vaers-ack", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
