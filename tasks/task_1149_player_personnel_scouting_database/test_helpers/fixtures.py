"""Composite setup helpers.

Encapsulates multi-step setup sequences so tests can focus on assertions.
Identity threading: every call made with an entity-backed role
(AreaScout / ScoutingDirector) passes the Scout's actual id via
make_*_headers(); opaque roles (GeneralManager / MedicalStaff) reuse the
shared TEST_USERS constants.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_budget_payload,
    create_draft_board_payload,
    create_flag_payload,
    create_free_agent_target_payload,
    create_interview_payload,
    create_outcome_payload,
    create_prospect_payload,
    create_report_payload,
    create_roster_need_payload,
    create_scout_payload,
)
from .test_users import (
    TEST_USERS,
    make_area_scout_headers,
    make_scouting_director_headers,
)

GM_HEADERS = TEST_USERS["general_manager_headers"]
MED_HEADERS = TEST_USERS["medical_staff_headers"]


# ---------------------------------------------------------------------------
# Tier 1: identity / role helpers
# ---------------------------------------------------------------------------


def create_scout(level: str = "AREA", **overrides):
    """Register a Scout (GM-only endpoint). Returns the Scout dict."""
    resp = api_client.create_scout(create_scout_payload(level=level, **overrides), GM_HEADERS)
    return get_success_data(resp)


def create_director(**overrides):
    return create_scout(level="DIRECTOR", **overrides)


def area_headers(scout) -> dict:
    return make_area_scout_headers(scout["id"])


def director_headers(director) -> dict:
    return make_scouting_director_headers(director["id"])


# ---------------------------------------------------------------------------
# Tier 2: prospect + report pipelines
# ---------------------------------------------------------------------------


def create_prospect(as_scout, **overrides):
    """Create a prospect as an AreaScout (identity-bound)."""
    resp = api_client.create_prospect(create_prospect_payload(**overrides), area_headers(as_scout))
    return get_success_data(resp)


def create_report(prospect_id, as_scout, **overrides):
    resp = api_client.create_report(
        prospect_id, create_report_payload(**overrides), area_headers(as_scout)
    )
    return get_success_data(resp)


def submit_report(report_id, as_scout):
    resp = api_client.submit_report(report_id, area_headers(as_scout))
    return get_success_data(resp)


def lock_report(report_id, as_director):
    resp = api_client.lock_report(report_id, director_headers(as_director))
    return get_success_data(resp)


def create_and_lock_report(prospect_id, author_scout, director, **report_overrides):
    """Create -> submit -> lock a report. Returns the locked report dict."""
    report = create_report(prospect_id, author_scout, **report_overrides)
    submit_report(report["id"], author_scout)
    return lock_report(report["id"], director)


def advance_prospect(prospect_id, to_state, as_director):
    resp = api_client.advance_prospect(
        prospect_id, {"to_state": to_state}, director_headers(as_director)
    )
    return get_success_data(resp)


def make_board_ready_prospect(
    author_scout,
    director,
    raw_grade: float = 7.00,
    scheme_fit: float = 1.00,
    **prospect_overrides,
):
    """Create a prospect, lock one report on them, and walk evaluation_status
    SCOUTING -> EVALUATED -> BOARD_READY. Returns the prospect dict."""
    prospect = create_prospect(author_scout, **prospect_overrides)
    create_and_lock_report(prospect["id"], author_scout, director, raw_grade=raw_grade, scheme_fit=scheme_fit)
    advance_prospect(prospect["id"], "EVALUATED", director)
    return advance_prospect(prospect["id"], "BOARD_READY", director)


# ---------------------------------------------------------------------------
# Tier 3: draft-board helpers
# ---------------------------------------------------------------------------


def create_draft_board(as_director, season_year: int = 2026):
    resp = api_client.create_draft_board(
        create_draft_board_payload(season_year=season_year), director_headers(as_director)
    )
    return get_success_data(resp)


def add_board_entry(board_id, prospect_id, as_director):
    resp = api_client.add_board_entry(
        board_id, {"prospect_id": prospect_id}, director_headers(as_director)
    )
    return get_success_data(resp)


def get_board(board_id, as_director):
    resp = api_client.get_draft_board(board_id, director_headers(as_director))
    return get_success_data(resp)


def list_board_entries(board_id, as_director, params: Optional[dict] = None):
    resp = api_client.list_board_entries(board_id, director_headers(as_director), params=params)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: flags
# ---------------------------------------------------------------------------


def create_flag(prospect_id, as_role_headers: dict, **overrides):
    """Create a flag; caller picks the role-appropriate headers.

    MEDICAL flags must be created with medical-staff headers; CHARACTER flags
    must be created with the authoring scout's / director's headers.
    """
    resp = api_client.create_flag(prospect_id, create_flag_payload(**overrides), as_role_headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: free agency / budgets
# ---------------------------------------------------------------------------


def create_budget(**overrides):
    resp = api_client.create_budget(create_budget_payload(**overrides), GM_HEADERS)
    return get_success_data(resp)


def get_budget(budget_id):
    resp = api_client.get_budget(budget_id, GM_HEADERS)
    return get_success_data(resp)


def create_roster_need(**overrides):
    resp = api_client.create_roster_need(create_roster_need_payload(**overrides), GM_HEADERS)
    return get_success_data(resp)


def create_free_agent_target(**overrides):
    resp = api_client.create_free_agent_target(
        create_free_agent_target_payload(**overrides), GM_HEADERS
    )
    return get_success_data(resp)


def advance_target(target_id, to_state):
    resp = api_client.advance_target(target_id, {"to_state": to_state}, GM_HEADERS)
    return get_success_data(resp)


def advance_target_to_offered(target_id):
    """IDENTIFIED -> EVALUATING -> APPROVED -> OFFERED (assumes matching need)."""
    advance_target(target_id, "EVALUATING")
    advance_target(target_id, "APPROVED")
    return advance_target(target_id, "OFFERED")


def create_offered_target(**overrides):
    """Create a target and walk it to OFFERED. Caller ensures an OPEN need exists."""
    target = create_free_agent_target(**overrides)
    advance_target_to_offered(target["id"])
    return get_success_data(api_client.get_free_agent_target(target["id"], GM_HEADERS))


def sign_target(target_id, budget_id):
    resp = api_client.sign_target(target_id, {"budget_id": budget_id}, GM_HEADERS)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 6: interviews / outcomes
# ---------------------------------------------------------------------------


def schedule_interview(prospect_id, as_headers: dict, **overrides):
    resp = api_client.schedule_interview(
        prospect_id, create_interview_payload(**overrides), as_headers
    )
    return get_success_data(resp)


def create_outcome(prospect_id, **overrides):
    resp = api_client.create_outcome(
        prospect_id, create_outcome_payload(**overrides), GM_HEADERS
    )
    return get_success_data(resp)


def make_drafted_prospect(author_scout, director, raw_grade: float = 7.00, **prospect_overrides):
    """Prospect walked all the way to DRAFTED (BOARD_READY -> mark-drafted by GM)."""
    prospect = make_board_ready_prospect(author_scout, director, raw_grade=raw_grade, **prospect_overrides)
    resp = api_client.mark_drafted(prospect["id"], GM_HEADERS)
    return get_success_data(resp)
