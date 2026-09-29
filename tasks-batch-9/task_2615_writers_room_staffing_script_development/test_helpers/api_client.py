"""HTTP client for the writers-room staffing and script development API.

One method per contract endpoint. Every method returns the raw response so the
caller can assert on the status code as well as the envelope.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed façade over the sixty-one endpoints of the contract."""

    # --- Guild agreements ----------------------------------------------------

    def create_guild_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/guild-agreements", payload, headers)

    def get_guild_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/guild-agreements/{agreement_id}", None, headers)

    def list_guild_agreements(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/guild-agreements", params, headers)

    # --- Writers -------------------------------------------------------------

    def create_writer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/writers", payload, headers)

    def add_credit_history(
        self, writer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/writers/{writer_id}/credit-history", payload, headers
        )

    def get_writer(self, writer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/writers/{writer_id}", None, headers)

    def list_writers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/writers", params, headers)

    # --- Availability windows ------------------------------------------------

    def create_availability_window(
        self, writer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/writers/{writer_id}/availability-windows", payload, headers
        )

    def get_availability_window(self, window_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/availability-windows/{window_id}", None, headers
        )

    def list_availability_windows(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/availability-windows", params, headers)

    # --- Seasons -------------------------------------------------------------

    def create_season(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/seasons", payload, headers)

    def reschedule_season(
        self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/seasons/{season_id}/reschedule", payload, headers
        )

    def get_season(self, season_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/seasons/{season_id}", None, headers)

    def list_seasons(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/seasons", params, headers)

    # --- Writers rooms -------------------------------------------------------

    def create_room(
        self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/seasons/{season_id}/rooms", payload, headers)

    def open_staffing(self, room_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/rooms/{room_id}/open-staffing", {}, headers)

    def reconfigure_room(
        self, room_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/rooms/{room_id}/reconfigure", payload, headers)

    def activate_room(self, room_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/rooms/{room_id}/activate", {}, headers)

    def wrap_room(self, room_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/rooms/{room_id}/wrap", {}, headers)

    def get_room(self, room_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rooms/{room_id}", None, headers)

    def list_rooms(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/rooms", params, headers)

    # --- Room seats ----------------------------------------------------------

    def offer_seat(
        self, room_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/rooms/{room_id}/seats", payload, headers)

    def accept_seat(self, seat_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/room-seats/{seat_id}/accept", {}, headers)

    def decline_seat(
        self,
        seat_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/room-seats/{seat_id}/decline", payload or {}, headers
        )

    def withdraw_seat(
        self,
        seat_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/room-seats/{seat_id}/withdraw", payload or {}, headers
        )

    def release_seat(
        self,
        seat_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/room-seats/{seat_id}/release", payload or {}, headers
        )

    def get_room_seat(self, seat_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/room-seats/{seat_id}", None, headers)

    def list_room_seats(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/room-seats", params, headers)

    # --- Episodes ------------------------------------------------------------

    def create_episode(
        self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/seasons/{season_id}/episodes", payload, headers)

    def lock_episode_for_production(self, episode_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/episodes/{episode_id}/lock-for-production", {}, headers
        )

    def get_episode(self, episode_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/episodes/{episode_id}", None, headers)

    def list_episodes(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/episodes", params, headers)

    # --- Script assignments --------------------------------------------------

    def create_script_assignment(
        self, episode_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/episodes/{episode_id}/script-assignments", payload, headers
        )

    def issue_notes(
        self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/script-assignments/{assignment_id}/issue-notes", payload, headers
        )

    def approve_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/script-assignments/{assignment_id}/approve", {}, headers
        )

    def void_assignment(
        self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/script-assignments/{assignment_id}/void", payload, headers
        )

    def get_script_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/script-assignments/{assignment_id}", None, headers
        )

    def list_script_assignments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/script-assignments", params, headers)

    # --- Milestones ----------------------------------------------------------

    def deliver_milestone(self, milestone_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/milestones/{milestone_id}/deliver", {}, headers)

    def get_milestone(self, milestone_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/milestones/{milestone_id}", None, headers)

    def list_milestones(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/milestones", params, headers)

    # --- Script clearance ----------------------------------------------------

    def create_clearance_review(
        self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/script-assignments/{assignment_id}/clearance-reviews",
            payload,
            headers,
        )

    def create_clearance_item(
        self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/clearance-reviews/{review_id}/items", payload, headers
        )

    def decide_clearance_item(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/clearance-items/{item_id}/decide", payload, headers
        )

    def grant_clearance_waiver(
        self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/clearance-reviews/{review_id}/waiver", payload, headers
        )

    def get_clearance_review(self, review_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/clearance-reviews/{review_id}", None, headers)

    def list_clearance_reviews(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/clearance-reviews", params, headers)

    def get_clearance_item(self, item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/clearance-items/{item_id}", None, headers)

    def list_clearance_items(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/clearance-items", params, headers)

    # --- Credit determination ------------------------------------------------

    def create_credit_submission(
        self, episode_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/episodes/{episode_id}/credit-submissions", payload, headers
        )

    def close_credit_submissions(self, episode_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/episodes/{episode_id}/credit-submissions/close", {}, headers
        )

    def convene_credit_arbitration(
        self, episode_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/episodes/{episode_id}/credit-arbitration", payload, headers
        )

    def cast_arbitration_vote(
        self, arbitration_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/credit-arbitrations/{arbitration_id}/votes", payload, headers
        )

    def determine_arbitration(
        self,
        arbitration_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/credit-arbitrations/{arbitration_id}/determine",
            payload or {},
            headers,
        )

    def get_credit_submission(self, submission_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/credit-submissions/{submission_id}", None, headers
        )

    def list_credit_submissions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/credit-submissions", params, headers)

    def get_credit_arbitration(self, arbitration_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/credit-arbitrations/{arbitration_id}", None, headers
        )

    def list_credit_arbitrations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/credit-arbitrations", params, headers)

    # --- Fee ledger ----------------------------------------------------------

    def get_fee_ledger_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/fee-ledger-entries/{entry_id}", None, headers)

    def list_fee_ledger_entries(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/fee-ledger-entries", params, headers)

    # --- Logical clock -------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
