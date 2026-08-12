"""Railcars, inspections, and AAR defect findings (PRD 3.2, 3.6)."""
from flask import Blueprint, g, request

import db
from errors import ApiError
from common import (
    auth, ok, get_body, req_str, invalid_request, base_fields,
    touch, get_or_404, ref_or_404, public, sort_items, list_response,
    now, now_iso, parse_dt, parse_date, dwell_actual, fnum,
    DEFECT_GROUPS, CAUSE_CODES, SEVERITIES, AAR_CODE_RE,
)

bp = Blueprint("rail", __name__)


def railcar_out(r):
    return public(r)


def inspection_out(i):
    return public(i)


def defect_out(d):
    return public(d)


def railcar_shop(railcar):
    return db.STORE["shops"].get(railcar["shop_id"])


# ---------------------------------------------------------------------------
# Railcars
# ---------------------------------------------------------------------------

@bp.post("/railcars")
@auth("YardClerk")
def create_railcar():
    body = get_body()
    shop = ref_or_404("shops", req_str(body, "shop_id"), "Shop")
    owner = ref_or_404("car_owners", req_str(body, "owner_id"), "CarOwner")
    line = ref_or_404("handling_lines", req_str(body, "handling_line_id"), "HandlingLine")
    built_raw = req_str(body, "built_date")
    try:
        built = parse_date(built_raw)
    except (ValueError, TypeError):
        raise invalid_request("built_date must be a YYYY-MM-DD date")
    car = base_fields()
    car.update({
        "shop_id": shop["id"],
        "reporting_mark": req_str(body, "reporting_mark"),
        "car_number": req_str(body, "car_number"),
        "owner_id": owner["id"],
        "handling_line_id": line["id"],
        "built_date": built.isoformat(),
        "arrived_at": now_iso(),
        "departed_at": None,
        "status": "ARRIVED",
        "shop_delay_hours": 0.0,
        "projected_dwell_charge_cents": None,
        "dwell_charge_cents": None,
    })
    db.STORE["railcars"][car["id"]] = car
    return ok(railcar_out(car), code=201)


@bp.get("/railcars")
@auth("Any")
def list_railcars():
    items = list(db.STORE["railcars"].values())
    for name in ("shop_id", "owner_id", "handling_line_id", "status"):
        v = request.args.get(name)
        if v is not None:
            items = [r for r in items if r[name] == v]
    return list_response([railcar_out(r) for r in sort_items(items)])


@bp.get("/railcars/<rid>")
@auth("Any")
def get_railcar(rid):
    return ok(railcar_out(get_or_404("railcars", rid, "Railcar")))


@bp.post("/railcars/<rid>/depart")
@auth("YardClerk")
def depart_railcar(rid):
    car = get_or_404("railcars", rid, "Railcar")
    get_body(required=False)
    if car["status"] not in ("ARRIVED", "READY_FOR_DEPARTURE"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Railcar cannot depart from status %s" % car["status"])
    open_wos = [w for w in db.STORE["work_orders"].values()
                if w["railcar_id"] == car["id"]
                and w["exec_status"] not in ("COMPLETED", "CANCELLED")]
    if open_wos:
        raise ApiError("ERR_OPEN_WORK_ORDERS", 409,
                       "A work order of this railcar is not yet completed or cancelled")
    car_inspections = [i["id"] for i in db.STORE["inspections"].values()
                       if i["railcar_id"] == car["id"]]
    for d in db.STORE["defects"].values():
        if (d["inspection_id"] in car_inspections
                and d["severity"] == "CONDEMNABLE"
                and d["status"] not in ("REPAIRED", "DECLINED")):
            raise ApiError("ERR_UNRESOLVED_SAFETY_DEFECT", 409,
                           "A CONDEMNABLE finding is neither REPAIRED nor DECLINED")
    car["departed_at"] = now_iso()
    car["status"] = "DEPARTED"
    shop = railcar_shop(car)
    _, _, charge = dwell_actual(car, shop, parse_dt(car["departed_at"]))
    car["dwell_charge_cents"] = charge
    touch(car)
    return ok(railcar_out(car))


@bp.get("/railcars/<rid>/dwell-summary")
@auth("Any")
def dwell_summary(rid):
    car = get_or_404("railcars", rid, "Railcar")
    shop = railcar_shop(car)
    end = parse_dt(car["departed_at"]) if car["departed_at"] else now()
    actual, billable, charge = dwell_actual(car, shop, end)
    data = {
        "actual_dwell_hours": fnum(actual, 2),
        "shop_delay_hours": fnum(car["shop_delay_hours"], 2),
        "billable_hours": fnum(billable, 2),
        "dwell_charge_cents": charge,
        "projected_dwell_charge_cents": car["projected_dwell_charge_cents"],
    }
    return ok(data)


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------

@bp.post("/railcars/<rid>/inspections")
@auth("CarInspector")
def create_inspection(rid):
    car = get_or_404("railcars", rid, "Railcar")
    get_body(required=False)
    insp = base_fields()
    insp.update({
        "railcar_id": car["id"],
        "status": "IN_PROGRESS",
        "inspector_user_id": g.user_id,
        "completed_at": None,
        "reopened_count": 0,
    })
    db.STORE["inspections"][insp["id"]] = insp
    return ok(inspection_out(insp), code=201)


@bp.get("/railcars/<rid>/inspections")
@auth("Any")
def list_inspections(rid):
    car = get_or_404("railcars", rid, "Railcar")
    items = [i for i in db.STORE["inspections"].values() if i["railcar_id"] == car["id"]]
    return list_response([inspection_out(i) for i in sort_items(items)])


@bp.get("/inspections/<iid>")
@auth("Any")
def get_inspection(iid):
    return ok(inspection_out(get_or_404("inspections", iid, "Inspection")))


@bp.post("/inspections/<iid>/complete")
@auth("CarInspector")
def complete_inspection(iid):
    insp = get_or_404("inspections", iid, "Inspection")
    get_body(required=False)
    if insp["status"] not in ("IN_PROGRESS", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Inspection cannot be completed from status %s" % insp["status"])
    insp["status"] = "COMPLETED"
    insp["completed_at"] = now_iso()
    touch(insp)
    return ok(inspection_out(insp))


@bp.post("/inspections/<iid>/reopen")
@auth("RepairForeman")
def reopen_inspection(iid):
    insp = get_or_404("inspections", iid, "Inspection")
    get_body(required=False)
    if insp["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a COMPLETED inspection can be reopened")
    for w in db.STORE["work_orders"].values():
        if (w["inspection_id"] == insp["id"]
                and w["auth_status"] in ("PENDING_AUTHORIZATION", "AUTHORIZED")):
            raise ApiError("ERR_INSPECTION_LOCKED", 409,
                           "Inspection is referenced by a pending or authorized work order")
    insp["status"] = "REOPENED"
    insp["reopened_count"] += 1
    touch(insp)
    return ok(inspection_out(insp))


# ---------------------------------------------------------------------------
# Defect findings
# ---------------------------------------------------------------------------

@bp.post("/inspections/<iid>/defects")
@auth("CarInspector")
def create_defect(iid):
    insp = get_or_404("inspections", iid, "Inspection")
    body = get_body()
    for f in ("aar_defect_code", "defect_group", "cause_code", "severity", "location"):
        req_str(body, f)
    if insp["status"] not in ("IN_PROGRESS", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Defects can only be filed against an open inspection")
    bad_code = ApiError("ERR_INVALID_DEFECT_CODE", 422,
                        "aar_defect_code must match AAR-NNNN and enums must be valid")
    if not AAR_CODE_RE.match(body["aar_defect_code"]):
        raise bad_code
    if body["defect_group"] not in DEFECT_GROUPS:
        raise bad_code
    if body["cause_code"] not in CAUSE_CODES:
        raise bad_code
    if body["severity"] not in SEVERITIES:
        raise bad_code
    defect = base_fields()
    defect.update({
        "inspection_id": insp["id"],
        "aar_defect_code": body["aar_defect_code"],
        "defect_group": body["defect_group"],
        "cause_code": body["cause_code"],
        "severity": body["severity"],
        "location": body["location"],
        "status": "OPEN",
    })
    db.STORE["defects"][defect["id"]] = defect
    return ok(defect_out(defect), code=201)


@bp.get("/inspections/<iid>/defects")
@auth("Any")
def list_defects(iid):
    insp = get_or_404("inspections", iid, "Inspection")
    items = [d for d in db.STORE["defects"].values() if d["inspection_id"] == insp["id"]]
    for name in ("status", "severity"):
        v = request.args.get(name)
        if v is not None:
            items = [d for d in items if d[name] == v]
    return list_response([defect_out(d) for d in sort_items(items)])


@bp.post("/inspections/<iid>/defects/<did>/decline")
@auth("RepairForeman")
def decline_defect(iid, did):
    insp = get_or_404("inspections", iid, "Inspection")
    defect = db.STORE["defects"].get(did)
    if defect is None or defect["inspection_id"] != insp["id"]:
        raise ApiError("ERR_NOT_FOUND", 404,
                       "DefectFinding %s not found under inspection %s" % (did, iid))
    get_body(required=False)
    if defect["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an OPEN finding can be declined")
    defect["status"] = "DECLINED"
    touch(defect)
    return ok(defect_out(defect))
