"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The runner restarts the server on the SAME port before every test
        # (per-test-server isolation). A keep-alive connection pooled from the
        # previous test's server would be reused against the freshly booted
        # server and intermittently fails with "Connection reset by peer"
        # when the old process was killed mid-shutdown. Forcing
        # Connection: close gives every request a fresh TCP connection.
        self.session.headers["Connection"] = "close"

    # ------------------------------------------------------------------
    # Logical clock and ops sweep
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_retention_sweep(self, headers):
        return self._request("POST", "/_sweeps/retention", {}, headers)

    # ------------------------------------------------------------------
    # Programs
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def deactivate_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/deactivate", {}, headers)

    # ------------------------------------------------------------------
    # Retention policies
    # ------------------------------------------------------------------
    def create_retention_policy(self, payload, headers):
        return self._request("POST", "/retention-policies", payload, headers)

    def list_retention_policies(self, headers, params=None):
        return self._request("GET", "/retention-policies", headers=headers, params=params)

    def get_retention_policy(self, policy_id, headers):
        return self._request("GET", f"/retention-policies/{policy_id}", headers=headers)

    # ------------------------------------------------------------------
    # Storage locations
    # ------------------------------------------------------------------
    def create_storage_location(self, payload, headers):
        return self._request("POST", "/storage-locations", payload, headers)

    def list_storage_locations(self, headers, params=None):
        return self._request("GET", "/storage-locations", headers=headers, params=params)

    def get_storage_location(self, location_id, headers):
        return self._request("GET", f"/storage-locations/{location_id}", headers=headers)

    def deactivate_storage_location(self, location_id, headers):
        return self._request("POST", f"/storage-locations/{location_id}/deactivate", {}, headers)

    # ------------------------------------------------------------------
    # Venues
    # ------------------------------------------------------------------
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/venues", headers=headers, params=params)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    # ------------------------------------------------------------------
    # Claimants
    # ------------------------------------------------------------------
    def create_claimant(self, payload, headers):
        return self._request("POST", "/claimants", payload, headers)

    def get_claimant(self, claimant_id, headers):
        return self._request("GET", f"/claimants/{claimant_id}", headers=headers)

    def verify_claimant_id(self, claimant_id, headers):
        return self._request("POST", f"/claimants/{claimant_id}/verify-id", {}, headers)

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------
    def create_item(self, payload, headers):
        return self._request("POST", "/items", payload, headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/items/{item_id}", headers=headers)

    def list_public_items(self, headers, params=None):
        return self._request("GET", "/public/items", headers=headers, params=params)

    def publish_item(self, item_id, headers):
        return self._request("POST", f"/items/{item_id}/publish", {}, headers)

    def unpublish_item(self, item_id, headers):
        return self._request("POST", f"/items/{item_id}/unpublish", {}, headers)

    def move_item(self, item_id, storage_location_id, headers):
        return self._request("POST", f"/items/{item_id}/move",
                             {"storage_location_id": storage_location_id}, headers)

    def dispose_item(self, item_id, method, headers):
        return self._request("POST", f"/items/{item_id}/dispose",
                             {"method": method}, headers)

    def release_item(self, item_id, payload, headers):
        return self._request("POST", f"/items/{item_id}/release", payload, headers)

    def refer_item_to_law_enforcement(self, item_id, payload, headers):
        return self._request("POST", f"/items/{item_id}/refer-to-law-enforcement",
                             payload, headers)

    # ------------------------------------------------------------------
    # Referral cases
    # ------------------------------------------------------------------
    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def confirm_pickup(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/confirm-pickup", {}, headers)

    def return_to_custody(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/return-to-custody", {}, headers)

    def convert_to_evidence(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/convert-to-evidence", {}, headers)

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def start_claim_review(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/start-review", {}, headers)

    def request_claim_info(self, claim_id, info_request_text, headers):
        return self._request("POST", f"/claims/{claim_id}/request-info",
                             {"info_request_text": info_request_text}, headers)

    def resubmit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/resubmit", payload, headers)

    def approve_claim(self, claim_id, headers, decision_reason=None):
        payload = {} if decision_reason is None else {"decision_reason": decision_reason}
        return self._request("POST", f"/claims/{claim_id}/approve", payload, headers)

    def reject_claim(self, claim_id, decision_reason, headers):
        return self._request("POST", f"/claims/{claim_id}/reject",
                             {"decision_reason": decision_reason}, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Inquiries
    # ------------------------------------------------------------------
    def create_inquiry(self, payload, headers):
        return self._request("POST", "/inquiries", payload, headers)

    def list_inquiries(self, headers, params=None):
        return self._request("GET", "/inquiries", headers=headers, params=params)

    def get_inquiry(self, inquiry_id, headers):
        return self._request("GET", f"/inquiries/{inquiry_id}", headers=headers)

    def answer_inquiry(self, inquiry_id, answer_text, headers):
        return self._request("POST", f"/inquiries/{inquiry_id}/answer",
                             {"answer_text": answer_text}, headers)

    def close_inquiry(self, inquiry_id, headers):
        return self._request("POST", f"/inquiries/{inquiry_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Auction events
    # ------------------------------------------------------------------
    def create_auction_event(self, payload, headers):
        return self._request("POST", "/auction-events", payload, headers)

    def list_auction_events(self, headers, params=None):
        return self._request("GET", "/auction-events", headers=headers, params=params)

    def get_auction_event(self, event_id, headers):
        return self._request("GET", f"/auction-events/{event_id}", headers=headers)

    def cancel_auction_event(self, event_id, headers):
        return self._request("POST", f"/auction-events/{event_id}/cancel", {}, headers)

    def settle_auction_event(self, event_id, headers):
        return self._request("POST", f"/auction-events/{event_id}/settle", {}, headers)

    # ------------------------------------------------------------------
    # Auction lots and membership rows
    # ------------------------------------------------------------------
    def create_auction_lot(self, payload, headers):
        return self._request("POST", "/auction-lots", payload, headers)

    def list_auction_lots(self, headers, params=None):
        return self._request("GET", "/auction-lots", headers=headers, params=params)

    def get_auction_lot(self, lot_id, headers):
        return self._request("GET", f"/auction-lots/{lot_id}", headers=headers)

    def add_lot_item(self, lot_id, item_id, expected_lot_version, headers):
        return self._request("POST", f"/auction-lots/{lot_id}/items",
                             {"item_id": item_id,
                              "expected_lot_version": expected_lot_version}, headers)

    def remove_lot_item(self, lot_id, item_id, headers):
        return self._request("DELETE", f"/auction-lots/{lot_id}/items/{item_id}",
                             headers=headers)

    def list_lot_items(self, lot_id, headers, params=None):
        return self._request("GET", f"/auction-lots/{lot_id}/items",
                             headers=headers, params=params)

    def list_all_lot_items(self, headers, params=None):
        return self._request("GET", "/lot-items", headers=headers, params=params)

    def get_lot_item(self, lot_item_id, headers):
        return self._request("GET", f"/lot-items/{lot_item_id}", headers=headers)

    def publish_lot(self, lot_id, headers):
        return self._request("POST", f"/auction-lots/{lot_id}/publish", {}, headers)

    def finalize_lot_sale(self, lot_id, hammer_price_cents, headers):
        return self._request("POST", f"/auction-lots/{lot_id}/finalize-sale",
                             {"hammer_price_cents": hammer_price_cents}, headers)

    def close_lot_unsold(self, lot_id, headers):
        return self._request("POST", f"/auction-lots/{lot_id}/close-unsold", {}, headers)

    # ------------------------------------------------------------------
    # Release records
    # ------------------------------------------------------------------
    def list_release_records(self, headers, params=None):
        return self._request("GET", "/release-records", headers=headers, params=params)

    def get_release_record(self, record_id, headers):
        return self._request("GET", f"/release-records/{record_id}", headers=headers)


api_client = ApiClient()
