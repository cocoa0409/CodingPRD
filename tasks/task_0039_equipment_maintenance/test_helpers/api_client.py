"""API client: one method per endpoint defined in PRD §4.

Every method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 makes
X-User-ID / X-User-Role mandatory for every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # Sites & test-driving capabilities
    # =====================================================================
    def create_site(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def advance_clock(self, site_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/clock/advance", payload, headers,
        )

    def run_sweep(self, site_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/sweep/run", {}, headers,
        )

    # =====================================================================
    # Equipment
    # =====================================================================
    def create_equipment(self, site_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/equipment", payload, headers,
        )

    def get_equipment(self, site_id: str, equipment_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET", f"/sites/{site_id}/equipment/{equipment_id}", headers=headers,
        )

    def patch_equipment(self, site_id: str, equipment_id: str,
                        payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/sites/{site_id}/equipment/{equipment_id}",
            payload, headers,
        )

    def commission_equipment(self, site_id: str, equipment_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/sites/{site_id}/equipment/{equipment_id}/commission",
            {}, headers,
        )

    def place_equipment_in_service(self, site_id: str, equipment_id: str,
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/sites/{site_id}/equipment/{equipment_id}/place-in-service",
            {}, headers,
        )

    def decommission_equipment(self, site_id: str, equipment_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/sites/{site_id}/equipment/{equipment_id}/decommission",
            {}, headers,
        )

    def emit_alarm(self, site_id: str, equipment_id: str,
                   payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/sites/{site_id}/equipment/{equipment_id}/alarms",
            payload, headers,
        )

    # =====================================================================
    # TaskTemplate
    # =====================================================================
    def create_template(self, site_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/templates", payload, headers,
        )

    def get_template(self, site_id: str, template_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET", f"/sites/{site_id}/templates/{template_id}",
            headers=headers,
        )

    # =====================================================================
    # MaintenancePlan
    # =====================================================================
    def create_plan(self, site_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/plans", payload, headers,
        )

    def get_plan(self, site_id: str, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/sites/{site_id}/plans/{plan_id}", headers=headers,
        )

    def patch_plan(self, site_id: str, plan_id: str,
                   payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/sites/{site_id}/plans/{plan_id}", payload, headers,
        )

    def activate_plan(self, site_id: str, plan_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/plans/{plan_id}/activate", {}, headers,
        )

    def pause_plan(self, site_id: str, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/plans/{plan_id}/pause", {}, headers,
        )

    def resume_plan(self, site_id: str, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/plans/{plan_id}/resume", {}, headers,
        )

    def retire_plan(self, site_id: str, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/plans/{plan_id}/retire", {}, headers,
        )

    # =====================================================================
    # SparePart
    # =====================================================================
    def create_spare_part(self, site_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/spare-parts", payload, headers,
        )

    def get_spare_part(self, site_id: str, part_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/sites/{site_id}/spare-parts/{part_id}", headers=headers,
        )

    def patch_spare_part(self, site_id: str, part_id: str,
                         payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/sites/{site_id}/spare-parts/{part_id}",
            payload, headers,
        )

    # =====================================================================
    # Technician
    # =====================================================================
    def create_technician(self, site_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/technicians", payload, headers,
        )

    def get_technician(self, site_id: str, tech_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/sites/{site_id}/technicians/{tech_id}", headers=headers,
        )

    def patch_technician(self, site_id: str, tech_id: str,
                         payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/sites/{site_id}/technicians/{tech_id}",
            payload, headers,
        )

    # =====================================================================
    # WorkOrder
    # =====================================================================
    def create_work_order(self, site_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/work-orders", payload, headers,
        )

    def get_work_order(self, site_id: str, wo_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET", f"/sites/{site_id}/work-orders/{wo_id}", headers=headers,
        )

    def list_work_orders(self, site_id: str, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/sites/{site_id}/work-orders",
            headers=headers, params=params,
        )

    def reassign_work_order(self, site_id: str, wo_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/work-orders/{wo_id}/reassign",
            payload, headers,
        )

    def start_work_order(self, site_id: str, wo_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/work-orders/{wo_id}/start",
            {}, headers,
        )

    def pause_work_order(self, site_id: str, wo_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/work-orders/{wo_id}/pause",
            payload, headers,
        )

    def resume_work_order(self, site_id: str, wo_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/work-orders/{wo_id}/resume",
            {}, headers,
        )

    def complete_work_order(self, site_id: str, wo_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/work-orders/{wo_id}/complete",
            payload, headers,
        )

    def accept_work_order(self, site_id: str, wo_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/work-orders/{wo_id}/accept",
            {}, headers,
        )

    def cancel_work_order(self, site_id: str, wo_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/work-orders/{wo_id}/cancel",
            payload, headers,
        )

    # =====================================================================
    # Requisition
    # =====================================================================
    def create_requisition(self, site_id: str, wo_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/sites/{site_id}/work-orders/{wo_id}/requisitions",
            payload, headers,
        )

    def issue_requisition(self, site_id: str, wo_id: str, req_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/sites/{site_id}/work-orders/{wo_id}/requisitions/{req_id}/issue",
            {}, headers,
        )

    def return_requisition(self, site_id: str, wo_id: str, req_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/sites/{site_id}/work-orders/{wo_id}/requisitions/{req_id}/return",
            payload, headers,
        )

    def cancel_requisition(self, site_id: str, wo_id: str, req_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/sites/{site_id}/work-orders/{wo_id}/requisitions/{req_id}/cancel",
            {}, headers,
        )

    # =====================================================================
    # RepairRecord
    # =====================================================================
    def get_repair_record(self, site_id: str, wo_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/sites/{site_id}/work-orders/{wo_id}/repair-record",
            headers=headers,
        )

    # =====================================================================
    # Audit & analytics
    # =====================================================================
    def list_audit(self, site_id: str, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/sites/{site_id}/audit",
            headers=headers, params=params,
        )

    def analytics_mttr(self, site_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/sites/{site_id}/analytics/mttr",
            headers=headers, params=params,
        )

    def analytics_mtbf(self, site_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/sites/{site_id}/analytics/mtbf",
            headers=headers, params=params,
        )

    def analytics_fault_recurrence(self, site_id: str,
                                   headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/sites/{site_id}/analytics/fault-recurrence",
            headers=headers, params=params,
        )

    def analytics_availability(self, site_id: str, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/sites/{site_id}/analytics/availability",
            headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
