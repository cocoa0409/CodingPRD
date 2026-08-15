"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server with an empty database and
the logical clock at the 2026-08-01T00:00:00Z boot instant, PRD §2.4). Lenient
get_success_data is used internally so setup failures surface as clear
"Setup failed" errors.

Parent calls that are ownership-gated always thread the owning family's
family_id through make_parent_headers (PRD §2.1); staff reads use the
unscoped AdmissionDirector headers.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BOOT_CLOCK,
    EARLY_CLOSE_CLOCK,
    INTERVIEW_WINDOW,
    REGULAR_CLOSE_CLOCK,
    TEST_WINDOW,
)
from .factories import (
    create_aid_application_payload,
    create_applicant_payload,
    create_application_payload,
    create_cycle_payload,
    create_evaluation_payload,
    create_grade_section_payload,
    create_reenrollment_offer_payload,
    create_student_payload,
    create_test_session_payload,
)
from .test_users import TEST_USERS, make_fao_headers, make_parent_headers

DIRECTOR = TEST_USERS["director_headers"]
OFFICER = TEST_USERS["officer_headers"]
FAO_1 = TEST_USERS["fao_1_headers"]
FAO_2 = TEST_USERS["fao_2_headers"]


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, DIRECTOR))


def pin_clock(to_iso8601: str = BOOT_CLOCK) -> dict:
    """Pin the logical clock to an explicit instant (usually the boot default)."""
    return set_clock(to_iso8601)


# ---------------------------------------------------------------------------
# Cycles, sections, sessions (PRD §3.1, §3.3)
# ---------------------------------------------------------------------------

def make_cycle(**overrides) -> dict:
    return get_success_data(api_client.create_cycle(create_cycle_payload(**overrides),
                                                    DIRECTOR))


def make_section(cycle_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_grade_section(
            create_grade_section_payload(cycle_id, **overrides), DIRECTOR,
        )
    )


def open_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.open_cycle(cycle_id, DIRECTOR))


def make_test_session(cycle_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_test_session(
            create_test_session_payload(cycle_id, **overrides), DIRECTOR,
        )
    )


def make_open_world(grade_level: str = "G9", capacity: int = 5,
                    tuition_cents: int = 3_000_000, max_aid_seat_pct: float = 0.5,
                    session_capacity: int = 5, with_session: bool = True,
                    **cycle_overrides) -> dict:
    """Cycle + one grade section + (optional) test session, cycle OPEN."""
    cycle = make_cycle(**cycle_overrides)
    section = make_section(cycle["id"], grade_level=grade_level, capacity=capacity,
                           tuition_cents=tuition_cents,
                           max_aid_seat_pct=max_aid_seat_pct)
    open_cycle(cycle["id"])
    session = make_test_session(cycle["id"], room_capacity=session_capacity) \
        if with_session else None
    return {"cycle": cycle, "section": section, "session": session}


# ---------------------------------------------------------------------------
# Applicants and applications (PRD §3.2)
# ---------------------------------------------------------------------------

def make_applicant(family_id: str = "fam-a", as_officer: bool = False,
                   **overrides) -> dict:
    headers = OFFICER if as_officer else make_parent_headers(family_id)
    return get_success_data(
        api_client.create_applicant(create_applicant_payload(family_id, **overrides),
                                    headers)
    )


def make_application(applicant_id: str, cycle_id: str, section_id: str,
                     family_id: str = "fam-a", round_name: str = "EARLY",
                     as_officer: bool = False) -> dict:
    headers = OFFICER if as_officer else make_parent_headers(family_id)
    return get_success_data(
        api_client.create_application(
            create_application_payload(applicant_id, cycle_id, section_id,
                                       round=round_name),
            headers,
        )
    )


def submit_application(application_id: str, family_id: str) -> dict:
    return get_success_data(
        api_client.submit_application(application_id, make_parent_headers(family_id))
    )


def setup_submitted_application(family_id: str = "fam-a", round_name: str = "EARLY",
                                applicant_overrides: Optional[dict] = None,
                                **world_kw) -> dict:
    """OPEN world + applicant + application + submit. Returns a context dict."""
    ctx = make_open_world(**world_kw)
    applicant = make_applicant(family_id, **(applicant_overrides or {}))
    application = make_application(applicant["id"], ctx["cycle"]["id"],
                                   ctx["section"]["id"], family_id, round_name)
    submit_application(application["id"], family_id)
    ctx.update({"applicant": applicant, "application": application,
                "family_id": family_id})
    return ctx


# ---------------------------------------------------------------------------
# Evaluations (PRD §3.3)
# ---------------------------------------------------------------------------

def schedule_test(application_id: str, session_id: str,
                  window: Tuple[str, str] = TEST_WINDOW) -> dict:
    payload = create_evaluation_payload(
        application_id, "TEST", scheduled_start=window[0], scheduled_end=window[1],
        test_session_id=session_id,
    )
    return get_success_data(api_client.create_evaluation(payload, OFFICER))


def schedule_interview(application_id: str, interviewer_id: str = "int-a",
                       window: Tuple[str, str] = INTERVIEW_WINDOW) -> dict:
    payload = create_evaluation_payload(
        application_id, "INTERVIEW", scheduled_start=window[0],
        scheduled_end=window[1], interviewer_id=interviewer_id,
    )
    return get_success_data(api_client.create_evaluation(payload, OFFICER))


def score_evaluation(evaluation_id: str, score: int) -> dict:
    return get_success_data(api_client.score_evaluation(evaluation_id, score, OFFICER))


def cancel_evaluation(evaluation_id: str) -> dict:
    return get_success_data(api_client.cancel_evaluation(evaluation_id, OFFICER))


def score_pair(application_id: str, session_id: str, test_score: int = 80,
               interview_score: int = 90, interviewer_id: str = "int-a",
               test_window: Tuple[str, str] = TEST_WINDOW) -> Tuple[dict, dict]:
    """Schedule and score both kinds; the second scoring moves the application
    SUBMITTED -> EVALUATION_COMPLETE (PRD §3.3). Returns (test_eval, interview)."""
    test_eval = schedule_test(application_id, session_id, test_window)
    interview = schedule_interview(application_id, interviewer_id)
    score_evaluation(test_eval["id"], test_score)
    score_evaluation(interview["id"], interview_score)
    return test_eval, interview


def setup_scored_application(family_id: str = "fam-a", round_name: str = "EARLY",
                             test_score: int = 80, interview_score: int = 90,
                             legacy_parent: bool = False, **world_kw) -> dict:
    """Through EVALUATION_COMPLETE with both kinds scored (default 80/90)."""
    overrides = {"legacy_parent": True} if legacy_parent else None
    ctx = setup_submitted_application(family_id, round_name,
                                      applicant_overrides=overrides, **world_kw)
    test_eval, interview = score_pair(ctx["application"]["id"],
                                      ctx["session"]["id"],
                                      test_score, interview_score,
                                      f"int-{family_id}")
    ctx.update({"test_eval": test_eval, "interview_eval": interview})
    ctx["application"] = get_application(ctx["application"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Financial aid (PRD §3.4)
# ---------------------------------------------------------------------------

def make_aid_application(application_id: str, family_id: str,
                         income_cents: int = 9_500_000, household_size: int = 4,
                         as_fao: bool = False) -> dict:
    headers = FAO_1 if as_fao else make_parent_headers(family_id)
    return get_success_data(
        api_client.create_aid_application(
            create_aid_application_payload(
                application_id, reported_annual_income_cents=income_cents,
                household_size=household_size,
            ),
            headers,
        )
    )


def verify_aid(aid_id: str, verified_income_cents: int,
               officer_id: str = "fao-1") -> dict:
    return get_success_data(
        api_client.verify_aid(aid_id, verified_income_cents,
                              make_fao_headers(officer_id))
    )


def finalize_aid(aid_id: str, officer_id: str = "fao-2") -> dict:
    return get_success_data(
        api_client.finalize_award(aid_id, make_fao_headers(officer_id))
    )


def accept_aid(aid_id: str, family_id: str) -> dict:
    return get_success_data(
        api_client.accept_award(aid_id, make_parent_headers(family_id))
    )


def resubmit_income(aid_id: str, family_id: str, income_cents: int,
                    household_size: int) -> dict:
    return get_success_data(
        api_client.resubmit_income(
            aid_id,
            {"reported_annual_income_cents": income_cents,
             "household_size": household_size},
            make_parent_headers(family_id),
        )
    )


def setup_finalized_aid(family_id: str = "fam-a", income_cents: int = 9_500_000,
                        household_size: int = 4,
                        verified_income_cents: Optional[int] = None,
                        verifier_id: str = "fao-1", finalizer_id: str = "fao-2",
                        **world_kw) -> dict:
    """Submitted application + aid application verified and finalized
    (award_status OFFERED). Returns a context dict."""
    ctx = setup_submitted_application(family_id, with_session=False, **world_kw)
    aid = make_aid_application(ctx["application"]["id"], family_id,
                               income_cents, household_size)
    verify_aid(aid["id"],
               verified_income_cents if verified_income_cents is not None
               else income_cents,
               officer_id=verifier_id)
    finalize_aid(aid["id"], officer_id=finalizer_id)
    ctx["aid"] = get_aid(aid["id"])
    return ctx


# ---------------------------------------------------------------------------
# Decisions, offers, sweeps (PRD §3.5)
# ---------------------------------------------------------------------------

def close_round(cycle_id: str, round_name: str) -> dict:
    return get_success_data(api_client.close_round(cycle_id, round_name, DIRECTOR))


def run_sweep(cycle_id: str) -> dict:
    return get_success_data(api_client.run_sweep(cycle_id, DIRECTOR))


def setup_offered_application(family_id: str = "fam-a",
                              aid: Optional[Tuple[int, int, int]] = None,
                              accept_aid_award: bool = False,
                              capacity: int = 1, round_name: str = "EARLY",
                              close_clock: str = EARLY_CLOSE_CLOCK,
                              test_score: int = 80, interview_score: int = 90,
                              **world_kw) -> dict:
    """Full chain through the round close with a single candidate -> OFFERED.

    aid: (reported_income_cents, household_size, verified_income_cents) tuple;
    when given, the aid application is created, verified and finalized before
    the close (so the offer letter's estimated deposit uses the provisional
    award), and accepted after the close iff accept_aid_award is true.
    """
    world_kw.setdefault("max_aid_seat_pct", 1.0)
    ctx = setup_submitted_application(family_id, round_name, capacity=capacity,
                                      **world_kw)
    app_id = ctx["application"]["id"]
    if aid is not None:
        reported, household, verified = aid
        aid_row = make_aid_application(app_id, family_id, reported, household)
        verify_aid(aid_row["id"], verified)
        finalize_aid(aid_row["id"])
        ctx["aid"] = get_aid(aid_row["id"])
    test_eval, interview = score_pair(app_id, ctx["session"]["id"],
                                      test_score, interview_score,
                                      f"int-{family_id}")
    ctx.update({"test_eval": test_eval, "interview_eval": interview})
    set_clock(close_clock)
    close_round(ctx["cycle"]["id"], round_name)
    ctx["application"] = get_application(app_id)
    if aid is not None and accept_aid_award:
        accept_aid(ctx["aid"]["id"], family_id)
        ctx["aid"] = get_aid(ctx["aid"]["id"])
    return ctx


def setup_decision_world(candidates: List[dict], capacity: int = 1,
                         round_name: str = "EARLY",
                         close_clock: str = EARLY_CLOSE_CLOCK,
                         regular_close_clock: str = REGULAR_CLOSE_CLOCK,
                         **world_kw) -> dict:
    """Multi-candidate world scored and closed per the committee rules (§3.5).

    candidates: list of dicts with keys
      family (str), test (int), interview (int),
      aid ((income_cents, household_size) | None), legacy (bool),
      submit_at (ISO str | None — clock is set to it just before submit).
    TEST windows all coincide (aggregate session capacity makes that legal);
    interviewers are distinct per candidate. For round_name == "REGULAR" the
    EARLY round is closed first (empty pool) before the REGULAR close.
    Returns a context dict whose "candidates" entries gain applicant /
    application / evaluation rows.
    """
    world_kw.setdefault("session_capacity", max(8, len(candidates) + 1))
    ctx = make_open_world(capacity=capacity, **world_kw)
    entries = []
    for index, cand in enumerate(candidates):
        family = cand["family"]
        applicant = make_applicant(
            family, first_name=cand.get("first_name", f"Kid{index}"),
            last_name=cand.get("last_name", family),
            legacy_parent=cand.get("legacy", False),
            date_of_birth=cand.get("date_of_birth", "2013-01-01"),
        )
        application = make_application(applicant["id"], ctx["cycle"]["id"],
                                       ctx["section"]["id"], family, round_name)
        if cand.get("submit_at"):
            set_clock(cand["submit_at"])
        submit_application(application["id"], family)
        if cand.get("aid"):
            income, household = cand["aid"]
            make_aid_application(application["id"], family, income, household)
        entries.append({**cand, "applicant": applicant,
                        "application": application})
    for index, entry in enumerate(entries):
        test_eval, interview = score_pair(
            entry["application"]["id"], ctx["session"]["id"],
            entry["test"], entry["interview"], f"int-{index}",
        )
        entry.update({"test_eval": test_eval, "interview_eval": interview})
        entry["application"] = get_application(entry["application"]["id"])
    ctx["candidates"] = entries
    if round_name == "REGULAR":
        set_clock(EARLY_CLOSE_CLOCK)
        close_round(ctx["cycle"]["id"], "EARLY")
        set_clock(close_clock if close_clock != EARLY_CLOSE_CLOCK
                  else regular_close_clock)
        close_round(ctx["cycle"]["id"], "REGULAR")
    else:
        set_clock(close_clock)
        close_round(ctx["cycle"]["id"], "EARLY")
    for entry in entries:
        entry["application"] = get_application(entry["application"]["id"])
    return ctx


def setup_pacing_boundary_world() -> dict:
    """Four-family pacing world (PRD §3.1, §3.4): fam-1 and fam-2 awards of
    2,700,000 each ACCEPTED (5,400,000 committed against the 7,220,000
    OPEN-phase ceiling), fam-3 finalized at 1,820,000, fam-4 finalized at
    2,700,000. All ride on EARLY applications; no evaluations are needed."""
    ctx = make_open_world(capacity=10, max_aid_seat_pct=1.0, with_session=False)
    cyc_id, sec_id = ctx["cycle"]["id"], ctx["section"]["id"]

    def file_and_finalize(family, income, accept=False):
        applicant = make_applicant(family, last_name=family)
        application = make_application(applicant["id"], cyc_id, sec_id, family,
                                       "EARLY")
        submit_application(application["id"], family)
        aid = make_aid_application(application["id"], family, income, 4)
        verify_aid(aid["id"], income)
        finalize_aid(aid["id"])
        if accept:
            accept_aid(aid["id"], family)
        return {"family": family, "applicant": applicant,
                "application": application, "aid": get_aid(aid["id"])}

    fam1 = file_and_finalize("fam-1", 5_500_000, accept=True)
    fam2 = file_and_finalize("fam-2", 5_500_000, accept=True)
    fam3 = file_and_finalize("fam-3", 12_000_000)
    fam4 = file_and_finalize("fam-4", 5_500_000)
    ctx.update({"fam1": fam1, "fam2": fam2, "fam3": fam3, "fam4": fam4})
    return ctx


# ---------------------------------------------------------------------------
# Contracts, deposits, enrollment (PRD §3.6)
# ---------------------------------------------------------------------------

def issue_contract(application_id: str) -> dict:
    return get_success_data(api_client.issue_contract(application_id, OFFICER),
                            expected_status=201)


def sign_contract(contract_id: str, family_id: str) -> dict:
    return get_success_data(
        api_client.sign_contract(contract_id, make_parent_headers(family_id))
    )


def pay_deposit(contract_id: str, family_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.pay_deposit(contract_id, amount_cents,
                               make_parent_headers(family_id))
    )


def setup_issued_contract_world(family_id: str = "fam-a", **kwargs) -> dict:
    """OFFERED application (+ accepted aid when configured) -> contract ISSUED."""
    ctx = setup_offered_application(family_id, **kwargs)
    ctx["contract"] = issue_contract(ctx["application"]["id"])
    ctx["application"] = get_application(ctx["application"]["id"])
    return ctx


def setup_signed_contract_world(family_id: str = "fam-a", **kwargs) -> dict:
    ctx = setup_issued_contract_world(family_id, **kwargs)
    ctx["contract"] = sign_contract(ctx["contract"]["id"], ctx["family_id"])
    return ctx


def setup_enrolled_world(family_id: str = "fam-a", **kwargs) -> dict:
    """Through ENROLLED: sign, then pay the exact deposit in one payment."""
    ctx = setup_signed_contract_world(family_id, **kwargs)
    contract = get_contract(ctx["contract"]["id"])
    paid = pay_deposit(contract["id"], ctx["family_id"],
                       contract["deposit_amount_cents"])
    ctx["contract"] = paid
    ctx["student_id"] = paid["created_student_id"]
    ctx["application"] = get_application(ctx["application"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Re-enrollment (PRD §3.7)
# ---------------------------------------------------------------------------

CURRENT_CYCLE_DEADLINES = {
    "academic_year": "2026-2027",
    "early_deadline_at": "2025-11-01T00:00:00Z",
    "regular_deadline_at": "2026-01-15T00:00:00Z",
    "reenroll_response_deadline_at": "2026-03-01T00:00:00Z",
    "melt_deadline_at": "2026-08-01T00:00:00Z",
    "aid_budget_total_cents": 0,
}


def make_student(family_id: str, section_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_student(
            create_student_payload(family_id, section_id, **overrides), DIRECTOR,
        )
    )


def setup_reenrollment_world(current_grades=(("G9", 3_000_000),),
                             target_grades=(("G10", 3_200_000),),
                             students=(("fam-r", 0),)) -> dict:
    """Current cycle + target (upcoming-year) cycle with sections for each
    listed grade, plus ACTIVE students. students: (family_id, index into
    current_grades) tuples, created in the given order (created_at ascending
    is the family's seniority order, PRD §3.7)."""
    current = make_cycle(**CURRENT_CYCLE_DEADLINES)
    target = make_cycle()
    current_sections = [
        make_section(current["id"], grade_level=grade, capacity=20,
                     tuition_cents=tuition, max_aid_seat_pct=1.0)
        for grade, tuition in current_grades
    ]
    target_sections = [
        make_section(target["id"], grade_level=grade, capacity=20,
                     tuition_cents=tuition, max_aid_seat_pct=1.0)
        for grade, tuition in target_grades
    ]
    rows = []
    for index, (family, grade_index) in enumerate(students):
        rows.append(make_student(family, current_sections[grade_index]["id"],
                                 first_name=f"St{index}", last_name=family))
    return {"current_cycle": current, "target_cycle": target,
            "current_sections": current_sections,
            "target_sections": target_sections, "students": rows}


def make_reenrollment_offer(student_id: str, cycle_id: str) -> dict:
    """Create an offer carrying the student's FRESH version (PRD §2.8 OCC)."""
    student = get_student(student_id)
    return get_success_data(
        api_client.create_reenrollment_offer(
            create_reenrollment_offer_payload(student_id, cycle_id,
                                              student["version"]),
            DIRECTOR,
        ),
        expected_status=201,
    )


def respond_offer(offer_id: str, family_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.respond_reenrollment_offer(offer_id, decision,
                                              make_parent_headers(family_id))
    )


# ---------------------------------------------------------------------------
# Staff read-backs (unscoped)
# ---------------------------------------------------------------------------

def get_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_cycle(cycle_id, DIRECTOR))


def get_section(section_id: str) -> dict:
    return get_success_data(api_client.get_grade_section(section_id, DIRECTOR))


def get_applicant(applicant_id: str) -> dict:
    return get_success_data(api_client.get_applicant(applicant_id, DIRECTOR))


def get_student(student_id: str) -> dict:
    return get_success_data(api_client.get_student(student_id, DIRECTOR))


def get_application(application_id: str) -> dict:
    return get_success_data(api_client.get_application(application_id, DIRECTOR))


def get_evaluation(evaluation_id: str) -> dict:
    return get_success_data(api_client.get_evaluation(evaluation_id, DIRECTOR))


def get_session(session_id: str) -> dict:
    return get_success_data(api_client.get_test_session(session_id, DIRECTOR))


def get_aid(aid_id: str) -> dict:
    return get_success_data(api_client.get_aid_application(aid_id, DIRECTOR))


def get_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_contract(contract_id, DIRECTOR))


def get_offer(offer_id: str) -> dict:
    return get_success_data(api_client.get_reenrollment_offer(offer_id, DIRECTOR))
