"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database, so
each helper builds all of its preconditions from scratch using only
PRD-declared endpoints. Setup calls use the lenient ``get_success_data``
validator so setup breakage surfaces as a clear "Setup failed".
"""
from prd_bench_local_runner.testing import get_success_data

from .test_users import TEST_USERS
from . import factories as F

PA = TEST_USERS["program_admin_headers"]
CM = TEST_USERS["case_manager_headers"]


# --------------------------------------------------------------------------
# Atomic building blocks
# --------------------------------------------------------------------------
def set_clock(api, iso: str):
    return get_success_data(api.set_clock(iso, PA))


def create_program(api, budget=100000, nrt_allotted=3, **over) -> dict:
    payload = F.create_employer_program_payload(
        budget_total_cents=budget, nrt_courses_allotted=nrt_allotted, **over
    )
    return get_success_data(api.create_employer_program(payload, PA))


def create_coach(api, languages=None, full_name="Coach EN") -> dict:
    payload = F.create_coach_payload(
        full_name=full_name, languages=languages if languages is not None else ["EN"]
    )
    return get_success_data(api.create_coach(payload, PA))


def create_participant(api, cpd=10, program_id=None, language="EN", **over) -> dict:
    payload = F.create_participant_payload(
        cigarettes_per_day=cpd, primary_language=language, **over
    )
    if program_id is not None:
        payload["employer_program_id"] = program_id
    return get_success_data(api.create_participant(payload, CM))


def create_enrollment(api, participant_id: str) -> dict:
    return get_success_data(api.create_enrollment(participant_id, {}, CM))


def submit_readiness(api, enrollment_id, motivation=6, confidence=6, prior=0) -> dict:
    payload = F.create_readiness_assessment_payload(
        motivation_score=motivation, confidence_score=confidence, prior_quit_attempts=prior
    )
    return get_success_data(api.create_readiness_assessment(enrollment_id, payload, CM))


def activate(api, enrollment_id) -> dict:
    return get_success_data(api.activate_enrollment(enrollment_id, CM))


def create_quit_attempt(api, enrollment_id, quit_date="2026-06-02T00:00:00Z",
                        method="COLD_TURKEY") -> dict:
    payload = F.create_quit_attempt_payload(quit_date=quit_date, method=method)
    return get_success_data(api.create_quit_attempt(enrollment_id, payload, CM))


def record_follow_up(api, enrollment_id, day, abstinent) -> dict:
    payload = F.create_follow_up_outcome_payload(day=day, abstinent=abstinent)
    return get_success_data(api.create_follow_up_outcome(enrollment_id, payload, CM))


def create_referral(api, enrollment_id, payload=None, headers=None) -> dict:
    payload = payload if payload is not None else F.create_referral_payload()
    return get_success_data(api.create_referral(enrollment_id, payload, headers or CM))


def read_program(api, program_id) -> dict:
    return get_success_data(api.get_employer_program(program_id, PA))


def read_program_version(api, program_id) -> int:
    return read_program(api, program_id)["version"]


def read_enrollment(api, enrollment_id) -> dict:
    return get_success_data(api.get_enrollment(enrollment_id, CM))


# --------------------------------------------------------------------------
# Tier 1/2: enrollment state progression
# --------------------------------------------------------------------------
def setup_pending_enrollment(api, cpd=10, language="EN", sponsored=False,
                             budget=100000, nrt_allotted=3, clock=None):
    """Participant + PENDING_ASSESSMENT enrollment (no readiness submitted)."""
    if clock is not None:
        set_clock(api, clock)
    program = create_program(api, budget=budget, nrt_allotted=nrt_allotted) if sponsored else None
    program_id = program["id"] if program else None
    participant = create_participant(api, cpd=cpd, program_id=program_id, language=language)
    enrollment = create_enrollment(api, participant["id"])
    return {
        "program": program,
        "program_id": program_id,
        "participant": participant,
        "participant_id": participant["id"],
        "enrollment": enrollment,
        "enrollment_id": enrollment["id"],
    }


def setup_active_enrollment(api, cpd=10, language="EN", sponsored=False,
                            budget=100000, nrt_allotted=3, clock=None,
                            motivation=8, confidence=8, prior=0):
    """Participant + enrollment walked to ACTIVE (readiness PASS + activate).

    Default motivation/confidence of 8 keep readiness_score at or above the
    pass threshold for any cigarettes_per_day tier (worst case 8+8-2 == 14)."""
    ctx = setup_pending_enrollment(
        api, cpd=cpd, language=language, sponsored=sponsored,
        budget=budget, nrt_allotted=nrt_allotted, clock=clock,
    )
    submit_readiness(api, ctx["enrollment_id"], motivation, confidence, prior)
    ctx["enrollment"] = activate(api, ctx["enrollment_id"])
    return ctx


# --------------------------------------------------------------------------
# Tier 3/4: quit-attempt + abstinence lifecycle
# --------------------------------------------------------------------------
def setup_seven_day_achieved(api, budget=100000, cpd=10, clock_start="2026-06-01T00:00:00Z"):
    """Sponsored ACTIVE enrollment -> QUIT_DATE_SET award -> 7-day abstinent
    (QuitAttempt QUIT_ACHIEVED + SEVEN award). incentive_earned 5000, budget 95000."""
    ctx = setup_active_enrollment(api, cpd=cpd, sponsored=True, budget=budget, clock=clock_start)
    qa = create_quit_attempt(api, ctx["enrollment_id"], "2026-06-02T00:00:00Z", "COLD_TURKEY")
    set_clock(api, "2026-06-09T00:00:00Z")
    record_follow_up(api, ctx["enrollment_id"], 7, True)
    ctx["quit_attempt"] = qa
    ctx["quit_attempt_id"] = qa["id"]
    return ctx


def setup_completed_enrollment(api, budget=100000, cpd=10):
    """Full lifecycle through COMPLETED via 30-day continuous abstinence.
    Awards ENROLLMENT/QUIT_DATE_SET/SEVEN/THIRTY all PAID; provisional 10000."""
    ctx = setup_active_enrollment(api, cpd=cpd, sponsored=True, budget=budget,
                                  clock="2026-06-01T00:00:00Z")
    qa = create_quit_attempt(api, ctx["enrollment_id"], "2026-06-02T00:00:00Z", "COLD_TURKEY")
    set_clock(api, "2026-06-09T00:00:00Z")
    record_follow_up(api, ctx["enrollment_id"], 7, True)
    set_clock(api, "2026-07-02T00:00:00Z")
    record_follow_up(api, ctx["enrollment_id"], 30, True)
    ctx["quit_attempt"] = qa
    ctx["quit_attempt_id"] = qa["id"]
    return ctx


# --------------------------------------------------------------------------
# Tier 3: NRT shipment progression
# --------------------------------------------------------------------------
_SHIP_CHAIN = ["REQUESTED", "APPROVED", "SHIPPED", "DELIVERED"]


def setup_shipment_at(api, target_status="REQUESTED", nrt_allotted=3, cpd=15,
                      budget=100000, sponsored=True, with_quit_attempt=True,
                      medication="PATCH", course_start="2026-06-02T00:00:00Z",
                      course_end="2026-06-30T00:00:00Z", clock="2026-06-01T00:00:00Z"):
    """ACTIVE enrollment with one NRT shipment driven to ``target_status``
    (one of REQUESTED, APPROVED, SHIPPED, DELIVERED)."""
    ctx = setup_active_enrollment(api, cpd=cpd, sponsored=sponsored, budget=budget,
                                  nrt_allotted=nrt_allotted, clock=clock)
    if with_quit_attempt:
        create_quit_attempt(api, ctx["enrollment_id"], "2026-06-02T00:00:00Z", "NRT_ASSISTED")
    payload = F.create_nrt_shipment_payload(
        medication_type=medication, course_start_date=course_start, course_end_date=course_end
    )
    shipment = get_success_data(api.create_nrt_shipment(ctx["enrollment_id"], payload, CM))
    target_index = _SHIP_CHAIN.index(target_status)
    for step in _SHIP_CHAIN[1:target_index + 1]:
        shipment = get_success_data(
            api.transition_nrt_shipment(shipment["id"], {"to_status": step}, CM)
        )
    ctx["shipment"] = shipment
    ctx["shipment_id"] = shipment["id"]
    return ctx


# --------------------------------------------------------------------------
# Tier 2: enrollment with children for the disenroll branch test
# --------------------------------------------------------------------------
def setup_active_with_children(api):
    """Non-sponsored ACTIVE enrollment with a COMMITTED quit attempt, a
    SCHEDULED coaching call (EN coach), and an OPEN referral."""
    set_clock(api, "2026-06-01T00:00:00Z")
    coach = create_coach(api, languages=["EN"], full_name="Coach EN")
    ctx = setup_active_enrollment(api, cpd=10, sponsored=False)
    qa = create_quit_attempt(api, ctx["enrollment_id"], "2026-06-02T00:00:00Z", "COLD_TURKEY")
    call_payload = F.create_coaching_call_payload(
        coach_id=coach["id"], scheduled_start="2026-06-02T10:00:00Z", duration_minutes=30
    )
    call = get_success_data(api.create_coaching_call(ctx["enrollment_id"], call_payload, CM))
    ref = get_success_data(api.create_referral(ctx["enrollment_id"], F.create_referral_payload(), CM))
    ctx["coach"] = coach
    ctx["quit_attempt"] = qa
    ctx["quit_attempt_id"] = qa["id"]
    ctx["coaching_call"] = call
    ctx["coaching_call_id"] = call["id"]
    ctx["referral"] = ref
    ctx["referral_id"] = ref["id"]
    return ctx


# --------------------------------------------------------------------------
# Tier 2: ACTIVE enrollment with an EN coach, for scheduling tests
# --------------------------------------------------------------------------
def setup_active_enrollment_with_coach(api, coach_languages=None, cpd=10,
                                       participant_language="EN",
                                       clock="2026-06-01T00:00:00Z"):
    """ACTIVE enrollment + a coach. clock defaults to 2026-06-01."""
    set_clock(api, clock)
    coach = create_coach(api, languages=coach_languages if coach_languages is not None else ["EN"])
    ctx = setup_active_enrollment(api, cpd=cpd, language=participant_language, sponsored=False)
    ctx["coach"] = coach
    ctx["coach_id"] = coach["id"]
    return ctx
