"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/rack/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- terminals ---
    def create_terminal(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rack/terminals", payload, headers)

    def get_terminal(self, terminal_id: str, headers: Dict):
        return self._request("GET", f"/rack/terminals/{terminal_id}", headers=headers)

    def list_terminals(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/rack/terminals", headers=headers, params=params)

    def freeze_terminal(self, terminal_id: str, headers: Dict):
        return self._request(
            "POST", f"/rack/terminals/{terminal_id}/freeze", {}, headers,
        )

    def unfreeze_terminal(self, terminal_id: str, headers: Dict):
        return self._request(
            "POST", f"/rack/terminals/{terminal_id}/unfreeze", {}, headers,
        )

    def adjust_inventory(self, terminal_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/rack/terminals/{terminal_id}/inventory/adjust",
            payload, headers,
        )

    # --- products ---
    def create_product(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rack/products", payload, headers)

    def get_product(self, product_id: str, headers: Dict):
        return self._request("GET", f"/rack/products/{product_id}", headers=headers)

    def list_products(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/rack/products", headers=headers, params=params)

    # --- customers ---
    def create_customer(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rack/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict):
        return self._request("GET", f"/rack/customers/{customer_id}", headers=headers)

    def list_customers(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/rack/customers", headers=headers, params=params)

    def place_hold(self, customer_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/rack/customers/{customer_id}/place-hold", payload, headers,
        )

    def release_hold(self, customer_id: str, headers: Dict):
        return self._request(
            "POST", f"/rack/customers/{customer_id}/release-hold", {}, headers,
        )

    # --- supply contracts ---
    def create_supply_contract(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rack/supply-contracts", payload, headers)

    def get_supply_contract(self, contract_id: str, headers: Dict):
        return self._request(
            "GET", f"/rack/supply-contracts/{contract_id}", headers=headers,
        )

    def list_supply_contracts(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/rack/supply-contracts", headers=headers, params=params,
        )

    def activate_supply_contract(self, contract_id: str, headers: Dict):
        return self._request(
            "POST", f"/rack/supply-contracts/{contract_id}/activate", {}, headers,
        )

    def close_supply_contract(self, contract_id: str, payload: Optional[Dict],
                              headers: Dict):
        return self._request(
            "POST", f"/rack/supply-contracts/{contract_id}/close",
            payload or {}, headers,
        )

    # --- lifting rights ---
    def create_lifting_right(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rack/lifting-rights", payload, headers)

    def get_lifting_right(self, right_id: str, headers: Dict):
        return self._request(
            "GET", f"/rack/lifting-rights/{right_id}", headers=headers,
        )

    def list_lifting_rights(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/rack/lifting-rights", headers=headers, params=params,
        )

    def suspend_lifting_right(self, right_id: str, headers: Dict):
        return self._request(
            "POST", f"/rack/lifting-rights/{right_id}/suspend", {}, headers,
        )

    def reinstate_lifting_right(self, right_id: str, headers: Dict):
        return self._request(
            "POST", f"/rack/lifting-rights/{right_id}/reinstate", {}, headers,
        )

    # --- price schedules ---
    def create_price_schedule(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rack/price-schedules", payload, headers)

    def get_price_schedule(self, schedule_id: str, headers: Dict):
        return self._request(
            "GET", f"/rack/price-schedules/{schedule_id}", headers=headers,
        )

    def list_price_schedules(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/rack/price-schedules", headers=headers, params=params,
        )

    def publish_price_schedule(self, schedule_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/rack/price-schedules/{schedule_id}/publish",
            payload, headers,
        )

    def void_price_schedule(self, schedule_id: str, headers: Dict):
        return self._request(
            "POST", f"/rack/price-schedules/{schedule_id}/void", {}, headers,
        )

    # --- allocation notices ---
    def create_allocation_notice(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rack/allocation-notices", payload, headers)

    def get_allocation_notice(self, notice_id: str, headers: Dict):
        return self._request(
            "GET", f"/rack/allocation-notices/{notice_id}", headers=headers,
        )

    def list_allocation_notices(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/rack/allocation-notices", headers=headers, params=params,
        )

    def publish_allocation_notice(self, notice_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/rack/allocation-notices/{notice_id}/publish",
            payload, headers,
        )

    # --- exchange agreements ---
    def create_exchange_agreement(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rack/exchange-agreements", payload, headers)

    def get_exchange_agreement(self, agreement_id: str, headers: Dict):
        return self._request(
            "GET", f"/rack/exchange-agreements/{agreement_id}", headers=headers,
        )

    def list_exchange_agreements(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/rack/exchange-agreements", headers=headers, params=params,
        )

    def activate_exchange_agreement(self, agreement_id: str, headers: Dict):
        return self._request(
            "POST", f"/rack/exchange-agreements/{agreement_id}/activate",
            {}, headers,
        )

    def suspend_exchange_agreement(self, agreement_id: str, headers: Dict):
        return self._request(
            "POST", f"/rack/exchange-agreements/{agreement_id}/suspend",
            {}, headers,
        )

    def reinstate_exchange_agreement(self, agreement_id: str, headers: Dict):
        return self._request(
            "POST", f"/rack/exchange-agreements/{agreement_id}/reinstate",
            {}, headers,
        )

    def terminate_exchange_agreement(self, agreement_id: str, headers: Dict):
        return self._request(
            "POST", f"/rack/exchange-agreements/{agreement_id}/terminate",
            {}, headers,
        )

    # --- lifting tickets ---
    def create_lifting_ticket(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rack/lifting-tickets", payload, headers)

    def get_lifting_ticket(self, ticket_id: str, headers: Dict):
        return self._request(
            "GET", f"/rack/lifting-tickets/{ticket_id}", headers=headers,
        )

    def list_lifting_tickets(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/rack/lifting-tickets", headers=headers, params=params,
        )

    def post_bol(self, ticket_id: str, headers: Dict):
        return self._request(
            "POST", f"/rack/lifting-tickets/{ticket_id}/post-bol", {}, headers,
        )

    def reverse_bol(self, ticket_id: str, headers: Dict):
        return self._request(
            "POST", f"/rack/lifting-tickets/{ticket_id}/reverse-bol", {}, headers,
        )

    def cancel_lifting_ticket(self, ticket_id: str, headers: Dict):
        return self._request(
            "POST", f"/rack/lifting-tickets/{ticket_id}/cancel", {}, headers,
        )

    def invoice_lifting_ticket(self, ticket_id: str, headers: Dict):
        return self._request(
            "POST", f"/rack/lifting-tickets/{ticket_id}/invoice", {}, headers,
        )

    # --- BOL events (read-only audit) ---
    def get_bol_event(self, event_id: str, headers: Dict):
        return self._request("GET", f"/rack/bol-events/{event_id}", headers=headers)

    def list_bol_events(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/rack/bol-events", headers=headers, params=params)

    # --- tax jurisdiction rules ---
    def create_tax_rule(self, payload: Dict, headers: Dict):
        return self._request("POST", "/rack/tax-rules", payload, headers)

    def get_tax_rule(self, rule_id: str, headers: Dict):
        return self._request("GET", f"/rack/tax-rules/{rule_id}", headers=headers)

    def list_tax_rules(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/rack/tax-rules", headers=headers, params=params)

    # --- credit hold log (read-only audit) ---
    def get_credit_hold_log(self, log_id: str, headers: Dict):
        return self._request(
            "GET", f"/rack/credit-hold-logs/{log_id}", headers=headers,
        )

    def list_credit_hold_logs(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/rack/credit-hold-logs", headers=headers, params=params,
        )


api_client = ApiClient()
