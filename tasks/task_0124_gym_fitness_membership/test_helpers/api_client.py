"""API client: one method per endpoint defined in the PRD."""
import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        # Per-test-server isolation restarts the server before every test. The
        # persistent requests.Session can reuse a keep-alive socket that the
        # just-restarted server has already dropped, surfacing intermittently as
        # BadStatusLine/ConnectionError on the first request after a reboot.
        # Force `Connection: close` so no stale socket is reused, and retry once
        # on ConnectionError to absorb the narrow restart race. (Known harness
        # flake — a test-helper fix, not an implementation bug.)
        hdrs = dict(headers or {})
        hdrs.setdefault("Connection", "close")
        try:
            return super()._request(method, path, payload, hdrs, params)
        except requests.exceptions.ConnectionError:
            return super()._request(method, path, payload, hdrs, params)

    # ---- MembershipPlan ----
    def create_membership_plan(self, payload, headers):
        return self._request("POST", "/membership-plans", payload, headers)

    def get_membership_plan(self, plan_id, headers):
        return self._request("GET", f"/membership-plans/{plan_id}", headers=headers)

    # ---- Location ----
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def activate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/activate", headers=headers)

    def freeze_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/freeze", payload, headers)

    def unfreeze_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/unfreeze", headers=headers)

    def cancel_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/cancel", headers=headers)

    # ---- ClassSession ----
    def create_class_session(self, payload, headers):
        return self._request("POST", "/class-sessions", payload, headers)

    def get_class_session(self, session_id, headers):
        return self._request("GET", f"/class-sessions/{session_id}", headers=headers)

    def list_class_sessions(self, headers, params=None):
        return self._request("GET", "/class-sessions", headers=headers, params=params)

    def cancel_class_session(self, session_id, payload, headers):
        return self._request("POST", f"/class-sessions/{session_id}/cancel", payload, headers)

    def complete_class_session(self, session_id, payload, headers):
        return self._request("POST", f"/class-sessions/{session_id}/complete", payload, headers)

    # ---- Booking ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", headers=headers)

    def attend_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/attend", headers=headers)

    # ---- PTPackage ----
    def create_pt_package(self, payload, headers):
        return self._request("POST", "/pt-packages", payload, headers)

    def get_pt_package(self, package_id, headers):
        return self._request("GET", f"/pt-packages/{package_id}", headers=headers)

    def list_pt_packages(self, headers, params=None):
        return self._request("GET", "/pt-packages", headers=headers, params=params)

    # ---- PTSession ----
    def create_pt_session(self, payload, headers):
        return self._request("POST", "/pt-sessions", payload, headers)

    def get_pt_session(self, pt_session_id, headers):
        return self._request("GET", f"/pt-sessions/{pt_session_id}", headers=headers)

    def list_pt_sessions(self, headers, params=None):
        return self._request("GET", "/pt-sessions", headers=headers, params=params)

    def complete_pt_session(self, pt_session_id, headers):
        return self._request("POST", f"/pt-sessions/{pt_session_id}/complete", headers=headers)

    def no_show_pt_session(self, pt_session_id, headers):
        return self._request("POST", f"/pt-sessions/{pt_session_id}/no-show", headers=headers)

    def cancel_pt_session(self, pt_session_id, payload, headers):
        return self._request("POST", f"/pt-sessions/{pt_session_id}/cancel", payload, headers)

    # ---- DuesInvoice ----
    def create_dues_invoice(self, payload, headers):
        return self._request("POST", "/dues-invoices", payload, headers)

    def get_dues_invoice(self, invoice_id, headers):
        return self._request("GET", f"/dues-invoices/{invoice_id}", headers=headers)

    def list_dues_invoices(self, headers, params=None):
        return self._request("GET", "/dues-invoices", headers=headers, params=params)

    def pay_dues_invoice(self, invoice_id, headers):
        return self._request("POST", f"/dues-invoices/{invoice_id}/pay", headers=headers)

    def void_dues_invoice(self, invoice_id, headers):
        return self._request("POST", f"/dues-invoices/{invoice_id}/void", headers=headers)

    # ---- GuestPass ----
    def create_guest_pass(self, payload, headers):
        return self._request("POST", "/guest-passes", payload, headers)

    def get_guest_pass(self, guest_pass_id, headers):
        return self._request("GET", f"/guest-passes/{guest_pass_id}", headers=headers)

    def list_guest_passes(self, headers, params=None):
        return self._request("GET", "/guest-passes", headers=headers, params=params)

    def revoke_guest_pass(self, guest_pass_id, headers):
        return self._request("POST", f"/guest-passes/{guest_pass_id}/revoke", headers=headers)

    # ---- CheckIn ----
    def create_check_in(self, payload, headers):
        return self._request("POST", "/check-ins", payload, headers)

    def get_check_in(self, check_in_id, headers):
        return self._request("GET", f"/check-ins/{check_in_id}", headers=headers)

    def list_check_ins(self, headers, params=None):
        return self._request("GET", "/check-ins", headers=headers, params=params)

    def checkout_check_in(self, check_in_id, headers):
        return self._request("POST", f"/check-ins/{check_in_id}/checkout", headers=headers)

    # ---- Administrative clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def advance_dues(self, headers):
        return self._request("POST", "/_clock/advance_dues", headers=headers)


api_client = ApiClient()
