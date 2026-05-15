"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce
clear "setup failed" errors rather than confusing assertion failures.

Identity threading rule (PRD §2.1): after creating a Family, every
FamilyUser-owned call MUST use make_family_user_headers(family['id']);
after creating a District, every DistrictAdmin-owned call MUST use
make_district_admin_headers(district['id']). The shared fallback
constants in TEST_USERS are reserved for tests that do NOT exercise
ownership.

Fixture tier overview:
- Tier 1 — primitive entity creation with ownership-correct headers.
- Tier 2 — entity hierarchies (district + school + program; family +
  student).
- Tier 3 — full lifecycle shortcuts (open window, draw lottery, take
  the application all the way to OFFERED / ACCEPTED / WITHDRAWN).
- Tier 4 — boundary / accumulation targeting (right at the poverty
  decile boundary, right at the seats_total boundary, etc.).
- Tier 5 — terminal-state / lockdown scenarios (post-grace, post-final
  draw, capacity-exhausted district).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULT_BASE_CLOCK,
    advance_clock_payload,
    create_application_payload,
    create_district_payload,
    create_family_payload,
    create_program_payload,
    create_school_payload,
    create_student_payload,
    create_transfer_request_payload,
    iso_offset,
    iso_utc,
    utc,
)
from .test_users import (
    TEST_USERS,
    make_district_admin_headers,
    make_family_user_headers,
)


SYSTEM_OPERATOR = TEST_USERS["system_operator_headers"]


# ===========================================================================
# Time helpers
# ===========================================================================
def advance_clock_to(target_dt: datetime) -> Dict[str, Any]:
    """Advance the simulated clock (PRD §2.10 SystemOperator-only) and
    return the new Clock state."""
    res = api_client.advance_clock(iso_utc(target_dt), SYSTEM_OPERATOR)
    return get_success_data(res)


def advance_clock_iso(target_iso: str) -> Dict[str, Any]:
    res = api_client.advance_clock(target_iso, SYSTEM_OPERATOR)
    return get_success_data(res)


# ===========================================================================
# Tier 1: primitive entity creation
# ===========================================================================
def create_district(
    name: Optional[str] = None,
    state_code: str = "CA",
    accepts_inter_district_transfers: bool = False,
    poverty_index_threshold: float = 0.50,
) -> Dict[str, Any]:
    """Create a District using SystemOperator (PRD §3.1)."""
    payload = create_district_payload(
        state_code=state_code,
        accepts_inter_district_transfers=accepts_inter_district_transfers,
        poverty_index_threshold=poverty_index_threshold,
    )
    if name is not None:
        payload["name"] = name
    res = api_client.create_district(payload, SYSTEM_OPERATOR)
    return get_success_data(res)


def create_school(
    district: Dict[str, Any],
    school_type: str = "NEIGHBORHOOD",
    grade_levels_offered: Optional[List[int]] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a School under district. Per PRD §3.1 DistrictAdmin's
    X-User-ID must equal district.id."""
    payload = create_school_payload(
        district_id=district["id"],
        school_type=school_type,
        grade_levels_offered=grade_levels_offered or [5],
    )
    if name is not None:
        payload["name"] = name
    headers = make_district_admin_headers(district["id"])
    res = api_client.create_school(payload, headers)
    return get_success_data(res)


def create_program(
    district: Dict[str, Any],
    school: Dict[str, Any],
    grade_level: int = 5,
    academic_year: int = 2026,
    seats_total: int = 1,
    registration_open_at: Optional[str] = None,
    registration_close_at: Optional[str] = None,
    lottery_seed: Optional[str] = "seed-test",
) -> Dict[str, Any]:
    """Create a Program under school owned by district (PRD §3.1)."""
    payload = create_program_payload(
        school_id=school["id"],
        grade_level=grade_level,
        academic_year=academic_year,
        seats_total=seats_total,
        registration_open_at=registration_open_at,
        registration_close_at=registration_close_at,
        lottery_seed=lottery_seed,
    )
    headers = make_district_admin_headers(district["id"])
    res = api_client.create_program(payload, headers)
    return get_success_data(res)


def create_family(
    residency_district: Dict[str, Any],
    poverty_index_score: float = 0.10,
) -> Dict[str, Any]:
    """Create a Family via FamilyUser (or SystemOperator). PRD §3.2.
    Note: PRD allows both FamilyUser and SystemOperator on POST
    /enrollment/families; we use SystemOperator here because the family
    does not yet have an id, so a FamilyUser X-User-ID can't be
    ownership-bound."""
    payload = create_family_payload(
        residency_district_id=residency_district["id"],
        poverty_index_score=poverty_index_score,
    )
    res = api_client.create_family(payload, SYSTEM_OPERATOR)
    return get_success_data(res)


def create_student(
    family: Dict[str, Any],
    grade_level_next_year: int = 5,
    has_iep: bool = False,
) -> Dict[str, Any]:
    """Create a Student under family using ownership-correct headers."""
    payload = create_student_payload(
        family_id=family["id"],
        grade_level_next_year=grade_level_next_year,
        has_iep=has_iep,
    )
    headers = make_family_user_headers(family["id"])
    res = api_client.create_student(payload, headers)
    return get_success_data(res)


def create_application(
    family: Dict[str, Any],
    student: Dict[str, Any],
    program: Dict[str, Any],
    choice_rank: int = 1,
) -> Dict[str, Any]:
    """Create a DRAFT Application using FamilyUser ownership headers
    (PRD §3.4 / §2.1)."""
    payload = create_application_payload(
        student_id=student["id"],
        program_id=program["id"],
        choice_rank=choice_rank,
    )
    headers = make_family_user_headers(family["id"])
    res = api_client.create_application(payload, headers)
    return get_success_data(res)


def create_transfer_request(
    family: Dict[str, Any],
    application: Dict[str, Any],
    target_district: Dict[str, Any],
) -> Dict[str, Any]:
    payload = create_transfer_request_payload(
        application_id=application["id"],
        target_district_id=target_district["id"],
    )
    headers = make_family_user_headers(family["id"])
    res = api_client.create_transfer_request(payload, headers)
    return get_success_data(res)


def approve_transfer_request(
    target_district: Dict[str, Any],
    transfer_request: Dict[str, Any],
) -> Dict[str, Any]:
    headers = make_district_admin_headers(target_district["id"])
    res = api_client.approve_transfer_request(transfer_request["id"], headers)
    return get_success_data(res)


def deny_transfer_request(
    target_district: Dict[str, Any],
    transfer_request: Dict[str, Any],
) -> Dict[str, Any]:
    headers = make_district_admin_headers(target_district["id"])
    res = api_client.deny_transfer_request(transfer_request["id"], headers)
    return get_success_data(res)


def revoke_transfer_request(
    target_district: Dict[str, Any],
    transfer_request: Dict[str, Any],
) -> Dict[str, Any]:
    headers = make_district_admin_headers(target_district["id"])
    res = api_client.revoke_transfer_request(transfer_request["id"], headers)
    return get_success_data(res)


def submit_application(
    family: Dict[str, Any],
    application: Dict[str, Any],
) -> Dict[str, Any]:
    headers = make_family_user_headers(family["id"])
    res = api_client.submit_application(application["id"], headers)
    return get_success_data(res)


def accept_application(
    family: Dict[str, Any],
    application: Dict[str, Any],
) -> Dict[str, Any]:
    headers = make_family_user_headers(family["id"])
    res = api_client.accept_application(application["id"], headers)
    return get_success_data(res)


def decline_application(
    family: Dict[str, Any],
    application: Dict[str, Any],
) -> Dict[str, Any]:
    headers = make_family_user_headers(family["id"])
    res = api_client.decline_application(application["id"], headers)
    return get_success_data(res)


def withdraw_application(
    family: Dict[str, Any],
    application: Dict[str, Any],
) -> Dict[str, Any]:
    headers = make_family_user_headers(family["id"])
    res = api_client.withdraw_application(application["id"], headers)
    return get_success_data(res)


def draw_lottery(
    district: Dict[str, Any],
    program: Dict[str, Any],
) -> Dict[str, Any]:
    headers = make_district_admin_headers(district["id"])
    res = api_client.draw_lottery(program["id"], headers)
    return get_success_data(res)


def get_program(program_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_program(program_id, SYSTEM_OPERATOR))


def get_family(family_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_family(family_id, SYSTEM_OPERATOR))


def get_application(application_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_application(application_id, SYSTEM_OPERATOR))


def get_transfer_request_via_list(application_id: str) -> Optional[Dict[str, Any]]:
    res = api_client.list_transfer_requests(
        SYSTEM_OPERATOR, params={"application_id": application_id},
    )
    data = get_success_data(res)
    rows = data if isinstance(data, list) else data.get("items", [])
    return rows[0] if rows else None


# ===========================================================================
# Tier 2: entity hierarchies
# ===========================================================================
def setup_district_with_school_and_program(
    *,
    grade_level: int = 5,
    school_type: str = "NEIGHBORHOOD",
    accepts_inter_district_transfers: bool = False,
    poverty_index_threshold: float = 0.50,
    seats_total: int = 1,
    open_offset_days: int = 1,
    close_offset_days: int = 30,
    seed: str = "seed-test",
    base_clock: Optional[datetime] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Anchor clock, create District + School + Program with a known
    registration window. Returns (district, school, program)."""
    base = base_clock or DEFAULT_BASE_CLOCK
    advance_clock_to(base)
    district = create_district(
        accepts_inter_district_transfers=accepts_inter_district_transfers,
        poverty_index_threshold=poverty_index_threshold,
    )
    school = create_school(
        district,
        school_type=school_type,
        grade_levels_offered=[grade_level],
    )
    program = create_program(
        district, school,
        grade_level=grade_level,
        seats_total=seats_total,
        registration_open_at=iso_utc(base + timedelta(days=open_offset_days)),
        registration_close_at=iso_utc(base + timedelta(days=close_offset_days)),
        lottery_seed=seed,
    )
    return district, school, program


def setup_family_with_student(
    district: Dict[str, Any],
    *,
    poverty_index_score: float = 0.10,
    grade_level_next_year: int = 5,
    has_iep: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    family = create_family(
        residency_district=district, poverty_index_score=poverty_index_score,
    )
    student = create_student(
        family, grade_level_next_year=grade_level_next_year, has_iep=has_iep,
    )
    return family, student


# ===========================================================================
# Tier 3: full lifecycle shortcuts
# ===========================================================================
def open_program_window(
    program: Dict[str, Any],
    base_clock: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Advance the simulated clock just past program.registration_open_at
    so that window_status flips to OPEN (PRD §2.10 / state machine
    SCHEDULED -> OPEN)."""
    target_iso = program["registration_open_at"]
    # Advance to exactly the open instant — left-inclusive per PRD §3.5
    # half-open registration window.
    advance_clock_iso(target_iso)
    return get_program(program["id"])


def close_program_window(program: Dict[str, Any]) -> Dict[str, Any]:
    """Advance the simulated clock to program.registration_close_at so
    that window_status flips to CLOSED."""
    advance_clock_iso(program["registration_close_at"])
    return get_program(program["id"])


def submit_via_window(
    family: Dict[str, Any],
    application: Dict[str, Any],
    program: Dict[str, Any],
) -> Dict[str, Any]:
    """Open the program window (if not yet OPEN), submit, return the
    refreshed application."""
    prog = get_program(program["id"])
    if prog["window_status"] == "SCHEDULED":
        open_program_window(program)
    submitted = submit_application(family, application)
    return submitted


def setup_open_program_with_one_application(
    *,
    grade_level: int = 5,
    school_type: str = "NEIGHBORHOOD",
    poverty_index_score: float = 0.10,
    poverty_index_threshold: float = 0.50,
    seats_total: int = 1,
    choice_rank: int = 1,
    seed: str = "seed-test",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """End-to-end through SUBMITTED for a single applicant.
    Returns (district, school, program, family, student, application)
    where application.status == SUBMITTED."""
    district, school, program = setup_district_with_school_and_program(
        grade_level=grade_level,
        school_type=school_type,
        poverty_index_threshold=poverty_index_threshold,
        seats_total=seats_total,
        seed=seed,
    )
    family, student = setup_family_with_student(
        district,
        poverty_index_score=poverty_index_score,
        grade_level_next_year=grade_level,
    )
    app = create_application(family, student, program, choice_rank=choice_rank)
    open_program_window(program)
    app = submit_application(family, app)
    return district, school, program, family, student, app


def setup_drawn_program_with_single_offer(
    *,
    grade_level: int = 5,
    school_type: str = "NEIGHBORHOOD",
    poverty_index_score: float = 0.10,
    poverty_index_threshold: float = 0.50,
    seats_total: int = 1,
    choice_rank: int = 1,
    seed: str = "seed-test",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Single submitted applicant, draw lottery, applicant ends up in
    OFFERED. Returns (district, school, program, family, student,
    application, lottery_run)."""
    district, school, program, family, student, app = setup_open_program_with_one_application(
        grade_level=grade_level,
        school_type=school_type,
        poverty_index_score=poverty_index_score,
        poverty_index_threshold=poverty_index_threshold,
        seats_total=seats_total,
        choice_rank=choice_rank,
        seed=seed,
    )
    close_program_window(program)
    lottery_run = draw_lottery(district, program)
    app = get_application(app["id"])
    return district, school, program, family, student, app, lottery_run


def setup_drawn_program_with_offer_and_one_waitlisted(
    *,
    seed: str = "seed-multi",
    grade_level: int = 5,
    school_type: str = "NEIGHBORHOOD",
    poverty_index_threshold: float = 0.50,
) -> Dict[str, Any]:
    """Seats_total=1; TWO equally-classified applicants compete; one
    wins OFFERED, the other becomes WAITLISTED at position 1. Returns
    a dict with district, school, program, family_a/student_a/app_a,
    family_b/student_b/app_b, lottery_run, plus 'winner' / 'loser'
    fields pointing at the actual rows."""
    district, school, program = setup_district_with_school_and_program(
        grade_level=grade_level,
        school_type=school_type,
        poverty_index_threshold=poverty_index_threshold,
        seats_total=1,
        seed=seed,
    )
    family_a, student_a = setup_family_with_student(
        district, poverty_index_score=0.10, grade_level_next_year=grade_level,
    )
    family_b, student_b = setup_family_with_student(
        district, poverty_index_score=0.10, grade_level_next_year=grade_level,
    )
    app_a = create_application(family_a, student_a, program, choice_rank=1)
    app_b = create_application(family_b, student_b, program, choice_rank=1)
    open_program_window(program)
    app_a = submit_application(family_a, app_a)
    app_b = submit_application(family_b, app_b)
    close_program_window(program)
    lottery_run = draw_lottery(district, program)
    app_a = get_application(app_a["id"])
    app_b = get_application(app_b["id"])
    if app_a["status"] == "OFFERED":
        winner_family, winner = family_a, app_a
        loser_family, loser = family_b, app_b
    else:
        winner_family, winner = family_b, app_b
        loser_family, loser = family_a, app_a
    assert winner["status"] == "OFFERED", "fixture invariant: one applicant must be OFFERED"
    assert loser["status"] == "WAITLISTED", "fixture invariant: one applicant must be WAITLISTED"
    return {
        "district": district,
        "school": school,
        "program": program,
        "family_a": family_a, "student_a": student_a, "app_a": app_a,
        "family_b": family_b, "student_b": student_b, "app_b": app_b,
        "winner_family": winner_family, "winner": winner,
        "loser_family": loser_family, "loser": loser,
        "lottery_run": lottery_run,
    }


def setup_accepted_application_with_anchor(
    *,
    seed: str = "anchor-seed",
    grade_level: int = 5,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """One family, one student, accepted on a program — Family
    head_household_application_id is now set. Returns (district,
    school, program, family, student, accepted_app)."""
    district, school, program, family, student, app, _run = setup_drawn_program_with_single_offer(
        grade_level=grade_level, seed=seed,
    )
    app = accept_application(family, app)
    return district, school, program, family, student, app


# ===========================================================================
# Tier 4: boundary-targeting fixtures
# ===========================================================================
def setup_family_at_threshold_exactly(
    *, threshold: float = 0.50,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """District threshold=0.50, Family poverty_index_score==threshold.
    Used to test PRD §3.4 strict-greater inequality: at exact equality
    the family does NOT receive the disadvantaged boost.
    Returns (district, school, program, family, student, draft_app)."""
    district, school, program = setup_district_with_school_and_program(
        poverty_index_threshold=threshold,
        seats_total=2,
        seed="boundary-seed",
    )
    family, student = setup_family_with_student(
        district, poverty_index_score=threshold,
    )
    app = create_application(family, student, program, choice_rank=1)
    return district, school, program, family, student, app


def setup_two_families_threshold_pair(
    *,
    threshold: float = 0.50,
    below_or_equal: float = 0.50,
    above: float = 0.60,
) -> Dict[str, Any]:
    """Two families on the same NEIGHBORHOOD program: one at the
    threshold exactly (no boost), one one decile above (1.1
    multiplier). Returns dict with district/school/program plus two
    (family, student, app) bundles labeled boundary_/above_."""
    district, school, program = setup_district_with_school_and_program(
        poverty_index_threshold=threshold,
        seats_total=2,
        seed="dual-pov",
    )
    f_boundary, s_boundary = setup_family_with_student(
        district, poverty_index_score=below_or_equal,
    )
    f_above, s_above = setup_family_with_student(
        district, poverty_index_score=above,
    )
    a_boundary = create_application(f_boundary, s_boundary, program, choice_rank=1)
    a_above = create_application(f_above, s_above, program, choice_rank=1)
    open_program_window(program)
    a_boundary = submit_application(f_boundary, a_boundary)
    a_above = submit_application(f_above, a_above)
    return {
        "district": district, "school": school, "program": program,
        "boundary_family": f_boundary, "boundary_student": s_boundary,
        "boundary_app": a_boundary,
        "above_family": f_above, "above_student": s_above, "above_app": a_above,
    }


# ===========================================================================
# Tier 5: terminal-state and lockdown scenarios
# ===========================================================================
def setup_cross_district_setup(
    *,
    target_accepts_transfers: bool = True,
    target_school_type: str = "MAGNET",
    target_seats_total: int = 2,
    grade_level: int = 5,
) -> Dict[str, Any]:
    """Two districts: residency district D_home (does not accept) and
    target district D_target with a MAGNET program. Returns dict with
    home_district, target_district, target_school, target_program,
    plus a family residing in home_district."""
    advance_clock_to(DEFAULT_BASE_CLOCK)
    home = create_district(accepts_inter_district_transfers=False)
    target = create_district(accepts_inter_district_transfers=target_accepts_transfers)
    target_school = create_school(
        target,
        school_type=target_school_type,
        grade_levels_offered=[grade_level],
    )
    target_program = create_program(
        target, target_school,
        grade_level=grade_level,
        seats_total=target_seats_total,
        registration_open_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=1)),
        registration_close_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=30)),
        lottery_seed="cross-seed",
    )
    family, student = setup_family_with_student(
        home, poverty_index_score=0.10, grade_level_next_year=grade_level,
    )
    return {
        "home_district": home,
        "target_district": target,
        "target_school": target_school,
        "target_program": target_program,
        "family": family,
        "student": student,
    }


def make_cross_district_application_with_approved_transfer(
    *,
    target_accepts_transfers: bool = True,
    target_school_type: str = "MAGNET",
    target_seats_total: int = 2,
    grade_level: int = 5,
    choice_rank: int = 1,
) -> Dict[str, Any]:
    bundle = setup_cross_district_setup(
        target_accepts_transfers=target_accepts_transfers,
        target_school_type=target_school_type,
        target_seats_total=target_seats_total,
        grade_level=grade_level,
    )
    app = create_application(
        bundle["family"], bundle["student"], bundle["target_program"],
        choice_rank=choice_rank,
    )
    tr = create_transfer_request(
        bundle["family"], app, bundle["target_district"],
    )
    tr = approve_transfer_request(bundle["target_district"], tr)
    bundle["application"] = app
    bundle["transfer_request"] = tr
    return bundle


def setup_post_grace_accepted_application() -> Dict[str, Any]:
    """Accept an application, then advance the clock past
    drawn_at + 14 days so withdraw becomes grace-blocked (PRD §3.6)."""
    district, school, program, family, student, accepted = setup_accepted_application_with_anchor(
        seed="grace-seed",
    )
    # Advance well past drawn_at + 14 days.
    far_future = DEFAULT_BASE_CLOCK + timedelta(days=60)
    advance_clock_to(far_future)
    accepted = get_application(accepted["id"])
    return {
        "district": district, "school": school, "program": program,
        "family": family, "student": student, "application": accepted,
    }


__all__ = [
    "SYSTEM_OPERATOR",
    "advance_clock_to",
    "advance_clock_iso",
    "create_district",
    "create_school",
    "create_program",
    "create_family",
    "create_student",
    "create_application",
    "create_transfer_request",
    "approve_transfer_request",
    "deny_transfer_request",
    "revoke_transfer_request",
    "submit_application",
    "accept_application",
    "decline_application",
    "withdraw_application",
    "draw_lottery",
    "get_program",
    "get_family",
    "get_application",
    "get_transfer_request_via_list",
    "setup_district_with_school_and_program",
    "setup_family_with_student",
    "open_program_window",
    "close_program_window",
    "submit_via_window",
    "setup_open_program_with_one_application",
    "setup_drawn_program_with_single_offer",
    "setup_drawn_program_with_offer_and_one_waitlisted",
    "setup_accepted_application_with_anchor",
    "setup_family_at_threshold_exactly",
    "setup_two_families_threshold_pair",
    "setup_cross_district_setup",
    "make_cross_district_application_with_approved_transfer",
    "setup_post_grace_accepted_application",
]
