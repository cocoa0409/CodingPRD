"""AssetFleet, AssetUnit lifecycle, and AssetLifecycleEvent endpoints."""
from flask import Blueprint, request

from core import (GRADE_RANK, STORE, append_event, auth, base_record, body,
                  check_occ, event_json, fail, fleet_json, get_fleet,
                  get_program, get_unit, list_response, months_in_service,
                  ok_object, opt_enum, reject_stray_occ, req_enum, req_int,
                  req_str, req_dt, set_lifecycle, touch, unit_json,
                  assignment_json, loaner_json)

bp = Blueprint("assets", __name__)

ASSET_READ = ["DistrictAdmin", "SiteTechnician", "Registrar"]
GRADES = ["A", "B", "C", "D", "F"]


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


# ------------------------------------------------------------- fleets ------
@bp.post("/api/programs/<progId>/fleets")
def create_fleet(progId):
    b = body()
    fleet_name = req_str(b, "fleet_name")
    asset_class = req_enum(b, "asset_class", ["DEVICE", "TEXTBOOK"])
    repl = req_int(b, "unit_replacement_cost_cents", minimum=0)
    salvage = req_int(b, "salvage_value_cents", minimum=0)
    ulm = req_int(b, "useful_life_months", minimum=0)
    in_service = req_dt(b, "in_service_date")
    reject_stray_occ(b)
    auth(["DistrictAdmin"])
    prog = get_program(progId)
    rec = base_record()
    rec.update({
        "program_id": prog["id"],
        "fleet_name": fleet_name,
        "asset_class": asset_class,
        "unit_replacement_cost_cents": repl,
        "salvage_value_cents": salvage,
        "useful_life_months": ulm,
        "in_service_date": in_service,
    })
    STORE["fleets"][rec["id"]] = rec
    return ok_object(fleet_json(rec), 201)


@bp.get("/api/programs/<progId>/fleets")
def list_fleets(progId):
    auth(ASSET_READ)
    prog = get_program(progId)
    asset_class = _q("asset_class")
    recs = [f for f in STORE["fleets"].values()
            if f["program_id"] == prog["id"]
            and (asset_class is None or f["asset_class"] == asset_class)]
    return list_response(recs, fleet_json)


@bp.get("/api/programs/<progId>/fleets/<fleetId>")
def get_fleet_route(progId, fleetId):
    auth(ASSET_READ)
    prog = get_program(progId)
    return ok_object(fleet_json(get_fleet(fleetId, prog)))


# ------------------------------------------------------------- units -------
@bp.post("/api/programs/<progId>/fleets/<fleetId>/asset-units")
def intake_unit(progId, fleetId):
    b = body()
    barcode = req_str(b, "asset_tag_barcode")
    serial = req_str(b, "serial_number")
    grade = opt_enum(b, "condition_grade", GRADES, "A")
    reject_stray_occ(b)
    auth(["DistrictAdmin", "SiteTechnician"])
    prog = get_program(progId)
    fleet = get_fleet(fleetId, prog)
    # barcode unique within program; serial unique within fleet (PRD 3.1)
    for u in STORE["units"].values():
        uf = STORE["fleets"].get(u["fleet_id"])
        if uf is not None and uf["program_id"] == prog["id"] and u["asset_tag_barcode"] == barcode:
            fail("ERR_INVALID_REQUEST", 400, "asset_tag_barcode must be unique within the program")
        if u["fleet_id"] == fleet["id"] and u["serial_number"] == serial:
            fail("ERR_INVALID_REQUEST", 400, "serial_number must be unique within the fleet")
    rec = base_record()
    rec.update({
        "fleet_id": fleet["id"],
        "asset_tag_barcode": barcode,
        "serial_number": serial,
        "condition_grade": grade,
        "lifecycle_status": "READY",
        "assigned_to_student_id": None,
        "_unaccounted": False,
        "_repair_student_id": None,
        "_repair_start_event_id": None,
        "_failed_repairs": 0,
    })
    STORE["units"][rec["id"]] = rec
    append_event(rec, "INTAKE")
    return ok_object(unit_json(rec), 201)


@bp.get("/api/programs/<progId>/fleets/<fleetId>/asset-units")
def list_units_in_fleet(progId, fleetId):
    auth(ASSET_READ)
    prog = get_program(progId)
    fleet = get_fleet(fleetId, prog)
    return list_response(_filter_units(request.args, fleet_id=fleet["id"]), unit_json)


def _filter_units(args, fleet_id=None, program_id=None, assigned_to=None):
    ls = args.get("lifecycle_status")
    cg = args.get("condition_grade")
    at = args.get("assigned_to_student_id") if assigned_to is None else assigned_to
    fid = fleet_id or args.get("fleet_id")
    pid = program_id or args.get("program_id")
    out = []
    for u in STORE["units"].values():
        fleet = STORE["fleets"].get(u["fleet_id"])
        if fid and u["fleet_id"] != fid:
            continue
        if pid and (fleet is None or fleet["program_id"] != pid):
            continue
        if ls and u["lifecycle_status"] != ls:
            continue
        if cg and u["condition_grade"] != cg:
            continue
        if at and u["assigned_to_student_id"] != at:
            continue
        out.append(u)
    return out


@bp.get("/api/programs/<progId>/asset-units/<assetId>")
def get_unit_route(progId, assetId):
    auth(ASSET_READ)
    prog = get_program(progId)
    return ok_object(unit_json(get_unit(assetId, prog)))


@bp.post("/api/programs/<progId>/asset-units/<assetId>/designate-loaner")
def designate_loaner(progId, assetId):
    b = body()
    reject_stray_occ(b)
    auth(["SiteTechnician"])
    prog = get_program(progId)
    unit = get_unit(assetId, prog)
    if unit["lifecycle_status"] != "READY":
        fail("ERR_INVALID_STATE", 409, "Unit must be READY to designate as loaner")
    if unit["condition_grade"] not in ("A", "B", "C"):
        fail("ERR_LOANER_CONDITION_TOO_LOW", 409,
             "designate-loaner requires condition_grade in {A, B, C}")
    set_lifecycle(unit, "LOANER")
    return ok_object(unit_json(unit))


@bp.post("/api/programs/<progId>/asset-units/<assetId>/return-loaner-to-pool")
def return_loaner_to_pool(progId, assetId):
    b = body()
    reject_stray_occ(b)
    auth(["SiteTechnician"])
    prog = get_program(progId)
    unit = get_unit(assetId, prog)
    if unit["lifecycle_status"] != "LOANER":
        fail("ERR_INVALID_STATE", 409, "Unit must be LOANER to return to pool")
    for c in STORE["loaners"].values():
        if c["loaner_asset_unit_id"] == unit["id"] and c["status"] == "OPEN":
            fail("ERR_LOANER_STILL_OUT", 409,
                 "An OPEN LoanerCheckout still references this unit")
    set_lifecycle(unit, "READY")
    return ok_object(unit_json(unit))


@bp.post("/api/programs/<progId>/asset-units/<assetId>/complete-repair")
def complete_repair(progId, assetId):
    b = body()
    post_grade = req_enum(b, "post_repair_grade", GRADES)
    reject_stray_occ(b)
    auth(["SiteTechnician"])
    prog = get_program(progId)
    unit = get_unit(assetId, prog)
    if unit["lifecycle_status"] != "IN_REPAIR":
        fail("ERR_INVALID_STATE", 409, "Unit must be IN_REPAIR to complete a repair")
    # Priority-13 completion payload check (after state, per PRD 2.10).
    if "repair_cost_cents" not in b or b["repair_cost_cents"] is None:
        fail("ERR_REPAIR_COST_REQUIRED", 400, "complete-repair requires repair_cost_cents")
    repair_cost = req_int(b, "repair_cost_cents", minimum=0)
    unit["condition_grade"] = post_grade
    if post_grade == "F":
        unit["_failed_repairs"] = unit.get("_failed_repairs", 0) + 1
    set_lifecycle(unit, "READY", "REPAIR_COMPLETE",
                  {"repair_cost_cents": repair_cost, "post_repair_grade": post_grade})
    return ok_object(unit_json(unit))


@bp.post("/api/programs/<progId>/asset-units/<assetId>/begin-reimage")
def begin_reimage(progId, assetId):
    b = body()
    reject_stray_occ(b)
    auth(["SiteTechnician"])
    prog = get_program(progId)
    unit = get_unit(assetId, prog)
    if prog["status"] != "SUMMER_COLLECTION":
        fail("ERR_PROGRAM_STATE_FORBIDS", 409, "Re-imaging requires SUMMER_COLLECTION")
    if unit["lifecycle_status"] != "SUMMER_INTAKE":
        fail("ERR_INVALID_STATE", 409, "Unit must be in SUMMER_INTAKE to begin re-imaging")
    fleet = STORE["fleets"][unit["fleet_id"]]
    if fleet["asset_class"] != "DEVICE":
        fail("ERR_REIMAGE_TEXTBOOK_NOT_ALLOWED", 409, "Textbook units cannot be re-imaged")
    ev = append_event(unit, "RE_IMAGE")
    unit["_reimage_event_id"] = ev["id"]
    unit["lifecycle_status"] = "RE_IMAGING"
    unit["assigned_to_student_id"] = None
    unit["_unaccounted"] = False
    touch(unit)
    return ok_object(unit_json(unit))


@bp.post("/api/programs/<progId>/asset-units/<assetId>/complete-reimage")
def complete_reimage(progId, assetId):
    b = body()
    reject_stray_occ(b)
    auth(["SiteTechnician"])
    prog = get_program(progId)
    unit = get_unit(assetId, prog)
    if prog["status"] != "SUMMER_COLLECTION":
        fail("ERR_PROGRAM_STATE_FORBIDS", 409, "Re-imaging requires SUMMER_COLLECTION")
    fleet = STORE["fleets"][unit["fleet_id"]]
    if unit["lifecycle_status"] == "SUMMER_INTAKE":
        # Textbooks skip imaging: SUMMER_INTAKE -> READY directly.
        if fleet["asset_class"] != "TEXTBOOK":
            fail("ERR_INVALID_STATE", 409, "DEVICE units must pass through RE_IMAGING")
        set_lifecycle(unit, "READY")
        return ok_object(unit_json(unit))
    if unit["lifecycle_status"] != "RE_IMAGING":
        fail("ERR_INVALID_STATE", 409, "Unit must be RE_IMAGING to complete re-imaging")
    # Priority-13 completion payload check.
    if "image_version" not in b or b["image_version"] is None:
        fail("ERR_IMAGE_VERSION_REQUIRED", 400, "complete-reimage on a DEVICE requires image_version")
    image_version = req_str(b, "image_version")
    ev_id = unit.get("_reimage_event_id")
    if ev_id and ev_id in STORE["events"]:
        STORE["events"][ev_id]["event_payload"]["image_version"] = image_version
    set_lifecycle(unit, "READY")
    return ok_object(unit_json(unit))


@bp.post("/api/programs/<progId>/asset-units/<assetId>/retire")
def retire_unit(progId, assetId):
    b = body()
    reject_stray_occ(b, "expected_asset_unit_version")
    auth(["DistrictAdmin"])
    prog = get_program(progId)
    unit = get_unit(assetId, prog)
    check_occ(b, "expected_asset_unit_version", unit["version"])
    if unit["lifecycle_status"] not in ("DEPLOYED", "READY"):
        fail("ERR_INVALID_STATE", 409, "Only DEPLOYED or READY units can be retired")
    fleet = STORE["fleets"][unit["fleet_id"]]
    eol = (months_in_service(unit) >= fleet["useful_life_months"]
           or (unit["condition_grade"] == "F" and unit.get("_failed_repairs", 0) >= 2))
    if not eol:
        fail("ERR_EOL_CRITERIA_NOT_MET", 409,
             "months_in_service must reach useful_life_months, or grade F with two failed repairs")
    set_lifecycle(unit, "END_OF_LIFE", "RETIRE")
    return ok_object(unit_json(unit))


@bp.post("/api/programs/<progId>/asset-units/<assetId>/dispose")
def dispose_unit(progId, assetId):
    _eol_exit(progId, assetId, "DISPOSED", "DISPOSE")
    return ok_object(unit_json(get_unit(assetId, get_program(progId))))


@bp.post("/api/programs/<progId>/asset-units/<assetId>/donate")
def donate_unit(progId, assetId):
    _eol_exit(progId, assetId, "DONATED", "DONATE")
    return ok_object(unit_json(get_unit(assetId, get_program(progId))))


def _eol_exit(progId, assetId, status, event_type):
    b = body()
    reject_stray_occ(b)
    auth(["DistrictAdmin"])
    prog = get_program(progId)
    unit = get_unit(assetId, prog)
    if unit["lifecycle_status"] != "END_OF_LIFE":
        fail("ERR_INVALID_STATE", 409, "Unit must be END_OF_LIFE")
    if unit["assigned_to_student_id"] is not None:
        fail("ERR_STILL_ASSIGNED", 409, "Unit is still assigned to a student")
    set_lifecycle(unit, status, event_type)


@bp.post("/api/programs/<progId>/asset-units/<assetId>/write-off")
def write_off_unit(progId, assetId):
    b = body()
    reject_stray_occ(b)
    auth(["DistrictAdmin"])
    prog = get_program(progId)
    unit = get_unit(assetId, prog)
    if unit["lifecycle_status"] != "END_OF_LIFE":
        fail("ERR_INVALID_STATE", 409, "Unit must be END_OF_LIFE to write off")
    if not unit.get("_unaccounted"):
        fail("ERR_NOT_UNACCOUNTED", 409,
             "Unit must have been flagged unaccounted in an audit sweep")
    set_lifecycle(unit, "WRITTEN_OFF", "WRITE_OFF")
    return ok_object(unit_json(unit))


# ------------------------------------------------- lifecycle events --------
@bp.get("/api/programs/<progId>/asset-units/<assetId>/lifecycle-events")
def list_unit_events(progId, assetId):
    auth(ASSET_READ)
    prog = get_program(progId)
    unit = get_unit(assetId, prog)
    et = _q("event_type")
    sup = _q("supersedes_event_id")
    recs = [e for e in STORE["events"].values()
            if e["asset_unit_id"] == unit["id"]
            and (et is None or e["event_type"] == et)
            and (sup is None or e["supersedes_event_id"] == sup)]
    return list_response(recs, event_json)


# ------------------------------------------- unit sub-resources ------------
@bp.get("/api/programs/<progId>/asset-units/<assetId>/assignments")
def list_unit_assignments(progId, assetId):
    auth(ASSET_READ)
    prog = get_program(progId)
    unit = get_unit(assetId, prog)
    recs = [a for a in STORE["assignments"].values() if a["asset_unit_id"] == unit["id"]]
    return list_response(recs, assignment_json)


@bp.get("/api/programs/<progId>/asset-units/<assetId>/loaner-checkouts")
def list_unit_loaners(progId, assetId):
    auth(["DistrictAdmin", "SiteTechnician"])
    prog = get_program(progId)
    unit = get_unit(assetId, prog)
    recs = [c for c in STORE["loaners"].values() if c["loaner_asset_unit_id"] == unit["id"]]
    return list_response(recs, loaner_json)
