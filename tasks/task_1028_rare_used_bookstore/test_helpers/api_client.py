"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Patron ──
    def create_patron(self, payload, headers):
        return self._request("POST", "/patrons", payload, headers)

    def get_patron(self, patron_id, headers):
        return self._request("GET", f"/patrons/{patron_id}", headers=headers)

    # ── IntakeLot ──
    def create_intake_lot(self, payload, headers):
        return self._request("POST", "/intake-lots", payload, headers)

    def get_intake_lot(self, lot_id, headers):
        return self._request("GET", f"/intake-lots/{lot_id}", headers=headers)

    def create_book_item(self, lot_id, payload, headers):
        return self._request("POST", f"/intake-lots/{lot_id}/book-items", payload, headers)

    def settle_lot(self, lot_id, headers):
        return self._request("POST", f"/intake-lots/{lot_id}/settle", {}, headers)

    def reject_lot(self, lot_id, headers):
        return self._request("POST", f"/intake-lots/{lot_id}/reject", {}, headers)

    # ── BookItem ──
    def get_book_item(self, book_id, headers):
        return self._request("GET", f"/book-items/{book_id}", headers=headers)

    def list_book_items(self, headers, params=None):
        return self._request("GET", "/book-items", headers=headers, params=params)

    def grade_book_item(self, book_id, payload, headers):
        return self._request("POST", f"/book-items/{book_id}/grade", payload, headers)

    def create_appraisal(self, book_id, payload, headers):
        return self._request("POST", f"/book-items/{book_id}/appraisals", payload, headers)

    def list_appraisals(self, book_id, headers, params=None):
        return self._request("GET", f"/book-items/{book_id}/appraisals", headers=headers, params=params)

    def create_listing(self, book_id, payload, headers):
        return self._request("POST", f"/book-items/{book_id}/listing", payload, headers)

    def get_listing(self, book_id, headers):
        return self._request("GET", f"/book-items/{book_id}/listing", headers=headers)

    # ── ConsignmentAgreement ──
    def create_consignment_agreement(self, payload, headers):
        return self._request("POST", "/consignment-agreements", payload, headers)

    def get_consignment_agreement(self, agreement_id, headers):
        return self._request("GET", f"/consignment-agreements/{agreement_id}", headers=headers)

    def list_consignment_agreements(self, headers, params=None):
        return self._request("GET", "/consignment-agreements", headers=headers, params=params)

    def amend_consignment_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/consignment-agreements/{agreement_id}/amend", payload, headers)

    def activate_consignment_agreement(self, agreement_id, headers):
        return self._request("POST", f"/consignment-agreements/{agreement_id}/activate", {}, headers)

    # ── CatalogListing ──
    def update_catalog_listing(self, listing_id, payload, headers):
        return self._request("PATCH", f"/catalog-listings/{listing_id}", payload, headers)

    # ── BuybackOffer ──
    def create_buyback_offer(self, payload, headers):
        return self._request("POST", "/buyback-offers", payload, headers)

    def get_buyback_offer(self, offer_id, headers):
        return self._request("GET", f"/buyback-offers/{offer_id}", headers=headers)

    def list_buyback_offers(self, headers, params=None):
        return self._request("GET", "/buyback-offers", headers=headers, params=params)

    def accept_buyback_offer(self, offer_id, headers):
        return self._request("POST", f"/buyback-offers/{offer_id}/accept", {}, headers)

    def void_buyback_offer(self, offer_id, headers):
        return self._request("POST", f"/buyback-offers/{offer_id}/void", {}, headers)

    # ── FairEvent / BoothSlot ──
    def create_fair_event(self, payload, headers):
        return self._request("POST", "/fair-events", payload, headers)

    def get_fair_event(self, fair_id, headers):
        return self._request("GET", f"/fair-events/{fair_id}", headers=headers)

    def create_booth_slot(self, fair_id, payload, headers):
        return self._request("POST", f"/fair-events/{fair_id}/booth-slots", payload, headers)

    def list_booth_slots(self, fair_id, headers, params=None):
        return self._request("GET", f"/fair-events/{fair_id}/booth-slots", headers=headers, params=params)

    # ── SaleOrder / Shipment ──
    def create_sale_order(self, payload, headers):
        return self._request("POST", "/sale-orders", payload, headers)

    def get_sale_order(self, order_id, headers):
        return self._request("GET", f"/sale-orders/{order_id}", headers=headers)

    def confirm_sale_order(self, order_id, headers):
        return self._request("POST", f"/sale-orders/{order_id}/confirm", {}, headers)

    def refund_sale_order(self, order_id, headers):
        return self._request("POST", f"/sale-orders/{order_id}/refund", {}, headers)

    def create_shipment(self, order_id, payload, headers):
        return self._request("POST", f"/sale-orders/{order_id}/shipment", payload, headers)

    def get_shipment(self, order_id, headers):
        return self._request("GET", f"/sale-orders/{order_id}/shipment", headers=headers)


api_client = ApiClient()
