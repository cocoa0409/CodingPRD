"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Administrative clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Yards
    # ------------------------------------------------------------------
    def create_yard(self, payload, headers):
        return self._request("POST", "/yards", payload, headers)

    def get_yard(self, yard_id, headers):
        return self._request("GET", f"/yards/{yard_id}", headers=headers)

    def list_yards(self, headers, params=None):
        return self._request("GET", "/yards", headers=headers, params=params)

    def list_yard_auctions(self, yard_id, headers, params=None):
        return self._request(
            "GET", f"/yards/{yard_id}/auctions", headers=headers, params=params
        )

    def list_yard_loadout_bays(self, yard_id, headers, params=None):
        return self._request(
            "GET", f"/yards/{yard_id}/loadout-bays", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Load-out bays
    # ------------------------------------------------------------------
    def create_loadout_bay(self, payload, headers):
        return self._request("POST", "/loadout-bays", payload, headers)

    def get_loadout_bay(self, bay_id, headers):
        return self._request("GET", f"/loadout-bays/{bay_id}", headers=headers)

    def update_loadout_bay(self, bay_id, payload, headers):
        return self._request("PATCH", f"/loadout-bays/{bay_id}", payload, headers)

    # ------------------------------------------------------------------
    # Consignors
    # ------------------------------------------------------------------
    def create_consignor(self, payload, headers):
        return self._request("POST", "/consignors", payload, headers)

    def get_consignor(self, consignor_id, headers):
        return self._request("GET", f"/consignors/{consignor_id}", headers=headers)

    def list_consignors(self, headers, params=None):
        return self._request("GET", "/consignors", headers=headers, params=params)

    def acknowledge_unreserved_policy(self, consignor_id, headers, payload=None):
        return self._request(
            "POST", f"/consignors/{consignor_id}/policy-ack", payload or {}, headers
        )

    def list_consignor_consignments(self, consignor_id, headers, params=None):
        return self._request(
            "GET",
            f"/consignors/{consignor_id}/consignments",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Consignments
    # ------------------------------------------------------------------
    def create_consignment(self, payload, headers):
        return self._request("POST", "/consignments", payload, headers)

    def get_consignment(self, consignment_id, headers):
        return self._request("GET", f"/consignments/{consignment_id}", headers=headers)

    def submit_consignment(self, consignment_id, headers, payload=None):
        return self._request(
            "POST", f"/consignments/{consignment_id}/submit", payload or {}, headers
        )

    def decide_consignment_intake(self, consignment_id, payload, headers):
        return self._request(
            "POST", f"/consignments/{consignment_id}/intake-decision", payload, headers
        )

    def list_consignment_lots(self, consignment_id, headers, params=None):
        return self._request(
            "GET", f"/consignments/{consignment_id}/lots", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Lots
    # ------------------------------------------------------------------
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def update_lot(self, lot_id, payload, headers):
        return self._request("PATCH", f"/lots/{lot_id}", payload, headers)

    def withdraw_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/withdraw", payload, headers)

    def order_lien_search(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/lien-search", payload, headers)

    def record_lien_result(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/lien-result", payload, headers)

    def release_lien(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/lien-release", payload, headers)

    def hammer_lot(self, lot_id, headers, payload=None):
        return self._request("POST", f"/lots/{lot_id}/hammer", payload or {}, headers)

    def create_condition_report(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/lots/{lot_id}/condition-reports", payload, headers
        )

    def list_lot_condition_reports(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/lots/{lot_id}/condition-reports", headers=headers, params=params
        )

    def list_lot_refurbishment_orders(self, lot_id, headers, params=None):
        return self._request(
            "GET",
            f"/lots/{lot_id}/refurbishment-orders",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Condition reports
    # ------------------------------------------------------------------
    def get_condition_report(self, report_id, headers):
        return self._request("GET", f"/condition-reports/{report_id}", headers=headers)

    def rescore_condition_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/condition-reports/{report_id}/rescore", payload, headers
        )

    def publish_condition_report(self, report_id, headers, payload=None):
        return self._request(
            "POST", f"/condition-reports/{report_id}/publish", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Refurbishment orders
    # ------------------------------------------------------------------
    def create_refurbishment_order(self, payload, headers):
        return self._request("POST", "/refurbishment-orders", payload, headers)

    def get_refurbishment_order(self, order_id, headers):
        return self._request(
            "GET", f"/refurbishment-orders/{order_id}", headers=headers
        )

    def transition_refurbishment_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/refurbishment-orders/{order_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Auctions
    # ------------------------------------------------------------------
    def create_auction(self, payload, headers):
        return self._request("POST", "/auctions", payload, headers)

    def get_auction(self, auction_id, headers):
        return self._request("GET", f"/auctions/{auction_id}", headers=headers)

    def list_auctions(self, headers, params=None):
        return self._request("GET", "/auctions", headers=headers, params=params)

    def reschedule_auction(self, auction_id, payload, headers):
        return self._request(
            "POST", f"/auctions/{auction_id}/reschedule", payload, headers
        )

    def assign_lot_to_auction(self, auction_id, payload, headers):
        return self._request(
            "POST", f"/auctions/{auction_id}/lot-assignments", payload, headers
        )

    def open_auction(self, auction_id, headers, payload=None):
        return self._request(
            "POST", f"/auctions/{auction_id}/open", payload or {}, headers
        )

    def close_auction(self, auction_id, headers, payload=None):
        return self._request(
            "POST", f"/auctions/{auction_id}/close", payload or {}, headers
        )

    def reconcile_auction(self, auction_id, headers, payload=None):
        return self._request(
            "POST", f"/auctions/{auction_id}/reconcile", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Bidders
    # ------------------------------------------------------------------
    def create_bidder(self, payload, headers):
        return self._request("POST", "/bidders", payload, headers)

    def get_bidder(self, bidder_id, headers):
        return self._request("GET", f"/bidders/{bidder_id}", headers=headers)

    def list_bidders(self, headers, params=None):
        return self._request("GET", "/bidders", headers=headers, params=params)

    def create_deposit(self, bidder_id, payload, headers):
        return self._request("POST", f"/bidders/{bidder_id}/deposits", payload, headers)

    def get_bidder_exposure(self, bidder_id, headers, params=None):
        return self._request(
            "GET", f"/bidders/{bidder_id}/exposure", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Bidder registrations
    # ------------------------------------------------------------------
    def create_bidder_registration(self, payload, headers):
        return self._request("POST", "/bidder-registrations", payload, headers)

    def get_bidder_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/bidder-registrations/{registration_id}", headers=headers
        )

    def list_bidder_registrations(self, headers, params=None):
        return self._request(
            "GET", "/bidder-registrations", headers=headers, params=params
        )

    def decide_credit(self, registration_id, payload, headers):
        return self._request(
            "POST",
            f"/bidder-registrations/{registration_id}/credit-decision",
            payload,
            headers,
        )

    def cancel_bidder_registration(self, registration_id, headers, payload=None):
        return self._request(
            "POST",
            f"/bidder-registrations/{registration_id}/cancel",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Bids
    # ------------------------------------------------------------------
    def create_bid(self, payload, headers):
        return self._request("POST", "/bids", payload, headers)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Sales
    # ------------------------------------------------------------------
    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/sales/{sale_id}", headers=headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/sales", headers=headers, params=params)

    def counteroffer_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/counteroffer", payload, headers)

    def respond_to_counteroffer(self, sale_id, payload, headers):
        return self._request(
            "POST", f"/sales/{sale_id}/counter-response", payload, headers
        )

    def reject_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/reject", payload, headers)

    def list_sale_consignor_settlements(self, sale_id, headers, params=None):
        return self._request(
            "GET",
            f"/sales/{sale_id}/consignor-settlements",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_settlement_preview(self, invoice_id, headers, params=None):
        return self._request(
            "GET",
            f"/invoices/{invoice_id}/settlement-preview",
            headers=headers,
            params=params,
        )

    def finalize_invoice(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/invoices/{invoice_id}/finalize", payload or {}, headers
        )

    def waive_invoice_fee(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/fee-waiver", payload, headers
        )

    def authorize_release(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/invoices/{invoice_id}/authorize-release", payload or {}, headers
        )

    def default_invoice(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/invoices/{invoice_id}/default", payload or {}, headers
        )

    def abandon_invoice(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/invoices/{invoice_id}/abandon", payload or {}, headers
        )

    def list_invoice_payments(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/invoices/{invoice_id}/payments", headers=headers, params=params
        )

    def list_invoice_export_packets(self, invoice_id, headers, params=None):
        return self._request(
            "GET",
            f"/invoices/{invoice_id}/export-packets",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    # ------------------------------------------------------------------
    # Export document packets
    # ------------------------------------------------------------------
    def create_export_packet(self, payload, headers):
        return self._request("POST", "/export-packets", payload, headers)

    def get_export_packet(self, packet_id, headers):
        return self._request("GET", f"/export-packets/{packet_id}", headers=headers)

    def transition_export_packet(self, packet_id, payload, headers):
        return self._request(
            "POST", f"/export-packets/{packet_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Load-out slots
    # ------------------------------------------------------------------
    def create_loadout_slot(self, payload, headers):
        return self._request("POST", "/loadout-slots", payload, headers)

    def get_loadout_slot(self, slot_id, headers):
        return self._request("GET", f"/loadout-slots/{slot_id}", headers=headers)

    def list_loadout_slots(self, headers, params=None):
        return self._request("GET", "/loadout-slots", headers=headers, params=params)

    def check_in_loadout_slot(self, slot_id, payload, headers):
        return self._request(
            "POST", f"/loadout-slots/{slot_id}/check-in", payload, headers
        )

    def complete_loadout_slot(self, slot_id, headers, payload=None):
        return self._request(
            "POST", f"/loadout-slots/{slot_id}/complete", payload or {}, headers
        )

    def cancel_loadout_slot(self, slot_id, payload, headers):
        return self._request(
            "POST", f"/loadout-slots/{slot_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Consignor settlements
    # ------------------------------------------------------------------
    def create_consignor_settlement(self, payload, headers):
        return self._request("POST", "/consignor-settlements", payload, headers)

    def get_consignor_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"/consignor-settlements/{settlement_id}", headers=headers
        )


api_client = ApiClient()
