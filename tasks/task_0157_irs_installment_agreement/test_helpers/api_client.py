"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request.

All paths are mounted under the /collections prefix (PRD §4 endpoint
table), plus the test-only /_clock/advance and /_sweep/run helpers.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Taxpayers — PRD §3.1, §4
    # ======================================================================
    def create_taxpayer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/collections/taxpayers",
                             payload, headers)

    def get_taxpayer(self, taxpayer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/collections/taxpayers/{taxpayer_id}",
            headers=headers,
        )

    def patch_taxpayer(self, taxpayer_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/collections/taxpayers/{taxpayer_id}",
            payload, headers,
        )

    def list_taxpayers(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/collections/taxpayers", headers=headers, params=params,
        )

    # ======================================================================
    # Tax Liabilities — PRD §3.1, §4
    # ======================================================================
    def create_tax_liability(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", "/collections/tax-liabilities", payload, headers,
        )

    def get_tax_liability(self, liability_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/collections/tax-liabilities/{liability_id}",
            headers=headers,
        )

    def list_tax_liabilities(self, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/collections/tax-liabilities",
            headers=headers, params=params,
        )

    # ======================================================================
    # Installment Agreements — PRD §3.4, §4
    # ======================================================================
    def create_installment_agreement(self, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", "/collections/installment-agreements", payload, headers,
        )

    def get_installment_agreement(self, agreement_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "GET", f"/collections/installment-agreements/{agreement_id}",
            headers=headers,
        )

    def activate_installment_agreement(self, agreement_id: str,
                                       headers: Dict[str, str],
                                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/collections/installment-agreements/{agreement_id}/activate",
            payload, headers,
        )

    def record_installment_payment(self, agreement_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/collections/installment-agreements/{agreement_id}/record-payment",
            payload, headers,
        )

    def terminate_installment_agreement(self, agreement_id: str,
                                        headers: Dict[str, str],
                                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/collections/installment-agreements/{agreement_id}/terminate",
            payload, headers,
        )

    def list_installment_agreements(self, headers: Dict[str, str],
                                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/collections/installment-agreements",
            headers=headers, params=params,
        )

    # ======================================================================
    # Payments — PRD §3.5, §4
    # ======================================================================
    def create_payment(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", "/collections/payments", payload, headers,
        )

    def get_payment(self, payment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/collections/payments/{payment_id}",
            headers=headers,
        )

    # ======================================================================
    # Offers in Compromise — PRD §3.8, §4
    # ======================================================================
    def create_offer_in_compromise(self, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", "/collections/offers-in-compromise", payload, headers,
        )

    def submit_offer_in_compromise(self, oic_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/collections/offers-in-compromise/{oic_id}/submit",
            payload, headers,
        )

    def take_up_offer_in_compromise(self, oic_id: str,
                                    headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/collections/offers-in-compromise/{oic_id}/take-up",
            payload, headers,
        )

    def decide_offer_in_compromise(self, oic_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/collections/offers-in-compromise/{oic_id}/decide",
            payload, headers,
        )

    def withdraw_offer_in_compromise(self, oic_id: str,
                                     headers: Dict[str, str],
                                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/collections/offers-in-compromise/{oic_id}/withdraw",
            payload, headers,
        )

    def get_offer_in_compromise(self, oic_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "GET", f"/collections/offers-in-compromise/{oic_id}",
            headers=headers,
        )

    def list_offers_in_compromise(self, headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/collections/offers-in-compromise",
            headers=headers, params=params,
        )

    # ======================================================================
    # Federal Tax Liens — PRD §3.7, §4
    # ======================================================================
    def create_lien(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", "/collections/liens", payload, headers,
        )

    def withdraw_lien(self, lien_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/collections/liens/{lien_id}/withdraw",
            payload, headers,
        )

    def get_lien(self, lien_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/collections/liens/{lien_id}", headers=headers,
        )

    def list_liens(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/collections/liens", headers=headers, params=params,
        )

    # ======================================================================
    # CNC — PRD §3.11, §4
    # ======================================================================
    def create_cnc_status(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", "/collections/cnc-statuses", payload, headers,
        )

    def reverse_cnc_status(self, cnc_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/collections/cnc-statuses/{cnc_id}/reverse",
            payload, headers,
        )

    def get_cnc_status(self, cnc_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/collections/cnc-statuses/{cnc_id}", headers=headers,
        )

    # ======================================================================
    # Reconsideration — PRD §3.10, §4
    # ======================================================================
    def create_reconsideration_request(self, payload: Dict[str, Any],
                                       headers: Dict[str, str]):
        return self._request(
            "POST", "/collections/reconsideration-requests",
            payload, headers,
        )

    def decide_reconsideration_request(self, request_id: str,
                                       payload: Dict[str, Any],
                                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/collections/reconsideration-requests/{request_id}/decide",
            payload, headers,
        )

    def get_reconsideration_request(self, request_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/collections/reconsideration-requests/{request_id}",
            headers=headers,
        )

    # ======================================================================
    # Clock / Sweep — PRD §3.2, §4
    # ======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
