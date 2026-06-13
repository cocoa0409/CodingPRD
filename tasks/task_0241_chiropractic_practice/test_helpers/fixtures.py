"""Composite setup helpers for multi-step test prerequisites.

Every fixture uses get_success_data() (the lenient validator) for its setup
calls, so a broken precondition surfaces as a clear "setup failed" error rather
than a confusing assertion failure deep inside a test.

Because the harness restarts the server (empty DB) before every test, each
fixture builds its entire world from scratch using only PRD-declared endpoints.

Identity threading: Provider is entity_backed, so any ownership-gated call
(finalize exam, create/sign SOAP, complete, propose/activate/discontinue/regress
plan, add phase) uses make_provider_headers(provider_id) with the real
Provider.id, never the shared TEST_USERS["provider_headers"] fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_provider_payload,
    create_room_payload,
    create_fee_schedule_payload,
    create_wellness_plan_payload,
    create_patient_payload,
    create_insurance_policy_payload,
    create_exam_payload,
    create_treatment_plan_payload,
    create_phase_payload,
    create_series_payload,
    create_appointment_payload,
    create_soap_note_payload,
)
from .test_users import TEST_USERS, make_provider_headers


ADMIN = TEST_USERS["admin_headers"]
FRONTDESK = TEST_USERS["frontdesk_headers"]
BILLING = TEST_USERS["billing_headers"]

DEFAULT_CLOCK = "2026-03-02T08:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: shared base configuration
# ---------------------------------------------------------------------------
def set_clock(current_utc):
    """Set the practice clock (PracticeAdmin)."""
    return get_success_data(api_client.set_clock(current_utc, ADMIN))


def create_provider(full_name="Dr Vega", npi="1234567890"):
    return get_success_data(
        api_client.create_provider(create_provider_payload(full_name=full_name, npi=npi), ADMIN)
    )


def create_room(name="Adj 1", room_type="ADJUSTMENT", turnover_buffer_minutes=0):
    payload = create_room_payload(name=name, room_type=room_type)
    payload["turnover_buffer_minutes"] = turnover_buffer_minutes
    return get_success_data(api_client.create_room(payload, ADMIN))


def create_fee_schedule(visit_type="ADJUSTMENT", cash_rate_cents=6000, billed_amount_cents=9000):
    return get_success_data(
        api_client.create_fee_schedule(
            create_fee_schedule_payload(
                visit_type=visit_type,
                cash_rate_cents=cash_rate_cents,
                billed_amount_cents=billed_amount_cents,
            ),
            ADMIN,
        )
    )


def create_wellness_plan(included_adjustments_per_month=4, overage_discount_pct=0.30, monthly_fee_cents=9900):
    return get_success_data(
        api_client.create_wellness_plan(
            create_wellness_plan_payload(
                included_adjustments_per_month=included_adjustments_per_month,
                overage_discount_pct=overage_discount_pct,
                monthly_fee_cents=monthly_fee_cents,
            ),
            ADMIN,
        )
    )


def setup_base_practice(
    visit_type="ADJUSTMENT",
    cash_rate_cents=6000,
    clock=DEFAULT_CLOCK,
    room_type="ADJUSTMENT",
    turnover_buffer_minutes=0,
):
    """Active provider + open room + ACTIVE fee schedule + clock set.

    Returns dict(provider, room, fee_schedule).
    """
    fee = create_fee_schedule(visit_type=visit_type, cash_rate_cents=cash_rate_cents)
    provider = create_provider()
    room = create_room(room_type=room_type, turnover_buffer_minutes=turnover_buffer_minutes)
    set_clock(clock)
    return {"provider": provider, "room": room, "fee_schedule": fee}


# ---------------------------------------------------------------------------
# Patients & coverage
# ---------------------------------------------------------------------------
def create_cash_patient(full_name="Cash Carl"):
    return get_success_data(
        api_client.create_patient(
            create_patient_payload(full_name=full_name, payer_mode="CASH"), FRONTDESK
        )
    )


def create_insurance_patient(full_name="Ins Ida"):
    return get_success_data(
        api_client.create_patient(
            create_patient_payload(full_name=full_name, payer_mode="INSURANCE"), FRONTDESK
        )
    )


def create_wellness_patient(wellness_plan_id, full_name="Well Wendy"):
    return get_success_data(
        api_client.create_patient(
            create_patient_payload(
                full_name=full_name, payer_mode="WELLNESS", wellness_plan_id=wellness_plan_id
            ),
            FRONTDESK,
        )
    )


def add_policy(
    patient_id,
    annual_visit_cap=20,
    deductible_total_cents=0,
    coinsurance_pct=0.20,
    allowed_amount_cents=8000,
):
    return get_success_data(
        api_client.create_insurance_policy(
            patient_id,
            create_insurance_policy_payload(
                annual_visit_cap=annual_visit_cap,
                deductible_total_cents=deductible_total_cents,
                coinsurance_pct=coinsurance_pct,
                allowed_amount_cents=allowed_amount_cents,
            ),
            BILLING,
        )
    )


# ---------------------------------------------------------------------------
# Appointment lifecycle shortcuts
# ---------------------------------------------------------------------------
def book_appointment(patient_id, provider_id, room_id, **overrides):
    return get_success_data(
        api_client.book_appointment(
            patient_id, create_appointment_payload(provider_id, room_id, **overrides), FRONTDESK
        )
    )


def add_signed_soap(patient_id, appt_id, provider_id):
    """Create a DRAFT SOAP note and sign it (note author == appointment provider)."""
    get_success_data(
        api_client.create_soap_note(
            patient_id, appt_id, create_soap_note_payload(provider_id), make_provider_headers(provider_id)
        )
    )
    return get_success_data(
        api_client.sign_soap_note(patient_id, appt_id, make_provider_headers(provider_id))
    )


def create_checked_in_with_signed_soap(patient_id, provider_id, room_id, **overrides):
    """Book -> check-in -> create+sign SOAP. Returns the appointment dict (post check-in)."""
    appt = book_appointment(patient_id, provider_id, room_id, **overrides)
    get_success_data(api_client.check_in(patient_id, appt["id"], FRONTDESK))
    add_signed_soap(patient_id, appt["id"], provider_id)
    return appt


def create_attended_appointment(patient_id, provider_id, room_id, **overrides):
    """Book -> check-in -> sign SOAP -> complete. Returns the COMPLETED appointment dict."""
    appt = create_checked_in_with_signed_soap(patient_id, provider_id, room_id, **overrides)
    return get_success_data(
        api_client.complete_appointment(patient_id, appt["id"], make_provider_headers(provider_id))
    )


def setup_attended_cash_visit(cash_rate_cents=6000):
    """A CASH patient with one ATTENDED+POSTED ADJUSTMENT visit.

    Returns dict(patient, provider, room, appointment).
    """
    base = setup_base_practice(cash_rate_cents=cash_rate_cents)
    patient = create_cash_patient("Ledger Lee")
    appt = create_attended_appointment(
        patient["id"], base["provider"]["id"], base["room"]["id"]
    )
    return {"patient": patient, "provider": base["provider"], "room": base["room"], "appointment": appt}


def setup_attended_insurance_visit(
    annual_visit_cap=20, deductible_total_cents=0, coinsurance_pct=0.20, allowed_amount_cents=8000
):
    """An INSURANCE patient with one ATTENDED+POSTED ADJUSTMENT visit (cap committed).

    Returns dict(patient, provider, room, policy, appointment).
    """
    base = setup_base_practice()
    patient = create_insurance_patient("Adj Andy")
    policy = add_policy(
        patient["id"],
        annual_visit_cap=annual_visit_cap,
        deductible_total_cents=deductible_total_cents,
        coinsurance_pct=coinsurance_pct,
        allowed_amount_cents=allowed_amount_cents,
    )
    appt = create_attended_appointment(
        patient["id"],
        base["provider"]["id"],
        base["room"]["id"],
        scheduled_start="2026-03-03T17:00:00Z",
        insurance_policy_id=policy["id"],
    )
    return {
        "patient": patient,
        "provider": base["provider"],
        "room": base["room"],
        "policy": policy,
        "appointment": appt,
    }


# ---------------------------------------------------------------------------
# Strikes / dismissal
# ---------------------------------------------------------------------------
def _no_show_one(patient_id, provider_id, room_id, slot_hour, insurance_policy_id=None):
    """Book an appointment in the past, advance the clock past it, and no-show it.
    Records exactly one strike. slot_hour is an int hour on 2026-03-02 (UTC).
    For INSURANCE patients, `insurance_policy_id` must be supplied so the booking
    satisfies the PRD §3.6 ERR_POLICY_REQUIRED precondition."""
    start = f"2026-03-02T{slot_hour:02d}:00:00Z"
    after = f"2026-03-02T{slot_hour:02d}:30:00Z"
    book_overrides = {"scheduled_start": start, "duration_minutes": 15}
    if insurance_policy_id is not None:
        book_overrides["insurance_policy_id"] = insurance_policy_id
    appt = book_appointment(patient_id, provider_id, room_id, **book_overrides)
    set_clock(after)
    return get_success_data(api_client.no_show_appointment(patient_id, appt["id"], FRONTDESK))


def accrue_strikes(patient_id, provider_id, room_id, n, start_hour=9, insurance_policy_id=None):
    """Record exactly `n` no-show strikes on the patient by booking and no-showing
    `n` elapsed appointments. Resets the clock to DEFAULT_CLOCK at the end so later
    future bookings remain valid. For INSURANCE patients, `insurance_policy_id` must
    be supplied so each strike booking satisfies ERR_POLICY_REQUIRED."""
    for i in range(n):
        _no_show_one(patient_id, provider_id, room_id, start_hour + i, insurance_policy_id=insurance_policy_id)
    set_clock(DEFAULT_CLOCK)


def setup_dismissed_patient(full_name="Dismiss Dan"):
    """A CASH patient dismissed by 5 no-show strikes.

    Returns dict(patient, provider, room).
    """
    base = setup_base_practice()
    patient = create_cash_patient(full_name)
    accrue_strikes(patient["id"], base["provider"]["id"], base["room"]["id"], 5)
    return {"patient": patient, "provider": base["provider"], "room": base["room"]}


# ---------------------------------------------------------------------------
# Plans / phases / series
# ---------------------------------------------------------------------------
def create_finalized_exam(patient_id, provider_id, exam_type="INITIAL", severity_score=6):
    exam = get_success_data(
        api_client.create_exam(
            patient_id,
            create_exam_payload(provider_id, exam_type=exam_type, severity_score=severity_score),
            make_provider_headers(provider_id),
        )
    )
    get_success_data(
        api_client.finalize_exam(patient_id, exam["id"], make_provider_headers(provider_id))
    )
    return exam


def propose_plan(patient_id, provider_id, exam_record_id):
    return get_success_data(
        api_client.create_treatment_plan(
            patient_id, create_treatment_plan_payload(exam_record_id), make_provider_headers(provider_id)
        )
    )


def add_phase(patient_id, plan_id, provider_id, phase_type="ACUTE", sequence_index=0, visits_per_week=3, planned_visit_count=1):
    return get_success_data(
        api_client.add_phase(
            patient_id,
            plan_id,
            create_phase_payload(
                phase_type=phase_type,
                sequence_index=sequence_index,
                visits_per_week=visits_per_week,
                planned_visit_count=planned_visit_count,
            ),
            make_provider_headers(provider_id),
        )
    )


def activate_plan(patient_id, plan_id, provider_id):
    """Read the patient's current version, then activate the plan with it (OCC)."""
    patient = get_success_data(api_client.get_patient(patient_id, make_provider_headers(provider_id)))
    return get_success_data(
        api_client.activate_plan(
            patient_id,
            plan_id,
            {"expected_patient_version": patient["version"]},
            make_provider_headers(provider_id),
        )
    )


def setup_active_plan(payer_mode="CASH", phases=None, full_name="Plan Pat"):
    """An ACTIVE treatment plan for a patient.

    phases: list of phase kwargs dicts; defaults to a single ACUTE phase
    (planned 3). Returns dict(patient, provider, room, exam, plan, phases).
    """
    base = setup_base_practice()
    if payer_mode == "CASH":
        patient = create_cash_patient(full_name)
    elif payer_mode == "INSURANCE":
        patient = create_insurance_patient(full_name)
    else:
        raise ValueError(payer_mode)

    provider_id = base["provider"]["id"]
    exam = create_finalized_exam(patient["id"], provider_id)
    plan = propose_plan(patient["id"], provider_id, exam["id"])

    if phases is None:
        phases = [{"phase_type": "ACUTE", "sequence_index": 0, "visits_per_week": 3, "planned_visit_count": 3}]
    phase_objs = [add_phase(patient["id"], plan["id"], provider_id, **p) for p in phases]

    plan = activate_plan(patient["id"], plan["id"], provider_id)
    return {
        "patient": patient,
        "provider": base["provider"],
        "room": base["room"],
        "exam": exam,
        "plan": plan,
        "phases": phase_objs,
    }


def create_series(patient_id, plan_id, plan_phase_id, provider_id, room_id, **overrides):
    return get_success_data(
        api_client.create_series(
            patient_id,
            plan_id,
            create_series_payload(plan_phase_id, provider_id, room_id, **overrides),
            FRONTDESK,
        )
    )


def setup_plan_with_corrective_in_progress(reexam_severity=8, full_name="Plan Pat"):
    """An ACTIVE CASH plan with ACUTE(seq0, planned1) completed and CORRECTIVE(seq1,
    planned3) IN_PROGRESS; a SCHEDULED series for the CORRECTIVE phase; and a
    FINALIZED RE_EXAM with the given severity_score.

    Returns dict(patient, provider, room, plan, acute_phase, corrective_phase,
    corr_series, reexam).
    """
    ctx = setup_active_plan(
        payer_mode="CASH",
        full_name=full_name,
        phases=[
            {"phase_type": "ACUTE", "sequence_index": 0, "visits_per_week": 3, "planned_visit_count": 1},
            {"phase_type": "CORRECTIVE", "sequence_index": 1, "visits_per_week": 2, "planned_visit_count": 3},
        ],
    )
    patient_id = ctx["patient"]["id"]
    provider_id = ctx["provider"]["id"]
    room_id = ctx["room"]["id"]
    acute_phase = ctx["phases"][0]
    corr_phase = ctx["phases"][1]

    # Complete the single ACUTE visit so CORRECTIVE becomes IN_PROGRESS.
    create_attended_appointment(
        patient_id,
        provider_id,
        room_id,
        scheduled_start="2026-03-03T17:00:00Z",
        plan_phase_id=acute_phase["id"],
    )

    # SCHEDULED series for the CORRECTIVE phase.
    corr_series = create_series(
        patient_id,
        ctx["plan"]["id"],
        corr_phase["id"],
        provider_id,
        room_id,
        start_date="2026-03-09",
        weekday_pattern=[0, 2],
        start_time_minutes=540,
        duration_minutes=15,
    )

    # FINALIZED RE_EXAM with the requested severity.
    reexam = create_finalized_exam(
        patient_id, provider_id, exam_type="RE_EXAM", severity_score=reexam_severity
    )

    return {
        "patient": ctx["patient"],
        "provider": ctx["provider"],
        "room": ctx["room"],
        "plan": ctx["plan"],
        "acute_phase": acute_phase,
        "corrective_phase": corr_phase,
        "corr_series": corr_series,
        "reexam": reexam,
    }


def setup_two_proposed_plans(full_name="OCC Otto"):
    """A CASH patient with TWO PROPOSED plans p1 and p2, each with one phase, built
    from two FINALIZED exams. Returns dict(patient, provider, p1, p2, version).
    `version` is the patient's version BEFORE any activation."""
    provider = create_provider()
    patient = create_cash_patient(full_name)
    pid = patient["id"]
    prov_id = provider["id"]

    exam1 = create_finalized_exam(pid, prov_id, exam_type="INITIAL", severity_score=6)
    p1 = propose_plan(pid, prov_id, exam1["id"])
    add_phase(pid, p1["id"], prov_id, planned_visit_count=2)

    exam2 = create_finalized_exam(pid, prov_id, exam_type="RE_EXAM", severity_score=4)
    p2 = propose_plan(pid, prov_id, exam2["id"])
    add_phase(pid, p2["id"], prov_id, planned_visit_count=2)

    fresh = get_success_data(api_client.get_patient(pid, make_provider_headers(prov_id)))
    return {
        "patient": patient,
        "provider": provider,
        "p1": p1,
        "p2": p2,
        "version": fresh["version"],
    }


def setup_discontinued_plan_exhausted_policy(full_name="Cap Carl"):
    """An INSURANCE patient with a cap-exhausted ACTIVE policy (cap=1, one committed)
    and a DISCONTINUED plan whose ACUTE phase (planned 2) is therefore CANCELLED.

    Returns dict(patient, provider, room, policy, plan, phase).
    """
    base = setup_base_practice()
    patient = create_insurance_patient(full_name)
    pid = patient["id"]
    prov_id = base["provider"]["id"]
    room_id = base["room"]["id"]

    policy = add_policy(pid, annual_visit_cap=1)
    # Exhaust the single cap slot: book -> check-in -> sign -> complete.
    create_attended_appointment(
        pid, prov_id, room_id, scheduled_start="2026-03-03T17:00:00Z", insurance_policy_id=policy["id"]
    )

    exam = create_finalized_exam(pid, prov_id)
    plan = propose_plan(pid, prov_id, exam["id"])
    phase = add_phase(pid, plan["id"], prov_id, planned_visit_count=2)
    plan = activate_plan(pid, plan["id"], prov_id)
    get_success_data(api_client.discontinue_plan(pid, plan["id"], make_provider_headers(prov_id)))

    return {
        "patient": patient,
        "provider": base["provider"],
        "room": base["room"],
        "policy": policy,
        "plan": plan,
        "phase": phase,
    }
