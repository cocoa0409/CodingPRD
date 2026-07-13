"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/concierge/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/concierge/members/{member_id}", headers=headers)

    def activate_member(self, member_id, headers):
        return self._request("POST", f"/concierge/members/{member_id}/activate", headers=headers)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/concierge/members/{member_id}/suspend", headers=headers)

    def create_membership(self, member_id, payload, headers):
        return self._request("POST", f"/concierge/members/{member_id}/memberships", payload, headers)

    # ---- RetainerPlan ----
    def create_retainer_plan(self, payload, headers):
        return self._request("POST", "/concierge/retainer-plans", payload, headers)

    def get_retainer_plan(self, plan_id, headers):
        return self._request("GET", f"/concierge/retainer-plans/{plan_id}", headers=headers)

    # ---- Vendor ----
    def create_vendor(self, payload, headers):
        return self._request("POST", "/concierge/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/concierge/vendors/{vendor_id}", headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/concierge/vendors/{vendor_id}/suspend", headers=headers)

    # ---- Membership ----
    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/concierge/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/concierge/memberships", headers=headers, params=params)

    def get_membership_satisfaction(self, membership_id, headers):
        return self._request("GET", f"/concierge/memberships/{membership_id}/satisfaction", headers=headers)

    def pause_membership(self, membership_id, headers):
        return self._request("POST", f"/concierge/memberships/{membership_id}/pause", headers=headers)

    def resume_membership(self, membership_id, headers):
        return self._request("POST", f"/concierge/memberships/{membership_id}/resume", headers=headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/concierge/memberships/{membership_id}/cancel", headers=headers)

    # ---- BillingCycle ----
    def get_billing_cycle(self, cycle_id, headers):
        return self._request("GET", f"/concierge/billing-cycles/{cycle_id}", headers=headers)

    def list_billing_cycles(self, headers, params=None):
        return self._request("GET", "/concierge/billing-cycles", headers=headers, params=params)

    def close_billing_cycle(self, cycle_id, headers):
        return self._request("POST", f"/concierge/billing-cycles/{cycle_id}/close", headers=headers)

    # ---- ServiceRequest ----
    def create_service_request(self, payload, headers):
        return self._request("POST", "/concierge/service-requests", payload, headers)

    def get_service_request(self, request_id, headers):
        return self._request("GET", f"/concierge/service-requests/{request_id}", headers=headers)

    def list_service_requests(self, headers, params=None):
        return self._request("GET", "/concierge/service-requests", headers=headers, params=params)

    def accept_service_request(self, request_id, payload, headers):
        return self._request("POST", f"/concierge/service-requests/{request_id}/accept", payload, headers)

    def hold_service_request(self, request_id, headers):
        return self._request("POST", f"/concierge/service-requests/{request_id}/hold", headers=headers)

    def resume_service_request(self, request_id, headers):
        return self._request("POST", f"/concierge/service-requests/{request_id}/resume", headers=headers)

    def fulfill_service_request(self, request_id, headers):
        return self._request("POST", f"/concierge/service-requests/{request_id}/fulfill", headers=headers)

    def cancel_service_request(self, request_id, headers):
        return self._request("POST", f"/concierge/service-requests/{request_id}/cancel", headers=headers)

    def generate_service_request(self, request_id, payload, headers):
        return self._request("POST", f"/concierge/service-requests/{request_id}/generate", payload, headers)

    def create_time_entry(self, request_id, payload, headers):
        return self._request("POST", f"/concierge/service-requests/{request_id}/time-entries", payload, headers)

    def create_rating(self, request_id, payload, headers):
        return self._request("POST", f"/concierge/service-requests/{request_id}/ratings", payload, headers)

    def create_engagement(self, request_id, payload, headers):
        return self._request("POST", f"/concierge/service-requests/{request_id}/engagements", payload, headers)

    # ---- TimeEntry ----
    def get_time_entry(self, entry_id, headers):
        return self._request("GET", f"/concierge/time-entries/{entry_id}", headers=headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/concierge/time-entries", headers=headers, params=params)

    def reverse_time_entry(self, entry_id, headers):
        return self._request("POST", f"/concierge/time-entries/{entry_id}/reverse", headers=headers)

    # ---- VendorEngagement ----
    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/concierge/vendor-engagements/{engagement_id}", headers=headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/concierge/vendor-engagements", headers=headers, params=params)

    def confirm_engagement(self, engagement_id, headers):
        return self._request("POST", f"/concierge/vendor-engagements/{engagement_id}/confirm", headers=headers)

    def reconcile_engagement(self, engagement_id, payload, headers):
        return self._request("POST", f"/concierge/vendor-engagements/{engagement_id}/reconcile", payload, headers)

    def void_engagement(self, engagement_id, headers):
        return self._request("POST", f"/concierge/vendor-engagements/{engagement_id}/void", headers=headers)

    # ---- Expense ----
    def get_expense(self, expense_id, headers):
        return self._request("GET", f"/concierge/expenses/{expense_id}", headers=headers)

    def list_expenses(self, headers, params=None):
        return self._request("GET", "/concierge/expenses", headers=headers, params=params)

    def dispute_expense(self, expense_id, headers):
        return self._request("POST", f"/concierge/expenses/{expense_id}/dispute", headers=headers)

    def resolve_expense(self, expense_id, headers):
        return self._request("POST", f"/concierge/expenses/{expense_id}/resolve", headers=headers)

    # ---- SatisfactionRating ----
    def get_rating(self, rating_id, headers):
        return self._request("GET", f"/concierge/satisfaction-ratings/{rating_id}", headers=headers)

    def list_ratings(self, headers, params=None):
        return self._request("GET", "/concierge/satisfaction-ratings", headers=headers, params=params)


api_client = ApiClient()
