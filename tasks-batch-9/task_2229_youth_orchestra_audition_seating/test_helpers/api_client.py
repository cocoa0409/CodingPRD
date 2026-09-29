"""Typed HTTP client: one method per endpoint declared in PRD §4."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per PRD §4 endpoint, returning the raw response."""

    # ------------------------------------------------------------------
    # Logical clock (PRD §2.5)
    # ------------------------------------------------------------------

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Seasons
    # ------------------------------------------------------------------

    def create_season(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/seasons", payload, headers)

    def list_seasons(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/seasons", headers=headers, params=params)

    def get_season(self, season_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/seasons/{season_id}", headers=headers)

    def advance_season_status(
        self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/seasons/{season_id}/advance-status", payload, headers
        )

    def offer_expiry_sweep(
        self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/seasons/{season_id}/offer-expiry-sweep", payload, headers
        )

    def aid_award_run(
        self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/seasons/{season_id}/aid-award-run", payload, headers
        )

    # ------------------------------------------------------------------
    # Ensembles
    # ------------------------------------------------------------------

    def create_ensemble(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/ensembles", payload, headers)

    def list_ensembles(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/ensembles", headers=headers, params=params)

    def get_ensemble(self, ensemble_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ensembles/{ensemble_id}", headers=headers)

    # ------------------------------------------------------------------
    # Section quotas
    # ------------------------------------------------------------------

    def create_section_quota(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/section-quotas", payload, headers)

    def list_section_quotas(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/section-quotas", headers=headers, params=params)

    def get_section_quota(self, quota_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/section-quotas/{quota_id}", headers=headers)

    def rotate_chairs(
        self, quota_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/section-quotas/{quota_id}/rotate-chairs", payload, headers
        )

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------

    def create_member(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/members", payload, headers)

    def list_members(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def member_status_transition(
        self, member_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/members/{member_id}/status-transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Panelists
    # ------------------------------------------------------------------

    def create_panelist(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/panelists", payload, headers)

    def list_panelists(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/panelists", headers=headers, params=params)

    def get_panelist(self, panelist_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/panelists/{panelist_id}", headers=headers)

    # ------------------------------------------------------------------
    # Audition slots
    # ------------------------------------------------------------------

    def create_audition_slot(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/audition-slots", payload, headers)

    def list_audition_slots(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/audition-slots", headers=headers, params=params)

    def get_audition_slot(self, slot_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/audition-slots/{slot_id}", headers=headers)

    # ------------------------------------------------------------------
    # Auditions
    # ------------------------------------------------------------------

    def create_audition(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/auditions", payload, headers)

    def list_auditions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/auditions", headers=headers, params=params)

    def get_audition(self, audition_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/auditions/{audition_id}", headers=headers)

    def schedule_audition(
        self, audition_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/auditions/{audition_id}/schedule", payload, headers
        )

    def submit_panel_score(
        self, audition_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/auditions/{audition_id}/panel-scores", payload, headers
        )

    def adjudicate_audition(
        self, audition_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/auditions/{audition_id}/adjudicate", payload, headers
        )

    def request_revision(
        self, audition_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/auditions/{audition_id}/request-revision", payload, headers
        )

    # ------------------------------------------------------------------
    # Panel scores (rubric sheets)
    # ------------------------------------------------------------------

    def list_panel_scores(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/panel-scores", headers=headers, params=params)

    def get_panel_score(self, score_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/panel-scores/{score_id}", headers=headers)

    # ------------------------------------------------------------------
    # Placements
    # ------------------------------------------------------------------

    def create_placement(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/placements", payload, headers)

    def list_placements(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/placements", headers=headers, params=params)

    def get_placement(self, placement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/placements/{placement_id}", headers=headers)

    def accept_placement(
        self, placement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/placements/{placement_id}/accept", payload, headers
        )

    def decline_placement(
        self, placement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/placements/{placement_id}/decline", payload, headers
        )

    # ------------------------------------------------------------------
    # Seat assignments (chairs)
    # ------------------------------------------------------------------

    def list_seat_assignments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/seat-assignments", headers=headers, params=params)

    def get_seat_assignment(self, seat_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/seat-assignments/{seat_id}", headers=headers)

    def vacate_seat(
        self, seat_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/seat-assignments/{seat_id}/vacate", payload, headers
        )

    # ------------------------------------------------------------------
    # Tuition accounts
    # ------------------------------------------------------------------

    def list_tuition_accounts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/tuition-accounts", headers=headers, params=params)

    def get_tuition_account(self, account_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/tuition-accounts/{account_id}", headers=headers)

    def finalize_assessment(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/tuition-accounts/{account_id}/finalize-assessment", payload, headers
        )

    def request_aid(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/tuition-accounts/{account_id}/aid-request", payload, headers
        )

    def review_aid(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/tuition-accounts/{account_id}/aid-review", payload, headers
        )

    def rescind_aid(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/tuition-accounts/{account_id}/aid-rescind", payload, headers
        )

    def record_payment(
        self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/tuition-accounts/{account_id}/payments", payload, headers
        )

    # ------------------------------------------------------------------
    # Ensemble events
    # ------------------------------------------------------------------

    def create_ensemble_event(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/ensemble-events", payload, headers)

    def list_ensemble_events(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/ensemble-events", headers=headers, params=params)

    def get_ensemble_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ensemble-events/{event_id}", headers=headers)

    def program_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/ensemble-events/{event_id}/programming", payload, headers
        )

    # ------------------------------------------------------------------
    # Event participations
    # ------------------------------------------------------------------

    def create_event_participation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/event-participations", payload, headers)

    def list_event_participations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/event-participations", headers=headers, params=params
        )

    def get_event_participation(
        self, participation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/event-participations/{participation_id}", headers=headers
        )

    def record_attendance(
        self, participation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/event-participations/{participation_id}/attendance", payload, headers
        )

    def request_excuse(
        self, participation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/event-participations/{participation_id}/excuse-request",
            payload,
            headers,
        )

    def decide_excuse(
        self, participation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/event-participations/{participation_id}/excuse-decision",
            payload,
            headers,
        )

    def review_eligibility(
        self, participation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/event-participations/{participation_id}/eligibility-review",
            payload,
            headers,
        )

    def submit_tour_requirements(
        self, participation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/event-participations/{participation_id}/tour-requirements",
            payload,
            headers,
        )
