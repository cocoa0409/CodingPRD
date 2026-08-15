"""ReprocessingCycle endpoints: the strictly-ordered step machine (PRD 3.6)."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_REPROCESSING_CYCLE_NOT_FOUND,
    ERR_SCOPE_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND,
    ERR_SCOPE_NOT_REPROCESSABLE,
    ERR_CYCLE_STEP_OUT_OF_ORDER,
    ERR_CYCLE_NOT_ADVANCABLE,
    ERR_STEP_DURATION_TOO_SHORT,
    ERR_HLD_CONCENTRATION_TOO_LOW,
    ERR_INVALID_REQUEST,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, open_quarantine_case_for_scope, public, touch
from util import now
from validate import get_body, req_enum, req_number, req_str, require_path_resource, resolve_ref

bp = Blueprint("reprocessing_cycles", __name__)

# reprocessing_step_windows constants
PRECLEAN_DEADLINE_MIN = 60
MANUAL_CLEAN_MIN = 5
EXTENDED_MANUAL_CLEAN_MIN = 20
HLD_MIN_CONTACT_SECONDS = 600
HLD_MIN_CONCENTRATION_PPM = 300
DRY_MIN_MINUTES = 10
HANG_TIME_HOURS = 72

STEP_ORDER = ["INITIATED", "PRECLEANED", "CLEANED", "DISINFECTED", "DRIED", "COMPLETE"]
# to_step schema-legal values: the full status vocabulary; a value that is not
# exactly the next step is rejected with ERR_CYCLE_STEP_OUT_OF_ORDER.
CYCLE_STEPS = set(STEP_ORDER) | {"FAILED"}


@bp.post("/endoscopy/reprocessing-cycles")
def create_cycle():
    caller = authorized(["ReprocessingTechnician"])
    body = get_body()
    # Rung 3 (existence): scope_id, then optional booking_id
    scope = resolve_ref("scopes", body.get("scope_id"), ERR_SCOPE_NOT_FOUND)
    booking = resolve_ref("bookings", body.get("booking_id"), ERR_BOOKING_NOT_FOUND)
    # Rung 4 (schema)
    req_str(body, "scope_id")
    if "booking_id" in body and body.get("booking_id") is not None \
            and not isinstance(body.get("booking_id"), str):
        raise_error(ERR_INVALID_REQUEST, "booking_id must be a string")
    # Rung 7 (state): the scope must be AWAITING_REPROCESS or QUARANTINED.
    if scope["status"] not in ("AWAITING_REPROCESS", "QUARANTINED"):
        raise_error(ERR_SCOPE_NOT_REPROCESSABLE,
                    "cycle creation requires scope status AWAITING_REPROCESS or QUARANTINED")
    current = now()
    since = scope.get("awaiting_reprocess_since")
    # Strictly more than 60 minutes elapsed -> extended soak (60:00 exactly is not).
    requires_extended_soak = bool(
        since is not None and (current - since) > timedelta(minutes=PRECLEAN_DEADLINE_MIN)
    )
    is_reculture = scope["status"] == "QUARANTINED"
    rec = new_record("reprocessing_cycles", {
        "scope_id": scope["id"],
        "booking_id": booking["id"] if booking is not None else None,
        "technician_id": caller.user_id,
        "status": "INITIATED",
        "is_reculture": is_reculture,
        "requires_extended_soak": requires_extended_soak,
        "hld_solution_lot": None,
        "hld_concentration_ppm": None,
        "initiated_at": current,
        "precleaned_at": None,
        "cleaned_at": None,
        "disinfected_at": None,
        "dried_at": None,
        "completed_at": None,
    })
    scope["status"] = "REPROCESSING"
    touch(scope)
    if is_reculture:
        case = open_quarantine_case_for_scope(scope["id"])
        if case is not None and case["status"] == "OPEN":
            case["status"] = "RECULTURING"
            case["reculture_cycle_id"] = rec["id"]
            touch(case)
    return success_object(public(rec), status=201)


@bp.get("/endoscopy/reprocessing-cycles")
def list_cycles():
    return list_response("reprocessing_cycles", {
        "scope_id": request.args.get("scope_id"),
        "booking_id": request.args.get("booking_id"),
        "status": request.args.get("status"),
    })


@bp.get("/endoscopy/reprocessing-cycles/<rid>")
def get_cycle(rid):
    return get_one("reprocessing_cycles", rid, ERR_REPROCESSING_CYCLE_NOT_FOUND)


@bp.post("/endoscopy/reprocessing-cycles/<rid>/steps/advance")
def advance_cycle(rid):
    authorized(["ReprocessingTechnician"])
    cycle = require_path_resource("reprocessing_cycles", rid, ERR_REPROCESSING_CYCLE_NOT_FOUND)
    body = get_body()
    # Rung 4 (schema)
    to_step = req_enum(body, "to_step", CYCLE_STEPS)
    hld_solution_lot = None
    hld_concentration_ppm = None
    if to_step == "DISINFECTED":
        # The DISINFECTED step is the documentation gate: lot and concentration
        # must be carried on the request.
        hld_solution_lot = req_str(body, "hld_solution_lot")
        hld_concentration_ppm = req_number(body, "hld_concentration_ppm")
    # Rung 7 (state): terminal cycles are not advancable; otherwise the target
    # must be exactly the next step.
    if cycle["status"] in ("COMPLETE", "FAILED"):
        raise_error(ERR_CYCLE_NOT_ADVANCABLE, "cycle is terminal")
    expected_next = STEP_ORDER[STEP_ORDER.index(cycle["status"]) + 1]
    if to_step != expected_next:
        raise_error(ERR_CYCLE_STEP_OUT_OF_ORDER,
                    f"to_step must be exactly the next step ({expected_next})")
    current = now()
    scope = db["scopes"].get(cycle["scope_id"])

    # Rung 8 (compliance): step minimum dwell times, inclusive thresholds.
    if to_step == "CLEANED":
        minimum = EXTENDED_MANUAL_CLEAN_MIN if cycle["requires_extended_soak"] else MANUAL_CLEAN_MIN
        if current - cycle["precleaned_at"] < timedelta(minutes=minimum):
            raise_error(ERR_STEP_DURATION_TOO_SHORT,
                        f"manual clean requires >= {minimum} minutes since precleaned_at")
    elif to_step == "DISINFECTED":
        if (current - cycle["cleaned_at"]).total_seconds() < HLD_MIN_CONTACT_SECONDS:
            raise_error(ERR_STEP_DURATION_TOO_SHORT,
                        "HLD contact requires >= 600 seconds since cleaned_at")
        # The concentration gate has teeth: a sub-300 ppm submission fails the
        # cycle and returns the scope to AWAITING_REPROCESS.
        if hld_concentration_ppm < HLD_MIN_CONCENTRATION_PPM:
            cycle["status"] = "FAILED"
            touch(cycle)
            if scope is not None:
                scope["status"] = "AWAITING_REPROCESS"
                scope["awaiting_reprocess_since"] = current
                touch(scope)
            raise_error(ERR_HLD_CONCENTRATION_TOO_LOW,
                        "hld_concentration_ppm below the 300 ppm floor")
    elif to_step == "DRIED":
        if current - cycle["disinfected_at"] < timedelta(minutes=DRY_MIN_MINUTES):
            raise_error(ERR_STEP_DURATION_TOO_SHORT,
                        "drying requires >= 10 minutes since disinfected_at")

    # Effects per step
    if to_step == "PRECLEANED":
        cycle["precleaned_at"] = current
    elif to_step == "CLEANED":
        cycle["cleaned_at"] = current
    elif to_step == "DISINFECTED":
        cycle["hld_solution_lot"] = hld_solution_lot
        cycle["hld_concentration_ppm"] = hld_concentration_ppm
        cycle["disinfected_at"] = current
    elif to_step == "DRIED":
        cycle["dried_at"] = current
    elif to_step == "COMPLETE":
        cycle["completed_at"] = current
        if scope is not None:
            # scope_storage_expiry: storage limit born at completion.
            scope["storage_expires_at"] = cycle["dried_at"] + timedelta(hours=HANG_TIME_HOURS)
            # The scope leaves the reprocessing pipeline clean: no preclean
            # deadline is pending until it next becomes AWAITING_REPROCESS.
            scope["awaiting_reprocess_since"] = None
            # A reculture cycle completing while the case is still open returns
            # the scope to QUARANTINED (documentation preserved); any other
            # completed cycle frees the scope to AVAILABLE.
            if open_quarantine_case_for_scope(scope["id"]) is not None:
                scope["status"] = "QUARANTINED"
            else:
                scope["status"] = "AVAILABLE"
            touch(scope)
    cycle["status"] = to_step
    touch(cycle)
    return success_object(public(cycle))
