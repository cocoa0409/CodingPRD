"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
The flat topology means every collection is addressed at the root.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Customer ─────────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def ban_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/ban", {}, headers)

    def create_credit_adjustment(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/credit-adjustments",
                             payload, headers)

    def list_ledger(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/ledger",
                             headers=headers, params=params)

    def list_customer_registrations(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/registrations",
                             headers=headers, params=params)

    # ─── InventoryItem ────────────────────────────────────────────────────────
    def create_inventory_item(self, payload, headers):
        return self._request("POST", "/inventory-items", payload, headers)

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"/inventory-items/{item_id}", headers=headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", "/inventory-items", headers=headers, params=params)

    # ─── BuylistSubmission + BuylistLine ──────────────────────────────────────
    def create_buylist_submission(self, payload, headers):
        return self._request("POST", "/buylist-submissions", payload, headers)

    def get_buylist_submission(self, sub_id, headers):
        return self._request("GET", f"/buylist-submissions/{sub_id}", headers=headers)

    def list_buylist_submissions(self, headers, params=None):
        return self._request("GET", "/buylist-submissions", headers=headers, params=params)

    def create_buylist_line(self, payload, headers):
        return self._request("POST", "/buylist-lines", payload, headers)

    def get_buylist_line(self, line_id, headers):
        return self._request("GET", f"/buylist-lines/{line_id}", headers=headers)

    def list_buylist_lines(self, headers, params=None):
        return self._request("GET", "/buylist-lines", headers=headers, params=params)

    def submit_buylist(self, sub_id, headers):
        return self._request("POST", f"/buylist-submissions/{sub_id}/submit", {}, headers)

    def accept_buylist(self, sub_id, headers):
        return self._request("POST", f"/buylist-submissions/{sub_id}/accept", {}, headers)

    def reject_buylist(self, sub_id, headers):
        return self._request("POST", f"/buylist-submissions/{sub_id}/reject", {}, headers)

    def void_buylist(self, sub_id, headers):
        return self._request("POST", f"/buylist-submissions/{sub_id}/void", {}, headers)

    # ─── ReleaseProduct + PreOrder ────────────────────────────────────────────
    def create_release_product(self, payload, headers):
        return self._request("POST", "/release-products", payload, headers)

    def get_release_product(self, rp_id, headers):
        return self._request("GET", f"/release-products/{rp_id}", headers=headers)

    def list_release_products(self, headers, params=None):
        return self._request("GET", "/release-products", headers=headers, params=params)

    def release_release_product(self, rp_id, headers):
        return self._request("POST", f"/release-products/{rp_id}/release", {}, headers)

    def create_pre_order(self, payload, headers):
        return self._request("POST", "/pre-orders", payload, headers)

    def get_pre_order(self, po_id, headers):
        return self._request("GET", f"/pre-orders/{po_id}", headers=headers)

    def list_pre_orders(self, headers, params=None):
        return self._request("GET", "/pre-orders", headers=headers, params=params)

    def allocate_pre_order(self, po_id, payload, headers):
        return self._request("POST", f"/pre-orders/{po_id}/allocate", payload, headers)

    def waitlist_pre_order(self, po_id, headers):
        return self._request("POST", f"/pre-orders/{po_id}/waitlist", {}, headers)

    def fulfill_pre_order(self, po_id, headers):
        return self._request("POST", f"/pre-orders/{po_id}/fulfill", {}, headers)

    def cancel_pre_order(self, po_id, headers):
        return self._request("POST", f"/pre-orders/{po_id}/cancel", {}, headers)

    # ─── Event + Registration + Pairing ───────────────────────────────────────
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def list_event_registrations(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/registrations",
                             headers=headers, params=params)

    def list_event_pairings(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/pairings",
                             headers=headers, params=params)

    def get_wpn_report(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}/wpn-report", headers=headers)

    def open_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/open", {}, headers)

    def start_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/start", {}, headers)

    def advance_round(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/advance-round", {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/complete", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/cancel", {}, headers)

    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def get_registration(self, reg_id, headers):
        return self._request("GET", f"/registrations/{reg_id}", headers=headers)

    def pay_registration(self, reg_id, headers):
        return self._request("POST", f"/registrations/{reg_id}/pay", {}, headers)

    def check_in_registration(self, reg_id, headers):
        return self._request("POST", f"/registrations/{reg_id}/check-in", {}, headers)

    def withdraw_registration(self, reg_id, headers):
        return self._request("POST", f"/registrations/{reg_id}/withdraw", {}, headers)

    def create_pairing(self, payload, headers):
        return self._request("POST", "/pairings", payload, headers)

    def get_pairing(self, pairing_id, headers):
        return self._request("GET", f"/pairings/{pairing_id}", headers=headers)

    def list_pairings(self, headers, params=None):
        return self._request("GET", "/pairings", headers=headers, params=params)

    def report_pairing(self, pairing_id, payload, headers):
        return self._request("POST", f"/pairings/{pairing_id}/report", payload, headers)

    # ─── GradingSubmission ────────────────────────────────────────────────────
    def create_grading_submission(self, payload, headers):
        return self._request("POST", "/grading-submissions", payload, headers)

    def get_grading_submission(self, gs_id, headers):
        return self._request("GET", f"/grading-submissions/{gs_id}", headers=headers)

    def list_grading_submissions(self, headers, params=None):
        return self._request("GET", "/grading-submissions", headers=headers, params=params)

    def send_grading_submission(self, gs_id, headers):
        return self._request("POST", f"/grading-submissions/{gs_id}/send", {}, headers)

    def return_grading_result(self, gs_id, payload, headers):
        return self._request("POST", f"/grading-submissions/{gs_id}/return-result",
                             payload, headers)

    def release_grading_submission(self, gs_id, headers):
        return self._request("POST", f"/grading-submissions/{gs_id}/release", {}, headers)

    # ─── ConsignmentCase ──────────────────────────────────────────────────────
    def create_consignment_case(self, payload, headers):
        return self._request("POST", "/consignment-cases", payload, headers)

    def get_consignment_case(self, cc_id, headers):
        return self._request("GET", f"/consignment-cases/{cc_id}", headers=headers)

    def list_consignment_cases(self, headers, params=None):
        return self._request("GET", "/consignment-cases", headers=headers, params=params)

    def sell_consignment_case(self, cc_id, headers):
        return self._request("POST", f"/consignment-cases/{cc_id}/sell", {}, headers)

    def settle_consignment_case(self, cc_id, headers):
        return self._request("POST", f"/consignment-cases/{cc_id}/settle", {}, headers)

    def withdraw_consignment_case(self, cc_id, headers):
        return self._request("POST", f"/consignment-cases/{cc_id}/withdraw", {}, headers)


api_client = ApiClient()
