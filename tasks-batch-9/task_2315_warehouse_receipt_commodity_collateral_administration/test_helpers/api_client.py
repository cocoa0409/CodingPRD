"""
Typed API client: one method per declared endpoint of the warehouse receipt &
commodity collateral API.

Every method returns the raw requests.Response so tests can assert HTTP status
codes and error envelopes.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per endpoint declared by the API contract."""

    # -- test-driving surface -----------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -- Warehouse ----------------------------------------------------------
    def create_warehouse(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/warehouses", payload, headers)

    def list_warehouses(self, params: Optional[Dict] = None, headers: Optional[Dict] = None):
        return self._request("GET", "/warehouses", params, headers)

    def get_warehouse(self, warehouse_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/warehouses/{warehouse_id}", None, headers)

    def patch_warehouse_financials(
        self, warehouse_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "PATCH", f"/warehouses/{warehouse_id}/financials", payload, headers
        )

    def license_decision(
        self, warehouse_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/warehouses/{warehouse_id}/license-decision", payload, headers
        )

    def insolvency_action(
        self, warehouse_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/warehouses/{warehouse_id}/insolvency", payload, headers
        )

    def get_position_summary(self, warehouse_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/warehouses/{warehouse_id}/position-summary", None, headers
        )

    # -- Party --------------------------------------------------------------
    def create_party(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/parties", payload, headers)

    def list_parties(self, params: Optional[Dict] = None, headers: Optional[Dict] = None):
        return self._request("GET", "/parties", params, headers)

    def get_party(self, party_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/parties/{party_id}", None, headers)

    def patch_party_credit_line(
        self, party_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request("PATCH", f"/parties/{party_id}/credit-line", payload, headers)

    # -- StorageAgreement ---------------------------------------------------
    def create_storage_agreement(
        self, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request("POST", "/storage-agreements", payload, headers)

    def list_storage_agreements(
        self, params: Optional[Dict] = None, headers: Optional[Dict] = None
    ):
        return self._request("GET", "/storage-agreements", params, headers)

    def get_storage_agreement(self, agreement_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/storage-agreements/{agreement_id}", None, headers)

    def terminate_storage_agreement(
        self, agreement_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/storage-agreements/{agreement_id}/terminate", payload, headers
        )

    # -- Bin ----------------------------------------------------------------
    def create_bin(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/bins", payload, headers)

    def list_bins(self, params: Optional[Dict] = None, headers: Optional[Dict] = None):
        return self._request("GET", "/bins", params, headers)

    def get_bin(self, bin_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/bins/{bin_id}", None, headers)

    def assess_bin_condition(
        self, bin_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/bins/{bin_id}/condition-assessment", payload, headers
        )

    # -- DepositTicket ------------------------------------------------------
    def create_deposit_ticket(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/deposit-tickets", payload, headers)

    def list_deposit_tickets(
        self, params: Optional[Dict] = None, headers: Optional[Dict] = None
    ):
        return self._request("GET", "/deposit-tickets", params, headers)

    def get_deposit_ticket(self, ticket_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/deposit-tickets/{ticket_id}", None, headers)

    def accept_deposit_ticket(
        self, ticket_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/deposit-tickets/{ticket_id}/accept", payload, headers
        )

    def reject_deposit_ticket(
        self, ticket_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/deposit-tickets/{ticket_id}/reject", payload, headers
        )

    # -- WarehouseReceipt ---------------------------------------------------
    def create_receipt(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/receipts", payload, headers)

    def list_receipts(self, params: Optional[Dict] = None, headers: Optional[Dict] = None):
        return self._request("GET", "/receipts", params, headers)

    def get_receipt(self, receipt_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/receipts/{receipt_id}", None, headers)

    def transfer_receipt(
        self, receipt_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request("POST", f"/receipts/{receipt_id}/transfer", payload, headers)

    def void_receipt(
        self, receipt_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request("POST", f"/receipts/{receipt_id}/void", payload, headers)

    # -- CollateralLien -----------------------------------------------------
    def create_collateral_lien(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/collateral-liens", payload, headers)

    def list_collateral_liens(
        self, params: Optional[Dict] = None, headers: Optional[Dict] = None
    ):
        return self._request("GET", "/collateral-liens", params, headers)

    def get_collateral_lien(self, lien_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/collateral-liens/{lien_id}", None, headers)

    def perfect_lien(
        self, lien_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request("POST", f"/collateral-liens/{lien_id}/perfect", payload, headers)

    def release_lien(
        self, lien_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request("POST", f"/collateral-liens/{lien_id}/release", payload, headers)

    def revalue_lien(
        self, lien_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request("POST", f"/collateral-liens/{lien_id}/revalue", payload, headers)

    # -- PositionReport -----------------------------------------------------
    def create_position_report(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/position-reports", payload, headers)

    def list_position_reports(
        self, params: Optional[Dict] = None, headers: Optional[Dict] = None
    ):
        return self._request("GET", "/position-reports", params, headers)

    def get_position_report(self, report_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/position-reports/{report_id}", None, headers)

    def submit_position_report(
        self, report_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/position-reports/{report_id}/submit", payload, headers
        )

    def examine_position_report(
        self, report_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/position-reports/{report_id}/examine", payload, headers
        )

    # -- DeliveryOrder ------------------------------------------------------
    def create_delivery_order(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/delivery-orders", payload, headers)

    def list_delivery_orders(
        self, params: Optional[Dict] = None, headers: Optional[Dict] = None
    ):
        return self._request("GET", "/delivery-orders", params, headers)

    def get_delivery_order(self, order_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/delivery-orders/{order_id}", None, headers)

    def load_delivery_order(
        self, order_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request("POST", f"/delivery-orders/{order_id}/load", payload, headers)

    def settle_delivery_order(
        self, order_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request("POST", f"/delivery-orders/{order_id}/settle", payload, headers)

    def cancel_delivery_order(
        self, order_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request("POST", f"/delivery-orders/{order_id}/cancel", payload, headers)

    # -- IndemnityClaim -----------------------------------------------------
    def create_indemnity_claim(self, payload: Dict[str, Any], headers: Optional[Dict] = None):
        return self._request("POST", "/indemnity-claims", payload, headers)

    def list_indemnity_claims(
        self, params: Optional[Dict] = None, headers: Optional[Dict] = None
    ):
        return self._request("GET", "/indemnity-claims", params, headers)

    def get_indemnity_claim(self, claim_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/indemnity-claims/{claim_id}", None, headers)

    def adjudicate_indemnity_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/indemnity-claims/{claim_id}/adjudicate", payload, headers
        )
