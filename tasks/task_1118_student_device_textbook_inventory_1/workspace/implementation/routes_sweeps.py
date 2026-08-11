"""AuditSweep endpoints (PRD 3.9)."""
from flask import Blueprint, request

from core import (STORE, auth, base_record, body, check_occ, fail, get_program,
                  get_sweep, list_response, now, ok_object, reject_stray_occ,
                  req_str, sweep_json, touch)

bp = Blueprint("sweeps", __name__)

SWEEP_READ = ["DistrictAdmin", "SiteTechnician"]


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


def _program_units(prog_id):
    out = []
    for u in STORE["units"].values():
        fleet = STORE["fleets"].get(u["fleet_id"])
        if fleet is not None and fleet["program_id"] == prog_id:
            out.append(u)
    return out


@bp.post("/api/programs/<progId>/audit-sweeps")
def create_sweep(progId):
    b = body()
    label = req_str(b, "sweep_label")
    reject_stray_occ(b, "expected_program_version")
    auth(["DistrictAdmin"])
    prog = get_program(progId)
    check_occ(b, "expected_program_version", prog["version"])
    rec = base_record()
    rec.update({
        "program_id": prog["id"],
        "sweep_label": label,
        "started_at": None,
        "closed_at": None,
        "unaccounted_count": 0,
        "status": "DRAFT",
        "_scanned": set(),
        "_flagged": [],
    })
    STORE["sweeps"][rec["id"]] = rec
    touch(prog)  # sweep creation increments DistrictProgram.version by 1
    return ok_object(sweep_json(rec), 201)


@bp.get("/api/programs/<progId>/audit-sweeps")
def list_sweeps(progId):
    auth(SWEEP_READ)
    prog = get_program(progId)
    st = _q("status")
    recs = [s for s in STORE["sweeps"].values()
            if s["program_id"] == prog["id"]
            and (st is None or s["status"] == st)]
    return list_response(recs, sweep_json)


@bp.get("/api/programs/<progId>/audit-sweeps/<sweepId>")
def get_sweep_route(progId, sweepId):
    auth(SWEEP_READ)
    prog = get_program(progId)
    return ok_object(sweep_json(get_sweep(sweepId, prog)))


@bp.post("/api/programs/<progId>/audit-sweeps/<sweepId>/begin")
def begin_sweep(progId, sweepId):
    b = body()
    reject_stray_occ(b)
    auth(["DistrictAdmin"])
    prog = get_program(progId)
    sweep = get_sweep(sweepId, prog)
    if sweep["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409, "Sweep must be DRAFT to begin")
    for s in STORE["sweeps"].values():
        if (s["program_id"] == prog["id"] and s["id"] != sweep["id"]
                and s["status"] in ("IN_PROGRESS", "RECONCILING")):
            fail("ERR_SWEEP_IN_PROGRESS", 409,
                 "Another sweep for this program is IN_PROGRESS or RECONCILING")
    sweep["status"] = "IN_PROGRESS"
    sweep["started_at"] = now()
    touch(sweep)
    return ok_object(sweep_json(sweep))


@bp.post("/api/programs/<progId>/audit-sweeps/<sweepId>/scan")
def scan_sweep(progId, sweepId):
    b = body()
    barcode = req_str(b, "asset_tag_barcode")
    reject_stray_occ(b)
    auth(["DistrictAdmin", "SiteTechnician"])
    prog = get_program(progId)
    sweep = get_sweep(sweepId, prog)
    if sweep["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", 409, "Sweep must be IN_PROGRESS to record scans")
    match = None
    for u in _program_units(prog["id"]):
        if u["asset_tag_barcode"] == barcode:
            match = u
            break
    if match is None:
        return ok_object({"recorded": False, "asset_unit_id": None})
    sweep["_scanned"].add(match["id"])
    return ok_object({"recorded": True, "asset_unit_id": match["id"]})


@bp.post("/api/programs/<progId>/audit-sweeps/<sweepId>/finish-scan")
def finish_scan(progId, sweepId):
    b = body()
    reject_stray_occ(b)
    auth(["DistrictAdmin"])
    prog = get_program(progId)
    sweep = get_sweep(sweepId, prog)
    if sweep["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", 409, "Sweep must be IN_PROGRESS to finish scanning")
    # unaccounted = expected (not disposed/donated/written-off) minus scanned.
    expected = [u for u in _program_units(prog["id"])
                if u["lifecycle_status"] not in ("DISPOSED", "DONATED", "WRITTEN_OFF")]
    unaccounted = [u for u in expected if u["id"] not in sweep["_scanned"]]
    sweep["unaccounted_count"] = len(unaccounted)
    sweep["_flagged"] = [u["id"] for u in unaccounted]
    for u in unaccounted:
        u["_unaccounted"] = True
    sweep["status"] = "RECONCILING"
    touch(sweep)
    return ok_object(sweep_json(sweep))


@bp.post("/api/programs/<progId>/audit-sweeps/<sweepId>/close")
def close_sweep(progId, sweepId):
    b = body()
    reject_stray_occ(b)
    auth(["DistrictAdmin"])
    prog = get_program(progId)
    sweep = get_sweep(sweepId, prog)
    if sweep["status"] != "RECONCILING":
        fail("ERR_INVALID_STATE", 409, "Sweep must be RECONCILING to close")
    # Every flagged unit must be resolved: written off, terminally disposed,
    # or re-located (its unaccounted flag cleared by a lifecycle transition).
    for uid in sweep["_flagged"]:
        u = STORE["units"].get(uid)
        if u is None:
            continue
        resolved = (u["lifecycle_status"] in ("WRITTEN_OFF", "DISPOSED", "DONATED")
                    or not u.get("_unaccounted"))
        if not resolved:
            fail("ERR_UNRESOLVED_UNACCOUNTED", 409,
                 "Unaccounted units remain unresolved")
    sweep["status"] = "CLOSED"
    sweep["closed_at"] = now()
    touch(sweep)
    return ok_object(sweep_json(sweep))
