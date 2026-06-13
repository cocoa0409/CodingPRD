"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Participant ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    # --- Event ---
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def open_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/open", {}, headers)

    def close_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/close", {}, headers)

    def post_results_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/post-results", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/cancel", {}, headers)

    # --- Distance ---
    def create_distance(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/distances", payload, headers)

    def list_event_distances(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/distances",
                             headers=headers, params=params)

    def get_distance(self, distance_id, headers):
        return self._request("GET", f"/distances/{distance_id}", headers=headers)

    def list_distances(self, headers, params=None):
        return self._request("GET", "/distances", headers=headers, params=params)

    # --- Wave ---
    def create_wave(self, distance_id, payload, headers):
        return self._request("POST", f"/distances/{distance_id}/waves", payload, headers)

    def list_distance_waves(self, distance_id, headers, params=None):
        return self._request("GET", f"/distances/{distance_id}/waves",
                             headers=headers, params=params)

    def get_wave(self, wave_id, headers):
        return self._request("GET", f"/waves/{wave_id}", headers=headers)

    def list_waves(self, headers, params=None):
        return self._request("GET", "/waves", headers=headers, params=params)

    # --- PricingTier ---
    def create_pricing_tier(self, distance_id, payload, headers):
        return self._request("POST", f"/distances/{distance_id}/pricing-tiers",
                             payload, headers)

    def get_pricing_tier(self, pricing_tier_id, headers):
        return self._request("GET", f"/pricing-tiers/{pricing_tier_id}", headers=headers)

    def list_pricing_tiers(self, headers, params=None):
        return self._request("GET", "/pricing-tiers", headers=headers, params=params)

    # --- Registration ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def confirm_payment(self, registration_id, payload, headers):
        return self._request("POST", f"/registrations/{registration_id}/confirm-payment",
                             payload, headers)

    def cancel_registration(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/cancel", {}, headers)

    def assign_bib(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/assign-bib",
                             {}, headers)

    def defer_registration(self, registration_id, payload, headers):
        return self._request("POST", f"/registrations/{registration_id}/defer",
                             payload, headers)

    def finish_registration(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/finish", {}, headers)

    def list_registration_bib_assignments(self, registration_id, headers, params=None):
        return self._request("GET", f"/registrations/{registration_id}/bib-assignments",
                             headers=headers, params=params)

    def list_registration_pledges(self, registration_id, headers, params=None):
        return self._request("GET", f"/registrations/{registration_id}/fundraising-pledges",
                             headers=headers, params=params)

    def list_registration_packet_pickups(self, registration_id, headers, params=None):
        return self._request("GET", f"/registrations/{registration_id}/packet-pickups",
                             headers=headers, params=params)

    def list_registration_results(self, registration_id, headers, params=None):
        return self._request("GET", f"/registrations/{registration_id}/results",
                             headers=headers, params=params)

    def list_registration_transfer_requests(self, registration_id, headers, params=None):
        return self._request("GET", f"/registrations/{registration_id}/transfer-requests",
                             headers=headers, params=params)

    # --- WaitlistEntry ---
    def get_waitlist_entry(self, waitlist_entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{waitlist_entry_id}", headers=headers)

    def list_distance_waitlist_entries(self, distance_id, headers, params=None):
        return self._request("GET", f"/distances/{distance_id}/waitlist-entries",
                             headers=headers, params=params)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)

    def claim_waitlist_entry(self, waitlist_entry_id, payload, headers):
        return self._request("POST", f"/waitlist-entries/{waitlist_entry_id}/claim",
                             payload, headers)

    def decline_waitlist_entry(self, waitlist_entry_id, headers):
        return self._request("POST", f"/waitlist-entries/{waitlist_entry_id}/decline",
                             {}, headers)

    def withdraw_waitlist_entry(self, waitlist_entry_id, headers):
        return self._request("POST", f"/waitlist-entries/{waitlist_entry_id}/withdraw",
                             {}, headers)

    def expire_check_waitlist_entry(self, waitlist_entry_id, headers):
        return self._request("POST", f"/waitlist-entries/{waitlist_entry_id}/expire-check",
                             {}, headers)

    # --- FundraisingPledge ---
    def create_pledge(self, payload, headers):
        return self._request("POST", "/pledges", payload, headers)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"/pledges/{pledge_id}", headers=headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/pledges", headers=headers, params=params)

    def settle_pledge(self, pledge_id, headers):
        return self._request("POST", f"/pledges/{pledge_id}/settle", {}, headers)

    def void_pledge(self, pledge_id, headers):
        return self._request("POST", f"/pledges/{pledge_id}/void", {}, headers)

    # --- TransferRequest ---
    def create_transfer_request(self, payload, headers):
        return self._request("POST", "/transfer-requests", payload, headers)

    def get_transfer_request(self, transfer_request_id, headers):
        return self._request("GET", f"/transfer-requests/{transfer_request_id}", headers=headers)

    def list_transfer_requests(self, headers, params=None):
        return self._request("GET", "/transfer-requests", headers=headers, params=params)

    def accept_transfer_request(self, transfer_request_id, headers):
        return self._request("POST", f"/transfer-requests/{transfer_request_id}/accept",
                             {}, headers)

    def reject_transfer_request(self, transfer_request_id, headers):
        return self._request("POST", f"/transfer-requests/{transfer_request_id}/reject",
                             {}, headers)

    def cancel_transfer_request(self, transfer_request_id, headers):
        return self._request("POST", f"/transfer-requests/{transfer_request_id}/cancel",
                             {}, headers)

    # --- BibAssignment ---
    def get_bib_assignment(self, bib_assignment_id, headers):
        return self._request("GET", f"/bib-assignments/{bib_assignment_id}", headers=headers)

    def list_bib_assignments(self, headers, params=None):
        return self._request("GET", "/bib-assignments", headers=headers, params=params)

    def list_wave_bib_assignments(self, wave_id, headers, params=None):
        return self._request("GET", f"/waves/{wave_id}/bib-assignments",
                             headers=headers, params=params)

    def list_distance_bib_assignments(self, distance_id, headers, params=None):
        return self._request("GET", f"/distances/{distance_id}/bib-assignments",
                             headers=headers, params=params)

    # --- PacketPickup ---
    def create_packet_pickup(self, payload, headers):
        return self._request("POST", "/packet-pickups", payload, headers)

    def get_packet_pickup(self, pickup_id, headers):
        return self._request("GET", f"/packet-pickups/{pickup_id}", headers=headers)

    def list_packet_pickups(self, headers, params=None):
        return self._request("GET", "/packet-pickups", headers=headers, params=params)

    def void_packet_pickup(self, pickup_id, headers):
        return self._request("POST", f"/packet-pickups/{pickup_id}/void", {}, headers)

    # --- ResultRecord ---
    def create_result(self, payload, headers):
        return self._request("POST", "/results", payload, headers)

    def get_result(self, result_id, headers):
        return self._request("GET", f"/results/{result_id}", headers=headers)

    def list_results(self, headers, params=None):
        return self._request("GET", "/results", headers=headers, params=params)

    def list_distance_results(self, distance_id, headers, params=None):
        return self._request("GET", f"/distances/{distance_id}/results",
                             headers=headers, params=params)

    def finalize_result(self, result_id, headers):
        return self._request("POST", f"/results/{result_id}/finalize", {}, headers)

    def disqualify_result(self, result_id, headers):
        return self._request("POST", f"/results/{result_id}/disqualify", {}, headers)


api_client = ApiClient()
