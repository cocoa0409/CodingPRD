"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- EventProject ----
    def create_event(self, payload, headers):
        return self._request("POST", "/planning/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/planning/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/planning/events/{event_id}", headers=headers)

    def confirm_event(self, event_id, headers):
        return self._request("POST", f"/planning/events/{event_id}/confirm", {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/planning/events/{event_id}/complete", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/planning/events/{event_id}/cancel", {}, headers)

    # ---- Contract ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/planning/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/planning/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/planning/contracts/{contract_id}", headers=headers)

    def send_contract(self, contract_id, headers):
        return self._request("POST", f"/planning/contracts/{contract_id}/send", {}, headers)

    def sign_contract(self, contract_id, headers):
        return self._request("POST", f"/planning/contracts/{contract_id}/sign", {}, headers)

    def countersign_contract(self, contract_id, headers):
        return self._request("POST", f"/planning/contracts/{contract_id}/countersign", {}, headers)

    def request_revision(self, contract_id, headers):
        return self._request("POST", f"/planning/contracts/{contract_id}/request-revision", {}, headers)

    # ---- Vendor ----
    def create_vendor(self, payload, headers):
        return self._request("POST", "/planning/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/planning/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/planning/vendors/{vendor_id}", headers=headers)

    # ---- COI ----
    def create_coi(self, payload, headers):
        return self._request("POST", "/planning/cois", payload, headers)

    def list_cois(self, headers, params=None):
        return self._request("GET", "/planning/cois", headers=headers, params=params)

    def get_coi(self, coi_id, headers):
        return self._request("GET", f"/planning/cois/{coi_id}", headers=headers)

    def verify_coi(self, coi_id, headers):
        return self._request("POST", f"/planning/cois/{coi_id}/verify", {}, headers)

    # ---- VendorBooking ----
    def create_vendor_booking(self, payload, headers):
        return self._request("POST", "/planning/vendor-bookings", payload, headers)

    def list_vendor_bookings(self, headers, params=None):
        return self._request("GET", "/planning/vendor-bookings", headers=headers, params=params)

    def get_vendor_booking(self, booking_id, headers):
        return self._request("GET", f"/planning/vendor-bookings/{booking_id}", headers=headers)

    def book_vendor_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/planning/vendor-bookings/{booking_id}/book", payload, headers)

    def cancel_vendor_booking(self, booking_id, headers):
        return self._request("POST", f"/planning/vendor-bookings/{booking_id}/cancel", {}, headers)

    # ---- VendorPayment (minted by book; no direct create) ----
    def list_vendor_payments(self, headers, params=None):
        return self._request("GET", "/planning/vendor-payments", headers=headers, params=params)

    def get_vendor_payment(self, payment_id, headers):
        return self._request("GET", f"/planning/vendor-payments/{payment_id}", headers=headers)

    def pay_vendor_payment(self, payment_id, headers):
        return self._request("POST", f"/planning/vendor-payments/{payment_id}/pay", {}, headers)

    # ---- TimelineBlock ----
    def create_timeline_block(self, payload, headers):
        return self._request("POST", "/planning/timeline-blocks", payload, headers)

    def list_timeline_blocks(self, headers, params=None):
        return self._request("GET", "/planning/timeline-blocks", headers=headers, params=params)

    def get_timeline_block(self, block_id, headers):
        return self._request("GET", f"/planning/timeline-blocks/{block_id}", headers=headers)

    # ---- Guest ----
    def create_guest(self, payload, headers):
        return self._request("POST", "/planning/guests", payload, headers)

    def list_guests(self, headers, params=None):
        return self._request("GET", "/planning/guests", headers=headers, params=params)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/planning/guests/{guest_id}", headers=headers)

    def rsvp_guest(self, guest_id, payload, headers):
        return self._request("POST", f"/planning/guests/{guest_id}/rsvp", payload, headers)

    # ---- Table ----
    def create_table(self, payload, headers):
        return self._request("POST", "/planning/tables", payload, headers)

    def list_tables(self, headers, params=None):
        return self._request("GET", "/planning/tables", headers=headers, params=params)

    def get_table(self, table_id, headers):
        return self._request("GET", f"/planning/tables/{table_id}", headers=headers)

    # ---- SeatAssignment ----
    def create_seat_assignment(self, payload, headers):
        return self._request("POST", "/planning/seat-assignments", payload, headers)

    def list_seat_assignments(self, headers, params=None):
        return self._request("GET", "/planning/seat-assignments", headers=headers, params=params)

    def get_seat_assignment(self, assignment_id, headers):
        return self._request("GET", f"/planning/seat-assignments/{assignment_id}", headers=headers)

    def delete_seat_assignment(self, assignment_id, headers):
        return self._request("DELETE", f"/planning/seat-assignments/{assignment_id}", headers=headers)

    # ---- StaffMember ----
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/planning/staff-members", payload, headers)

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/planning/staff-members", headers=headers, params=params)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"/planning/staff-members/{staff_id}", headers=headers)

    # ---- StaffAssignment ----
    def create_staff_assignment(self, payload, headers):
        return self._request("POST", "/planning/staff-assignments", payload, headers)

    def list_staff_assignments(self, headers, params=None):
        return self._request("GET", "/planning/staff-assignments", headers=headers, params=params)

    def get_staff_assignment(self, assignment_id, headers):
        return self._request("GET", f"/planning/staff-assignments/{assignment_id}", headers=headers)


api_client = ApiClient()
