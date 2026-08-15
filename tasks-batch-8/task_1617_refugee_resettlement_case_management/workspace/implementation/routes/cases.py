"""Case endpoints: register arrival notification, read, arrive."""

from flask import Blueprint

from db import store, new_id, stamp_new
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_HOUSING_NOT_READY,
    ERR_DUPLICATE_CASE_NUMBER,
)
from helpers import body_dict, req_string, req_int, req_date
from middleware import authenticate, authorize, CASE_MANAGER
from response import success_object
from serializers import ser_case
from services import arrive_cascade

bp = Blueprint("cases", __name__)


def get_case_or_404(case_id):
    case = store.cases.get(case_id)
    if case is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Case not found.")
    return case


@bp.post("/cases")
def create_case():
    _uid, role = authenticate()
    authorize(role, {CASE_MANAGER})
    d = body_dict()
    # Priority 4: schema / field validity
    case_number = req_string(d, "case_number")
    affiliate = req_string(d, "agency_affiliate_code")
    household_size = req_int(d, "household_size", minimum=1)
    scheduled = req_date(d, "scheduled_arrival_date")
    # Priority 9: case_number uniqueness (client-supplied system fields ignored)
    if any(c["case_number"] == case_number for c in store.cases.values()):
        raise ApiError(ERR_DUPLICATE_CASE_NUMBER, 409, "case_number already registered.")
    case = {
        "id": new_id(),
        "case_number": case_number,
        "agency_affiliate_code": affiliate,
        "household_size": household_size,
        "scheduled_arrival_date": scheduled,
        "actual_arrival_date": None,
        "airport_pickup_completed": False,
        "status": "PRE_ARRIVAL",
        "open_transfer_id": None,
    }
    stamp_new(case)
    store.cases[case["id"]] = case
    return success_object(ser_case(case), 201)


@bp.get("/cases/<case_id>")
def get_case(case_id):
    authenticate()  # all five roles may read
    case = get_case_or_404(case_id)
    return success_object(ser_case(case))


@bp.post("/cases/<case_id>/arrive")
def arrive_case(case_id):
    _uid, role = authenticate()
    authorize(role, {CASE_MANAGER})
    case = get_case_or_404(case_id)
    d = body_dict()
    # Priority 4: schema
    arrival = req_date(d, "actual_arrival_date")
    # Priority 6: state-machine legality (arrive twice / after transfer-out)
    if case["status"] != "PRE_ARRIVAL":
        raise ApiError(ERR_INVALID_STATE, 409, "Case is not PRE_ARRIVAL.")
    # Priority 9: a READY housing setup must exist for the case
    ready = [
        s
        for s in store.housing_setups.values()
        if s["case_id"] == case["id"] and s["status"] == "READY"
    ]
    if not ready:
        raise ApiError(
            ERR_HOUSING_NOT_READY,
            409,
            "Arrival requires a HousingSetup in READY status for the case.",
        )
    arrive_cascade(case, arrival)
    return success_object(ser_case(case), 200)
