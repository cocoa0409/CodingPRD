"""One method per documented endpoint of the Rent-To-Own Store API.

All endpoints are mounted directly at the server root; there is no version or
namespace prefix. Every method returns the raw response so that tests can
assert on status codes as well as bodies.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

JsonDict = Dict[str, Any]


class RtoApiClient(GenericApiClient):
    """Thin transport wrapper: no business logic lives here."""

    # ------------------------------------------------------------------
    # The logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: JsonDict) -> requests.Response:
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def get_clock(self, headers: JsonDict) -> requests.Response:
        return self._request("GET", "/_clock", headers=headers)

    # ------------------------------------------------------------------
    # Statutory rules
    # ------------------------------------------------------------------

    def create_state_rule(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/state-rto-rules", payload, headers)

    def get_state_rule(self, rule_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/state-rto-rules/{rule_id}", headers=headers)

    def list_state_rules(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/state-rto-rules", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Stores
    # ------------------------------------------------------------------

    def create_store(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def list_stores(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/stores", headers=headers, params=params)

    def run_day_close(
        self, store_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/stores/{store_id}/day-close", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Inventory units
    # ------------------------------------------------------------------

    def create_inventory_unit(
        self, store_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/stores/{store_id}/inventory-units", payload, headers
        )

    def list_store_inventory_units(
        self, store_id: str, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/stores/{store_id}/inventory-units", headers=headers, params=params
        )

    def get_inventory_unit(self, unit_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/inventory-units/{unit_id}", headers=headers)

    def list_inventory_units(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/inventory-units", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Delivery crews
    # ------------------------------------------------------------------

    def create_delivery_crew(
        self, store_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/stores/{store_id}/delivery-crews", payload, headers
        )

    def list_delivery_crews(
        self, store_id: str, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/stores/{store_id}/delivery-crews", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Customers, references and verification
    # ------------------------------------------------------------------

    def create_customer(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/customers", headers=headers, params=params)

    def create_customer_reference(
        self, customer_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/customers/{customer_id}/references", payload, headers
        )

    def list_customer_references(
        self, customer_id: str, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/customers/{customer_id}/references", headers=headers, params=params
        )

    def check_customer_reference(
        self, reference_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/customer-references/{reference_id}/check", payload, headers
        )

    def verify_customer(
        self, customer_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request("POST", f"/customers/{customer_id}/verify", payload, headers)

    # ------------------------------------------------------------------
    # Loyalty ledger
    # ------------------------------------------------------------------

    def get_loyalty_ledger_entry(
        self, entry_id: str, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "GET", f"/loyalty-ledger-entries/{entry_id}", headers=headers
        )

    def list_loyalty_ledger_entries(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/loyalty-ledger-entries", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Agreements
    # ------------------------------------------------------------------

    def create_agreement(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/agreements", payload, headers)

    def get_agreement(self, agreement_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def list_agreements(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/agreements", headers=headers, params=params)

    def get_agreement_disclosure(
        self, agreement_id: str, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "GET", f"/agreements/{agreement_id}/disclosure", headers=headers
        )

    # ------------------------------------------------------------------
    # Renewal payments and reversal
    # ------------------------------------------------------------------

    def post_renewal_payment(
        self, agreement_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/agreements/{agreement_id}/renewal-payments", payload, headers
        )

    def list_renewal_payments(
        self, agreement_id: str, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/agreements/{agreement_id}/renewal-payments",
            headers=headers,
            params=params,
        )

    def reverse_renewal_payment(
        self, payment_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/renewal-payments/{payment_id}/reverse", payload, headers
        )

    def list_reinstatement_windows(
        self, agreement_id: str, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/agreements/{agreement_id}/reinstatement-windows",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Delivery orders
    # ------------------------------------------------------------------

    def create_delivery_order(
        self, agreement_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/agreements/{agreement_id}/delivery-orders", payload, headers
        )

    def get_delivery_order(self, order_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/delivery-orders/{order_id}", headers=headers)

    def list_delivery_orders(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/delivery-orders", headers=headers, params=params)

    def complete_delivery_order(
        self, order_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/delivery-orders/{order_id}/complete", payload, headers
        )

    def fail_delivery_attempt(
        self, order_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/delivery-orders/{order_id}/fail-attempt", payload, headers
        )

    # ------------------------------------------------------------------
    # Service tickets
    # ------------------------------------------------------------------

    def create_service_ticket(
        self, agreement_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/agreements/{agreement_id}/service-tickets", payload, headers
        )

    def get_service_ticket(self, ticket_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/service-tickets/{ticket_id}", headers=headers)

    def list_service_tickets(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/service-tickets", headers=headers, params=params)

    def issue_swap(
        self, ticket_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/issue-swap", payload, headers
        )

    def resolve_service_ticket(
        self, ticket_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/service-tickets/{ticket_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------------
    # Returns and grading
    # ------------------------------------------------------------------

    def return_agreement(
        self, agreement_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/agreements/{agreement_id}/return", payload, headers
        )

    def get_return_inspection(
        self, inspection_id: str, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "GET", f"/return-inspections/{inspection_id}", headers=headers
        )

    def list_return_inspections(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/return-inspections", headers=headers, params=params)

    def grade_return_inspection(
        self, inspection_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/return-inspections/{inspection_id}/grade", payload, headers
        )

    # ------------------------------------------------------------------
    # Early purchase
    # ------------------------------------------------------------------

    def issue_early_purchase_quote(
        self, agreement_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/agreements/{agreement_id}/early-purchase-quotes", payload, headers
        )

    def list_early_purchase_quotes(
        self, agreement_id: str, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/agreements/{agreement_id}/early-purchase-quotes",
            headers=headers,
            params=params,
        )

    def accept_early_purchase_quote(
        self, quote_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/early-purchase-quotes/{quote_id}/accept", payload, headers
        )

    # ------------------------------------------------------------------
    # Collections and repossession
    # ------------------------------------------------------------------

    def log_collection_contact(
        self, agreement_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/agreements/{agreement_id}/collection-contacts", payload, headers
        )

    def list_collection_contacts(
        self, agreement_id: str, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/agreements/{agreement_id}/collection-contacts",
            headers=headers,
            params=params,
        )

    def repossess_agreement(
        self, agreement_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/agreements/{agreement_id}/repossess", payload, headers
        )
