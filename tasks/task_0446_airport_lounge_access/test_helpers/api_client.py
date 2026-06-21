"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions).

Subclasses GenericApiClient; the base _request(method, path, payload, headers, params)
is inherited. The system is a flat topology — entities are peer top-level collections
linked by foreign keys.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (test-driving) --------------------------------------
    def set_clock(self, to_iso8601: str, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- MembershipPlan ----------------------------------------------------
    def create_plan(self, payload, headers):
        return self._request("POST", "/membership-plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/membership-plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/membership-plans/{plan_id}", headers=headers)

    # ---- Lounge ------------------------------------------------------------
    def create_lounge(self, payload, headers):
        return self._request("POST", "/lounges", payload, headers)

    def list_lounges(self, headers, params=None):
        return self._request("GET", "/lounges", headers=headers, params=params)

    def get_lounge(self, lounge_id, headers):
        return self._request("GET", f"/lounges/{lounge_id}", headers=headers)

    def get_settlement_summary(self, lounge_id, headers):
        return self._request(
            "GET", f"/lounges/{lounge_id}/settlement-summary", headers=headers
        )

    def close_lounge(self, lounge_id, payload, headers):
        return self._request("POST", f"/lounges/{lounge_id}/close", payload, headers)

    def reopen_lounge(self, lounge_id, headers):
        return self._request("POST", f"/lounges/{lounge_id}/reopen", {}, headers)

    def sweep_lounge(self, lounge_id, headers):
        return self._request("POST", f"/lounges/{lounge_id}/sweep", {}, headers)

    def purchase_day_pass(self, lounge_id, payload, headers):
        return self._request("POST", f"/lounges/{lounge_id}/day-passes", payload, headers)

    def pay_settlements(self, lounge_id, headers):
        return self._request(
            "POST", f"/lounges/{lounge_id}/settlements/pay", {}, headers
        )

    # ---- Member ------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/memberships/{member_id}", headers=headers)

    def reinstate_member(self, member_id, headers):
        return self._request(
            "POST", f"/memberships/{member_id}/reinstate", {}, headers
        )

    def roll_year(self, member_id, headers):
        return self._request(
            "POST", f"/memberships/{member_id}/roll-year", {}, headers
        )

    # ---- EligibilityCard ---------------------------------------------------
    def create_card(self, payload, headers):
        return self._request("POST", "/eligibility-cards", payload, headers)

    def list_cards(self, headers, params=None):
        return self._request("GET", "/eligibility-cards", headers=headers, params=params)

    def get_card(self, card_id, headers):
        return self._request("GET", f"/eligibility-cards/{card_id}", headers=headers)

    def activate_card(self, card_id, headers):
        return self._request(
            "POST", f"/eligibility-cards/{card_id}/activate", {}, headers
        )

    # ---- Visit -------------------------------------------------------------
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def check_in(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/check-in", {}, headers)

    def complete_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/complete", {}, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", {}, headers)

    # ---- Guest -------------------------------------------------------------
    def list_guests(self, headers, params=None):
        return self._request("GET", "/guests", headers=headers, params=params)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    # ---- DayPass -----------------------------------------------------------
    def list_day_passes(self, headers, params=None):
        return self._request("GET", "/day-passes", headers=headers, params=params)

    def get_day_pass(self, day_pass_id, headers):
        return self._request("GET", f"/day-passes/{day_pass_id}", headers=headers)

    def refund_day_pass(self, day_pass_id, headers):
        return self._request(
            "POST", f"/day-passes/{day_pass_id}/refund", {}, headers
        )

    # ---- Settlement --------------------------------------------------------
    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def reverse_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/reverse", {}, headers
        )

    # ---- LedgerEntry -------------------------------------------------------
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    # ---- ShowerSuite -------------------------------------------------------
    def create_shower_suite(self, payload, headers):
        return self._request("POST", "/shower-suites", payload, headers)

    def list_shower_suites(self, headers, params=None):
        return self._request("GET", "/shower-suites", headers=headers, params=params)

    def get_shower_suite(self, suite_id, headers):
        return self._request("GET", f"/shower-suites/{suite_id}", headers=headers)

    # ---- ShowerReservation -------------------------------------------------
    def create_shower_reservation(self, payload, headers):
        return self._request("POST", "/shower-reservations", payload, headers)

    def list_shower_reservations(self, headers, params=None):
        return self._request(
            "GET", "/shower-reservations", headers=headers, params=params
        )

    def get_shower_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/shower-reservations/{reservation_id}", headers=headers
        )

    def cancel_shower_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/shower-reservations/{reservation_id}/cancel", {}, headers
        )

    def complete_shower_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/shower-reservations/{reservation_id}/complete", {}, headers
        )


api_client = ApiClient()
