"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its state from scratch through PRD-declared endpoints only —
each test starts against an empty database.  Setup calls use the lenient
`get_success_data()` validator so a broken precondition surfaces as a setup
failure rather than a confusing assertion failure.

Identity threading: a `Coach` acts with its own `StaffMember.id` in `X-User-ID`,
and an `Athlete`/`Guardian` acts with the athlete's own `id`.  Helpers therefore
build those headers from the created entity, never from a shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_ORIGIN, TEST_DEFAULTS
from .factories import (
    assign_coach_payload,
    battery_results_payload,
    create_athlete_payload,
    create_certification_payload,
    create_clearance_document_payload,
    create_enrollment_payload,
    create_group_session_payload,
    create_injury_record_payload,
    create_membership_package_payload,
    create_program_block_payload,
    create_rts_plan_payload,
    create_staff_member_payload,
    create_team_contract_payload,
    create_test_session_payload,
    create_training_program_payload,
    screen_results_payload,
)
from .test_users import TEST_USERS, make_coach_headers

PD = TEST_USERS["performance_director_headers"]
FD = TEST_USERS["front_desk_headers"]
MP = TEST_USERS["medical_provider_headers"]


# ─── Tier 0: the logical clock ───────────────────────────────────────────────

def advance_clock(current_utc: str, headers=None) -> dict:
    """Advance the logical UTC clock and run the expiry sweep.  Returns the
    response body carrying current_utc, clearance_documents_expired_count and
    packages_expired_count."""
    return get_success_data(api_client.set_clock(current_utc, headers or PD))


# ─── Tier 0: reads used by composite setups ─────────────────────────────────

def fetch_athlete(athlete_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_athlete(athlete_id, headers or PD))


def fetch_group_session(group_session_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_group_session(group_session_id, headers or PD))


def fetch_enrollment(enrollment_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, headers or PD))


def fetch_membership_package(membership_package_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_membership_package(membership_package_id, headers or PD))


def fetch_team_contract(team_contract_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_team_contract(team_contract_id, headers or PD))


def fetch_staff_member(staff_member_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_staff_member(staff_member_id, headers or PD))


def fetch_certification(certification_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_certification(certification_id, headers or PD))


def fetch_rts_plan(rts_plan_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_rts_plan(rts_plan_id, headers or PD))


def fetch_test_session(test_session_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_test_session(test_session_id, headers or PD))


def fetch_clearance_document(clearance_document_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_clearance_document(clearance_document_id, headers or PD))


def fetch_training_program(training_program_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_training_program(training_program_id, headers or PD))


def fetch_program_block(program_block_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_program_block(program_block_id, headers or PD))


def fetch_progress_report(athlete_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_progress_report(athlete_id, headers or PD))


# ─── Tier 1: coaching staff in a known credential state ─────────────────────

def create_compliant_coach(full_name="Sol Rivera", role_title="HEAD_COACH",
                           liability_insurance_expires_on=None,
                           cert_code="CPR_AED", issued_on=None, cert_expires_on=None,
                           ceu_credits_required=6):
    """Register a staff member and give them one live certification, so their
    credential_status derives to a non-lapsed value.

    Returns (staff_member, certification, coach_headers) where coach_headers
    carries the staff member's own id as X-User-ID.
    """
    staff = get_success_data(api_client.create_staff_member(
        create_staff_member_payload(
            full_name=full_name,
            role_title=role_title,
            liability_insurance_expires_on=(
                liability_insurance_expires_on or TEST_DEFAULTS["INSURANCE_EXPIRES_ON"]),
        ), PD))
    certification = get_success_data(api_client.create_certification(
        create_certification_payload(
            staff["id"],
            cert_code=cert_code,
            issued_on=issued_on or TEST_DEFAULTS["CERT_ISSUED_ON"],
            expires_on=cert_expires_on or TEST_DEFAULTS["CERT_EXPIRES_ON"],
            ceu_credits_required=ceu_credits_required,
        ), PD))
    return staff, certification, make_coach_headers(staff["id"])


def create_two_compliant_coaches(first_name="Petra Vogel", second_name="Job Adeyemi"):
    """Two independently certified coaches.  Returns
    ((staff_a, headers_a), (staff_b, headers_b))."""
    staff_a, _, headers_a = create_compliant_coach(full_name=first_name)
    staff_b, _, headers_b = create_compliant_coach(
        full_name=second_name, role_title="PERFORMANCE_COACH")
    return (staff_a, headers_a), (staff_b, headers_b)


# ─── Tier 2: athletes walked through the movement screen ────────────────────

def register_athlete(**overrides) -> dict:
    """Register one athlete at intake.  Arrives PENDING_INTAKE / SCREEN_PENDING."""
    return get_success_data(api_client.create_athlete(
        create_athlete_payload(**overrides), FD))


def run_movement_screen(athlete_id: str, coach_headers: dict, scores=None) -> dict:
    """Open a MOVEMENT_SCREEN, append the five screen codes and finalize it.
    Returns the finalized test session."""
    session = get_success_data(api_client.create_test_session(
        create_test_session_payload(athlete_id, "MOVEMENT_SCREEN"), coach_headers))
    get_success_data(api_client.submit_test_results(
        session["id"], screen_results_payload(scores), coach_headers))
    return get_success_data(api_client.finalize_test_session(session["id"], coach_headers))


def setup_screened_athlete(scores=None, athlete_overrides=None, coach_name="Cass Mwangi"):
    """Register a coach and an athlete, then finalize the athlete's intake movement
    screen.  The first finalized screen also moves the athlete to ACTIVE.

    Returns (athlete, staff_member, coach_headers) with the athlete re-read after
    the screen so its derived clearance and risk score are visible.
    """
    staff, _, coach_headers = create_compliant_coach(full_name=coach_name)
    athlete = register_athlete(**(athlete_overrides or {}))
    run_movement_screen(athlete["id"], coach_headers, scores)
    return fetch_athlete(athlete["id"]), staff, coach_headers


def setup_cleared_athlete(athlete_overrides=None, coach_name="Cass Mwangi"):
    """A perfect screen (every code scored 3) yields a risk_score of 0.00, so the
    athlete lands CLEARED and ACTIVE.  Returns (athlete, staff, coach_headers)."""
    return setup_screened_athlete(scores=None, athlete_overrides=athlete_overrides,
                                  coach_name=coach_name)


def setup_restricted_athlete(athlete_overrides=None, coach_name="Cass Mwangi"):
    """A screen scoring 1/1/1/0/0 gives a raw total of 3 and no asymmetry, so the
    deficit is 12 and the risk_score lands exactly on the restriction threshold.
    Returns (athlete, staff, coach_headers)."""
    scores = {"OH_SQUAT": 1, "HURDLE_STEP": 1, "INLINE_LUNGE": 1,
              "SL_HOP_L": 0, "SL_HOP_R": 0}
    return setup_screened_athlete(scores=scores, athlete_overrides=athlete_overrides,
                                  coach_name=coach_name)


def finalize_performance_battery(athlete_id: str, coach_headers: dict, values: dict) -> dict:
    """Open a PERFORMANCE_BATTERY, append the given metric rows and finalize it.
    Returns the finalized test session."""
    session = get_success_data(api_client.create_test_session(
        create_test_session_payload(athlete_id, "PERFORMANCE_BATTERY"), coach_headers))
    get_success_data(api_client.submit_test_results(
        session["id"], battery_results_payload(values), coach_headers))
    return get_success_data(api_client.finalize_test_session(session["id"], coach_headers))


# Metric values that score exactly 60.0 composite for a BASKETBALL GUARD in the
# 15-16 band: CMJ 42.5 -> 60.0, SPRINT 1.74 -> 60.0, IMTP 1850 -> 60.0.
BATTERY_AT_COMPETITION_MINIMUM = {"CMJ_CM": 42.5, "SPRINT_10M_S": 1.74, "IMTP_N": 1850}


def setup_athlete_at_competition_readiness(athlete_overrides=None):
    """Screen an athlete clear, then finalize a battery whose composite is exactly
    the competition readiness minimum.  Returns (athlete, staff, coach_headers,
    battery_session)."""
    athlete, staff, coach_headers = setup_cleared_athlete(
        athlete_overrides=athlete_overrides)
    battery = finalize_performance_battery(
        athlete["id"], coach_headers, BATTERY_AT_COMPETITION_MINIMUM)
    return fetch_athlete(athlete["id"]), staff, coach_headers, battery


# ─── Tier 3: group sessions and staffing ────────────────────────────────────

def schedule_group_session(headers=None, **overrides) -> dict:
    """Schedule one group session.  Arrives SCHEDULED / STAFF_PENDING."""
    return get_success_data(api_client.create_group_session(
        create_group_session_payload(**overrides), headers or PD))


def assign_coach_to_session(group_session_id: str, staff_member_id: str,
                            coach_role="LEAD", headers=None) -> dict:
    """Assign a coach, reading the session's live version for the concurrency guard.
    Returns the session as the assignment reports it."""
    session = fetch_group_session(group_session_id)
    return get_success_data(api_client.assign_coach(
        group_session_id,
        assign_coach_payload(staff_member_id, session["version"], coach_role),
        headers or PD))


def setup_session_with_coach(staff_member_id: str, **session_overrides) -> dict:
    """Schedule a session and assign one coach to it.  Returns the staffed session."""
    session = schedule_group_session(**session_overrides)
    return assign_coach_to_session(session["id"], staff_member_id)


def setup_onsite_session_with_coach(staff_member_id: str,
                                    start_at="2026-08-10T10:00:00Z",
                                    end_at="2026-08-10T11:00:00Z",
                                    **session_overrides) -> dict:
    """The most common session shape: one ONSITE hour with three stations, a
    ten-athlete roster cap and a single assigned coach."""
    return setup_session_with_coach(
        staff_member_id, start_at=start_at, end_at=end_at, **session_overrides)


def lock_session_roster(group_session_id: str, headers=None) -> dict:
    """Lock the roster, which distributes stations.  Returns the locked session."""
    return get_success_data(api_client.lock_roster(group_session_id, headers or PD))


def start_session_at_start_at(session: dict, coach_headers: dict) -> dict:
    """Advance the logical clock to the session's own start_at, then start it.
    Returns the IN_PROGRESS session."""
    advance_clock(session["start_at"])
    return get_success_data(
        api_client.start_group_session(session["id"], coach_headers))


def complete_session(group_session_id: str, coach_headers: dict) -> dict:
    """Complete an IN_PROGRESS session.  Returns the COMPLETED session."""
    return get_success_data(
        api_client.complete_group_session(group_session_id, coach_headers))


def deliver_session(session: dict, coach_headers: dict, attend_enrollment_ids=None,
                    lock_first=True) -> dict:
    """Walk one scheduled session all the way to COMPLETED: lock the roster,
    advance the clock to start_at, start it, mark the named enrollments attended,
    and complete it.  Returns the completed session."""
    if lock_first:
        lock_session_roster(session["id"])
    start_session_at_start_at(session, coach_headers)
    for enrollment_id in (attend_enrollment_ids or []):
        get_success_data(api_client.attend_enrollment(enrollment_id, coach_headers))
    return complete_session(session["id"], coach_headers)


# ─── Tier 4: funding instruments ────────────────────────────────────────────

def sell_package(athlete_id: str, **overrides) -> dict:
    """Sell a membership package.  Opens ACTIVE with every credit remaining."""
    return get_success_data(api_client.create_membership_package(
        create_membership_package_payload(athlete_id, **overrides), FD))


def create_draft_contract(**overrides) -> dict:
    """Create a team contract.  Arrives DRAFT with its slots seeded but unspendable."""
    return get_success_data(api_client.create_team_contract(
        create_team_contract_payload(**overrides), PD))


def create_active_contract(**overrides) -> dict:
    """Create and activate a team contract, so its slots become spendable."""
    contract = create_draft_contract(**overrides)
    return get_success_data(api_client.activate_team_contract(contract["id"], PD))


def link_athlete_to_contract(team_contract_id: str, athlete_id: str, headers=None) -> dict:
    """Link a roster athlete to an active contract, writing team_contract_id on the
    athlete and putting contract slots at the head of their funding waterfall."""
    return get_success_data(api_client.link_contract_athlete(
        team_contract_id, {"athlete_id": athlete_id}, headers or PD))


def setup_contract_linked_athlete(contract_overrides=None, athlete_overrides=None,
                                  coach_name="Talia Brooks"):
    """A screened, cleared athlete linked to an ACTIVE team contract.
    Returns (athlete, staff, coach_headers, contract)."""
    athlete, staff, coach_headers = setup_cleared_athlete(
        athlete_overrides=athlete_overrides, coach_name=coach_name)
    contract = create_active_contract(**(contract_overrides or {}))
    link_athlete_to_contract(contract["id"], athlete["id"])
    return fetch_athlete(athlete["id"]), staff, coach_headers, contract


# ─── Tier 5: enrollment ─────────────────────────────────────────────────────

def enroll_athlete(athlete_id: str, group_session_id: str, headers=None,
                   **overrides) -> dict:
    """Book an enrollment, running the funding waterfall."""
    return get_success_data(api_client.create_enrollment(
        create_enrollment_payload(athlete_id, group_session_id, **overrides),
        headers or FD))


def setup_enrolled_athlete_on_session(staff_member_id: str, athlete_id: str,
                                      session_overrides=None, enrollment_overrides=None):
    """One staffed session with one reserved enrollment on it.
    Returns (session, enrollment)."""
    session = setup_session_with_coach(staff_member_id, **(session_overrides or {}))
    enrollment = enroll_athlete(athlete_id, session["id"],
                                **(enrollment_overrides or {}))
    return fetch_group_session(session["id"]), enrollment


# ─── Tier 6: accumulation / threshold targeting ─────────────────────────────

def drive_no_show_ladder(athlete_id: str, staff_member_id: str, coach_headers: dict,
                         session_windows, enrollment_overrides=None):
    """Take an athlete through one no-show per session window, so their rolling
    `no_show_strikes` climbs the fee ladder.

    Every session is scheduled and every enrollment booked before the clock moves,
    because enrollment closes once a session's start_at is reached.  The windows are
    then walked in ascending order: the clock advances to each start_at, the session
    starts, and the athlete's enrollment is marked a no-show.

    Returns (sessions, no_show_enrollments) — both lists in window order, each
    enrollment as the no-show transition reported it.
    """
    sessions, enrollments = [], []
    for start_at, end_at in session_windows:
        session = setup_session_with_coach(staff_member_id, start_at=start_at,
                                           end_at=end_at)
        enrollment = enroll_athlete(athlete_id, session["id"],
                                    **(enrollment_overrides or {}))
        lock_session_roster(session["id"])
        sessions.append(fetch_group_session(session["id"]))
        enrollments.append(enrollment)

    no_shows = []
    for session, enrollment in zip(sessions, enrollments):
        advance_clock(session["start_at"])
        get_success_data(api_client.start_group_session(session["id"], coach_headers))
        no_shows.append(get_success_data(
            api_client.no_show_enrollment(enrollment["id"], coach_headers)))
    return sessions, no_shows


def setup_athlete_with_two_strikes(athlete_overrides=None,
                                    windows=(("2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z"),
                                             ("2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z"))):
    """A cleared athlete carrying exactly two no-show strikes, so the next no-show
    is the third and fires the automatic suspension chain.

    Returns (athlete, staff, coach_headers, no_show_enrollments).
    """
    athlete, staff, coach_headers = setup_cleared_athlete(
        athlete_overrides=athlete_overrides)
    _, no_shows = drive_no_show_ladder(athlete["id"], staff["id"], coach_headers,
                                       list(windows))
    return fetch_athlete(athlete["id"]), staff, coach_headers, no_shows


def setup_lapsing_coach_on_future_session(cert_expires_on="2026-08-15",
                                          review_clock="2026-09-01T00:00:00Z",
                                          session_start_at="2026-10-01T10:00:00Z",
                                          session_end_at="2026-10-01T11:00:00Z",
                                          run_review=False):
    """A coach whose only certification expires before a later logical date, already
    assigned to a future session that holds one reserved, station-assigned athlete.

    Credential review is the only operation that reconciles certifications against
    the clock, so the cascade does not fire until it is run.  With
    `run_review=False` the caller runs it themselves as the trigger under test.

    Returns (staff, certification, coach_headers, session, athlete, enrollment).
    """
    staff, certification, coach_headers = create_compliant_coach(
        full_name="Nia Okafor", cert_code="CSCS", cert_expires_on=cert_expires_on)
    athlete, _, screen_coach_headers = setup_cleared_athlete(coach_name="Reed Salas")
    session = setup_session_with_coach(staff["id"], start_at=session_start_at,
                                       end_at=session_end_at)
    enrollment = enroll_athlete(athlete["id"], session["id"])
    lock_session_roster(session["id"])
    advance_clock(review_clock)
    if run_review:
        get_success_data(api_client.credential_review(staff["id"], PD))
    return (staff, certification, coach_headers, fetch_group_session(session["id"]),
            fetch_athlete(athlete["id"]), fetch_enrollment(enrollment["id"]))


# ─── Tier 7: periodized programs ────────────────────────────────────────────

def create_draft_program(athlete_id: str, **overrides) -> dict:
    """Create a DRAFT training program for one athlete."""
    return get_success_data(api_client.create_training_program(
        create_training_program_payload(athlete_id, **overrides), PD))


def append_program_block(training_program_id: str, headers=None, **overrides) -> dict:
    """Append the next block, reading the program's live version for the guard."""
    program = fetch_training_program(training_program_id)
    return get_success_data(api_client.create_program_block(
        training_program_id,
        create_program_block_payload(program["version"], **overrides),
        headers or PD))


def setup_activatable_program(athlete_id: str, blocks=None, **program_overrides):
    """A DRAFT program carrying a valid unbroken chain that satisfies every
    activation precondition: at least two blocks, one null-predecessor root,
    contiguous weeks and at least one COMPETITION block.

    Returns (program, blocks) with the program re-read after the last append.
    """
    program = create_draft_program(athlete_id, **program_overrides)
    specs = blocks or [
        {"phase": "GENERAL_PREP", "start_week": 1, "end_week": 4,
         "target_intensity_pct": 70, "weekly_volume_units": 100.0},
        {"phase": "COMPETITION", "start_week": 5, "end_week": 8,
         "target_intensity_pct": 90, "weekly_volume_units": 80.0},
    ]
    created = []
    previous_id = None
    for spec in specs:
        payload = dict(spec)
        if previous_id is not None and "predecessor_block_id" not in payload:
            payload["predecessor_block_id"] = previous_id
        block = append_program_block(program["id"], **payload)
        created.append(block)
        previous_id = block["id"]
    return fetch_training_program(program["id"]), created


def setup_active_program(athlete_id: str, blocks=None, **program_overrides):
    """A program walked through to ACTIVE, with its blocks PINNED and its
    planned_load_units computed.  Returns (program, blocks)."""
    program, created = setup_activatable_program(athlete_id, blocks, **program_overrides)
    activated = get_success_data(
        api_client.activate_training_program(program["id"], PD))
    return activated, created


# ─── Tier 8: return-to-sport progressions and clearance documents ───────────

def record_rts_injury(athlete_id: str, **overrides) -> dict:
    """Record an ACTIVE_REHAB injury eligible to anchor a return-to-sport plan."""
    payload = create_injury_record_payload(athlete_id, **overrides)
    payload.setdefault("rts_required", True)
    return get_success_data(api_client.create_injury_record(payload, MP))


def open_rts_plan(athlete_id: str, injury_record_id: str, **overrides) -> dict:
    """Open a return-to-sport plan.  Opens STAGE_ACTIVE at stage 1 and drives the
    athlete's training_clearance from CLEARED to RESTRICTED."""
    return get_success_data(api_client.create_rts_plan(
        create_rts_plan_payload(injury_record_id=injury_record_id,
                                athlete_id=athlete_id, **overrides), MP))


def setup_rts_plan(athlete_overrides=None, coach_name="Iris Halden", **plan_overrides):
    """A cleared athlete with an open return-to-sport plan against a fresh
    rts_required injury record.

    Returns (athlete, staff, coach_headers, injury_record, plan) with the athlete
    re-read so its RESTRICTED clearance and penalised readiness are visible.
    """
    athlete, staff, coach_headers = setup_cleared_athlete(
        athlete_overrides=athlete_overrides, coach_name=coach_name)
    injury = record_rts_injury(athlete["id"])
    plan = open_rts_plan(athlete["id"], injury["id"], **plan_overrides)
    return fetch_athlete(athlete["id"]), staff, coach_headers, injury, plan


def open_and_finalize_stage_test(rts_plan_id: str, coach_headers: dict,
                                 values=None) -> dict:
    """Open the criterion test for the plan's current stage, then populate and
    finalize it, leaving the plan STAGE_TESTING and eligible for a decision.
    Returns the finalized stage test session."""
    session = get_success_data(api_client.open_stage_test(rts_plan_id, coach_headers))
    get_success_data(api_client.submit_test_results(
        session["id"],
        battery_results_payload(values or BATTERY_AT_COMPETITION_MINIMUM),
        coach_headers))
    return get_success_data(api_client.finalize_test_session(session["id"], coach_headers))


def setup_plan_at_stage_testing(athlete_overrides=None, **plan_overrides):
    """A plan sitting at STAGE_TESTING with its named stage test already FINALIZED,
    which is the state a stage decision requires.

    Returns (athlete, staff, coach_headers, injury_record, plan, stage_test).
    """
    athlete, staff, coach_headers, injury, plan = setup_rts_plan(
        athlete_overrides=athlete_overrides, **plan_overrides)
    stage_test = open_and_finalize_stage_test(plan["id"], coach_headers)
    return (athlete, staff, coach_headers, injury,
            fetch_rts_plan(plan["id"]), stage_test)


def create_clearance_document(athlete_id: str, document_type: str,
                              expires_on="2026-12-31", **overrides) -> dict:
    """Create a PENDING clearance document."""
    return get_success_data(api_client.create_clearance_document(
        create_clearance_document_payload(athlete_id, document_type, expires_on,
                                          **overrides), MP))


def create_signed_stage_clearance(athlete_id: str, rts_plan_id: str, stage_number: int,
                                  expires_on="2026-12-31",
                                  provider_license_id="LIC-1", headers=None) -> dict:
    """Create and sign the STAGE_CLEARANCE that a PASS decision at this stage
    requires.  Returns the signed document."""
    document = create_clearance_document(
        athlete_id, "STAGE_CLEARANCE", expires_on,
        rts_plan_id=rts_plan_id, stage_number=stage_number)
    return get_success_data(api_client.sign_clearance_document(
        document["id"], {"provider_license_id": provider_license_id}, headers or MP))


def setup_plan_ready_for_pass(athlete_overrides=None, **plan_overrides):
    """A plan at STAGE_TESTING with a finalized stage test AND a signed stage
    clearance for the current stage, so a PASS decision has every precondition.

    Returns (athlete, staff, coach_headers, plan, stage_test, clearance_document).
    """
    athlete, staff, coach_headers, _injury, plan, stage_test = setup_plan_at_stage_testing(
        athlete_overrides=athlete_overrides, **plan_overrides)
    document = create_signed_stage_clearance(
        athlete["id"], plan["id"], plan["current_stage"])
    return athlete, staff, coach_headers, plan, stage_test, document


def setup_athlete_on_medical_hold(athlete_overrides=None, coach_name="Vera Lund"):
    """A cleared athlete driven to MEDICAL_HOLD, from which only a signed
    MEDICAL_HOLD_RELEASE lifts them.  Returns (athlete, staff, coach_headers)."""
    athlete, staff, coach_headers = setup_cleared_athlete(
        athlete_overrides=athlete_overrides, coach_name=coach_name)
    get_success_data(api_client.medical_hold_athlete(
        athlete["id"], {"hold_reason": "Concussion protocol"}, MP))
    return fetch_athlete(athlete["id"]), staff, coach_headers
