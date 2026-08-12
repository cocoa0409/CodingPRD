"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- securities ---
    def create_security(self, payload, headers):
        return self._request("POST", "/api/securities", payload, headers)

    def list_securities(self, headers, params=None):
        return self._request("GET", "/api/securities", headers=headers, params=params)

    def get_security(self, security_id, headers):
        return self._request("GET", f"/api/securities/{security_id}", headers=headers)

    def update_security(self, security_id, payload, headers):
        return self._request("PUT", f"/api/securities/{security_id}", payload, headers)

    # --- accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/api/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/api/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}", headers=headers)

    def update_account(self, account_id, payload, headers):
        return self._request("PUT", f"/api/accounts/{account_id}", payload, headers)

    # --- position lots ---
    def create_position_lot(self, payload, headers):
        return self._request("POST", "/api/position-lots", payload, headers)

    def list_position_lots(self, headers, params=None):
        return self._request("GET", "/api/position-lots", headers=headers, params=params)

    def get_position_lot(self, lot_id, headers):
        return self._request("GET", f"/api/position-lots/{lot_id}", headers=headers)

    # --- event sources ---
    def create_event_source(self, payload, headers):
        return self._request("POST", "/api/event-sources", payload, headers)

    def list_event_sources(self, headers, params=None):
        return self._request("GET", "/api/event-sources", headers=headers, params=params)

    def get_event_source(self, source_id, headers):
        return self._request("GET", f"/api/event-sources/{source_id}", headers=headers)

    # --- source notifications ---
    def create_source_notification(self, payload, headers):
        return self._request("POST", "/api/source-notifications", payload, headers)

    def list_source_notifications(self, headers, params=None):
        return self._request("GET", "/api/source-notifications", headers=headers, params=params)

    def get_source_notification(self, notification_id, headers):
        return self._request("GET", f"/api/source-notifications/{notification_id}", headers=headers)

    def reject_source_notification(self, notification_id, headers):
        return self._request("POST", f"/api/source-notifications/{notification_id}/reject", {}, headers)

    # --- corporate action events ---
    def create_event(self, payload, headers):
        return self._request("POST", "/api/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/api/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/api/events/{event_id}", headers=headers)

    def confirm_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/confirm", {}, headers)

    def amend_event(self, event_id, payload, headers):
        return self._request("POST", f"/api/events/{event_id}/amendments", payload, headers)

    def list_amendments(self, event_id, headers, params=None):
        return self._request("GET", f"/api/events/{event_id}/amendments", headers=headers, params=params)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/cancel", {}, headers)

    def capture_record_position(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/capture-record-position", {}, headers)

    def book_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/book", {}, headers)

    def list_event_bookings(self, event_id, headers, params=None):
        return self._request("GET", f"/api/events/{event_id}/bookings", headers=headers, params=params)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/complete", {}, headers)

    # --- bookings / booking lines ---
    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/api/bookings/{booking_id}", headers=headers)

    def reverse_booking(self, booking_id, headers):
        return self._request("POST", f"/api/bookings/{booking_id}/reverse", {}, headers)

    def list_booking_lines(self, headers, params=None):
        return self._request("GET", "/api/booking-lines", headers=headers, params=params)

    def get_booking_line(self, line_id, headers):
        return self._request("GET", f"/api/booking-lines/{line_id}", headers=headers)

    # --- elections ---
    def submit_election(self, event_id, payload, headers):
        return self._request("POST", f"/api/events/{event_id}/elections", payload, headers)

    def withdraw_election(self, election_id, headers):
        return self._request("POST", f"/api/elections/{election_id}/withdraw", {}, headers)

    def resubmit_election(self, election_id, headers):
        return self._request("POST", f"/api/elections/{election_id}/resubmit", {}, headers)

    def list_elections(self, headers, params=None):
        return self._request("GET", "/api/elections", headers=headers, params=params)

    def get_election(self, election_id, headers):
        return self._request("GET", f"/api/elections/{election_id}", headers=headers)

    # --- claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/api/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/api/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}", headers=headers)

    def decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/decide", payload, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/pay", {}, headers)

    # --- custodian statements / recon breaks ---
    def create_custodian_statement(self, payload, headers):
        return self._request("POST", "/api/custodian-statements", payload, headers)

    def list_custodian_statements(self, headers, params=None):
        return self._request("GET", "/api/custodian-statements", headers=headers, params=params)

    def get_custodian_statement(self, statement_id, headers):
        return self._request("GET", f"/api/custodian-statements/{statement_id}", headers=headers)

    def list_recon_breaks(self, headers, params=None):
        return self._request("GET", "/api/recon-breaks", headers=headers, params=params)

    def get_recon_break(self, break_id, headers):
        return self._request("GET", f"/api/recon-breaks/{break_id}", headers=headers)

    def resolve_recon_break(self, break_id, payload, headers):
        return self._request("POST", f"/api/recon-breaks/{break_id}/resolve", payload, headers)

    # --- entitlements (read-only) ---
    def list_entitlements(self, headers, params=None):
        return self._request("GET", "/api/entitlements", headers=headers, params=params)

    def get_entitlement(self, entitlement_id, headers):
        return self._request("GET", f"/api/entitlements/{entitlement_id}", headers=headers)


api_client = ApiClient()
