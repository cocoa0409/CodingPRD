"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- assets
    def create_storage_asset(self, payload, headers):
        return self._request("POST", "/storage-assets", payload, headers)

    def get_storage_asset(self, asset_id, headers):
        return self._request("GET", f"/storage-assets/{asset_id}", headers=headers)

    def list_storage_assets(self, headers, params=None):
        return self._request("GET", "/storage-assets", headers=headers, params=params)

    def commission_storage_asset(self, asset_id, headers, payload=None):
        return self._request(
            "POST", f"/storage-assets/{asset_id}/commission", payload, headers
        )

    # ----------------------------------------------------------------- clock
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ---------------------------------------------------------- reservations
    def create_soc_reservation(self, payload, headers):
        return self._request("POST", "/soc-reservations", payload, headers)

    def get_soc_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/soc-reservations/{reservation_id}", headers=headers
        )

    def list_soc_reservations(self, headers, params=None):
        return self._request("GET", "/soc-reservations", headers=headers, params=params)

    def release_soc_reservation(self, reservation_id, headers, payload=None):
        return self._request(
            "POST", f"/soc-reservations/{reservation_id}/release", payload, headers
        )

    # ------------------------------------------------------------ market bids
    def create_market_bid(self, payload, headers):
        return self._request("POST", "/market-bids", payload, headers)

    def get_market_bid(self, bid_id, headers):
        return self._request("GET", f"/market-bids/{bid_id}", headers=headers)

    def list_market_bids(self, headers, params=None):
        return self._request("GET", "/market-bids", headers=headers, params=params)

    def submit_market_bid(self, bid_id, headers, payload=None):
        return self._request("POST", f"/market-bids/{bid_id}/submit", payload, headers)

    def post_clearing_result(self, bid_id, payload, headers):
        return self._request(
            "POST", f"/market-bids/{bid_id}/clearing-result", payload, headers
        )

    def revise_market_bid(self, bid_id, payload, headers):
        return self._request("POST", f"/market-bids/{bid_id}/revise", payload, headers)

    def withdraw_market_bid(self, bid_id, headers, payload=None):
        return self._request("POST", f"/market-bids/{bid_id}/withdraw", payload, headers)

    # --------------------------------------------------- dispatch instructions
    def create_dispatch_instruction(self, payload, headers):
        return self._request("POST", "/dispatch-instructions", payload, headers)

    def get_dispatch_instruction(self, dispatch_id, headers):
        return self._request(
            "GET", f"/dispatch-instructions/{dispatch_id}", headers=headers
        )

    def list_dispatch_instructions(self, headers, params=None):
        return self._request(
            "GET", "/dispatch-instructions", headers=headers, params=params
        )

    def accept_dispatch_instruction(self, dispatch_id, headers, payload=None):
        return self._request(
            "POST", f"/dispatch-instructions/{dispatch_id}/accept", payload, headers
        )

    def execute_dispatch_instruction(self, dispatch_id, headers, payload=None):
        return self._request(
            "POST", f"/dispatch-instructions/{dispatch_id}/execute", payload, headers
        )

    def complete_dispatch_instruction(self, dispatch_id, headers, payload=None):
        return self._request(
            "POST", f"/dispatch-instructions/{dispatch_id}/complete", payload, headers
        )

    def fail_dispatch_instruction(self, dispatch_id, headers, payload=None):
        return self._request(
            "POST", f"/dispatch-instructions/{dispatch_id}/fail", payload, headers
        )

    def settle_dispatch_score(self, dispatch_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dispatch-instructions/{dispatch_id}/settle-score",
            payload,
            headers,
        )

    # -------------------------------------------------------------- telemetry
    def create_telemetry_sample(self, payload, headers):
        return self._request("POST", "/telemetry-samples", payload, headers)

    def list_telemetry_samples(self, dispatch_id, headers, params=None):
        return self._request(
            "GET",
            f"/dispatch-instructions/{dispatch_id}/telemetry-samples",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------------------- safety events
    def create_safety_event(self, payload, headers):
        return self._request("POST", "/safety-events", payload, headers)

    def get_safety_event(self, event_id, headers):
        return self._request("GET", f"/safety-events/{event_id}", headers=headers)

    def list_safety_events(self, headers, params=None):
        return self._request("GET", "/safety-events", headers=headers, params=params)

    def discharge_suppression(self, event_id, payload, headers):
        return self._request(
            "POST", f"/safety-events/{event_id}/discharge-suppression", payload, headers
        )

    def close_safety_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/safety-events/{event_id}/close", payload, headers
        )

    # ----------------------------------------------------- capacity obligations
    def create_capacity_obligation(self, payload, headers):
        return self._request("POST", "/capacity-obligations", payload, headers)

    def get_capacity_obligation(self, obligation_id, headers):
        return self._request(
            "GET", f"/capacity-obligations/{obligation_id}", headers=headers
        )

    def list_capacity_obligations(self, headers, params=None):
        return self._request(
            "GET", "/capacity-obligations", headers=headers, params=params
        )

    def record_unavailability(self, obligation_id, payload, headers):
        return self._request(
            "POST",
            f"/capacity-obligations/{obligation_id}/unavailability",
            payload,
            headers,
        )

    def assess_capacity_obligation(self, obligation_id, payload, headers):
        return self._request(
            "POST", f"/capacity-obligations/{obligation_id}/assess", payload, headers
        )

    # ---------------------------------------------------------- capacity tests
    def create_capacity_test(self, payload, headers):
        return self._request("POST", "/capacity-tests", payload, headers)

    def get_capacity_test(self, test_id, headers):
        return self._request("GET", f"/capacity-tests/{test_id}", headers=headers)

    def list_capacity_tests(self, headers, params=None):
        return self._request("GET", "/capacity-tests", headers=headers, params=params)

    def start_capacity_test(self, test_id, headers, payload=None):
        return self._request(
            "POST", f"/capacity-tests/{test_id}/start", payload, headers
        )

    def complete_capacity_test(self, test_id, payload, headers):
        return self._request(
            "POST", f"/capacity-tests/{test_id}/complete", payload, headers
        )

    # --------------------------------------------------------- warranty claims
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def submit_warranty_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/submit", payload, headers
        )

    def adjudicate_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/adjudicate", payload, headers
        )

    def install_warranty_remedy(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/install-remedy", payload, headers
        )


api_client = ApiClient()
