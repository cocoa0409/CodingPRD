"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use get_success_data() so
failures surface as clear "Setup step failed" errors.
"""
from datetime import date, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    call_next_payload,
    clock_payload,
    complete_registration_payload,
    create_appointment_payload,
    create_authorization_payload,
    create_eligibility_payload,
    create_estimate_payload,
    create_flag_payload,
    create_patient_payload,
    create_payment_payload,
    create_policy_payload,
    create_referral_payload,
)
from .test_users import TEST_USERS

REG = TEST_USERS["registrar_headers"]
FC = TEST_USERS["financial_counselor_headers"]
FD = TEST_USERS["front_desk_headers"]
SUP = TEST_USERS["access_supervisor_headers"]


# ─── Small building blocks ─────────────────────────────


def set_clock(to_iso8601):
    """PRD §2.5: AccessSupervisor-only logical clock control."""
    res = api_client.set_clock(clock_payload(to_iso8601), SUP)
    return get_success_data(res)


def create_patient_raw(**overrides):
    """POST /patients only — patient stays PRE_REGISTERED."""
    res = api_client.create_patient(create_patient_payload(**overrides), REG)
    return get_success_data(res)


def create_registered_patient(**overrides):
    """Create patient + capture consent -> REGISTERED (PRD §3.1)."""
    patient = create_patient_raw(**overrides)
    res = api_client.complete_registration(
        patient["id"], complete_registration_payload(), REG
    )
    return get_success_data(res)


def create_policy_for(patient_id, **overrides):
    res = api_client.create_insurance_policy(create_policy_payload(patient_id, **overrides), REG)
    return get_success_data(res)


def create_patient_with_policy(patient_over=None, **policy_over):
    """Registered patient + one ACTIVE policy. Returns (patient, policy)."""
    patient = create_registered_patient(**(patient_over or {}))
    policy = create_policy_for(patient["id"], **policy_over)
    return patient, policy


def schedule_appointment(patient_id, **overrides):
    res = api_client.create_appointment(create_appointment_payload(patient_id, **overrides), REG)
    return get_success_data(res)


def post_eligibility_check(policy_id, appointment_id, **overrides):
    res = api_client.create_eligibility_check(
        create_eligibility_payload(policy_id, appointment_id, **overrides), REG
    )
    return get_success_data(res)


def create_referral_for(patient_id, **overrides):
    res = api_client.create_referral(create_referral_payload(patient_id, **overrides), REG)
    return get_success_data(res)


def create_authorization_for(patient_id, appointment_id, **overrides):
    res = api_client.create_authorization(
        create_authorization_payload(patient_id, appointment_id, **overrides), REG
    )
    return get_success_data(res)


def create_accommodation_flag_for(patient_id, **overrides):
    res = api_client.create_accommodation_flag(
        patient_id, create_flag_payload(**overrides), REG
    )
    return get_success_data(res)


def create_estimate(appointment_id, policy_id, allowed_amount_cents=0, **overrides):
    res = api_client.create_copay_estimate(
        appointment_id,
        create_estimate_payload(policy_id, allowed_amount_cents=allowed_amount_cents, **overrides),
        FC,
    )
    return get_success_data(res)


def post_payment(appointment_id, amount_cents, method="CARD", kind="POST"):
    res = api_client.create_payment(
        appointment_id,
        create_payment_payload(amount_cents=amount_cents, method=method, kind=kind),
        FC,
    )
    return get_success_data(res)


def get_appointment(appointment_id):
    return get_success_data(api_client.get_appointment(appointment_id, FC))


def get_referral(referral_id):
    return get_success_data(api_client.get_referral(referral_id, REG))


def list_appointment_tickets(appointment_id):
    return get_success_data(
        api_client.list_appointment_tickets(appointment_id, FD)
    )


def list_appointment_estimates(appointment_id):
    return get_success_data(
        api_client.list_appointment_estimates(appointment_id, FC)
    )


def mark_no_show_at(appointment_id, clock_iso):
    """Advance the logical clock well past the grace moment, then mark NO_SHOW."""
    set_clock(clock_iso)
    res = api_client.mark_no_show(appointment_id, FD)
    return get_success_data(res)


# ─── Tier 1/2: verified & pre-checked visits ───────────


def create_prechecked_visit(
    *,
    patient_over=None,
    register_patient=True,
    plan_type="PPO",
    deductible_remaining_cents=0,
    oop_max_remaining_cents=500000,
    priority_rank=1,
    policy_over=None,
    department_code="ORTHO",
    procedure_code="99213",
    scheduled_start="2026-08-20T09:00:00Z",
    duration_minutes=30,
    visit_type="ESTABLISHED",
    provider_code="DRPROV",
    referring_provider_npi=None,
    with_referral=False,
    referral_npi="NPI100",
    referral_visits_authorized=5,
    referral_valid_from="2026-01-01",
    referral_valid_until="2027-12-31",
    flag_over=None,
    post_check=True,
    run_pre_check=True,
    coverage_status="ACTIVE",
    copay_cents=0,
    coinsurance_pct=0,
    auth_required=False,
):
    """Registered patient + ACTIVE policy (+ optional referral) + appointment
    + fresh eligibility check + pre-check. Returns a context dict.

    PRD §3.4: pre-check requires the patient REGISTERED and a usable
    verification whose result is VERIFIED or VERIFIED_WITH_AUTH.
    """
    ctx = {}
    if register_patient:
        patient = create_registered_patient(**(patient_over or {}))
    else:
        patient = create_patient_raw(**(patient_over or {}))
    ctx["patient"] = patient

    if flag_over is not None:
        ctx["flag"] = create_accommodation_flag_for(patient["id"], **flag_over)

    policy_kwargs = dict(
        plan_type=plan_type,
        deductible_remaining_cents=deductible_remaining_cents,
        oop_max_remaining_cents=oop_max_remaining_cents,
        priority_rank=priority_rank,
    )
    policy_kwargs.update(policy_over or {})
    policy = create_policy_for(patient["id"], **policy_kwargs)
    ctx["policy"] = policy

    if with_referral:
        ctx["referral"] = create_referral_for(
            patient["id"],
            referring_provider_npi=referral_npi,
            specialty_code=department_code,
            procedure_code=procedure_code,
            visits_authorized=referral_visits_authorized,
            valid_from=referral_valid_from,
            valid_until=referral_valid_until,
        )

    appt_kwargs = dict(
        department_code=department_code,
        procedure_code=procedure_code,
        scheduled_start=scheduled_start,
        duration_minutes=duration_minutes,
        visit_type=visit_type,
        provider_code=provider_code,
    )
    npi = referring_provider_npi
    if npi is None and with_referral:
        npi = referral_npi
    if npi is not None:
        appt_kwargs["referring_provider_npi"] = npi
    appointment = schedule_appointment(patient["id"], **appt_kwargs)
    ctx["appointment"] = appointment

    if post_check:
        ctx["check"] = post_eligibility_check(
            policy["id"],
            appointment["id"],
            coverage_status=coverage_status,
            copay_cents=copay_cents,
            coinsurance_pct=coinsurance_pct,
            auth_required=auth_required,
        )
        if run_pre_check:
            ctx["appointment"] = get_success_data(
                api_client.pre_check(appointment["id"], REG)
            )
    return ctx


# ─── Tier 3: full lifecycle shortcuts ──────────────────


def setup_ready_visit(
    *,
    allowed_amount_cents=0,
    payment_amounts=(),
    with_authorization=False,
    authorization_valid_until="2027-12-31",
    authorization_units=1,
    run_estimate=True,
    run_mark_ready=True,
    **visit_kw,
):
    """create_prechecked_visit + estimate + payments (+ optional authorization)
    + mark-ready. Returns the context dict extended with estimate/payments."""
    ctx = create_prechecked_visit(**visit_kw)
    appointment_id = ctx["appointment"]["id"]

    if run_estimate:
        ctx["estimate"] = create_estimate(
            appointment_id, ctx["policy"]["id"], allowed_amount_cents
        )
    ctx["payments"] = [
        post_payment(appointment_id, amount) for amount in payment_amounts
    ]
    if with_authorization:
        ctx["authorization"] = create_authorization_for(
            ctx["patient"]["id"],
            appointment_id,
            authorized_units=authorization_units,
            valid_until=authorization_valid_until,
        )
    if run_mark_ready:
        ctx["appointment"] = get_success_data(api_client.mark_ready(appointment_id, FC))
    return ctx


def setup_arrived_visit(*, checkin_clock=None, stat_flag=None, **visit_kw):
    """READY visit + check-in (PRD §3.6). Adds the issued queue ticket list."""
    ctx = setup_ready_visit(**visit_kw)
    if checkin_clock is not None:
        set_clock(checkin_clock)
    payload = {} if stat_flag is None else {"stat_flag": stat_flag}
    ctx["appointment"] = get_success_data(
        api_client.check_in(ctx["appointment"]["id"], payload, FD)
    )
    ctx["tickets"] = list_appointment_tickets(ctx["appointment"]["id"])
    return ctx


def setup_in_room_visit(**visit_kw):
    """ARRIVED visit + call-next -> ticket CALLED, appointment IN_ROOM."""
    ctx = setup_arrived_visit(**visit_kw)
    queue_date = ctx["appointment"]["scheduled_start"][:10]
    ctx["ticket"] = get_success_data(
        api_client.call_next(
            call_next_payload(ctx["appointment"]["department_code"], queue_date), FD
        )
    )
    ctx["appointment"] = get_appointment(ctx["appointment"]["id"])
    return ctx


def setup_completed_visit(**visit_kw):
    """IN_ROOM visit + complete -> COMPLETED (ticket SERVED, estimate FINAL)."""
    ctx = setup_in_room_visit(**visit_kw)
    ctx["appointment"] = get_success_data(
        api_client.complete_appointment(ctx["appointment"]["id"], FD)
    )
    return ctx


# ─── Tier 4: accumulation / threshold targeting ────────


def seed_no_show(patient_id, scheduled_start, provider_code, mark_clock):
    """Create one appointment for `patient_id` and mark it NO_SHOW after the
    grace moment has passed (PRD §3.7)."""
    appt = schedule_appointment(
        patient_id,
        scheduled_start=scheduled_start,
        provider_code=provider_code,
    )
    return mark_no_show_at(appt["id"], mark_clock)


def setup_low_vs_high_risk_estimates():
    """Two registered patients with identical PPO coverage and identical
    ESTABLISHED appointments; LOW has zero trailing no-shows, HIGH has two
    inside the trailing 365-day window. Returns (estimate_low, estimate_high).

    PRD §3.5 deposit tiering: below two strikes a non-NEW visit owes 25%;
    with at least two strikes the deposit target is the full estimate.
    """
    set_clock("2026-08-01T00:00:00Z")

    # LOW-risk patient: no trailing no-shows.
    low_patient, low_policy = create_patient_with_policy(
        patient_over={
            "first_name": "Low", "last_name": "Risk",
            "date_of_birth": "1990-01-01", "sex_at_birth": "F",
            "primary_phone": "+15552000001",
        },
        deductible_remaining_cents=30000,
    )
    low_appt = schedule_appointment(
        low_patient["id"],
        procedure_code="99213",
        scheduled_start="2026-08-10T09:00:00Z",
        visit_type="ESTABLISHED",
        provider_code="DRA",
    )
    post_eligibility_check(
        low_policy["id"], low_appt["id"],
        coverage_status="ACTIVE", copay_cents=0, coinsurance_pct=20,
        auth_required=False,
    )

    # HIGH-risk patient: two past appointments later marked NO_SHOW.
    high_patient, high_policy = create_patient_with_policy(
        patient_over={
            "first_name": "Hi", "last_name": "Risk",
            "date_of_birth": "1991-02-02", "sex_at_birth": "M",
            "primary_phone": "+15552000002",
        },
        deductible_remaining_cents=30000,
    )
    high_appt1 = schedule_appointment(
        high_patient["id"],
        procedure_code="99213",
        scheduled_start="2026-08-05T09:00:00Z",
        visit_type="ESTABLISHED",
        provider_code="DRB",
    )
    high_appt2 = schedule_appointment(
        high_patient["id"],
        procedure_code="99213",
        scheduled_start="2026-08-06T09:00:00Z",
        visit_type="ESTABLISHED",
        provider_code="DRB",
    )
    high_appt3 = schedule_appointment(
        high_patient["id"],
        procedure_code="99213",
        scheduled_start="2026-08-10T09:00:00Z",
        visit_type="ESTABLISHED",
        provider_code="DRB",
    )
    post_eligibility_check(
        high_policy["id"], high_appt3["id"],
        coverage_status="ACTIVE", copay_cents=0, coinsurance_pct=20,
        auth_required=False,
    )

    # Advance logical time well beyond any plausible grace moment for each
    # no-show appointment, then mark them (PRD §3.7).
    mark_no_show_at(high_appt1["id"], "2026-08-06T00:00:00Z")
    mark_no_show_at(high_appt2["id"], "2026-08-07T00:00:00Z")

    estimate_low = create_estimate(low_appt["id"], low_policy["id"], 100000)
    estimate_high = create_estimate(high_appt3["id"], high_policy["id"], 100000)
    return estimate_low, estimate_high


def setup_dual_variant_estimates():
    """Two NEW appointments with identical PPO coverage: one backed by a fresh
    ACTIVE eligibility check (PAYER_VERIFIED path), one with no usable
    verification (FEE_SCHEDULE path). Returns (estimate_verified, estimate_fee).

    PRD §3.5: PAYER_VERIFIED applies when a usable verification exists;
    FEE_SCHEDULE applies when no usable verification exists.
    """
    patient1, policy1 = create_patient_with_policy(
        patient_over={
            "first_name": "Ana", "last_name": "Vera",
            "date_of_birth": "1980-04-02", "sex_at_birth": "F",
            "primary_phone": "+15551000001",
        },
        deductible_remaining_cents=30000,
    )
    appt1 = schedule_appointment(
        patient1["id"],
        procedure_code="99205",
        scheduled_start="2026-08-10T09:00:00Z",
        visit_type="NEW",
        provider_code="DRSMITH",
    )
    post_eligibility_check(
        policy1["id"], appt1["id"],
        coverage_status="ACTIVE", copay_cents=0, coinsurance_pct=20,
        auth_required=False,
    )
    get_success_data(api_client.pre_check(appt1["id"], REG))

    patient2, policy2 = create_patient_with_policy(
        patient_over={
            "first_name": "Bob", "last_name": "Lee",
            "date_of_birth": "1975-11-20", "sex_at_birth": "M",
            "primary_phone": "+15551000002",
        },
        deductible_remaining_cents=30000,
    )
    appt2 = schedule_appointment(
        patient2["id"],
        procedure_code="99205",
        scheduled_start="2026-08-10T10:00:00Z",
        visit_type="NEW",
        provider_code="DRJONES",
    )

    estimate_fee = create_estimate(appt2["id"], policy2["id"], 100000)
    estimate_verified = create_estimate(appt1["id"], policy1["id"], 100000)
    return estimate_verified, estimate_fee


def setup_oop_capped_estimate():
    """PPO policy with oop_max_remaining 2000 so the cap binds under
    PAYER_VERIFIED (PRD §3.5: responsibility capped at oop_max_remaining)."""
    ctx = create_prechecked_visit(
        deductible_remaining_cents=30000,
        oop_max_remaining_cents=2000,
        copay_cents=0,
        coinsurance_pct=20,
        visit_type="ESTABLISHED",
        scheduled_start="2026-08-10T09:00:00Z",
        provider_code="DRC",
    )
    ctx["estimate"] = create_estimate(
        ctx["appointment"]["id"], ctx["policy"]["id"], 100000
    )
    return ctx


def setup_procedure_visit_with_auth_and_payment():
    """PRE_CHECKED PROCEDURE visit (auth_required flagged) with an APPROVED
    authorization, a 20000-cent estimate (deposit 5000), and 10000 collected,
    so the gate resolves CLEAR. PRD §3.5 pinned gate derivation."""
    ctx = create_prechecked_visit(
        visit_type="PROCEDURE",
        department_code="SURG",
        procedure_code="47562",
        duration_minutes=60,
        scheduled_start="2026-08-12T09:00:00Z",
        provider_code="DRD",
        copay_cents=0,
        coinsurance_pct=20,
        auth_required=True,
        deductible_remaining_cents=0,
    )
    appointment_id = ctx["appointment"]["id"]
    ctx["authorization"] = create_authorization_for(
        ctx["patient"]["id"], appointment_id, valid_until="2026-08-31"
    )
    ctx["estimate"] = create_estimate(appointment_id, ctx["policy"]["id"], 100000)
    ctx["payments"] = [post_payment(appointment_id, 10000)]
    ctx["appointment"] = get_appointment(appointment_id)
    return ctx


def setup_visit_with_payment(payment_amount=5000, **visit_kw):
    """PRE_CHECKED visit with one POSTED payment of `payment_amount` cents."""
    ctx = create_prechecked_visit(**visit_kw)
    ctx["payments"] = [post_payment(ctx["appointment"]["id"], payment_amount)]
    return ctx
