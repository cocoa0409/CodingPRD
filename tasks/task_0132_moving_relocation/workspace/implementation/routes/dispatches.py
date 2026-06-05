"""Dispatch routes (PRD §3.6, §3.7, §3.9).

Scheduling enforces window/capacity/crew-size/overlap guards in PRD §3.12
priority order. Truck uses half-open overlap (boundary touch allowed); crew
uses a 90-minute turnaround buffer on each side. Depart bubbles the job to
IN_TRANSIT; complete bubbles to DELIVERED and runs final reconciliation.
"""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_roles
from response import object_response, array_response
from serialize import public, public_list
from services import common
from services import calculations

bp = Blueprint("dispatches", __name__)

NON_TERMINAL_DISPATCH = {"SCHEDULED", "EN_ROUTE"}
CREW_TURNAROUND_MINUTES = 90


def _linked_survey_for_job(move_job_id):
    """The (most recent) survey of the job, for the truck-capacity check."""
    surveys = [s for s in db.surveys.values() if s["move_job_id"] == move_job_id]
    if not surveys:
        return None
    surveys.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return surveys[-1]


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: true iff a_start < b_end and b_start < a_end."""
    return a_start < b_end and b_start < a_end


@bp.route("/dispatches", methods=["POST"])
def create_dispatch():
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher"})
    body = common.get_json_body()
    common.require_fields(body, [
        "move_job_id", "truck_id", "crew_id",
        "window_start", "window_end", "required_crew_size",
    ])

    # Existence: body FKs left-to-right (PRD §2.5).
    job = common.lookup_fk(db.move_jobs, body["move_job_id"])
    truck = common.lookup_fk(db.trucks, body["truck_id"])
    crew = common.lookup_fk(db.crews, body["crew_id"])

    # Field validity (priority 9): required_crew_size >= 2.
    common.require_int_field(body, "required_crew_size", minimum=2)

    # Window well-formedness (priority 11).
    window_start = common.parse_datetime(body["window_start"], "ERR_INVALID_FIELD", "window_start")
    window_end = common.parse_datetime(body["window_end"], "ERR_INVALID_FIELD", "window_end")
    if not (window_end > window_start):
        raise err("ERR_INVALID_WINDOW", "window_end must be strictly after window_start.")

    # Truck capacity (priority 12): linked survey total_cubic_feet <= capacity.
    survey = _linked_survey_for_job(body["move_job_id"])
    survey_cf = survey["total_cubic_feet"] if survey else 0
    if survey_cf > truck["capacity_cubic_feet"]:
        raise err("ERR_TRUCK_CAPACITY_EXCEEDED", "Survey volume exceeds truck capacity.")

    # Crew sizing (priority 13): head_count >= required_crew_size.
    if crew["head_count"] < body["required_crew_size"]:
        raise err("ERR_CREW_TOO_SMALL", "Crew is too small for the required size.")

    # Truck overlap (priority 14): half-open, boundary touch allowed.
    for d in db.dispatches.values():
        if d["truck_id"] == body["truck_id"] and d["status"] in NON_TERMINAL_DISPATCH:
            if _intervals_overlap(window_start, window_end, d["_window_start"], d["_window_end"]):
                raise err("ERR_TRUCK_DOUBLE_BOOKED", "Truck is already booked for this window.")

    # Crew overlap with 90-min turnaround buffer on each side (priority 15).
    buffer = timedelta(minutes=CREW_TURNAROUND_MINUTES)
    buffered_start = window_start - buffer
    buffered_end = window_end + buffer
    for d in db.dispatches.values():
        if d["crew_id"] == body["crew_id"] and d["status"] in NON_TERMINAL_DISPATCH:
            if _intervals_overlap(buffered_start, buffered_end, d["_window_start"], d["_window_end"]):
                raise err("ERR_CREW_DOUBLE_BOOKED", "Crew is unavailable within the turnaround buffer.")

    record = db.new_common({
        "move_job_id": body["move_job_id"],
        "truck_id": body["truck_id"],
        "crew_id": body["crew_id"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "required_crew_size": body["required_crew_size"],
        "status": "SCHEDULED",
        # internal parsed windows for overlap math (stripped on serialize):
        "_window_start": window_start,
        "_window_end": window_end,
    })
    db.dispatches[record["id"]] = record
    return object_response(public(record), 201)


@bp.route("/dispatches/<did>", methods=["GET"])
def get_dispatch(did):
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher", "PlatformAdmin", "Customer"})
    record = common.lookup(db.dispatches, did)
    return object_response(public(record), 200)


@bp.route("/dispatches", methods=["GET"])
def list_dispatches():
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher", "PlatformAdmin", "Customer"})
    limit, offset = common.parse_pagination()
    move_job_id = request.args.get("move_job_id")
    truck_id = request.args.get("truck_id")
    crew_id = request.args.get("crew_id")
    status = request.args.get("status")
    records = list(db.dispatches.values())
    if move_job_id is not None:
        records = [r for r in records if r["move_job_id"] == move_job_id]
    if truck_id is not None:
        records = [r for r in records if r["truck_id"] == truck_id]
    if crew_id is not None:
        records = [r for r in records if r["crew_id"] == crew_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = common.paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total, 200)


@bp.route("/dispatches/<did>/depart", methods=["POST"])
def depart_dispatch(did):
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher"})
    dispatch = common.lookup(db.dispatches, did)
    job = common.lookup(db.move_jobs, dispatch["move_job_id"])

    # State (priority 6): depart only from SCHEDULED; job BOOKED.
    if dispatch["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Dispatch must be SCHEDULED to depart.")
    if job["job_status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Job must be BOOKED to depart.")
    # Dependent-state block (priority 7): money dimension >= deposit.
    if job["payment_status"] not in {"DEPOSIT_PAID", "PAID_IN_FULL"}:
        raise err("ERR_DEPENDENT_STATE_BLOCK", "Departure requires at least a deposit.")

    dispatch["status"] = "EN_ROUTE"
    db.touch(dispatch)
    job["job_status"] = "IN_TRANSIT"  # cross-entity bubble-up
    db.touch_updated_only(job)
    return object_response(public(dispatch), 200)


@bp.route("/dispatches/<did>/complete", methods=["POST"])
def complete_dispatch(did):
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher"})
    dispatch = common.lookup(db.dispatches, did)
    job = common.lookup(db.move_jobs, dispatch["move_job_id"])

    # State (priority 6): complete only from EN_ROUTE.
    if dispatch["status"] != "EN_ROUTE":
        raise err("ERR_INVALID_STATE", "Dispatch must be EN_ROUTE to complete.")

    body = common.get_json_body()
    common.require_fields(body, ["actual_weight_lbs"])
    common.require_int_field(body, "actual_weight_lbs", minimum=0)
    actual_weight = body["actual_weight_lbs"]
    actual_cubic_feet = body.get("actual_cubic_feet")
    if actual_cubic_feet is not None:
        common.require_number_field(body, "actual_cubic_feet", minimum=0)
    addendum_present = bool(body.get("addendum_present", False))

    dispatch["status"] = "COMPLETED"
    db.touch(dispatch)
    job["job_status"] = "DELIVERED"

    # Final-charge reconciliation against the accepted estimate.
    estimate = db.estimates.get(job["accepted_estimate_id"]) if job["accepted_estimate_id"] else None
    if estimate is not None:
        survey = db.surveys.get(estimate["survey_id"])
        final = calculations.final_charge_reconciliation(
            job, survey, estimate, actual_weight, actual_cubic_feet, addendum_present
        )
        job["final_charge_cents"] = final
        # gross = reconciled final + storage/packing already gross-booked
        # (beyond the original accepted-estimate amount). PRD §3.7.
        prior_estimate_in_gross = estimate["estimate_total_cents"]
        extras_in_gross = job["gross_charges_cents"] - prior_estimate_in_gross
        job["gross_charges_cents"] = final + extras_in_gross
        common.recompute_balance(job)
    db.touch_updated_only(job)

    return object_response(public(dispatch), 200)


@bp.route("/dispatches/<did>/cancel", methods=["POST"])
def cancel_dispatch(did):
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher"})
    dispatch = common.lookup(db.dispatches, did)

    # State (priority 6): cancel only from SCHEDULED.
    if dispatch["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Only a SCHEDULED dispatch may be cancelled.")

    dispatch["status"] = "CANCELLED"  # frees truck+crew windows (terminal status)
    db.touch(dispatch)
    return object_response(public(dispatch), 200)
