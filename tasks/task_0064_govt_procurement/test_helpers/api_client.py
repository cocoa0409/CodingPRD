"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.

All endpoints are mounted under the /procurement prefix (PRD §1).
The two test-driving endpoints (/_clock/advance and /_events/emit) sit
outside that prefix per PRD §4.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Clock / Events (PRD §2.4, §4)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def emit_event(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", payload, headers)

    # =======================================================================
    # Suppliers (PRD §3.3, §4)
    # =======================================================================
    def create_supplier(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", "/procurement/suppliers", payload, headers,
        )

    def verify_supplier(self, supplier_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/suppliers/{supplier_id}/verify",
            headers=headers,
        )

    def blacklist_supplier(self, supplier_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/suppliers/{supplier_id}/blacklist",
            payload, headers,
        )

    def get_supplier(self, supplier_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/procurement/suppliers/{supplier_id}",
            headers=headers,
        )

    # =======================================================================
    # Procurement plans (PRD §3.1, §3.2, §4)
    # =======================================================================
    def create_plan(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", "/procurement/plans", payload, headers,
        )

    def add_plan_item(self, plan_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/plans/{plan_id}/items",
            payload, headers,
        )

    def approve_plan_item(self, item_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/plan-items/{item_id}/approve",
            headers=headers,
        )

    def reject_plan_item(self, item_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/plan-items/{item_id}/reject",
            headers=headers,
        )

    def cancel_plan_item(self, item_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/plan-items/{item_id}/cancel",
            headers=headers,
        )

    def submit_plan_review(self, plan_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/plans/{plan_id}/submit-review",
            headers=headers,
        )

    def publish_plan(self, plan_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/plans/{plan_id}/publish",
            headers=headers,
        )

    def reject_plan(self, plan_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/plans/{plan_id}/reject",
            headers=headers,
        )

    def begin_plan_amendment(self, plan_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/plans/{plan_id}/begin-amendment",
            headers=headers,
        )

    def archive_plan(self, plan_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/plans/{plan_id}/archive",
            headers=headers,
        )

    def list_plans(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/procurement/plans", headers=headers, params=params,
        )

    def get_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/procurement/plans/{plan_id}", headers=headers,
        )

    # =======================================================================
    # Projects + Tender Documents (PRD §3.4, §3.5, §3.6, §4)
    # =======================================================================
    def create_project(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", "/procurement/projects", payload, headers,
        )

    def create_tender_document(self, project_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/projects/{project_id}/tender-document",
            payload, headers,
        )

    def publish_tender_document(self, tender_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/tender-documents/{tender_id}/publish",
            headers=headers,
        )

    def clarify_tender_document(self, tender_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/tender-documents/{tender_id}/clarify",
            payload, headers,
        )

    def finalize_clarification(self, tender_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/procurement/tender-documents/{tender_id}/finalize-clarification",
            headers=headers,
        )

    def begin_tender_amendment(self, tender_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/procurement/tender-documents/{tender_id}/begin-amendment",
            headers=headers,
        )

    def get_project(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/procurement/projects/{project_id}",
            headers=headers,
        )

    def open_bidding(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/projects/{project_id}/open-bidding",
            headers=headers,
        )

    def close_bidding(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/projects/{project_id}/close-bidding",
            headers=headers,
        )

    def cancel_project(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/projects/{project_id}/cancel",
            headers=headers,
        )

    def publish_prescreen_results(self, project_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/procurement/projects/{project_id}/prescreen-results",
            headers=headers,
        )

    # =======================================================================
    # Bids (PRD §3.6, §3.8, §4)
    # =======================================================================
    def submit_bid(self, project_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/projects/{project_id}/bids",
            payload, headers,
        )

    def withdraw_bid(self, bid_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/bids/{bid_id}/withdraw",
            headers=headers,
        )

    def record_evaluation(self, bid_id: str,
                          payload: Optional[Dict[str, Any]],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/bids/{bid_id}/record-evaluation",
            payload, headers,
        )

    def list_project_bids(self, project_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/procurement/projects/{project_id}/bids",
            headers=headers, params=params,
        )

    # =======================================================================
    # Committees (PRD §3.7, §4)
    # =======================================================================
    def form_committee(self, project_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/projects/{project_id}/form-committee",
            payload, headers,
        )

    def finalize_committee(self, committee_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/procurement/committees/{committee_id}/finalize",
            headers=headers,
        )

    def open_bid_ceremony(self, project_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/procurement/projects/{project_id}/open-bid-ceremony",
            headers=headers,
        )

    # =======================================================================
    # Awards (PRD §3.9, §4)
    # =======================================================================
    def decide_award(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/projects/{project_id}/decide-award",
            headers=headers,
        )

    def publish_award(self, award_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/awards/{award_id}/publish",
            headers=headers,
        )

    # =======================================================================
    # Queries (PRD §3.7, §4)
    # =======================================================================
    def submit_query(self, project_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/projects/{project_id}/queries",
            payload, headers,
        )

    def respond_query(self, query_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/queries/{query_id}/respond",
            payload, headers,
        )

    # =======================================================================
    # Complaints (PRD §3.10, §4)
    # =======================================================================
    def file_complaint(self, project_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/projects/{project_id}/complaints",
            payload, headers,
        )

    def accept_complaint(self, complaint_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/complaints/{complaint_id}/accept",
            headers=headers,
        )

    def uphold_complaint(self, complaint_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/complaints/{complaint_id}/uphold",
            payload, headers,
        )

    def dismiss_complaint(self, complaint_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/complaints/{complaint_id}/dismiss",
            headers=headers,
        )

    def withdraw_complaint(self, complaint_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/complaints/{complaint_id}/withdraw",
            headers=headers,
        )

    # =======================================================================
    # Contracts (PRD §3.11, §4)
    # =======================================================================
    def file_contract(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/procurement/contracts", payload, headers,
        )

    def sign_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/contracts/{contract_id}/sign",
            headers=headers,
        )

    def begin_contract_amendment(self, contract_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/procurement/contracts/{contract_id}/begin-amendment",
            headers=headers,
        )

    def file_contract_amendment(self, contract_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/procurement/contracts/{contract_id}/file-amendment",
            payload, headers,
        )

    def record_payment(self, contract_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/procurement/contracts/{contract_id}/record-payment",
            payload, headers,
        )

    def mark_contract_executed(self, contract_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/procurement/contracts/{contract_id}/mark-executed",
            headers=headers,
        )

    def terminate_contract(self, contract_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/procurement/contracts/{contract_id}/terminate",
            payload, headers,
        )

    # =======================================================================
    # Audit log (PRD §2.8, §4)
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/procurement/audit-logs",
            headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
