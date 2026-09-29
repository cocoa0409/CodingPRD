"""Thin typed wrapper over the SNAP Retailer Authorization and Redemption
Compliance HTTP API.

One method per endpoint of the PRD's endpoint table. Every collection is mounted
directly at the root, so there is no shared URL prefix; only a case's
civil-money-penalty elections and its penalty ledger are addressed beneath a
parent. Methods return the raw response so a test can assert on both the status
code and the body.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # The logical clock
    # ------------------------------------------------------------------

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Owners
    # ------------------------------------------------------------------

    def create_owner(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/owners/{owner_id}", None, headers)

    def list_owners(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/owners", params or {}, headers)

    # ------------------------------------------------------------------
    # Stores
    # ------------------------------------------------------------------

    def create_store(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/stores/{store_id}", None, headers)

    def list_stores(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/stores", params or {}, headers)

    def update_store(
        self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/stores/{store_id}", payload, headers)

    def withdraw_store(
        self,
        store_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/stores/{store_id}/withdraw", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------

    def create_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/applications/{application_id}", None, headers)

    def list_applications(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/applications", params or {}, headers)

    def submit_application(
        self,
        application_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/applications/{application_id}/submit", payload or {}, headers
        )

    def submit_application_documents(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/applications/{application_id}/documents", payload, headers
        )

    def decide_application(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/applications/{application_id}/decision", payload, headers
        )

    def withdraw_application(
        self,
        application_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/applications/{application_id}/withdraw", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Inspectors
    # ------------------------------------------------------------------

    def create_inspector(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/inspectors", payload, headers)

    def get_inspector(self, inspector_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/inspectors/{inspector_id}", None, headers)

    def list_inspectors(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/inspectors", params or {}, headers)

    def update_inspector(
        self, inspector_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/inspectors/{inspector_id}", payload, headers)

    # ------------------------------------------------------------------
    # Store visits
    # ------------------------------------------------------------------

    def create_store_visit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/store-visits", payload, headers)

    def get_store_visit(self, visit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/store-visits/{visit_id}", None, headers)

    def list_store_visits(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/store-visits", params or {}, headers)

    def start_store_visit(
        self,
        visit_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/store-visits/{visit_id}/start", payload or {}, headers
        )

    def submit_findings(
        self, visit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/store-visits/{visit_id}/findings", payload, headers
        )

    def record_no_access(
        self,
        visit_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/store-visits/{visit_id}/no-access", payload or {}, headers
        )

    def cancel_store_visit(
        self,
        visit_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/store-visits/{visit_id}/cancel", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Point-of-sale transactions
    # ------------------------------------------------------------------

    def create_pos_transaction(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/pos-transactions", payload, headers)

    def get_pos_transaction(self, transaction_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/pos-transactions/{transaction_id}", None, headers
        )

    def list_pos_transactions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/pos-transactions", params or {}, headers)

    def void_pos_transaction(
        self, transaction_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/pos-transactions/{transaction_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Redemption monitoring periods
    # ------------------------------------------------------------------

    def create_redemption_period(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/redemption-periods", payload, headers)

    def get_redemption_period(self, period_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/redemption-periods/{period_id}", None, headers)

    def list_redemption_periods(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/redemption-periods", params or {}, headers)

    def import_settlement(
        self, period_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/redemption-periods/{period_id}/settlement-import", payload, headers
        )

    def close_redemption_period(
        self,
        period_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/redemption-periods/{period_id}/close", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Investigations
    # ------------------------------------------------------------------

    def create_investigation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/investigations", payload, headers)

    def get_investigation(self, investigation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/investigations/{investigation_id}", None, headers)

    def list_investigations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/investigations", params or {}, headers)

    def add_evidence(
        self, investigation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/investigations/{investigation_id}/evidence", payload, headers
        )

    def conclude_investigation(
        self, investigation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/investigations/{investigation_id}/conclude", payload, headers
        )

    # ------------------------------------------------------------------
    # Sanction cases
    # ------------------------------------------------------------------

    def create_sanction_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/sanction-cases", payload, headers)

    def get_sanction_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sanction-cases/{case_id}", None, headers)

    def list_sanction_cases(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/sanction-cases", params or {}, headers)

    def issue_charge_letter(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sanction-cases/{case_id}/charge-letter", payload, headers
        )

    def file_reply(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sanction-cases/{case_id}/reply", payload, headers
        )

    def create_cmp_election(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sanction-cases/{case_id}/cmp-elections", payload, headers
        )

    def list_cmp_elections(
        self,
        case_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/sanction-cases/{case_id}/cmp-elections", params or {}, headers
        )

    def issue_determination(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sanction-cases/{case_id}/determination", payload, headers
        )

    def request_administrative_review(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sanction-cases/{case_id}/administrative-review", payload, headers
        )

    def decide_administrative_review(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/sanction-cases/{case_id}/administrative-review-decision",
            payload,
            headers,
        )

    def finalize_sanction_case(
        self,
        case_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/sanction-cases/{case_id}/finalize", payload or {}, headers
        )

    def enforce_sanction_case(
        self,
        case_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/sanction-cases/{case_id}/enforce", payload or {}, headers
        )

    def list_penalty_ledger(
        self,
        case_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/sanction-cases/{case_id}/penalty-ledger", params or {}, headers
        )

    def create_cmp_payment(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sanction-cases/{case_id}/cmp-payments", payload, headers
        )

    # ------------------------------------------------------------------
    # Equipment depots
    # ------------------------------------------------------------------

    def create_equipment_depot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/equipment-depots", payload, headers)

    def get_equipment_depot(self, depot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/equipment-depots/{depot_id}", None, headers)

    def list_equipment_depots(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/equipment-depots", params or {}, headers)

    # ------------------------------------------------------------------
    # EBT terminals
    # ------------------------------------------------------------------

    def create_ebt_terminal(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/ebt-terminals", payload, headers)

    def get_ebt_terminal(self, terminal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/ebt-terminals/{terminal_id}", None, headers)

    def list_ebt_terminals(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/ebt-terminals", params or {}, headers)

    # ------------------------------------------------------------------
    # Terminal deployments
    # ------------------------------------------------------------------

    def create_terminal_deployment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/terminal-deployments", payload, headers)

    def get_terminal_deployment(self, deployment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/terminal-deployments/{deployment_id}", None, headers
        )

    def list_terminal_deployments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/terminal-deployments", params or {}, headers)

    def activate_deployment(
        self,
        deployment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/terminal-deployments/{deployment_id}/activate",
            payload or {},
            headers,
        )

    def recall_deployment(
        self,
        deployment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/terminal-deployments/{deployment_id}/recall",
            payload or {},
            headers,
        )

    def return_deployment(
        self,
        deployment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/terminal-deployments/{deployment_id}/return",
            payload or {},
            headers,
        )

    def release_deployment(
        self,
        deployment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/terminal-deployments/{deployment_id}/release",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Equipment orders
    # ------------------------------------------------------------------

    def create_equipment_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/equipment-orders", payload, headers)

    def get_equipment_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/equipment-orders/{order_id}", None, headers)

    def list_equipment_orders(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/equipment-orders", params or {}, headers)

    def place_equipment_order(
        self,
        order_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/equipment-orders/{order_id}/place", payload or {}, headers
        )

    def fulfill_equipment_order(
        self,
        order_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/equipment-orders/{order_id}/fulfill", payload or {}, headers
        )

    def cancel_equipment_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/equipment-orders/{order_id}/cancel", payload, headers
        )


api_client = ApiClient()
