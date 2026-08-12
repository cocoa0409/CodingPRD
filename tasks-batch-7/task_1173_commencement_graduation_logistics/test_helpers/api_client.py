"""API client: one method per endpoint defined in the PRD (§4 endpoint index)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Ceremony lifecycle ---
    def create_ceremony(self, payload, headers):
        return self._request("POST", "/api/ceremonies", payload, headers)

    def get_ceremony(self, ceremony_id, headers):
        return self._request("GET", f"/api/ceremonies/{ceremony_id}", headers=headers)

    def patch_ceremony(self, ceremony_id, payload, headers):
        return self._request("PATCH", f"/api/ceremonies/{ceremony_id}", payload, headers)

    def open_audit(self, ceremony_id, headers):
        return self._request("POST", f"/api/ceremonies/{ceremony_id}/open-audit", {}, headers)

    def lock_audit(self, ceremony_id, headers):
        return self._request("POST", f"/api/ceremonies/{ceremony_id}/lock-audit", {}, headers)

    def reopen_audit(self, ceremony_id, headers):
        return self._request("POST", f"/api/ceremonies/{ceremony_id}/reopen-audit", {}, headers)

    def mark_ready(self, ceremony_id, headers):
        return self._request("POST", f"/api/ceremonies/{ceremony_id}/mark-ready", {}, headers)

    def activate_rain_plan(self, ceremony_id, headers):
        return self._request("POST", f"/api/ceremonies/{ceremony_id}/activate-rain-plan", {}, headers)

    def deactivate_rain_plan(self, ceremony_id, headers):
        return self._request("POST", f"/api/ceremonies/{ceremony_id}/deactivate-rain-plan", {}, headers)

    def commence_ceremony(self, ceremony_id, headers):
        return self._request("POST", f"/api/ceremonies/{ceremony_id}/commence", {}, headers)

    def complete_ceremony(self, ceremony_id, headers):
        return self._request("POST", f"/api/ceremonies/{ceremony_id}/complete", {}, headers)

    def run_ticket_waterfall(self, ceremony_id, headers):
        return self._request("POST", f"/api/ceremonies/{ceremony_id}/run-ticket-waterfall", {}, headers)

    def run_seating(self, ceremony_id, headers):
        return self._request("POST", f"/api/ceremonies/{ceremony_id}/run-seating", {}, headers)

    # --- Ceremony-scoped sub-resource lists ---
    def list_ceremony_graduates(self, ceremony_id, headers, params=None):
        return self._request("GET", f"/api/ceremonies/{ceremony_id}/graduates", headers=headers, params=params)

    def list_ceremony_ticket_allocations(self, ceremony_id, headers, params=None):
        return self._request("GET", f"/api/ceremonies/{ceremony_id}/ticket-allocations", headers=headers, params=params)

    def list_ceremony_seat_assignments(self, ceremony_id, headers, params=None):
        return self._request("GET", f"/api/ceremonies/{ceremony_id}/seat-assignments", headers=headers, params=params)

    def list_ceremony_accommodation_requests(self, ceremony_id, headers, params=None):
        return self._request("GET", f"/api/ceremonies/{ceremony_id}/accommodation-requests", headers=headers, params=params)

    def list_ceremony_vendor_contracts(self, ceremony_id, headers, params=None):
        return self._request("GET", f"/api/ceremonies/{ceremony_id}/vendor-contracts", headers=headers, params=params)

    def list_ceremony_print_batches(self, ceremony_id, headers, params=None):
        return self._request("GET", f"/api/ceremonies/{ceremony_id}/print-batches", headers=headers, params=params)

    def list_ceremony_rehearsal_sessions(self, ceremony_id, headers, params=None):
        return self._request("GET", f"/api/ceremonies/{ceremony_id}/rehearsal-sessions", headers=headers, params=params)

    # --- Venue ---
    def create_venue(self, payload, headers):
        return self._request("POST", "/api/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/api/venues/{venue_id}", headers=headers)

    def list_venue_ceremonies(self, venue_id, headers, params=None):
        return self._request("GET", f"/api/venues/{venue_id}/ceremonies", headers=headers, params=params)

    def list_venue_rehearsal_sessions(self, venue_id, headers, params=None):
        return self._request("GET", f"/api/venues/{venue_id}/rehearsal-sessions", headers=headers, params=params)

    # --- Graduate ---
    def create_graduate(self, payload, headers):
        return self._request("POST", "/api/graduates", payload, headers)

    def get_graduate(self, graduate_id, headers):
        return self._request("GET", f"/api/graduates/{graduate_id}", headers=headers)

    def withdraw_graduate(self, graduate_id, headers):
        return self._request("POST", f"/api/graduates/{graduate_id}/withdraw", {}, headers)

    def confirm_graduate(self, graduate_id, headers):
        return self._request("POST", f"/api/graduates/{graduate_id}/confirm", {}, headers)

    def post_grade_revision(self, graduate_id, payload, headers):
        return self._request("POST", f"/api/graduates/{graduate_id}/grade-revision", payload, headers)

    def list_graduate_audits(self, graduate_id, headers, params=None):
        return self._request("GET", f"/api/graduates/{graduate_id}/audits", headers=headers, params=params)

    def list_graduate_ticket_allocations(self, graduate_id, headers, params=None):
        return self._request("GET", f"/api/graduates/{graduate_id}/ticket-allocations", headers=headers, params=params)

    def list_graduate_regalia_orders(self, graduate_id, headers, params=None):
        return self._request("GET", f"/api/graduates/{graduate_id}/regalia-orders", headers=headers, params=params)

    def list_graduate_seat_assignments(self, graduate_id, headers, params=None):
        return self._request("GET", f"/api/graduates/{graduate_id}/seat-assignments", headers=headers, params=params)

    def list_graduate_diplomas(self, graduate_id, headers, params=None):
        return self._request("GET", f"/api/graduates/{graduate_id}/diplomas", headers=headers, params=params)

    def list_graduate_accommodation_requests(self, graduate_id, headers, params=None):
        return self._request("GET", f"/api/graduates/{graduate_id}/accommodation-requests", headers=headers, params=params)

    def list_graduate_rehearsal_attendances(self, graduate_id, headers, params=None):
        return self._request("GET", f"/api/graduates/{graduate_id}/rehearsal-attendances", headers=headers, params=params)

    def list_graduate_reader_cards(self, graduate_id, headers, params=None):
        return self._request("GET", f"/api/graduates/{graduate_id}/reader-cards", headers=headers, params=params)

    # --- Eligibility audit & appeal ---
    def create_audit(self, graduate_id, payload, headers):
        return self._request("POST", f"/api/graduates/{graduate_id}/audits", payload, headers)

    def appeal_audit(self, audit_id, headers):
        return self._request("POST", f"/api/eligibility-audits/{audit_id}/appeal", {}, headers)

    def decide_appeal(self, audit_id, payload, headers):
        return self._request("POST", f"/api/eligibility-audits/{audit_id}/appeal-decision", payload, headers)

    # --- Ticket allocation ---
    def request_tickets(self, allocation_id, payload, headers):
        return self._request("POST", f"/api/ticket-allocations/{allocation_id}/request", payload, headers)

    def release_tickets(self, allocation_id, headers):
        return self._request("POST", f"/api/ticket-allocations/{allocation_id}/release", {}, headers)

    # --- Regalia ---
    def create_regalia_order(self, graduate_id, payload, headers):
        return self._request("POST", f"/api/graduates/{graduate_id}/regalia-orders", payload, headers)

    def get_regalia_order(self, order_id, headers):
        return self._request("GET", f"/api/regalia-orders/{order_id}", headers=headers)

    def pay_regalia_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/regalia-orders/{order_id}/pay", payload, headers)

    def fulfill_regalia_order(self, order_id, headers):
        return self._request("POST", f"/api/regalia-orders/{order_id}/fulfill", {}, headers)

    def request_exchange(self, order_id, payload, headers):
        return self._request("POST", f"/api/regalia-orders/{order_id}/request-exchange", payload, headers)

    def cancel_regalia_order(self, order_id, headers):
        return self._request("POST", f"/api/regalia-orders/{order_id}/cancel", {}, headers)

    # --- Seating ---
    def create_seat_assignment(self, payload, headers):
        return self._request("POST", "/api/seat-assignments", payload, headers)

    def get_seat_assignment(self, seat_id, headers):
        return self._request("GET", f"/api/seat-assignments/{seat_id}", headers=headers)

    def evict_seat(self, seat_id, headers):
        return self._request("POST", f"/api/seat-assignments/{seat_id}/evict", {}, headers)

    # --- Reader cards ---
    def create_reader_card(self, graduate_id, payload, headers):
        return self._request("POST", f"/api/graduates/{graduate_id}/reader-card", payload, headers)

    def update_reader_card(self, card_id, payload, headers):
        return self._request("PATCH", f"/api/reader-cards/{card_id}", payload, headers)

    def approve_reader_card(self, card_id, headers):
        return self._request("POST", f"/api/reader-cards/{card_id}/approve", {}, headers)

    # --- Print batches & diplomas ---
    def create_print_batch(self, ceremony_id, payload, headers):
        return self._request("POST", f"/api/ceremonies/{ceremony_id}/print-batches", payload, headers)

    def get_print_batch(self, batch_id, headers):
        return self._request("GET", f"/api/print-batches/{batch_id}", headers=headers)

    def queue_diploma(self, batch_id, payload, headers):
        return self._request("POST", f"/api/print-batches/{batch_id}/diplomas", payload, headers)

    def list_batch_diplomas(self, batch_id, headers, params=None):
        return self._request("GET", f"/api/print-batches/{batch_id}/diplomas", headers=headers, params=params)

    def release_batch(self, batch_id, headers):
        return self._request("POST", f"/api/print-batches/{batch_id}/release", {}, headers)

    def mark_batch_printed(self, batch_id, headers):
        return self._request("POST", f"/api/print-batches/{batch_id}/mark-printed", {}, headers)

    def get_diploma(self, diploma_id, headers):
        return self._request("GET", f"/api/diplomas/{diploma_id}", headers=headers)

    def issue_diploma(self, diploma_id, headers):
        return self._request("POST", f"/api/diplomas/{diploma_id}/issue", {}, headers)

    def request_correction(self, diploma_id, payload, headers):
        return self._request("POST", f"/api/diplomas/{diploma_id}/corrections", payload, headers)

    def decide_correction(self, diploma_id, payload, headers):
        return self._request("POST", f"/api/diplomas/{diploma_id}/correction-decision", payload, headers)

    # --- Rehearsal ---
    def create_rehearsal_session(self, ceremony_id, payload, headers):
        return self._request("POST", f"/api/ceremonies/{ceremony_id}/rehearsal-sessions", payload, headers)

    def get_rehearsal_session(self, session_id, headers):
        return self._request("GET", f"/api/rehearsal-sessions/{session_id}", headers=headers)

    def register_for_session(self, session_id, headers):
        return self._request("POST", f"/api/rehearsal-sessions/{session_id}/register", {}, headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/api/rehearsal-sessions/{session_id}/complete", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/api/rehearsal-sessions/{session_id}/cancel", {}, headers)

    def list_session_attendances(self, session_id, headers, params=None):
        return self._request("GET", f"/api/rehearsal-sessions/{session_id}/attendances", headers=headers, params=params)

    def check_in_attendance(self, attendance_id, headers):
        return self._request("POST", f"/api/rehearsal-attendances/{attendance_id}/check-in", {}, headers)

    def waive_attendance(self, attendance_id, headers):
        return self._request("POST", f"/api/rehearsal-attendances/{attendance_id}/waive", {}, headers)

    # --- Accessibility accommodations ---
    def create_accommodation_request(self, graduate_id, payload, headers):
        return self._request("POST", f"/api/graduates/{graduate_id}/accommodation-requests", payload, headers)

    def get_accommodation_request(self, request_id, headers):
        return self._request("GET", f"/api/accommodation-requests/{request_id}", headers=headers)

    def approve_accommodation(self, request_id, headers):
        return self._request("POST", f"/api/accommodation-requests/{request_id}/approve", {}, headers)

    def deny_accommodation(self, request_id, payload, headers):
        return self._request("POST", f"/api/accommodation-requests/{request_id}/deny", payload, headers)

    def fulfill_accommodation(self, request_id, headers):
        return self._request("POST", f"/api/accommodation-requests/{request_id}/fulfill", {}, headers)

    # --- Vendors ---
    def create_vendor_contract(self, ceremony_id, payload, headers):
        return self._request("POST", f"/api/ceremonies/{ceremony_id}/vendor-contracts", payload, headers)

    def get_vendor_contract(self, contract_id, headers):
        return self._request("GET", f"/api/vendor-contracts/{contract_id}", headers=headers)

    def activate_vendor_contract(self, contract_id, headers):
        return self._request("POST", f"/api/vendor-contracts/{contract_id}/activate", {}, headers)

    def submit_deliverable(self, contract_id, payload, headers):
        return self._request("POST", f"/api/vendor-contracts/{contract_id}/submit-deliverable", payload, headers)

    def settle_vendor_contract(self, contract_id, headers):
        return self._request("POST", f"/api/vendor-contracts/{contract_id}/settle", {}, headers)

    def cancel_vendor_contract(self, contract_id, headers):
        return self._request("POST", f"/api/vendor-contracts/{contract_id}/cancel", {}, headers)


api_client = ApiClient()
