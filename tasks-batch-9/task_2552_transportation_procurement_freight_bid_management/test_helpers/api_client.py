"""API client: one method per endpoint defined by the PRD (§4)."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/freight-procurement"


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the Freight Bid Management API."""

    # ─── The logical procurement clock ────────────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Optional[Dict] = None):
        """Set the logical clock. This endpoint does not require user headers."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Carriers ─────────────────────────────────────────────────────────────

    def create_carrier(self, payload: Dict[str, Any], headers: Dict):
        return self._request("POST", f"{BASE}/carriers", payload, headers)

    def get_carrier(self, carrier_id: str, headers: Dict):
        return self._request("GET", f"{BASE}/carriers/{carrier_id}", headers=headers)

    def list_carriers(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/carriers", headers=headers, params=params)

    def change_carrier_status(
        self, carrier_id: str, payload: Dict[str, Any], headers: Dict
    ):
        return self._request(
            "POST", f"{BASE}/carriers/{carrier_id}/status-change", payload, headers
        )

    # ─── Qualification reviews ────────────────────────────────────────────────

    def create_qualification_review(
        self, carrier_id: str, payload: Dict[str, Any], headers: Dict
    ):
        return self._request(
            "POST", f"{BASE}/carriers/{carrier_id}/qualification-reviews", payload, headers
        )

    def list_qualification_reviews(
        self, carrier_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/carriers/{carrier_id}/qualification-reviews",
            headers=headers,
            params=params,
        )

    def verify_insurance(self, review_id: str, payload: Dict[str, Any], headers: Dict):
        return self._request(
            "POST",
            f"{BASE}/qualification-reviews/{review_id}/insurance-verification",
            payload,
            headers,
        )

    def screen_capability(
        self, review_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{BASE}/qualification-reviews/{review_id}/capability-screening",
            payload if payload is not None else {},
            headers,
        )

    def decide_qualification_review(
        self, review_id: str, payload: Dict[str, Any], headers: Dict
    ):
        return self._request(
            "POST", f"{BASE}/qualification-reviews/{review_id}/decision", payload, headers
        )

    # ─── Scorecards ───────────────────────────────────────────────────────────

    def create_scorecard(self, carrier_id: str, payload: Dict[str, Any], headers: Dict):
        return self._request(
            "POST", f"{BASE}/carriers/{carrier_id}/scorecards", payload, headers
        )

    def list_carrier_scorecards(
        self, carrier_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/carriers/{carrier_id}/scorecards",
            headers=headers,
            params=params,
        )

    def publish_scorecard(
        self, scorecard_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{BASE}/scorecards/{scorecard_id}/publish",
            payload if payload is not None else {},
            headers,
        )

    def dispute_scorecard(
        self, scorecard_id: str, payload: Dict[str, Any], headers: Dict
    ):
        return self._request(
            "POST", f"{BASE}/scorecards/{scorecard_id}/dispute", payload, headers
        )

    # ─── Bid events ───────────────────────────────────────────────────────────

    def create_bid_event(self, payload: Dict[str, Any], headers: Dict):
        return self._request("POST", f"{BASE}/bid-events", payload, headers)

    def get_bid_event(self, event_id: str, headers: Dict):
        return self._request("GET", f"{BASE}/bid-events/{event_id}", headers=headers)

    def create_lane(self, event_id: str, payload: Dict[str, Any], headers: Dict):
        return self._request(
            "POST", f"{BASE}/bid-events/{event_id}/lanes", payload, headers
        )

    def lock_lanes(self, event_id: str, headers: Dict, payload: Optional[Dict] = None):
        return self._request(
            "POST",
            f"{BASE}/bid-events/{event_id}/lock-lanes",
            payload if payload is not None else {},
            headers,
        )

    def create_invitation(self, event_id: str, payload: Dict[str, Any], headers: Dict):
        return self._request(
            "POST", f"{BASE}/bid-events/{event_id}/invitations", payload, headers
        )

    def create_bid_round(self, event_id: str, payload: Dict[str, Any], headers: Dict):
        return self._request(
            "POST", f"{BASE}/bid-events/{event_id}/bid-rounds", payload, headers
        )

    def list_bid_rounds(
        self, event_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/bid-events/{event_id}/bid-rounds", headers=headers, params=params
        )

    def list_event_optimization_runs(
        self, event_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/bid-events/{event_id}/optimization-runs",
            headers=headers,
            params=params,
        )

    def award_bid_event(
        self, event_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{BASE}/bid-events/{event_id}/award",
            payload if payload is not None else {},
            headers,
        )

    # ─── Lanes ────────────────────────────────────────────────────────────────

    def get_lane(self, lane_id: str, headers: Dict):
        return self._request("GET", f"{BASE}/lanes/{lane_id}", headers=headers)

    def list_lanes(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/lanes", headers=headers, params=params)

    def validate_lane(self, lane_id: str, headers: Dict, payload: Optional[Dict] = None):
        return self._request(
            "POST",
            f"{BASE}/lanes/{lane_id}/validate",
            payload if payload is not None else {},
            headers,
        )

    # ─── Invitations ──────────────────────────────────────────────────────────

    def get_invitation(self, invitation_id: str, headers: Dict):
        return self._request("GET", f"{BASE}/invitations/{invitation_id}", headers=headers)

    def list_invitations(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/invitations", headers=headers, params=params)

    def respond_to_invitation(
        self, invitation_id: str, payload: Dict[str, Any], headers: Dict
    ):
        return self._request(
            "POST", f"{BASE}/invitations/{invitation_id}/response", payload, headers
        )

    def revoke_invitation(
        self, invitation_id: str, payload: Dict[str, Any], headers: Dict
    ):
        return self._request(
            "POST", f"{BASE}/invitations/{invitation_id}/revoke", payload, headers
        )

    # ─── Bid rounds and lane bids ─────────────────────────────────────────────

    def get_bid_round(self, round_id: str, headers: Dict):
        return self._request("GET", f"{BASE}/bid-rounds/{round_id}", headers=headers)

    def create_lane_bid(self, round_id: str, payload: Dict[str, Any], headers: Dict):
        return self._request(
            "POST", f"{BASE}/bid-rounds/{round_id}/lane-bids", payload, headers
        )

    def close_bid_round(self, round_id: str, headers: Dict, payload: Optional[Dict] = None):
        return self._request(
            "POST",
            f"{BASE}/bid-rounds/{round_id}/close",
            payload if payload is not None else {},
            headers,
        )

    def get_lane_bid(self, bid_id: str, headers: Dict):
        return self._request("GET", f"{BASE}/lane-bids/{bid_id}", headers=headers)

    def list_lane_bids(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/lane-bids", headers=headers, params=params)

    def withdraw_lane_bid(self, bid_id: str, headers: Dict, payload: Optional[Dict] = None):
        return self._request(
            "POST",
            f"{BASE}/lane-bids/{bid_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    # ─── Optimisation runs and the routing guide ──────────────────────────────

    def create_optimization_run(self, payload: Dict[str, Any], headers: Dict):
        return self._request("POST", f"{BASE}/optimization-runs", payload, headers)

    def get_optimization_run(self, run_id: str, headers: Dict):
        return self._request(
            "GET", f"{BASE}/optimization-runs/{run_id}", headers=headers
        )

    def publish_routing_guide(
        self, run_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{BASE}/optimization-runs/{run_id}/routing-guide",
            payload if payload is not None else {},
            headers,
        )

    # ─── Award allocations ────────────────────────────────────────────────────

    def get_award_allocation(self, allocation_id: str, headers: Dict):
        return self._request(
            "GET", f"{BASE}/award-allocations/{allocation_id}", headers=headers
        )

    def list_award_allocations(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{BASE}/award-allocations", headers=headers, params=params
        )

    def approve_award_allocation(
        self, allocation_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{BASE}/award-allocations/{allocation_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    def reject_award_allocation(
        self, allocation_id: str, payload: Dict[str, Any], headers: Dict
    ):
        return self._request(
            "POST", f"{BASE}/award-allocations/{allocation_id}/reject", payload, headers
        )

    # ─── Contracts ────────────────────────────────────────────────────────────

    def get_contract(self, contract_id: str, headers: Dict):
        return self._request("GET", f"{BASE}/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/contracts", headers=headers, params=params)

    def sign_contract_as_carrier(
        self, contract_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{BASE}/contracts/{contract_id}/carrier-signature",
            payload if payload is not None else {},
            headers,
        )

    def sign_contract_as_shipper(
        self, contract_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{BASE}/contracts/{contract_id}/shipper-signature",
            payload if payload is not None else {},
            headers,
        )

    def create_rate_record(self, contract_id: str, payload: Dict[str, Any], headers: Dict):
        return self._request(
            "POST", f"{BASE}/contracts/{contract_id}/rate-records", payload, headers
        )

    # ─── Rate records, loading, go-live and tendering ─────────────────────────

    def get_rate_record(self, rate_record_id: str, headers: Dict):
        return self._request(
            "GET", f"{BASE}/rate-records/{rate_record_id}", headers=headers
        )

    def list_rate_records(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/rate-records", headers=headers, params=params)

    def load_rate_record(
        self, rate_record_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{BASE}/rate-records/{rate_record_id}/load",
            payload if payload is not None else {},
            headers,
        )

    def go_live_rate_record(
        self, rate_record_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{BASE}/rate-records/{rate_record_id}/go-live",
            payload if payload is not None else {},
            headers,
        )

    def create_tender_event(
        self, rate_record_id: str, payload: Dict[str, Any], headers: Dict
    ):
        return self._request(
            "POST", f"{BASE}/rate-records/{rate_record_id}/tender-events", payload, headers
        )

    def list_tender_events(
        self, rate_record_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/rate-records/{rate_record_id}/tender-events",
            headers=headers,
            params=params,
        )

    # ─── Mini-bids ────────────────────────────────────────────────────────────

    def create_mini_bid(self, payload: Dict[str, Any], headers: Dict):
        return self._request("POST", f"{BASE}/mini-bids", payload, headers)

    def get_mini_bid(self, mini_bid_id: str, headers: Dict):
        return self._request("GET", f"{BASE}/mini-bids/{mini_bid_id}", headers=headers)

    def list_mini_bids(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/mini-bids", headers=headers, params=params)

    def propose_mini_bid_rate(
        self, mini_bid_id: str, payload: Dict[str, Any], headers: Dict
    ):
        return self._request(
            "POST", f"{BASE}/mini-bids/{mini_bid_id}/proposal", payload, headers
        )

    def apply_mini_bid(self, mini_bid_id: str, payload: Dict[str, Any], headers: Dict):
        return self._request(
            "POST", f"{BASE}/mini-bids/{mini_bid_id}/apply", payload, headers
        )

    def deny_mini_bid(self, mini_bid_id: str, payload: Dict[str, Any], headers: Dict):
        return self._request(
            "POST", f"{BASE}/mini-bids/{mini_bid_id}/deny", payload, headers
        )

    def revert_mini_bid(self, mini_bid_id: str, payload: Dict[str, Any], headers: Dict):
        return self._request(
            "POST", f"{BASE}/mini-bids/{mini_bid_id}/revert", payload, headers
        )


api_client = ApiClient()
