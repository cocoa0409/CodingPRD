"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Customers & wallet (PRD §3.1, §4)
    # =======================================================================
    def create_customer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/customers/{customer_id}", headers=headers,
        )

    def create_recharge(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/recharges", payload, headers)

    def get_recharge(self, recharge_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/recharges/{recharge_id}", headers=headers,
        )

    # =======================================================================
    # Evidence (PRD §3.2, §3.3, §4)
    # =======================================================================
    def create_evidence(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/evidences", payload, headers)

    def get_evidence(self, evidence_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/evidences/{evidence_id}", headers=headers,
        )

    def list_evidences(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/evidences", headers=headers, params=params,
        )

    def submit_evidence(self, evidence_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/evidences/{evidence_id}/submit",
            payload or {}, headers,
        )

    def resubmit_evidence(self, evidence_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/evidences/{evidence_id}/resubmit",
            payload or {}, headers,
        )

    # =======================================================================
    # Timestamp notarization (PRD §3.2, §4)
    # =======================================================================
    def create_timestamp_notarization(self, payload: Dict[str, Any],
                                      headers: Dict[str, str]):
        return self._request(
            "POST", "/timestamp-notarizations", payload, headers,
        )

    def get_timestamp_notarization(self, notarization_id: str,
                                   headers: Dict[str, str]):
        return self._request(
            "GET", f"/timestamp-notarizations/{notarization_id}",
            headers=headers,
        )

    def verify_timestamp_notarization(self, notarization_id: str,
                                      headers: Dict[str, str],
                                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/timestamp-notarizations/{notarization_id}/verify",
            payload or {}, headers,
        )

    # =======================================================================
    # Batch (PRD §3.5, §4)
    # =======================================================================
    def create_batch(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/batches", payload, headers)

    def get_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/batches/{batch_id}", headers=headers,
        )

    def submit_batch(self, batch_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/batches/{batch_id}/submit",
            payload or {}, headers,
        )

    def get_batch_proof(self, batch_id: str, evidence_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/batches/{batch_id}/proof/{evidence_id}",
            headers=headers,
        )

    # =======================================================================
    # Certificate (PRD §3.6, §4)
    # =======================================================================
    def create_certificate(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/certificates", payload, headers)

    def get_certificate(self, certificate_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/certificates/{certificate_id}", headers=headers,
        )

    def download_certificate(self, certificate_id: str,
                             headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/certificates/{certificate_id}/download",
            headers=headers, params=params,
        )

    def revoke_certificate(self, certificate_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/certificates/{certificate_id}/revoke",
            payload or {}, headers,
        )

    # =======================================================================
    # Verification (PRD §3.8, §4)
    # =======================================================================
    def create_verification(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/verifications", payload, headers)

    # =======================================================================
    # Judicial package (PRD §3.7, §4)
    # =======================================================================
    def create_judicial_package(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/judicial-packages", payload, headers,
        )

    def get_judicial_package(self, package_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/judicial-packages/{package_id}", headers=headers,
        )

    def seal_judicial_package(self, package_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/judicial-packages/{package_id}/seal",
            payload or {}, headers,
        )

    def deliver_judicial_package(self, package_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/judicial-packages/{package_id}/deliver",
            payload or {}, headers,
        )

    # =======================================================================
    # Invoice (PRD §3.9, §4)
    # =======================================================================
    def create_invoice(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/invoices/{invoice_id}", headers=headers,
        )

    # =======================================================================
    # Audit logs (PRD §2.12, §4)
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params,
        )

    # =======================================================================
    # Test-driving endpoints (PRD §3.10, §4)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def chain_confirm(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_chain/confirm", payload, headers)

    def chain_fail(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/_chain/fail", payload, headers)

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run", payload or {}, headers,
        )

    def deliver_payment_event(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/_events/payment", payload, headers,
        )

    def deliver_judicial_ack(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", "/_events/judicial-ack", payload, headers,
        )

    def deliver_notary_callback(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/_events/notary-callback", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
