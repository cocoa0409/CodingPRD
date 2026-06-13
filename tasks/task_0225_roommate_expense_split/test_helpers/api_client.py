"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- RoommateProfile ----
    def create_profile(self, payload, headers=None):
        return self._request("POST", "/roommate-profiles", payload, headers)

    def get_profile(self, profile_id, headers):
        return self._request("GET", f"/roommate-profiles/{profile_id}", headers=headers)

    def list_profiles(self, headers, params=None):
        return self._request("GET", "/roommate-profiles", headers=headers, params=params)

    def list_profile_bill_splits(self, profile_id, headers, params=None):
        return self._request(
            "GET", f"/roommate-profiles/{profile_id}/bill-splits", headers=headers, params=params
        )

    def list_profile_expense_shares(self, profile_id, headers, params=None):
        return self._request(
            "GET", f"/roommate-profiles/{profile_id}/expense-shares", headers=headers, params=params
        )

    # ---- RoomListing ----
    def create_listing(self, payload, headers):
        return self._request("POST", "/room-listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/room-listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/room-listings", headers=headers, params=params)

    # ---- MatchRequest ----
    def create_match_request(self, payload, headers):
        return self._request("POST", "/match-requests", payload, headers)

    def get_match_request(self, mr_id, headers):
        return self._request("GET", f"/match-requests/{mr_id}", headers=headers)

    def list_match_requests(self, headers, params=None):
        return self._request("GET", "/match-requests", headers=headers, params=params)

    def accept_match_request(self, mr_id, headers):
        return self._request("POST", f"/match-requests/{mr_id}/accept", {}, headers)

    def reject_match_request(self, mr_id, headers):
        return self._request("POST", f"/match-requests/{mr_id}/reject", {}, headers)

    def withdraw_match_request(self, mr_id, headers):
        return self._request("POST", f"/match-requests/{mr_id}/withdraw", {}, headers)

    def reapply_match_request(self, mr_id, headers):
        return self._request("POST", f"/match-requests/{mr_id}/reapply", {}, headers)

    # ---- Household ----
    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/households", headers=headers, params=params)

    def list_household_memberships(self, household_id, headers, params=None):
        return self._request(
            "GET", f"/households/{household_id}/memberships", headers=headers, params=params
        )

    def list_household_bills(self, household_id, headers, params=None):
        return self._request(
            "GET", f"/households/{household_id}/bills", headers=headers, params=params
        )

    def list_household_expenses(self, household_id, headers, params=None):
        return self._request(
            "GET", f"/households/{household_id}/expenses", headers=headers, params=params
        )

    def list_household_settlements(self, household_id, headers, params=None):
        return self._request(
            "GET", f"/households/{household_id}/settlements", headers=headers, params=params
        )

    def list_household_disputes(self, household_id, headers, params=None):
        return self._request(
            "GET", f"/households/{household_id}/disputes", headers=headers, params=params
        )

    # ---- Membership ----
    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def activate_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/activate", {}, headers)

    def move_out_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/move-out", {}, headers)

    # ---- Bill ----
    def create_bill(self, payload, headers):
        return self._request("POST", "/bills", payload, headers)

    def get_bill(self, bill_id, headers):
        return self._request("GET", f"/bills/{bill_id}", headers=headers)

    def list_bill_splits(self, bill_id, headers, params=None):
        return self._request("GET", f"/bills/{bill_id}/splits", headers=headers, params=params)

    def record_payment(self, bill_id, payload, headers):
        return self._request("POST", f"/bills/{bill_id}/record-payment", payload, headers)

    # ---- Expense ----
    def create_expense(self, payload, headers):
        return self._request("POST", "/expenses", payload, headers)

    def list_expenses(self, headers, params=None):
        return self._request("GET", "/expenses", headers=headers, params=params)

    def get_expense(self, expense_id, headers):
        return self._request("GET", f"/expenses/{expense_id}", headers=headers)

    def list_expense_shares(self, expense_id, headers, params=None):
        return self._request(
            "GET", f"/expenses/{expense_id}/shares", headers=headers, params=params
        )

    def void_expense(self, expense_id, headers):
        return self._request("POST", f"/expenses/{expense_id}/void", {}, headers)

    # ---- Settlement ----
    def create_settlement(self, payload, headers):
        return self._request("POST", "/settlements", payload, headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def confirm_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/settlements/{settlement_id}/confirm", payload, headers)

    def repropose_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/repropose", {}, headers)

    def cancel_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/cancel", {}, headers)

    # ---- PaymentReminder ----
    def create_payment_reminder(self, payload, headers):
        return self._request("POST", "/payment-reminders", payload, headers)

    def get_payment_reminder(self, reminder_id, headers):
        return self._request("GET", f"/payment-reminders/{reminder_id}", headers=headers)

    def list_payment_reminders(self, headers, params=None):
        return self._request("GET", "/payment-reminders", headers=headers, params=params)

    def acknowledge_reminder(self, reminder_id, headers):
        return self._request("POST", f"/payment-reminders/{reminder_id}/acknowledge", {}, headers)

    # ---- Dispute ----
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def claim_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/claim", {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    def reject_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/reject", {}, headers)

    def reopen_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/reopen", {}, headers)

    # ---- Test-driving endpoints ----
    def set_clock(self, to_iso8601, headers=None):
        return self._request("POST", "/_clock/set", {"to_iso8601": to_iso8601}, headers)

    def dispatch_reminders(self, headers):
        return self._request("POST", "/_reminders/dispatch", {}, headers)


api_client = ApiClient()
