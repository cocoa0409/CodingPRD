"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, mounted outside /api)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Card holders
    # ------------------------------------------------------------------
    def create_card_holder(self, payload, headers):
        return self._request("POST", "/api/card-holders", payload, headers)

    def list_card_holders(self, headers, params=None):
        return self._request("GET", "/api/card-holders", headers=headers, params=params)

    def get_card_holder(self, holder_id, headers):
        return self._request("GET", f"/api/card-holders/{holder_id}", headers=headers)

    def suspend_card_holder(self, holder_id, headers):
        return self._request("POST", f"/api/card-holders/{holder_id}/suspend", {}, headers)

    def reinstate_card_holder(self, holder_id, headers):
        return self._request("POST", f"/api/card-holders/{holder_id}/reinstate", {}, headers)

    def withdraw_card_holder(self, holder_id, headers):
        return self._request("POST", f"/api/card-holders/{holder_id}/withdraw", {}, headers)

    def graduate_card_holder(self, holder_id, headers):
        return self._request("POST", f"/api/card-holders/{holder_id}/graduate", {}, headers)

    def fraud_review_card_holder(self, holder_id, payload, headers):
        return self._request("POST", f"/api/card-holders/{holder_id}/fraud-review",
                             payload, headers)

    # ------------------------------------------------------------------
    # Campus cards
    # ------------------------------------------------------------------
    def issue_card(self, holder_id, payload, headers):
        return self._request("POST", f"/api/card-holders/{holder_id}/cards",
                             payload, headers)

    def list_cards(self, headers, params=None):
        return self._request("GET", "/api/cards", headers=headers, params=params)

    def get_card(self, card_id, headers):
        return self._request("GET", f"/api/cards/{card_id}", headers=headers)

    def activate_card(self, card_id, payload, headers):
        return self._request("POST", f"/api/cards/{card_id}/activate", payload, headers)

    def report_card_lost(self, card_id, headers):
        return self._request("POST", f"/api/cards/{card_id}/report-lost", {}, headers)

    def report_card_stolen(self, card_id, payload, headers):
        return self._request("POST", f"/api/cards/{card_id}/report-stolen",
                             payload, headers)

    def unfreeze_card(self, card_id, headers):
        return self._request("POST", f"/api/cards/{card_id}/unfreeze", {}, headers)

    def replace_card(self, card_id, payload, headers):
        return self._request("POST", f"/api/cards/{card_id}/replacement",
                             payload, headers)

    def deactivate_card(self, card_id, headers):
        return self._request("POST", f"/api/cards/{card_id}/deactivate", {}, headers)

    # ------------------------------------------------------------------
    # Photo submissions
    # ------------------------------------------------------------------
    def submit_card_photo(self, card_id, payload, headers):
        return self._request("POST", f"/api/cards/{card_id}/photos", payload, headers)

    def list_card_photos(self, card_id, headers, params=None):
        return self._request("GET", f"/api/cards/{card_id}/photos",
                             headers=headers, params=params)

    def review_photo(self, photo_id, payload, headers):
        return self._request("POST", f"/api/photos/{photo_id}/review", payload, headers)

    # ------------------------------------------------------------------
    # Terms
    # ------------------------------------------------------------------
    def create_term(self, payload, headers):
        return self._request("POST", "/api/terms", payload, headers)

    def list_terms(self, headers, params=None):
        return self._request("GET", "/api/terms", headers=headers, params=params)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/api/terms/{term_id}", headers=headers)

    def open_term(self, term_id, headers):
        return self._request("POST", f"/api/terms/{term_id}/open", {}, headers)

    def advance_term_week(self, term_id, headers):
        return self._request("POST", f"/api/terms/{term_id}/advance-week", {}, headers)

    def close_term(self, term_id, headers):
        return self._request("POST", f"/api/terms/{term_id}/close", {}, headers)

    def settle_term(self, term_id, headers):
        return self._request("POST", f"/api/terms/{term_id}/settle", {}, headers)

    # ------------------------------------------------------------------
    # Meal plans
    # ------------------------------------------------------------------
    def create_meal_plan(self, payload, headers):
        return self._request("POST", "/api/meal-plans", payload, headers)

    def list_meal_plans(self, headers, params=None):
        return self._request("GET", "/api/meal-plans", headers=headers, params=params)

    def get_meal_plan(self, plan_id, headers):
        return self._request("GET", f"/api/meal-plans/{plan_id}", headers=headers)

    def publish_meal_plan(self, plan_id, headers):
        return self._request("POST", f"/api/meal-plans/{plan_id}/publish", {}, headers)

    def retire_meal_plan(self, plan_id, headers):
        return self._request("POST", f"/api/meal-plans/{plan_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # Meal plan enrollments
    # ------------------------------------------------------------------
    def create_enrollment(self, holder_id, payload, headers):
        return self._request("POST", f"/api/card-holders/{holder_id}/enrollments",
                             payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/api/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/api/enrollments/{enrollment_id}", headers=headers)

    def cancel_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/api/enrollments/{enrollment_id}/cancel",
                             {}, headers)

    def list_enrollment_change_requests(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/api/enrollments/{enrollment_id}/change-requests",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Plan change requests
    # ------------------------------------------------------------------
    def create_change_request(self, enrollment_id, payload, headers):
        return self._request("POST", f"/api/enrollments/{enrollment_id}/change-requests",
                             payload, headers)

    def list_change_requests(self, headers, params=None):
        return self._request("GET", "/api/change-requests", headers=headers, params=params)

    def get_change_request(self, request_id, headers):
        return self._request("GET", f"/api/change-requests/{request_id}", headers=headers)

    def approve_change_request(self, request_id, headers):
        return self._request("POST", f"/api/change-requests/{request_id}/approve",
                             {}, headers)

    def deny_change_request(self, request_id, payload, headers):
        return self._request("POST", f"/api/change-requests/{request_id}/deny",
                             payload, headers)

    def withdraw_change_request(self, request_id, headers):
        return self._request("POST", f"/api/change-requests/{request_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # Declining-balance accounts
    # ------------------------------------------------------------------
    def create_account(self, holder_id, payload, headers):
        return self._request("POST", f"/api/card-holders/{holder_id}/accounts",
                             payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/api/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}", headers=headers)

    def fund_account(self, account_id, payload, headers):
        return self._request("POST", f"/api/accounts/{account_id}/funding",
                             payload, headers)

    def adjust_account(self, account_id, payload, headers):
        return self._request("POST", f"/api/accounts/{account_id}/adjustments",
                             payload, headers)

    # ------------------------------------------------------------------
    # Ledger entries
    # ------------------------------------------------------------------
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/api/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/api/ledger-entries/{entry_id}", headers=headers)

    # ------------------------------------------------------------------
    # Refund requests
    # ------------------------------------------------------------------
    def create_refund_request(self, account_id, headers):
        return self._request("POST", f"/api/accounts/{account_id}/refund-requests",
                             {}, headers)

    def list_refund_requests(self, headers, params=None):
        return self._request("GET", "/api/refund-requests", headers=headers, params=params)

    def get_refund_request(self, refund_id, headers):
        return self._request("GET", f"/api/refund-requests/{refund_id}", headers=headers)

    def approve_refund_request(self, refund_id, headers):
        return self._request("POST", f"/api/refund-requests/{refund_id}/approve",
                             {}, headers)

    def deny_refund_request(self, refund_id, payload, headers):
        return self._request("POST", f"/api/refund-requests/{refund_id}/deny",
                             payload, headers)

    def pay_refund_request(self, refund_id, headers):
        return self._request("POST", f"/api/refund-requests/{refund_id}/pay", {}, headers)

    # ------------------------------------------------------------------
    # Card transactions
    # ------------------------------------------------------------------
    def create_transaction(self, payload, headers):
        return self._request("POST", "/api/transactions", payload, headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/api/transactions", headers=headers, params=params)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/api/transactions/{transaction_id}", headers=headers)

    # ------------------------------------------------------------------
    # Disputes
    # ------------------------------------------------------------------
    def create_dispute(self, transaction_id, payload, headers):
        return self._request("POST", f"/api/transactions/{transaction_id}/disputes",
                             payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/api/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/api/disputes/{dispute_id}", headers=headers)

    def grant_provisional_credit(self, dispute_id, headers):
        return self._request("POST",
                             f"/api/disputes/{dispute_id}/grant-provisional-credit",
                             {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/api/disputes/{dispute_id}/resolve",
                             payload, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/api/disputes/{dispute_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Door zones
    # ------------------------------------------------------------------
    def create_door_zone(self, payload, headers):
        return self._request("POST", "/api/door-zones", payload, headers)

    def list_door_zones(self, headers, params=None):
        return self._request("GET", "/api/door-zones", headers=headers, params=params)

    def get_door_zone(self, zone_id, headers):
        return self._request("GET", f"/api/door-zones/{zone_id}", headers=headers)

    def decommission_door_zone(self, zone_id, headers):
        return self._request("POST", f"/api/door-zones/{zone_id}/decommission",
                             {}, headers)

    # ------------------------------------------------------------------
    # Access grants
    # ------------------------------------------------------------------
    def create_access_grant(self, card_id, payload, headers):
        return self._request("POST", f"/api/cards/{card_id}/access-grants",
                             payload, headers)

    def list_access_grants(self, headers, params=None):
        return self._request("GET", "/api/access-grants", headers=headers, params=params)

    def get_access_grant(self, grant_id, headers):
        return self._request("GET", f"/api/access-grants/{grant_id}", headers=headers)

    def suspend_access_grant(self, grant_id, headers):
        return self._request("POST", f"/api/access-grants/{grant_id}/suspend",
                             {}, headers)

    def reinstate_access_grant(self, grant_id, headers):
        return self._request("POST", f"/api/access-grants/{grant_id}/reinstate",
                             {}, headers)

    def revoke_access_grant(self, grant_id, headers):
        return self._request("POST", f"/api/access-grants/{grant_id}/revoke", {}, headers)

    # ------------------------------------------------------------------
    # Access events
    # ------------------------------------------------------------------
    def create_access_event(self, payload, headers):
        return self._request("POST", "/api/access-events", payload, headers)

    def list_access_events(self, headers, params=None):
        return self._request("GET", "/api/access-events", headers=headers, params=params)

    def get_access_event(self, event_id, headers):
        return self._request("GET", f"/api/access-events/{event_id}", headers=headers)

    # ------------------------------------------------------------------
    # Merchants
    # ------------------------------------------------------------------
    def create_merchant(self, payload, headers):
        return self._request("POST", "/api/merchants", payload, headers)

    def list_merchants(self, headers, params=None):
        return self._request("GET", "/api/merchants", headers=headers, params=params)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/api/merchants/{merchant_id}", headers=headers)

    def activate_merchant(self, merchant_id, headers):
        return self._request("POST", f"/api/merchants/{merchant_id}/activate",
                             {}, headers)

    def suspend_merchant(self, merchant_id, headers):
        return self._request("POST", f"/api/merchants/{merchant_id}/suspend",
                             {}, headers)

    def terminate_merchant(self, merchant_id, headers):
        return self._request("POST", f"/api/merchants/{merchant_id}/terminate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Merchant settlements
    # ------------------------------------------------------------------
    def create_settlement(self, merchant_id, payload, headers):
        return self._request("POST", f"/api/merchants/{merchant_id}/settlements",
                             payload, headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/api/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/api/settlements/{settlement_id}", headers=headers)

    def submit_settlement(self, settlement_id, headers):
        return self._request("POST", f"/api/settlements/{settlement_id}/submit",
                             {}, headers)

    def approve_settlement(self, settlement_id, headers):
        return self._request("POST", f"/api/settlements/{settlement_id}/approve",
                             {}, headers)

    def reject_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/api/settlements/{settlement_id}/reject",
                             payload, headers)

    def pay_settlement(self, settlement_id, headers):
        return self._request("POST", f"/api/settlements/{settlement_id}/pay", {}, headers)


api_client = ApiClient()
