"""API client: one method per endpoint defined in the Country Club Membership PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clubs ----
    def create_club(self, payload, headers):
        return self._request("POST", "/clubs", payload, headers)

    def get_club(self, club_id, headers):
        return self._request("GET", f"/clubs/{club_id}", headers=headers)

    def close_period(self, club_id, payload, headers):
        return self._request("POST", f"/clubs/{club_id}/close-period", payload, headers)

    def open_statements(self, club_id, headers, payload=None):
        return self._request("POST", f"/clubs/{club_id}/open-statements", payload or {}, headers)

    # ---- Membership categories ----
    def create_category(self, payload, headers):
        return self._request("POST", "/membership-categories", payload, headers)

    def get_category(self, category_id, headers):
        return self._request("GET", f"/membership-categories/{category_id}", headers=headers)

    def list_categories(self, headers, params=None):
        return self._request("GET", "/membership-categories", headers=headers, params=params)

    # ---- Memberships ----
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def activate_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"/memberships/{membership_id}/activate", payload or {}, headers)

    def suspend_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"/memberships/{membership_id}/suspend", payload or {}, headers)

    def reinstate_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"/memberships/{membership_id}/reinstate", payload or {}, headers)

    def resign_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"/memberships/{membership_id}/resign", payload or {}, headers)

    def settle_resignation(self, membership_id, headers, payload=None):
        return self._request("POST", f"/memberships/{membership_id}/settle-resignation", payload or {}, headers)

    def create_payment(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/payments", payload, headers)

    # ---- Resources ----
    def create_resource(self, payload, headers):
        return self._request("POST", "/resources", payload, headers)

    def get_resource(self, resource_id, headers):
        return self._request("GET", f"/resources/{resource_id}", headers=headers)

    def list_resources(self, headers, params=None):
        return self._request("GET", "/resources", headers=headers, params=params)

    # ---- Reservations ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def propose_amend(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/propose-amend", payload, headers)

    def confirm_amend(self, reservation_id, headers, payload=None):
        return self._request("POST", f"/reservations/{reservation_id}/confirm-amend", payload or {}, headers)

    def abandon_amend(self, reservation_id, headers, payload=None):
        return self._request("POST", f"/reservations/{reservation_id}/abandon-amend", payload or {}, headers)

    def cancel_reservation(self, reservation_id, headers, payload=None):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", payload or {}, headers)

    def complete_reservation(self, reservation_id, headers, payload=None):
        return self._request("POST", f"/reservations/{reservation_id}/complete", payload or {}, headers)

    # ---- Chits ----
    def create_chit(self, payload, headers):
        return self._request("POST", "/chits", payload, headers)

    def get_chit(self, chit_id, headers):
        return self._request("GET", f"/chits/{chit_id}", headers=headers)

    def list_chits(self, headers, params=None):
        return self._request("GET", "/chits", headers=headers, params=params)

    def void_chit(self, chit_id, headers, payload=None):
        return self._request("POST", f"/chits/{chit_id}/void", payload or {}, headers)

    # ---- Guest passes ----
    def create_guest_pass(self, payload, headers):
        return self._request("POST", "/guest-passes", payload, headers)

    def get_guest_pass(self, guest_pass_id, headers):
        return self._request("GET", f"/guest-passes/{guest_pass_id}", headers=headers)

    def list_guest_passes(self, headers, params=None):
        return self._request("GET", "/guest-passes", headers=headers, params=params)

    def check_in_guest(self, guest_pass_id, headers, payload=None):
        return self._request("POST", f"/guest-passes/{guest_pass_id}/check-in", payload or {}, headers)

    def cancel_guest_pass(self, guest_pass_id, headers, payload=None):
        return self._request("POST", f"/guest-passes/{guest_pass_id}/cancel", payload or {}, headers)

    # ---- Capital assessments ----
    def create_assessment(self, payload, headers):
        return self._request("POST", "/capital-assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/capital-assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/capital-assessments", headers=headers, params=params)

    def levy_assessment(self, assessment_id, headers, payload=None):
        return self._request("POST", f"/capital-assessments/{assessment_id}/levy", payload or {}, headers)

    def cancel_assessment(self, assessment_id, headers, payload=None):
        return self._request("POST", f"/capital-assessments/{assessment_id}/cancel", payload or {}, headers)

    def list_assessment_charges_of(self, assessment_id, headers, params=None):
        return self._request("GET", f"/capital-assessments/{assessment_id}/charges", headers=headers, params=params)

    # ---- Assessment charges ----
    def get_assessment_charge(self, charge_id, headers):
        return self._request("GET", f"/assessment-charges/{charge_id}", headers=headers)

    def list_assessment_charges(self, headers, params=None):
        return self._request("GET", "/assessment-charges", headers=headers, params=params)

    # ---- Waitlist entries ----
    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/waitlist-entries", payload, headers)

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{entry_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)

    def offer_waitlist_entry(self, entry_id, headers, payload=None):
        return self._request("POST", f"/waitlist-entries/{entry_id}/offer", payload or {}, headers)

    def accept_waitlist_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/waitlist-entries/{entry_id}/accept", payload, headers)

    def decline_waitlist_entry(self, entry_id, headers, payload=None):
        return self._request("POST", f"/waitlist-entries/{entry_id}/decline", payload or {}, headers)

    # ---- Statements ----
    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/statements/{statement_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/statements", headers=headers, params=params)

    # ---- Clock (administrative) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
