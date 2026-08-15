"""HousingUnit and HousingSetup endpoints."""

from flask import Blueprint

from db import store, new_id, stamp_new, touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_HOUSING_CAPACITY_INSUFFICIENT,
    ERR_UNIT_OCCUPANCY_CONFLICT,
    ERR_SETUP_ALREADY_EXISTS,
    ERR_FURNISHING_INCOMPLETE,
    ERR_ITEM_ALREADY_FURNISHED,
)
from helpers import body_dict, req_string, req_int, req_date
from middleware import authenticate, authorize, HOUSING_COORDINATOR
from response import success_object, success_list
from serializers import ser_unit, ser_setup
from services import (
    REQUIRED_FURNISHINGS,
    NON_TERMINAL_SETUP_STATUSES,
    setups_of_case,
    setups_of_unit,
    sorted_records,
)
from routes.cases import get_case_or_404

bp = Blueprint("housing", __name__)


def get_unit_or_404(unit_id):
    unit = store.housing_units.get(unit_id)
    if unit is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Housing unit not found.")
    return unit


def get_setup_or_404(setup_id):
    setup = store.housing_setups.get(setup_id)
    if setup is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Housing setup not found.")
    return setup


@bp.post("/housing-units")
def create_unit():
    _uid, role = authenticate()
    authorize(role, {HOUSING_COORDINATOR})
    d = body_dict()
    address = req_string(d, "address")
    bedrooms = req_int(d, "bedrooms", minimum=0)
    unit = {"id": new_id(), "address": address, "bedrooms": bedrooms}
    stamp_new(unit)
    store.housing_units[unit["id"]] = unit
    return success_object(ser_unit(unit), 201)


@bp.get("/housing-units/<unit_id>")
def get_unit(unit_id):
    authenticate()
    return success_object(ser_unit(get_unit_or_404(unit_id)))


@bp.post("/housing-setups")
def create_setup():
    _uid, role = authenticate()
    authorize(role, {HOUSING_COORDINATOR})
    d = body_dict()
    # Priority 3: body FK existence, left-to-right (case_id, then housing_unit_id)
    case_id = req_string(d, "case_id")
    case = store.cases.get(case_id)
    if case is None:
        raise ApiError(ERR_NOT_FOUND, 404, "case_id does not identify an existing case.")
    unit_id = req_string(d, "housing_unit_id")
    unit = store.housing_units.get(unit_id)
    if unit is None:
        raise ApiError(ERR_NOT_FOUND, 404, "housing_unit_id does not identify an existing unit.")
    # Priority 4: schema — half-open window must be correctly ordered
    occ_start = req_date(d, "occupancy_start")
    occ_end = req_date(d, "occupancy_end")
    if not occ_end > occ_start:
        raise ApiError(ERR_VALIDATION, 400, "occupancy_end must be strictly after occupancy_start.")
    # Priority 6: state — the case must still be PRE_ARRIVAL
    if case["status"] != "PRE_ARRIVAL":
        raise ApiError(ERR_INVALID_STATE, 409, "Case must be PRE_ARRIVAL to create a housing setup.")
    # Priority 7: capacity — bedrooms >= ceil(household_size / 2). A
    # single-person household may take a studio (0 bedrooms); every larger
    # household rounds half up (4 -> 2, 5 -> 3).
    required_bedrooms = 0 if case["household_size"] == 1 else (case["household_size"] + 1) // 2
    if unit["bedrooms"] < required_bedrooms:
        raise ApiError(
            ERR_HOUSING_CAPACITY_INSUFFICIENT,
            422,
            "Unit bedrooms below ceil(household_size / 2).",
        )
    # Priority 8: temporal — half-open occupancy windows must not overlap
    # another non-terminal setup on the same unit (adjacency allowed).
    for other in setups_of_unit(unit["id"]):
        if other["status"] in NON_TERMINAL_SETUP_STATUSES:
            if occ_start < other["occupancy_end"] and other["occupancy_start"] < occ_end:
                raise ApiError(
                    ERR_UNIT_OCCUPANCY_CONFLICT,
                    409,
                    "Occupancy window overlaps another non-terminal setup on the unit.",
                )
    # Priority 9: at most one non-terminal setup per case
    if any(s["status"] in NON_TERMINAL_SETUP_STATUSES for s in setups_of_case(case["id"])):
        raise ApiError(
            ERR_SETUP_ALREADY_EXISTS, 409, "Case already has a non-terminal housing setup."
        )
    setup = {
        "id": new_id(),
        "case_id": case["id"],
        "housing_unit_id": unit["id"],
        "occupancy_start": occ_start,
        "occupancy_end": occ_end,
        "furnishing_items_completed": [],
        "status": "PREPARING",
    }
    stamp_new(setup)
    store.housing_setups[setup["id"]] = setup
    return success_object(ser_setup(setup), 201)


@bp.get("/cases/<case_id>/housing-setups")
def list_setups_of_case(case_id):
    authenticate()
    case = get_case_or_404(case_id)
    return success_list(sorted_records(setups_of_case(case["id"])), ser_setup)


@bp.get("/housing-units/<unit_id>/housing-setups")
def list_setups_of_unit(unit_id):
    authenticate()
    unit = get_unit_or_404(unit_id)
    return success_list(sorted_records(setups_of_unit(unit["id"])), ser_setup)


@bp.post("/housing-setups/<setup_id>/furnish")
def furnish_setup(setup_id):
    _uid, role = authenticate()
    authorize(role, {HOUSING_COORDINATOR})
    setup = get_setup_or_404(setup_id)
    d = body_dict()
    # Priority 4: schema — item must be one of the required furnishings
    item = req_string(d, "item")
    if item not in REQUIRED_FURNISHINGS:
        raise ApiError(ERR_VALIDATION, 400, "item is not a required furnishing.")
    # Priority 6: state — furnish is only valid from PREPARING
    if setup["status"] != "PREPARING":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PREPARING setup can be furnished.")
    # Priority 9: each item can be completed only once
    if item in setup["furnishing_items_completed"]:
        raise ApiError(ERR_ITEM_ALREADY_FURNISHED, 409, "Item already furnished.")
    setup["furnishing_items_completed"].append(item)
    touch(setup)
    return success_object(ser_setup(setup), 200)


@bp.post("/housing-setups/<setup_id>/ready")
def ready_setup(setup_id):
    _uid, role = authenticate()
    authorize(role, {HOUSING_COORDINATOR})
    setup = get_setup_or_404(setup_id)
    if setup["status"] != "PREPARING":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PREPARING setup can become READY.")
    if set(REQUIRED_FURNISHINGS) - set(setup["furnishing_items_completed"]):
        raise ApiError(
            ERR_FURNISHING_INCOMPLETE, 409, "All six required furnishings must be completed."
        )
    setup["status"] = "READY"
    touch(setup)
    return success_object(ser_setup(setup), 200)


@bp.post("/housing-setups/<setup_id>/vacate")
def vacate_setup(setup_id):
    _uid, role = authenticate()
    authorize(role, {HOUSING_COORDINATOR})
    setup = get_setup_or_404(setup_id)
    if setup["status"] not in NON_TERMINAL_SETUP_STATUSES:
        raise ApiError(ERR_INVALID_STATE, 409, "Only a non-terminal setup can be vacated.")
    setup["status"] = "VACATED"
    touch(setup)
    return success_object(ser_setup(setup), 200)
