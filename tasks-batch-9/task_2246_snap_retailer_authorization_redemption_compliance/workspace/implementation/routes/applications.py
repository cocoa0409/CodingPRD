"""Application endpoints."""
from flask import Blueprint

import serial
import services
from core import (db, ensure_object, fail, filter_str, get_body, mark, now, ok,
                  ok_list, opt_enum, opt_number, ordered, paginate, req_enum,
                  req_int, req_str, require_auth, resolve_body_ref,
                  resolve_path, stamp_new)
from guards import ADMIN, ADMIN_OWNER, ALL_READ, validate_inventory_lines

bp = Blueprint("applications", __name__)

APPLICATION_TYPES = ("INITIAL", "REAUTHORIZATION_OWNERSHIP_CHANGE", "RENEWAL")
CRITERIA = ("CRITERION_A", "CRITERION_B")
DECISION_OUTCOMES = ("APPROVED", "DENIED")
DECISION_REASON_CODES = ("APPROVED_CRITERION_A", "APPROVED_CRITERION_B",
                         "STAPLE_STOCK_INSUFFICIENT",
                         "DEFICIENCY_CYCLES_EXHAUSTED",
                         "OWNER_PERMANENTLY_DISQUALIFIED",
                         "TRANSFER_CMP_OUTSTANDING", "WITHDRAWN_BY_APPLICANT")
APPLICATION_READ_ROLES = ("FnsAdmin", "FnsAnalyst", "AdminReviewOfficer",
                          "RetailerOwner", "Inspector")


@bp.post("/applications")
def create_application():
    require_auth(ADMIN_OWNER)
    body = get_body()
    ensure_object(body)
    store = resolve_body_ref(body, "store_id", db.stores, "ERR_STORE_NOT_FOUND")
    expected = req_int(body, "expected_store_version")
    application_type = req_enum(body, "application_type", APPLICATION_TYPES)
    claimed_criterion = req_enum(body, "claimed_criterion", CRITERIA)
    lines = validate_inventory_lines(body, "reported_inventory_lines")
    reported_pct = opt_number(body, "reported_staple_sales_pct")
    if store is None:
        req_str(body, "store_id")
    if expected != store["version"]:
        fail("ERR_STALE_STORE_VERSION")
    for other in db.applications.values():
        if other["store_id"] == store["id"] and other["status"] in \
                services.NON_TERMINAL_APPLICATION_STATUSES:
            fail("ERR_APPLICATION_ALREADY_OPEN")
    row = stamp_new({
        "store_id": store["id"],
        "application_type": application_type,
        "claimed_criterion": claimed_criterion,
        "reported_inventory_lines": lines,
        "reported_staple_sales_pct": reported_pct,
        "verified_criterion_pass": None,
        "deficiency_cycle_count": 0,
        "hold_reason_code": None,
        "decision_reason_code": None,
        "submitted_at": None,
        "decided_at": None,
        "status": "DRAFT",
    })
    row.update(services.run_desk_assessment(row))
    db.applications[row["id"]] = row
    mark(store)
    services.commit()
    return ok(serial.application(row), 201)


@bp.get("/applications/<application_id>")
def get_application(application_id):
    require_auth(APPLICATION_READ_ROLES)
    row = resolve_path(db.applications, application_id,
                       "ERR_APPLICATION_NOT_FOUND")
    return ok(serial.application(row))


@bp.get("/applications")
def list_applications():
    require_auth(ALL_READ)
    rows = ordered(list(db.applications.values()))
    for name in ("store_id", "status", "application_type", "claimed_criterion"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    data, pagination = paginate(rows, serial.application)
    return ok_list(data, pagination)


@bp.post("/applications/<application_id>/submit")
def submit_application(application_id):
    require_auth(ADMIN_OWNER)
    app_row = resolve_path(db.applications, application_id,
                           "ERR_APPLICATION_NOT_FOUND")
    store = services.store_of_application(app_row)
    if app_row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    owner = db.owners.get(store["owner_id"]) if store else None
    if owner is not None and owner["status"] == "BARRED":
        fail("ERR_OWNER_BARRED")
    if store["authorization_status"] not in ("NOT_AUTHORIZED", "WITHDRAWN"):
        fail("ERR_INVALID_STATE")
    desk = services.run_desk_assessment(app_row)
    if app_row["claimed_criterion"] == "CRITERION_B":
        if not store["criterion_b_pass"]:
            fail("ERR_CRITERION_B_NOT_MET")
    else:
        if not desk["desk_criterion_pass"]:
            fail("ERR_STAPLE_STOCK_INSUFFICIENT")
    app_row.update(desk)
    app_row["status"] = "SUBMITTED"
    app_row["submitted_at"] = now()
    app_row["hold_reason_code"] = None
    mark(app_row)
    services.commit()
    return ok(serial.application(app_row))


@bp.post("/applications/<application_id>/documents")
def resubmit_documents(application_id):
    require_auth(ADMIN_OWNER)
    app_row = resolve_path(db.applications, application_id,
                           "ERR_APPLICATION_NOT_FOUND")
    body = get_body()
    ensure_object(body)
    lines = validate_inventory_lines(body, "reported_inventory_lines")
    reported_pct = opt_number(body, "reported_staple_sales_pct")
    if app_row["status"] != "PENDING_DOCUMENTS":
        fail("ERR_INVALID_STATE")
    if (app_row.get("deficiency_cycle_count") or 0) > 2:
        fail("ERR_INVALID_STATE")
    app_row["reported_inventory_lines"] = lines
    if "reported_staple_sales_pct" in body:
        app_row["reported_staple_sales_pct"] = reported_pct
    app_row.update(services.run_desk_assessment(app_row))
    app_row["status"] = "SUBMITTED"
    app_row["submitted_at"] = now()
    app_row["hold_reason_code"] = None
    mark(app_row)
    services.commit()
    return ok(serial.application(app_row))


def _latest_findings_visit(application_id):
    rows = [v for v in db.store_visits.values()
            if v["application_id"] == application_id
            and v["status"] == "FINDINGS_SUBMITTED"]
    if not rows:
        return None
    return ordered(rows)[-1]


@bp.post("/applications/<application_id>/decision")
def decide_application(application_id):
    require_auth(ADMIN)
    app_row = resolve_path(db.applications, application_id,
                           "ERR_APPLICATION_NOT_FOUND")
    body = get_body()
    ensure_object(body)
    outcome = req_enum(body, "outcome", DECISION_OUTCOMES)
    reason_code = opt_enum(body, "reason_code", DECISION_REASON_CODES)
    if app_row["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE")
    store = services.store_of_application(app_row)
    if outcome == "APPROVED":
        if not app_row.get("verified_criterion_pass"):
            fail("ERR_INVALID_STATE")
        visit = _latest_findings_visit(app_row["id"])
        if visit is None or not visit.get("depth_of_stock_pass"):
            fail("ERR_DEPTH_OF_STOCK_INSUFFICIENT")
        owner = db.owners.get(store["owner_id"])
        if owner is not None and (owner["permanent_disqualification_count"] or 0) != 0:
            fail("ERR_OWNER_PERMANENTLY_DISQUALIFIED")
        if app_row["application_type"] == "REAUTHORIZATION_OWNERSHIP_CHANGE":
            predecessor = db.stores.get(store.get("predecessor_store_id"))
            if predecessor is not None:
                prior_owner = db.owners.get(predecessor["owner_id"])
                if prior_owner is not None and \
                        (prior_owner["cmp_outstanding_cents"] or 0) != 0:
                    fail("ERR_TRANSFER_CMP_OUTSTANDING")
                if predecessor["owner_id"] == store["owner_id"]:
                    fail("ERR_OWNERSHIP_UNCHANGED")
        app_row["status"] = "APPROVED"
        app_row["decided_at"] = now()
        app_row["decision_reason_code"] = (
            "APPROVED_CRITERION_A"
            if app_row["claimed_criterion"] == "CRITERION_A"
            else "APPROVED_CRITERION_B")
        if not store.get("fns_number"):
            store["fns_number"] = db.next_fns_number()
        store["authorization_status"] = "AUTHORIZED"
        store["authorized_at"] = now()
        mark(store)
    else:
        app_row["status"] = "DENIED"
        app_row["decided_at"] = now()
        app_row["decision_reason_code"] = reason_code
        services.release_reserved_deployments(store)
    mark(app_row)
    services.commit()
    return ok(serial.application(app_row))


@bp.post("/applications/<application_id>/withdraw")
def withdraw_application(application_id):
    require_auth(ADMIN_OWNER)
    app_row = resolve_path(db.applications, application_id,
                           "ERR_APPLICATION_NOT_FOUND")
    if app_row["status"] not in services.NON_TERMINAL_APPLICATION_STATUSES:
        fail("ERR_INVALID_STATE")
    app_row["status"] = "WITHDRAWN"
    app_row["decision_reason_code"] = "WITHDRAWN_BY_APPLICANT"
    mark(app_row)
    inspectors = set()
    for visit in ordered(list(db.store_visits.values())):
        if visit["application_id"] != app_row["id"]:
            continue
        if visit["status"] != "SCHEDULED":
            continue
        visit["status"] = "CANCELLED"
        mark(visit)
        inspectors.add(visit["inspector_id"])
    for inspector_id in inspectors:
        services.refresh_inspector_minutes_by_id(inspector_id)
    services.commit()
    return ok(serial.application(app_row))
