"""API client: one method per endpoint defined in the PRD.

All endpoints are mounted under the /api prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Inspection facilities
    # ------------------------------------------------------------------
    def create_inspection_facility(self, payload, headers):
        return self._request("POST", "/api/inspection-facilities", payload, headers)

    # ------------------------------------------------------------------
    # Listings
    # ------------------------------------------------------------------
    def create_listing(self, payload, headers):
        return self._request("POST", "/api/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/api/listings/{listing_id}", headers=headers)

    def run_valuation(self, listing_id, payload, headers):
        return self._request("POST", f"/api/listings/{listing_id}/valuation",
                             payload, headers)

    def activate_listing(self, listing_id, headers):
        return self._request("POST", f"/api/listings/{listing_id}/activate", {}, headers)

    # ------------------------------------------------------------------
    # Buyers
    # ------------------------------------------------------------------
    def create_buyer(self, payload, headers):
        return self._request("POST", "/api/buyers", payload, headers)

    def qualify_buyer(self, buyer_id, payload, headers):
        return self._request("POST", f"/api/buyers/{buyer_id}/qualify", payload, headers)

    # ------------------------------------------------------------------
    # Comparable sales
    # ------------------------------------------------------------------
    def create_comparable_sale(self, payload, headers):
        return self._request("POST", "/api/comparable-sales", payload, headers)

    def list_comparable_sales(self, headers, params=None):
        return self._request("GET", "/api/comparable-sales", headers=headers, params=params)

    def get_comparable_sale(self, comp_id, headers):
        return self._request("GET", f"/api/comparable-sales/{comp_id}", headers=headers)

    # ------------------------------------------------------------------
    # Letters of intent
    # ------------------------------------------------------------------
    def create_loi(self, payload, headers):
        return self._request("POST", "/api/lois", payload, headers)

    def list_lois(self, headers, params=None):
        return self._request("GET", "/api/lois", headers=headers, params=params)

    def get_loi(self, loi_id, headers):
        return self._request("GET", f"/api/lois/{loi_id}", headers=headers)

    def counter_loi(self, loi_id, payload, headers):
        return self._request("POST", f"/api/lois/{loi_id}/counter", payload, headers)

    def accept_loi(self, loi_id, headers):
        return self._request("POST", f"/api/lois/{loi_id}/accept", {}, headers)

    def withdraw_loi(self, loi_id, headers):
        return self._request("POST", f"/api/lois/{loi_id}/withdraw", {}, headers)

    def ack_disclosure(self, loi_id, payload, headers):
        return self._request("POST", f"/api/lois/{loi_id}/disclosure/ack",
                             payload, headers)

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------
    def list_transactions(self, headers, params=None):
        return self._request("GET", "/api/transactions", headers=headers, params=params)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/api/transactions/{transaction_id}", headers=headers)

    def patch_delivery_conditions(self, transaction_id, payload, headers):
        return self._request("PATCH",
                             f"/api/transactions/{transaction_id}/delivery-conditions",
                             payload, headers)

    def accept_as_is(self, transaction_id, headers):
        return self._request("POST", f"/api/transactions/{transaction_id}/accept-as-is",
                             {}, headers)

    def terminate_transaction(self, transaction_id, payload, headers):
        return self._request("POST", f"/api/transactions/{transaction_id}/terminate",
                             payload, headers)

    def close_transaction(self, transaction_id, headers):
        return self._request("POST", f"/api/transactions/{transaction_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Escrow deposits
    # ------------------------------------------------------------------
    def list_escrow_deposits(self, headers, params=None):
        return self._request("GET", "/api/escrow-deposits", headers=headers, params=params)

    def get_escrow_deposit(self, escrow_id, headers):
        return self._request("GET", f"/api/escrow-deposits/{escrow_id}", headers=headers)

    def fund_escrow_deposit(self, escrow_id, payload, headers):
        return self._request("POST", f"/api/escrow-deposits/{escrow_id}/fund",
                             payload, headers)

    # ------------------------------------------------------------------
    # Inspection bookings
    # ------------------------------------------------------------------
    def create_inspection_booking(self, payload, headers):
        return self._request("POST", "/api/inspection-bookings", payload, headers)

    def list_inspection_bookings(self, headers, params=None):
        return self._request("GET", "/api/inspection-bookings", headers=headers,
                             params=params)

    def get_inspection_booking(self, booking_id, headers):
        return self._request("GET", f"/api/inspection-bookings/{booking_id}",
                             headers=headers)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/api/inspection-bookings/{booking_id}/confirm",
                             {}, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/api/inspection-bookings/{booking_id}/complete",
                             {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/api/inspection-bookings/{booking_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Discrepancy items
    # ------------------------------------------------------------------
    def raise_discrepancy_item(self, transaction_id, payload, headers):
        return self._request("POST",
                             f"/api/transactions/{transaction_id}/discrepancy-items",
                             payload, headers)

    def list_discrepancy_items(self, headers, params=None):
        return self._request("GET", "/api/discrepancy-items", headers=headers,
                             params=params)

    def get_discrepancy_item(self, item_id, headers):
        return self._request("GET", f"/api/discrepancy-items/{item_id}", headers=headers)

    def counter_discrepancy_item(self, item_id, payload, headers):
        return self._request("POST", f"/api/discrepancy-items/{item_id}/counter",
                             payload, headers)

    def commit_repair(self, item_id, headers):
        return self._request("POST", f"/api/discrepancy-items/{item_id}/commit-repair",
                             {}, headers)

    def agree_credit(self, item_id, headers):
        return self._request("POST", f"/api/discrepancy-items/{item_id}/agree-credit",
                             {}, headers)

    def waive_discrepancy_item(self, item_id, headers):
        return self._request("POST", f"/api/discrepancy-items/{item_id}/waive",
                             {}, headers)


api_client = ApiClient()
