"""API client: one method per endpoint declared in PRD section 4.

All paths are mounted under the `/api` prefix (PRD section 4 preamble).
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Rent Collection & Delinquency Enforcement API."""

    # --- Portfolio setup ---
    def create_property(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/properties", payload, headers)

    def create_tenant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/tenants", payload, headers)

    def create_lease(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/leases", payload, headers)

    def get_lease(self, lease_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/leases/{lease_id}", headers=headers)

    def list_leases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/leases", headers=headers, params=params)

    def transition_lease(self, lease_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/leases/{lease_id}/transition", payload, headers)

    def get_lease_ledger(self, lease_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/leases/{lease_id}/ledger", headers=headers)

    # --- Ledger charges ---
    def create_charge(self, lease_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/leases/{lease_id}/charges", payload, headers)

    def list_charges(self, lease_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/api/leases/{lease_id}/charges", headers=headers, params=params)

    def waive_charge(self, charge_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/charges/{charge_id}/waive", payload, headers)

    # --- Payments and allocations ---
    def create_payment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/payments", payload, headers)

    def get_payment(self, payment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/payments/{payment_id}", headers=headers)

    def list_payments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/payments", headers=headers, params=params)

    def transition_payment(self, payment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/payments/{payment_id}/transition", payload, headers)

    def get_allocation(self, allocation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/allocations", headers=headers, params=params)

    # --- Delinquency notices ---
    def create_notice(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/notices", payload, headers)

    def list_notices(self, lease_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/api/leases/{lease_id}/notices", headers=headers, params=params)

    def transition_notice(self, notice_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/notices/{notice_id}/transition", payload, headers)

    # --- Payment plans ---
    def create_payment_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/payment-plans", payload, headers)

    def list_payment_plans(self, lease_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/api/leases/{lease_id}/payment-plans", headers=headers, params=params)

    def get_payment_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/payment-plans/{plan_id}", headers=headers)

    def transition_payment_plan(self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/payment-plans/{plan_id}/transition", payload, headers)

    # --- Disputes ---
    def create_dispute(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/disputes", payload, headers)

    def get_dispute(self, dispute_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/disputes", headers=headers, params=params)

    def transition_dispute(self, dispute_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/disputes/{dispute_id}/transition", payload, headers)

    # --- Collections referrals ---
    def transition_referral(self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/collections-referrals/{referral_id}/transition", payload, headers
        )

    def list_referrals(self, lease_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/leases/{lease_id}/collections-referrals", headers=headers, params=params
        )

    # --- Ops sweep and logical clock ---
    def run_delinquency_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/api/delinquency-runs", {}, headers)

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
