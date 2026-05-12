"""API client: one method per endpoint defined in the PRD.

Every method delegates to GenericApiClient._request and returns the raw
Response object so tests can assert status codes. Tests pass headers
explicitly because PRD §2.1 requires X-User-ID / X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # WeddingProject (PRD §3.1, §3.5, §3.8)
    # =====================================================================
    def create_project(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/wedding-projects", payload, headers)

    def list_projects(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/wedding-projects", headers=headers, params=params
        )

    def get_project(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/wedding-projects/{project_id}", headers=headers
        )

    def activate_project(self, project_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/wedding-projects/{project_id}/activate",
            payload or {}, headers,
        )

    def start_execution(self, project_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/wedding-projects/{project_id}/start-execution",
            payload or {}, headers,
        )

    def enter_settlement(self, project_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/wedding-projects/{project_id}/enter-settlement",
            payload or {}, headers,
        )

    def close_project(self, project_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/wedding-projects/{project_id}/close",
            payload or {}, headers,
        )

    def cancel_project(self, project_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/wedding-projects/{project_id}/cancel",
            payload or {}, headers,
        )

    def reallocate_budget(self, project_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/wedding-projects/{project_id}/budget/reallocate",
            payload, headers,
        )

    # =====================================================================
    # ProjectTemplate (PRD §3.1)
    # =====================================================================
    def create_template(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/project-templates", payload, headers)

    def list_templates(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/project-templates", headers=headers, params=params
        )

    def get_template(self, template_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/project-templates/{template_id}", headers=headers
        )

    # =====================================================================
    # Milestone (PRD §3.1)
    # =====================================================================
    def create_milestone(self, project_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/wedding-projects/{project_id}/milestones",
            payload, headers,
        )

    def list_milestones(self, project_id: str,
                        headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/wedding-projects/{project_id}/milestones",
            headers=headers, params=params,
        )

    def patch_milestone(self, project_id: str, milestone_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/wedding-projects/{project_id}/milestones/{milestone_id}",
            payload, headers,
        )

    def delete_milestone(self, project_id: str, milestone_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"/wedding-projects/{project_id}/milestones/{milestone_id}",
            headers=headers,
        )

    # =====================================================================
    # Vendor (PRD §3.2)
    # =====================================================================
    def create_vendor(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/vendors", payload, headers)

    def list_vendors(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/vendors", headers=headers, params=params
        )

    def get_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/vendors/{vendor_id}", headers=headers
        )

    def approve_vendor(self, vendor_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/vendors/{vendor_id}/approve",
            payload or {}, headers,
        )

    def reject_vendor(self, vendor_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/vendors/{vendor_id}/reject",
            payload or {}, headers,
        )

    def suspend_vendor(self, vendor_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/vendors/{vendor_id}/suspend",
            payload or {}, headers,
        )

    def reinstate_vendor(self, vendor_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/vendors/{vendor_id}/reinstate",
            payload or {}, headers,
        )

    # =====================================================================
    # Quote (PRD §3.2)
    # =====================================================================
    def create_quote(self, vendor_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/vendors/{vendor_id}/quotes", payload, headers
        )

    def list_quotes(self, vendor_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/vendors/{vendor_id}/quotes",
            headers=headers, params=params,
        )

    def offer_quote(self, vendor_id: str, quote_id: str,
                    headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/vendors/{vendor_id}/quotes/{quote_id}/offer",
            payload or {}, headers,
        )

    def withdraw_quote(self, vendor_id: str, quote_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/vendors/{vendor_id}/quotes/{quote_id}/withdraw",
            payload or {}, headers,
        )

    # =====================================================================
    # Contract (PRD §3.3)
    # =====================================================================
    def create_contract(self, project_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/wedding-projects/{project_id}/contracts",
            payload, headers,
        )

    def list_contracts(self, project_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/wedding-projects/{project_id}/contracts",
            headers=headers, params=params,
        )

    def get_contract(self, project_id: str, contract_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/wedding-projects/{project_id}/contracts/{contract_id}",
            headers=headers,
        )

    def send_for_negotiation(self, project_id: str, contract_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/wedding-projects/{project_id}/contracts/{contract_id}"
            f"/send-for-negotiation",
            payload or {}, headers,
        )

    def revise_contract(self, project_id: str, contract_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/wedding-projects/{project_id}/contracts/{contract_id}/revise",
            payload or {}, headers,
        )

    def sign_contract(self, project_id: str, contract_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/wedding-projects/{project_id}/contracts/{contract_id}/sign",
            payload or {}, headers,
        )

    def accept_signature(self, project_id: str, contract_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/wedding-projects/{project_id}/contracts/{contract_id}"
            f"/accept-signature",
            payload or {}, headers,
        )

    def terminate_contract(self, project_id: str, contract_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/wedding-projects/{project_id}/contracts/{contract_id}"
            f"/terminate",
            payload or {}, headers,
        )

    # =====================================================================
    # ChangeOrder (PRD §3.4)
    # =====================================================================
    def create_change_order(self, project_id: str, contract_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/wedding-projects/{project_id}/contracts/{contract_id}"
            f"/change-orders",
            payload, headers,
        )

    def list_change_orders(self, project_id: str, contract_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/wedding-projects/{project_id}/contracts/{contract_id}"
            f"/change-orders",
            headers=headers, params=params,
        )

    def approve_change_order(self, project_id: str, contract_id: str,
                             change_order_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/wedding-projects/{project_id}/contracts/{contract_id}"
            f"/change-orders/{change_order_id}/approve",
            payload or {}, headers,
        )

    def reject_change_order(self, project_id: str, contract_id: str,
                            change_order_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/wedding-projects/{project_id}/contracts/{contract_id}"
            f"/change-orders/{change_order_id}/reject",
            payload or {}, headers,
        )

    # =====================================================================
    # Settlement (PRD §3.4)
    # =====================================================================
    def create_settlement(self, project_id: str, contract_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/wedding-projects/{project_id}/contracts/{contract_id}"
            f"/settlement",
            payload, headers,
        )

    def get_settlement(self, project_id: str, contract_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/wedding-projects/{project_id}/contracts/{contract_id}"
            f"/settlement",
            headers=headers,
        )

    def patch_settlement(self, project_id: str, contract_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/wedding-projects/{project_id}/contracts/{contract_id}"
            f"/settlement",
            payload, headers,
        )

    def confirm_settlement(self, project_id: str, contract_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/wedding-projects/{project_id}/contracts/{contract_id}"
            f"/settlement/confirm",
            payload or {}, headers,
        )

    def finalize_settlement(self, project_id: str, contract_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/wedding-projects/{project_id}/contracts/{contract_id}"
            f"/settlement/finalize",
            payload or {}, headers,
        )

    def create_performance_rating(self, project_id: str, contract_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/wedding-projects/{project_id}/contracts/{contract_id}"
            f"/settlement/performance-rating",
            payload, headers,
        )

    # =====================================================================
    # TimelineSlot (PRD §3.6)
    # =====================================================================
    def create_timeline_slot(self, project_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/wedding-projects/{project_id}/timeline-slots",
            payload, headers,
        )

    def list_timeline_slots(self, project_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/wedding-projects/{project_id}/timeline-slots",
            headers=headers, params=params,
        )

    def patch_timeline_slot(self, project_id: str, slot_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/wedding-projects/{project_id}/timeline-slots/{slot_id}",
            payload, headers,
        )

    def delete_timeline_slot(self, project_id: str, slot_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"/wedding-projects/{project_id}/timeline-slots/{slot_id}",
            headers=headers,
        )

    def snapshot_rehearsal(self, project_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/wedding-projects/{project_id}/timeline/snapshot-rehearsal",
            payload or {}, headers,
        )

    # =====================================================================
    # Guest (PRD §3.7)
    # =====================================================================
    def create_guest(self, project_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/wedding-projects/{project_id}/guests",
            payload, headers,
        )

    def list_guests(self, project_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/wedding-projects/{project_id}/guests",
            headers=headers, params=params,
        )

    def patch_guest(self, project_id: str, guest_id: str,
                    payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"/wedding-projects/{project_id}/guests/{guest_id}",
            payload, headers,
        )

    def rsvp_guest(self, project_id: str, guest_id: str,
                   payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/wedding-projects/{project_id}/guests/{guest_id}/rsvp",
            payload, headers,
        )

    # =====================================================================
    # AuditEntry (PRD §2.10, §3.8)
    # =====================================================================
    def list_audit_entries(self, project_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/wedding-projects/{project_id}/audit-entries",
            headers=headers, params=params,
        )

    # =====================================================================
    # Test-driving / external-event hooks (PRD §3.8)
    # =====================================================================
    def emit_event(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", payload, headers)

    def advance_clock(self, to_timestamp: int,
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance",
            {"to_timestamp": to_timestamp}, headers,
        )

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run", payload or {}, headers
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
