"""One method per endpoint in the PRD §4 table.

Every method returns the raw ``requests.Response`` so tests can assert on the
HTTP status as well as the envelope body.  Paths are exactly as tabulated in
PRD §4; the topology is flat, so no nested collection paths appear here
(PRD §2.10).
"""
from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient


class EsportsLeagueApiClient(GenericApiClient):
    """Typed facade over the Scholastic Esports League API."""

    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(
        self, current_utc: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            payload={"current_utc": current_utc},
            headers=headers,
        )

    def set_clock_raw(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", payload=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Districts (PRD §3.1)
    # ------------------------------------------------------------------
    def create_district(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/districts", payload=payload, headers=headers)

    def get_district(
        self, district_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/districts/{district_id}", headers=headers)

    def list_districts(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("GET", "/districts", payload=params, headers=headers)

    # ------------------------------------------------------------------
    # Schools (PRD §3.1)
    # ------------------------------------------------------------------
    def create_school(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/schools", payload=payload, headers=headers)

    def get_school(
        self, school_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/schools/{school_id}", headers=headers)

    def list_schools(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("GET", "/schools", payload=params, headers=headers)

    # ------------------------------------------------------------------
    # Coaches (PRD §3.2)
    # ------------------------------------------------------------------
    def create_coach(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/coaches", payload=payload, headers=headers)

    def get_coach(
        self, coach_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/coaches/{coach_id}", headers=headers)

    def list_coaches(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("GET", "/coaches", payload=params, headers=headers)

    def certify_coach(
        self,
        coach_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/coaches/{coach_id}/certification",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Students (PRD §3.2, §3.9)
    # ------------------------------------------------------------------
    def create_student(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/students", payload=payload, headers=headers)

    def get_student(
        self, student_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_students(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("GET", "/students", payload=params, headers=headers)

    def post_academic_term(
        self,
        student_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/students/{student_id}/academic-postings",
            payload=payload,
            headers=headers,
        )

    def nominate_showcase(
        self,
        student_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/students/{student_id}/showcase-nomination",
            payload=payload,
            headers=headers,
        )

    def log_recruiting_contact(
        self,
        student_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/students/{student_id}/recruiting-contacts",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Titles (PRD §3.3)
    # ------------------------------------------------------------------
    def create_title(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/titles", payload=payload, headers=headers)

    def get_title(
        self, title_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/titles/{title_id}", headers=headers)

    def list_titles(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("GET", "/titles", payload=params, headers=headers)

    # ------------------------------------------------------------------
    # Title approvals (PRD §3.3)
    # ------------------------------------------------------------------
    def create_title_approval(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/title-approvals", payload=payload, headers=headers
        )

    def get_title_approval(
        self, approval_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/title-approvals/{approval_id}", headers=headers
        )

    def list_title_approvals(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", "/title-approvals", payload=params, headers=headers
        )

    def decide_title_approval(
        self,
        approval_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/title-approvals/{approval_id}/decision",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Seasons (PRD §3.4, §3.9)
    # ------------------------------------------------------------------
    def create_season(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/seasons", payload=payload, headers=headers)

    def get_season(
        self, season_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/seasons/{season_id}", headers=headers)

    def list_seasons(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("GET", "/seasons", payload=params, headers=headers)

    def advance_season(
        self,
        season_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/seasons/{season_id}/advance", payload=payload, headers=headers
        )

    def run_seeding(
        self,
        season_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/seasons/{season_id}/seeding",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Teams (PRD §3.5, §3.6)
    # ------------------------------------------------------------------
    def create_team(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/teams", payload=payload, headers=headers)

    def get_team(
        self, team_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/teams/{team_id}", headers=headers)

    def list_teams(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("GET", "/teams", payload=params, headers=headers)

    def register_team(
        self,
        team_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/teams/{team_id}/register",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def lock_roster(
        self,
        team_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/teams/{team_id}/roster-lock",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def withdraw_team(
        self,
        team_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/teams/{team_id}/withdraw",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Roster slots (PRD §3.5)
    # ------------------------------------------------------------------
    def create_roster_slot(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/roster-slots", payload=payload, headers=headers)

    def get_roster_slot(
        self, slot_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/roster-slots/{slot_id}", headers=headers)

    def list_roster_slots(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("GET", "/roster-slots", payload=params, headers=headers)

    def verify_enrollment(
        self,
        slot_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/roster-slots/{slot_id}/verify-enrollment",
            payload=payload,
            headers=headers,
        )

    def verify_academics(
        self,
        slot_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/roster-slots/{slot_id}/verify-academics",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def release_roster_slot(
        self,
        slot_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/roster-slots/{slot_id}/release",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Matches (PRD §3.7, §3.8)
    # ------------------------------------------------------------------
    def create_match(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/matches", payload=payload, headers=headers)

    def get_match(
        self, match_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/matches/{match_id}", headers=headers)

    def list_matches(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("GET", "/matches", payload=params, headers=headers)

    def configure_server(
        self,
        match_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/matches/{match_id}/server-config",
            payload=payload,
            headers=headers,
        )

    def report_result(
        self,
        match_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/matches/{match_id}/result-reports",
            payload=payload,
            headers=headers,
        )

    def finalize_match(
        self,
        match_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/matches/{match_id}/finalize",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def forfeit_match(
        self,
        match_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/matches/{match_id}/forfeit", payload=payload, headers=headers
        )

    def file_dispute(
        self,
        match_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/matches/{match_id}/disputes", payload=payload, headers=headers
        )

    def dispute_action(
        self,
        match_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/matches/{match_id}/dispute-actions",
            payload=payload,
            headers=headers,
        )

    def broadcast_action(
        self,
        match_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/matches/{match_id}/broadcast", payload=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Fair-play cases (PRD §3.8)
    # ------------------------------------------------------------------
    def create_fair_play_case(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/fair-play-cases", payload=payload, headers=headers
        )

    def get_fair_play_case(
        self, case_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"/fair-play-cases/{case_id}", headers=headers)

    def list_fair_play_cases(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", "/fair-play-cases", payload=params, headers=headers
        )

    def investigate_case(
        self,
        case_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/fair-play-cases/{case_id}/investigate",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def decide_case(
        self,
        case_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/fair-play-cases/{case_id}/decision",
            payload=payload,
            headers=headers,
        )

    def appeal_case(
        self,
        case_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/fair-play-cases/{case_id}/appeal",
            payload=payload,
            headers=headers,
        )

    def decide_appeal(
        self,
        case_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/fair-play-cases/{case_id}/appeal-decision",
            payload=payload,
            headers=headers,
        )
