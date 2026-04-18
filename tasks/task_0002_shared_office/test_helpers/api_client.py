"""API client for the Shared Office API.

One method per endpoint mounted under /shared-office (PRD §4).
Inherits _request from GenericApiClient.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Concrete client. Every method returns the raw requests.Response."""

    # ──────────────── Health & test-driving clock/sweep ────────────────

    def health(self, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", "/shared-office/health", headers=headers or {})

    def advance_clock(self, to_timestamp: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/shared-office/_clock/advance", {"to_timestamp": to_timestamp}, headers
        )

    def run_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/shared-office/_sweep/run", {}, headers)

    # ──────────────── Tenants ────────────────

    def create_tenant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shared-office/tenants", payload, headers)

    def get_tenant(self, tenant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shared-office/tenants/{tenant_id}", headers=headers)

    def list_tenants(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/shared-office/tenants", headers=headers, params=params)

    # ──────────────── Leases ────────────────

    def create_lease(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shared-office/leases", payload, headers)

    def activate_lease(self, lease_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/shared-office/leases/{lease_id}/activate", payload or {}, headers
        )

    def request_lease_termination(
        self, lease_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/shared-office/leases/{lease_id}/request-termination",
            payload or {},
            headers,
        )

    def withdraw_lease_termination(
        self, lease_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/shared-office/leases/{lease_id}/withdraw-termination",
            payload or {},
            headers,
        )

    def begin_lease_review(
        self, lease_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/shared-office/leases/{lease_id}/begin-review", payload or {}, headers
        )

    def finalize_lease_termination(
        self, lease_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/shared-office/leases/{lease_id}/finalize-termination",
            payload or {},
            headers,
        )

    def reject_lease_termination(
        self, lease_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/shared-office/leases/{lease_id}/reject-termination",
            payload or {},
            headers,
        )

    def get_lease(self, lease_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shared-office/leases/{lease_id}", headers=headers)

    # ──────────────── Members ────────────────

    def create_member(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shared-office/members", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shared-office/members/{member_id}", headers=headers)

    # ──────────────── Resources ────────────────

    def create_resource(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shared-office/resources", payload, headers)

    def list_resources(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/shared-office/resources", headers=headers, params=params)

    # ──────────────── Reservations ────────────────

    def create_reservation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shared-office/reservations", payload, headers)

    def confirm_reservation(
        self, reservation_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/shared-office/reservations/{reservation_id}/confirm",
            payload or {},
            headers,
        )

    def cancel_reservation(
        self, reservation_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/shared-office/reservations/{reservation_id}/cancel",
            payload or {},
            headers,
        )

    def get_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/shared-office/reservations/{reservation_id}", headers=headers
        )

    def list_reservations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/shared-office/reservations", headers=headers, params=params
        )

    # ──────────────── Visitors ────────────────

    def create_visitor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shared-office/visitors", payload, headers)

    def revoke_visitor(
        self, visitor_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/shared-office/visitors/{visitor_id}/revoke", payload or {}, headers
        )

    def get_visitor(self, visitor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shared-office/visitors/{visitor_id}", headers=headers)

    # ──────────────── Access badges ────────────────

    def create_access_badge(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shared-office/access-badges", payload, headers)

    def suspend_access_badge(
        self, badge_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/shared-office/access-badges/{badge_id}/suspend", payload or {}, headers
        )

    def reactivate_access_badge(
        self, badge_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"/shared-office/access-badges/{badge_id}/reactivate",
            payload or {},
            headers,
        )

    def revoke_access_badge(
        self, badge_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/shared-office/access-badges/{badge_id}/revoke", payload or {}, headers
        )

    # ──────────────── Access events ────────────────

    def create_access_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shared-office/access-events", payload, headers)

    # ──────────────── Bills ────────────────

    def issue_bill(self, bill_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/shared-office/bills/{bill_id}/issue", payload or {}, headers
        )

    def pay_bill(self, bill_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/shared-office/bills/{bill_id}/pay", payload or {}, headers
        )

    def void_bill(self, bill_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/shared-office/bills/{bill_id}/void", payload or {}, headers
        )

    def get_bill(self, bill_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shared-office/bills/{bill_id}", headers=headers)

    def list_bills(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/shared-office/bills", headers=headers, params=params)


api_client = ApiClient()
