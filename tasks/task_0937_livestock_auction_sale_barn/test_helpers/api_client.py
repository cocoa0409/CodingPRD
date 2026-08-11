"""API client: one method per endpoint of the sale barn API.

Every path is mounted under the /sale-barn prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/sale-barn"


class ApiClient(GenericApiClient):
    # ---- logical clock -------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- parties -------------------------------------------------------
    def create_party(self, payload, headers):
        return self._request("POST", f"{BASE}/parties", payload, headers)

    def get_party(self, party_id, headers):
        return self._request("GET", f"{BASE}/parties/{party_id}", headers=headers)

    def get_party_raw(self, party_id, headers):
        """GET a party with caller-supplied (possibly incomplete) headers."""
        return self._request("GET", f"{BASE}/parties/{party_id}", headers=headers)

    def set_party_status(self, party_id, payload, headers):
        return self._request("POST", f"{BASE}/parties/{party_id}/status", payload, headers)

    # ---- sale days -----------------------------------------------------
    def create_sale_day(self, payload, headers):
        return self._request("POST", f"{BASE}/sale-days", payload, headers)

    def get_sale_day(self, sale_day_id, headers):
        return self._request("GET", f"{BASE}/sale-days/{sale_day_id}", headers=headers)

    def advance_sale_day(self, sale_day_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/sale-days/{sale_day_id}/advance", payload, headers
        )

    def close_sale_day(self, sale_day_id, headers):
        return self._request("POST", f"{BASE}/sale-days/{sale_day_id}/close", {}, headers)

    # ---- pens ----------------------------------------------------------
    def create_pen(self, payload, headers):
        return self._request("POST", f"{BASE}/pens", payload, headers)

    def get_pen(self, pen_id, headers):
        return self._request("GET", f"{BASE}/pens/{pen_id}", headers=headers)

    def set_pen_status(self, pen_id, payload, headers):
        return self._request("POST", f"{BASE}/pens/{pen_id}/status", payload, headers)

    # ---- scales --------------------------------------------------------
    def create_scale(self, payload, headers):
        return self._request("POST", f"{BASE}/scales", payload, headers)

    def get_scale(self, scale_id, headers):
        return self._request("GET", f"{BASE}/scales/{scale_id}", headers=headers)

    # ---- drover crews --------------------------------------------------
    def create_drover_crew(self, payload, headers):
        return self._request("POST", f"{BASE}/drover-crews", payload, headers)

    def get_drover_crew(self, crew_id, headers):
        return self._request("GET", f"{BASE}/drover-crews/{crew_id}", headers=headers)

    def set_crew_duty(self, crew_id, payload, headers):
        return self._request("POST", f"{BASE}/drover-crews/{crew_id}/duty", payload, headers)

    # ---- consignments --------------------------------------------------
    def create_consignment(self, payload, headers):
        return self._request("POST", f"{BASE}/consignments", payload, headers)

    def get_consignment(self, consignment_id, headers):
        return self._request("GET", f"{BASE}/consignments/{consignment_id}", headers=headers)

    def list_consignments(self, headers, params=None):
        return self._request("GET", f"{BASE}/consignments", headers=headers, params=params)

    def check_in_consignment(self, consignment_id, headers):
        return self._request(
            "POST", f"{BASE}/consignments/{consignment_id}/check-in", {}, headers
        )

    def report_loss(self, consignment_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/consignments/{consignment_id}/losses", payload, headers
        )

    # ---- lots ----------------------------------------------------------
    def create_lot(self, payload, headers):
        return self._request("POST", f"{BASE}/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"{BASE}/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", f"{BASE}/lots", headers=headers, params=params)

    def assign_pen(self, lot_id, payload, headers):
        return self._request("POST", f"{BASE}/lots/{lot_id}/assign-pen", payload, headers)

    def mark_lot_ready(self, lot_id, headers):
        return self._request("POST", f"{BASE}/lots/{lot_id}/mark-ready", {}, headers)

    def enter_ring(self, lot_id, headers):
        return self._request("POST", f"{BASE}/lots/{lot_id}/enter-ring", {}, headers)

    def hammer_down(self, lot_id, payload, headers):
        return self._request("POST", f"{BASE}/lots/{lot_id}/hammer-down", payload, headers)

    def no_sale_lot(self, lot_id, headers):
        return self._request("POST", f"{BASE}/lots/{lot_id}/no-sale", {}, headers)

    def re_ring_lot(self, lot_id, headers):
        return self._request("POST", f"{BASE}/lots/{lot_id}/re-ring", {}, headers)

    def quarantine_lot(self, lot_id, payload, headers):
        return self._request("POST", f"{BASE}/lots/{lot_id}/quarantine", payload, headers)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"{BASE}/lots/{lot_id}/release", {}, headers)

    # ---- weigh tickets -------------------------------------------------
    def create_weigh_ticket(self, payload, headers):
        return self._request("POST", f"{BASE}/weigh-tickets", payload, headers)

    def get_weigh_ticket(self, ticket_id, headers):
        return self._request("GET", f"{BASE}/weigh-tickets/{ticket_id}", headers=headers)

    def list_weigh_tickets(self, headers, params=None):
        return self._request("GET", f"{BASE}/weigh-tickets", headers=headers, params=params)

    def capture_weigh_ticket(self, ticket_id, headers):
        return self._request("POST", f"{BASE}/weigh-tickets/{ticket_id}/capture", {}, headers)

    def void_weigh_ticket(self, ticket_id, headers):
        return self._request("POST", f"{BASE}/weigh-tickets/{ticket_id}/void", {}, headers)

    # ---- pen moves -----------------------------------------------------
    def create_pen_move(self, payload, headers):
        return self._request("POST", f"{BASE}/pen-moves", payload, headers)

    def get_pen_move(self, move_id, headers):
        return self._request("GET", f"{BASE}/pen-moves/{move_id}", headers=headers)

    def list_pen_moves(self, headers, params=None):
        return self._request("GET", f"{BASE}/pen-moves", headers=headers, params=params)

    def set_pen_move_status(self, move_id, payload, headers):
        return self._request("POST", f"{BASE}/pen-moves/{move_id}/status", payload, headers)

    # ---- buyer registrations -------------------------------------------
    def create_buyer_registration(self, payload, headers):
        return self._request("POST", f"{BASE}/buyer-registrations", payload, headers)

    def get_buyer_registration(self, registration_id, headers):
        return self._request(
            "GET", f"{BASE}/buyer-registrations/{registration_id}", headers=headers
        )

    def list_buyer_registrations(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/buyer-registrations", headers=headers, params=params
        )

    def approve_buyer_registration(self, registration_id, headers):
        return self._request(
            "POST", f"{BASE}/buyer-registrations/{registration_id}/approve", {}, headers
        )

    def set_credit_hold(self, registration_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/buyer-registrations/{registration_id}/credit-hold",
            payload,
            headers,
        )

    def revoke_buyer_registration(self, registration_id, headers):
        return self._request(
            "POST", f"{BASE}/buyer-registrations/{registration_id}/revoke", {}, headers
        )

    def credit_override(self, registration_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/buyer-registrations/{registration_id}/credit-override",
            payload,
            headers,
        )

    def apply_payment(self, registration_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/buyer-registrations/{registration_id}/payments",
            payload,
            headers,
        )

    # ---- bids ----------------------------------------------------------
    def create_bid(self, payload, headers):
        return self._request("POST", f"{BASE}/bids", payload, headers)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"{BASE}/bids/{bid_id}", headers=headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", f"{BASE}/bids", headers=headers, params=params)

    # ---- purchases -----------------------------------------------------
    def get_purchase(self, purchase_id, headers):
        return self._request("GET", f"{BASE}/purchases/{purchase_id}", headers=headers)

    def list_purchases(self, headers, params=None):
        return self._request("GET", f"{BASE}/purchases", headers=headers, params=params)

    def void_purchase(self, purchase_id, payload, headers):
        return self._request("POST", f"{BASE}/purchases/{purchase_id}/void", payload, headers)

    # ---- buyer invoices ------------------------------------------------
    def get_buyer_invoice(self, invoice_id, headers):
        return self._request("GET", f"{BASE}/buyer-invoices/{invoice_id}", headers=headers)

    def list_buyer_invoices(self, headers, params=None):
        return self._request("GET", f"{BASE}/buyer-invoices", headers=headers, params=params)

    def issue_credit_memo(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/buyer-invoices/{invoice_id}/credit-memo", payload, headers
        )

    # ---- settlements ---------------------------------------------------
    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"{BASE}/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", f"{BASE}/settlements", headers=headers, params=params)

    def release_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/release", {}, headers
        )

    def adjust_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/adjust", payload, headers
        )

    # ---- charge lines --------------------------------------------------
    def get_charge_line(self, charge_line_id, headers):
        return self._request("GET", f"{BASE}/charge-lines/{charge_line_id}", headers=headers)

    def list_charge_lines(self, headers, params=None):
        return self._request("GET", f"{BASE}/charge-lines", headers=headers, params=params)

    # ---- inspection records --------------------------------------------
    def create_inspection_record(self, payload, headers):
        return self._request("POST", f"{BASE}/inspection-records", payload, headers)

    def get_inspection_record(self, record_id, headers):
        return self._request(
            "GET", f"{BASE}/inspection-records/{record_id}", headers=headers
        )

    def list_inspection_records(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/inspection-records", headers=headers, params=params
        )

    def result_inspection_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/inspection-records/{record_id}/result", payload, headers
        )

    # ---- load manifests -------------------------------------------------
    def create_load_manifest(self, payload, headers):
        return self._request("POST", f"{BASE}/load-manifests", payload, headers)

    def get_load_manifest(self, manifest_id, headers):
        return self._request("GET", f"{BASE}/load-manifests/{manifest_id}", headers=headers)

    def list_load_manifests(self, headers, params=None):
        return self._request("GET", f"{BASE}/load-manifests", headers=headers, params=params)

    def add_load_line(self, manifest_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/load-manifests/{manifest_id}/lines", payload, headers
        )

    def remove_load_line(self, manifest_id, line_id, headers):
        return self._request(
            "DELETE", f"{BASE}/load-manifests/{manifest_id}/lines/{line_id}", headers=headers
        )

    def dispatch_load_manifest(self, manifest_id, headers):
        return self._request(
            "POST", f"{BASE}/load-manifests/{manifest_id}/dispatch", {}, headers
        )

    def deliver_load_manifest(self, manifest_id, headers):
        return self._request(
            "POST", f"{BASE}/load-manifests/{manifest_id}/deliver", {}, headers
        )

    def close_load_manifest(self, manifest_id, headers):
        return self._request("POST", f"{BASE}/load-manifests/{manifest_id}/close", {}, headers)

    # ---- load lines -----------------------------------------------------
    def get_load_line(self, line_id, headers):
        return self._request("GET", f"{BASE}/load-lines/{line_id}", headers=headers)

    def list_load_lines(self, headers, params=None):
        return self._request("GET", f"{BASE}/load-lines", headers=headers, params=params)


api_client = ApiClient()
