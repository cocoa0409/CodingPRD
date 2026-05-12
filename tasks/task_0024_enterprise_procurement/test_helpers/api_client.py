"""API client: one method per endpoint defined in the PRD §4.

Every method delegates to GenericApiClient._request and returns the raw
Response. PRD §2.1 makes X-User-ID / X-User-Role mandatory for every
request, so headers are required for every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # Test-driving (PRD §3.11)
    # =====================================================================
    def advance_clock(self, to_iso: str, headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", {"to": to_iso}, headers)

    def supplier_delivery_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_events/supplier-delivery", payload, headers)

    # =====================================================================
    # BudgetAccount (PRD §3.1)
    # =====================================================================
    def create_budget_account(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/budget-accounts", payload, headers)

    def get_budget_account(self, budget_account_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/budget-accounts/{budget_account_id}", headers=headers
        )

    def list_budget_accounts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/budget-accounts", headers=headers, params=params)

    # =====================================================================
    # Supplier (PRD §3.1)
    # =====================================================================
    def create_supplier(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/suppliers", payload, headers)

    def qualify_supplier(self, supplier_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/suppliers/{supplier_id}/qualify", {}, headers
        )

    def get_supplier(self, supplier_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/suppliers/{supplier_id}", headers=headers)

    def list_suppliers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/suppliers", headers=headers, params=params)

    # =====================================================================
    # Requirement (PRD §3.2, §3.5)
    # =====================================================================
    def create_requirement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/requirements", payload, headers)

    def submit_requirement(self, requirement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/requirements/{requirement_id}/submit", {}, headers
        )

    def add_quote(
        self, requirement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/requirements/{requirement_id}/quotes", payload, headers
        )

    def shortlist_quotes(
        self, requirement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/requirements/{requirement_id}/shortlist", payload, headers
        )

    def award_requirement(
        self, requirement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/requirements/{requirement_id}/award", payload, headers
        )

    def rework_requirement(self, requirement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/requirements/{requirement_id}/rework", {}, headers
        )

    def cancel_requirement(self, requirement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/requirements/{requirement_id}/cancel", {}, headers
        )

    def get_requirement(self, requirement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/requirements/{requirement_id}", headers=headers
        )

    def list_requirements(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/requirements", headers=headers, params=params)

    def get_quotes_comparison_table(
        self, requirement_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET",
            f"/requirements/{requirement_id}/quotes/comparison-table",
            headers=headers,
        )

    # =====================================================================
    # Quote (PRD §3.2)
    # =====================================================================
    def get_quote(self, quote_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    # =====================================================================
    # PurchaseOrder (PRD §3.3, §3.5)
    # =====================================================================
    def get_purchase_order(self, purchase_order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/purchase-orders/{purchase_order_id}", headers=headers
        )

    def cancel_purchase_order(self, purchase_order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/purchase-orders/{purchase_order_id}/cancel", {}, headers
        )

    def list_purchase_orders(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/purchase-orders", headers=headers, params=params
        )

    def list_approval_steps(self, purchase_order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/purchase-orders/{purchase_order_id}/approval-steps",
            headers=headers,
        )

    # =====================================================================
    # ApprovalStep (PRD §3.3, §3.4)
    # =====================================================================
    def approve_step(
        self,
        step_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/approval-steps/{step_id}/approve", payload or {}, headers
        )

    def reject_step(
        self,
        step_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/approval-steps/{step_id}/reject", payload or {}, headers
        )

    def delegate_step(
        self, step_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/approval-steps/{step_id}/delegate", payload, headers
        )

    # =====================================================================
    # Contract (PRD §3.6)
    # =====================================================================
    def create_contract(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/contracts", payload, headers)

    def submit_contract_for_review(self, contract_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/contracts/{contract_id}/submit-for-review", {}, headers
        )

    def finalize_contract_review(self, contract_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/contracts/{contract_id}/finalize-review", {}, headers
        )

    def amend_contract(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/contracts/{contract_id}/amend", payload, headers
        )

    def sign_contract(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/contracts/{contract_id}/sign", payload, headers
        )

    def terminate_contract(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/contracts/{contract_id}/terminate", payload, headers
        )

    def get_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contract_versions(self, contract_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/contracts/{contract_id}/versions", headers=headers
        )

    # =====================================================================
    # ClauseTemplate (PRD §3.6)
    # =====================================================================
    def create_clause_template(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/clause-templates", payload, headers)

    def list_clause_templates(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/clause-templates", headers=headers, params=params
        )

    # =====================================================================
    # Receipt (PRD §3.8)
    # =====================================================================
    def create_receipt(
        self,
        purchase_order_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/purchase-orders/{purchase_order_id}/receipts", payload, headers
        )

    def inspect_receipt(self, receipt_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/receipts/{receipt_id}/inspect", {}, headers
        )

    def accept_receipt(self, receipt_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/receipts/{receipt_id}/accept", {}, headers
        )

    def reject_receipt(self, receipt_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/receipts/{receipt_id}/reject", {}, headers
        )

    def return_receipt(self, receipt_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/receipts/{receipt_id}/return", {}, headers
        )

    # =====================================================================
    # Invoice (PRD §3.9)
    # =====================================================================
    def create_invoice(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/invoices", payload, headers)

    def match_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/invoices/{invoice_id}/match", {}, headers
        )

    def override_invoice(
        self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/invoices/{invoice_id}/override", payload, headers
        )

    def approve_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/invoices/{invoice_id}/approve", {}, headers
        )

    def reject_invoice(
        self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/invoices/{invoice_id}/reject", payload, headers
        )

    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    # =====================================================================
    # PaymentSchedule + Payment (PRD §3.7, §3.10)
    # =====================================================================
    def get_payment_schedule(
        self, purchase_order_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET",
            f"/purchase-orders/{purchase_order_id}/payment-schedule",
            headers=headers,
        )

    def apply_payment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/payments", payload, headers)

    def approve_payment(self, payment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/payments/{payment_id}/approve", {}, headers
        )

    def execute_payment(self, payment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/payments/{payment_id}/execute", {}, headers
        )

    def cancel_payment(self, payment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/payments/{payment_id}/cancel", {}, headers
        )

    # =====================================================================
    # Audit log (PRD §2.11)
    # =====================================================================
    def list_audit_log(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/audit-log", headers=headers, params=params)


api_client = ApiClient()
