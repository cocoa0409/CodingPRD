"""Composite setup helpers for the oncology workflow.

Every fixture builds its preconditions from scratch via PRD-declared endpoints
(the runner restarts the server before each test, so each test starts empty).
Setup calls use get_success_data() so failures surface as clear setup errors.
"""
from datetime import date, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_patient_payload,
    create_course_payload,
    create_simulation_payload,
    complete_simulation_payload,
    create_contour_set_payload,
    create_plan_payload,
    create_dose_constraint_payload,
    create_physics_check_payload,
    create_fraction_session_payload,
    create_machine_payload,
    create_interruption_payload,
    create_chart_review_payload,
)
from .test_users import TEST_USERS, make_oncologist_headers, make_dosimetrist_headers, make_physicist_headers

ONC_A = TEST_USERS["oncologist_headers"]
ONC_B = TEST_USERS["oncologist_b_headers"]
DOS_A = TEST_USERS["dosimetrist_headers"]
PHYS_A = TEST_USERS["physicist_headers"]
PHYS_B = TEST_USERS["physicist_b_headers"]
RTT_A = TEST_USERS["therapist_headers"]
SCHED = TEST_USERS["scheduler_headers"]
BILL = TEST_USERS["billing_headers"]
ADMIN = TEST_USERS["admin_headers"]


def setup_patient(mrn=None, **overrides):
    """Register one patient; returns the Patient record."""
    payload = create_patient_payload(**overrides)
    if mrn is not None:
        payload["mrn"] = mrn
    return get_success_data(api_client.create_patient(payload, SCHED))


def setup_machine(machine_type="LINAC", name=None, room=None):
    """Register one machine; returns the TreatmentMachine record."""
    name = name or ("Linac" if machine_type == "LINAC" else "CT-Sim")
    room = room or ("TX1" if machine_type == "LINAC" else "SIM1")
    return get_success_data(api_client.create_machine(
        create_machine_payload(name=name, machine_type=machine_type, room=room), ADMIN))


def setup_course(patient_id, **overrides):
    """Open a treatment course; returns the TreatmentCourse record (CONSULT)."""
    return get_success_data(api_client.create_course(
        patient_id, create_course_payload(**overrides), ONC_A))


def setup_course_with_simulation(course_id, machine_id, weight=80.0, immobilization=None,
                                 sim_start="2026-07-30T09:00:00Z", sim_end="2026-07-30T09:30:00Z"):
    """Book + complete a simulation; returns the COMPLETED appointment.
    Drives the course CONSULT -> SIMULATION_SCHEDULED -> SIMULATED."""
    immobilization = immobilization or "THERMOPLASTIC_MASK"
    sim = get_success_data(api_client.create_simulation(
        course_id,
        create_simulation_payload(machine_id=machine_id, start_time=sim_start,
                                  end_time=sim_end, immobilization_device=immobilization),
        SCHED))
    return get_success_data(api_client.complete_simulation(
        sim["id"], complete_simulation_payload(patient_weight_kg=weight), RTT_A))


def setup_approved_contour(course_id, onc_creator=ONC_A, onc_reviewer=ONC_B, **overrides):
    """Create + submit + approve a contour set; returns the APPROVED ContourSet.
    Drives the course SIMULATED -> CONTOURING -> PLANNING."""
    cs = get_success_data(api_client.create_contour_set(
        course_id, create_contour_set_payload(**overrides), onc_creator))
    get_success_data(api_client.submit_contour_set(cs["id"], onc_creator))
    return get_success_data(api_client.approve_contour_set(cs["id"], onc_reviewer))


def setup_course_in_planning(patient_id=None, technique="IMRT", total_dose=2000, fractions=10,
                             contour_overrides=None, patient_weight=80.0, immobilization=None,
                             patient=None, sim_machine=None, mrn=None, **course_overrides):
    """Full setup: patient + simulator + course through CONSULT..PLANNING.
    Returns dict with patient, course (post-PLANNING, fresh read), contour set,
    and simulator machine. Extra kwargs (e.g. intent, diagnosis_code) are
    forwarded into the course-creation payload."""
    patient = patient or setup_patient(mrn=mrn)
    sim_m = sim_machine or setup_machine("CT_SIMULATOR", name="CT-Sim", room="SIM1")
    course = setup_course(patient["id"], technique=technique,
                          prescribed_total_dose_cGy=total_dose, planned_fractions=fractions,
                          **course_overrides)
    setup_course_with_simulation(course["id"], sim_m["id"], weight=patient_weight,
                                 immobilization=immobilization)
    contour = setup_approved_contour(course["id"], **(contour_overrides or {}))
    course = get_success_data(api_client.get_course(course["id"], ONC_A))
    return {"patient": patient, "course": course, "contour": contour, "sim_machine": sim_m}


def setup_planning_with_draft_plan(**kwargs):
    """Course in PLANNING plus a DRAFT plan. Adds 'plan' to the returned dict."""
    ctx = setup_course_in_planning(**kwargs)
    course = ctx["course"]
    plan = get_success_data(api_client.create_plan(
        course["id"],
        create_plan_payload(contour_set_id=ctx["contour"]["id"],
                            target_total_dose_cGy=course["prescribed_total_dose_cGy"],
                            planned_fractions=course["planned_fractions"],
                            expected_course_version=course["version"]),
        DOS_A))
    ctx["plan"] = plan
    return ctx


def setup_submitted_plan(**kwargs):
    """Plan in PENDING_PRIMARY_CHECK with one satisfied constraint."""
    ctx = setup_planning_with_draft_plan(**kwargs)
    plan = ctx["plan"]
    get_success_data(api_client.create_dose_constraint(
        plan["id"], create_dose_constraint_payload(), DOS_A))
    plan = get_success_data(api_client.submit_plan_for_check(plan["id"], DOS_A))
    ctx["plan"] = plan
    return ctx


def setup_approved_plan(**kwargs):
    """Plan approved for delivery: both physics checks PASS. Course TREATMENT_READY."""
    ctx = setup_submitted_plan(**kwargs)
    plan = ctx["plan"]
    get_success_data(api_client.create_physics_check(
        plan["id"], create_physics_check_payload(check_type="PRIMARY", outcome="PASS"), PHYS_A))
    get_success_data(api_client.create_physics_check(
        plan["id"], create_physics_check_payload(check_type="SECOND", outcome="PASS"), PHYS_B))
    ctx["plan"] = get_success_data(api_client.get_plan(plan["id"], DOS_A))
    ctx["course"] = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
    return ctx


def setup_treatment_ready_linac(**kwargs):
    """Approved plan plus a LINAC machine. Adds 'linac' to the returned dict."""
    ctx = setup_approved_plan(**kwargs)
    ctx["linac"] = setup_machine("LINAC", name="Linac", room="TX1")
    return ctx


def book_session(course_id, plan_id, machine_id, start_time, end_time, igrt=None):
    """Book one fraction session; returns the SCHEDULED session record."""
    payload = create_fraction_session_payload(
        plan_id=plan_id, machine_id=machine_id, start_time=start_time, end_time=end_time)
    if igrt is not None:
        payload["igrt_planned"] = igrt
    return get_success_data(api_client.create_fraction_session(course_id, payload, SCHED))


def deliver_session(session_id):
    """Deliver one fraction session; returns the DELIVERED record."""
    return get_success_data(api_client.deliver_fraction(session_id, RTT_A))


def weekday_slot(d: date, hour=9, minute=0, duration_min=20):
    """Return (start_time, end_time) ISO strings for a slot on date d."""
    from datetime import datetime, timezone
    s = datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)
    e = s + timedelta(minutes=duration_min)
    fmt = lambda x: x.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt(s), fmt(e)


def setup_on_treatment(num_delivered=1, technique="IMRT", total_dose=2000, fractions=10,
                       booking_start=date(2026, 8, 3), chart_review_every=5, **kwargs):
    """Course driven to ON_TREATMENT with `num_delivered` DELIVERED fractions.

    Books num_delivered sessions on consecutive weekdays starting booking_start
    and delivers them, inserting PASS chart reviews as needed to keep the gate
    open (PASS review after every CHART_REVIEW_FRACTION_LIMIT deliveries except
    at the end). Returns ctx with patient/course/plan/contour/linac plus
    'sessions' (delivered records)."""
    ctx = setup_treatment_ready_linac(technique=technique, total_dose=total_dose,
                                      fractions=fractions, **kwargs)
    sessions = []
    delivered = 0
    d = booking_start
    while delivered < num_delivered:
        # skip weekends
        while d.weekday() >= 5:
            d += timedelta(days=1)
        s_t, e_t = weekday_slot(d)
        sess = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"], s_t, e_t)
        sessions.append(deliver_session(sess["id"]))
        delivered += 1
        d += timedelta(days=1)
        if delivered < num_delivered and delivered % chart_review_every == 0:
            get_success_data(api_client.create_chart_review(
                ctx["course"]["id"], create_chart_review_payload(outcome="PASS"), PHYS_A))
    ctx["sessions"] = sessions
    ctx["course"] = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
    return ctx


def setup_course_with_draft_claim(num_delivered=1, open_claim_after_approval=True, **kwargs):
    """ON_TREATMENT course with a DRAFT billing claim (opened after plan approval,
    so physics/planning lines are live-appended; delivery lines appended on deliver).
    Returns ctx with 'claim'."""
    ctx = setup_treatment_ready_linac(**kwargs)
    claim = get_success_data(api_client.create_claim(ctx["course"]["id"], BILL)) \
        if open_claim_after_approval else None
    # deliver
    sessions = []
    d = date(2026, 8, 3)
    for _ in range(num_delivered):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        s_t, e_t = weekday_slot(d)
        sess = book_session(ctx["course"]["id"], ctx["plan"]["id"], ctx["linac"]["id"], s_t, e_t)
        sessions.append(deliver_session(sess["id"]))
        d += timedelta(days=1)
    ctx["sessions"] = sessions
    if claim is not None:
        ctx["claim"] = get_success_data(api_client.get_claim(claim["id"], BILL))
    ctx["course"] = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
    return ctx
