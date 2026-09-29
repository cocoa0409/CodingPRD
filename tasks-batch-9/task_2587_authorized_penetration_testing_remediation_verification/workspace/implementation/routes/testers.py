"""The tester roster, background checks and certification rescoring (PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import serialize
from auth import authorize
from core import new_record, ordered, revoke_assignment, touch
from envelope import object_response
from errors import ApiError
from resolve import filtered, get_tester, paginate
from store import store
from validate import body, get_datetime, get_enum, get_enum_array, get_int, get_str

bp = Blueprint("testers", __name__)

CERTIFICATIONS = ("OSCP", "GPEN", "CREST", "CISSP")
CHECK_RESULTS = ("CLEARED", "FLAGGED", "EXPIRED")
READ_ROLES = ("PlatformAdmin", "ProgramManager", "ComplianceOfficer")


@bp.post("/testers")
def register_tester():
    authorize("PlatformAdmin")
    data = body()
    full_name = get_str(data, "full_name", min_len=1, max_len=120)
    certifications = get_enum_array(data, "certifications", CERTIFICATIONS, required=True)
    clearance_raw, clearance = get_datetime(data, "clearance_expires_at")
    cap = get_int(data, "max_concurrent_engagements", required=False, minimum=1, maximum=5, default=2)
    record = new_record(
        full_name=full_name,
        certifications=certifications,
        max_concurrent_engagements=cap,
        clearance_expires_at=clearance,
        clearance_expires_at_raw=clearance_raw,
        background_check_status="PENDING",
        background_check_at=None,
        qualification_score=Decimal(calc.qualification_score(certifications)),
        availability_state="PENDING_CLEARANCE",
        active_assignment_count=0,
    )
    store.testers[record["id"]] = record
    return object_response(serialize.tester(record), 201)


@bp.get("/testers/<tester_id>")
def read_tester(tester_id):
    authorize(*READ_ROLES)
    return object_response(serialize.tester(get_tester(tester_id)))


@bp.get("/testers")
def list_testers():
    authorize(*READ_ROLES)
    rows = filtered(
        list(store.testers.values()),
        background_check_status=request.args.get("background_check_status"),
        availability_state=request.args.get("availability_state"),
    )
    return paginate(rows, serialize.tester)


@bp.post("/testers/<tester_id>/background-check")
def background_check(tester_id):
    authorize("PlatformAdmin", "ComplianceOfficer")
    tester = get_tester(tester_id)
    data = body()
    result = get_enum(data, "result", CHECK_RESULTS)
    now = store.now()
    if result == "CLEARED":
        if tester["availability_state"] not in ("PENDING_CLEARANCE", "SUSPENDED"):
            raise ApiError("ERR_TESTER_STATE_INVALID")
        if not tester["clearance_expires_at"] > now:
            raise ApiError("ERR_CLEARANCE_EXPIRED")
        tester["background_check_status"] = result
        tester["background_check_at"] = now
        tester["availability_state"] = "AVAILABLE"
        touch(tester)
    else:
        if tester["availability_state"] not in ("AVAILABLE", "ASSIGNED"):
            raise ApiError("ERR_TESTER_STATE_INVALID")
        tester["background_check_status"] = result
        tester["background_check_at"] = now
        tester["availability_state"] = "SUSPENDED"
        touch(tester)
        for assignment in ordered(list(store.assignments.values())):
            if assignment["tester_id"] != tester["id"]:
                continue
            if assignment["access_state"] != "PROVISIONED":
                continue
            revoke_assignment(assignment)
        tester["active_assignment_count"] = 0
    return object_response(serialize.tester(tester))


@bp.post("/testers/<tester_id>/certifications")
def replace_certifications(tester_id):
    authorize("PlatformAdmin")
    tester = get_tester(tester_id)
    data = body()
    certifications = get_enum_array(data, "certifications", CERTIFICATIONS, required=True)
    tester["certifications"] = certifications
    tester["qualification_score"] = Decimal(calc.qualification_score(certifications))
    touch(tester)
    return object_response(serialize.tester(tester))
