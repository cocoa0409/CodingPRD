"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles the
HTTP plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Test-driving clock (PRD §4)
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    # =======================================================================
    # Exhibition (PRD §3.1, §4)
    # =======================================================================
    def create_exhibition(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/exhibitions", payload, headers)

    def get_exhibition(self, exhibition_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/exhibitions/{exhibition_id}", headers=headers,
        )

    def open_intake(self, exhibition_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/open-intake",
            payload if payload is not None else {}, headers,
        )

    def publish_allocation(self, exhibition_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/publish-allocation",
            payload if payload is not None else {}, headers,
        )

    def start_setup(self, exhibition_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/start-setup",
            payload if payload is not None else {}, headers,
        )

    def open_doors(self, exhibition_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/open-doors",
            payload if payload is not None else {}, headers,
        )

    def close_doors(self, exhibition_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/close-doors",
            payload if payload is not None else {}, headers,
        )

    def close_exhibition(self, exhibition_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/close",
            payload if payload is not None else {}, headers,
        )

    def get_entitlement_report(self, exhibition_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET", f"/exhibitions/{exhibition_id}/entitlement-report",
            headers=headers,
        )

    def get_audit_log(self, exhibition_id: str,
                      headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/exhibitions/{exhibition_id}/audit-log",
            headers=headers, params=params,
        )

    def get_occupancy(self, exhibition_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/exhibitions/{exhibition_id}/occupancy",
            headers=headers,
        )

    # =======================================================================
    # Halls (PRD §3.2, §4)
    # =======================================================================
    def create_hall(self, exhibition_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/halls", payload, headers,
        )

    # =======================================================================
    # FloorPlanVersion (PRD §3.2, §4)
    # =======================================================================
    def create_floor_plan(self, hall_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/halls/{hall_id}/floor-plans", payload, headers,
        )

    def activate_floor_plan(self, hall_id: str, plan_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/halls/{hall_id}/floor-plans/{plan_id}/activate",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Booths (PRD §3.2, §4)
    # =======================================================================
    def create_booth(self, hall_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/halls/{hall_id}/booths", payload, headers,
        )

    def list_booths(self, hall_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/halls/{hall_id}/booths",
            headers=headers, params=params,
        )

    def get_booth(self, booth_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/booths/{booth_id}", headers=headers,
        )

    # =======================================================================
    # ExhibitorApplication (PRD §3.3, §4)
    # =======================================================================
    def create_application(self, exhibition_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/applications",
            payload, headers,
        )

    def submit_application(self, application_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/submit",
            payload if payload is not None else {}, headers,
        )

    def start_review_application(self, application_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/start-review",
            payload if payload is not None else {}, headers,
        )

    def qualify_application(self, application_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/qualify",
            payload if payload is not None else {}, headers,
        )

    def reject_application(self, application_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/applications/{application_id}/reject",
            payload, headers,
        )

    def withdraw_application(self, application_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/applications/{application_id}/withdraw",
            payload if payload is not None else {}, headers,
        )

    def list_applications(self, exhibition_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/exhibitions/{exhibition_id}/applications",
            headers=headers, params=params,
        )

    # =======================================================================
    # BoothAllocation (PRD §3.4, §4)
    # =======================================================================
    def create_allocation(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/allocations", payload, headers)

    def object_allocation(self, allocation_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/allocations/{allocation_id}/object",
            payload, headers,
        )

    def confirm_allocation(self, allocation_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/allocations/{allocation_id}/confirm",
            payload if payload is not None else {}, headers,
        )

    def start_relocation(self, allocation_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/allocations/{allocation_id}/start-relocation",
            payload if payload is not None else {}, headers,
        )

    def relocate_allocation(self, allocation_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/allocations/{allocation_id}/relocate",
            payload, headers,
        )

    def revoke_allocation(self, allocation_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/allocations/{allocation_id}/revoke",
            payload, headers,
        )

    def get_allocation(self, allocation_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/allocations/{allocation_id}", headers=headers,
        )

    # =======================================================================
    # DockSlot (PRD §3.5, §4)
    # =======================================================================
    def create_dock_slot(self, exhibition_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/dock-slots",
            payload, headers,
        )

    def complete_dock_slot(self, dock_slot_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/dock-slots/{dock_slot_id}/complete",
            payload if payload is not None else {}, headers,
        )

    def cancel_dock_slot(self, dock_slot_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/dock-slots/{dock_slot_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # SafetyInspection (PRD §3.5, §4)
    # =======================================================================
    def create_safety_inspection(self, exhibition_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/safety-inspections",
            payload, headers,
        )

    # =======================================================================
    # WorkOrder (PRD §3.6, §4)
    # =======================================================================
    def create_work_order(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/work-orders", payload, headers)

    def submit_work_order(self, work_order_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/submit",
            payload if payload is not None else {}, headers,
        )

    def dispatch_work_order(self, work_order_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/dispatch",
            payload if payload is not None else {}, headers,
        )

    def confirm_execution(self, work_order_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/confirm-execution",
            payload if payload is not None else {}, headers,
        )

    def bill_work_order(self, work_order_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/bill",
            payload if payload is not None else {}, headers,
        )

    def dispute_work_order(self, work_order_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/dispute",
            payload, headers,
        )

    def resolve_work_order(self, work_order_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/resolve",
            payload, headers,
        )

    def cancel_work_order(self, work_order_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Ticket (PRD §3.7, §4)
    # =======================================================================
    def create_ticket(self, exhibition_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/tickets",
            payload, headers,
        )

    def scan_in_ticket(self, ticket_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/tickets/{ticket_id}/scan-in",
            payload if payload is not None else {}, headers,
        )

    def scan_out_ticket(self, ticket_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/tickets/{ticket_id}/scan-out",
            payload if payload is not None else {}, headers,
        )

    def refund_ticket(self, ticket_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/tickets/{ticket_id}/refund",
            payload if payload is not None else {}, headers,
        )

    def void_ticket(self, ticket_id: str,
                    headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/tickets/{ticket_id}/void",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # SponsorEntitlement (PRD §3.8, §4)
    # =======================================================================
    def create_entitlement(self, exhibition_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/entitlements",
            payload, headers,
        )

    def start_entitlement(self, entitlement_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/entitlements/{entitlement_id}/start",
            payload if payload is not None else {}, headers,
        )

    def fulfill_entitlement(self, entitlement_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/entitlements/{entitlement_id}/fulfill",
            payload, headers,
        )

    def mark_missed_entitlement(self, entitlement_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/entitlements/{entitlement_id}/mark-missed",
            payload if payload is not None else {}, headers,
        )

    def offer_make_good(self, entitlement_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/entitlements/{entitlement_id}/offer-make-good",
            payload if payload is not None else {}, headers,
        )

    def accept_make_good(self, entitlement_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/entitlements/{entitlement_id}/accept-make-good",
            payload if payload is not None else {}, headers,
        )

    def waive_entitlement(self, entitlement_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/entitlements/{entitlement_id}/waive",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
