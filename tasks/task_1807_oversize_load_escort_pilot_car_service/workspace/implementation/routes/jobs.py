"""Job endpoints: booking, amendment, quote, acceptance, movement control, cancel."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_JOB_NOT_FOUND,
    ERR_CARRIER_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_JOB_INVALID_STATE,
    ERR_STALE_JOB_VERSION,
    ERR_QUOTE_EXPIRED,
    ERR_CREDIT_LIMIT_WOULD_BE_EXCEEDED,
    ERR_PERMIT_WINDOW_INSUFFICIENT,
    ERR_CURFEW_WINDOW_VIOLATION,
    ERR_ASSIGNMENTS_INCOMPLETE,
    ERR_COMMS_CHECKIN_OVERDUE,
    raise_err,
)
from middleware import require_roles, check_carrier_owner, ALL_ROLES
from mutate import mark
from response import success_object, paginate
from serializers import ser_job, ser_leg
from services import calc, cascade
from util import (
    body_json, req_string, req_int, opt_int, req_dt, opt_dt, require_field,
    new_id, is_int,
)

bp = Blueprint("jobs", __name__)

NON_TERMINAL_JOB_STATES_FOR_CANCEL = ("DELIVERED", "CLOSED", "CANCELLED")
INVOICE_BLOCKS_CANCEL_STATES = ("FINALIZED", "DISPUTED", "PAID")


def _new_resource():
    n = db.now()
    return {"id": new_id(), "created_at": n, "updated_at": n, "version": 1,
            "_seq": db.next_seq()}


def _get_job_or_404(job_id):
    job = db.jobs.get(job_id)
    if job is None:
        raise_err(ERR_JOB_NOT_FOUND, f"Job {job_id} not found")
    return job


def _validate_leg_spec(el, idx):
    if not isinstance(el, dict):
        raise_err(ERR_INVALID_REQUEST, f"legs[{idx}] must be an object")
    state_code = require_field(el, "state_code")
    if not isinstance(state_code, str) or state_code not in calc.VALID_STATE_CODES:
        raise_err(ERR_INVALID_REQUEST, f"legs[{idx}].state_code must be one of TX, OK, KS, LA")
    sequence_index = require_field(el, "sequence_index")
    if not is_int(sequence_index) or sequence_index < 0:
        raise_err(ERR_INVALID_REQUEST, f"legs[{idx}].sequence_index must be an integer >= 0")
    distance_miles = require_field(el, "distance_miles")
    if not is_int(distance_miles) or distance_miles <= 0:
        raise_err(ERR_INVALID_REQUEST, f"legs[{idx}].distance_miles must be an integer > 0")
    entry = req_dt(el, "planned_entry_at")
    exit_ = req_dt(el, "planned_exit_at")
    if not exit_ > entry:
        raise_err(ERR_INVALID_REQUEST, f"legs[{idx}].planned_exit_at must be later than planned_entry_at")
    clearance = require_field(el, "map_min_clearance_inches")
    if not is_int(clearance) or clearance < 0:
        raise_err(ERR_INVALID_REQUEST, f"legs[{idx}].map_min_clearance_inches must be an integer >= 0")
    return {
        "state_code": state_code,
        "sequence_index": sequence_index,
        "distance_miles": distance_miles,
        "planned_entry_at": entry,
        "planned_exit_at": exit_,
        "map_min_clearance_inches": clearance,
    }


@bp.post("/jobs")
def create_job():
    uid, _role = require_roles("CarrierRep")
    data = body_json(request)
    carrier_id = req_string(data, "carrier_id")
    load_description = req_string(data, "load_description")
    width = req_int(data, "width_inches", min_v=1)
    height = req_int(data, "height_inches", min_v=1)
    length = req_int(data, "length_inches", min_v=1)
    gross = req_int(data, "gross_weight_lbs", min_v=1)
    ws = req_dt(data, "window_start_at")
    we = req_dt(data, "window_end_at")
    if not we > ws:
        raise_err(ERR_INVALID_REQUEST, "window_end_at must be later than window_start_at")
    legs_in = require_field(data, "legs")
    if not isinstance(legs_in, list) or len(legs_in) < 1:
        raise_err(ERR_INVALID_REQUEST, "legs must be an array with at least one element")
    leg_specs = [_validate_leg_spec(el, i) for i, el in enumerate(legs_in)]

    carrier = db.carriers.get(carrier_id)
    if carrier is None:
        raise_err(ERR_CARRIER_NOT_FOUND, f"Carrier {carrier_id} not found")
    if carrier_id != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "CarrierRep may only book jobs for its own carrier")

    job = _new_resource()
    job.update({
        "carrier_id": carrier_id,
        "load_description": load_description,
        "width_inches": width,
        "height_inches": height,
        "length_inches": length,
        "gross_weight_lbs": gross,
        "window_start_at": ws,
        "window_end_at": we,
        "legs": leg_specs,
        "job_status": "DRAFT",
        "quoted_cents": None,
        "quoted_at": None,
        "quote_expires_at": None,
        "booked_at": None,
        "departed_at": None,
        "delivered_at": None,
        "cancelled_at": None,
        "cancel_fee_cents": 0,
        "cancel_fee_tier": None,
        "total_escort_positions": 0,
    })
    db.jobs[job["id"]] = job

    for spec in sorted(leg_specs, key=lambda s: s["sequence_index"]):
        leg = _new_resource()
        leg.update({
            "job_id": job["id"],
            "state_code": spec["state_code"],
            "sequence_index": spec["sequence_index"],
            "distance_miles": spec["distance_miles"],
            "planned_entry_at": spec["planned_entry_at"],
            "planned_exit_at": spec["planned_exit_at"],
            "map_min_clearance_inches": spec["map_min_clearance_inches"],
            "leg_status": "PENDING",
            "required_front_escorts": 0,
            "required_rear_escorts": 0,
            "requires_height_pole": False,
            "requires_police_escort": False,
            "requires_route_survey": False,
            "police_confirmed": False,
            "clearance_verdict": "UNKNOWN",
            "survey_min_clearance_inches": None,
        })
        db.legs[leg["id"]] = leg

    return success_object(ser_job(job), status=201)


@bp.get("/jobs")
def list_jobs():
    require_roles(*ALL_ROLES)
    carrier_id = request.args.get("carrier_id")
    job_status = request.args.get("job_status")
    rows = list(db.jobs.values())
    if carrier_id is not None:
        rows = [j for j in rows if j["carrier_id"] == carrier_id]
    if job_status is not None:
        rows = [j for j in rows if j["job_status"] == job_status]
    rows.sort(key=lambda j: (j["created_at"], j["_seq"]))
    return paginate(request, [ser_job(j) for j in rows])


@bp.get("/jobs/<id>")
def get_job(id):
    require_roles(*ALL_ROLES)
    return success_object(ser_job(_get_job_or_404(id)))


DIMENSIONAL_FIELDS = ("width_inches", "height_inches", "length_inches", "gross_weight_lbs")


@bp.post("/jobs/<id>/amendments")
def amend_job(id):
    uid, role = require_roles("CarrierRep", "Dispatcher")
    data = body_json(request)
    expected = req_int(data, "expected_job_version")
    supplied = {}
    if "load_description" in data and data["load_description"] is not None:
        if not isinstance(data["load_description"], str):
            raise_err(ERR_INVALID_REQUEST, "load_description must be a string")
        supplied["load_description"] = data["load_description"]
    for f in DIMENSIONAL_FIELDS:
        v = opt_int(data, f, min_v=1)
        if v is not None:
            supplied[f] = v
    new_ws = opt_dt(data, "window_start_at")
    new_we = opt_dt(data, "window_end_at")
    if new_ws is not None and new_we is not None and not new_we > new_ws:
        raise_err(ERR_INVALID_REQUEST, "window_end_at must be later than window_start_at")

    job = _get_job_or_404(id)
    if role == "CarrierRep":
        check_carrier_owner(job)
    if job["job_status"] not in ("DRAFT", "QUOTED"):
        raise_err(ERR_JOB_INVALID_STATE, "Amendments require the job to be DRAFT or QUOTED")
    if expected != job["version"]:
        raise_err(ERR_STALE_JOB_VERSION, "expected_job_version does not match the job's current version")

    eff_ws = new_ws if new_ws is not None else job["window_start_at"]
    eff_we = new_we if new_we is not None else job["window_end_at"]
    if not eff_we > eff_ws:
        raise_err(ERR_INVALID_REQUEST, "window_end_at must be later than window_start_at")

    dimensional_changed = any(
        f in supplied and supplied[f] != job[f] for f in DIMENSIONAL_FIELDS
    )
    for f, v in supplied.items():
        job[f] = v
    if new_ws is not None:
        job["window_start_at"] = new_ws
    if new_we is not None:
        job["window_end_at"] = new_we

    if job["job_status"] == "QUOTED":
        job["job_status"] = "DRAFT"
        job["quoted_cents"] = None
        job["quoted_at"] = None
        job["quote_expires_at"] = None
        job["total_escort_positions"] = 0

    if dimensional_changed:
        for leg in cascade.legs_of_job(job["id"]):
            if leg["leg_status"] == "DETERMINED":
                leg["leg_status"] = "PENDING"
                calc.reset_requirements(leg)
                mark(leg)

    mark(job)
    return success_object(ser_job(job))


@bp.post("/jobs/<id>/quote")
def quote_job(id):
    require_roles("Dispatcher")
    body_json(request)
    job = _get_job_or_404(id)
    if job["job_status"] != "DRAFT":
        raise_err(ERR_JOB_INVALID_STATE, "Quoting requires the job to be DRAFT")
    legs = sorted(cascade.legs_of_job(job["id"]),
                  key=lambda l: (l["sequence_index"], l["_seq"]))
    for leg in legs:
        calc.determine_requirements(job, leg)
        leg["leg_status"] = "DETERMINED"
        mark(leg)
    quoted, positions = calc.quote_estimate(job, legs)
    n = db.now()
    job["quoted_cents"] = quoted
    job["quoted_at"] = n
    job["quote_expires_at"] = n + timedelta(hours=calc.QUOTE_TTL_HOURS)
    job["total_escort_positions"] = positions
    job["job_status"] = "QUOTED"
    mark(job)
    return success_object(ser_job(job))


@bp.post("/jobs/<id>/accept-quote")
def accept_quote(id):
    uid, _role = require_roles("CarrierRep")
    body_json(request)
    job = _get_job_or_404(id)
    check_carrier_owner(job)
    if job["job_status"] != "QUOTED":
        raise_err(ERR_JOB_INVALID_STATE, "Accepting a quote requires the job to be QUOTED")
    if not db.now() < job["quote_expires_at"]:
        raise_err(ERR_QUOTE_EXPIRED, "The quote has expired")
    from serializers import carrier_credit_available
    carrier = db.carriers.get(job["carrier_id"])
    if carrier_credit_available(carrier) < job["quoted_cents"]:
        raise_err(ERR_CREDIT_LIMIT_WOULD_BE_EXCEEDED,
                  "Accepting this quote would exceed the carrier's credit limit")
    job["job_status"] = "BOOKED"
    job["booked_at"] = db.now()
    mark(job)
    return success_object(ser_job(job))


@bp.post("/jobs/<id>/schedule")
def schedule_job(id):
    require_roles("Dispatcher")
    body_json(request)
    job = _get_job_or_404(id)
    if job["job_status"] != "CLEARED":
        raise_err(ERR_JOB_INVALID_STATE, "Scheduling requires the job to be CLEARED")
    legs = cascade.legs_of_job(job["id"])
    for leg in legs:
        permits = cascade.permits_of_leg(leg["id"])
        if not any(calc.permit_covers(p, leg["planned_entry_at"], leg["planned_exit_at"])
                   for p in permits):
            raise_err(ERR_PERMIT_WINDOW_INSUFFICIENT,
                      f"No ISSUED permit fully covers leg {leg['id']}'s traversal window")
    for leg in legs:
        if calc.curfew_violation(leg["state_code"], leg["planned_entry_at"], leg["planned_exit_at"]):
            raise_err(ERR_CURFEW_WINDOW_VIOLATION,
                      f"Leg {leg['id']}'s traversal intersects a curfew window")
    if not cascade.required_positions_covered(job):
        raise_err(ERR_ASSIGNMENTS_INCOMPLETE,
                  "Every required escort position must be covered by an ACCEPTED assignment")
    job["job_status"] = "SCHEDULED"
    mark(job)
    return success_object(ser_job(job))


@bp.post("/jobs/<id>/depart")
def depart_job(id):
    require_roles("Dispatcher")
    body_json(request)
    job = _get_job_or_404(id)
    if job["job_status"] != "SCHEDULED":
        raise_err(ERR_JOB_INVALID_STATE, "Departure requires the job to be SCHEDULED")
    n = db.now()
    if n < job["window_start_at"] - timedelta(minutes=30):
        raise_err(ERR_INVALID_REQUEST, "Departure may occur no earlier than 30 minutes before window_start_at")
    job["job_status"] = "EN_ROUTE"
    job["departed_at"] = n
    for leg in cascade.legs_of_job(job["id"]):
        for a in cascade.assignments_of_leg(leg["id"]):
            if a["assignment_status"] == "ACCEPTED":
                a["assignment_status"] = "ACTIVE"
                a["activated_at"] = n
                a["last_checkin_at"] = n
                mark(a)
    mark(job)
    return success_object(ser_job(job))


@bp.post("/jobs/<id>/hold")
def hold_job(id):
    require_roles("Dispatcher")
    body_json(request)
    job = _get_job_or_404(id)
    if job["job_status"] != "EN_ROUTE":
        raise_err(ERR_JOB_INVALID_STATE, "Hold requires the job to be EN_ROUTE")
    job["job_status"] = "ON_HOLD"
    mark(job)
    return success_object(ser_job(job))


@bp.post("/jobs/<id>/resume")
def resume_job(id):
    require_roles("Dispatcher")
    body_json(request)
    job = _get_job_or_404(id)
    if job["job_status"] != "ON_HOLD":
        raise_err(ERR_JOB_INVALID_STATE, "Resume requires the job to be ON_HOLD")
    job["job_status"] = "EN_ROUTE"
    mark(job)
    return success_object(ser_job(job))


@bp.post("/jobs/<id>/deliver")
def deliver_job(id):
    require_roles("Dispatcher")
    body_json(request)
    job = _get_job_or_404(id)
    if job["job_status"] != "EN_ROUTE":
        raise_err(ERR_JOB_INVALID_STATE, "Delivery requires the job to be EN_ROUTE")
    n = db.now()
    stale_limit = timedelta(minutes=90)
    active = []
    for leg in cascade.legs_of_job(job["id"]):
        for a in cascade.assignments_of_leg(leg["id"]):
            if a["assignment_status"] == "ACTIVE":
                active.append(a)
    for a in active:
        if n - a["last_checkin_at"] > stale_limit:
            raise_err(ERR_COMMS_CHECKIN_OVERDUE,
                      "An ACTIVE assignment's last check-in is more than 90 minutes old")
    job["job_status"] = "DELIVERED"
    job["delivered_at"] = n
    for a in active:
        a["assignment_status"] = "COMPLETED"
        a["completed_at"] = n
        hours, fee = calc.final_billing(a["activated_at"], n)
        a["billable_hours"] = hours
        a["assignment_fee_cents"] = fee
        mark(a)
    for leg in cascade.legs_of_job(job["id"]):
        if leg["leg_status"] == "CLEARED":
            leg["leg_status"] = "COMPLETED"
            mark(leg)
    mark(job)
    return success_object(ser_job(job))


@bp.post("/jobs/<id>/cancel")
def cancel_job(id):
    uid, role = require_roles("CarrierRep", "Dispatcher")
    body_json(request)
    job = _get_job_or_404(id)
    if role == "CarrierRep":
        check_carrier_owner(job)
    if job["job_status"] in NON_TERMINAL_JOB_STATES_FOR_CANCEL:
        raise_err(ERR_JOB_INVALID_STATE, "A DELIVERED, CLOSED, or CANCELLED job cannot be cancelled")
    for inv in cascade.invoices_of_job(job["id"]):
        if inv["invoice_status"] in INVOICE_BLOCKS_CANCEL_STATES:
            raise_err(ERR_JOB_INVALID_STATE,
                      "A job with a FINALIZED, DISPUTED, or PAID invoice cannot be cancelled")
    tier, fee = calc.cancellation_fee(job["job_status"], job["quoted_cents"])
    n = db.now()
    job["job_status"] = "CANCELLED"
    job["cancelled_at"] = n
    job["cancel_fee_tier"] = tier
    job["cancel_fee_cents"] = fee
    for leg in cascade.legs_of_job(job["id"]):
        for a in cascade.assignments_of_leg(leg["id"]):
            if a["assignment_status"] in ("OFFERED", "ACCEPTED", "ACTIVE"):
                cascade.release_assignment(a, "JOB_CANCELLED")
    for leg in cascade.legs_of_job(job["id"]):
        if leg["leg_status"] in ("PENDING", "DETERMINED", "CLEARED", "BLOCKED"):
            leg["leg_status"] = "CANCELLED"
            mark(leg)
    mark(job)
    return success_object(ser_job(job))
