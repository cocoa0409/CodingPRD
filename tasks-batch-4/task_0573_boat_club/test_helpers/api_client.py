"""API client: one method per endpoint defined in the Boat Club PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Docks ----
    def create_dock(self, payload, headers):
        return self._request("POST", "/docks", payload, headers)

    def get_dock(self, dock_id, headers):
        return self._request("GET", f"/docks/{dock_id}", headers=headers)

    def list_docks(self, headers, params=None):
        return self._request("GET", "/docks", headers=headers, params=params)

    # ---- Membership Tiers ----
    def create_tier(self, payload, headers):
        return self._request("POST", "/membership-tiers", payload, headers)

    def get_tier(self, tier_code, headers):
        return self._request("GET", f"/membership-tiers/{tier_code}", headers=headers)

    def list_tiers(self, headers, params=None):
        return self._request("GET", "/membership-tiers", headers=headers, params=params)

    # ---- Boats ----
    def create_boat(self, payload, headers):
        return self._request("POST", "/boats", payload, headers)

    def get_boat(self, boat_id, headers):
        return self._request("GET", f"/boats/{boat_id}", headers=headers)

    def list_boats(self, headers, params=None):
        return self._request("GET", "/boats", headers=headers, params=params)

    def boat_maintenance(self, boat_id, payload, headers):
        return self._request("POST", f"/boats/{boat_id}/maintenance", payload, headers)

    def boat_clean_complete(self, boat_id, headers):
        return self._request("POST", f"/boats/{boat_id}/clean-complete", {}, headers)

    # ---- Members ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def suspend_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/suspend", payload, headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/reinstate", {}, headers)

    def create_dues_invoice(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/dues-invoices", payload, headers)

    # ---- Reservations ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/confirm", {}, headers)

    def checkout_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/checkout", payload, headers)

    def return_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/return", payload, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", {}, headers)

    # ---- Training Sessions ----
    def create_training_session(self, payload, headers):
        return self._request("POST", "/training-sessions", payload, headers)

    def get_training_session(self, session_id, headers):
        return self._request("GET", f"/training-sessions/{session_id}", headers=headers)

    def list_training_sessions(self, headers, params=None):
        return self._request("GET", "/training-sessions", headers=headers, params=params)

    # ---- Enrollments ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def mark_attendance(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/mark-attendance", payload, headers)

    # ---- Damage Reports ----
    def create_damage_report(self, payload, headers):
        return self._request("POST", "/damage-reports", payload, headers)

    def get_damage_report(self, report_id, headers):
        return self._request("GET", f"/damage-reports/{report_id}", headers=headers)

    def list_damage_reports(self, headers, params=None):
        return self._request("GET", "/damage-reports", headers=headers, params=params)

    def assess_damage_report(self, report_id, headers):
        return self._request("POST", f"/damage-reports/{report_id}/assess", {}, headers)

    # ---- Fees ----
    def get_fee(self, fee_id, headers):
        return self._request("GET", f"/fees/{fee_id}", headers=headers)

    def list_fees(self, headers, params=None):
        return self._request("GET", "/fees", headers=headers, params=params)

    def waive_fee(self, fee_id, headers):
        return self._request("POST", f"/fees/{fee_id}/waive", {}, headers)

    # ---- Dues Invoices ----
    def get_dues_invoice(self, invoice_id, headers):
        return self._request("GET", f"/dues-invoices/{invoice_id}", headers=headers)

    def list_dues_invoices(self, headers, params=None):
        return self._request("GET", "/dues-invoices", headers=headers, params=params)

    def pay_dues_invoice(self, invoice_id, headers):
        return self._request("POST", f"/dues-invoices/{invoice_id}/pay", {}, headers)

    # ---- Test-driving operations ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def run_no_show_sweep(self, headers):
        return self._request("POST", "/_ops/run-no-show-sweep", {}, headers)


api_client = ApiClient()
