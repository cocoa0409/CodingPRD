"""API client: one method per endpoint defined in the PRD §4.

Every method delegates to GenericApiClient._request and returns the raw
Response. Tests pass headers explicitly because PRD §2.1 makes
X-User-ID / X-User-Role mandatory for every request.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # HsCode library
    # =====================================================================
    def create_hs_code(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/hs_codes", payload, headers)

    def deprecate_hs_code(self, hs_code_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/hs_codes/{hs_code_id}/deprecate", headers=headers,
        )

    def get_hs_code(self, hs_code_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/hs_codes/{hs_code_id}", headers=headers,
        )

    def suggest_classification(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", "/classification/suggest", payload, headers,
        )

    # =====================================================================
    # TariffRule / ExchangeRate
    # =====================================================================
    def create_tariff_rule(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/tariff_rules", payload, headers)

    def create_exchange_rate(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/exchange_rates", payload, headers)

    # =====================================================================
    # Importer / Declarant
    # =====================================================================
    def create_importer(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/importers", payload, headers)

    def suspend_importer(
        self, importer_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/importers/{importer_id}/suspend", headers=headers,
        )

    def create_declarant(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/declarants", payload, headers)

    # =====================================================================
    # Order
    # =====================================================================
    def create_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/orders", payload, headers)

    def cancel_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/cancel", headers=headers,
        )

    def return_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/return", headers=headers,
        )

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    # =====================================================================
    # Declaration
    # =====================================================================
    def create_declaration(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/declarations", payload, headers)

    def add_declaration_line(
        self,
        declaration_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/declarations/{declaration_id}/lines",
            payload,
            headers,
        )

    def review_line_override(
        self,
        declaration_id: str,
        line_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/declarations/{declaration_id}/lines/{line_id}/override",
            payload,
            headers,
        )

    def submit_declaration(
        self, declaration_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/declarations/{declaration_id}/submit",
            payload,
            headers,
        )

    def start_review_declaration(
        self, declaration_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/declarations/{declaration_id}/start_review",
            headers=headers,
        )

    def open_query(
        self,
        declaration_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/declarations/{declaration_id}/queries",
            payload,
            headers,
        )

    def respond_query(
        self,
        query_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/queries/{query_id}/respond", payload, headers,
        )

    def resolve_query(self, query_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/queries/{query_id}/resolve", headers=headers,
        )

    def schedule_inspection(
        self,
        declaration_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/declarations/{declaration_id}/inspection_appointments",
            payload,
            headers,
        )

    def complete_inspection(
        self, appointment_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/inspection_appointments/{appointment_id}/complete",
            headers=headers,
        )

    def cancel_inspection(
        self, appointment_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/inspection_appointments/{appointment_id}/cancel",
            headers=headers,
        )

    def reject_declaration(
        self,
        declaration_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/declarations/{declaration_id}/reject",
            payload,
            headers,
        )

    def approve_declaration(
        self, declaration_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/declarations/{declaration_id}/approve",
            headers=headers,
        )

    def conditional_release(
        self, declaration_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/declarations/{declaration_id}/conditional_release",
            headers=headers,
        )

    def amend_declaration(
        self,
        declaration_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/declarations/{declaration_id}/amend",
            payload,
            headers,
        )

    def finalize_amendment(
        self, declaration_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/declarations/{declaration_id}/finalize_amendment",
            headers=headers,
        )

    def get_declaration(
        self, declaration_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/declarations/{declaration_id}", headers=headers,
        )

    def list_declarations(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/declarations", headers=headers, params=params,
        )

    # =====================================================================
    # PaymentNotice
    # =====================================================================
    def get_payment_notice(self, notice_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/payment_notices/{notice_id}", headers=headers,
        )

    def confirm_payment(
        self,
        notice_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        # confirm_payment requires Idempotency-Key header. Pass via the
        # `headers` arg; do NOT mutate the caller's dict here.
        return self._request(
            "POST",
            f"/payment_notices/{notice_id}/confirm_payment",
            payload,
            headers,
        )

    def reverse_payment(
        self,
        notice_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/payment_notices/{notice_id}/reverse",
            payload,
            headers,
        )

    # =====================================================================
    # Refund
    # =====================================================================
    def create_refund(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/refunds", payload, headers)

    def submit_refund(self, refund_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refunds/{refund_id}/submit", headers=headers,
        )

    def approve_refund(self, refund_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refunds/{refund_id}/approve", headers=headers,
        )

    def reject_refund(
        self,
        refund_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/refunds/{refund_id}/reject",
            payload,
            headers,
        )

    def execute_refund(self, refund_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/refunds/{refund_id}/execute", headers=headers,
        )

    def get_refund(self, refund_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/refunds/{refund_id}", headers=headers,
        )

    # =====================================================================
    # Audit
    # =====================================================================
    def list_audit_events(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/audit_events", headers=headers, params=params,
        )

    # =====================================================================
    # Test-driving (clock + synthetic events)
    # =====================================================================
    def advance_clock(
        self, seconds: int, headers: Dict[str, str]
    ):
        return self._request(
            "POST", "/_clock/advance", {"seconds": seconds}, headers,
        )

    def emit_event(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", "/_events/emit", payload, headers,
        )


# Single shared instance — base URL is provided by the runner via env.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
