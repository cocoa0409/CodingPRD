"""
API client for the shared power bank operation API.

One method per endpoint defined in the PRD. The base ``_request()`` method is
inherited from ``GenericApiClient``; this subclass merely names each operation.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Cabinets
    # ------------------------------------------------------------------

    def create_cabinet(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cabinets", payload, headers)

    def get_cabinet(self, cabinet_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cabinets/{cabinet_id}", headers=headers)

    def heartbeat_cabinet(
        self, cabinet_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cabinets/{cabinet_id}/heartbeat", payload, headers
        )

    def eject_slot(
        self, cabinet_id: str, slot_index: int, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/cabinets/{cabinet_id}/slots/{slot_index}/eject",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------

    def create_device(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/devices", payload, headers)

    def get_device(self, device_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/devices/{device_id}", headers=headers)

    def report_fault(
        self, device_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/devices/{device_id}/report-fault", payload, headers
        )

    # ------------------------------------------------------------------
    # Pricing plans
    # ------------------------------------------------------------------

    def create_pricing_plan(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/pricing-plans", payload, headers)

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def create_user(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/users", payload, headers)

    def get_user(self, user_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/users/{user_id}", headers=headers)

    def topup_wallet(
        self, user_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/users/{user_id}/wallet/topup", payload, headers
        )

    def deposit(
        self, user_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/users/{user_id}/deposit", payload, headers
        )

    # ------------------------------------------------------------------
    # Rentals
    # ------------------------------------------------------------------

    def create_rental(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/rentals", payload, headers)

    def get_rental(self, rental_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rentals/{rental_id}", headers=headers)

    def return_rental(
        self, rental_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/rentals/{rental_id}/return", payload, headers
        )

    def return_retry(
        self, rental_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/rentals/{rental_id}/return-retry", payload, headers
        )

    def refund_rental(self, rental_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/rentals/{rental_id}/refund", headers=headers
        )

    # ------------------------------------------------------------------
    # Repair tickets
    # ------------------------------------------------------------------

    def get_repair_ticket(self, ticket_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/repair-tickets/{ticket_id}", headers=headers
        )

    def assign_ticket(self, ticket_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/repair-tickets/{ticket_id}/assign", headers=headers
        )

    def hold_ticket(self, ticket_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/repair-tickets/{ticket_id}/hold", headers=headers
        )

    def resume_ticket(self, ticket_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/repair-tickets/{ticket_id}/resume", headers=headers
        )

    def resolve_ticket(
        self,
        ticket_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/repair-tickets/{ticket_id}/resolve",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Operator tasks
    # ------------------------------------------------------------------

    def auto_assign_task(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", "/operator-tasks/auto-assign", payload, headers
        )

    def get_operator_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/operator-tasks/{task_id}", headers=headers
        )

    def complete_task(
        self,
        task_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/operator-tasks/{task_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Settlements
    # ------------------------------------------------------------------

    def create_settlement(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/settlements", payload, headers)

    def get_settlement(self, settlement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/settlements/{settlement_id}", headers=headers
        )

    def approve_settlement(
        self, settlement_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/settlements/{settlement_id}/approve", headers=headers
        )

    def issue_invoice(self, settlement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/settlements/{settlement_id}/issue-invoice",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Location partners
    # ------------------------------------------------------------------

    def create_location_partner(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/location-partners", payload, headers)

    # ------------------------------------------------------------------
    # Maintenance windows
    # ------------------------------------------------------------------

    def create_maintenance_window(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", "/maintenance-windows", payload, headers
        )

    # ------------------------------------------------------------------
    # System / unauthenticated endpoints
    # ------------------------------------------------------------------

    def post_payment_event(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", "/payment-events", payload, headers if headers else {}
        )

    def advance_clock(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", "/_clock/advance", payload, headers if headers else {}
        )

    def run_sweep(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", "/_sweep/run", payload, headers if headers else {}
        )

    def emit_event(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", "/_events/emit", payload, headers if headers else {}
        )


api_client = ApiClient()
