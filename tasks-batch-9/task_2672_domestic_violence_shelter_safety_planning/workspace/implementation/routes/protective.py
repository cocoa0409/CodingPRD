"""ProtectiveOrderCase endpoints: drafting, filing and outcome recording."""

from datetime import timedelta

from flask import Blueprint

from db import clock_iso, clock_now, db, public, touch
from errors import ApiError
from middleware import (ROLE_AGENCY_ADMIN, ROLE_HOTLINE_ADVOCATE, ROLE_LEGAL_ADVOCATE, auth)
from response import created, ok
from routes.common import (by_created, filtered, get_case, get_client, get_staff, insert,
                           list_page)
from services import derive
from validation import (dt_out, get_body, q_enum, q_str, req_datetime, req_enum, req_str)

bp = Blueprint("protective", __name__)

ORDER_TYPES = ("EMERGENCY_EX_PARTE", "FULL_ORDER", "MODIFICATION")
CASE_STATUSES = ("PETITION_DRAFTED", "FILED", "GRANTED", "DENIED_FINAL")
OUTCOMES = ("GRANTED", "DENIED")
TRAVEL_BUFFER_MINUTES = 60
MAX_REFILES = 2
READ_ROLES = (ROLE_LEGAL_ADVOCATE, ROLE_HOTLINE_ADVOCATE, ROLE_AGENCY_ADMIN)


@bp.post("/protective-order-cases")
def create_case():
    auth((ROLE_LEGAL_ADVOCATE,))
    body = get_body()
    client_id = req_str(body, "client_id")
    order_type = req_enum(body, "order_type", ORDER_TYPES)
    client = get_client(client_id)

    case = insert("protective_order_cases", {
        "client_id": client["id"],
        "accompanying_advocate_id": None,
        "order_type": order_type,
        "status": "PETITION_DRAFTED",
        "filed_court": None,
        "hearing_start_utc": None,
        "hearing_end_utc": None,
        "refile_count": 0,
        "outcome_recorded_at": None,
    })
    return created(public(case))


@bp.get("/protective-order-cases/<case_id>")
def read_case(case_id):
    auth(READ_ROLES)
    return ok(public(get_case(case_id)))


@bp.get("/protective-order-cases")
def list_cases():
    auth(READ_ROLES)
    filters = {
        "client_id": q_str("client_id"),
        "accompanying_advocate_id": q_str("accompanying_advocate_id"),
        "status": q_enum("status", CASE_STATUSES),
    }
    return list_page(by_created(filtered("protective_order_cases", filters)))


@bp.post("/protective-order-cases/<case_id>/file")
def file_case(case_id):
    auth((ROLE_LEGAL_ADVOCATE,))
    body = get_body()
    filed_court = req_str(body, "filed_court", 1, 200)
    hearing_start = req_datetime(body, "hearing_start_utc")
    hearing_end = req_datetime(body, "hearing_end_utc")
    advocate_id = req_str(body, "accompanying_advocate_id")
    case = get_case(case_id)
    advocate = get_staff(advocate_id)

    if case["status"] != "PETITION_DRAFTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a PETITION_DRAFTED case may be filed")

    if advocate["wellness_posture"] == "FROZEN":
        raise ApiError("ERR_ADVOCATE_FROZEN")

    if not hearing_end > hearing_start:
        raise ApiError("ERR_INVALID_DATE_WINDOW",
                       "hearing_end_utc must be strictly after hearing_start_utc")
    if not hearing_start > clock_now():
        raise ApiError("ERR_INVALID_DATE_WINDOW",
                       "hearing_start_utc must be strictly after the logical clock")

    buffer = timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    new_start = hearing_start - buffer
    new_end = hearing_end + buffer
    for other in derive.where("protective_order_cases", status="FILED",
                              accompanying_advocate_id=advocate["id"]):
        if other["id"] == case["id"]:
            continue
        other_start = derive.as_datetime(other["hearing_start_utc"]) - buffer
        other_end = derive.as_datetime(other["hearing_end_utc"]) + buffer
        if new_start <= other_end and other_start <= new_end:
            raise ApiError("ERR_ADVOCATE_DOUBLE_BOOKED")

    case["status"] = "FILED"
    case["filed_court"] = filed_court
    case["hearing_start_utc"] = dt_out(hearing_start)
    case["hearing_end_utc"] = dt_out(hearing_end)
    case["accompanying_advocate_id"] = advocate["id"]
    touch(case)

    client = db.clients.get(case["client_id"])
    if client is not None:
        client["protective_order_active"] = True
        touch(client)
        derive.recompute_client_posture(client)
    return ok(public(case))


@bp.post("/protective-order-cases/<case_id>/record-outcome")
def record_outcome(case_id):
    auth((ROLE_LEGAL_ADVOCATE,))
    body = get_body()
    outcome = req_enum(body, "outcome", OUTCOMES)
    case = get_case(case_id)

    if case["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a FILED case may carry an outcome")
    if clock_now() < derive.as_datetime(case["hearing_end_utc"]):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the hearing window has not closed yet")

    case["outcome_recorded_at"] = clock_iso()
    if outcome == "GRANTED":
        case["status"] = "GRANTED"
    else:
        if case["refile_count"] < MAX_REFILES:
            case["refile_count"] = case["refile_count"] + 1
            case["status"] = "PETITION_DRAFTED"
        else:
            case["status"] = "DENIED_FINAL"
        case["filed_court"] = None
        case["hearing_start_utc"] = None
        case["hearing_end_utc"] = None
        case["accompanying_advocate_id"] = None
    touch(case)

    client = db.clients.get(case["client_id"])
    if client is not None:
        touch(client)
        derive.refresh_protective_order_active(client)
        derive.recompute_client_posture(client)
    return ok(public(case))
