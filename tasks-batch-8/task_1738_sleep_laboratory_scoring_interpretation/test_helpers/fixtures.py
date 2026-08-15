"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: SleepTechnologist / Scorer / InterpretingPhysician are
entity-backed roles. Ownership-gated calls (staffing confirm, task
start/submit, report sign/finalize/addenda, prescription order/cancel) always
use per-instance headers built from the real entity ids via the make_*
builders — never the shared TEST_USERS fallbacks.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    complete_acquisition_payload,
    create_authorization_payload,
    create_bed_payload,
    create_dme_order_payload,
    create_inter_rater_case_payload,
    create_interpretation_report_payload,
    create_patient_payload,
    create_physician_payload,
    create_referral_order_payload,
    create_scorer_payload,
    create_scoring_task_payload,
    create_sleep_study_payload,
    create_staffing_assignment_payload,
    create_therapy_prescription_payload,
    create_technologist_payload,
    split_decision_payload,
    submit_scoring_task_payload,
)
from .test_users import (
    TEST_USERS,
    make_physician_headers,
    make_scorer_headers,
    make_sleep_technologist_headers,
)

SCHED = TEST_USERS["scheduler_headers"]
DME = TEST_USERS["dme_coordinator_headers"]
DIRECTOR = TEST_USERS["lab_director_headers"]

IN_LAB_TYPES = ("PSG_DIAGNOSTIC", "SPLIT_NIGHT", "TITRATION_PAP")


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, DIRECTOR))


def create_patient(**overrides):
    return get_success_data(
        api_client.create_patient(create_patient_payload(**overrides), SCHED))


def create_technologist(credential="RPSGT", **overrides):
    return get_success_data(api_client.create_technologist(
        create_technologist_payload(credential=credential, **overrides),
        DIRECTOR))


def create_bed(titration_capable=None, is_active=None, room_label=None):
    return get_success_data(api_client.create_bed(
        create_bed_payload(room_label=room_label,
                           titration_capable=titration_capable,
                           is_active=is_active),
        DIRECTOR))


def create_scorer(credential="RPSGT", npi=None, reliability_pool=None,
                  **overrides):
    return get_success_data(api_client.create_scorer(
        create_scorer_payload(credential=credential, npi=npi,
                              reliability_pool=reliability_pool, **overrides),
        DIRECTOR))


def create_physician(npi=None, board_certified=None, **overrides):
    return get_success_data(api_client.create_physician(
        create_physician_payload(npi=npi, board_certified=board_certified,
                                 **overrides),
        DIRECTOR))


def create_order(patient_id, requested_study_type="HST", priority=None,
                 icd10_primary=None):
    """Create a referral order (born RECEIVED)."""
    return get_success_data(api_client.create_referral_order(
        create_referral_order_payload(
            patient_id, requested_study_type=requested_study_type,
            priority=priority, icd10_primary=icd10_primary),
        SCHED))


def get_order(order_id):
    return get_success_data(api_client.get_referral_order(order_id, SCHED))


def submit_authorization(order, approved_nights=1, window_start=None,
                         window_end=None, payer_name=None,
                         authorization_number=None):
    """Submit an authorization, threading the order's current version (OCC)."""
    payload = create_authorization_payload(
        order["version"], payer_name=payer_name,
        authorization_number=authorization_number,
        approved_nights=approved_nights,
        window_start=window_start, window_end=window_end)
    return get_success_data(
        api_client.submit_authorization(order["id"], payload, SCHED))


def decide_authorization(auth_id, outcome):
    return get_success_data(
        api_client.decide_authorization(auth_id, outcome, SCHED))


def create_authorized_order(patient_id, study_type="HST", approved_nights=1,
                            window_start=None, window_end=None, priority=None,
                            icd10_primary=None):
    """Order walked RECEIVED -> AUTH_IN_PROGRESS -> AUTHORIZED.

    Returns {"order": <freshly re-read AUTHORIZED order>, "auth": <APPROVED>}.
    """
    order = create_order(patient_id, requested_study_type=study_type,
                         priority=priority, icd10_primary=icd10_primary)
    auth = submit_authorization(order, approved_nights=approved_nights,
                                window_start=window_start,
                                window_end=window_end)
    auth = decide_authorization(auth["id"], "APPROVED")
    return {"order": get_order(order["id"]), "auth": auth}


# ---------------------------------------------------------------------------
# Tier 2: staffing and night coverage
# ---------------------------------------------------------------------------

def plan_staffing(technologist_id, shift_date, patient_capacity=2):
    return get_success_data(api_client.create_staffing_assignment(
        create_staffing_assignment_payload(
            technologist_id, shift_date, patient_capacity=patient_capacity),
        DIRECTOR))


def confirm_staffing(assignment):
    """Confirm as the assigned technologist (ownership-gated)."""
    return get_success_data(api_client.confirm_staffing_assignment(
        assignment["id"],
        make_sleep_technologist_headers(assignment["technologist_id"])))


def setup_night_coverage(shift_date=None, capacity=2, credential="RPSGT"):
    """A technologist with a CONFIRMED assignment covering `shift_date`."""
    shift_date = shift_date or TEST_DEFAULTS["STUDY_DATE"]
    tech = create_technologist(credential=credential)
    assignment = confirm_staffing(
        plan_staffing(tech["id"], shift_date, patient_capacity=capacity))
    return {"technologist": tech, "staffing": assignment}


# ---------------------------------------------------------------------------
# Tier 3: study lifecycle
# ---------------------------------------------------------------------------

def schedule_study(order_id, patient_id, study_type, scheduled_date=None,
                   bed_id=None):
    return get_success_data(api_client.create_sleep_study(
        create_sleep_study_payload(patient_id, order_id, study_type,
                                   scheduled_date=scheduled_date,
                                   bed_id=bed_id),
        SCHED))


def get_study(study_id):
    return get_success_data(api_client.get_sleep_study(study_id, DIRECTOR))


def check_in_study(study_id, technologist_id):
    return get_success_data(api_client.check_in_study(
        study_id, make_sleep_technologist_headers(technologist_id)))


def complete_acquisition(study_id, technologist_id,
                         total_recording_time_minutes=480,
                         titration_final_pressure_cm=None,
                         leak_95th_l_min=None):
    return get_success_data(api_client.complete_acquisition(
        study_id,
        complete_acquisition_payload(
            total_recording_time_minutes=total_recording_time_minutes,
            titration_final_pressure_cm=titration_final_pressure_cm,
            leak_95th_l_min=leak_95th_l_min),
        make_sleep_technologist_headers(technologist_id)))


def record_split_decision(study_id, technologist_id, **kwargs):
    return get_success_data(api_client.split_decision(
        study_id, split_decision_payload(**kwargs),
        make_sleep_technologist_headers(technologist_id)))


def setup_staff(with_rescorer=False, scorer_npi=None, physician_npi=None,
                rescorer_npi=None):
    """The lab's working roster: one technologist, one scorer, one physician.

    With `with_rescorer`, also a reliability-pool scorer (key "rescorer").
    """
    staff = {
        "technologist": create_technologist(),
        "scorer": create_scorer(npi=scorer_npi),
        "physician": create_physician(npi=physician_npi),
    }
    if with_rescorer:
        staff["rescorer"] = create_scorer(credential="RST",
                                          npi=rescorer_npi,
                                          reliability_pool=True)
    return staff


def setup_study_scheduled(study_type="HST", scheduled_date=None,
                          approved_nights=1, window_start=None,
                          window_end=None, priority=None, staff=None,
                          bed_titration_capable=None, night_capacity=2,
                          icd10_primary=None):
    """Authorized order + study booked in SCHEDULED.

    In-lab types also get a bed and CONFIRMED night coverage for
    `scheduled_date`. Returns a workspace dict.
    """
    scheduled_date = scheduled_date or TEST_DEFAULTS["STUDY_DATE"]
    staff = staff or setup_staff()
    patient = create_patient()
    ws = {"patient": patient, **staff}
    if study_type in IN_LAB_TYPES:
        if bed_titration_capable is None:
            bed_titration_capable = study_type in ("SPLIT_NIGHT",
                                                   "TITRATION_PAP")
        ws["bed"] = create_bed(titration_capable=bed_titration_capable)
        ws["staffing"] = plan_staffing(staff["technologist"]["id"],
                                       scheduled_date, night_capacity)
        confirm_staffing(ws["staffing"])
    booked = create_authorized_order(
        patient["id"], study_type=study_type, approved_nights=approved_nights,
        window_start=window_start, window_end=window_end, priority=priority,
        icd10_primary=icd10_primary)
    ws.update(booked)
    ws["study"] = schedule_study(
        booked["order"]["id"], patient["id"], study_type,
        scheduled_date=scheduled_date,
        bed_id=ws.get("bed", {}).get("id"))
    ws["order"] = get_order(booked["order"]["id"])
    return ws


def check_in_ws(ws):
    """Check the study in, moving the logical clock onto the scheduled date
    first when the study is not booked on the startup date."""
    scheduled_date = ws["study"]["scheduled_date"]
    if scheduled_date != TEST_DEFAULTS["STUDY_DATE"]:
        set_clock(f"{scheduled_date}T00:00:00Z")
    ws["study"] = check_in_study(ws["study"]["id"],
                                 ws["technologist"]["id"])
    return ws["study"]


def setup_study_in_progress(**kwargs):
    ws = setup_study_scheduled(**kwargs)
    check_in_ws(ws)
    return ws


def complete_acquisition_ws(ws, total_recording_time_minutes=480,
                            titration_final_pressure_cm=None,
                            leak_95th_l_min=None):
    ws["study"] = complete_acquisition(
        ws["study"]["id"], ws["technologist"]["id"],
        total_recording_time_minutes=total_recording_time_minutes,
        titration_final_pressure_cm=titration_final_pressure_cm,
        leak_95th_l_min=leak_95th_l_min)
    ws["order"] = get_order(ws["order"]["id"])
    return ws["study"]


def setup_scoring_queued(study_type="HST", total_recording_time_minutes=480,
                         titration_final_pressure_cm=None, leak_95th_l_min=None,
                         **kwargs):
    ws = setup_study_in_progress(study_type=study_type, **kwargs)
    complete_acquisition_ws(
        ws, total_recording_time_minutes=total_recording_time_minutes,
        titration_final_pressure_cm=titration_final_pressure_cm,
        leak_95th_l_min=leak_95th_l_min)
    return ws


# ---------------------------------------------------------------------------
# Tier 4: scoring tasks and index snapshots
# ---------------------------------------------------------------------------

def assign_task(study_id, scorer_id, assignment_kind="PRIMARY"):
    return get_success_data(api_client.create_scoring_task(
        create_scoring_task_payload(study_id, scorer_id, assignment_kind),
        DIRECTOR))


def get_task(task_id):
    return get_success_data(api_client.get_scoring_task(task_id, DIRECTOR))


def start_task(task_id, scorer_id):
    return get_success_data(api_client.start_scoring_task(
        task_id, make_scorer_headers(scorer_id)))


def submit_task(task_id, scorer_id, **overrides):
    return get_success_data(api_client.submit_scoring_task(
        task_id, submit_scoring_task_payload(**overrides),
        make_scorer_headers(scorer_id)))


def accept_task(task_id, physician_id):
    return get_success_data(api_client.accept_scoring_task(
        task_id, make_physician_headers(physician_id)))


def return_task(task_id, physician_id, reason="staging needs revision"):
    return get_success_data(api_client.return_scoring_task(
        task_id, reason, make_physician_headers(physician_id)))


def score_primary(ws, **submit_overrides):
    """Assign a PRIMARY task to the workspace scorer and walk it
    ASSIGNED -> IN_PROGRESS -> SUBMITTED -> ACCEPTED; refreshes the study
    (now SCORED with index snapshots). Returns the accepted task."""
    if ws["study"]["study_type"] in IN_LAB_TYPES:
        submit_overrides.setdefault("total_sleep_time_minutes", 360)
        submit_overrides.setdefault("total_recording_time_minutes", 420)
        submit_overrides.setdefault("epochs_total", 720)
    task = assign_task(ws["study"]["id"], ws["scorer"]["id"], "PRIMARY")
    start_task(task["id"], ws["scorer"]["id"])
    submit_task(task["id"], ws["scorer"]["id"], **submit_overrides)
    task = accept_task(task["id"], ws["physician"]["id"])
    ws["task"] = task
    ws["study"] = get_study(ws["study"]["id"])
    return task


def setup_scored_study(submit_overrides=None, study_type="HST", **kwargs):
    """Study walked all the way to SCORED with an ACCEPTED PRIMARY task."""
    ws = setup_scoring_queued(study_type=study_type, **kwargs)
    score_primary(ws, **(submit_overrides or {}))
    return ws


# ---------------------------------------------------------------------------
# Tier 4b: inter-rater reliability composites
# ---------------------------------------------------------------------------

def score_rescore(ws, rescorer=None, **submit_overrides):
    """Assign a RELIABILITY_RESCORE task to the pool rescorer and walk it to
    ACCEPTED. The study must already be SCORED."""
    rescorer = rescorer or ws["rescorer"]
    task = assign_task(ws["study"]["id"], rescorer["id"], "RELIABILITY_RESCORE")
    start_task(task["id"], rescorer["id"])
    submit_task(task["id"], rescorer["id"], **submit_overrides)
    task = accept_task(task["id"], ws["physician"]["id"])
    ws["rescore_task"] = task
    return task


def setup_double_scored_study(primary_submit=None, rescore_submit=None,
                              rescorer_npi=None, **kwargs):
    """HST study SCORED with an ACCEPTED PRIMARY and an ACCEPTED
    RELIABILITY_RESCORE by a different, pool-enrolled scorer."""
    kwargs.setdefault("staff", setup_staff(with_rescorer=True,
                                           rescorer_npi=rescorer_npi))
    ws = setup_scored_study(submit_overrides=primary_submit
                            or {"obstructive_apneas": 20, "hypopneas": 20},
                            study_type=kwargs.pop("study_type", "HST"),
                            **kwargs)
    score_rescore(ws, **(rescore_submit
                         or {"obstructive_apneas": 20, "hypopneas": 20}))
    return ws


def open_inter_rater_case(ws):
    case = get_success_data(api_client.create_inter_rater_case(
        create_inter_rater_case_payload(
            ws["study"]["id"], ws["task"]["id"], ws["rescore_task"]["id"]),
        DIRECTOR))
    ws["case"] = case
    return case


def adjudicate_case(case_id, epochs_concordant):
    return get_success_data(api_client.adjudicate_inter_rater_case(
        case_id, epochs_concordant, DIRECTOR))


def get_scorer(scorer_id):
    return get_success_data(api_client.get_scorer(scorer_id, DIRECTOR))


def adjudicated_case_for_rescorer(staff, rescorer, epochs_concordant,
                                  rescore_epochs=1000,
                                  rescore_events=(27, 0, 0, 30),
                                  primary_events=(30, 0, 0, 30),
                                  total_recording_time_minutes=360):
    """One full HST double-scored study whose case is adjudicated for
    `rescorer`. Primary defaults to REI 10.0 (60 events / 360 TRT); the
    rescore defaults to REI 9.5 (57 events / 360 TRT). Returns the case."""
    ws = setup_scored_study(
        staff=staff,
        total_recording_time_minutes=total_recording_time_minutes,
        submit_overrides={
            "obstructive_apneas": primary_events[0],
            "central_apneas": primary_events[1],
            "mixed_apneas": primary_events[2],
            "hypopneas": primary_events[3],
            "epochs_total": 1000,
            "total_recording_time_minutes": total_recording_time_minutes,
        })
    score_rescore(ws, rescorer=rescorer, **{
        "obstructive_apneas": rescore_events[0],
        "central_apneas": rescore_events[1],
        "mixed_apneas": rescore_events[2],
        "hypopneas": rescore_events[3],
        "epochs_total": rescore_epochs,
        "total_recording_time_minutes": total_recording_time_minutes,
    })
    case = open_inter_rater_case(ws)
    return adjudicate_case(case["id"], epochs_concordant)


def setup_open_primary_task(scorer):
    """A fresh HST study at SCORING_IN_PROGRESS whose PRIMARY task belongs to
    `scorer` and is IN_PROGRESS. Returns the workspace."""
    staff = setup_staff()
    ws = setup_scoring_queued(staff=staff)
    task = assign_task(ws["study"]["id"], scorer["id"], "PRIMARY")
    ws["task"] = start_task(task["id"], scorer["id"])
    ws["study"] = get_study(ws["study"]["id"])
    return ws


# ---------------------------------------------------------------------------
# Tier 5: reports, prescriptions, DME
# ---------------------------------------------------------------------------

def create_report(ws, diagnosis_code=None):
    """Create a DRAFT report for the workspace's SCORED study as the
    workspace physician, threading the study's current version (OCC)."""
    study = get_study(ws["study"]["id"])
    payload = create_interpretation_report_payload(
        study["id"], ws["task"]["id"], study["version"],
        diagnosis_code=diagnosis_code)
    report = get_success_data(api_client.create_interpretation_report(
        payload, make_physician_headers(ws["physician"]["id"])))
    ws["report"] = report
    ws["study"] = get_study(study["id"])
    return report


def get_report(report_id):
    return get_success_data(
        api_client.get_interpretation_report(report_id, DIRECTOR))


def sign_report(ws):
    report = get_success_data(api_client.sign_report(
        ws["report"]["id"],
        make_physician_headers(ws["report"]["physician_id"])))
    ws["report"] = report
    ws["study"] = get_study(ws["study"]["id"])
    return report


def setup_signed_report(sign_at=None, **kwargs):
    """Study SCORED + report DRAFT + SIGNED. `sign_at` moves the logical
    clock just before signing (turnaround tests)."""
    ws = setup_scored_study(**kwargs)
    create_report(ws)
    if sign_at is not None:
        set_clock(sign_at)
    sign_report(ws)
    return ws


def setup_finalized_report(**kwargs):
    ws = setup_signed_report(**kwargs)
    report = get_success_data(api_client.finalize_report(
        ws["report"]["id"],
        make_physician_headers(ws["report"]["physician_id"])))
    ws["report"] = report
    ws["study"] = get_study(ws["study"]["id"])
    return ws


def create_prescription(ws, **overrides):
    """Create a DRAFT prescription on the workspace report as its author,
    threading the report's current version (OCC)."""
    report = get_report(ws["report"]["id"])
    overrides.setdefault("cpap_pressure_cm", 9.0)
    payload = create_therapy_prescription_payload(
        report["id"], report["version"], **overrides)
    rx = get_success_data(api_client.create_therapy_prescription(
        payload, make_physician_headers(report["physician_id"])))
    ws["rx"] = rx
    return rx


def setup_ordered_prescription(submit_overrides=None, rx_overrides=None,
                               **kwargs):
    """SIGNED report (MILD by default) + CPAP prescription ORDERED."""
    submit_overrides = submit_overrides or {
        "obstructive_apneas": 40, "hypopneas": 56}  # REI 12.0 -> MILD
    ws = setup_signed_report(submit_overrides=submit_overrides, **kwargs)
    create_prescription(ws, **(rx_overrides or {}))
    ws["rx"] = get_success_data(api_client.order_prescription(
        ws["rx"]["id"], make_physician_headers(ws["report"]["physician_id"])))
    return ws


def setup_delivered_dme(vendor_name="DME Corp", **kwargs):
    """Prescription ORDERED + DME order DISPATCHED -> DELIVERED (the delivery
    fulfills the prescription)."""
    ws = setup_ordered_prescription(**kwargs)
    dme = get_success_data(api_client.create_dme_order(
        create_dme_order_payload(ws["rx"]["id"], vendor_name=vendor_name),
        DME))
    dme = get_success_data(api_client.deliver_dme_order(dme["id"], DME))
    ws["dme"] = dme
    ws["rx"] = get_success_data(
        api_client.get_therapy_prescription(ws["rx"]["id"], DIRECTOR))
    return ws
