"""LicenseApplication routes."""
from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_referenced_not_found, err_invalid_request, err_invalid_temporal,
    err_invalid_state, err_org_suspended, err_title_withdrawn, err_title_unavailable,
    err_territory_restricted, err_exclusive_run_conflict, err_stale_version,
)
from middleware import require_roles, check_applicant_owner
from response import ok_object, ok_list, parse_pagination
from services import calculations
from services.serializers import application_out, agreement_out, snapshot_out

bp = Blueprint("applications", __name__)

CLASSIFICATIONS = {"AMATEUR", "PROFESSIONAL"}

APP_EDITABLE_FIELDS = (
    "requested_territory_code", "requested_classification", "venue_seating_capacity",
    "ticket_top_price_cents", "performers_compensated", "admission_charged",
    "projected_gross_cents", "performance_count", "first_performance_date",
    "last_performance_date",
)


def _req_int(body, field, minimum=None):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err_invalid_request(f"{field} is required and must be an integer")
    if minimum is not None and v < minimum:
        raise err_invalid_request(f"{field} must be >= {minimum}")
    return v


def _req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise err_invalid_request(f"{field} is required and must be a boolean")
    return v


def _req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise err_invalid_request(f"{field} is required and must be a non-empty string")
    return v


def _compute_and_store_snapshot(app_rec):
    available, br, ba = calculations.compute_availability(
        app_rec["title_id"],
        app_rec["requested_territory_code"],
        app_rec["requested_classification"],
        app_rec["first_performance_date"],
        app_rec["last_performance_date"],
    )
    now = db.clock_now()
    snap = {
        "id": db.new_id(),
        "title_id": app_rec["title_id"],
        "territory_code": app_rec["requested_territory_code"],
        "classification": app_rec["requested_classification"],
        "window_start": app_rec["first_performance_date"],
        "window_end": app_rec["last_performance_date"],
        "available": available,
        "blocking_restriction_ids": br,
        "blocking_agreement_ids": ba,
        "computed_at": now,
        "created_at": now,
        "application_id": app_rec["id"],
        "_seq": db.next_seq(),
    }
    db.availability_snapshots[snap["id"]] = snap
    app_rec["latest_snapshot_id"] = snap["id"]
    return snap


def _validate_application_window(first_dt, last_dt):
    if first_dt is None or last_dt is None:
        raise err_invalid_temporal("first_performance_date and last_performance_date must be valid ISO8601 UTC")
    # PRD §2.4's strict-inequality rule names the `window_start`/`window_end`
    # fields (TerritoryRestriction, LicenseAgreement amendment). The
    # application's first/last performance dates form the requested window and
    # may coincide for a single-show run (the §3.5 performance window is
    # inclusive on both ends), so no strict-inequality check applies here.


@bp.post("/licensing/applications")
def create_application():
    user_id, role = require_roles("Applicant")
    body = request.get_json(silent=True) or {}
    # Priority 3: ownership — Applicant's X-User-ID must equal organization_id.
    organization_id = body.get("organization_id")
    if not isinstance(organization_id, str) or not organization_id:
        raise err_invalid_request("organization_id is required")
    check_applicant_owner(user_id, role, organization_id)
    # Priority 5: body FK existence
    title_id = body.get("title_id")
    if not isinstance(title_id, str) or not title_id:
        raise err_invalid_request("title_id is required")
    title = db.titles.get(title_id)
    org = db.organizations.get(organization_id)
    if not title or not org:
        raise err_referenced_not_found("title_id or organization_id not found")
    # Priority 6: shape/typing
    requested_territory_code = _req_str(body, "requested_territory_code")
    requested_classification = _req_str(body, "requested_classification")
    if requested_classification not in CLASSIFICATIONS:
        raise err_invalid_request("requested_classification must be AMATEUR or PROFESSIONAL")
    venue_seating_capacity = _req_int(body, "venue_seating_capacity", 1)
    ticket_top_price_cents = _req_int(body, "ticket_top_price_cents", 0)
    performers_compensated = _req_bool(body, "performers_compensated")
    admission_charged = _req_bool(body, "admission_charged")
    projected_gross_cents = _req_int(body, "projected_gross_cents", 0)
    performance_count = _req_int(body, "performance_count", 1)
    # Priority 7: temporal
    first_dt = db.parse_ts(body.get("first_performance_date")) if body.get("first_performance_date") is not None else None
    last_dt = db.parse_ts(body.get("last_performance_date")) if body.get("last_performance_date") is not None else None
    _validate_application_window(first_dt, last_dt)
    # Priority 9: org standing
    if org["standing"] != "GOOD":
        raise err_org_suspended()
    # Priority 10: title status
    if title["status"] != "ACTIVE":
        raise err_title_withdrawn()

    now = db.clock_now()
    a = {
        "id": db.new_id(),
        "title_id": title_id,
        "organization_id": organization_id,
        "requested_territory_code": requested_territory_code,
        "requested_classification": requested_classification,
        "venue_seating_capacity": venue_seating_capacity,
        "ticket_top_price_cents": ticket_top_price_cents,
        "performers_compensated": performers_compensated,
        "admission_charged": admission_charged,
        "projected_gross_cents": projected_gross_cents,
        "performance_count": performance_count,
        "first_performance_date": first_dt,
        "last_performance_date": last_dt,
        "determined_classification": None,
        "status": "DRAFT",
        "submitted_at": None,
        "review_round": 0,
        "latest_snapshot_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.applications[a["id"]] = a
    return ok_object(application_out(a), 201)


@bp.get("/licensing/applications/<application_id>")
def get_application(application_id):
    user_id, role = require_roles("RightsAdmin", "LicensingOfficer", "Applicant")
    a = db.applications.get(application_id)
    if not a:
        raise err_not_found("Application not found")
    check_applicant_owner(user_id, role, a["organization_id"])
    return ok_object(application_out(a))


@bp.get("/licensing/applications")
def list_applications():
    user_id, role = require_roles("RightsAdmin", "LicensingOfficer", "Applicant")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    organization_id = request.args.get("organization_id")
    title_id = request.args.get("title_id")
    valid_statuses = {"DRAFT", "SUBMITTED", "UNDER_REVIEW", "RETURNED_FOR_INFO", "APPROVED", "REJECTED"}
    if status is not None and status not in valid_statuses:
        raise err_invalid_request("status filter invalid")
    items = list(db.applications.values())
    if role == "Applicant":
        items = [a for a in items if a["organization_id"] == user_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if organization_id is not None:
        items = [a for a in items if a["organization_id"] == organization_id]
    if title_id is not None:
        items = [a for a in items if a["title_id"] == title_id]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([application_out(a) for a in page], limit, offset, total)


@bp.patch("/licensing/applications/<application_id>")
def edit_application(application_id):
    user_id, role = require_roles("Applicant")
    a = db.applications.get(application_id)
    if not a:
        raise err_not_found("Application not found")
    check_applicant_owner(user_id, role, a["organization_id"])
    if a["status"] not in ("DRAFT", "RETURNED_FOR_INFO"):
        raise err_invalid_state("Only DRAFT or RETURNED_FOR_INFO applications may be edited")
    body = request.get_json(silent=True) or {}
    for field in APP_EDITABLE_FIELDS:
        if field not in body:
            continue
        v = body[field]
        if field == "requested_territory_code":
            if not isinstance(v, str) or not v:
                raise err_invalid_request("requested_territory_code must be a non-empty string")
            a[field] = v
        elif field == "requested_classification":
            if v not in CLASSIFICATIONS:
                raise err_invalid_request("requested_classification must be AMATEUR or PROFESSIONAL")
            a[field] = v
        elif field in ("venue_seating_capacity", "performance_count"):
            if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                raise err_invalid_request(f"{field} must be an integer >= 1")
            a[field] = v
        elif field in ("ticket_top_price_cents", "projected_gross_cents"):
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise err_invalid_request(f"{field} must be an integer >= 0")
            a[field] = v
        elif field in ("performers_compensated", "admission_charged"):
            if not isinstance(v, bool):
                raise err_invalid_request(f"{field} must be a boolean")
            a[field] = v
        elif field in ("first_performance_date", "last_performance_date"):
            dt = db.parse_ts(v)
            if dt is None:
                raise err_invalid_temporal(f"{field} must be a valid ISO8601 UTC datetime")
            a[field] = dt
    _validate_application_window(a["first_performance_date"], a["last_performance_date"])
    a["updated_at"] = db.clock_now()
    a["version"] += 1
    return ok_object(application_out(a))


@bp.post("/licensing/applications/<application_id>/submit")
def submit_application(application_id):
    user_id, role = require_roles("Applicant")
    a = db.applications.get(application_id)
    if not a:
        raise err_not_found("Application not found")
    check_applicant_owner(user_id, role, a["organization_id"])
    if a["status"] not in ("DRAFT", "RETURNED_FOR_INFO"):
        raise err_invalid_state("Application must be DRAFT or RETURNED_FOR_INFO to submit")
    now = db.clock_now()
    a["status"] = "SUBMITTED"
    a["submitted_at"] = now
    _compute_and_store_snapshot(a)
    a["updated_at"] = now
    a["version"] += 1
    return ok_object(application_out(a))


@bp.post("/licensing/applications/<application_id>/begin_review")
def begin_review(application_id):
    require_roles("LicensingOfficer")
    a = db.applications.get(application_id)
    if not a:
        raise err_not_found("Application not found")
    if a["status"] != "SUBMITTED":
        raise err_invalid_state("Application must be SUBMITTED to begin review")
    org = db.organizations[a["organization_id"]]
    a["status"] = "UNDER_REVIEW"
    a["review_round"] += 1
    a["determined_classification"] = calculations.compute_classification(a, org)
    a["updated_at"] = db.clock_now()
    a["version"] += 1
    return ok_object(application_out(a))


@bp.post("/licensing/applications/<application_id>/return_for_info")
def return_for_info(application_id):
    require_roles("LicensingOfficer")
    a = db.applications.get(application_id)
    if not a:
        raise err_not_found("Application not found")
    if a["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Application must be UNDER_REVIEW to return for info")
    a["status"] = "RETURNED_FOR_INFO"
    a["updated_at"] = db.clock_now()
    a["version"] += 1
    return ok_object(application_out(a))


@bp.post("/licensing/applications/<application_id>/approve")
def approve_application(application_id):
    require_roles("LicensingOfficer")
    a = db.applications.get(application_id)
    if not a:
        raise err_not_found("Application not found")
    body = request.get_json(silent=True) or {}
    if a["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Application must be UNDER_REVIEW to approve")
    # Business checks (priority 11) BEFORE OCC (priority 21) per PRD §2.7.
    # 1. Latest snapshot must have available == true
    snap = db.availability_snapshots.get(a.get("latest_snapshot_id"))
    if snap is None or not snap["available"]:
        raise err_title_unavailable()
    # 2. No active restriction covers requested window/territory matching determined classification
    det = a["determined_classification"]
    for r in db.restrictions.values():
        if r["title_id"] != a["title_id"] or not r["active"]:
            continue
        if r["territory_code"] != a["requested_territory_code"]:
            continue
        if r["blocks_classification"] not in (det, "BOTH"):
            continue
        if r["window_start"] <= a["last_performance_date"] and r["window_end"] >= a["first_performance_date"]:
            raise err_territory_restricted()
    # 3. No other ACTIVE exclusive-run agreement overlapping in same territory
    for g in db.agreements.values():
        if g["title_id"] != a["title_id"]:
            continue
        if g["territory_code"] != a["requested_territory_code"]:
            continue
        if g["license_status"] != "ACTIVE":
            continue
        if not g.get("has_exclusive_run"):
            continue
        if g["window_start"] < a["last_performance_date"] and a["first_performance_date"] < g["window_end"]:
            raise err_exclusive_run_conflict()
    # OCC (priority 21)
    expected = body.get("expected_application_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise err_invalid_request("expected_application_version must be an integer")
        if expected != a["version"]:
            raise err_stale_version()

    now = db.clock_now()
    a["status"] = "APPROVED"
    a["updated_at"] = now
    a["version"] += 1

    title = db.titles[a["title_id"]]
    quoted = calculations.quoted_royalty_total(title, a)
    g = {
        "id": db.new_id(),
        "application_id": a["id"],
        "title_id": a["title_id"],
        "organization_id": a["organization_id"],
        "territory_code": a["requested_territory_code"],
        "classification": a["determined_classification"],
        "house_seating_capacity": a["venue_seating_capacity"],
        "contracted_performance_count": a["performance_count"],
        "window_start": a["first_performance_date"],
        "window_end": a["last_performance_date"],
        "royalty_mode": "QUOTED",
        "quoted_royalty_total_cents": quoted,
        "settled_royalty_total_cents": None,
        "royalty_balance_cents": quoted,
        "license_status": "PENDING_PAYMENT",
        "payment_status": "UNPAID",
        "amendment_seq": 0,
        "supersedes_agreement_id": None,
        "has_exclusive_run": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.agreements[g["id"]] = g
    return ok_object(agreement_out(g), 201)


@bp.post("/licensing/applications/<application_id>/reject")
def reject_application(application_id):
    require_roles("LicensingOfficer")
    a = db.applications.get(application_id)
    if not a:
        raise err_not_found("Application not found")
    if a["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Application must be UNDER_REVIEW to reject")
    a["status"] = "REJECTED"
    a["updated_at"] = db.clock_now()
    a["version"] += 1
    return ok_object(application_out(a))


@bp.get("/licensing/applications/<application_id>/availability")
def get_application_availability(application_id):
    user_id, role = require_roles("RightsAdmin", "LicensingOfficer", "Applicant")
    a = db.applications.get(application_id)
    if not a:
        raise err_not_found("Application not found")
    check_applicant_owner(user_id, role, a["organization_id"])
    snap = db.availability_snapshots.get(a.get("latest_snapshot_id"))
    if not snap:
        raise err_not_found("No availability snapshot for application")
    return ok_object(snapshot_out(snap))
