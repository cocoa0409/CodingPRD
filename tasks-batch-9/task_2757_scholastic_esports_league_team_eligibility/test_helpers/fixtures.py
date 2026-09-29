"""Composite setup helpers.

Every helper builds state exclusively through the PRD's own endpoints, because
the harness restarts the API with an empty store before each individual test.
Ownership-gated calls always thread the real entity identifier into
``X-User-ID`` via the ``make_*_headers`` builders of :mod:`test_users`, as
PRD §2.1 requires for the three entity-backed roles.
"""
from typing import Any, Dict, List, Optional, Tuple

from . import factories as F
from .api_client import EsportsLeagueApiClient
from .assertions import data_of
from .test_users import (
    ELIGIBILITY_OFFICER_ID,
    ELIGIBILITY_OFFICER_ID_2,
    INTEGRITY_OFFICER_ID,
    INTEGRITY_OFFICER_ID_2,
    INTEGRITY_OFFICER_ID_3,
    eligibility_officer_headers,
    integrity_officer_headers,
    league_admin_headers,
    make_athletic_director_headers,
    make_coach_headers,
    make_district_admin_headers,
)

Api = EsportsLeagueApiClient


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(api: Api, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock (PRD §2.4); LeagueAdmin only."""
    response = api.set_clock(current_utc, headers=league_admin_headers())
    return data_of(response)


# --------------------------------------------------------------------------
# Tier 1 — single entities
# --------------------------------------------------------------------------
def make_district(api: Api, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 district creation; LeagueAdmin only."""
    return data_of(
        api.create_district(F.district_payload(**overrides), league_admin_headers()),
        201,
    )


def make_school(api: Api, district_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 school registration."""
    return data_of(
        api.create_school(
            F.school_payload(district_id, **overrides), league_admin_headers()
        ),
        201,
    )


def make_coach(api: Api, school_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 coach designation, performed by the school's own director."""
    return data_of(
        api.create_coach(
            F.coach_payload(school_id, **overrides),
            make_athletic_director_headers(school_id),
        ),
        201,
    )


def certify_coach(
    api: Api,
    coach: Dict[str, Any],
    background_check_expires_on: str = "2027-06-30",
) -> Dict[str, Any]:
    """PRD §3.2 certification by the school's athletic director."""
    return data_of(
        api.certify_coach(
            coach["id"],
            F.certification_payload(
                action="CERTIFY",
                background_check_expires_on=background_check_expires_on,
            ),
            make_athletic_director_headers(coach["school_id"]),
        )
    )


def make_certified_coach(
    api: Api,
    school_id: str,
    background_check_expires_on: str = "2027-06-30",
    **overrides: Any,
) -> Dict[str, Any]:
    """Designate then certify, the pair PRD §3.2 requires before a coach may
    register a team or have a slot's enrollment verified."""
    coach = make_coach(api, school_id, **overrides)
    return certify_coach(api, coach, background_check_expires_on)


def make_student(api: Api, school_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 student enrolment, by the school's athletic director."""
    return data_of(
        api.create_student(
            F.student_payload(school_id, **overrides),
            make_athletic_director_headers(school_id),
        ),
        201,
    )


def make_title(api: Api, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3 title catalogue entry; LeagueAdmin only."""
    return data_of(
        api.create_title(F.title_payload(**overrides), league_admin_headers()), 201
    )


def make_season(api: Api, title_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4 season creation; LeagueAdmin only."""
    return data_of(
        api.create_season(F.season_payload(title_id, **overrides), league_admin_headers()),
        201,
    )


# --------------------------------------------------------------------------
# Tier 2 — approval pathway
# --------------------------------------------------------------------------
def request_title_approval(
    api: Api, district_id: str, title_id: str, school_id: str
) -> Dict[str, Any]:
    """PRD §3.3 approval request, made by the requesting school's director."""
    return data_of(
        api.create_title_approval(
            F.title_approval_payload(district_id, title_id, school_id),
            make_athletic_director_headers(school_id),
        ),
        201,
    )


def decide_title_approval(
    api: Api, approval: Dict[str, Any], action: str, **overrides: Any
) -> Dict[str, Any]:
    """PRD §3.3 district decision, by the DistrictAdmin named in the approval."""
    return data_of(
        api.decide_title_approval(
            approval["id"],
            F.approval_decision_payload(action, **overrides),
            make_district_admin_headers(approval["district_id"]),
        )
    )


def approve_title_for_district(
    api: Api, district_id: str, title_id: str, school_id: str
) -> Dict[str, Any]:
    """Request and approve in one step — the ``APPROVED`` approval PRD §3.6
    demands before a team of that district may register."""
    approval = request_title_approval(api, district_id, title_id, school_id)
    return decide_title_approval(api, approval, "APPROVE")


# --------------------------------------------------------------------------
# Tier 3 — teams and rosters
# --------------------------------------------------------------------------
def make_team(
    api: Api,
    season_id: str,
    school_id: str,
    title_id: str,
    coach_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5 team creation in ``DRAFT``, by the designated coach."""
    return data_of(
        api.create_team(
            F.team_payload(season_id, school_id, title_id, coach_id, **overrides),
            make_coach_headers(coach_id),
        ),
        201,
    )


def add_slot(
    api: Api,
    team_id: str,
    student_id: str,
    coach_id: str,
    slot_role: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.5 roster-slot creation; the coach's own act."""
    extra: Dict[str, Any] = {}
    if slot_role is not None:
        extra["slot_role"] = slot_role
    return data_of(
        api.create_roster_slot(
            F.roster_slot_payload(team_id, student_id, **extra),
            make_coach_headers(coach_id),
        ),
        201,
    )


def verify_slot_enrollment(
    api: Api,
    slot_id: str,
    verified_birthdate: str,
    officer_id: str = ELIGIBILITY_OFFICER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5 axis one — enrollment and age, by the eligibility desk."""
    return data_of(
        api.verify_enrollment(
            slot_id,
            F.verify_enrollment_payload(verified_birthdate, **overrides),
            eligibility_officer_headers(officer_id),
        )
    )


def verify_slot_academics(
    api: Api, slot_id: str, officer_id: str = ELIGIBILITY_OFFICER_ID_2
) -> Dict[str, Any]:
    """PRD §3.5 axis two — academics, by a **different** officer."""
    return data_of(
        api.verify_academics(slot_id, {}, eligibility_officer_headers(officer_id))
    )


def post_term(
    api: Api,
    student: Dict[str, Any],
    term_gpa: float,
    term_credits: float,
    term_label: str = "Fall 2026",
) -> Dict[str, Any]:
    """PRD §3.2 academic posting, carrying the §2.6 version guard."""
    return data_of(
        api.post_academic_term(
            student["id"],
            F.academic_posting_payload(
                student["version"],
                term_label=term_label,
                term_gpa=term_gpa,
                term_credits=term_credits,
            ),
            eligibility_officer_headers(),
        )
    )


def make_student_with_term(
    api: Api,
    school_id: str,
    term_gpa: float = 3.500,
    term_credits: float = 6.0,
    term_label: str = "Fall 2026",
    **overrides: Any,
) -> Dict[str, Any]:
    """A student who already has one posted term, which PRD §3.5 axis two
    requires (``latest_term_gpa`` must not be null)."""
    student = make_student(api, school_id, **overrides)
    return post_term(api, student, term_gpa, term_credits, term_label)


def fully_verify_slot(
    api: Api,
    slot_id: str,
    verified_birthdate: str,
    enrollment_officer_id: str = ELIGIBILITY_OFFICER_ID,
    academics_officer_id: str = ELIGIBILITY_OFFICER_ID_2,
) -> Dict[str, Any]:
    """Clear both axes with two distinct officers so PRD §3.5's derivation
    yields ``participation_status`` ``ACTIVE``."""
    verify_slot_enrollment(
        api, slot_id, verified_birthdate, officer_id=enrollment_officer_id
    )
    return verify_slot_academics(api, slot_id, officer_id=academics_officer_id)


def make_active_starter(
    api: Api,
    team_id: str,
    coach_id: str,
    student: Dict[str, Any],
    slot_role: Optional[str] = None,
) -> Dict[str, Any]:
    """Roster the student and clear both axes, producing an ACTIVE slot."""
    slot = add_slot(api, team_id, student["id"], coach_id, slot_role=slot_role)
    return fully_verify_slot(api, slot["id"], student["birthdate"])


# --------------------------------------------------------------------------
# Tier 4 — registration, lock, withdrawal, stage advancement
# --------------------------------------------------------------------------
def advance_season(api: Api, season_id: str, to_status: str) -> Dict[str, Any]:
    """PRD §3.4 single-step stage advance; LeagueAdmin only."""
    return data_of(
        api.advance_season(
            season_id, F.advance_payload(to_status), league_admin_headers()
        )
    )


def open_registration(api: Api, season_id: str) -> Dict[str, Any]:
    """DRAFT → REGISTRATION_OPEN (PRD §3.4)."""
    return advance_season(api, season_id, "REGISTRATION_OPEN")


def register_team(api: Api, team: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.6 registration — the coach's own act."""
    return data_of(
        api.register_team(team["id"], {}, make_coach_headers(team["coach_id"]))
    )


def lock_roster(api: Api, team: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.6 roster lock — REGISTERED → ROSTER_LOCKED, coach's own act."""
    return data_of(
        api.lock_roster(team["id"], {}, make_coach_headers(team["coach_id"]))
    )


def withdraw_team(
    api: Api, team: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    """PRD §3.6 withdrawal — the athletic director's prerogative."""
    return data_of(
        api.withdraw_team(
            team["id"], dict(overrides), make_athletic_director_headers(team["school_id"])
        )
    )


def run_seeding(
    api: Api, season_id: str, basis_override: Optional[str] = None
) -> Dict[str, Any]:
    """PRD §3.9 seeding run; LeagueAdmin only."""
    payload: Dict[str, Any] = {}
    if basis_override is not None:
        payload["basis_override"] = basis_override
    return data_of(api.run_seeding(season_id, payload, league_admin_headers()))


# --------------------------------------------------------------------------
# Tier 4 — matches
# --------------------------------------------------------------------------
def schedule_match(
    api: Api,
    season_id: str,
    home_team_id: str,
    away_team_id: str,
    scheduled_start_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7 match scheduling; LeagueAdmin only."""
    return data_of(
        api.create_match(
            F.match_payload(
                season_id,
                home_team_id,
                away_team_id,
                scheduled_start_at,
                **overrides,
            ),
            league_admin_headers(),
        ),
        201,
    )


def configure_server(api: Api, match_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7 server configuration — SCHEDULED → SERVER_READY."""
    return data_of(
        api.configure_server(
            match_id, F.server_config_payload(**overrides), league_admin_headers()
        )
    )


def report_result(
    api: Api,
    match: Dict[str, Any],
    reporting_team: Dict[str, Any],
    home_games_won: int,
    away_games_won: int,
) -> Dict[str, Any]:
    """PRD §3.7 result report, carrying the §2.6 ``expected_match_version``."""
    return data_of(
        api.report_result(
            match["id"],
            F.result_report_payload(
                reporting_team["id"],
                home_games_won,
                away_games_won,
                match["version"],
            ),
            make_coach_headers(reporting_team["coach_id"]),
        )
    )


def confirm_result(
    api: Api,
    match: Dict[str, Any],
    home_team: Dict[str, Any],
    away_team: Dict[str, Any],
    home_games_won: int,
    away_games_won: int,
) -> Dict[str, Any]:
    """Both sides report the same pair, which PRD §3.7 confirms."""
    after_home = report_result(api, match, home_team, home_games_won, away_games_won)
    return report_result(api, after_home, away_team, home_games_won, away_games_won)


def finalize_match(
    api: Api, match_id: str, **overrides: Any
) -> Dict[str, Any]:
    """PRD §3.7 finalization; LeagueAdmin only."""
    return data_of(
        api.finalize_match(match_id, dict(overrides), league_admin_headers())
    )


def forfeit_match(
    api: Api, match_id: str, forfeiting_team_id: str, **overrides: Any
) -> Dict[str, Any]:
    """PRD §3.7 direct league-office forfeit charge."""
    return data_of(
        api.forfeit_match(
            match_id,
            F.forfeit_payload(forfeiting_team_id, **overrides),
            league_admin_headers(),
        )
    )


def file_dispute(
    api: Api,
    match_id: str,
    filing_team: Dict[str, Any],
    dispute_reason_code: str = "SCORE_MISMATCH",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7 dispute filing by a participating coach."""
    return data_of(
        api.file_dispute(
            match_id,
            F.dispute_payload(filing_team["id"], dispute_reason_code, **overrides),
            make_coach_headers(filing_team["coach_id"]),
        )
    )


def dispute_action(api: Api, match_id: str, action: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7 league action on an open dispute."""
    return data_of(
        api.dispute_action(
            match_id,
            F.dispute_action_payload(action, **overrides),
            league_admin_headers(),
        )
    )


def register_broadcast(
    api: Api,
    match_id: str,
    coach_id: str,
    broadcast_school_id: str,
    broadcast_start_at: str,
    broadcast_end_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8 broadcast REGISTER, claimed by a participating coach."""
    return data_of(
        api.broadcast_action(
            match_id,
            F.broadcast_register_payload(
                broadcast_school_id,
                broadcast_start_at,
                broadcast_end_at,
                **overrides,
            ),
            make_coach_headers(coach_id),
        )
    )


def broadcast_action(
    api: Api, match_id: str, coach_id: str, action: str, **overrides: Any
) -> Dict[str, Any]:
    """PRD §3.8 GO_LIVE / RESUME / END, which must omit the three register
    fields."""
    return data_of(
        api.broadcast_action(
            match_id,
            F.broadcast_action_payload(action, **overrides),
            make_coach_headers(coach_id),
        )
    )


# --------------------------------------------------------------------------
# Tier 4 — fair-play cases
# --------------------------------------------------------------------------
def open_student_case(
    api: Api, team_id: str, student_id: str, **overrides: Any
) -> Dict[str, Any]:
    """PRD §3.8 STUDENT-subject case, opened by an integrity officer."""
    return data_of(
        api.create_fair_play_case(
            F.student_case_payload(team_id, student_id, **overrides),
            integrity_officer_headers(),
        ),
        201,
    )


def open_broadcast_case(
    api: Api, team_id: str, match_id: str, **overrides: Any
) -> Dict[str, Any]:
    """PRD §3.8 MATCH_BROADCAST-subject case."""
    return data_of(
        api.create_fair_play_case(
            F.broadcast_case_payload(team_id, match_id, **overrides),
            integrity_officer_headers(),
        ),
        201,
    )


def investigate_case(
    api: Api, case_id: str, officer_id: str = INTEGRITY_OFFICER_ID
) -> Dict[str, Any]:
    """PRD §3.8 REPORTED → INVESTIGATING."""
    return data_of(
        api.investigate_case(case_id, {}, integrity_officer_headers(officer_id))
    )


def decide_case(
    api: Api,
    case_id: str,
    decision: str = "SUSTAIN",
    severity: Optional[str] = "MINOR",
    officer_id: str = INTEGRITY_OFFICER_ID_2,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8 SUSTAIN / DISMISS.  A SUSTAIN carries ``severity``; a DISMISS
    must omit it."""
    payload: Dict[str, Any] = {"decision": decision}
    if decision == "SUSTAIN":
        payload["severity"] = severity
    payload.update(overrides)
    return data_of(
        api.decide_case(case_id, payload, integrity_officer_headers(officer_id))
    )


def sustain_case(
    api: Api,
    team_id: str,
    student_id: str,
    severity: str = "MINOR",
    case_type: str = "ACCOUNT_SHARING",
    investigator_id: str = INTEGRITY_OFFICER_ID,
    decider_id: str = INTEGRITY_OFFICER_ID_2,
) -> Dict[str, Any]:
    """Open, take and sustain one STUDENT case in a single step."""
    case = open_student_case(api, team_id, student_id, case_type=case_type)
    investigate_case(api, case["id"], officer_id=investigator_id)
    return decide_case(
        api,
        case["id"],
        decision="SUSTAIN",
        severity=severity,
        officer_id=decider_id,
    )


def appeal_case(
    api: Api, case: Dict[str, Any], coach_id: str, **overrides: Any
) -> Dict[str, Any]:
    """PRD §3.8 SUSTAINED → APPEALED, by the charged team's coach."""
    return data_of(
        api.appeal_case(
            case["id"], F.appeal_payload(**overrides), make_coach_headers(coach_id)
        )
    )


def decide_appeal(
    api: Api,
    case_id: str,
    decision: str,
    officer_id: str = INTEGRITY_OFFICER_ID_3,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8 AFFIRM / OVERTURN, by an officer independent of both the
    investigator and the decider."""
    return data_of(
        api.decide_appeal(
            case_id,
            F.appeal_decision_payload(decision, **overrides),
            integrity_officer_headers(officer_id),
        )
    )


# --------------------------------------------------------------------------
# Readers — every role in §4's read lists may read, so LeagueAdmin is used
# --------------------------------------------------------------------------
def get_district(api: Api, district_id: str) -> Dict[str, Any]:
    return data_of(api.get_district(district_id, league_admin_headers()))


def get_school(api: Api, school_id: str) -> Dict[str, Any]:
    return data_of(api.get_school(school_id, league_admin_headers()))


def get_coach(api: Api, coach_id: str) -> Dict[str, Any]:
    return data_of(api.get_coach(coach_id, league_admin_headers()))


def get_student(api: Api, student_id: str) -> Dict[str, Any]:
    return data_of(api.get_student(student_id, league_admin_headers()))


def get_title(api: Api, title_id: str) -> Dict[str, Any]:
    return data_of(api.get_title(title_id, league_admin_headers()))


def get_title_approval(api: Api, approval_id: str) -> Dict[str, Any]:
    return data_of(api.get_title_approval(approval_id, league_admin_headers()))


def get_season(api: Api, season_id: str) -> Dict[str, Any]:
    return data_of(api.get_season(season_id, league_admin_headers()))


def get_team(api: Api, team_id: str) -> Dict[str, Any]:
    return data_of(api.get_team(team_id, league_admin_headers()))


def get_slot(api: Api, slot_id: str) -> Dict[str, Any]:
    return data_of(api.get_roster_slot(slot_id, league_admin_headers()))


def get_match(api: Api, match_id: str) -> Dict[str, Any]:
    return data_of(api.get_match(match_id, league_admin_headers()))


def get_case(api: Api, case_id: str) -> Dict[str, Any]:
    return data_of(api.get_fair_play_case(case_id, league_admin_headers()))


# --------------------------------------------------------------------------
# Tier 5 — whole-scenario builders
# --------------------------------------------------------------------------
def build_draft_team(
    api: Api,
    district_kwargs: Optional[Dict[str, Any]] = None,
    school_kwargs: Optional[Dict[str, Any]] = None,
    title_kwargs: Optional[Dict[str, Any]] = None,
    season_kwargs: Optional[Dict[str, Any]] = None,
    coach_kwargs: Optional[Dict[str, Any]] = None,
    student_kwargs: Optional[Dict[str, Any]] = None,
    term_gpa: float = 3.500,
    term_credits: float = 6.0,
    approve_title: bool = True,
    open_registration_stage: bool = True,
) -> Dict[str, Any]:
    """District → school → certified coach → student-with-term → title →
    approval → season → DRAFT team, the chain PRD §3.1–§3.5 prescribes."""
    district = make_district(api, **(district_kwargs or {}))
    school = make_school(api, district["id"], **(school_kwargs or {}))
    coach = make_certified_coach(api, school["id"], **(coach_kwargs or {}))
    student = make_student_with_term(
        api,
        school["id"],
        term_gpa=term_gpa,
        term_credits=term_credits,
        **(student_kwargs or {}),
    )
    title = make_title(api, **(title_kwargs or {}))
    approval = None
    if approve_title:
        approval = approve_title_for_district(
            api, district["id"], title["id"], school["id"]
        )
    season = make_season(api, title["id"], **(season_kwargs or {}))
    if open_registration_stage:
        season = open_registration(api, season["id"])
    team = make_team(api, season["id"], school["id"], title["id"], coach["id"])
    return {
        "district": district,
        "school": school,
        "coach": coach,
        "student": student,
        "title": title,
        "approval": approval,
        "season": season,
        "team": team,
    }


def build_registered_team(
    api: Api, slot_role: Optional[str] = None, **kwargs: Any
) -> Dict[str, Any]:
    """A DRAFT team carrying one ACTIVE starter, then registered per §3.6."""
    world = build_draft_team(api, **kwargs)
    world["slot"] = make_active_starter(
        api,
        world["team"]["id"],
        world["coach"]["id"],
        world["student"],
        slot_role=slot_role,
    )
    world["team"] = register_team(api, world["team"])
    world["district"] = get_district(api, world["district"]["id"])
    world["student"] = get_student(api, world["student"]["id"])
    return world


def build_two_team_season(
    api: Api,
    district_kwargs: Optional[Dict[str, Any]] = None,
    title_kwargs: Optional[Dict[str, Any]] = None,
    season_kwargs: Optional[Dict[str, Any]] = None,
    advance_to_regular_season: bool = True,
) -> Dict[str, Any]:
    """Two schools of one district each field one registered, roster-locked
    team, and the season is walked to ``REGULAR_SEASON`` (PRD §3.4), which
    cascades both teams to ``COMPETING``."""
    district = make_district(api, **(district_kwargs or {}))
    title = make_title(api, **(title_kwargs or {}))
    season = make_season(api, title["id"], **(season_kwargs or {}))

    school_a = make_school(api, district["id"])
    coach_a = make_certified_coach(api, school_a["id"])
    student_a = make_student_with_term(api, school_a["id"])

    school_b = make_school(api, district["id"])
    coach_b = make_certified_coach(api, school_b["id"])
    student_b = make_student_with_term(api, school_b["id"])

    approval = approve_title_for_district(
        api, district["id"], title["id"], school_a["id"]
    )
    season = open_registration(api, season["id"])

    team_a = make_team(api, season["id"], school_a["id"], title["id"], coach_a["id"])
    team_b = make_team(api, season["id"], school_b["id"], title["id"], coach_b["id"])

    slot_a = make_active_starter(api, team_a["id"], coach_a["id"], student_a)
    slot_b = make_active_starter(api, team_b["id"], coach_b["id"], student_b)

    team_a = register_team(api, team_a)
    team_b = register_team(api, team_b)
    team_a = lock_roster(api, team_a)
    team_b = lock_roster(api, team_b)

    if advance_to_regular_season:
        season = advance_season(api, season["id"], "ROSTER_LOCKED")
        season = advance_season(api, season["id"], "REGULAR_SEASON")
        team_a = get_team(api, team_a["id"])
        team_b = get_team(api, team_b["id"])

    return {
        "district": get_district(api, district["id"]),
        "title": title,
        "season": season,
        "approval": approval,
        "school_a": school_a,
        "coach_a": coach_a,
        "student_a": get_student(api, student_a["id"]),
        "slot_a": get_slot(api, slot_a["id"]),
        "team_a": team_a,
        "school_b": school_b,
        "coach_b": coach_b,
        "student_b": get_student(api, student_b["id"]),
        "slot_b": get_slot(api, slot_b["id"]),
        "team_b": team_b,
    }


def build_ready_match(
    api: Api,
    scheduled_start_at: str = "2026-10-01T12:00:00.000Z",
    **kwargs: Any,
) -> Dict[str, Any]:
    """A two-team season with one match already in ``SERVER_READY``, the
    from-state PRD §3.7 requires before either coach may report."""
    world = build_two_team_season(api, **kwargs)
    match = schedule_match(
        api,
        world["season"]["id"],
        world["team_a"]["id"],
        world["team_b"]["id"],
        scheduled_start_at,
    )
    world["match"] = configure_server(api, match["id"])
    return world


def build_confirmed_match(
    api: Api,
    home_games_won: int = 2,
    away_games_won: int = 1,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A match whose two reports agree, so §3.7 confirms it, pins the winner
    and computes ``dispute_deadline_at``."""
    world = build_ready_match(api, **kwargs)
    world["match"] = confirm_result(
        api,
        world["match"],
        world["team_a"],
        world["team_b"],
        home_games_won,
        away_games_won,
    )
    world["team_a"] = get_team(api, world["team_a"]["id"])
    world["team_b"] = get_team(api, world["team_b"]["id"])
    world["season"] = get_season(api, world["season"]["id"])
    return world
