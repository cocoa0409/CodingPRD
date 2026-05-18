"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Customers — PRD §4
    # =======================================================================
    def create_customer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET", f"/customers/{customer_id}", headers=headers,
        )

    def update_customer(self, customer_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PUT", f"/customers/{customer_id}", payload, headers,
        )

    def suspend_customer(self, customer_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/customers/{customer_id}/suspend", {}, headers,
        )

    def reinstate_customer(self, customer_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/customers/{customer_id}/reinstate", {}, headers,
        )

    def advance_clock(self, customer_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/customers/{customer_id}/clock/advance",
            payload, headers,
        )

    # =======================================================================
    # Vehicles — PRD §4
    # =======================================================================
    def create_vehicle(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}", headers=headers,
        )

    def list_vehicles(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/vehicles", headers=headers, params=params,
        )

    # =======================================================================
    # Loan contracts — PRD §4
    # =======================================================================
    def create_loan_contract(self, customer_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/customers/{customer_id}/loan-contracts",
            payload, headers,
        )

    def approve_loan_contract(self, customer_id: str,
                              contract_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/customers/{customer_id}/loan-contracts/"
            f"{contract_id}/approve",
            payload if payload is not None else {}, headers,
        )

    def activate_loan_contract(self, customer_id: str,
                               contract_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/customers/{customer_id}/loan-contracts/"
            f"{contract_id}/activate",
            payload if payload is not None else {}, headers,
        )

    def reinstate_loan_contract(self, customer_id: str,
                                contract_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/customers/{customer_id}/loan-contracts/"
            f"{contract_id}/reinstate",
            {}, headers,
        )

    def charge_off_loan_contract(self, customer_id: str,
                                 contract_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/customers/{customer_id}/loan-contracts/"
            f"{contract_id}/charge-off",
            {}, headers,
        )

    def get_loan_contract(self, customer_id: str,
                          contract_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/customers/{customer_id}/loan-contracts/{contract_id}",
            headers=headers,
        )

    def get_loan_payoff_quote(self, customer_id: str,
                              contract_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/customers/{customer_id}/loan-contracts/"
            f"{contract_id}/payoff-quote",
            headers=headers, params=params,
        )

    # =======================================================================
    # Lease contracts — PRD §4
    # =======================================================================
    def create_lease_contract(self, customer_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/customers/{customer_id}/lease-contracts",
            payload, headers,
        )

    def approve_lease_contract(self, customer_id: str,
                               contract_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/customers/{customer_id}/lease-contracts/"
            f"{contract_id}/approve",
            payload if payload is not None else {}, headers,
        )

    def activate_lease_contract(self, customer_id: str,
                                contract_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/customers/{customer_id}/lease-contracts/"
            f"{contract_id}/activate",
            payload if payload is not None else {}, headers,
        )

    def get_lease_contract(self, customer_id: str,
                           contract_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/customers/{customer_id}/lease-contracts/{contract_id}",
            headers=headers,
        )

    def get_lease_purchase_quote(self, customer_id: str,
                                 contract_id: str,
                                 headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/customers/{customer_id}/lease-contracts/"
            f"{contract_id}/purchase-quote",
            headers=headers, params=params,
        )

    def submit_lease_end(self, customer_id: str,
                         contract_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/customers/{customer_id}/lease-contracts/"
            f"{contract_id}/lease-end",
            payload, headers,
        )

    def patch_assessment(self, customer_id: str,
                         contract_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/customers/{customer_id}/lease-contracts/"
            f"{contract_id}/assessment",
            payload, headers,
        )

    def settle_assessment(self, customer_id: str,
                          contract_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/customers/{customer_id}/lease-contracts/"
            f"{contract_id}/assessment/settle",
            {}, headers,
        )

    def dispute_assessment(self, customer_id: str,
                           contract_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/customers/{customer_id}/lease-contracts/"
            f"{contract_id}/assessment/dispute",
            {}, headers,
        )

    def resolve_assessment(self, customer_id: str,
                           contract_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/customers/{customer_id}/lease-contracts/"
            f"{contract_id}/assessment/resolve",
            payload, headers,
        )

    # =======================================================================
    # Payments — PRD §4
    # =======================================================================
    def list_payments(self, customer_id: str,
                      headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/customers/{customer_id}/payments",
            headers=headers, params=params,
        )

    def get_payment(self, customer_id: str,
                    payment_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/customers/{customer_id}/payments/{payment_id}",
            headers=headers,
        )

    def pay_payment(self, customer_id: str,
                    payment_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/customers/{customer_id}/payments/{payment_id}/pay",
            {}, headers,
        )

    # =======================================================================
    # Gap insurance riders — PRD §4
    # =======================================================================
    def create_gap_rider(self, customer_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/customers/{customer_id}/gap-riders",
            payload, headers,
        )

    def get_gap_rider(self, customer_id: str,
                      rider_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/customers/{customer_id}/gap-riders/{rider_id}",
            headers=headers,
        )

    def cancel_gap_rider(self, customer_id: str,
                         rider_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/customers/{customer_id}/gap-riders/{rider_id}/cancel",
            {}, headers,
        )

    def claim_gap_rider(self, customer_id: str,
                        rider_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/customers/{customer_id}/gap-riders/{rider_id}/claim",
            payload, headers,
        )

    # =======================================================================
    # Delinquency events — PRD §4
    # =======================================================================
    def list_delinquency_events(self, customer_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/customers/{customer_id}/delinquency-events",
            headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
