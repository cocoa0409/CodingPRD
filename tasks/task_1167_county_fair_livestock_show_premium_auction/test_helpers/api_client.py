"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Fair / posture / logical clock ---
    def create_fair(self, payload, headers):
        return self._request("POST", "/v1/fairs", payload, headers)

    def get_fair(self, fair_id, headers):
        return self._request("GET", f"/v1/fairs/{fair_id}", headers=headers)

    def advance_posture(self, fair_id, to_posture, headers):
        return self._request(
            "POST", f"/v1/fairs/{fair_id}/advance-posture",
            {"to_posture": to_posture}, headers,
        )

    def reopen_entries(self, fair_id, headers):
        return self._request("POST", f"/v1/fairs/{fair_id}/reopen-entries", {}, headers)

    def run_settlement(self, fair_id, headers):
        return self._request("POST", f"/v1/fairs/{fair_id}/run-settlement", {}, headers)

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Exhibitors ---
    def create_exhibitor(self, payload, headers):
        return self._request("POST", "/v1/exhibitors", payload, headers)

    def get_exhibitor(self, exhibitor_id, headers):
        return self._request("GET", f"/v1/exhibitors/{exhibitor_id}", headers=headers)

    def list_exhibitors(self, headers, params=None):
        return self._request("GET", "/v1/exhibitors", headers=headers, params=params)

    def suspend_exhibitor(self, exhibitor_id, headers):
        return self._request(
            "POST", f"/v1/exhibitors/{exhibitor_id}/suspend", {}, headers
        )

    # --- Animal entries ---
    def create_entry(self, payload, headers):
        return self._request("POST", "/v1/entries", payload, headers)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/v1/entries/{entry_id}", headers=headers)

    def list_entries(self, headers, params=None):
        return self._request("GET", "/v1/entries", headers=headers, params=params)

    def verify_entry(self, entry_id, decision, headers, note=None):
        payload = {"decision": decision}
        if note is not None:
            payload["note"] = note
        return self._request(
            "POST", f"/v1/entries/{entry_id}/verify", payload, headers
        )

    def disqualify_entry(self, entry_id, reason, headers):
        return self._request(
            "POST", f"/v1/entries/{entry_id}/disqualify", {"reason": reason}, headers
        )

    # --- Weigh tickets ---
    def create_weigh_ticket(self, payload, headers):
        return self._request("POST", "/v1/weigh-tickets", payload, headers)

    def get_weigh_ticket(self, ticket_id, headers):
        return self._request("GET", f"/v1/weigh-tickets/{ticket_id}", headers=headers)

    def list_weigh_tickets(self, headers, params=None):
        return self._request("GET", "/v1/weigh-tickets", headers=headers, params=params)

    def void_weigh_ticket(self, ticket_id, headers, reason=None):
        payload = {}
        if reason is not None:
            payload["reason"] = reason
        return self._request(
            "POST", f"/v1/weigh-tickets/{ticket_id}/void", payload, headers
        )

    # --- Show classes / classification ---
    def create_class(self, payload, headers):
        return self._request("POST", "/v1/classes", payload, headers)

    def get_class(self, class_id, headers):
        return self._request("GET", f"/v1/classes/{class_id}", headers=headers)

    def list_classes(self, headers, params=None):
        return self._request("GET", "/v1/classes", headers=headers, params=params)

    def classify_entry(self, entry_id, headers, class_id=None):
        payload = {}
        if class_id is not None:
            payload["class_id"] = class_id
        return self._request(
            "POST", f"/v1/entries/{entry_id}/classify", payload, headers
        )

    # --- Judges / ring slots / placings ---
    def create_judge(self, payload, headers):
        return self._request("POST", "/v1/judges", payload, headers)

    def get_judge(self, judge_id, headers):
        return self._request("GET", f"/v1/judges/{judge_id}", headers=headers)

    def list_judges(self, headers, params=None):
        return self._request("GET", "/v1/judges", headers=headers, params=params)

    def create_ring_slot(self, payload, headers):
        return self._request("POST", "/v1/ring-slots", payload, headers)

    def get_ring_slot(self, slot_id, headers):
        return self._request("GET", f"/v1/ring-slots/{slot_id}", headers=headers)

    def list_ring_slots(self, headers, params=None):
        return self._request("GET", "/v1/ring-slots", headers=headers, params=params)

    def assign_judge(self, slot_id, judge_id, expected_ring_slot_version, headers):
        return self._request(
            "POST", f"/v1/ring-slots/{slot_id}/assign-judge",
            {"judge_id": judge_id,
             "expected_ring_slot_version": expected_ring_slot_version},
            headers,
        )

    def start_slot(self, slot_id, headers):
        return self._request("POST", f"/v1/ring-slots/{slot_id}/start", {}, headers)

    def submit_placings(self, slot_id, placings, headers):
        return self._request(
            "POST", f"/v1/ring-slots/{slot_id}/placings",
            {"placings": placings}, headers,
        )

    def get_placing(self, placing_id, headers):
        return self._request("GET", f"/v1/placings/{placing_id}", headers=headers)

    def list_placings(self, headers, params=None):
        return self._request("GET", "/v1/placings", headers=headers, params=params)

    def void_placing(self, placing_id, reason, headers):
        return self._request(
            "POST", f"/v1/placings/{placing_id}/void", {"reason": reason}, headers
        )

    # --- Premium awards ---
    def get_premium_award(self, award_id, headers):
        return self._request(
            "GET", f"/v1/premium-awards/{award_id}", headers=headers
        )

    def list_premium_awards(self, headers, params=None):
        return self._request(
            "GET", "/v1/premium-awards", headers=headers, params=params
        )

    def approve_premium_award(self, award_id, headers):
        return self._request(
            "POST", f"/v1/premium-awards/{award_id}/approve", {}, headers
        )

    def pay_premium_award(self, award_id, headers):
        return self._request(
            "POST", f"/v1/premium-awards/{award_id}/pay", {}, headers
        )

    def forfeit_premium_award(self, award_id, reason, headers):
        return self._request(
            "POST", f"/v1/premium-awards/{award_id}/forfeit", {"reason": reason},
            headers,
        )

    # --- Buyers ---
    def create_buyer(self, payload, headers):
        return self._request("POST", "/v1/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/v1/buyers/{buyer_id}", headers=headers)

    def list_buyers(self, headers, params=None):
        return self._request("GET", "/v1/buyers", headers=headers, params=params)

    # --- Auction lots ---
    def generate_auction_lots(self, fair_id, headers):
        return self._request(
            "POST", "/v1/auction-lots/generate", {"fair_id": fair_id}, headers
        )

    def get_auction_lot(self, lot_id, headers):
        return self._request("GET", f"/v1/auction-lots/{lot_id}", headers=headers)

    def list_auction_lots(self, headers, params=None):
        return self._request("GET", "/v1/auction-lots", headers=headers, params=params)

    def open_lot(self, lot_id, headers):
        return self._request("POST", f"/v1/auction-lots/{lot_id}/open", {}, headers)

    def close_sold(self, lot_id, buyer_id, hammer_price_cents, headers):
        return self._request(
            "POST", f"/v1/auction-lots/{lot_id}/close-sold",
            {"buyer_id": buyer_id, "hammer_price_cents": hammer_price_cents}, headers,
        )

    def close_passed(self, lot_id, headers):
        return self._request(
            "POST", f"/v1/auction-lots/{lot_id}/close-passed", {}, headers
        )

    def reoffer_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/v1/auction-lots/{lot_id}/reoffer", {}, headers
        )

    def no_sale_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/v1/auction-lots/{lot_id}/no-sale", {}, headers
        )

    # --- Add-on pledges ---
    def create_add_on(self, payload, headers):
        return self._request("POST", "/v1/add-ons", payload, headers)

    def get_add_on(self, addon_id, headers):
        return self._request("GET", f"/v1/add-ons/{addon_id}", headers=headers)

    def list_add_ons(self, headers, params=None):
        return self._request("GET", "/v1/add-ons", headers=headers, params=params)

    def void_add_on(self, addon_id, headers, reason=None):
        payload = {}
        if reason is not None:
            payload["reason"] = reason
        return self._request("POST", f"/v1/add-ons/{addon_id}/void", payload, headers)

    # --- Invoices ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/v1/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/v1/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/v1/invoices/{invoice_id}/issue", {}, headers
        )

    def post_payment(self, invoice_id, amount_cents, headers):
        return self._request(
            "POST", f"/v1/invoices/{invoice_id}/payments",
            {"amount_cents": amount_cents}, headers,
        )

    # --- Disposition orders ---
    def create_disposition(self, payload, headers):
        return self._request("POST", "/v1/dispositions", payload, headers)

    def get_disposition(self, order_id, headers):
        return self._request("GET", f"/v1/dispositions/{order_id}", headers=headers)

    def list_dispositions(self, headers, params=None):
        return self._request("GET", "/v1/dispositions", headers=headers, params=params)

    def approve_disposition(self, order_id, headers):
        return self._request(
            "POST", f"/v1/dispositions/{order_id}/approve", {}, headers
        )

    def reject_disposition(self, order_id, reason, headers):
        return self._request(
            "POST", f"/v1/dispositions/{order_id}/reject", {"reason": reason}, headers
        )

    def complete_disposition(self, order_id, headers):
        return self._request(
            "POST", f"/v1/dispositions/{order_id}/complete", {}, headers
        )

    # --- Health inspections / affidavits ---
    def create_health_inspection(self, payload, headers):
        return self._request("POST", "/v1/health-inspections", payload, headers)

    def get_health_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"/v1/health-inspections/{inspection_id}", headers=headers
        )

    def list_health_inspections(self, headers, params=None):
        return self._request(
            "GET", "/v1/health-inspections", headers=headers, params=params
        )

    def create_affidavit(self, payload, headers):
        return self._request("POST", "/v1/affidavits", payload, headers)

    def get_affidavit(self, affidavit_id, headers):
        return self._request("GET", f"/v1/affidavits/{affidavit_id}", headers=headers)

    def list_affidavits(self, headers, params=None):
        return self._request("GET", "/v1/affidavits", headers=headers, params=params)

    def revoke_affidavit(self, affidavit_id, reason, headers):
        return self._request(
            "POST", f"/v1/affidavits/{affidavit_id}/revoke", {"reason": reason},
            headers,
        )


api_client = ApiClient()
