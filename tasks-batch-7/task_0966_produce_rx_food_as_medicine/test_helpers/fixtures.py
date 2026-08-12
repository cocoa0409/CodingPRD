"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Helpers use get_success_data() (lenient)
so setup failures surface as clear "Setup failed" errors, not assertions.

Identity threading: entity-backed roles always use the make_*_headers builders
with the real entity id — never the shared TEST_USERS fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_program_payload,
    create_funder_payload,
    create_funding_pool_payload,
    create_clinic_payload,
    create_retailer_payload,
    create_patient_payload,
    create_referral_payload,
    create_cycle_payload,
    create_redemption_payload,
    create_education_session_payload,
    create_completion_payload,
    create_biometric_reading_payload,
    create_funder_report_payload,
    create_renewal_payload,
)
from .test_users import (
    TEST_USERS,
    make_funder_analyst_headers,
    make_clinic_staff_headers,
    make_retailer_staff_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
EDUCATOR = TEST_USERS["educator_headers"]


def _setup_fail(step, res):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {res.status_code}: {res.text}"
    )


def _ok(step, res, expected=None):
    if expected is not None and res.status_code != expected:
        _setup_fail(step, res)
    if res.status_code >= 400:
        _setup_fail(step, res)
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 1: atomic creators and state progression
# ---------------------------------------------------------------------------

def create_funder(name="F1", total_commitment_cents=1000000):
    return _ok("create_funder", api_client.create_funder(
        create_funder_payload(name=name, total_commitment_cents=total_commitment_cents),
        ADMIN), 201)


def create_program(**overrides):
    return _ok("create_program", api_client.create_program(
        create_program_payload(**overrides), ADMIN), 201)


def create_pool(program_id, funder_id, committed_cents=500000, **extra):
    return _ok("create_pool", api_client.create_funding_pool(
        create_funding_pool_payload(program_id, funder_id,
                                    committed_cents=committed_cents, **extra),
        ADMIN), 201)


def fund_pool(pool_id, funder_id):
    """Fund a PENDING pool as its own funder (ownership-gated, PRD §3.1)."""
    return _ok("fund_pool", api_client.fund_pool(
        pool_id, make_funder_analyst_headers(funder_id)), 200)


def activate_program(program_id):
    return _ok("activate_program", api_client.activate_program(program_id, ADMIN), 200)


def create_clinic(name="C1", max_active_referrals=50):
    return _ok("create_clinic", api_client.create_clinic(
        create_clinic_payload(name=name, max_active_referrals=max_active_referrals),
        ADMIN), 201)


def create_retailer(name="R1", kind="GROCERY", double_up_eligible=True):
    return _ok("create_retailer", api_client.create_retailer(
        create_retailer_payload(name=name, kind=kind,
                                double_up_eligible=double_up_eligible),
        ADMIN), 201)


def create_patient(clinic_id, full_name="Pat One", household_size=2,
                   date_of_birth="1980-01-15"):
    """Register a patient as its owning clinic (ownership-gated, PRD §3.2)."""
    return _ok("create_patient", api_client.create_patient(
        create_patient_payload(clinic_id, full_name=full_name,
                               household_size=household_size,
                               date_of_birth=date_of_birth),
        make_clinic_staff_headers(clinic_id)), 201)


def grant_consent(clinic_id, patient_id):
    return _ok("grant_consent", api_client.grant_consent(
        patient_id, make_clinic_staff_headers(clinic_id)), 200)


def revoke_consent(clinic_id, patient_id):
    return _ok("revoke_consent", api_client.revoke_consent(
        patient_id, make_clinic_staff_headers(clinic_id)), 200)


def create_patient_with_consent(clinic_id, **kwargs):
    patient = create_patient(clinic_id, **kwargs)
    grant_consent(clinic_id, patient["id"])
    return patient


def create_referral(clinic_id, patient_id, program_id, priority="STANDARD"):
    return _ok("create_referral", api_client.create_referral(
        create_referral_payload(clinic_id, patient_id, program_id,
                                priority=priority),
        make_clinic_staff_headers(clinic_id)), 201)


def start_review(referral_id):
    return _ok("start_review", api_client.start_review(referral_id, ADMIN), 200)


def approve_referral(referral_id):
    """start-review + approve. Returns the APPROVED referral (with enrollment_id)."""
    start_review(referral_id)
    return _ok("approve_referral", api_client.approve_referral(referral_id, ADMIN), 200)


def create_cycle(program_id, period_index=1, start_date="2026-05-01",
                 end_date="2026-06-01"):
    return _ok("create_cycle", api_client.create_cycle(
        program_id,
        create_cycle_payload(period_index=period_index, start_date=start_date,
                             end_date=end_date),
        ADMIN), 201)


def open_cycle(cycle_id):
    return _ok("open_cycle", api_client.open_cycle(cycle_id, ADMIN), 200)


def issue_cycle(cycle_id):
    return _ok("issue_cycle", api_client.issue_cycle(cycle_id, ADMIN), 200)


def close_cycle(cycle_id):
    return _ok("close_cycle", api_client.close_cycle(cycle_id, ADMIN), 200)


def set_clock(to_iso8601):
    return _ok("set_clock", api_client.set_clock(
        {"to_iso8601": to_iso8601}, ADMIN), 200)


def get_program(program_id):
    return _ok("get_program", api_client.get_program(program_id, ADMIN), 200)


def get_pool(pool_id):
    return _ok("get_pool", api_client.get_funding_pool(pool_id, ADMIN), 200)


def get_enrollment(enrollment_id):
    return _ok("get_enrollment", api_client.get_enrollment(enrollment_id, ADMIN), 200)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — active program, funded pool, enrolled patient
# ---------------------------------------------------------------------------

def setup_active_program(program_overrides=None, pool_committed_cents=500000,
                         funder_commitment_cents=1000000):
    """Funder + program + FUNDED pool + program ACTIVE.

    Returns dict(program, funder, pool).
    """
    funder = create_funder(total_commitment_cents=funder_commitment_cents)
    program = create_program(**(program_overrides or {}))
    pool = create_pool(program["id"], funder["id"],
                       committed_cents=pool_committed_cents)
    fund_pool(pool["id"], funder["id"])
    program = activate_program(program["id"])
    return {"program": program, "funder": funder, "pool": pool}


def setup_enrollment(program_overrides=None, pool_committed_cents=500000,
                     clinic_overrides=None, household_size=2,
                     patient_name="Pat One", priority="STANDARD",
                     with_retailer=False, base=None):
    """Active program + clinic + consenting patient + APPROVED referral.

    Returns dict with program, funder, pool, clinic, patient, referral,
    enrollment_id (and retailer when with_retailer=True).
    """
    ctx = base or setup_active_program(
        program_overrides=program_overrides,
        pool_committed_cents=pool_committed_cents)
    clinic = create_clinic(**(clinic_overrides or {}))
    patient = create_patient_with_consent(
        clinic["id"], full_name=patient_name, household_size=household_size)
    referral = create_referral(clinic["id"], patient["id"],
                               ctx["program"]["id"], priority=priority)
    referral = approve_referral(referral["id"])
    ctx.update({
        "clinic": clinic,
        "patient": patient,
        "referral": referral,
        "enrollment_id": referral["enrollment_id"],
    })
    if with_retailer:
        ctx["retailer"] = create_retailer()
    return ctx


def add_enrollment(ctx, household_size=2, patient_name="Pat B",
                   priority="STANDARD"):
    """Add a second enrolled patient to an existing setup_enrollment context.

    Returns (patient, referral, enrollment_id). Enrollments created later have
    later created_at, which fixes the issuance waterfall order (PRD §3.4).
    """
    patient = create_patient_with_consent(
        ctx["clinic"]["id"], full_name=patient_name, household_size=household_size)
    referral = create_referral(ctx["clinic"]["id"], patient["id"],
                               ctx["program"]["id"], priority=priority)
    referral = approve_referral(referral["id"])
    return patient, referral, referral["enrollment_id"]


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts — open cycle, issued voucher, redemption
# ---------------------------------------------------------------------------

def setup_open_cycle(ctx, period_index=1, start_date="2026-05-01",
                     end_date="2026-06-01"):
    """Create + open a cycle in an ACTIVE-program context. Returns the cycle."""
    cycle = create_cycle(ctx["program"]["id"], period_index=period_index,
                         start_date=start_date, end_date=end_date)
    open_cycle(cycle["id"])
    return _ok("get_cycle", api_client.get_cycle(cycle["id"], ADMIN), 200)


def setup_issued_voucher(ctx=None, period_index=1, **enrollment_kwargs):
    """Enrollment + OPEN cycle + issuance run; exactly one ISSUED voucher.

    Returns ctx augmented with cycle, issue_result, voucher_id, voucher.
    """
    if ctx is None:
        ctx = setup_enrollment(**enrollment_kwargs)
    cycle = create_cycle(ctx["program"]["id"], period_index=period_index)
    open_cycle(cycle["id"])
    issue_result = _ok("issue_cycle", api_client.issue_cycle(cycle["id"], ADMIN), 200)
    vouchers = _ok("list_vouchers", api_client.list_vouchers(
        ADMIN, params={"enrollment_id": ctx["enrollment_id"]}), 200)
    assert isinstance(vouchers, list) and len(vouchers) == 1, (
        f"Setup failed: expected exactly 1 voucher, got {vouchers}"
    )
    ctx.update({
        "cycle": cycle,
        "issue_result": issue_result,
        "voucher_id": vouchers[0]["id"],
        "voucher": vouchers[0],
    })
    return ctx


def create_settled_redemption(ctx, lines=None):
    """Settle a redemption at the context retailer (created if absent).

    Returns the SETTLED redemption.
    """
    if "retailer" not in ctx:
        ctx["retailer"] = create_retailer()
    retailer = ctx["retailer"]
    redemption = _ok("create_redemption", api_client.create_redemption(
        create_redemption_payload(retailer["id"], ctx["enrollment_id"],
                                  lines=lines),
        make_retailer_staff_headers(retailer["id"])), 201)
    return redemption


def setup_settled_redemption(lines=None, **enrollment_kwargs):
    """Issued voucher + one SETTLED redemption. Default basket is
    produce 2000 + staple 3000 -> match 2000, voucher_applied 3000."""
    ctx = setup_issued_voucher(with_retailer=True, **enrollment_kwargs)
    ctx["redemption"] = create_settled_redemption(ctx, lines=lines)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: education sessions, completions, engagement-tier targeting
# ---------------------------------------------------------------------------

def create_completed_session(program_id, topic="T", venue="RM-1",
                             starts_at="2026-05-10T10:00:00Z",
                             ends_at="2026-05-10T11:00:00Z", capacity=10):
    session = _ok("create_education_session", api_client.create_education_session(
        program_id,
        create_education_session_payload(topic=topic, venue=venue,
                                         starts_at=starts_at, ends_at=ends_at,
                                         capacity=capacity),
        EDUCATOR), 201)
    _ok("complete_session", api_client.complete_session(session["id"], EDUCATOR), 200)
    return session


def record_completion(session_id, enrollment_id, minutes_attended=60, passed=True):
    return _ok("record_completion", api_client.record_completion(
        session_id,
        create_completion_payload(enrollment_id, minutes_attended=minutes_attended,
                                  passed=passed),
        EDUCATOR), 201)


def record_passed_completions(ctx, count, start_day=10):
    """Record `count` passed completions for ctx's enrollment, one per session
    (sessions on consecutive days at the same venue to avoid buffer overlap).

    Returns the list of sessions.
    """
    sessions = []
    for i in range(count):
        day = start_day + i
        session = create_completed_session(
            ctx["program"]["id"], topic=f"T{i + 1}",
            starts_at=f"2026-05-{day:02d}T10:00:00Z",
            ends_at=f"2026-05-{day:02d}T11:00:00Z")
        record_completion(session["id"], ctx["enrollment_id"])
        sessions.append(session)
    return sessions


def setup_enrollment_with_tier(passed_completions, **enrollment_kwargs):
    """Enrollment whose engagement tier reflects `passed_completions` passed
    completions (canonical program: tier2 at 3, tier3 at 6)."""
    ctx = setup_enrollment(**enrollment_kwargs)
    record_passed_completions(ctx, passed_completions)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4b: biometrics
# ---------------------------------------------------------------------------

def record_a1c(ctx, value, measured_at, source="LAB_VERIFIED"):
    return _ok("create_biometric_reading", api_client.create_biometric_reading(
        ctx["enrollment_id"],
        create_biometric_reading_payload(kind="A1C", value=value,
                                         measured_at=measured_at, source=source),
        make_clinic_staff_headers(ctx["clinic"]["id"])), 201)


# ---------------------------------------------------------------------------
# Tier 5: funder reports, renewals, lapse/terminal states
# ---------------------------------------------------------------------------

def create_report(ctx, pool_id, basis="CASH", period_start="2026-05-01",
                  period_end="2026-06-01"):
    """Create a DRAFT funder report with a fresh OCC program version."""
    program = get_program(ctx["program"]["id"])
    report = _ok("create_funder_report", api_client.create_funder_report(
        ctx["program"]["id"],
        create_funder_report_payload(
            pool_id, program["version"], basis=basis,
            period_start=period_start, period_end=period_end),
        ADMIN), 201)
    return report


def setup_submitted_report(basis="CASH"):
    """Active program + FUNDED pool + report created and SUBMITTED."""
    ctx = setup_active_program()
    report = create_report(ctx, ctx["pool"]["id"], basis=basis)
    report = _ok("submit_report", api_client.submit_report(report["id"], ADMIN), 200)
    ctx["report"] = report
    return ctx


def setup_lapsed_enrollment(**enrollment_kwargs):
    """Enrollment lapsed by an ops run: issued voucher, cycle closed without
    any redemption, then run-ops applies the zero-redemption lapse rule
    (PRD §3.8/§3.9). lapsed_at is the logical clock at run-ops time."""
    ctx = setup_issued_voucher(**enrollment_kwargs)
    close_cycle(ctx["cycle"]["id"])
    ctx["ops_result"] = _ok("run_ops", api_client.run_ops(
        ctx["program"]["id"], ADMIN), 200)
    ctx["enrollment"] = get_enrollment(ctx["enrollment_id"])
    return ctx


def create_renewal(ctx, reason="renewal request"):
    """Create a DRAFT renewal with a fresh OCC enrollment version."""
    enrollment = get_enrollment(ctx["enrollment_id"])
    renewal = _ok("create_renewal", api_client.create_renewal(
        ctx["enrollment_id"],
        create_renewal_payload(enrollment["version"], reason=reason),
        make_clinic_staff_headers(ctx["clinic"]["id"])), 201)
    return renewal
