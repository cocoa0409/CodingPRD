"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Reference data ----
    def create_membership_category(self, payload, headers):
        return self._request("POST", "/api/membership-categories", payload, headers)

    def get_membership_category(self, category_id, headers):
        return self._request("GET", f"/api/membership-categories/{category_id}", headers=headers)

    def create_chapter(self, payload, headers):
        return self._request("POST", "/api/chapters", payload, headers)

    def get_chapter(self, chapter_id, headers):
        return self._request("GET", f"/api/chapters/{chapter_id}", headers=headers)

    def create_renewal_cycle_policy(self, payload, headers):
        return self._request("POST", "/api/renewal-cycle-policies", payload, headers)

    def get_renewal_cycle_policy(self, policy_id, headers):
        return self._request("GET", f"/api/renewal-cycle-policies/{policy_id}", headers=headers)

    # ---- Dues schedules ----
    def create_dues_schedule(self, payload, headers):
        return self._request("POST", "/api/dues-schedules", payload, headers)

    def get_dues_schedule(self, schedule_id, headers):
        return self._request("GET", f"/api/dues-schedules/{schedule_id}", headers=headers)

    def list_dues_schedules_for_category(self, category_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/membership-categories/{category_id}/dues-schedules",
            headers=headers,
            params=params,
        )

    def publish_dues_schedule(self, schedule_id, headers):
        return self._request("POST", f"/api/dues-schedules/{schedule_id}/publish", {}, headers)

    def retire_dues_schedule(self, schedule_id, headers):
        return self._request("POST", f"/api/dues-schedules/{schedule_id}/retire", {}, headers)

    # ---- Dues increase notices ----
    def create_increase_notice(self, schedule_id, headers):
        return self._request("POST", f"/api/dues-schedules/{schedule_id}/increase-notices", {}, headers)

    def list_increase_notices(self, schedule_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/dues-schedules/{schedule_id}/increase-notices",
            headers=headers,
            params=params,
        )

    # ---- Members ----
    def create_member(self, payload, headers):
        return self._request("POST", "/api/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/api/members", headers=headers, params=params)

    def verify_member(self, member_id, headers):
        return self._request("POST", f"/api/members/{member_id}/verify", {}, headers)

    def resign_member(self, member_id, payload, headers):
        return self._request("POST", f"/api/members/{member_id}/resign", payload, headers)

    def expel_member(self, member_id, headers):
        return self._request("POST", f"/api/members/{member_id}/expel", {}, headers)

    # ---- Membership terms ----
    def list_membership_terms(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/members/{member_id}/membership-terms",
            headers=headers,
            params=params,
        )

    # ---- Dues invoices ----
    def list_member_dues_invoices(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/members/{member_id}/dues-invoices",
            headers=headers,
            params=params,
        )

    def get_dues_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/dues-invoices/{invoice_id}", headers=headers)

    def list_dues_invoices(self, headers, params=None):
        return self._request("GET", "/api/dues-invoices", headers=headers, params=params)

    def list_invoice_reinstatement_requests(self, invoice_id, headers):
        return self._request(
            "GET",
            f"/api/dues-invoices/{invoice_id}/reinstatement-requests",
            headers=headers,
        )

    def submit_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/dues-invoices/{invoice_id}/payments", payload, headers)

    def refund_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/dues-invoices/{invoice_id}/refund", {}, headers)

    def list_payment_attempts(self, invoice_id, headers):
        return self._request(
            "GET",
            f"/api/dues-invoices/{invoice_id}/payment-attempts",
            headers=headers,
        )

    # ---- Auto-renew ----
    def enroll_auto_renew(self, member_id, payload, headers):
        return self._request("POST", f"/api/members/{member_id}/auto-renew/enroll", payload, headers)

    def revoke_auto_renew(self, member_id, payload, headers):
        return self._request("POST", f"/api/members/{member_id}/auto-renew/revoke", payload, headers)

    def reactivate_auto_renew(self, member_id, payload, headers):
        return self._request(
            "POST", f"/api/members/{member_id}/auto-renew/reactivate", payload, headers
        )

    def get_auto_renew(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}/auto-renew", headers=headers)

    # ---- Benefits ----
    def list_benefit_entitlements(self, member_id, headers):
        return self._request(
            "GET", f"/api/members/{member_id}/benefit-entitlements", headers=headers
        )

    # ---- Directory ----
    def get_directory_listing(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}/directory-listing", headers=headers)

    def update_directory_listing(self, listing_id, payload, headers):
        return self._request("PATCH", f"/api/directory-listings/{listing_id}", payload, headers)

    # ---- Reinstatement ----
    def create_reinstatement_request(self, member_id, headers):
        return self._request(
            "POST", f"/api/members/{member_id}/reinstatement-requests", {}, headers
        )

    def list_reinstatement_requests(self, member_id, headers):
        return self._request(
            "GET", f"/api/members/{member_id}/reinstatement-requests", headers=headers
        )

    def approve_reinstatement_request(self, member_id, request_id, headers):
        return self._request(
            "POST",
            f"/api/members/{member_id}/reinstatement-requests/{request_id}/approve",
            {},
            headers,
        )

    def reject_reinstatement_request(self, member_id, request_id, headers):
        return self._request(
            "POST",
            f"/api/members/{member_id}/reinstatement-requests/{request_id}/reject",
            {},
            headers,
        )

    # ---- Revenue attribution ----
    def create_revenue_attribution(self, member_id, payload, headers):
        return self._request(
            "POST", f"/api/members/{member_id}/revenue-attributions", payload, headers
        )

    def list_revenue_attributions(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/members/{member_id}/revenue-attributions",
            headers=headers,
            params=params,
        )

    # ---- System / scheduler ----
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    def run_renewal_cycle(self, headers):
        return self._request("POST", "/api/_scheduler/run_renewal_cycle", {}, headers)


api_client = ApiClient()
