"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- clock / ops ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    def run_daily_sweep(self, headers):
        return self._request("POST", "/api/ops/run-daily-sweep", {}, headers)

    # ---- Site ----
    def create_site(self, payload, headers):
        return self._request("POST", "/api/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/api/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/api/sites/{site_id}", headers=headers)

    def update_site(self, site_id, payload, headers):
        return self._request("PATCH", f"/api/sites/{site_id}", payload, headers)

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/api/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/api/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}", headers=headers)

    def update_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/api/members/{member_id}", payload, headers)

    def get_credit_summary(self, member_id, headers):
        return self._request(
            "GET", f"/api/members/{member_id}/credit-summary", headers=headers
        )

    # ---- Volunteer ----
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/api/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/api/volunteers/{volunteer_id}", headers=headers)

    def approve_volunteer(self, volunteer_id, headers):
        return self._request(
            "POST", f"/api/volunteers/{volunteer_id}/approve", {}, headers
        )

    def update_volunteer(self, volunteer_id, payload, headers):
        return self._request(
            "PATCH", f"/api/volunteers/{volunteer_id}", payload, headers
        )

    # ---- SeedVariety ----
    def create_seed_variety(self, payload, headers):
        return self._request("POST", "/api/seed-varieties", payload, headers)

    def list_seed_varieties(self, headers, params=None):
        return self._request("GET", "/api/seed-varieties", headers=headers, params=params)

    def get_seed_variety(self, variety_id, headers):
        return self._request("GET", f"/api/seed-varieties/{variety_id}", headers=headers)

    def update_seed_variety(self, variety_id, payload, headers):
        return self._request(
            "PATCH", f"/api/seed-varieties/{variety_id}", payload, headers
        )

    # ---- SeedLot ----
    def create_seed_lot(self, payload, headers):
        return self._request("POST", "/api/seed-lots", payload, headers)

    def list_seed_lots(self, headers, params=None):
        return self._request("GET", "/api/seed-lots", headers=headers, params=params)

    def get_seed_lot(self, lot_id, headers):
        return self._request("GET", f"/api/seed-lots/{lot_id}", headers=headers)

    def update_seed_lot(self, lot_id, payload, headers):
        return self._request("PATCH", f"/api/seed-lots/{lot_id}", payload, headers)

    def submit_lot_for_review(self, lot_id, headers):
        return self._request(
            "POST", f"/api/seed-lots/{lot_id}/submit-for-review", {}, headers
        )

    def recheck_seed_lot(self, lot_id, headers):
        return self._request("POST", f"/api/seed-lots/{lot_id}/recheck", {}, headers)

    # ---- GerminationTest ----
    def record_germination_test(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/api/seed-lots/{lot_id}/germination-tests", payload, headers
        )

    def list_germination_tests(self, headers, params=None):
        return self._request(
            "GET", "/api/germination-tests", headers=headers, params=params
        )

    def get_germination_test(self, test_id, headers):
        return self._request(
            "GET", f"/api/germination-tests/{test_id}", headers=headers
        )

    def certify_germination_test(self, test_id, payload, headers):
        return self._request(
            "POST", f"/api/germination-tests/{test_id}/certify", payload, headers
        )

    def void_germination_test(self, test_id, headers):
        return self._request(
            "POST", f"/api/germination-tests/{test_id}/void", {}, headers
        )

    # ---- SeedPacket ----
    def pack_seed_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/seed-lots/{lot_id}/pack", payload, headers)

    def list_seed_packets(self, headers, params=None):
        return self._request("GET", "/api/seed-packets", headers=headers, params=params)

    def get_seed_packet(self, packet_id, headers):
        return self._request("GET", f"/api/seed-packets/{packet_id}", headers=headers)

    def void_seed_packet(self, packet_id, payload, headers):
        return self._request(
            "POST", f"/api/seed-packets/{packet_id}/void", payload, headers
        )

    def dispose_seed_packet(self, packet_id, headers):
        return self._request(
            "POST", f"/api/seed-packets/{packet_id}/dispose", {}, headers
        )

    # ---- Checkout ----
    def create_checkout(self, payload, headers):
        return self._request("POST", "/api/checkouts", payload, headers)

    def list_checkouts(self, headers, params=None):
        return self._request("GET", "/api/checkouts", headers=headers, params=params)

    def get_checkout(self, checkout_id, headers):
        return self._request("GET", f"/api/checkouts/{checkout_id}", headers=headers)

    def return_checkout(self, checkout_id, headers):
        return self._request("POST", f"/api/checkouts/{checkout_id}/return", {}, headers)

    def verify_return(self, checkout_id, headers):
        return self._request(
            "POST", f"/api/checkouts/{checkout_id}/verify-return", {}, headers
        )

    def dispute_checkout(self, checkout_id, payload, headers):
        return self._request(
            "POST", f"/api/checkouts/{checkout_id}/dispute", payload, headers
        )

    def resolve_dispute(self, checkout_id, payload, headers):
        return self._request(
            "POST", f"/api/checkouts/{checkout_id}/resolve-dispute", payload, headers
        )

    # ---- SwapEvent ----
    def create_swap_event(self, payload, headers):
        return self._request("POST", "/api/swap-events", payload, headers)

    def list_swap_events(self, headers, params=None):
        return self._request("GET", "/api/swap-events", headers=headers, params=params)

    def get_swap_event(self, event_id, headers):
        return self._request("GET", f"/api/swap-events/{event_id}", headers=headers)

    def update_swap_event(self, event_id, payload, headers):
        return self._request("PATCH", f"/api/swap-events/{event_id}", payload, headers)

    def publish_swap_event(self, event_id, headers):
        return self._request(
            "POST", f"/api/swap-events/{event_id}/publish", {}, headers
        )

    def open_intake(self, event_id, headers):
        return self._request(
            "POST", f"/api/swap-events/{event_id}/open-intake", {}, headers
        )

    def close_intake(self, event_id, headers):
        return self._request(
            "POST", f"/api/swap-events/{event_id}/close-intake", {}, headers
        )

    def complete_swap_event(self, event_id, headers):
        return self._request(
            "POST", f"/api/swap-events/{event_id}/complete", {}, headers
        )

    def cancel_swap_event(self, event_id, headers):
        return self._request("POST", f"/api/swap-events/{event_id}/cancel", {}, headers)

    def redeem_credits(self, event_id, payload, headers):
        return self._request(
            "POST", f"/api/swap-events/{event_id}/redeem-credits", payload, headers
        )

    # ---- SwapIntakeItem ----
    def submit_intake_item(self, event_id, payload, headers):
        return self._request(
            "POST", f"/api/swap-events/{event_id}/intake-items", payload, headers
        )

    def list_intake_items(self, headers, params=None):
        return self._request("GET", "/api/intake-items", headers=headers, params=params)

    def get_intake_item(self, item_id, headers):
        return self._request("GET", f"/api/intake-items/{item_id}", headers=headers)

    def screen_intake_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/api/intake-items/{item_id}/screen", payload, headers
        )

    def withdraw_intake_item(self, item_id, headers):
        return self._request(
            "POST", f"/api/intake-items/{item_id}/withdraw", {}, headers
        )

    # ---- CreditEntry ----
    def list_credit_entries(self, headers, params=None):
        return self._request("GET", "/api/credit-entries", headers=headers, params=params)

    def get_credit_entry(self, entry_id, headers):
        return self._request("GET", f"/api/credit-entries/{entry_id}", headers=headers)

    # ---- PackingSession / PackingAssignment ----
    def create_packing_session(self, payload, headers):
        return self._request("POST", "/api/packing-sessions", payload, headers)

    def list_packing_sessions(self, headers, params=None):
        return self._request(
            "GET", "/api/packing-sessions", headers=headers, params=params
        )

    def get_packing_session(self, session_id, headers):
        return self._request(
            "GET", f"/api/packing-sessions/{session_id}", headers=headers
        )

    def cancel_packing_session(self, session_id, headers):
        return self._request(
            "POST", f"/api/packing-sessions/{session_id}/cancel", {}, headers
        )

    def complete_packing_session(self, session_id, headers):
        return self._request(
            "POST", f"/api/packing-sessions/{session_id}/complete", {}, headers
        )

    def sign_up_volunteer(self, session_id, payload, headers):
        return self._request(
            "POST", f"/api/packing-sessions/{session_id}/assignments", payload, headers
        )

    def list_packing_assignments(self, headers, params=None):
        return self._request(
            "GET", "/api/packing-assignments", headers=headers, params=params
        )

    def get_packing_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/api/packing-assignments/{assignment_id}", headers=headers
        )

    def cancel_packing_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/api/packing-assignments/{assignment_id}/cancel", {}, headers
        )

    def mark_attended(self, assignment_id, headers):
        return self._request(
            "POST", f"/api/packing-assignments/{assignment_id}/mark-attended", {}, headers
        )


api_client = ApiClient()
