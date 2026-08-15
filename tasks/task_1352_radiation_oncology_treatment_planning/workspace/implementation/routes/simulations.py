"""Simulation appointments (PRD 3.2)."""
from flask import Blueprint

from db import store, new_entity, touch, sorted_all
from errors import (err, ERR_NOT_FOUND, ERR_COURSE_TERMINAL,
                    ERR_SIMULATION_NOT_SCHEDULED, ERR_MACHINE_TYPE_MISMATCH,
                    ERR_MACHINE_NOT_OPERATIONAL, ERR_IMMOBILIZATION_REQUIRED,
                    ERR_SIMULATOR_SLOT_CONFLICT, ERR_SIMULATOR_DAILY_CAPACITY,
                    ERR_COURSE_NOT_ADAPTING)
from middleware import require_roles, ALL_ROLES, get_body
from response import success, paginate
from serializers import simulation_json
from services import calc
from services.billing import bill_draft
from timeutil import new_id
from validate import req_enum, opt_enum, req_dt_pair, req_num

bp = Blueprint("simulations", __name__)

DEVICES = {"NONE", "THERMOPLASTIC_MASK", "VACUUM_CRADLE", "BODY_FRAME"}
PURPOSES = {"INITIAL", "ADAPTATION"}
SBRT_DEVICES = {"THERMOPLASTIC_MASK", "BODY_FRAME"}


def get_sim_or_404(aid):
    a = store.simulations.get(aid)
    if a is None:
        err(ERR_NOT_FOUND, "simulation appointment not found")
    return a


@bp.post("/oncology/treatment-courses/<cid>/simulation-appointments")
@require_roles("Scheduler")
def book_simulation(cid, user_id):
    course = store.courses.get(cid)
    if course is None:
        err(ERR_NOT_FOUND, "treatment course not found")
    body = get_body()
    # p3 existence: body-referenced machine_id
    machine_id = body.get("machine_id")
    if isinstance(machine_id, str) and machine_id not in store.machines:
        err(ERR_NOT_FOUND, "machine not found")
    # p4 schema
    from validate import req_str
    machine_id = req_str(body, "machine_id")
    s_raw, e_raw, s, e = req_dt_pair(body)
    device = req_enum(body, "immobilization_device", DEVICES)
    purpose = opt_enum(body, "purpose", PURPOSES, default="INITIAL")
    # p6 state gates: terminal lockout; ADAPTATION purpose needs ADAPTATION_REQUIRED
    if course["status"] in ("COMPLETED", "DISCONTINUED"):
        err(ERR_COURSE_TERMINAL, "Course is terminal")
    if purpose == "ADAPTATION" and course["status"] != "ADAPTATION_REQUIRED":
        err(ERR_COURSE_NOT_ADAPTING,
            "ADAPTATION simulation bookings require course ADAPTATION_REQUIRED")
    # p11 machine constraints: type first, then operational, then SBRT immobilization
    machine = store.machines[machine_id]
    if machine["machine_type"] != "CT_SIMULATOR":
        err(ERR_MACHINE_TYPE_MISMATCH, "Simulation requires a CT_SIMULATOR")
    if machine["status"] != "OPERATIONAL":
        err(ERR_MACHINE_NOT_OPERATIONAL, "Machine is DOWN")
    if course["technique"] == "SBRT" and device not in SBRT_DEVICES:
        err(ERR_IMMOBILIZATION_REQUIRED,
            "SBRT courses require THERMOPLASTIC_MASK or BODY_FRAME")
    # p12 interval occupation: pure half-open overlap vs SCHEDULED on this simulator
    for a in store.simulations.values():
        if a["machine_id"] == machine_id and a["status"] == "SCHEDULED":
            if s < a["_end"] and a["_start"] < e:
                err(ERR_SIMULATOR_SLOT_CONFLICT,
                    "Simulator booking overlaps an existing appointment")
    # p13 aggregate daily capacity per UTC date (SCHEDULED or COMPLETED)
    day = s.date()
    same_day = [a for a in store.simulations.values()
                if a["machine_id"] == machine_id
                and a["status"] in ("SCHEDULED", "COMPLETED")
                and a["_start"].date() == day]
    if len(same_day) >= calc.SIM_DAILY_CAPACITY:
        err(ERR_SIMULATOR_DAILY_CAPACITY,
            "Simulator daily capacity reached for that date")
    appt = new_entity()
    appt.update({
        "id": new_id(), "course_id": cid, "machine_id": machine_id,
        "purpose": purpose, "start_time": s_raw, "end_time": e_raw,
        "_start": s, "_end": e,
        "immobilization_device": device, "patient_weight_kg": None,
        "status": "SCHEDULED",
    })
    store.simulations[appt["id"]] = appt
    if course["status"] == "CONSULT":
        course["status"] = "SIMULATION_SCHEDULED"
        touch(course)
    return success(simulation_json(appt), 201)


@bp.get("/oncology/treatment-courses/<cid>/simulation-appointments")
@require_roles(*ALL_ROLES)
def list_simulations(cid, user_id):
    if cid not in store.courses:
        err(ERR_NOT_FOUND, "treatment course not found")
    items = sorted_all(a for a in store.simulations.values() if a["course_id"] == cid)
    page, meta = paginate(items)
    return success([simulation_json(a) for a in page], 200, pagination=meta)


@bp.post("/oncology/simulation-appointments/<aid>/complete")
@require_roles("RadiationTherapist")
def complete_simulation(aid, user_id):
    appt = get_sim_or_404(aid)
    body = get_body()
    weight = req_num(body, "patient_weight_kg", minimum_exclusive=0)
    if appt["status"] != "SCHEDULED":
        err(ERR_SIMULATION_NOT_SCHEDULED, "Appointment is not SCHEDULED")
    course = store.courses[appt["course_id"]]
    if course["status"] in ("COMPLETED", "DISCONTINUED"):
        err(ERR_COURSE_TERMINAL, "Course is terminal")
    appt["status"] = "COMPLETED"
    appt["patient_weight_kg"] = weight
    touch(appt)
    # first completion: SIMULATION_SCHEDULED -> SIMULATED + baseline captured;
    # a completion during ADAPTATION_REQUIRED leaves the course in place.
    if course["status"] == "SIMULATION_SCHEDULED" and course["baseline_weight_kg"] is None:
        course["status"] = "SIMULATED"
        course["baseline_weight_kg"] = weight
        touch(course)
    bill_draft(course, "SIMULATION", "Simulation appointment",
               calc.SIMULATION_FEE_CENTS, appt["id"])
    return success(simulation_json(appt), 200)


@bp.post("/oncology/simulation-appointments/<aid>/cancel")
@require_roles("Scheduler")
def cancel_simulation(aid, user_id):
    appt = get_sim_or_404(aid)
    get_body()
    if appt["status"] != "SCHEDULED":
        err(ERR_SIMULATION_NOT_SCHEDULED, "Appointment is not SCHEDULED")
    appt["status"] = "CANCELLED"
    touch(appt)
    return success(simulation_json(appt), 200)


@bp.post("/oncology/simulation-appointments/<aid>/mark-no-show")
@require_roles("RadiationTherapist")
def no_show_simulation(aid, user_id):
    appt = get_sim_or_404(aid)
    get_body()
    if appt["status"] != "SCHEDULED":
        err(ERR_SIMULATION_NOT_SCHEDULED, "Appointment is not SCHEDULED")
    appt["status"] = "NO_SHOW"
    touch(appt)
    return success(simulation_json(appt), 200)
