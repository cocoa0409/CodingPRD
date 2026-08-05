"""API client: one method per endpoint defined in the PRD.

Subclasses the framework GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Clock (test-driving) -----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ----- Owner -----
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    # ----- Guest -----
    def create_guest(self, payload, headers):
        return self._request("POST", "/guests", payload, headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    def ban_guest(self, guest_id, headers):
        return self._request("POST", f"/guests/{guest_id}/ban", headers=headers)

    # ----- Vendor -----
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    # ----- Property -----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def list_property(self, property_id, headers):
        return self._request("POST", f"/properties/{property_id}/list", headers=headers)

    def unlist_property(self, property_id, headers):
        return self._request("POST", f"/properties/{property_id}/unlist", headers=headers)

    def offboard_property(self, property_id, headers):
        return self._request("POST", f"/properties/{property_id}/offboard", headers=headers)

    def create_pricing_rule(self, property_id, payload, headers):
        return self._request("POST", f"/properties/{property_id}/pricing-rules", payload, headers)

    def list_pricing_rules(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/pricing-rules", headers=headers, params=params)

    def quote_property(self, property_id, payload, headers):
        return self._request("POST", f"/properties/{property_id}/quote", payload, headers)

    # ----- Permit -----
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def activate_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/activate", headers=headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/revoke", headers=headers)

    # ----- ChannelListing -----
    def create_channel_listing(self, payload, headers):
        return self._request("POST", "/channel-listings", payload, headers)

    def get_channel_listing(self, listing_id, headers):
        return self._request("GET", f"/channel-listings/{listing_id}", headers=headers)

    def list_channel_listings(self, headers, params=None):
        return self._request("GET", "/channel-listings", headers=headers, params=params)

    def sync_channel_listing(self, listing_id, headers):
        return self._request("POST", f"/channel-listings/{listing_id}/sync", headers=headers)

    def pause_channel_listing(self, listing_id, headers):
        return self._request("POST", f"/channel-listings/{listing_id}/pause", headers=headers)

    # ----- PricingRule (single read) -----
    def get_pricing_rule(self, rule_id, headers):
        return self._request("GET", f"/pricing-rules/{rule_id}", headers=headers)

    # ----- Booking -----
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def screen_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/screen", payload, headers)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", headers=headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-in", headers=headers)

    def check_out_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-out", headers=headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", headers=headers)

    def add_booking_message(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/messages", payload, headers)

    # ----- TurnoverTask -----
    def create_turnover_task(self, payload, headers):
        return self._request("POST", "/turnover-tasks", payload, headers)

    def get_turnover_task(self, task_id, headers):
        return self._request("GET", f"/turnover-tasks/{task_id}", headers=headers)

    def list_turnover_tasks(self, headers, params=None):
        return self._request("GET", "/turnover-tasks", headers=headers, params=params)

    def start_turnover(self, task_id, headers):
        return self._request("POST", f"/turnover-tasks/{task_id}/start", headers=headers)

    def complete_turnover(self, task_id, headers):
        return self._request("POST", f"/turnover-tasks/{task_id}/complete", headers=headers)

    def cancel_turnover(self, task_id, headers):
        return self._request("POST", f"/turnover-tasks/{task_id}/cancel", headers=headers)

    # ----- Inspection -----
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    # ----- WorkOrder -----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def assign_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/assign", payload, headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/start", headers=headers)

    def request_info_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/request-info", headers=headers)

    def resume_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/resume", headers=headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", headers=headers)

    def approve_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/approve", headers=headers)

    def reject_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/reject", headers=headers)

    # ----- OwnerStatement -----
    def create_owner_statement(self, payload, headers):
        return self._request("POST", "/owner-statements", payload, headers)

    def get_owner_statement(self, statement_id, headers):
        return self._request("GET", f"/owner-statements/{statement_id}", headers=headers)

    def list_owner_statements(self, headers, params=None):
        return self._request("GET", "/owner-statements", headers=headers, params=params)

    def list_statement_lines(self, statement_id, headers, params=None):
        return self._request("GET", f"/owner-statements/{statement_id}/lines", headers=headers, params=params)

    def finalize_statement(self, statement_id, headers):
        return self._request("POST", f"/owner-statements/{statement_id}/finalize", headers=headers)

    def reopen_statement(self, statement_id, headers):
        return self._request("POST", f"/owner-statements/{statement_id}/reopen", headers=headers)

    def pay_statement(self, statement_id, headers):
        return self._request("POST", f"/owner-statements/{statement_id}/pay", headers=headers)

    # ----- Review -----
    def create_review(self, payload, headers):
        return self._request("POST", "/reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/reviews", headers=headers, params=params)

    def publish_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/publish", headers=headers)

    def suppress_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/suppress", headers=headers)


api_client = ApiClient()
