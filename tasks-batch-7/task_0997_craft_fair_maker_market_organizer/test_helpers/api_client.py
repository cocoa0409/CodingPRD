"""API client: one method per endpoint defined in the PRD §4 endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Clock (test-driving) ----------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------- MakerEvent ----------
    def create_maker_event(self, payload, headers):
        return self._request("POST", "/maker-events", payload, headers)

    def list_maker_events(self, headers, params=None):
        return self._request("GET", "/maker-events", headers=headers, params=params)

    def get_maker_event(self, event_id, headers):
        return self._request("GET", f"/maker-events/{event_id}", headers=headers)

    def open_applications(self, event_id, headers):
        return self._request(
            "POST", f"/maker-events/{event_id}/open-applications", {}, headers
        )

    def close_applications(self, event_id, headers):
        return self._request(
            "POST", f"/maker-events/{event_id}/close-applications", {}, headers
        )

    def begin_scheduling(self, event_id, headers):
        return self._request(
            "POST", f"/maker-events/{event_id}/begin-scheduling", {}, headers
        )

    def go_live(self, event_id, headers):
        return self._request("POST", f"/maker-events/{event_id}/go-live", {}, headers)

    def end_event(self, event_id, headers):
        return self._request("POST", f"/maker-events/{event_id}/end-event", {}, headers)

    def close_event(self, event_id, headers):
        return self._request(
            "POST", f"/maker-events/{event_id}/close-event", {}, headers
        )

    def cancel_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/maker-events/{event_id}/cancel", payload or {}, headers
        )

    def set_weather(self, event_id, weather_flag, headers):
        return self._request(
            "POST",
            f"/maker-events/{event_id}/weather",
            {"weather_flag": weather_flag},
            headers,
        )

    # ---------- BoothZone & Booth ----------
    def create_booth_zone(self, event_id, payload, headers):
        return self._request(
            "POST", f"/maker-events/{event_id}/booth-zones", payload, headers
        )

    def list_booth_zones(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/maker-events/{event_id}/booth-zones", headers=headers, params=params
        )

    def get_booth_zone(self, zone_id, headers):
        return self._request("GET", f"/booth-zones/{zone_id}", headers=headers)

    def list_booth_zones_filtered(self, headers, params=None):
        return self._request("GET", "/booth-zones", headers=headers, params=params)

    def create_booth(self, event_id, zone_id, payload, headers):
        return self._request(
            "POST",
            f"/maker-events/{event_id}/booth-zones/{zone_id}/booths",
            payload,
            headers,
        )

    def list_booths(self, event_id, zone_id, headers, params=None):
        return self._request(
            "GET",
            f"/maker-events/{event_id}/booth-zones/{zone_id}/booths",
            headers=headers,
            params=params,
        )

    def get_booth(self, booth_id, headers):
        return self._request("GET", f"/booths/{booth_id}", headers=headers)

    def list_booths_filtered(self, headers, params=None):
        return self._request("GET", "/booths", headers=headers, params=params)

    # ---------- VendorProfile ----------
    def create_vendor_profile(self, payload, headers):
        return self._request("POST", "/vendor-profiles", payload, headers)

    def get_vendor_profile(self, vendor_id, headers):
        return self._request("GET", f"/vendor-profiles/{vendor_id}", headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request(
            "POST", f"/vendor-profiles/{vendor_id}/suspend", {}, headers
        )

    def list_vendor_applications(self, vendor_id, headers, params=None):
        return self._request(
            "GET",
            f"/vendor-profiles/{vendor_id}/applications",
            headers=headers,
            params=params,
        )

    # ---------- VendorApplication ----------
    def create_application(self, event_id, payload, headers):
        return self._request(
            "POST", f"/maker-events/{event_id}/applications", payload, headers
        )

    def list_applications(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/maker-events/{event_id}/applications", headers=headers, params=params
        )

    def get_application(self, event_id, app_id, headers):
        return self._request(
            "GET", f"/maker-events/{event_id}/applications/{app_id}", headers=headers
        )

    def get_application_canonical(self, app_id, headers):
        return self._request("GET", f"/applications/{app_id}", headers=headers)

    def list_applications_filtered(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def submit_application(self, event_id, app_id, headers):
        return self._request(
            "POST", f"/maker-events/{event_id}/applications/{app_id}/submit", {}, headers
        )

    def withdraw_application(self, event_id, app_id, headers):
        return self._request(
            "POST",
            f"/maker-events/{event_id}/applications/{app_id}/withdraw",
            {},
            headers,
        )

    def decide_application(self, event_id, app_id, payload, headers):
        return self._request(
            "POST", f"/maker-events/{event_id}/applications/{app_id}/decide", payload, headers
        )

    def revoke_application(self, event_id, app_id, headers):
        return self._request(
            "POST", f"/maker-events/{event_id}/applications/{app_id}/revoke", {}, headers
        )

    # ---------- JuryScore ----------
    def create_jury_score(self, event_id, app_id, payload, headers):
        return self._request(
            "POST",
            f"/maker-events/{event_id}/applications/{app_id}/jury-scores",
            payload,
            headers,
        )

    def list_jury_scores(self, event_id, app_id, headers, params=None):
        return self._request(
            "GET",
            f"/maker-events/{event_id}/applications/{app_id}/jury-scores",
            headers=headers,
            params=params,
        )

    def list_jury_scores_filtered(self, headers, params=None):
        return self._request("GET", "/jury-scores", headers=headers, params=params)

    def get_jury_score(self, score_id, headers):
        return self._request("GET", f"/jury-scores/{score_id}", headers=headers)

    # ---------- BoothAssignment ----------
    def list_assignments(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/maker-events/{event_id}/assignments", headers=headers, params=params
        )

    def get_assignment(self, event_id, assignment_id, headers):
        return self._request(
            "GET", f"/maker-events/{event_id}/assignments/{assignment_id}", headers=headers
        )

    def get_assignment_canonical(self, assignment_id, headers):
        return self._request("GET", f"/booth-assignments/{assignment_id}", headers=headers)

    def list_assignments_filtered(self, headers, params=None):
        return self._request("GET", "/booth-assignments", headers=headers, params=params)

    def pay_assignment(self, event_id, assignment_id, headers):
        return self._request(
            "POST", f"/maker-events/{event_id}/assignments/{assignment_id}/pay", {}, headers
        )

    def forfeit_assignment(self, event_id, assignment_id, headers):
        return self._request(
            "POST",
            f"/maker-events/{event_id}/assignments/{assignment_id}/forfeit",
            {},
            headers,
        )

    def release_assignment(self, event_id, assignment_id, headers):
        return self._request(
            "POST",
            f"/maker-events/{event_id}/assignments/{assignment_id}/release",
            {},
            headers,
        )

    def confirm_assignment(self, event_id, assignment_id, headers):
        return self._request(
            "POST",
            f"/maker-events/{event_id}/assignments/{assignment_id}/confirm",
            {},
            headers,
        )

    # ---------- BoothFeeCharge ----------
    def list_charges(self, event_id, assignment_id, headers, params=None):
        return self._request(
            "GET",
            f"/maker-events/{event_id}/assignments/{assignment_id}/charges",
            headers=headers,
            params=params,
        )

    def list_charges_filtered(self, headers, params=None):
        return self._request("GET", "/booth-fee-charges", headers=headers, params=params)

    def get_charge(self, charge_id, headers):
        return self._request("GET", f"/booth-fee-charges/{charge_id}", headers=headers)

    # ---------- LoadInSlot ----------
    def create_load_slot(self, event_id, payload, headers):
        return self._request(
            "POST", f"/maker-events/{event_id}/load-in-slots", payload, headers
        )

    def list_load_slots(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/maker-events/{event_id}/load-in-slots", headers=headers, params=params
        )

    def get_load_slot(self, slot_id, headers):
        return self._request("GET", f"/load-in-slots/{slot_id}", headers=headers)

    def list_load_slots_filtered(self, headers, params=None):
        return self._request("GET", "/load-in-slots", headers=headers, params=params)

    # ---------- Ticket ----------
    def create_ticket(self, event_id, payload, headers):
        return self._request("POST", f"/maker-events/{event_id}/tickets", payload, headers)

    def list_tickets(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/maker-events/{event_id}/tickets", headers=headers, params=params
        )

    def get_ticket(self, event_id, ticket_id, headers):
        return self._request(
            "GET", f"/maker-events/{event_id}/tickets/{ticket_id}", headers=headers
        )

    def get_ticket_canonical(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets_filtered(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def redeem_ticket(self, event_id, ticket_id, headers):
        return self._request(
            "POST", f"/maker-events/{event_id}/tickets/{ticket_id}/redeem", {}, headers
        )

    def refund_ticket(self, event_id, ticket_id, payload, headers):
        return self._request(
            "POST", f"/maker-events/{event_id}/tickets/{ticket_id}/refund", payload, headers
        )

    # ---------- Attendance ----------
    def list_attendance(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/maker-events/{event_id}/attendance", headers=headers, params=params
        )

    def get_attendance(self, attendance_id, headers):
        return self._request("GET", f"/attendance/{attendance_id}", headers=headers)

    def list_attendance_filtered(self, headers, params=None):
        return self._request("GET", "/attendance", headers=headers, params=params)

    def exit_attendance(self, event_id, attendance_id, headers):
        return self._request(
            "POST",
            f"/maker-events/{event_id}/attendance/{attendance_id}/exit",
            {},
            headers,
        )

    # ---------- SalesLedgerEntry ----------
    def create_ledger_entry(self, event_id, payload, headers):
        return self._request(
            "POST", f"/maker-events/{event_id}/sales-ledger", payload, headers
        )

    def list_ledger_entries(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/maker-events/{event_id}/sales-ledger", headers=headers, params=params
        )

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/sales-ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries_filtered(self, headers, params=None):
        return self._request(
            "GET", "/sales-ledger-entries", headers=headers, params=params
        )

    # ---------- Settlement ----------
    def list_settlements(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/maker-events/{event_id}/settlements", headers=headers, params=params
        )

    def get_settlement(self, event_id, settlement_id, headers):
        return self._request(
            "GET", f"/maker-events/{event_id}/settlements/{settlement_id}", headers=headers
        )

    def get_settlement_canonical(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements_filtered(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def compute_settlement(self, event_id, settlement_id, headers):
        return self._request(
            "POST",
            f"/maker-events/{event_id}/settlements/{settlement_id}/compute",
            {},
            headers,
        )

    def approve_settlement(self, event_id, settlement_id, payload, headers):
        return self._request(
            "POST",
            f"/maker-events/{event_id}/settlements/{settlement_id}/approve",
            payload,
            headers,
        )

    def dispute_settlement(self, event_id, settlement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/maker-events/{event_id}/settlements/{settlement_id}/dispute",
            payload or {},
            headers,
        )

    def mark_paid_settlement(self, event_id, settlement_id, headers):
        return self._request(
            "POST",
            f"/maker-events/{event_id}/settlements/{settlement_id}/mark-paid",
            {},
            headers,
        )

    def cancel_settlement(self, event_id, settlement_id, headers):
        return self._request(
            "POST",
            f"/maker-events/{event_id}/settlements/{settlement_id}/cancel",
            {},
            headers,
        )


api_client = ApiClient()
