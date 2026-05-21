"""API client: one method per endpoint defined in the PRD.

Subclass of GenericApiClient — the base `_request()` handles HTTP
plumbing. All endpoints are mounted under `/brokerages` (PRD §4).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Brokerage — PRD §3.1
    # ======================================================================
    def create_brokerage(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/brokerages", payload, headers)

    def get_brokerage(self, brokerage_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/brokerages/{brokerage_id}", headers=headers,
        )

    def clock_advance(self, brokerage_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/brokerages/{brokerage_id}/_clock/advance",
            payload, headers,
        )

    def sweep_expire_quotes(self, brokerage_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/brokerages/{brokerage_id}/_sweep/expire-quotes",
            payload, headers,
        )

    # ======================================================================
    # Shipper — PRD §3.2
    # ======================================================================
    def create_shipper(self, brokerage_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/brokerages/{brokerage_id}/shippers",
            payload, headers,
        )

    def list_shippers(self, brokerage_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/brokerages/{brokerage_id}/shippers",
            headers=headers, params=params,
        )

    def get_shipper(self, brokerage_id: str, shipper_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET", f"/brokerages/{brokerage_id}/shippers/{shipper_id}",
            headers=headers,
        )

    def suspend_shipper(self, brokerage_id: str, shipper_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/shippers/{shipper_id}/suspend",
            payload, headers,
        )

    # ======================================================================
    # Carrier — PRD §3.3
    # ======================================================================
    def create_carrier(self, brokerage_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/brokerages/{brokerage_id}/carriers",
            payload, headers,
        )

    def list_carriers(self, brokerage_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/brokerages/{brokerage_id}/carriers",
            headers=headers, params=params,
        )

    def get_carrier(self, brokerage_id: str, carrier_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET", f"/brokerages/{brokerage_id}/carriers/{carrier_id}",
            headers=headers,
        )

    def qualify_carrier(self, brokerage_id: str, carrier_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/carriers/{carrier_id}/qualify",
            payload, headers,
        )

    def suspend_carrier(self, brokerage_id: str, carrier_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/carriers/{carrier_id}/suspend",
            payload, headers,
        )

    def requalify_carrier(self, brokerage_id: str, carrier_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/carriers/{carrier_id}/requalify",
            payload, headers,
        )

    def revoke_carrier(self, brokerage_id: str, carrier_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/carriers/{carrier_id}/revoke",
            payload, headers,
        )

    # ======================================================================
    # RateContract — PRD §3.4
    # ======================================================================
    def create_rate_contract(self, brokerage_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/brokerages/{brokerage_id}/rate-contracts",
            payload, headers,
        )

    def list_rate_contracts(self, brokerage_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/brokerages/{brokerage_id}/rate-contracts",
            headers=headers, params=params,
        )

    def terminate_rate_contract(self, brokerage_id: str, contract_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/rate-contracts/{contract_id}/terminate",
            payload, headers,
        )

    # ======================================================================
    # QuoteRequest — PRD §3.5
    # ======================================================================
    def create_quote_request(self, brokerage_id: str, shipper_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/shippers/{shipper_id}/quote-requests",
            payload, headers,
        )

    def get_quote_request(self, brokerage_id: str, shipper_id: str,
                          quote_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/brokerages/{brokerage_id}/shippers/{shipper_id}/quote-requests/{quote_id}",
            headers=headers,
        )

    def quote_quote_request(self, brokerage_id: str, shipper_id: str,
                            quote_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/shippers/{shipper_id}/quote-requests/{quote_id}/quote",
            payload, headers,
        )

    def accept_quote_request(self, brokerage_id: str, shipper_id: str,
                             quote_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/shippers/{shipper_id}/quote-requests/{quote_id}/accept",
            payload, headers,
        )

    def reject_quote_request(self, brokerage_id: str, shipper_id: str,
                             quote_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/shippers/{shipper_id}/quote-requests/{quote_id}/reject",
            payload, headers,
        )

    # ======================================================================
    # Load — PRD §3.6
    # ======================================================================
    def create_load(self, brokerage_id: str, shipper_id: str,
                    payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/shippers/{shipper_id}/loads",
            payload, headers,
        )

    def get_load(self, brokerage_id: str, shipper_id: str, load_id: str,
                 headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/brokerages/{brokerage_id}/shippers/{shipper_id}/loads/{load_id}",
            headers=headers,
        )

    def carrier_accept_load(self, brokerage_id: str, shipper_id: str,
                            load_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/shippers/{shipper_id}/loads/{load_id}/carrier-accept",
            payload, headers,
        )

    def depart_load(self, brokerage_id: str, shipper_id: str,
                    load_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/shippers/{shipper_id}/loads/{load_id}/depart",
            payload, headers,
        )

    def deliver_load(self, brokerage_id: str, shipper_id: str,
                     load_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/shippers/{shipper_id}/loads/{load_id}/deliver",
            payload, headers,
        )

    def invoice_load(self, brokerage_id: str, shipper_id: str,
                     load_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/shippers/{shipper_id}/loads/{load_id}/invoice",
            payload, headers,
        )

    def cancel_load(self, brokerage_id: str, shipper_id: str,
                    load_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/shippers/{shipper_id}/loads/{load_id}/cancel",
            payload, headers,
        )

    # ======================================================================
    # AccessorialCharge — PRD §3.7
    # ======================================================================
    def create_accessorial_charge(self, brokerage_id: str, shipper_id: str,
                                  load_id: str, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/shippers/{shipper_id}/loads/{load_id}/accessorial-charges",
            payload, headers,
        )

    def approve_accessorial_charge(self, brokerage_id: str, charge_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/accessorial-charges/{charge_id}/approve",
            payload, headers,
        )

    def deny_accessorial_charge(self, brokerage_id: str, charge_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/accessorial-charges/{charge_id}/deny",
            payload, headers,
        )

    # ======================================================================
    # Invoice / Factoring — PRD §3.8, §3.10
    # ======================================================================
    def list_invoices(self, brokerage_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/brokerages/{brokerage_id}/invoices",
            headers=headers, params=params,
        )

    def get_invoice(self, brokerage_id: str, invoice_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET", f"/brokerages/{brokerage_id}/invoices/{invoice_id}",
            headers=headers,
        )

    def factor_invoice(self, brokerage_id: str, invoice_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/invoices/{invoice_id}/factor",
            payload, headers,
        )

    def write_off_invoice(self, brokerage_id: str, invoice_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/invoices/{invoice_id}/write-off",
            payload, headers,
        )

    # ======================================================================
    # DisputeClaim — PRD §3.9
    # ======================================================================
    def create_dispute_claim(self, brokerage_id: str, invoice_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/invoices/{invoice_id}/dispute-claims",
            payload, headers,
        )

    def get_dispute_claim(self, brokerage_id: str, claim_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/brokerages/{brokerage_id}/dispute-claims/{claim_id}",
            headers=headers,
        )

    def start_review_dispute_claim(self, brokerage_id: str, claim_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/dispute-claims/{claim_id}/start-review",
            payload, headers,
        )

    def counter_dispute_claim(self, brokerage_id: str, claim_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/dispute-claims/{claim_id}/counter",
            payload, headers,
        )

    def accept_counter_dispute_claim(self, brokerage_id: str, claim_id: str,
                                     headers: Dict[str, str],
                                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/dispute-claims/{claim_id}/accept-counter",
            payload, headers,
        )

    def reject_counter_dispute_claim(self, brokerage_id: str, claim_id: str,
                                     headers: Dict[str, str],
                                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/dispute-claims/{claim_id}/reject-counter",
            payload, headers,
        )

    def resolve_dispute_claim(self, brokerage_id: str, claim_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/dispute-claims/{claim_id}/resolve",
            payload, headers,
        )

    def escalate_dispute_claim(self, brokerage_id: str, claim_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/dispute-claims/{claim_id}/escalate",
            payload, headers,
        )

    def withdraw_dispute_claim(self, brokerage_id: str, claim_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/brokerages/{brokerage_id}/dispute-claims/{claim_id}/withdraw",
            payload, headers,
        )

    # ======================================================================
    # Liveness — no auth
    # ======================================================================
    def healthz(self, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", "/healthz", headers=headers or {})


# Module-level singleton used by tests + fixtures.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
