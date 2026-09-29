"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because each test starts against an empty database. Setup
calls use the lenient validator so a broken precondition surfaces as a
clear setup failure rather than a confusing assertion error.

Identity threading: after a teaching artist or school partner exists, any
ownership-gated call uses make_teaching_artist_headers(artist["id"]) or
make_school_liaison_headers(school["id"]) — never the shared constant.
"""
from typing import Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_arts_standard_payload,
    create_calendar_blackout_payload,
    create_cancel_payload,
    create_certify_payload,
    create_confirm_payload,
    create_deliver_payload,
    create_funder_report_payload,
    create_lead_artist_payload,
    create_lesson_plan_payload,
    create_lesson_plan_review_payload,
    create_observation_rubric_payload,
    create_payment_voucher_payload,
    create_portfolio_review_payload,
    create_reassign_payload,
    create_residency_payload,
    create_residency_status_payload,
    create_school_partner_payload,
    create_screening_payload,
    create_session_payload,
    create_teaching_artist_payload,
    create_vetting_payload,
    create_voucher_review_payload,
)
from .test_users import (
    CURRICULUM_SPECIALIST_USER_ID,
    DEMO_EVALUATOR_USER_ID,
    FISCAL_OFFICER_USER_ID,
    OBSERVER_USER_ID,
    PANELIST_1_USER_ID,
    PANELIST_2_USER_ID,
    PROGRAM_DIRECTOR_USER_ID,
    TEST_USERS,
    make_school_liaison_headers,
    make_teaching_artist_headers,
)

PD = TEST_USERS["program_director_headers"]
RC = TEST_USERS["roster_coordinator_headers"]
CS = TEST_USERS["curriculum_specialist_headers"]
FO = TEST_USERS["fiscal_officer_headers"]


# ==========================================================================
# Logical clock
# ==========================================================================
def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock. ProgramDirector capability."""
    return get_success_data(api_client.set_clock(to_iso8601, PD))


def set_clock_to_default() -> dict:
    """Pin the clock at the value it reads before any client sets it."""
    return set_clock("2026-08-01T00:00:00Z")


# ==========================================================================
# Tier 1 — State progression
# ==========================================================================
def create_school(**overrides) -> dict:
    """Register a school partner. Returns the created school."""
    payload = create_school_partner_payload(**overrides)
    return get_success_data(api_client.create_school_partner(payload, PD))


def add_blackout(school_partner_id: str, **overrides) -> dict:
    """Add a closed-interval blackout window to a school calendar."""
    payload = create_calendar_blackout_payload(**overrides)
    return get_success_data(
        api_client.create_calendar_blackout(school_partner_id, payload, RC)
    )


def create_artist_applicant(**overrides) -> dict:
    """Intake a teaching artist applicant. Returns the created artist."""
    payload = create_teaching_artist_payload(**overrides)
    return get_success_data(api_client.create_teaching_artist(payload, RC))


def advance_vetting(artist_id: str, to_vetting_status: str, **extra) -> dict:
    payload = create_vetting_payload(to_vetting_status, **extra)
    return get_success_data(api_client.advance_vetting(artist_id, payload, RC))


def record_portfolio_review(
    artist_id: str,
    reviewer_user_id: str,
    artistic_quality_score: float,
    pedagogical_clarity_score: float,
    cultural_responsiveness_score: float,
) -> dict:
    payload = create_portfolio_review_payload(
        reviewer_user_id,
        artistic_quality_score=artistic_quality_score,
        pedagogical_clarity_score=pedagogical_clarity_score,
        cultural_responsiveness_score=cultural_responsiveness_score,
    )
    return get_success_data(api_client.create_portfolio_review(artist_id, payload, RC))


def record_passing_portfolio_panel(artist_id: str) -> List[dict]:
    """Two panelists whose composites average at or above the advance
    threshold, so the demonstration may be scheduled."""
    return [
        record_portfolio_review(artist_id, PANELIST_1_USER_ID, 3.5, 4.0, 3.2),
        record_portfolio_review(artist_id, PANELIST_2_USER_ID, 4.0, 3.5, 3.0),
    ]


def record_clearance_screenings(
    artist_id: str,
    effective_on: str = TEST_DEFAULTS["CLEARANCE_EFFECTIVE_ON"],
    expires_on: str = TEST_DEFAULTS["CLEARANCE_EXPIRES_ON"],
    expires_on_by_type: Optional[Dict[str, str]] = None,
) -> List[dict]:
    """Record one CLEARED screening for each of the three required types."""
    out = []
    for screening_type in (
        "STATE_CRIMINAL", "FBI_FINGERPRINT", "CHILD_ABUSE_REGISTRY",
    ):
        expiry = (expires_on_by_type or {}).get(screening_type, expires_on)
        payload = create_screening_payload(
            screening_type,
            outcome="CLEARED",
            effective_on=effective_on,
            expires_on=expiry,
        )
        out.append(
            get_success_data(api_client.create_screening(artist_id, payload, RC))
        )
    return out


def record_failed_screening(
    artist_id: str,
    screening_type: str = "CHILD_ABUSE_REGISTRY",
    effective_on: str = "2026-09-01",
) -> dict:
    """Record a FAILED screening — the trigger for Cascade A."""
    payload = create_screening_payload(
        screening_type,
        outcome="FAILED",
        effective_on=effective_on,
        expires_on=None,
    )
    return get_success_data(api_client.create_screening(artist_id, payload, RC))


def create_cleared_artist(
    demo_rubric_score: float = TEST_DEFAULTS["DEMO_RUBRIC_SCORE"],
    demo_evaluator_user_id: str = DEMO_EVALUATOR_USER_ID,
    clearance_effective_on: str = TEST_DEFAULTS["CLEARANCE_EFFECTIVE_ON"],
    clearance_expires_on: str = TEST_DEFAULTS["CLEARANCE_EXPIRES_ON"],
    expires_on_by_type: Optional[Dict[str, str]] = None,
    portfolio_reviews: Optional[List[Tuple[str, float, float, float]]] = None,
    **artist_overrides,
) -> dict:
    """Walk an applicant all the way to vetting CLEARED, which also moves
    the roster axis to ACTIVE. Returns the artist as last read."""
    from .test_users import make_roster_coordinator_headers  # local: avoid cycle

    artist = create_artist_applicant(**artist_overrides)
    artist_id = artist["id"]
    advance_vetting(artist_id, "PORTFOLIO_REVIEW")
    if portfolio_reviews is None:
        record_passing_portfolio_panel(artist_id)
    else:
        for reviewer_user_id, aq, pc, cr in portfolio_reviews:
            record_portfolio_review(artist_id, reviewer_user_id, aq, pc, cr)
    advance_vetting(artist_id, "DEMO_SCHEDULED")
    demo_headers = make_roster_coordinator_headers(demo_evaluator_user_id)
    get_success_data(
        api_client.advance_vetting(
            artist_id,
            create_vetting_payload(
                "DEMO_PASSED", demo_rubric_score=demo_rubric_score
            ),
            demo_headers,
        )
    )
    advance_vetting(artist_id, "SCREENING_PENDING")
    record_clearance_screenings(
        artist_id,
        effective_on=clearance_effective_on,
        expires_on=clearance_expires_on,
        expires_on_by_type=expires_on_by_type,
    )
    advance_vetting(artist_id, "CLEARED")
    return read_artist(artist_id)


def read_artist(artist_id: str) -> dict:
    return get_success_data(api_client.get_teaching_artist(artist_id, PD))


def read_school(school_partner_id: str) -> dict:
    return get_success_data(api_client.get_school_partner(school_partner_id, PD))


def read_residency(residency_id: str) -> dict:
    return get_success_data(api_client.get_residency(residency_id, PD))


def read_session(session_id: str) -> dict:
    return get_success_data(api_client.get_session(session_id, PD))


def read_voucher(voucher_id: str) -> dict:
    return get_success_data(api_client.get_payment_voucher(voucher_id, PD))


def read_lesson_plan(lesson_plan_id: str) -> dict:
    return get_success_data(api_client.get_lesson_plan(lesson_plan_id, PD))


def read_funder_report(report_id: str) -> dict:
    return get_success_data(api_client.get_funder_report(report_id, PD))


def set_roster_status(artist_id: str, to_roster_status: str, **extra) -> dict:
    from .factories import create_roster_status_payload

    payload = create_roster_status_payload(to_roster_status, **extra)
    return get_success_data(api_client.set_roster_status(artist_id, payload, PD))


# ==========================================================================
# Tier 2 — Entity hierarchy
# ==========================================================================
def create_standard(code: str, strand: str, **overrides) -> dict:
    payload = create_arts_standard_payload(code, strand, **overrides)
    return get_success_data(api_client.create_arts_standard(payload, CS))


def create_dance_standards_pair(
    discipline: str = "DANCE", grade_band: str = "G3_5"
) -> Dict[str, dict]:
    """One CREATING and one RESPONDING standard matched to a residency frame."""
    creating = create_standard(
        TEST_DEFAULTS["STANDARD_CODE_CREATING"],
        "CREATING",
        discipline=discipline,
        grade_band=grade_band,
    )
    responding = create_standard(
        TEST_DEFAULTS["STANDARD_CODE_RESPONDING"],
        "RESPONDING",
        discipline=discipline,
        grade_band=grade_band,
    )
    return {"CREATING": creating, "RESPONDING": responding}


def create_residency_for_school(school_partner_id: str, **overrides) -> dict:
    payload = create_residency_payload(school_partner_id, **overrides)
    return get_success_data(api_client.create_residency(payload, PD))


def assign_lead_artist(residency_id: str, teaching_artist_id: str) -> dict:
    payload = create_lead_artist_payload(teaching_artist_id)
    return get_success_data(api_client.assign_lead_artist(residency_id, payload, PD))


def set_residency_status(residency_id: str, to_status: str, **extra) -> dict:
    payload = create_residency_status_payload(to_status, **extra)
    return get_success_data(
        api_client.set_residency_status(residency_id, payload, PD)
    )


def submit_lesson_plan(
    residency_id: str,
    standard_codes: List[str],
    session_sequence_no: int = 1,
    **overrides,
) -> dict:
    payload = create_lesson_plan_payload(
        residency_id, standard_codes, session_sequence_no, **overrides
    )
    return get_success_data(api_client.create_lesson_plan(payload, RC))


def align_lesson_plan(lesson_plan_id: str) -> dict:
    payload = create_lesson_plan_review_payload("ALIGN")
    return get_success_data(
        api_client.review_lesson_plan(lesson_plan_id, payload, CS)
    )


def create_aligned_lesson_plan(
    residency_id: str,
    standard_codes: List[str],
    session_sequence_no: int = 1,
    **overrides,
) -> dict:
    plan = submit_lesson_plan(
        residency_id, standard_codes, session_sequence_no, **overrides
    )
    return align_lesson_plan(plan["id"])


def setup_approved_residency(
    school_overrides: Optional[dict] = None,
    artist_overrides: Optional[dict] = None,
    residency_overrides: Optional[dict] = None,
    clearance_expires_on: str = TEST_DEFAULTS["CLEARANCE_EXPIRES_ON"],
    expires_on_by_type: Optional[Dict[str, str]] = None,
) -> dict:
    """School + cleared lead artist + residency approved.

    Returns {"school", "artist", "residency"} with the residency read
    after approval, so its allotment and money ledger are initialized.
    """
    school = create_school(**(school_overrides or {}))
    artist = create_cleared_artist(
        clearance_expires_on=clearance_expires_on,
        expires_on_by_type=expires_on_by_type,
        **(artist_overrides or {}),
    )
    residency = create_residency_for_school(
        school["id"], **(residency_overrides or {})
    )
    assign_lead_artist(residency["id"], artist["id"])
    residency = set_residency_status(residency["id"], "APPROVED")
    return {"school": school, "artist": artist, "residency": residency}


def setup_active_residency(
    school_overrides: Optional[dict] = None,
    artist_overrides: Optional[dict] = None,
    residency_overrides: Optional[dict] = None,
    clearance_expires_on: str = TEST_DEFAULTS["CLEARANCE_EXPIRES_ON"],
    expires_on_by_type: Optional[Dict[str, str]] = None,
    required_strands: Optional[List[str]] = None,
) -> dict:
    """School + cleared lead artist + residency ACTIVE with one aligned
    lesson plan whose covered strands satisfy the required strands.

    Returns {"school", "artist", "residency", "lesson_plan", "standards"}.
    """
    residency_overrides = dict(residency_overrides or {})
    if required_strands is not None:
        residency_overrides["required_strands"] = required_strands
    base = setup_approved_residency(
        school_overrides=school_overrides,
        artist_overrides=artist_overrides,
        residency_overrides=residency_overrides,
        clearance_expires_on=clearance_expires_on,
        expires_on_by_type=expires_on_by_type,
    )
    residency = base["residency"]
    strands = residency["required_strands"]
    standards = {}
    codes = []
    code_by_strand = {
        "CREATING": TEST_DEFAULTS["STANDARD_CODE_CREATING"],
        "RESPONDING": TEST_DEFAULTS["STANDARD_CODE_RESPONDING"],
        "PERFORMING": "DA:Pr4.1.4",
        "CONNECTING": "DA:Cn10.1.4",
    }
    for strand in strands:
        code = code_by_strand[strand]
        standards[strand] = create_standard(
            code,
            strand,
            discipline=residency["discipline"],
            grade_band=residency["grade_band"],
        )
        codes.append(code)
    plan = create_aligned_lesson_plan(residency["id"], codes, 1)
    residency = set_residency_status(residency["id"], "ACTIVE")
    base.update(
        {"residency": residency, "lesson_plan": plan, "standards": standards}
    )
    return base


# ==========================================================================
# Tier 3 — Full lifecycle shortcuts
# ==========================================================================
def schedule_session(
    residency_id: str,
    assigned_artist_id: str,
    session_date: str = "2026-09-15",
    start_time: str = "09:00",
    end_time: str = "10:00",
    lesson_plan_id: Optional[str] = None,
    expected_residency_version: Optional[int] = None,
    **overrides,
) -> dict:
    """Read the residency for its current version, then schedule a session."""
    if expected_residency_version is None:
        expected_residency_version = read_residency(residency_id)["version"]
    payload = create_session_payload(
        residency_id,
        assigned_artist_id,
        expected_residency_version,
        session_date=session_date,
        start_time=start_time,
        end_time=end_time,
        **overrides,
    )
    if lesson_plan_id is not None:
        payload["lesson_plan_id"] = lesson_plan_id
    return get_success_data(api_client.create_session(payload, RC))


def confirm_session_as_liaison(
    session_id: str,
    school_partner_id: str,
    classroom_teacher_name: str = TEST_DEFAULTS["CLASSROOM_TEACHER_NAME"],
    co_planning_completed: bool = True,
) -> dict:
    """Confirm as the host school's own SchoolLiaison (ownership-gated)."""
    payload = create_confirm_payload(
        classroom_teacher_name, co_planning_completed
    )
    return get_success_data(
        api_client.confirm_session(
            session_id, payload, make_school_liaison_headers(school_partner_id)
        )
    )


def confirm_session_as_coordinator(
    session_id: str,
    classroom_teacher_name: str = TEST_DEFAULTS["CLASSROOM_TEACHER_NAME"],
    co_planning_completed: bool = True,
) -> dict:
    payload = create_confirm_payload(
        classroom_teacher_name, co_planning_completed
    )
    return get_success_data(api_client.confirm_session(session_id, payload, RC))


def deliver_session(
    session_id: str,
    artist_id: str,
    students_present_count: int = 24,
    minutes_delivered: int = 60,
    travel_miles: float = 0.0,
    materials_spend_cents: int = 0,
) -> dict:
    """Report delivery as the assigned artist (ownership-gated)."""
    payload = create_deliver_payload(
        students_present_count=students_present_count,
        minutes_delivered=minutes_delivered,
        travel_miles=travel_miles,
        materials_spend_cents=materials_spend_cents,
    )
    return get_success_data(
        api_client.deliver_session(
            session_id, payload, make_teaching_artist_headers(artist_id)
        )
    )


def cancel_session_as_liaison(
    session_id: str, school_partner_id: str, cancel_reason: str, **extra
) -> dict:
    payload = create_cancel_payload(cancel_reason, **extra)
    return get_success_data(
        api_client.cancel_session(
            session_id, payload, make_school_liaison_headers(school_partner_id)
        )
    )


def cancel_session_as_coordinator(
    session_id: str, cancel_reason: str, **extra
) -> dict:
    payload = create_cancel_payload(cancel_reason, **extra)
    return get_success_data(api_client.cancel_session(session_id, payload, RC))


def cancel_session_as_artist(
    session_id: str, artist_id: str, cancel_reason: str = "ARTIST_ILLNESS", **extra
) -> dict:
    payload = create_cancel_payload(cancel_reason, **extra)
    return get_success_data(
        api_client.cancel_session(
            session_id, payload, make_teaching_artist_headers(artist_id)
        )
    )


def reassign_session(
    session_id: str,
    substitute_artist_id: str,
    expected_session_version: Optional[int] = None,
) -> dict:
    if expected_session_version is None:
        expected_session_version = read_session(session_id)["version"]
    payload = create_reassign_payload(
        substitute_artist_id, expected_session_version
    )
    return get_success_data(api_client.reassign_session(session_id, payload, RC))


def create_confirmed_session(
    scenario: dict,
    session_date: str = "2026-09-15",
    start_time: str = "09:00",
    end_time: str = "10:00",
    **overrides,
) -> dict:
    """Schedule then confirm one session inside an active-residency scenario."""
    session = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date=session_date,
        start_time=start_time,
        end_time=end_time,
        lesson_plan_id=scenario["lesson_plan"]["id"],
        **overrides,
    )
    return confirm_session_as_liaison(session["id"], scenario["school"]["id"])


def create_delivered_session(
    scenario: dict,
    session_date: str = "2026-09-15",
    start_time: str = "09:00",
    end_time: str = "10:00",
    students_present_count: int = 24,
    minutes_delivered: int = 60,
    travel_miles: float = 0.0,
    materials_spend_cents: int = 0,
    **overrides,
) -> dict:
    """Schedule, confirm and deliver one session."""
    confirmed = create_confirmed_session(
        scenario,
        session_date=session_date,
        start_time=start_time,
        end_time=end_time,
        **overrides,
    )
    return deliver_session(
        confirmed["id"],
        scenario["artist"]["id"],
        students_present_count=students_present_count,
        minutes_delivered=minutes_delivered,
        travel_miles=travel_miles,
        materials_spend_cents=materials_spend_cents,
    )


def attach_observation_rubric(
    session_id: str,
    evaluator_user_id: str = OBSERVER_USER_ID,
    rubric_engagement_score: int = 4,
    rubric_craft_score: int = 3,
    rubric_standards_evidence_score: int = 4,
) -> dict:
    """Attach an OBSERVATION_RUBRIC as a CurriculumSpecialist."""
    from .test_users import make_curriculum_specialist_headers

    payload = create_observation_rubric_payload(
        evaluator_user_id,
        rubric_engagement_score=rubric_engagement_score,
        rubric_craft_score=rubric_craft_score,
        rubric_standards_evidence_score=rubric_standards_evidence_score,
    )
    return get_success_data(
        api_client.create_evaluation(
            session_id, payload, make_curriculum_specialist_headers(evaluator_user_id)
        )
    )


def attach_teacher_survey(
    session_id: str,
    school_partner_id: str,
    evaluator_user_id: str = "teacher-1",
    teacher_survey_score: int = 4,
) -> dict:
    """Attach a TEACHER_SURVEY as the host school's own SchoolLiaison."""
    from .factories import create_teacher_survey_payload

    payload = create_teacher_survey_payload(
        evaluator_user_id, teacher_survey_score=teacher_survey_score
    )
    return get_success_data(
        api_client.create_evaluation(
            session_id, payload, make_school_liaison_headers(school_partner_id)
        )
    )


def attach_student_work_sample(
    session_id: str,
    school_partner_id: str,
    evaluator_user_id: str = "teacher-1",
    student_work_artifact_count: int = 12,
) -> dict:
    from .factories import create_student_work_sample_payload

    payload = create_student_work_sample_payload(
        evaluator_user_id,
        student_work_artifact_count=student_work_artifact_count,
    )
    return get_success_data(
        api_client.create_evaluation(
            session_id, payload, make_school_liaison_headers(school_partner_id)
        )
    )


def open_voucher(
    artist_id: str,
    residency_id: str,
    session_ids: List[str],
    period_start: str = "2026-09-01",
    period_end: str = "2026-09-30",
    **overrides,
) -> dict:
    """Open a voucher as the payee artist themselves (ownership-gated)."""
    payload = create_payment_voucher_payload(
        artist_id,
        residency_id,
        session_ids,
        period_start=period_start,
        period_end=period_end,
        **overrides,
    )
    return get_success_data(
        api_client.create_payment_voucher(
            payload, make_teaching_artist_headers(artist_id)
        )
    )


def submit_voucher(voucher_id: str, artist_id: str) -> dict:
    return get_success_data(
        api_client.submit_payment_voucher(
            voucher_id, make_teaching_artist_headers(artist_id)
        )
    )


def review_voucher_track(
    voucher_id: str,
    review_track: str,
    decision: str,
    reviewer_user_id: Optional[str] = None,
    expected_payment_voucher_version: Optional[int] = None,
) -> dict:
    """Close one review track. FISCAL is a FiscalOfficer act, PROGRAM a
    ProgramDirector act."""
    from .test_users import (
        make_fiscal_officer_headers,
        make_program_director_headers,
    )

    if expected_payment_voucher_version is None:
        expected_payment_voucher_version = read_voucher(voucher_id)["version"]
    payload = create_voucher_review_payload(
        review_track, decision, expected_payment_voucher_version
    )
    if review_track == "FISCAL":
        headers = make_fiscal_officer_headers(
            reviewer_user_id or FISCAL_OFFICER_USER_ID
        )
    else:
        headers = make_program_director_headers(
            reviewer_user_id or PROGRAM_DIRECTOR_USER_ID
        )
    return get_success_data(
        api_client.review_payment_voucher(voucher_id, payload, headers)
    )


def create_submitted_voucher(
    scenario: dict,
    session_ids: List[str],
    period_start: str = "2026-09-01",
    period_end: str = "2026-09-30",
) -> dict:
    """Open and submit a voucher over already-evaluated delivered sessions."""
    voucher = open_voucher(
        scenario["artist"]["id"],
        scenario["residency"]["id"],
        session_ids,
        period_start=period_start,
        period_end=period_end,
    )
    return submit_voucher(voucher["id"], scenario["artist"]["id"])


def create_approved_voucher(
    scenario: dict,
    session_ids: List[str],
    period_start: str = "2026-09-01",
    period_end: str = "2026-09-30",
) -> dict:
    """Submit and pass both review tracks so the join approves the voucher."""
    voucher = create_submitted_voucher(
        scenario, session_ids, period_start=period_start, period_end=period_end
    )
    review_voucher_track(voucher["id"], "FISCAL", "PASS")
    return review_voucher_track(voucher["id"], "PROGRAM", "PASS")


# ==========================================================================
# Tier 4 — Accumulation and threshold targeting
# ==========================================================================
def setup_two_delivered_evaluated_sessions(
    scenario: Optional[dict] = None,
    first_travel_miles: float = 20.5,
    first_materials_spend_cents: int = 3000,
    second_travel_miles: float = 14.5,
    second_materials_spend_cents: int = 0,
) -> dict:
    """The canonical two-delivery scenario used by the money and cost-outlook
    claims: two delivered sessions, each carrying an observation rubric so a
    voucher may claim them.

    Returns the scenario dict plus {"session_one", "session_two"}.
    """
    scenario = scenario or setup_active_residency()
    one = create_delivered_session(
        scenario,
        session_date="2026-09-15",
        start_time="09:00",
        end_time="10:00",
        students_present_count=24,
        minutes_delivered=60,
        travel_miles=first_travel_miles,
        materials_spend_cents=first_materials_spend_cents,
    )
    two = create_delivered_session(
        scenario,
        session_date="2026-09-22",
        start_time="09:00",
        end_time="10:00",
        students_present_count=22,
        minutes_delivered=60,
        travel_miles=second_travel_miles,
        materials_spend_cents=second_materials_spend_cents,
    )
    attach_observation_rubric(one["id"], OBSERVER_USER_ID, 4, 3, 4)
    attach_observation_rubric(two["id"], OBSERVER_USER_ID, 3, 3, 4)
    scenario = dict(scenario)
    scenario["session_one"] = one
    scenario["session_two"] = two
    scenario["residency"] = read_residency(scenario["residency"]["id"])
    return scenario


def setup_artist_with_terminal_sessions(
    delivered: int = 2,
    artist_cancelled: int = 2,
    scenario: Optional[dict] = None,
    session_dates: Optional[List[str]] = None,
    minutes_delivered: int = 60,
    travel_miles: float = 0.0,
    materials_spend_cents: int = 0,
) -> dict:
    """Drive an artist's reliability input set to a known composition by
    delivering some confirmed sessions and cancelling others for an
    artist-side reason.

    Returns the scenario plus {"delivered_sessions", "cancelled_sessions"}.
    """
    scenario = scenario or setup_active_residency()
    total = delivered + artist_cancelled
    dates = session_dates or [
        "2026-09-15", "2026-09-22", "2026-09-29", "2026-10-06",
        "2026-10-13", "2026-10-20", "2026-10-27", "2026-11-03",
    ][:total]
    confirmed = [
        create_confirmed_session(scenario, session_date=date) for date in dates
    ]
    delivered_sessions = []
    for session in confirmed[:delivered]:
        delivered_sessions.append(
            deliver_session(
                session["id"],
                scenario["artist"]["id"],
                minutes_delivered=minutes_delivered,
                travel_miles=travel_miles,
                materials_spend_cents=materials_spend_cents,
            )
        )
    cancelled_sessions = []
    for session in confirmed[delivered:]:
        cancelled_sessions.append(
            cancel_session_as_artist(
                session["id"], scenario["artist"]["id"], "ARTIST_ILLNESS"
            )
        )
    scenario = dict(scenario)
    scenario["confirmed_sessions"] = confirmed
    scenario["delivered_sessions"] = delivered_sessions
    scenario["cancelled_sessions"] = cancelled_sessions
    scenario["artist"] = read_artist(scenario["artist"]["id"])
    scenario["residency"] = read_residency(scenario["residency"]["id"])
    return scenario


def setup_makeup_credit_outstanding(
    scenario: Optional[dict] = None, session_date: str = "2026-09-15"
) -> dict:
    """Cancel a make-up-eligible session so one credit sits outstanding.

    Returns the scenario plus {"origin_session"}.
    """
    scenario = scenario or setup_active_residency()
    session = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date=session_date,
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    origin = cancel_session_as_coordinator(session["id"], "SCHOOL_CLOSURE")
    scenario = dict(scenario)
    scenario["origin_session"] = origin
    scenario["residency"] = read_residency(scenario["residency"]["id"])
    return scenario


def setup_second_artist(
    primary_discipline: str = "DANCE",
    grade_bands: Optional[List[str]] = None,
    languages: Optional[List[str]] = None,
    roster_tier_assigned: str = "TEACHING_ARTIST",
    full_name: str = "Bo Halvorsen",
    email: str = "bo.halvorsen@arts.org",
    demo_rubric_score: float = 4.1,
    portfolio_reviews: Optional[List[Tuple[str, float, float, float]]] = None,
    **overrides,
) -> dict:
    """A second cleared artist, used for reassignment, capability-mismatch
    and multi-artist scheduling scenarios. Its panelists are distinct from
    the first artist's so the demonstration evaluator stays eligible."""
    reviews = portfolio_reviews or [
        ("panelist-3", 4.0, 4.0, 4.0),
        ("panelist-4", 3.8, 4.0, 3.9),
    ]
    return create_cleared_artist(
        demo_rubric_score=demo_rubric_score,
        demo_evaluator_user_id="demo-evaluator-2",
        portfolio_reviews=reviews,
        full_name=full_name,
        email=email,
        primary_discipline=primary_discipline,
        secondary_disciplines=[],
        grade_bands=grade_bands or ["G3_5"],
        languages=languages or ["en", "es"],
        roster_tier_assigned=roster_tier_assigned,
        **overrides,
    )


# ==========================================================================
# Tier 5 — Finalization and terminal state
# ==========================================================================
def complete_residency(residency_id: str, reason: Optional[str] = None) -> dict:
    """ACTIVE → COMPLETED, running the forfeiture sweep."""
    extra = {"reason": reason} if reason else {}
    return set_residency_status(residency_id, "COMPLETED", **extra)


def close_residency(residency_id: str) -> dict:
    """COMPLETED → CLOSED, the accounting close."""
    return set_residency_status(residency_id, "CLOSED")


def open_funder_report(
    scope_residency_ids: List[str],
    funder_name: str = "Cascade Arts Trust",
    grant_code: str = "CAT-2026-09",
    period_start: str = "2026-09-01",
    period_end: str = "2026-09-30",
    headcount_basis: str = "UNDUPLICATED",
) -> dict:
    payload = create_funder_report_payload(
        scope_residency_ids,
        funder_name=funder_name,
        grant_code=grant_code,
        period_start=period_start,
        period_end=period_end,
        headcount_basis=headcount_basis,
    )
    return get_success_data(api_client.create_funder_report(payload, PD))


def compile_funder_report(
    report_id: str, compiler_user_id: str = PROGRAM_DIRECTOR_USER_ID
) -> dict:
    from .test_users import make_program_director_headers

    return get_success_data(
        api_client.compile_funder_report(
            report_id, make_program_director_headers(compiler_user_id)
        )
    )


def certify_funder_report(
    report_id: str,
    certifier_user_id: str = FISCAL_OFFICER_USER_ID,
    attestation_text: str = "Figures reviewed and attested.",
) -> dict:
    from .test_users import make_fiscal_officer_headers

    payload = create_certify_payload(certifier_user_id, attestation_text)
    return get_success_data(
        api_client.certify_funder_report(
            report_id, payload, make_fiscal_officer_headers(certifier_user_id)
        )
    )


def setup_compiled_funder_report(
    scenario: Optional[dict] = None,
    headcount_basis: str = "UNDUPLICATED",
    grant_code: str = "CAT-2026-09",
    period_start: str = "2026-09-01",
    period_end: str = "2026-09-30",
    deliver_one_session: bool = True,
) -> dict:
    """An active residency with (optionally) one delivered session, plus a
    funder report over it already compiled.

    Returns the scenario plus {"report"}.
    """
    scenario = scenario or setup_active_residency()
    if deliver_one_session:
        delivered = create_delivered_session(
            scenario, session_date="2026-09-15", students_present_count=24
        )
        scenario = dict(scenario)
        scenario["delivered_session"] = delivered
    report = open_funder_report(
        [scenario["residency"]["id"]],
        grant_code=grant_code,
        period_start=period_start,
        period_end=period_end,
        headcount_basis=headcount_basis,
    )
    report = compile_funder_report(report["id"])
    scenario = dict(scenario)
    scenario["report"] = report
    scenario["residency"] = read_residency(scenario["residency"]["id"])
    return scenario
