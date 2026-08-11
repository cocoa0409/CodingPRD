"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Sale events ---
    def create_sale_event(self, payload, headers):
        return self._request("POST", "/sale-events", payload, headers)

    def list_sale_events(self, headers, params=None):
        return self._request("GET", "/sale-events", headers=headers, params=params)

    def get_sale_event(self, event_id, headers):
        return self._request("GET", f"/sale-events/{event_id}", headers=headers)

    def advance_phase(self, event_id, payload, headers):
        return self._request("POST", f"/sale-events/{event_id}/advance-phase", payload, headers)

    def issue_presale_passes(self, event_id, headers):
        return self._request("POST", f"/sale-events/{event_id}/issue-presale-passes", {}, headers)

    def generate_settlements(self, event_id, payload, headers):
        return self._request("POST", f"/sale-events/{event_id}/generate-settlements", payload, headers)

    # --- Markdown rules ---
    def create_markdown_rule(self, payload, headers):
        return self._request("POST", "/markdown-rules", payload, headers)

    def list_markdown_rules(self, headers, params=None):
        return self._request("GET", "/markdown-rules", headers=headers, params=params)

    def get_markdown_rule(self, rule_id, headers):
        return self._request("GET", f"/markdown-rules/{rule_id}", headers=headers)

    # --- Consignors ---
    def create_consignor(self, payload, headers):
        return self._request("POST", "/consignors", payload, headers)

    def list_consignors(self, headers, params=None):
        return self._request("GET", "/consignors", headers=headers, params=params)

    def get_consignor(self, consignor_id, headers):
        return self._request("GET", f"/consignors/{consignor_id}", headers=headers)

    def withdraw_consignor(self, consignor_id, headers):
        return self._request("POST", f"/consignors/{consignor_id}/withdraw", {}, headers)

    # --- Volunteers ---
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/volunteers", payload, headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/volunteers", headers=headers, params=params)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    # --- Drop-off slots ---
    def create_drop_off_slot(self, payload, headers):
        return self._request("POST", "/drop-off-slots", payload, headers)

    def list_drop_off_slots(self, headers, params=None):
        return self._request("GET", "/drop-off-slots", headers=headers, params=params)

    def get_drop_off_slot(self, slot_id, headers):
        return self._request("GET", f"/drop-off-slots/{slot_id}", headers=headers)

    # --- Drop-off bookings ---
    def create_drop_off_booking(self, payload, headers):
        return self._request("POST", "/drop-off-bookings", payload, headers)

    def list_drop_off_bookings(self, headers, params=None):
        return self._request("GET", "/drop-off-bookings", headers=headers, params=params)

    def get_drop_off_booking(self, booking_id, headers):
        return self._request("GET", f"/drop-off-bookings/{booking_id}", headers=headers)

    def cancel_drop_off_booking(self, booking_id, headers):
        return self._request("POST", f"/drop-off-bookings/{booking_id}/cancel", {}, headers)

    def check_in_drop_off_booking(self, booking_id, headers):
        return self._request("POST", f"/drop-off-bookings/{booking_id}/check-in", {}, headers)

    # --- Items ---
    def create_item(self, payload, headers):
        return self._request("POST", "/items", payload, headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/items/{item_id}", headers=headers)

    def drop_off_item(self, item_id, headers):
        return self._request("POST", f"/items/{item_id}/drop-off", {}, headers)

    def inspect_item(self, item_id, payload, headers):
        return self._request("POST", f"/items/{item_id}/inspect", payload, headers)

    def pickup_item(self, item_id, headers):
        return self._request("POST", f"/items/{item_id}/pickup", {}, headers)

    # --- Inspection records ---
    def list_inspection_records(self, headers, params=None):
        return self._request("GET", "/inspection-records", headers=headers, params=params)

    def get_inspection_record(self, record_id, headers):
        return self._request("GET", f"/inspection-records/{record_id}", headers=headers)

    # --- Volunteer shifts ---
    def create_volunteer_shift(self, payload, headers):
        return self._request("POST", "/volunteer-shifts", payload, headers)

    def list_volunteer_shifts(self, headers, params=None):
        return self._request("GET", "/volunteer-shifts", headers=headers, params=params)

    def get_volunteer_shift(self, shift_id, headers):
        return self._request("GET", f"/volunteer-shifts/{shift_id}", headers=headers)

    # --- Shift signups ---
    def create_shift_signup(self, payload, headers):
        return self._request("POST", "/shift-signups", payload, headers)

    def list_shift_signups(self, headers, params=None):
        return self._request("GET", "/shift-signups", headers=headers, params=params)

    def get_shift_signup(self, signup_id, headers):
        return self._request("GET", f"/shift-signups/{signup_id}", headers=headers)

    def cancel_shift_signup(self, signup_id, headers):
        return self._request("POST", f"/shift-signups/{signup_id}/cancel", {}, headers)

    def check_in_shift_signup(self, signup_id, headers):
        return self._request("POST", f"/shift-signups/{signup_id}/check-in", {}, headers)

    def check_out_shift_signup(self, signup_id, headers):
        return self._request("POST", f"/shift-signups/{signup_id}/check-out", {}, headers)

    def mark_no_show_shift_signup(self, signup_id, headers):
        return self._request("POST", f"/shift-signups/{signup_id}/mark-no-show", {}, headers)

    # --- Presale passes ---
    def list_presale_passes(self, headers, params=None):
        return self._request("GET", "/presale-passes", headers=headers, params=params)

    def get_presale_pass(self, pass_id, headers):
        return self._request("GET", f"/presale-passes/{pass_id}", headers=headers)

    def revoke_presale_pass(self, pass_id, headers):
        return self._request("POST", f"/presale-passes/{pass_id}/revoke", {}, headers)

    # --- POS transactions ---
    def create_pos_transaction(self, payload, headers):
        return self._request("POST", "/pos-transactions", payload, headers)

    def list_pos_transactions(self, headers, params=None):
        return self._request("GET", "/pos-transactions", headers=headers, params=params)

    def get_pos_transaction(self, transaction_id, headers):
        return self._request("GET", f"/pos-transactions/{transaction_id}", headers=headers)

    def scan_line(self, transaction_id, payload, headers):
        return self._request("POST", f"/pos-transactions/{transaction_id}/lines", payload, headers)

    def list_transaction_lines(self, headers, params=None):
        return self._request("GET", "/transaction-lines", headers=headers, params=params)

    def get_transaction_line(self, line_id, headers):
        return self._request("GET", f"/transaction-lines/{line_id}", headers=headers)

    def delete_line(self, transaction_id, line_id, headers):
        return self._request(
            "DELETE", f"/pos-transactions/{transaction_id}/lines/{line_id}", headers=headers
        )

    def checkout(self, transaction_id, payload, headers):
        return self._request("POST", f"/pos-transactions/{transaction_id}/checkout", payload, headers)

    def void_transaction(self, transaction_id, headers):
        return self._request("POST", f"/pos-transactions/{transaction_id}/void", {}, headers)

    # --- Settlements ---
    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/finalize", {}, headers)

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/settlements/{settlement_id}/dispute", payload, headers)

    def resolve_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/settlements/{settlement_id}/resolve", payload, headers)

    def mark_paid_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/mark-paid", {}, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
