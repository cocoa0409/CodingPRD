"""DistrictProgram lifecycle + logical clock endpoints."""
from flask import Blueprint

from core import (STORE, auth, body, check_occ, fail, get_program, iso,
                  list_response, now, ok_list, ok_object, opt_num, parse_dt,
                  program_json, reject_stray_occ, req_str, run_scheduled_scans,
                  set_lifecycle, base_record, touch, whole_days)

bp = Blueprint("programs", __name__)

PROGRAM_ROLES_READ = ["DistrictAdmin", "SiteTechnician", "Registrar", "Family"]


@bp.post("/api/programs")
def create_program():
    b = body()
    program_name = req_str(b, "program_name")
    school_year = req_str(b, "school_year")
    pct = opt_num(b, "loaner_pool_threshold_pct", 0.10)
    reject_stray_occ(b)
    auth(["DistrictAdmin"])
    rec = base_record()
    rec.update({
        "program_name": program_name,
        "school_year": school_year,
        "loaner_pool_threshold_pct": pct,
        "status": "DRAFT",
    })
    STORE["programs"][rec["id"]] = rec
    return ok_object(program_json(rec), 201)


@bp.get("/api/programs")
def list_programs():
    auth(PROGRAM_ROLES_READ)
    status = _q("status")
    recs = [p for p in STORE["programs"].values() if status is None or p["status"] == status]
    return list_response(recs, program_json)


@bp.get("/api/programs/<progId>")
def get_program_route(progId):
    auth(PROGRAM_ROLES_READ)
    return ok_object(program_json(get_program(progId)))


@bp.post("/api/programs/<progId>/activate")
def activate_program(progId):
    b = body()
    reject_stray_occ(b)
    auth(["DistrictAdmin"])
    prog = get_program(progId)
    if prog["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409, "Program must be DRAFT to activate")
    has_fleet = any(f["program_id"] == prog["id"] for f in STORE["fleets"].values())
    if not has_fleet:
        fail("ERR_PROGRAM_HAS_NO_FLEET", 409, "Cannot activate a program with zero AssetFleets")
    prog["status"] = "ACTIVE"
    touch(prog)
    return ok_object(program_json(prog))


@bp.post("/api/programs/<progId>/begin-summer-collection")
def begin_summer_collection(progId):
    b = body()
    reject_stray_occ(b)
    auth(["DistrictAdmin"])
    prog = get_program(progId)
    if prog["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", 409, "Program must be ACTIVE to begin summer collection")
    # Blocked while any assignment has been OVERDUE > 30 days without a
    # corresponding NON_RETURN fee (PRD 3.9).
    prog_student_ids = {s["id"] for s in STORE["students"].values()
                        if s["program_id"] == prog["id"]}
    for a in STORE["assignments"].values():
        if a["student_account_id"] not in prog_student_ids or a["status"] != "OVERDUE":
            continue
        overdue_days = whole_days(a["expected_return_date"], now())
        if overdue_days > 30:
            resolved = any(
                f["student_account_id"] == a["student_account_id"]
                and f["fee_type"] == "NON_RETURN"
                and f["created_at"] >= a["expected_return_date"]
                for f in STORE["fees"].values())
            if not resolved:
                fail("ERR_OVERDUE_UNRESOLVED", 409,
                     "An assignment has been OVERDUE for more than 30 days without a NON_RETURN fee")
    # Cascade: past-due ACTIVE assignments flip to OVERDUE.
    for a in STORE["assignments"].values():
        if (a["student_account_id"] in prog_student_ids and a["status"] == "ACTIVE"
                and a["checked_in_at"] is None and a["expected_return_date"] < now()):
            a["status"] = "OVERDUE"
            touch(a)
    # Cascade: every DEPLOYED unit moves to SUMMER_INTAKE with a RETURN event.
    for u in STORE["units"].values():
        fleet = STORE["fleets"].get(u["fleet_id"])
        if fleet is not None and fleet["program_id"] == prog["id"] and u["lifecycle_status"] == "DEPLOYED":
            set_lifecycle(u, "SUMMER_INTAKE", "RETURN", relocated=True)
    prog["status"] = "SUMMER_COLLECTION"
    touch(prog)
    return ok_object(program_json(prog))


@bp.post("/api/programs/<progId>/close")
def close_program(progId):
    b = body()
    reject_stray_occ(b)
    auth(["DistrictAdmin"])
    prog = get_program(progId)
    if prog["status"] != "SUMMER_COLLECTION":
        fail("ERR_INVALID_STATE", 409, "Program must be in SUMMER_COLLECTION to close")
    for u in STORE["units"].values():
        fleet = STORE["fleets"].get(u["fleet_id"])
        if (fleet is not None and fleet["program_id"] == prog["id"]
                and u["lifecycle_status"] in ("SUMMER_INTAKE", "RE_IMAGING")):
            fail("ERR_UNPROCESSED_SUMMER_INTAKE", 409,
                 "Asset units remain in SUMMER_INTAKE or RE_IMAGING")
    for s in STORE["sweeps"].values():
        if s["program_id"] == prog["id"] and s["status"] != "CLOSED":
            fail("ERR_OPEN_AUDIT_SWEEP", 409, "All audit sweeps for the program must be CLOSED")
    prog["status"] = "CLOSED"
    touch(prog)
    return ok_object(program_json(prog))


@bp.post("/_clock/set_current_utc")
def set_clock():
    b = body()
    if "to_iso8601" not in b or b["to_iso8601"] is None:
        fail("ERR_INVALID_REQUEST", 400, "Required field 'to_iso8601' is missing")
    target = parse_dt(b["to_iso8601"], "to_iso8601")
    reject_stray_occ(b)
    auth(["DistrictAdmin"])
    from core import CLOCK
    if target < CLOCK["now"]:
        fail("ERR_INVALID_REQUEST", 400, "The logical clock only moves forward")
    CLOCK["now"] = target
    run_scheduled_scans()
    return ok_object({"current_utc": iso(now())})


def _q(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None
