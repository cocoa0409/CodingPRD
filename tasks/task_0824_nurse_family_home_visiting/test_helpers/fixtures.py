"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface as
clear "setup failed" errors rather than confusing assertion failures.

Identity threading: HomeVisitNurse and Supervisor are entity-backed roles, so every
ownership-gated call is issued with make_nurse_headers(nurse.id) /
make_supervisor_headers(supervisor.id) — never the shared constant.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_nurse_payload,
    create_supervisor_payload,
    create_client_payload,
    create_enrollment_payload,
    record_birth_payload,
    create_assignment_payload,
    create_visit_payload,
    complete_visit_payload,
    create_referral_payload,
    create_supervision_session_payload,
)
from .test_users import (
    TEST_USERS,
    make_nurse_headers,
    make_supervisor_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
INTAKE = TEST_USERS["intake_headers"]


# ─── Logical clock ────────────────────────────────────
def set_clock(to_iso8601: str):
    """Set the logical clock to the given instant."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 0: single-entity creators ───────────────────
def create_nurse(full_name="Test Nurse", credential_type="RN", **overrides):
    payload = create_nurse_payload(
        full_name=full_name, credential_type=credential_type, **overrides
    )
    return get_success_data(api_client.create_nurse(payload, ADMIN))


def create_supervisor(full_name="Test Supervisor", **overrides):
    payload = create_supervisor_payload(full_name=full_name, **overrides)
    return get_success_data(api_client.create_supervisor(payload, ADMIN))


def create_client(full_name="Test Mother", gestational_age_weeks=20, **overrides):
    payload = create_client_payload(
        full_name=full_name, gestational_age_weeks=gestational_age_weeks, **overrides
    )
    return get_success_data(api_client.create_client(payload, INTAKE))


def record_consent(client_id: str):
    return get_success_data(api_client.record_consent(client_id, INTAKE))


def create_prospect_enrollment(client_id: str):
    return get_success_data(
        api_client.create_enrollment(create_enrollment_payload(client_id), INTAKE)
    )


def activate_enrollment(enrollment_id: str):
    """PROSPECT -> ENROLLED. Returns the enrollment (carries the post-activation version)."""
    return get_success_data(api_client.activate_enrollment(enrollment_id, INTAKE))


def get_enrollment(enrollment_id: str):
    return get_success_data(api_client.get_enrollment(enrollment_id, INTAKE))


def get_nurse(nurse_id: str):
    return get_success_data(api_client.get_nurse(nurse_id, ADMIN))


def create_assignment(enrollment_id, nurse_id, supervisor_id, expected_version, high_needs=False):
    payload = create_assignment_payload(
        enrollment_id, nurse_id, expected_version, high_needs=high_needs
    )
    return get_success_data(
        api_client.create_assignment(payload, make_supervisor_headers(supervisor_id))
    )


# ─── Tier 1: consented + enrolled client (no assignment) ──
def setup_enrolled_enrollment(
    gestational_age_weeks=20, nurse_full_name="Test Nurse", nurse_overrides=None
):
    """Consent + enrollment + activation (status ENROLLED, never assigned so not ACTIVE).

    Returns a namespace with nurse, supervisor, client, enrollment, and convenience
    headers. The enrollment carries its post-activation `version`.
    """
    nurse = create_nurse(full_name=nurse_full_name, **(nurse_overrides or {}))
    supervisor = create_supervisor()
    client = create_client(gestational_age_weeks=gestational_age_weeks)
    record_consent(client["id"])
    enrollment = create_prospect_enrollment(client["id"])
    enrollment = activate_enrollment(enrollment["id"])
    return SimpleNamespace(
        nurse=nurse,
        nurse_id=nurse["id"],
        nurse_headers=make_nurse_headers(nurse["id"]),
        supervisor=supervisor,
        supervisor_id=supervisor["id"],
        supervisor_headers=make_supervisor_headers(supervisor["id"]),
        client=client,
        client_id=client["id"],
        enrollment=enrollment,
        enrollment_id=enrollment["id"],
        enrollment_version=enrollment["version"],
    )


# ─── Tier 2: active enrollment (assigned to a nurse) ──────
def setup_active_enrollment(
    gestational_age_weeks=20, high_needs=False, nurse_overrides=None
):
    """Consent + enrollment + activation + first assignment => enrollment ACTIVE.

    Returns a namespace with nurse, supervisor, client, the (refreshed, ACTIVE)
    enrollment, the assignment, and convenience headers.
    """
    ctx = setup_enrolled_enrollment(
        gestational_age_weeks=gestational_age_weeks, nurse_overrides=nurse_overrides
    )
    assignment = create_assignment(
        ctx.enrollment_id,
        ctx.nurse_id,
        ctx.supervisor_id,
        ctx.enrollment_version,
        high_needs=high_needs,
    )
    ctx.assignment = assignment
    ctx.assignment_id = assignment["id"]
    ctx.enrollment = get_enrollment(ctx.enrollment_id)  # now ACTIVE
    ctx.enrollment_version = ctx.enrollment["version"]
    return ctx


# ─── Tier 3: visit helpers on an active enrollment ────────
def schedule_visit(
    ctx,
    phase="PREGNANCY",
    target_date="2026-06-01",
    scheduled_start="2026-06-01T09:00:00Z",
    scheduled_end="2026-06-01T10:00:00Z",
    nurse_id=None,
    nurse_headers=None,
):
    """Schedule a visit for ctx.enrollment conducted by ctx.nurse (default)."""
    nurse_id = nurse_id or ctx.nurse_id
    nurse_headers = nurse_headers or ctx.nurse_headers
    payload = create_visit_payload(
        ctx.enrollment_id, nurse_id, phase, target_date, scheduled_start, scheduled_end
    )
    return get_success_data(api_client.create_visit(payload, nurse_headers))


def complete_visit(visit_id, completed_date, nurse_headers):
    return get_success_data(
        api_client.complete_visit(
            visit_id, complete_visit_payload(completed_date), nurse_headers
        )
    )


def mark_missed(visit_id, nurse_headers):
    return get_success_data(api_client.mark_missed(visit_id, nurse_headers))


# ─── Tier 4: dosage-alert scenario (used by supervision) ──
def setup_active_enrollment_with_dosage_alert(clock="2026-06-01T00:00:00Z"):
    """Active enrollment whose single due visit was missed, so dosage_to_date drops to
    0%, dosage_alert flips true, review_required is set, and pending_supervision_count
    becomes 1. Returns the active-enrollment namespace plus the missed visit id.
    """
    ctx = setup_active_enrollment()
    set_clock(clock)
    visit = schedule_visit(
        ctx,
        target_date="2026-05-01",
        scheduled_start="2026-05-01T09:00:00Z",
        scheduled_end="2026-05-01T10:00:00Z",
    )
    mark_missed(visit["id"], ctx.nurse_headers)
    ctx.missed_visit = visit
    ctx.enrollment = get_enrollment(ctx.enrollment_id)
    return ctx


def open_referral(ctx, benefit_type="WIC"):
    """Open a referral on ctx.enrollment as the owning nurse."""
    return get_success_data(
        api_client.create_referral(
            create_referral_payload(ctx.enrollment_id, benefit_type), ctx.nurse_headers
        )
    )


# ─── Per-difficulty composite builders ────────────────
def setup_shared_nurse_enrollments(count=2, gestational_age_weeks=20):
    """One nurse + one supervisor + `count` active enrollments each assigned to that
    same nurse (all PREGNANCY, high_needs false). Returns a namespace whose
    `enrollments` / `enrollment_ids` list the active enrollments in creation order.
    """
    nurse = create_nurse(full_name="Shared Nurse")
    supervisor = create_supervisor()
    enrollments = []
    for i in range(count):
        client = create_client(
            full_name=f"Mother {i}", gestational_age_weeks=gestational_age_weeks
        )
        record_consent(client["id"])
        enr = create_prospect_enrollment(client["id"])
        enr = activate_enrollment(enr["id"])
        create_assignment(enr["id"], nurse["id"], supervisor["id"], enr["version"])
        enrollments.append(get_enrollment(enr["id"]))
    return SimpleNamespace(
        nurse=nurse,
        nurse_id=nurse["id"],
        nurse_headers=make_nurse_headers(nurse["id"]),
        supervisor=supervisor,
        supervisor_id=supervisor["id"],
        supervisor_headers=make_supervisor_headers(supervisor["id"]),
        enrollments=enrollments,
        enrollment_ids=[e["id"] for e in enrollments],
    )


def setup_dosage_divergence():
    """Active enrollment, clock 2026-06-01, four visits producing a to-date/full-program
    dosage split (66.67 vs 50.00). Returns the active-enrollment namespace.

    v1 target 2026-05-01 -> COMPLETED; v2 target 2026-05-10 -> MISSED;
    v3 target 2026-05-20 -> COMPLETED; v4 target 2026-07-01 -> SCHEDULED (future).
    """
    ctx = setup_active_enrollment()
    set_clock("2026-06-01T00:00:00Z")
    v1 = schedule_visit(
        ctx, target_date="2026-05-01",
        scheduled_start="2026-05-01T09:00:00Z", scheduled_end="2026-05-01T10:00:00Z",
    )
    v2 = schedule_visit(
        ctx, target_date="2026-05-10",
        scheduled_start="2026-05-10T09:00:00Z", scheduled_end="2026-05-10T10:00:00Z",
    )
    v3 = schedule_visit(
        ctx, target_date="2026-05-20",
        scheduled_start="2026-05-20T09:00:00Z", scheduled_end="2026-05-20T10:00:00Z",
    )
    schedule_visit(
        ctx, target_date="2026-07-01",
        scheduled_start="2026-07-01T09:00:00Z", scheduled_end="2026-07-01T10:00:00Z",
    )
    complete_visit(v1["id"], "2026-05-01", ctx.nurse_headers)
    mark_missed(v2["id"], ctx.nurse_headers)
    complete_visit(v3["id"], "2026-05-20", ctx.nurse_headers)
    return ctx


def setup_risk_divergence():
    """Active enrollment with one COMPLETED visit and two assessments on it: an INTAKE
    with 1 domain_flag and an ASQ with 2 domain_flags. Provisional count (INTAKE only)
    = 1 -> MODERATE; comprehensive count (all) = 3 -> HIGH. Returns the namespace with
    `client_id` set for the risk read.
    """
    ctx = setup_active_enrollment(gestational_age_weeks=18)
    set_clock("2026-06-01T00:00:00Z")
    v1 = schedule_visit(
        ctx, target_date="2026-05-05",
        scheduled_start="2026-05-05T09:00:00Z", scheduled_end="2026-05-05T10:00:00Z",
    )
    complete_visit(v1["id"], "2026-05-05", ctx.nurse_headers)
    from .factories import create_assessment_payload
    get_success_data(api_client.create_assessment(
        create_assessment_payload(
            v1["id"], ctx.enrollment_id, "INTAKE", {"communication": 5, "motor": 50}
        ),
        ctx.nurse_headers,
    ))
    get_success_data(api_client.create_assessment(
        create_assessment_payload(
            v1["id"], ctx.enrollment_id, "ASQ",
            {"communication": 5, "motor": 5, "social": 50},
        ),
        ctx.nurse_headers,
    ))
    return ctx


def setup_caseload_three_assignments():
    """One nurse holding three ACTIVE assignments across three enrollments:
    (PREGNANCY, high_needs=false)=1.0, (INFANCY, high_needs=true)=1.0,
    (PREGNANCY, high_needs=true)=1.25 -> current_caseload_weight 3.25.
    Returns (nurse_id, [assignment1, assignment2, assignment3]).
    """
    nurse = create_nurse(full_name="Caseload Nurse", credential_type="APRN")
    supervisor = create_supervisor()

    # e1: PREGNANCY, high_needs false
    c1 = create_client(full_name="C1", gestational_age_weeks=20)
    record_consent(c1["id"])
    e1 = activate_enrollment(create_prospect_enrollment(c1["id"])["id"])
    a1 = create_assignment(e1["id"], nurse["id"], supervisor["id"], e1["version"], high_needs=False)

    # e2: record birth -> INFANCY, high_needs true
    c2 = create_client(full_name="C2", gestational_age_weeks=22)
    record_consent(c2["id"])
    e2 = activate_enrollment(create_prospect_enrollment(c2["id"])["id"])
    e2 = get_success_data(api_client.record_birth(e2["id"], record_birth_payload("2026-02-15"), INTAKE))
    a2 = create_assignment(e2["id"], nurse["id"], supervisor["id"], e2["version"], high_needs=True)

    # e3: PREGNANCY, high_needs true
    c3 = create_client(full_name="C3", gestational_age_weeks=24)
    record_consent(c3["id"])
    e3 = activate_enrollment(create_prospect_enrollment(c3["id"])["id"])
    a3 = create_assignment(e3["id"], nurse["id"], supervisor["id"], e3["version"], high_needs=True)

    return nurse["id"], [a1, a2, a3]


def setup_program_on_time_report():
    """Two active enrollments with completed visits producing a pooled on-time rate of
    66.67 (numerator 2 / denominator 3). Returns (report_id) of a DRAFT MIECHV report
    covering 2026-05-01..2026-05-31. Clock at 2026-05-25.

    E1: v1 target/completed 2026-05-05 (on time); v2 target 2026-05-08 completed
        2026-05-18 (10 days late, not on time). E2: v1 target/completed 2026-05-05.
    """
    n1 = create_nurse(full_name="OT Nurse A")
    n2 = create_nurse(full_name="OT Nurse B")
    supervisor = create_supervisor()

    c1 = create_client(full_name="OT1", gestational_age_weeks=20)
    record_consent(c1["id"])
    e1 = activate_enrollment(create_prospect_enrollment(c1["id"])["id"])
    create_assignment(e1["id"], n1["id"], supervisor["id"], e1["version"])

    c2 = create_client(full_name="OT2", gestational_age_weeks=21)
    record_consent(c2["id"])
    e2 = activate_enrollment(create_prospect_enrollment(c2["id"])["id"])
    create_assignment(e2["id"], n2["id"], supervisor["id"], e2["version"])

    set_clock("2026-05-25T00:00:00Z")
    n1_headers = make_nurse_headers(n1["id"])
    n2_headers = make_nurse_headers(n2["id"])

    e1v1 = get_success_data(api_client.create_visit(
        create_visit_payload(e1["id"], n1["id"], "PREGNANCY", "2026-05-05",
                             "2026-05-05T09:00:00Z", "2026-05-05T10:00:00Z"), n1_headers))
    e1v2 = get_success_data(api_client.create_visit(
        create_visit_payload(e1["id"], n1["id"], "PREGNANCY", "2026-05-08",
                             "2026-05-08T09:00:00Z", "2026-05-08T10:00:00Z"), n1_headers))
    e2v1 = get_success_data(api_client.create_visit(
        create_visit_payload(e2["id"], n2["id"], "PREGNANCY", "2026-05-05",
                             "2026-05-05T09:00:00Z", "2026-05-05T10:00:00Z"), n2_headers))

    complete_visit(e1v1["id"], "2026-05-05", n1_headers)
    complete_visit(e1v2["id"], "2026-05-18", n1_headers)
    complete_visit(e2v1["id"], "2026-05-05", n2_headers)

    from .factories import create_miechv_report_payload
    report = get_success_data(api_client.create_miechv_report(
        create_miechv_report_payload("2026-05-01", "2026-05-31"), ADMIN))
    return report["id"]


def setup_missed_visit_escalation():
    """Active enrollment, clock 2026-06-01. v1 (target 2026-05-01) COMPLETED so dosage
    is 100% and no alert; v2 (target 2026-05-02) still SCHEDULED. Returns (ctx, v2_id):
    marking v2 missed drops dosage to 50% and drives the depth-4 escalation cascade.
    """
    ctx = setup_active_enrollment()
    set_clock("2026-06-01T00:00:00Z")
    v1 = schedule_visit(
        ctx, target_date="2026-05-01",
        scheduled_start="2026-05-01T09:00:00Z", scheduled_end="2026-05-01T10:00:00Z",
    )
    v2 = schedule_visit(
        ctx, target_date="2026-05-02",
        scheduled_start="2026-05-02T09:00:00Z", scheduled_end="2026-05-02T10:00:00Z",
    )
    complete_visit(v1["id"], "2026-05-01", ctx.nurse_headers)
    return ctx, v2["id"]
