from datetime import timedelta

from flask import Blueprint

import db
from db import LOCK, STORE
from errors import ApiError
from middleware import auth
from response import ok_list, ok_object
from services import calc, serialize as ser
from services.resolution import get_case, get_hearing, jurisdiction_of_case
from utils import body_json, pagination, v_dt, v_str

bp = Blueprint("hearings", __name__)


def _validate_scheduling(case, courtroom, start_at, end_at, exclude_hearing_id=None):
    """The four scheduling rules, in ladder order after the state gate."""
    # 1. at most one SCHEDULED hearing per case
    for h in STORE.hearings.values():
        if (
            h["case_id"] == case["id"]
            and h["status"] == "SCHEDULED"
            and h["id"] != exclude_hearing_id
        ):
            raise ApiError(
                "ERR_HEARING_ALREADY_SCHEDULED",
                409,
                "Case already has a SCHEDULED hearing",
            )
    # 2. window well-formed
    if end_at <= start_at:
        raise ApiError(
            "ERR_HEARING_WINDOW_INVALID", 422, "end_at must be later than start_at"
        )
    # 3. statutory lead time (date granularity)
    jurisdiction = jurisdiction_of_case(case)
    lead = calc.HEARING_LEAD_DAYS[jurisdiction]
    scd = case["service_completed_at"].date()
    if start_at.date() < scd + timedelta(days=lead):
        raise ApiError(
            "ERR_HEARING_LEAD_TIME",
            422,
            "Hearing date before service_completed_at + jurisdictional lead days",
        )
    # 4. courtroom half-open [start_at, end_at) overlap
    for h in STORE.hearings.values():
        if (
            h["courtroom"] == courtroom
            and h["status"] == "SCHEDULED"
            and h["id"] != exclude_hearing_id
            and h["start_at"] < end_at
            and start_at < h["end_at"]
        ):
            raise ApiError(
                "ERR_COURTROOM_OVERLAP",
                409,
                "Hearing window intersects another SCHEDULED hearing in the same courtroom",
            )


@bp.post("/api/cases/<cid>/hearings")
@auth({"CourtClerk"})
def create_hearing(cid, _uid, _role):
    with LOCK:
        case = get_case(cid)
        b = body_json()
        courtroom = v_str(b, "courtroom")
        start_at = v_dt(b, "start_at")
        end_at = v_dt(b, "end_at")
        if case["status"] not in ("SERVICE_COMPLETE", "HEARING_SCHEDULED"):
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Case status does not permit hearing scheduling"
            )
        _validate_scheduling(case, courtroom, start_at, end_at)
        r = db.new_record(
            {
                "case_id": cid,
                "courtroom": courtroom,
                "start_at": start_at,
                "end_at": end_at,
                "status": "SCHEDULED",
                "clerk_user_id": _uid,
            }
        )
        STORE.hearings[r["id"]] = r
        if case["status"] == "SERVICE_COMPLETE":
            case["status"] = "HEARING_SCHEDULED"
            db.bump(case)
        return ok_object(ser.hearing(r), 201)


@bp.get("/api/hearings/<hid>")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def read_hearing(hid, _uid, _role):
    with LOCK:
        return ok_object(ser.hearing(get_hearing(hid)))


@bp.get("/api/cases/<cid>/hearings")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def list_case_hearings(cid, _uid, _role):
    with LOCK:
        get_case(cid)
        limit, offset = pagination()
        items = [h for h in db.sorted_items(STORE.hearings) if h["case_id"] == cid]
        page = items[offset : offset + limit]
        return ok_list([ser.hearing(r) for r in page], len(items), limit, offset)


@bp.post("/api/hearings/<hid>/continuance")
@auth({"CourtClerk"})
def continuance(hid, _uid, _role):
    with LOCK:
        hearing = get_hearing(hid)
        b = body_json()
        courtroom = v_str(b, "courtroom")
        start_at = v_dt(b, "start_at")
        end_at = v_dt(b, "end_at")
        v_str(b, "reason", required=False)
        if hearing["status"] != "SCHEDULED":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Hearing is not SCHEDULED"
            )
        case = STORE.cases[hearing["case_id"]]
        _validate_scheduling(case, courtroom, start_at, end_at, exclude_hearing_id=hid)
        hearing["status"] = "CONTINUED"
        db.bump(hearing)
        r = db.new_record(
            {
                "case_id": case["id"],
                "courtroom": courtroom,
                "start_at": start_at,
                "end_at": end_at,
                "status": "SCHEDULED",
                "clerk_user_id": _uid,
            }
        )
        STORE.hearings[r["id"]] = r
        return ok_object(ser.hearing(r), 201)


@bp.post("/api/hearings/<hid>/conclude")
@auth({"CourtClerk"})
def conclude(hid, _uid, _role):
    with LOCK:
        hearing = get_hearing(hid)
        b = body_json()
        v_str(b, "notes", required=False)
        case = STORE.cases[hearing["case_id"]]
        if hearing["status"] != "SCHEDULED" or case["status"] not in (
            "HEARING_SCHEDULED",
            "ANSWERED",
        ):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Hearing must be SCHEDULED and case HEARING_SCHEDULED or ANSWERED",
            )
        hearing["status"] = "HELD"
        db.bump(hearing)
        case["status"] = "HEARING_CONCLUDED"
        db.bump(case)
        return ok_object(ser.hearing(hearing))
