"""API client for the Domestic Service Dispatch API.

One method per endpoint defined in PRD §4. All endpoints are mounted under the
/dsd URL prefix per PRD §1. Inherits _request from GenericApiClient.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Concrete client; every method returns the raw requests.Response."""

    # ──────────────── ServicePersonnel ────────────────

    def create_personnel(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dsd/personnel", payload, headers)

    def get_personnel(self, personnel_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/dsd/personnel/{personnel_id}", headers=headers
        )

    def list_personnel(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/dsd/personnel", headers=headers, params=params
        )

    def verify_personnel_identity(
        self, personnel_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/dsd/personnel/{personnel_id}/verify-identity",
            {},
            headers,
        )

    def activate_personnel(self, personnel_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/personnel/{personnel_id}/activate", {}, headers
        )

    def suspend_personnel(self, personnel_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/personnel/{personnel_id}/suspend", {}, headers
        )

    def reinstate_personnel(self, personnel_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/personnel/{personnel_id}/reinstate", {}, headers
        )

    def disqualify_personnel(self, personnel_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/personnel/{personnel_id}/disqualify", {}, headers
        )

    # ──────────────── SkillCertification ────────────────

    def create_certification(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/dsd/certifications", payload, headers)

    def approve_certification(self, cert_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/certifications/{cert_id}/approve", {}, headers
        )

    def revoke_certification(self, cert_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/certifications/{cert_id}/revoke", {}, headers
        )

    def list_personnel_certifications(
        self,
        personnel_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/dsd/personnel/{personnel_id}/certifications",
            headers=headers,
            params=params,
        )

    # ──────────────── ServiceItem ────────────────

    def create_service_item(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/dsd/service-items", payload, headers)

    def list_service_items(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/dsd/service-items", headers=headers, params=params
        )

    def patch_service_item(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/dsd/service-items/{item_id}", payload, headers
        )

    # ──────────────── Customer ────────────────

    def create_customer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dsd/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/dsd/customers/{customer_id}", headers=headers
        )

    # ──────────────── Order ────────────────

    def create_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dsd/orders", payload, headers)

    def patch_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/dsd/orders/{order_id}", payload, headers
        )

    def submit_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/orders/{order_id}/submit", {}, headers
        )

    def dispatch_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/orders/{order_id}/dispatch", {}, headers
        )

    def reassign_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/dsd/orders/{order_id}/reassign", payload, headers
        )

    def accept_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/orders/{order_id}/accept", {}, headers
        )

    def reject_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/orders/{order_id}/reject", {}, headers
        )

    def checkin_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/dsd/orders/{order_id}/checkin", payload, headers
        )

    def patch_execution(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/dsd/orders/{order_id}/execution", payload, headers
        )

    def complete_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/orders/{order_id}/complete", {}, headers
        )

    def customer_accept_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/orders/{order_id}/customer-accept", {}, headers
        )

    def cancel_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/orders/{order_id}/cancel", {}, headers
        )

    def refund_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/orders/{order_id}/refund", {}, headers
        )

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dsd/orders/{order_id}", headers=headers)

    def list_orders(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/dsd/orders", headers=headers, params=params
        )

    # ──────────────── RecurringOrder ────────────────

    def create_recurring_order(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", "/dsd/recurring-orders", payload, headers
        )

    def pause_recurring_order(self, ro_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/recurring-orders/{ro_id}/pause", {}, headers
        )

    def resume_recurring_order(self, ro_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/recurring-orders/{ro_id}/resume", {}, headers
        )

    def terminate_recurring_order(self, ro_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/recurring-orders/{ro_id}/terminate", {}, headers
        )

    # ──────────────── AbnormalEvent ────────────────

    def report_abnormal_event(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/dsd/orders/{order_id}/abnormal-events",
            payload,
            headers,
        )

    # ──────────────── OrderRating ────────────────

    def rate_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/dsd/orders/{order_id}/rate", payload, headers
        )

    def close_investigation(self, rating_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/dsd/ratings/{rating_id}/close-investigation",
            {},
            headers,
        )

    # ──────────────── InsuranceClaim ────────────────

    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dsd/claims/{claim_id}", headers=headers)

    def attach_claim_evidence(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/dsd/claims/{claim_id}/evidence", payload, headers
        )

    def request_claim_evidence(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/claims/{claim_id}/request-evidence", {}, headers
        )

    def file_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/claims/{claim_id}/file", {}, headers
        )

    def mark_claim_paid(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/claims/{claim_id}/mark-paid", {}, headers
        )

    def archive_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dsd/claims/{claim_id}/archive", {}, headers
        )

    # ──────────────── Audit logs ────────────────

    def list_audit_logs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/dsd/audit-logs", headers=headers, params=params
        )

    # ──────────────── Settlement ────────────────

    def list_personnel_settlement(
        self,
        personnel_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/dsd/personnel/{personnel_id}/settlement",
            headers=headers,
            params=params,
        )

    # ──────────────── Test-driving / system endpoints ────────────────

    def advance_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", "/dsd/_clock/advance", payload, headers
        )

    def run_recertification_sweep(self, headers: Dict[str, str]):
        return self._request(
            "POST", "/dsd/_sweep/recertification", {}, headers
        )

    def run_settlement_sweep(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", "/dsd/_sweep/settlement", payload, headers
        )

    def emit_insurance_decision(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", "/dsd/_events/insurance-decision", payload, headers
        )

    def emit_payment_received(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", "/dsd/_events/payment-received", payload, headers
        )


api_client = ApiClient()
