"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Patron ──────────────────────────────────────────────────────
    def create_patron(self, payload, headers):
        return self._request("POST", "/patrons", payload, headers)

    def get_patron(self, patron_id, headers):
        return self._request("GET", f"/patrons/{patron_id}", headers=headers)

    def list_patrons(self, headers, params=None):
        return self._request("GET", "/patrons", headers=headers, params=params)

    # ── MembershipPlan ──────────────────────────────────────────────
    def create_membership_plan(self, payload, headers):
        return self._request("POST", "/membership-plans", payload, headers)

    def get_membership_plan(self, plan_id, headers):
        return self._request("GET", f"/membership-plans/{plan_id}", headers=headers)

    def list_membership_plans(self, headers, params=None):
        return self._request("GET", "/membership-plans", headers=headers, params=params)

    # ── Membership ──────────────────────────────────────────────────
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def renew_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/renew", payload, headers)

    def cancel_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"/memberships/{membership_id}/cancel", payload or {}, headers)

    def set_auto_renew(self, membership_id, payload, headers):
        return self._request("PATCH", f"/memberships/{membership_id}/auto-renew", payload, headers)

    # ── HouseholdMember ─────────────────────────────────────────────
    def add_household_member(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/household-members", payload, headers)

    def get_household_member(self, member_id, headers):
        return self._request("GET", f"/household-members/{member_id}", headers=headers)

    def list_household_members(self, headers, params=None):
        return self._request("GET", "/household-members", headers=headers, params=params)

    def remove_household_member(self, member_id, headers):
        return self._request("DELETE", f"/household-members/{member_id}", headers=headers)

    # ── GuestPass ───────────────────────────────────────────────────
    def get_guest_pass(self, pass_id, headers):
        return self._request("GET", f"/guest-passes/{pass_id}", headers=headers)

    def list_guest_passes(self, headers, params=None):
        return self._request("GET", "/guest-passes", headers=headers, params=params)

    def list_guest_pass_tickets(self, pass_id, headers):
        return self._request("GET", f"/guest-passes/{pass_id}/tickets", headers=headers)

    # ── TimedEntrySlot ──────────────────────────────────────────────
    def create_slot(self, payload, headers):
        return self._request("POST", "/timed-entry-slots", payload, headers)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/timed-entry-slots/{slot_id}", headers=headers)

    def list_slots(self, headers, params=None):
        return self._request("GET", "/timed-entry-slots", headers=headers, params=params)

    def close_slot(self, slot_id, headers, payload=None):
        return self._request("POST", f"/timed-entry-slots/{slot_id}/close", payload or {}, headers)

    # ── SpecialExhibit + ExhibitSession ─────────────────────────────
    def create_special_exhibit(self, payload, headers):
        return self._request("POST", "/special-exhibits", payload, headers)

    def get_special_exhibit(self, exhibit_id, headers):
        return self._request("GET", f"/special-exhibits/{exhibit_id}", headers=headers)

    def list_special_exhibits(self, headers, params=None):
        return self._request("GET", "/special-exhibits", headers=headers, params=params)

    def create_exhibit_session(self, exhibit_id, payload, headers):
        return self._request("POST", f"/special-exhibits/{exhibit_id}/sessions", payload, headers)

    def list_exhibit_sessions(self, exhibit_id, headers, params=None):
        return self._request("GET", f"/special-exhibits/{exhibit_id}/sessions", headers=headers, params=params)

    def get_exhibit_session(self, session_id, headers):
        return self._request("GET", f"/exhibit-sessions/{session_id}", headers=headers)

    # ── ReciprocalPartner ───────────────────────────────────────────
    def create_reciprocal_partner(self, payload, headers):
        return self._request("POST", "/reciprocal-partners", payload, headers)

    def get_reciprocal_partner(self, partner_id, headers):
        return self._request("GET", f"/reciprocal-partners/{partner_id}", headers=headers)

    def list_reciprocal_partners(self, headers, params=None):
        return self._request("GET", "/reciprocal-partners", headers=headers, params=params)

    # ── AdmissionOrder ──────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/admission-orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/admission-orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/admission-orders", headers=headers, params=params)

    def add_ticket(self, order_id, payload, headers):
        return self._request("POST", f"/admission-orders/{order_id}/tickets", payload, headers)

    def update_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/admission-orders/{order_id}", payload, headers)

    def confirm_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/admission-orders/{order_id}/confirm", payload or {}, headers)

    def check_in_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/admission-orders/{order_id}/check-in", payload or {}, headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/admission-orders/{order_id}/cancel", payload or {}, headers)

    def refund_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/admission-orders/{order_id}/refund", payload or {}, headers)

    # ── AdmissionTicket ─────────────────────────────────────────────
    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/admission-tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/admission-tickets", headers=headers, params=params)

    # ── Donation ────────────────────────────────────────────────────
    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/donations/{donation_id}", headers=headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/donations", headers=headers, params=params)

    # ── Test-driving hooks (/_*) ────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def settle_payment(self, payload, headers):
        return self._request("POST", "/_payments/settle", payload, headers)

    def run_renewals(self, headers, payload=None):
        return self._request("POST", "/_jobs/run_renewals", payload or {}, headers)

    def run_expirations(self, headers, payload=None):
        return self._request("POST", "/_jobs/run_expirations", payload or {}, headers)


api_client = ApiClient()
