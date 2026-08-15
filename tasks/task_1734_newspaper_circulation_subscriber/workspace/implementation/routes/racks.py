"""RackLocation and RackSalesReport endpoints."""
from flask import Blueprint, request

import domain
from db import bump, by_created, create_rec, store
from errors import ApiError
from middleware import body, require_roles
from response import ok_obj, paginate
from serialize import ser_rack, ser_rack_report
from validate import opt_int, req_date, req_int, req_str

bp = Blueprint("racks", __name__)

DIST_ROLES = ("DistrictManager", "CirculationDirector")
READ_ROLES = ("ServiceRep", "DistrictManager", "CirculationDirector")
RACK_STATUSES = ("ACTIVE", "INACTIVE")


# --- RackLocation -----------------------------------------------------------

@bp.post("/api/rack-locations")
def create_rack():
    require_roles(*DIST_ROLES)
    b = body()
    location_name = req_str(b, "location_name")
    address = req_str(b, "address")
    price = req_int(b, "price_per_copy_cents", min_v=1)
    rec = create_rec(store.racks, {
        "location_name": location_name,
        "address": address,
        "price_per_copy_cents": price,
        "status": "ACTIVE",
    })
    return ok_obj(ser_rack(rec), 201)


@bp.get("/api/rack-locations")
def list_racks():
    require_roles(*READ_ROLES)
    recs = by_created(store.racks.values())
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_rack)


@bp.get("/api/rack-locations/<rid>")
def get_rack(rid):
    require_roles(*READ_ROLES)
    return ok_obj(ser_rack(domain.fetch(store.racks, rid)))


@bp.patch("/api/rack-locations/<rid>")
def update_rack(rid):
    require_roles(*DIST_ROLES)
    rack = domain.fetch(store.racks, rid)
    b = body()
    if "status" in b:
        status = b.get("status")
        if not isinstance(status, str) or status not in RACK_STATUSES:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "status must be ACTIVE or INACTIVE")
        if status != rack["status"]:
            if rack["status"] == "ACTIVE" and status == "INACTIVE":
                rack["status"] = "INACTIVE"
                bump(rack)
            else:
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Rack status transition not permitted")
    return ok_obj(ser_rack(rack))


# --- RackSalesReport --------------------------------------------------------

@bp.post("/api/rack-sales-reports")
def create_report():
    require_roles(*DIST_ROLES)
    b = body()
    rack_location_id = req_str(b, "rack_location_id")
    week_start = req_date(b, "week_start_date")
    copies_delivered = req_int(b, "copies_delivered", min_v=0)
    copies_returned = req_int(b, "copies_returned", min_v=0)
    reported = opt_int(b, "reported_sold_copies", min_v=0)
    if week_start.weekday() != 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "week_start_date must be a Monday")
    if copies_returned > copies_delivered:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "copies_returned must not exceed copies_delivered")
    rack = domain.fetch(store.racks, rack_location_id)
    if rack["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Rack location is INACTIVE; new reports rejected")
    for r in store.rack_reports.values():
        if r["rack_location_id"] == rack["id"] and r["week_start_date"] == week_start:
            raise ApiError("ERR_REPORT_WEEK_CONFLICT", 409,
                           "A report already exists for this rack and week")
    rec = create_rec(store.rack_reports, {
        "rack_location_id": rack["id"],
        "week_start_date": week_start,
        "copies_delivered": copies_delivered,
        "copies_returned": copies_returned,
        "reported_sold_copies": reported,
        "status": "DRAFT",
    })
    return ok_obj(ser_rack_report(rec), 201)


@bp.get("/api/rack-sales-reports")
def list_reports():
    require_roles(*READ_ROLES)
    recs = by_created(store.rack_reports.values())
    rack_location_id = request.args.get("rack_location_id")
    if rack_location_id is not None:
        recs = [r for r in recs if r["rack_location_id"] == rack_location_id]
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_rack_report)


@bp.get("/api/rack-sales-reports/<rid>")
def get_report(rid):
    require_roles(*READ_ROLES)
    return ok_obj(ser_rack_report(domain.fetch(store.rack_reports, rid)))


@bp.patch("/api/rack-sales-reports/<rid>")
def update_report(rid):
    require_roles(*DIST_ROLES)
    report = domain.fetch(store.rack_reports, rid)
    b = body()
    new_delivered = opt_int(b, "copies_delivered", min_v=0) \
        if "copies_delivered" in b else None
    new_returned = opt_int(b, "copies_returned", min_v=0) \
        if "copies_returned" in b else None
    if report["status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError("ERR_REPORT_NOT_EDITABLE", 409,
                       "Report is editable only in DRAFT or DISPUTED")
    if report["status"] == "DISPUTED" and new_delivered is not None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "copies_delivered is frozen once submitted; only copies_returned is correctable in DISPUTED")
    eff_delivered = report["copies_delivered"] if new_delivered is None else new_delivered
    eff_returned = report["copies_returned"] if new_returned is None else new_returned
    if eff_returned > eff_delivered:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "copies_returned must not exceed copies_delivered")
    changed = False
    if new_delivered is not None and new_delivered != report["copies_delivered"]:
        report["copies_delivered"] = new_delivered
        changed = True
    if new_returned is not None and new_returned != report["copies_returned"]:
        report["copies_returned"] = new_returned
        changed = True
    if changed:
        bump(report)
    return ok_obj(ser_rack_report(report))


@bp.post("/api/rack-sales-reports/<rid>/submit")
def submit_report(rid):
    require_roles(*DIST_ROLES)
    report = domain.fetch(store.rack_reports, rid)
    if report["status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError("ERR_REPORT_NOT_SUBMITTABLE", 409,
                       "submit requires status DRAFT or DISPUTED")
    # copies_sold / amount_due_cents / variance_* are computed from the stored
    # counts at serialization; submit freezes copies_delivered via PATCH rules.
    report["status"] = "SUBMITTED"
    bump(report)
    return ok_obj(ser_rack_report(report))


@bp.post("/api/rack-sales-reports/<rid>/reconcile")
def reconcile_report(rid):
    require_roles("CirculationDirector")
    report = domain.fetch(store.rack_reports, rid)
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_NOT_RECONCILABLE", 409,
                       "reconcile requires status SUBMITTED")
    report["status"] = "RECONCILED"
    bump(report)
    return ok_obj(ser_rack_report(report))


@bp.post("/api/rack-sales-reports/<rid>/dispute")
def dispute_report(rid):
    require_roles("CirculationDirector")
    report = domain.fetch(store.rack_reports, rid)
    body()  # optional reason; accepted and intentionally not persisted
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "dispute requires status SUBMITTED")
    report["status"] = "DISPUTED"
    bump(report)
    return ok_obj(ser_rack_report(report))
