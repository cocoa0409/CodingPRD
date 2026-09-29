"""HTTP client with one method per Draft & Combine Operations endpoint.

Every method returns the raw ``requests.Response`` so tests can assert on
status codes as well as bodies.
"""

from typing import Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/draft-ops"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Draft & Combine Operations API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_logical_clock(
        self, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", payload=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Draft cycles
    # ------------------------------------------------------------------

    def create_draft_cycle(
        self, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/draft-cycles", payload=payload, headers=headers
        )

    def get_draft_cycle(
        self, cycle_id: str, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/draft-cycles/{cycle_id}", headers=headers
        )

    def set_cycle_phase(
        self, cycle_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/draft-cycles/{cycle_id}/phase",
            payload=payload,
            headers=headers,
        )

    def run_lottery(
        self, cycle_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/draft-cycles/{cycle_id}/lottery",
            payload=payload,
            headers=headers,
        )

    def finalize_draft_order(
        self,
        cycle_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/draft-cycles/{cycle_id}/draft-order/finalize",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def advance_selection_clock(
        self,
        cycle_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/draft-cycles/{cycle_id}/clock/advance",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def select_combine_invitations(
        self, cycle_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/draft-cycles/{cycle_id}/combine-invitations/select",
            payload=payload,
            headers=headers,
        )

    def list_cycle_clubs(
        self,
        cycle_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE}/draft-cycles/{cycle_id}/clubs",
            headers=headers,
            params=params,
        )

    def list_cycle_prospects(
        self,
        cycle_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE}/draft-cycles/{cycle_id}/prospects",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Clubs
    # ------------------------------------------------------------------

    def create_club(
        self, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/clubs", payload=payload, headers=headers
        )

    def get_club(
        self, club_id: str, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/clubs/{club_id}", headers=headers)

    # ------------------------------------------------------------------
    # Prospects
    # ------------------------------------------------------------------

    def create_prospect(
        self, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/prospects", payload=payload, headers=headers
        )

    def get_prospect(
        self, prospect_id: str, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/prospects/{prospect_id}", headers=headers
        )

    def declare_prospect(
        self, prospect_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/prospects/{prospect_id}/declaration",
            payload=payload,
            headers=headers,
        )

    def determine_prospect_eligibility(
        self, prospect_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/prospects/{prospect_id}/eligibility-determination",
            payload=payload,
            headers=headers,
        )

    def act_on_combine_invitation(
        self, prospect_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/prospects/{prospect_id}/combine-invitation",
            payload=payload,
            headers=headers,
        )

    def act_on_prospect_consent(
        self, prospect_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/prospects/{prospect_id}/consent",
            payload=payload,
            headers=headers,
        )

    def create_eligibility_waiver(
        self, prospect_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/prospects/{prospect_id}/eligibility-waivers",
            payload=payload,
            headers=headers,
        )

    def list_eligibility_waivers(
        self,
        prospect_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE}/prospects/{prospect_id}/eligibility-waivers",
            headers=headers,
            params=params,
        )

    def review_eligibility_waiver(
        self, waiver_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/eligibility-waivers/{waiver_id}/review",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Combine resources
    # ------------------------------------------------------------------

    def create_medical_station(
        self, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/medical-stations", payload=payload, headers=headers
        )

    def get_medical_station(
        self, station_id: str, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/medical-stations/{station_id}", headers=headers
        )

    def create_interview_room(
        self, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/interview-rooms", payload=payload, headers=headers
        )

    def get_interview_room(
        self, room_id: str, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/interview-rooms/{room_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Combine bookings
    # ------------------------------------------------------------------

    def create_combine_booking(
        self, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/combine-bookings", payload=payload, headers=headers
        )

    def get_combine_booking(
        self, booking_id: str, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/combine-bookings/{booking_id}", headers=headers
        )

    def list_combine_bookings(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/combine-bookings", headers=headers, params=params
        )

    def set_booking_status(
        self, booking_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/combine-bookings/{booking_id}/status",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Medical evaluations
    # ------------------------------------------------------------------

    def create_medical_evaluation(
        self, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/medical-evaluations",
            payload=payload,
            headers=headers,
        )

    def get_medical_evaluation(
        self, evaluation_id: str, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/medical-evaluations/{evaluation_id}", headers=headers
        )

    def list_medical_evaluations(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/medical-evaluations", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Medical record shares
    # ------------------------------------------------------------------

    def create_medical_record_share(
        self, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/medical-record-shares",
            payload=payload,
            headers=headers,
        )

    def get_medical_record_share(
        self, share_id: str, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/medical-record-shares/{share_id}", headers=headers
        )

    def list_medical_record_shares(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE}/medical-record-shares",
            headers=headers,
            params=params,
        )

    def decide_medical_record_share(
        self, share_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/medical-record-shares/{share_id}/decision",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Draft picks
    # ------------------------------------------------------------------

    def get_draft_pick(
        self, pick_id: str, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/draft-picks/{pick_id}", headers=headers
        )

    def list_draft_picks(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/draft-picks", headers=headers, params=params
        )

    def create_selection(
        self, pick_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/draft-picks/{pick_id}/selections",
            payload=payload,
            headers=headers,
        )

    def act_on_pick_clock(
        self, pick_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/draft-picks/{pick_id}/clock-action",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Pick trades
    # ------------------------------------------------------------------

    def create_pick_trade(
        self, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/pick-trades", payload=payload, headers=headers
        )

    def get_pick_trade(
        self, trade_id: str, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/pick-trades/{trade_id}", headers=headers
        )

    def list_pick_trades(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/pick-trades", headers=headers, params=params
        )

    def counter_pick_trade(
        self, trade_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/pick-trades/{trade_id}/counter",
            payload=payload,
            headers=headers,
        )

    def accept_pick_trade(
        self,
        trade_id: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/pick-trades/{trade_id}/accept",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def terminate_pick_trade(
        self, trade_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/pick-trades/{trade_id}/termination",
            payload=payload,
            headers=headers,
        )

    def resolve_trade_condition(
        self, trade_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/pick-trades/{trade_id}/conditional-resolution",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Compensatory claims
    # ------------------------------------------------------------------

    def create_compensatory_claim(
        self, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/compensatory-claims",
            payload=payload,
            headers=headers,
        )

    def get_compensatory_claim(
        self, claim_id: str, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/compensatory-claims/{claim_id}", headers=headers
        )

    def list_compensatory_claims(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/compensatory-claims", headers=headers, params=params
        )

    def verify_compensatory_claim(
        self, claim_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/compensatory-claims/{claim_id}/verify",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Player contracts
    # ------------------------------------------------------------------

    def create_player_contract(
        self, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/player-contracts", payload=payload, headers=headers
        )

    def get_player_contract(
        self, contract_id: str, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/player-contracts/{contract_id}", headers=headers
        )

    def list_player_contracts(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/player-contracts", headers=headers, params=params
        )

    def set_contract_status(
        self, contract_id: str, payload: Dict, headers: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/player-contracts/{contract_id}/status",
            payload=payload,
            headers=headers,
        )


# Shared client instance used by the session-scoped ``api`` fixture.
api_client = ApiClient()
