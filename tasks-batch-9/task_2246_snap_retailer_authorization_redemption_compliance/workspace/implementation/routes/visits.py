"""StoreVisit endpoints."""
from flask import Blueprint

import calc
import serial
import services
from core import (bad_request, db, ensure_object, fail, filter_str, get_body,
                  mark, now, ok, ok_list, opt_str, ordered, paginate, req_dt,
                  req_enum, req_int, require_auth, resolve_body_ref,
                  resolve_path, stamp_new)
from guards import (ADMIN_ANALYST, INSPECTOR_ADMIN, check_visit_scope,
                    validate_inventory_lines)

bp = Blueprint("visits", __name__)

VISIT_TYPES = ("PRE_AUTHORIZATION", "COMPLIANCE", "REVERIFICATION")
VISIT_READ_ROLES = ("FnsAdmin", "FnsAnalyst", "AdminReviewOfficer",
                    "RetailerOwner", "Inspector")
VISIT_LIST_ROLES = ("FnsAdmin", "FnsAnalyst", "AdminReviewOfficer", "Inspector")


@bp.post("/store-visits")
def create_visit():
    require_auth(ADMIN_ANALYST)
    body = get_body()
    ensure_object(body)
    application = resolve_body_ref(body, "application_id", db.applications,
                                  "ERR_APPLICATION_NOT_FOUND")
    inspector = resolve_body_ref(body, "inspector_id", db.inspectors,
                                "ERR_INSPECTOR_NOT_FOUND")
    visit_type = req_enum(body, "visit_type", VISIT_TYPES)
    window_start = req_dt(body, "window_start")
    window_end = req_dt(body, "window_end")
    if application is None:
        bad_request("Field 'application_id' is required.")
    if inspector is None:
        bad_request("Field 'inspector_id' is required.")
    if window_end <= window_start:
        bad_request("Field 'window_end' must be strictly after 'window_start'.")
    minutes = calc.window_minutes(window_start, window_end)
    if calc.visit_conflicts(inspector["id"], window_start, window_end):
        fail("ERR_INSPECTOR_WINDOW_CONFLICT")
    day_total = calc.inspector_day_minutes(inspector["id"], window_start.date())
    if day_total + minutes > inspector["max_daily_minutes"]:
        fail("ERR_INSPECTOR_DAILY_LIMIT_EXCEEDED")
    row = stamp_new({
        "application_id": application["id"],
        "inspector_id": inspector["id"],
        "visit_type": visit_type,
        "window_start": window_start,
        "window_end": window_end,
        "window_minutes": minutes,
        "observed_inventory_lines": None,
        "observed_staple_shelf_linear_feet": None,
        "verified_qualifying_categories": None,
        "verified_perishable_categories": None,
        "verified_criterion_a_pass": None,
        "depth_of_stock_pass": None,
        "shelf_discrepancy_bps": None,
        "shelf_discrepancy_flag": None,
        "findings_submitted_at": None,
        "status": "SCHEDULED",
    })
    db.store_visits[row["id"]] = row
    services.refresh_inspector_minutes(inspector)
    if application["status"] == "SUBMITTED":
        services.update_row(application, {"status": "PENDING_VISIT"})
    services.commit()
    return ok(serial.store_visit(row), 201)


@bp.get("/store-visits/<visit_id>")
def get_visit(visit_id):
    require_auth(VISIT_READ_ROLES)
    row = resolve_path(db.store_visits, visit_id, "ERR_STORE_VISIT_NOT_FOUND")
    return ok(serial.store_visit(row))


@bp.get("/store-visits")
def list_visits():
    require_auth(VISIT_LIST_ROLES)
    rows = ordered(list(db.store_visits.values()))
    for name in ("application_id", "inspector_id", "status", "visit_type"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    data, pagination = paginate(rows, serial.store_visit)
    return ok_list(data, pagination)


@bp.post("/store-visits/<visit_id>/start")
def start_visit(visit_id):
    require_auth(INSPECTOR_ADMIN)
    visit = resolve_path(db.store_visits, visit_id, "ERR_STORE_VISIT_NOT_FOUND")
    check_visit_scope(visit)
    if visit["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE")
    inspector = db.inspectors.get(visit["inspector_id"])
    if inspector is None or inspector["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    if now() < visit["window_start"]:
        fail("ERR_VISIT_WINDOW_NOT_OPEN")
    visit["status"] = "IN_PROGRESS"
    mark(visit)
    services.commit()
    return ok(serial.store_visit(visit))


def _store_of_visit(visit):
    application = db.applications.get(visit["application_id"])
    if application is None:
        return None, None
    return application, db.stores.get(application["store_id"])


def _check_reverification_independence(visit, store):
    if visit["visit_type"] != "REVERIFICATION" or store is None:
        return
    for other in db.store_visits.values():
        if other["id"] == visit["id"]:
            continue
        if other["visit_type"] != "PRE_AUTHORIZATION":
            continue
        if other["status"] != "FINDINGS_SUBMITTED":
            continue
        other_app = db.applications.get(other["application_id"])
        if other_app is None or other_app["store_id"] != store["id"]:
            continue
        if other["inspector_id"] == visit["inspector_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES")


@bp.post("/store-visits/<visit_id>/findings")
def submit_findings(visit_id):
    require_auth(INSPECTOR_ADMIN)
    visit = resolve_path(db.store_visits, visit_id, "ERR_STORE_VISIT_NOT_FOUND")
    check_visit_scope(visit)
    application, store = _store_of_visit(visit)
    _check_reverification_independence(visit, store)
    body = get_body()
    ensure_object(body)
    lines = validate_inventory_lines(body, "observed_inventory_lines")
    shelf_feet = req_int(body, "observed_staple_shelf_linear_feet", minimum=0)
    if visit["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE")
    qualifying, perishable, passes = calc.criterion_a(lines,
                                                     "ONSITE_DEPTH_FIRST")
    depth_pass, discrepancy_bps, discrepancy_flag = calc.depth_of_stock(
        shelf_feet, store)
    visit.update({
        "observed_inventory_lines": lines,
        "observed_staple_shelf_linear_feet": shelf_feet,
        "verified_qualifying_categories": qualifying,
        "verified_perishable_categories": perishable,
        "verified_criterion_a_pass": passes,
        "depth_of_stock_pass": depth_pass,
        "shelf_discrepancy_bps": discrepancy_bps,
        "shelf_discrepancy_flag": discrepancy_flag,
        "findings_submitted_at": now(),
        "status": "FINDINGS_SUBMITTED",
    })
    mark(visit)
    services.refresh_inspector_minutes_by_id(visit["inspector_id"])
    if application is not None and application["status"] == "PENDING_VISIT":
        if passes and not discrepancy_flag:
            services.update_row(application, {
                "status": "UNDER_REVIEW",
                "verified_criterion_pass": True,
                "hold_reason_code": None,
            })
        else:
            hold = ("STAPLE_STOCK_INSUFFICIENT" if not passes
                    else "SHELF_DISCREPANCY")
            services.consume_deficiency_cycle(application, hold,
                                              verified_pass=passes)
    services.commit()
    return ok(serial.store_visit(visit))


@bp.post("/store-visits/<visit_id>/no-access")
def no_access(visit_id):
    require_auth(INSPECTOR_ADMIN)
    visit = resolve_path(db.store_visits, visit_id, "ERR_STORE_VISIT_NOT_FOUND")
    check_visit_scope(visit)
    body = get_body()
    ensure_object(body)
    opt_str(body, "note")
    if visit["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE")
    visit["status"] = "NO_ACCESS"
    mark(visit)
    services.refresh_inspector_minutes_by_id(visit["inspector_id"])
    application = db.applications.get(visit["application_id"])
    if application is not None and application["status"] == "PENDING_VISIT":
        services.consume_deficiency_cycle(application, "NO_ACCESS")
    services.commit()
    return ok(serial.store_visit(visit))


@bp.post("/store-visits/<visit_id>/cancel")
def cancel_visit(visit_id):
    require_auth(ADMIN_ANALYST)
    visit = resolve_path(db.store_visits, visit_id, "ERR_STORE_VISIT_NOT_FOUND")
    body = get_body()
    ensure_object(body)
    opt_str(body, "note")
    if visit["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE")
    visit["status"] = "CANCELLED"
    mark(visit)
    services.refresh_inspector_minutes_by_id(visit["inspector_id"])
    services.commit()
    return ok(serial.store_visit(visit))
