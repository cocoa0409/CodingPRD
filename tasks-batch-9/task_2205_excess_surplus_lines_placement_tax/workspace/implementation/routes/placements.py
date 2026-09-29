"""Placements, the diligent search revision loop, and declinations (PRD 3.3-3.4)."""

from flask import Blueprint

import auth
import serialize
import store
import validation
from calc import diligent, home_state
from envelope import created, ok
from errors import ApiError
from routes.common import arg, filtered, list_response
from store import db, touch

bp = Blueprint("placements", __name__)

COVERAGE_CLASSES = ("PROPERTY", "GENERAL_LIABILITY", "PROFESSIONAL_LIABILITY",
                    "EXCESS_CASUALTY", "INLAND_MARINE")
REASON_CODES = ("NO_APPETITE", "CAPACITY", "UNDERWRITING", "RATE",
                "NOT_LICENSED_FOR_CLASS")


@bp.post("/placements")
def create_placement():
    auth.require("PlacementBroker")
    data = validation.body()
    insured_name = validation.req_str(data, "insured_name")
    ppb_state = validation.req_state_code(data, "principal_place_of_business_state")
    coverage_class = validation.req_enum(data, "coverage_class", COVERAGE_CLASSES)
    is_export = validation.opt_bool(data, "is_export_list_risk", default=False)
    exposures = validation.req_state_exposures(data, "state_exposures")

    # Rung 17: the home state waterfall runs once, here, and never again.
    home, total_iv = home_state.determine(ppb_state, exposures)

    rec = db.insert("placements", {
        "broker_id": auth.user_id(),
        "insured_name": insured_name,
        "principal_place_of_business_state": ppb_state,
        "coverage_class": coverage_class,
        "is_export_list_risk": is_export,
        "state_exposures": exposures,
        "home_state": home,
        "total_insured_value_cents": total_iv,
        "declination_count": 0,
        "status": "DRAFT",
    })
    return created(serialize.public(rec))


@bp.get("/placements/<rec_id>")
def get_placement(rec_id):
    auth.require(auth.ANY)
    rec = auth.path_entity("placements", "placement", rec_id)
    return ok(serialize.public(rec))


@bp.get("/placements")
def list_placements():
    auth.require(auth.ANY)
    rows = filtered(db.all("placements"), broker_id=arg("broker_id"),
                    home_state=arg("home_state"), status=arg("status"))
    return list_response(rows)


def _broker_suspended(broker_id):
    broker = db.get("brokers", broker_id)
    return broker is not None and broker.get("status") == "SUSPENDED"


@bp.post("/placements/<rec_id>/begin-search")
def begin_search(rec_id):
    auth.require("PlacementBroker")
    rec = auth.path_entity("placements", "placement", rec_id)
    auth.check_owner(rec.get("broker_id"))
    if rec.get("status") not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "A search may only be begun from DRAFT or "
                       "CHANGES_REQUESTED.")
    if _broker_suspended(rec.get("broker_id")):
        raise ApiError("ERR_BROKER_SUSPENDED",
                       "A suspended brokerage cannot begin a diligent search.")
    rec["status"] = "SEARCH_IN_PROGRESS"
    touch(rec)
    return ok(serialize.public(rec))


@bp.post("/placements/<rec_id>/complete-search")
def complete_search(rec_id):
    auth.require("PlacementBroker")
    rec = auth.path_entity("placements", "placement", rec_id)
    auth.check_owner(rec.get("broker_id"))
    if rec.get("status") != "SEARCH_IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SEARCH_IN_PROGRESS placement may be completed.")
    program = store.state_program_by_code(rec.get("home_state"))
    if program is None:
        raise ApiError("ERR_STATE_PROGRAM_NOT_FOUND",
                       "No state program is configured for the home state %s."
                       % rec.get("home_state"))

    # Rung 15: sufficiency, evaluated last.
    count, sufficient = diligent.evaluate(rec, program)
    if not sufficient:
        raise ApiError("ERR_DILIGENT_SEARCH_INSUFFICIENT",
                       "The diligent search holds %d valid declinations; %s "
                       "requires %s." % (count, rec.get("home_state"),
                                         program.get("diligent_search_min_declinations")))

    rec["declination_count"] = count
    rec["status"] = "SEARCH_COMPLETE"
    touch(rec)
    return ok(serialize.public(rec))


@bp.post("/placements/<rec_id>/request-changes")
def request_changes(rec_id):
    auth.require("ComplianceOfficer")
    rec = auth.path_entity("placements", "placement", rec_id)
    if store.policies_of_placement(rec["id"]):
        raise ApiError("ERR_PLACEMENT_ALREADY_BOUND",
                       "A placement that already carries a policy cannot be "
                       "sent back for revision.")
    if rec.get("status") != "SEARCH_COMPLETE":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SEARCH_COMPLETE placement may be sent back.")
    rec["declination_count"] = 0
    rec["status"] = "CHANGES_REQUESTED"
    touch(rec)
    return ok(serialize.public(rec))


# --- declinations ---------------------------------------------------------

@bp.post("/placements/<rec_id>/declinations")
def create_declination(rec_id):
    auth.require("PlacementBroker")
    placement = auth.path_entity("placements", "placement", rec_id)
    data = validation.body()
    insurer_name = validation.req_str(data, "admitted_carrier_name")
    state_code = validation.req_state_code(data, "state_code")
    reason_code = validation.req_enum(data, "reason_code", REASON_CODES)
    declined_at, declined_raw = validation.req_datetime(data, "declined_on")
    naic_number = validation.opt_str(data, "naic_number")
    auth.check_owner(placement.get("broker_id"))

    rec = db.insert("declinations", {
        "placement_id": placement["id"],
        "admitted_insurer_name": insurer_name,
        "naic_number": naic_number,
        "state_code": state_code,
        "declined_on": declined_raw,
        "reason_code": reason_code,
        "status": "RECORDED",
        "_declined_at": declined_at,
    })
    return created(serialize.public(rec))


@bp.get("/placements/<rec_id>/declinations")
def list_declinations(rec_id):
    auth.require(auth.ANY)
    placement = auth.path_entity("placements", "placement", rec_id)
    rows = filtered(store.declinations_of(placement["id"]), status=arg("status"),
                    state_code=arg("state_code"))
    return list_response(rows)


@bp.post("/declinations/<rec_id>/invalidate")
def invalidate_declination(rec_id):
    auth.require("ComplianceOfficer")
    rec = auth.path_entity("declinations", "declination", rec_id)
    placement = db.get("placements", rec.get("placement_id"))
    if placement is not None and placement.get("status") == "BOUND":
        raise ApiError("ERR_PLACEMENT_ALREADY_BOUND",
                       "The parent placement is already bound.")
    if rec.get("status") != "RECORDED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a RECORDED declination may be invalidated.")
    rec["status"] = "INVALIDATED"
    touch(rec)
    return ok(serialize.public(rec))
