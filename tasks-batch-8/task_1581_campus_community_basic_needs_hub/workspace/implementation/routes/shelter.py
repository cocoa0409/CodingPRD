"""Shelter beds and stays (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_CLIENT_NOT_ACTIVE, ERR_ASSESSMENT_REQUIRED,
    ERR_STAY_WINDOW_INVALID, ERR_BED_OUT_OF_SERVICE, ERR_BED_OCCUPIED,
    ERR_BED_NOT_AVAILABLE, ERR_CLIENT_STAY_OVERLAP, ERR_SHELTER_RESTRICTED,
    ERR_NOT_HOUSING_INSECURE, ERR_STAY_NOT_ACTIONABLE, ERR_DUPLICATE_BED_LABEL,
)
from middleware import authenticate, authorize, check_client_scope
from response import success_object
from routes.helpers import list_response
from services import calculations as calc
from services.core import new_record, touch, public, verified_assessment
from util import CLOCK, parse_date
from validate import (
    get_body, req_int, req_str, req_enum, req_date, opt_enum_list,
    require_path_resource, require_body_ref,
)

bp = Blueprint("shelter", __name__)

BED_FEATURES = ["ADA_ACCESSIBLE", "FAMILY_UNIT", "PET_FRIENDLY"]
BED_READ_ROLES = ["IntakeCoordinator", "ShelterCoordinator", "HubAdmin"]
STAY_READ_ROLES = ["Client", "ShelterCoordinator", "HubAdmin"]


# ---------------------------------------------------------------------------
# Beds
# ---------------------------------------------------------------------------

@bp.post("/shelter-beds")
def create_bed():
    caller = authenticate()
    authorize(caller, ["ShelterCoordinator", "HubAdmin"])
    body = get_body()
    shelter_site = req_str(body, "shelter_site")
    bed_label = req_str(body, "bed_label")
    features = opt_enum_list(body, "features", BED_FEATURES, default=[])
    for b in db["shelter_beds"].values():
        if b["shelter_site"] == shelter_site and b["bed_label"] == bed_label:
            raise_error(ERR_DUPLICATE_BED_LABEL, "bed_label already used within this shelter_site")
    rec = new_record("shelter_beds", {
        "shelter_site": shelter_site,
        "bed_label": bed_label,
        "features": features,
        "status": "AVAILABLE",
    })
    return success_object(public(rec), status=201)


@bp.get("/shelter-beds")
def list_beds():
    caller = authenticate()
    authorize(caller, BED_READ_ROLES)
    filters = {
        "shelter_site": request.args.get("shelter_site"),
        "status": request.args.get("status"),
    }
    return list_response("shelter_beds", filters)


@bp.patch("/shelter-beds/<bid>")
def patch_bed(bid):
    caller = authenticate()
    authorize(caller, ["ShelterCoordinator", "HubAdmin"])
    bed = require_path_resource("shelter_beds", bid, "shelter bed")
    body = get_body()
    new_status = req_enum(body, "status", ["AVAILABLE", "OUT_OF_SERVICE"])
    if new_status == "OUT_OF_SERVICE":
        # Blocked while a stay is OCCUPIED on the bed
        for s in db["shelter_stays"].values():
            if s["bed_id"] == bed["id"] and s["status"] == "OCCUPIED":
                raise_error(ERR_BED_OCCUPIED, "a stay is OCCUPIED on this bed")
    bed["status"] = new_status
    touch(bed)
    return success_object(public(bed))


# ---------------------------------------------------------------------------
# Stays
# ---------------------------------------------------------------------------

@bp.post("/clients/<cid>/shelter-stays")
def create_stay(cid):
    caller = authenticate()
    authorize(caller, ["ShelterCoordinator"])
    client = require_path_resource("clients", cid, "client")
    body = get_body()
    bed_id = req_str(body, "bed_id")
    check_in_date = req_date(body, "check_in_date")
    planned_nights = req_int(body, "planned_nights")
    if client["status"] != "ACTIVE":
        raise_error(ERR_CLIENT_NOT_ACTIVE, "stay creation requires an ACTIVE client")
    va = verified_assessment(client["id"])
    if va is None:
        raise_error(ERR_ASSESSMENT_REQUIRED, "client must hold a VERIFIED assessment")
    # Stay window sanity: booking horizon and nights bound (PRD 3.6)
    today = CLOCK.today()
    ci = parse_date(check_in_date)
    if ci < today or ci > today + timedelta(days=calc.BOOKING_HORIZON_DAYS):
        raise_error(ERR_STAY_WINDOW_INVALID, "check_in_date outside [today, today + 13 days]")
    if planned_nights < 1 or planned_nights > calc.MAX_STAY_NIGHTS:
        raise_error(ERR_STAY_WINDOW_INVALID, "planned_nights must be within 1..14")
    # Placement: bed status, bed interval, client night-set, restriction, eligibility
    bed = require_body_ref("shelter_beds", bed_id, "bed_id")
    if bed["status"] != "AVAILABLE":
        raise_error(ERR_BED_OUT_OF_SERVICE, "bed is OUT_OF_SERVICE")
    pet = "PET_FRIENDLY" in (bed["features"] or [])
    check_out_exclusive, buffer_until_exclusive = calc.stay_window_dates(
        check_in_date, planned_nights, pet)
    if calc.bed_conflict(bed["id"], check_in_date, buffer_until_exclusive):
        raise_error(ERR_BED_NOT_AVAILABLE, "bed interval collides with an existing stay")
    if calc.client_stay_overlap(client["id"], check_in_date, check_out_exclusive):
        raise_error(ERR_CLIENT_STAY_OVERLAP, "client night-set intersects an existing stay")
    if calc.no_show_count_90d(client["id"]) >= 2:
        raise_error(ERR_SHELTER_RESTRICTED, "client is shelter-restricted (2+ no-shows in 90 days)")
    if va["housing_status"] not in ("UNSTABLE", "HOMELESS"):
        raise_error(ERR_NOT_HOUSING_INSECURE, "verified assessment is not UNSTABLE or HOMELESS")
    rec = new_record("shelter_stays", {
        "client_id": client["id"],
        "bed_id": bed["id"],
        "check_in_date": check_in_date,
        "planned_nights": planned_nights,
        "check_out_exclusive": check_out_exclusive,
        "buffer_until_exclusive": buffer_until_exclusive,
        "actual_check_out_date": None,
        "no_show_marked_at": None,
        "status": "RESERVED",
    })
    return success_object(public(rec), status=201)


@bp.get("/shelter-stays")
def list_stays():
    caller = authenticate()
    authorize(caller, STAY_READ_ROLES)
    filters = {
        "client_id": request.args.get("client_id"),
        "bed_id": request.args.get("bed_id"),
        "status": request.args.get("status"),
    }
    scope = None
    if caller.role == "Client":
        scope = lambda rec: rec["client_id"] == caller.user_id
    return list_response("shelter_stays", filters, scope_fn=scope)


@bp.get("/shelter-stays/<sid>")
def get_stay(sid):
    caller = authenticate()
    authorize(caller, STAY_READ_ROLES)
    stay = require_path_resource("shelter_stays", sid, "shelter stay")
    check_client_scope(caller, stay["client_id"])
    return success_object(public(stay))


@bp.post("/shelter-stays/<sid>/check-in")
def check_in_stay(sid):
    caller = authenticate()
    authorize(caller, ["ShelterCoordinator"])
    stay = require_path_resource("shelter_stays", sid, "shelter stay")
    if stay["status"] != "RESERVED":
        raise_error(ERR_STAY_NOT_ACTIONABLE, "only a RESERVED stay can be checked in")
    today = CLOCK.today()
    ci = parse_date(stay["check_in_date"])
    if today < ci or today > ci + timedelta(days=calc.NO_SHOW_GRACE_DAYS):
        raise_error(ERR_STAY_WINDOW_INVALID,
                    "check-in is admitted only on [check_in_date, check_in_date + 1 day]")
    client = db["clients"].get(stay["client_id"])
    if client is None or client["status"] != "ACTIVE":
        raise_error(ERR_CLIENT_NOT_ACTIVE, "client must be ACTIVE at check-in")
    stay["status"] = "OCCUPIED"
    touch(stay)
    return success_object(public(stay))


@bp.post("/shelter-stays/<sid>/check-out")
def check_out_stay(sid):
    caller = authenticate()
    authorize(caller, ["ShelterCoordinator"])
    stay = require_path_resource("shelter_stays", sid, "shelter stay")
    if stay["status"] != "OCCUPIED":
        raise_error(ERR_STAY_NOT_ACTIONABLE, "only an OCCUPIED stay can be checked out")
    stay["actual_check_out_date"] = CLOCK.today().isoformat()
    stay["status"] = "CHECKED_OUT"
    touch(stay)
    client = db["clients"].get(stay["client_id"])
    if client is not None:
        touch(client)  # risk_tier recomputed (PRD 2.5)
    return success_object(public(stay))


@bp.post("/shelter-stays/<sid>/cancel")
def cancel_stay(sid):
    caller = authenticate()
    authorize(caller, ["ShelterCoordinator", "HubAdmin"])
    stay = require_path_resource("shelter_stays", sid, "shelter stay")
    if stay["status"] != "RESERVED":
        raise_error(ERR_STAY_NOT_ACTIONABLE, "only a RESERVED stay can be cancelled")
    stay["status"] = "CANCELLED"
    touch(stay)
    return success_object(public(stay))
