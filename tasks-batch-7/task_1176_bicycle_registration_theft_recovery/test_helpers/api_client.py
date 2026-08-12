"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/registry/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- Owners ----
    def register_owner(self, payload, headers):
        return self._request("POST", "/registry/owners/register", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/registry/owners/{owner_id}", headers=headers)

    def patch_owner(self, owner_id, payload, headers):
        return self._request("PATCH", f"/registry/owners/{owner_id}", payload, headers)

    # ---- Partner orgs ----
    def create_partner_org(self, payload, headers):
        return self._request("POST", "/registry/partner-orgs", payload, headers)

    def list_partner_orgs(self, headers, params=None):
        return self._request("GET", "/registry/partner-orgs", headers=headers, params=params)

    def get_partner_org(self, org_id, headers):
        return self._request("GET", f"/registry/partner-orgs/{org_id}", headers=headers)

    def activate_partner_org(self, org_id, headers):
        return self._request("POST", f"/registry/partner-orgs/{org_id}/activate", {}, headers)

    def suspend_partner_org(self, org_id, headers):
        return self._request("POST", f"/registry/partner-orgs/{org_id}/suspend", {}, headers)

    def revoke_partner_org(self, org_id, headers):
        return self._request("POST", f"/registry/partner-orgs/{org_id}/revoke", {}, headers)

    # ---- Bicycles ----
    def create_bicycle(self, payload, headers):
        return self._request("POST", "/registry/bicycles", payload, headers)

    def list_bicycles(self, headers, params=None):
        return self._request("GET", "/registry/bicycles", headers=headers, params=params)

    def get_bicycle(self, bicycle_id, headers):
        return self._request("GET", f"/registry/bicycles/{bicycle_id}", headers=headers)

    def patch_bicycle(self, bicycle_id, payload, headers):
        return self._request("PATCH", f"/registry/bicycles/{bicycle_id}", payload, headers)

    # ---- Ownership transfers ----
    def create_transfer(self, payload, headers):
        return self._request("POST", "/registry/transfers", payload, headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/registry/transfers", headers=headers, params=params)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/registry/transfers/{transfer_id}", headers=headers)

    def accept_transfer(self, transfer_id, headers):
        return self._request("POST", f"/registry/transfers/{transfer_id}/accept", {}, headers)

    def reject_transfer(self, transfer_id, headers):
        return self._request("POST", f"/registry/transfers/{transfer_id}/reject", {}, headers)

    def cancel_transfer(self, transfer_id, headers):
        return self._request("POST", f"/registry/transfers/{transfer_id}/cancel", {}, headers)

    # ---- Theft reports ----
    def create_theft_report(self, payload, headers):
        return self._request("POST", "/registry/theft-reports", payload, headers)

    def list_theft_reports(self, headers, params=None):
        return self._request("GET", "/registry/theft-reports", headers=headers, params=params)

    def get_theft_report(self, report_id, headers):
        return self._request("GET", f"/registry/theft-reports/{report_id}", headers=headers)

    def request_info_theft_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/registry/theft-reports/{report_id}/request-info", payload, headers
        )

    def respond_theft_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/registry/theft-reports/{report_id}/respond", payload, headers
        )

    def flag_theft_report(self, report_id, headers):
        return self._request("POST", f"/registry/theft-reports/{report_id}/flag", {}, headers)

    def reject_theft_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/registry/theft-reports/{report_id}/reject", payload, headers
        )

    def withdraw_theft_report(self, report_id, headers):
        return self._request(
            "POST", f"/registry/theft-reports/{report_id}/withdraw", {}, headers
        )

    # ---- Recovery intakes ----
    def create_recovery_intake(self, payload, headers):
        return self._request("POST", "/registry/recovery-intakes", payload, headers)

    def list_recovery_intakes(self, headers, params=None):
        return self._request("GET", "/registry/recovery-intakes", headers=headers, params=params)

    def get_recovery_intake(self, intake_id, headers):
        return self._request(
            "GET", f"/registry/recovery-intakes/{intake_id}", headers=headers
        )

    def scan_recovery_intake(self, intake_id, headers):
        return self._request(
            "POST", f"/registry/recovery-intakes/{intake_id}/scan", {}, headers
        )

    def mark_unclaimed(self, intake_id, headers):
        return self._request(
            "POST", f"/registry/recovery-intakes/{intake_id}/mark-unclaimed", {}, headers
        )

    def complete_return(self, intake_id, headers):
        return self._request(
            "POST", f"/registry/recovery-intakes/{intake_id}/complete-return", {}, headers
        )

    # ---- Match candidates ----
    def list_matches(self, headers, params=None):
        return self._request("GET", "/registry/matches", headers=headers, params=params)

    def get_match(self, match_id, headers):
        return self._request("GET", f"/registry/matches/{match_id}", headers=headers)

    def dismiss_match(self, match_id, headers):
        return self._request("POST", f"/registry/matches/{match_id}/dismiss", {}, headers)

    # ---- Owner claims ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/registry/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/registry/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/registry/claims/{claim_id}", headers=headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/registry/claims/{claim_id}/approve", {}, headers)

    def reject_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/registry/claims/{claim_id}/reject", payload, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/registry/claims/{claim_id}/withdraw", {}, headers)

    # ---- Auctions & bids ----
    def create_auction(self, payload, headers):
        return self._request("POST", "/registry/auctions", payload, headers)

    def list_auctions(self, headers, params=None):
        return self._request("GET", "/registry/auctions", headers=headers, params=params)

    def get_auction(self, auction_id, headers):
        return self._request("GET", f"/registry/auctions/{auction_id}", headers=headers)

    def open_auction(self, auction_id, headers):
        return self._request("POST", f"/registry/auctions/{auction_id}/open", {}, headers)

    def close_auction(self, auction_id, headers):
        return self._request("POST", f"/registry/auctions/{auction_id}/close", {}, headers)

    def settle_auction(self, auction_id, headers):
        return self._request("POST", f"/registry/auctions/{auction_id}/settle", {}, headers)

    def void_settlement(self, auction_id, headers):
        return self._request(
            "POST", f"/registry/auctions/{auction_id}/void-settlement", {}, headers
        )

    def cancel_auction(self, auction_id, headers):
        return self._request("POST", f"/registry/auctions/{auction_id}/cancel", {}, headers)

    def place_bid(self, auction_id, payload, headers):
        return self._request("POST", f"/registry/auctions/{auction_id}/bids", payload, headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/registry/bids", headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/registry/bids/{bid_id}", headers=headers)

    def retract_bid(self, bid_id, headers):
        return self._request("POST", f"/registry/bids/{bid_id}/retract", {}, headers)

    # ---- Registry events (campus programs) ----
    def create_event(self, payload, headers):
        return self._request("POST", "/registry/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/registry/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/registry/events/{event_id}", headers=headers)

    def publish_event(self, event_id, headers):
        return self._request("POST", f"/registry/events/{event_id}/publish", {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/registry/events/{event_id}/complete", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/registry/events/{event_id}/cancel", {}, headers)

    def book_event_seat(self, event_id, headers):
        return self._request("POST", f"/registry/events/{event_id}/registrations", {}, headers)

    def list_event_registrations(self, headers, params=None):
        return self._request(
            "GET", "/registry/event-registrations", headers=headers, params=params
        )

    def get_event_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/registry/event-registrations/{registration_id}", headers=headers
        )

    def cancel_event_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registry/event-registrations/{registration_id}/cancel", {}, headers
        )

    # ---- Duplicate flags ----
    def create_duplicate_flag(self, payload, headers):
        return self._request("POST", "/registry/duplicate-flags", payload, headers)

    def list_duplicate_flags(self, headers, params=None):
        return self._request("GET", "/registry/duplicate-flags", headers=headers, params=params)

    def get_duplicate_flag(self, flag_id, headers):
        return self._request("GET", f"/registry/duplicate-flags/{flag_id}", headers=headers)

    def confirm_duplicate_flag(self, flag_id, payload, headers):
        return self._request(
            "POST", f"/registry/duplicate-flags/{flag_id}/confirm", payload, headers
        )

    def dismiss_duplicate_flag(self, flag_id, headers):
        return self._request(
            "POST", f"/registry/duplicate-flags/{flag_id}/dismiss", {}, headers
        )

    # ---- Ledger & notifications ----
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/registry/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/registry/ledger-entries/{entry_id}", headers=headers)

    def list_notifications(self, headers, params=None):
        return self._request("GET", "/registry/notifications", headers=headers, params=params)

    def get_notification(self, notification_id, headers):
        return self._request(
            "GET", f"/registry/notifications/{notification_id}", headers=headers
        )

    def mark_notification_read(self, notification_id, headers):
        return self._request(
            "POST", f"/registry/notifications/{notification_id}/mark-read", {}, headers
        )


api_client = ApiClient()
