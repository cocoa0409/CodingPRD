"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Surgeons ---
    def create_surgeon(self, payload, headers):
        return self._request("POST", "/perioperative/surgeons", payload, headers)

    def get_surgeon(self, surgeon_id, headers):
        return self._request("GET", f"/perioperative/surgeons/{surgeon_id}", headers=headers)

    def deactivate_surgeon(self, surgeon_id, headers):
        return self._request("POST", f"/perioperative/surgeons/{surgeon_id}/deactivate", headers=headers)

    # --- Supply items ---
    def create_supply_item(self, payload, headers):
        return self._request("POST", "/perioperative/supply-items", payload, headers)

    def list_supply_items(self, headers, params=None):
        return self._request("GET", "/perioperative/supply-items", headers=headers, params=params)

    def get_supply_item(self, item_id, headers):
        return self._request("GET", f"/perioperative/supply-items/{item_id}", headers=headers)

    def create_stock_adjustment(self, item_id, payload, headers):
        return self._request("POST", f"/perioperative/supply-items/{item_id}/stock-adjustments", payload, headers)

    # --- Preference cards ---
    def create_preference_card(self, payload, headers):
        return self._request("POST", "/perioperative/preference-cards", payload, headers)

    def list_preference_cards(self, headers, params=None):
        return self._request("GET", "/perioperative/preference-cards", headers=headers, params=params)

    def get_preference_card(self, card_id, headers):
        return self._request("GET", f"/perioperative/preference-cards/{card_id}", headers=headers)

    def publish_preference_card(self, card_id, payload, headers):
        return self._request("POST", f"/perioperative/preference-cards/{card_id}/publish", payload, headers)

    def retire_preference_card(self, card_id, headers):
        return self._request("POST", f"/perioperative/preference-cards/{card_id}/retire", headers=headers)

    # --- Preference card lines ---
    def create_preference_card_line(self, payload, headers):
        return self._request("POST", "/perioperative/preference-card-lines", payload, headers)

    def list_preference_card_lines(self, headers, params=None):
        return self._request("GET", "/perioperative/preference-card-lines", headers=headers, params=params)

    def get_preference_card_line(self, line_id, headers):
        return self._request("GET", f"/perioperative/preference-card-lines/{line_id}", headers=headers)

    def delete_preference_card_line(self, line_id, headers):
        return self._request("DELETE", f"/perioperative/preference-card-lines/{line_id}", headers=headers)

    # --- Surgical cases ---
    def create_case(self, payload, headers):
        return self._request("POST", "/perioperative/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/perioperative/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/perioperative/cases/{case_id}", headers=headers)

    def release_pick_list(self, case_id, headers):
        return self._request("POST", f"/perioperative/cases/{case_id}/release-pick-list", {}, headers)

    def repin_card(self, case_id, payload, headers):
        return self._request("POST", f"/perioperative/cases/{case_id}/repin-card", payload, headers)

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"/perioperative/cases/{case_id}/cancel", {}, headers)

    def complete_case(self, case_id, payload, headers):
        return self._request("POST", f"/perioperative/cases/{case_id}/complete", payload, headers)

    # --- Pick lists ---
    def list_pick_lists(self, headers, params=None):
        return self._request("GET", "/perioperative/pick-lists", headers=headers, params=params)

    def get_pick_list(self, pick_list_id, headers):
        return self._request("GET", f"/perioperative/pick-lists/{pick_list_id}", headers=headers)

    def begin_picking(self, pick_list_id, headers):
        return self._request("POST", f"/perioperative/pick-lists/{pick_list_id}/begin-picking", {}, headers)

    def dispatch_pick_list(self, pick_list_id, headers):
        return self._request("POST", f"/perioperative/pick-lists/{pick_list_id}/dispatch", {}, headers)

    def return_pick_list(self, pick_list_id, payload, headers):
        return self._request("POST", f"/perioperative/pick-lists/{pick_list_id}/return", payload, headers)

    # --- Pick list lines ---
    def list_pick_list_lines(self, headers, params=None):
        return self._request("GET", "/perioperative/pick-list-lines", headers=headers, params=params)

    def get_pick_list_line(self, line_id, headers):
        return self._request("GET", f"/perioperative/pick-list-lines/{line_id}", headers=headers)

    def pick_line(self, line_id, headers):
        return self._request("POST", f"/perioperative/pick-list-lines/{line_id}/pick", {}, headers)

    def mark_short(self, line_id, payload, headers):
        return self._request("POST", f"/perioperative/pick-list-lines/{line_id}/mark-short", payload, headers)

    def substitute_line(self, line_id, payload, headers):
        return self._request("POST", f"/perioperative/pick-list-lines/{line_id}/substitute", payload, headers)

    # --- Usage records ---
    def list_usage_records(self, headers, params=None):
        return self._request("GET", "/perioperative/usage-records", headers=headers, params=params)

    def get_usage_record(self, record_id, headers):
        return self._request("GET", f"/perioperative/usage-records/{record_id}", headers=headers)

    # --- Card accuracy audits ---
    def list_card_audits(self, headers, params=None):
        return self._request("GET", "/perioperative/card-audits", headers=headers, params=params)

    def get_card_audit(self, audit_id, headers):
        return self._request("GET", f"/perioperative/card-audits/{audit_id}", headers=headers)

    def accept_card_audit(self, audit_id, headers):
        return self._request("POST", f"/perioperative/card-audits/{audit_id}/accept", {}, headers)

    def dispute_card_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/perioperative/card-audits/{audit_id}/dispute", payload, headers)

    def reopen_card_audit_review(self, audit_id, headers):
        return self._request("POST", f"/perioperative/card-audits/{audit_id}/reopen-review", {}, headers)

    # --- Product requests ---
    def create_product_request(self, payload, headers):
        return self._request("POST", "/perioperative/product-requests", payload, headers)

    def list_product_requests(self, headers, params=None):
        return self._request("GET", "/perioperative/product-requests", headers=headers, params=params)

    def get_product_request(self, request_id, headers):
        return self._request("GET", f"/perioperative/product-requests/{request_id}", headers=headers)

    def open_product_request_review(self, request_id, headers):
        return self._request("POST", f"/perioperative/product-requests/{request_id}/open-review", {}, headers)

    def endorse_product_request(self, request_id, headers):
        return self._request("POST", f"/perioperative/product-requests/{request_id}/endorse", {}, headers)

    def approve_product_request(self, request_id, headers):
        return self._request("POST", f"/perioperative/product-requests/{request_id}/approve", {}, headers)

    def reject_product_request(self, request_id, payload, headers):
        return self._request("POST", f"/perioperative/product-requests/{request_id}/reject", payload, headers)

    # --- Consignment counts ---
    def create_consignment_count(self, payload, headers):
        return self._request("POST", "/perioperative/consignment-counts", payload, headers)

    def list_consignment_counts(self, headers, params=None):
        return self._request("GET", "/perioperative/consignment-counts", headers=headers, params=params)

    def get_consignment_count(self, count_id, headers):
        return self._request("GET", f"/perioperative/consignment-counts/{count_id}", headers=headers)

    def verify_consignment_count(self, count_id, headers):
        return self._request("POST", f"/perioperative/consignment-counts/{count_id}/verify", {}, headers)

    # --- Consignment charges ---
    def list_consignment_charges(self, headers, params=None):
        return self._request("GET", "/perioperative/consignment-charges", headers=headers, params=params)

    def get_consignment_charge(self, charge_id, headers):
        return self._request("GET", f"/perioperative/consignment-charges/{charge_id}", headers=headers)

    def capture_consignment_charge(self, charge_id, headers):
        return self._request("POST", f"/perioperative/consignment-charges/{charge_id}/capture", {}, headers)

    def void_consignment_charge(self, charge_id, headers):
        return self._request("POST", f"/perioperative/consignment-charges/{charge_id}/void", {}, headers)


api_client = ApiClient()
