"""Composite setup helpers.

Encapsulates the multi-step preambles that most test claims share, so tests can
focus on the assertion under test. Every fixture builds its preconditions from
scratch against an empty database using only PRD-declared endpoints, and uses
``get_success_data()`` (lenient) internally so setup failures surface as clear
"Setup step failed" errors.

Identity threading: after an entity-backed Coach / Member is created, any
ownership-gated call uses ``make_coach_headers(coach_id)`` /
``make_member_headers(member_id)`` with the real entity id, never the shared
fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .test_users import (
    TEST_USERS,
    make_coach_headers,
    make_member_headers,
)
from . import factories as f

ADMIN = TEST_USERS["program_admin_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]
BILLING = TEST_USERS["billing_agent_headers"]


# ─── Tier 0: primitive creators ───────────────────────
def create_program(**overrides) -> dict:
    """Create a program (ProgramAdmin). Returns the program resource."""
    return get_success_data(api.create_program(f.create_program_payload(**overrides), ADMIN))


def set_clock(program_id, to_iso8601) -> dict:
    return get_success_data(api.clock_set(program_id, f.clock_set_payload(to_iso8601), ADMIN))


def create_plan(program_id, **overrides) -> dict:
    return get_success_data(api.create_plan(f.create_plan_payload(program_id, **overrides), ADMIN))


def create_member(program_id, **overrides) -> dict:
    return get_success_data(api.create_member(f.create_member_payload(program_id, **overrides), ADMIN))


def create_coach(program_id, **overrides) -> dict:
    return get_success_data(api.create_coach(f.create_coach_payload(program_id, **overrides), ADMIN))


# ─── Tier 1: intake state progression ─────────────────
def create_approved_intake(member_id, weight_kg=95, comorbidity_count=0) -> dict:
    """DRAFT -> SUBMITTED -> UNDER_REVIEW -> APPROVED. Returns the APPROVED intake.

    The Member is the actor for create/submit (entity-backed identity threaded);
    the Clinician drives review/approve.
    """
    member_headers = make_member_headers(member_id)
    intake = get_success_data(
        api.create_intake(
            f.create_intake_payload(member_id, weight_kg=weight_kg, comorbidity_count=comorbidity_count),
            member_headers,
        )
    )
    iid = intake["id"]
    get_success_data(api.submit_intake(iid, {}, member_headers))
    get_success_data(api.start_review_intake(iid, CLINICIAN))
    return get_success_data(api.approve_intake(iid, CLINICIAN))


def create_intake_under_review(member_id, weight_kg=95, comorbidity_count=0) -> dict:
    """DRAFT -> SUBMITTED -> UNDER_REVIEW. Returns the UNDER_REVIEW intake."""
    member_headers = make_member_headers(member_id)
    intake = get_success_data(
        api.create_intake(
            f.create_intake_payload(member_id, weight_kg=weight_kg, comorbidity_count=comorbidity_count),
            member_headers,
        )
    )
    iid = intake["id"]
    get_success_data(api.submit_intake(iid, {}, member_headers))
    return get_success_data(api.start_review_intake(iid, CLINICIAN))


# ─── Tier 2: enrollment scaffolding ───────────────────
def create_pending_enrollment(
    program_id=None,
    plan_overrides=None,
    intake_weight_kg=95,
    comorbidity_count=0,
    enrollment_overrides=None,
) -> dict:
    """Build program(optional)+plan+member+APPROVED intake+PENDING_CLINICAL enrollment.

    Returns a dict with keys: program, plan, member, intake, enrollment.
    """
    plan_overrides = plan_overrides or {}
    enrollment_overrides = enrollment_overrides or {}
    program = create_program() if program_id is None else {"id": program_id}
    pid = program["id"]
    plan = create_plan(pid, **plan_overrides)
    member = create_member(pid)
    intake = create_approved_intake(member["id"], weight_kg=intake_weight_kg, comorbidity_count=comorbidity_count)
    enrollment = get_success_data(
        api.create_enrollment(
            f.create_enrollment_payload(member["id"], plan["id"], intake["id"], **enrollment_overrides),
            ADMIN,
        )
    )
    return {
        "program": program,
        "plan": plan,
        "member": member,
        "intake": intake,
        "enrollment": enrollment,
    }


def create_active_enrollment(
    plan_overrides=None,
    intake_weight_kg=95,
    comorbidity_count=0,
    enrollment_overrides=None,
    clock_iso=None,
) -> dict:
    """Build everything through clinical ACTIVE (cycle-0 invoice issued).

    Returns dict with: program, plan, member, intake, enrollment (post-activate,
    so .version is current), plus the activate response stored under
    ``enrollment``. If ``clock_iso`` is given, the program clock is set before
    activation so billing_anchor / period boundaries are deterministic.
    """
    ctx = create_pending_enrollment(
        plan_overrides=plan_overrides,
        intake_weight_kg=intake_weight_kg,
        comorbidity_count=comorbidity_count,
        enrollment_overrides=enrollment_overrides,
    )
    if clock_iso is not None:
        set_clock(ctx["program"]["id"], clock_iso)
    activated = get_success_data(api.activate_enrollment(ctx["enrollment"]["id"], ADMIN))
    ctx["enrollment"] = activated
    return ctx


def get_enrollment_version(enrollment_id) -> int:
    enr = get_success_data(api.get_enrollment(enrollment_id, ADMIN))
    return enr["version"]


def cycle0_invoice(enrollment_id) -> dict:
    """Return the cycle-0 invoice for an enrollment (the first listed invoice)."""
    data, _meta = _list_invoices(enrollment_id)
    for inv in data:
        if inv.get("cycle_index") == 0:
            return inv
    return data[0]


def _list_invoices(enrollment_id):
    resp = api.list_invoices(BILLING, params={"enrollment_id": enrollment_id})
    body = resp.json()
    return body["data"], body["meta"]


def list_invoices(enrollment_id):
    return _list_invoices(enrollment_id)


# ─── Tier 3: weigh-in accumulation (OCC-aware) ────────
def record_counted_weighin(enrollment_id, weight_kg, body_fat_pct=None, actor_headers=None):
    """Record a single counted weigh-in, re-reading the enrollment version first
    so the OCC check passes. Returns the weigh-in resource."""
    actor_headers = actor_headers or TEST_USERS["coach_headers"]
    version = get_enrollment_version(enrollment_id)
    overrides = {}
    if body_fat_pct is not None:
        overrides["body_fat_pct"] = body_fat_pct
    payload = f.create_weighin_payload(enrollment_id, weight_kg, version, **overrides)
    return get_success_data(api.create_weighin(payload, actor_headers))


def record_n_counted_weighins(enrollment_id, weights, actor_headers=None):
    """Record a series of counted weigh-ins (re-reading version each time)."""
    results = []
    for w in weights:
        results.append(record_counted_weighin(enrollment_id, w, actor_headers=actor_headers))
    return results


# ─── Tier 4: goals / milestones / coaching ────────────
def create_goal(enrollment_id, kind, target_weight_kg, actor_headers=None) -> dict:
    actor_headers = actor_headers or ADMIN
    return get_success_data(
        api.create_goal(f.create_goal_payload(enrollment_id, kind, target_weight_kg), actor_headers)
    )


def create_milestone(goal_id, threshold_pct, actor_headers=None) -> dict:
    actor_headers = actor_headers or ADMIN
    return get_success_data(
        api.create_milestone(f.create_milestone_payload(goal_id, threshold_pct), actor_headers)
    )


def assign_coach(enrollment_id, coach_id) -> dict:
    return get_success_data(
        api.create_coach_assignment(f.create_coach_assignment_payload(enrollment_id, coach_id), ADMIN)
    )


def open_thread(coach_assignment_id, coach_id, subject="hi") -> dict:
    """Open a message thread, acting as the entity-backed Coach owner."""
    return get_success_data(
        api.create_message_thread(
            f.create_message_thread_payload(coach_assignment_id, subject=subject),
            make_coach_headers(coach_id),
        )
    )


# ─── Tier 5: eligibility / Rx scaffolding ─────────────
def create_pending_eligibility(member_id, enrollment_id) -> dict:
    return get_success_data(
        api.create_eligibility(f.create_eligibility_payload(member_id, enrollment_id), CLINICIAN)
    )


def create_approved_eligibility(member_id, enrollment_id) -> dict:
    det = create_pending_eligibility(member_id, enrollment_id)
    return get_success_data(api.approve_eligibility(det["id"], CLINICIAN))


def create_requested_rx(enrollment_id, eligibility_determination_id) -> dict:
    return get_success_data(
        api.create_rx(f.create_rx_payload(enrollment_id, eligibility_determination_id), CLINICIAN)
    )


def setup_rx_enrollment_active(intake_weight_kg=95, comorbidity_count=0) -> dict:
    """RX-tier enrollment driven clinically ACTIVE via a full issued Rx path.

    program -> RX plan -> member -> APPROVED intake -> enrollment ->
    APPROVED eligibility -> requested Rx -> issued Rx (OCC version threaded) ->
    activate. Returns dict: program, plan, member, intake, enrollment, det, rx.
    """
    ctx = create_pending_enrollment(
        plan_overrides={"tier": "RX", "monthly_fee_cents": 9000},
        intake_weight_kg=intake_weight_kg,
        comorbidity_count=comorbidity_count,
    )
    enr_id = ctx["enrollment"]["id"]
    det = create_approved_eligibility(ctx["member"]["id"], enr_id)
    rx = create_requested_rx(enr_id, det["id"])
    version = get_enrollment_version(enr_id)
    get_success_data(api.issue_rx(rx["id"], f.issue_rx_payload(version), CLINICIAN))
    activated = get_success_data(api.activate_enrollment(enr_id, ADMIN))
    ctx["enrollment"] = activated
    ctx["det"] = det
    ctx["rx"] = rx
    return ctx
