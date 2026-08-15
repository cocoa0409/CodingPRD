"""Permit applications: submit, review loop (approve/deny/request-info),
resubmit, and the reverse-reachability list endpoints."""

from flask import Blueprint, request

from auth import require_roles
from db import store, new_record, bump
from errors import err
from response import ok, ok_list, serialize, serialize_list, sort_created
from services import (
    check_display_ownership, check_operator_active, check_operator_exists,
    current_site_plan, planned_hours, provisional_fee_cents,
)
from validation import validate_schema, parse_pagination, paginate

bp = Blueprint("permits", __name__)


def _get_application(app_id):
    app = store.permit_applications.get(app_id)
    if app is None:
        err("ERR_NOT_FOUND", f"permit application {app_id} not found")
    return app


def _event_of(app):
    return store.displays.get(app["display_event_id"])


@bp.post("/pyro/displays/<display_id>/permit-applications")
def create_permit_application(display_id):
    uid, _ = require_roles("Operator")
    vals = validate_schema(request.get_json(silent=True), [
        ("site_plan_id", "str", True, None),
        ("standby_engines", "int", True, None),
    ])
    if vals["standby_engines"] < 1:
        err("ERR_INVALID_QUANTITY", "standby_engines must be at least 1")
    ev = store.displays.get(display_id)
    if ev is None:
        err("ERR_NOT_FOUND", f"display {display_id} not found")
    plan = store.site_plans.get(vals["site_plan_id"])
    if plan is None:
        err("ERR_NOT_FOUND", f"site plan {vals['site_plan_id']} not found")
    check_display_ownership(ev, uid)
    # Tier 7 — on this endpoint the duplicate-application check fires BEFORE
    # the generic event-state check (PRD §2.8).
    if any(a["display_event_id"] == ev["id"] and a["status"] in ("SUBMITTED", "INFO_REQUESTED")
           for a in store.permit_applications.values()):
        err("ERR_DUPLICATE_APPLICATION",
            "a non-terminal permit application already exists for this event")
    if ev["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "event is not DRAFT")
    check_operator_active(uid)
    if current_site_plan(ev) is None:
        err("ERR_INVALID_STATE", "no CURRENT site plan exists for the event")
    if plan["display_event_id"] != ev["id"]:
        err("ERR_SCOPE_MISMATCH", "referenced site plan belongs to another display")
    op = check_operator_exists(uid)
    if not (op["license_valid_from"] <= ev["scheduled_start_at"] <= op["license_expires_at"]):
        err("ERR_LICENSE_EXPIRED", "operator license window does not contain the show date")
    rec = new_record()
    rec.update({
        "display_event_id": ev["id"],
        "site_plan_id": plan["id"],
        "site_plan_version": plan["version"],
        "standby_engines": vals["standby_engines"],
        "planned_hours": planned_hours(ev),
        "provisional_standby_fee_cents": provisional_fee_cents(ev, vals["standby_engines"]),
        "reviewed_by_user_id": None,
        "decision_note": None,
        "revision_count": 0,
        "status": "SUBMITTED",
    })
    store.permit_applications[rec["id"]] = rec
    ev["status"] = "SUBMITTED"
    bump(ev)
    return ok(serialize(rec), 201)


@bp.get("/pyro/displays/<display_id>/permit-applications")
def list_permit_applications_of_display(display_id):
    uid, role = require_roles("Operator", "FireMarshal")
    ev = store.displays.get(display_id)
    if ev is None:
        err("ERR_NOT_FOUND", f"display {display_id} not found")
    if role == "Operator":
        check_display_ownership(ev, uid)
    limit, offset = parse_pagination(request.args)
    recs = sort_created([a for a in store.permit_applications.values()
                         if a["display_event_id"] == display_id])
    return ok_list(serialize_list(paginate(recs, limit, offset)), len(recs),
                   limit, offset)


@bp.get("/pyro/permit-applications/<app_id>")
def get_permit_application(app_id):
    uid, role = require_roles("Operator", "FireMarshal")
    app = _get_application(app_id)
    if role == "Operator":
        ev = _event_of(app)
        if ev is None or ev["operator_id"] != uid:
            err("ERR_FORBIDDEN_OWNERSHIP", "application belongs to another operator")
    return ok(serialize(app))


@bp.get("/pyro/permit-applications")
def list_permit_applications():
    uid, role = require_roles("Operator", "FireMarshal")
    limit, offset = parse_pagination(request.args)
    recs = list(store.permit_applications.values())
    if role == "Operator":
        recs = [a for a in recs
                if (store.displays.get(a["display_event_id"]) or {}).get("operator_id") == uid]
    display_filter = request.args.get("display_event_id")
    if display_filter is not None:
        if role == "Operator":
            ev = store.displays.get(display_filter)
            if ev is not None and ev["operator_id"] != uid:
                err("ERR_FORBIDDEN_OWNERSHIP", "display belongs to another operator")
        recs = [a for a in recs if a["display_event_id"] == display_filter]
    plan_filter = request.args.get("site_plan_id")
    if plan_filter is not None:
        recs = [a for a in recs if a["site_plan_id"] == plan_filter]
    status = request.args.get("status")
    if status is not None:
        recs = [a for a in recs if a["status"] == status]
    recs = sort_created(recs)
    return ok_list(serialize_list(paginate(recs, limit, offset)), len(recs),
                   limit, offset)


def _marshal_decision(app_id, require_note):
    uid, _ = require_roles("FireMarshal")
    spec = [("decision_note", "str", require_note, None)]
    vals = validate_schema(request.get_json(silent=True), spec)
    app = _get_application(app_id)
    if app["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", "application is not SUBMITTED")
    return uid, vals, app


@bp.post("/pyro/permit-applications/<app_id>/approve")
def approve_application(app_id):
    uid, vals, app = _marshal_decision(app_id, require_note=False)
    app["status"] = "APPROVED"
    app["reviewed_by_user_id"] = uid
    app["decision_note"] = vals["decision_note"]
    bump(app)
    ev = _event_of(app)
    if ev is not None and ev["status"] == "SUBMITTED":
        ev["status"] = "APPROVED"
        bump(ev)
    return ok(serialize(app))


@bp.post("/pyro/permit-applications/<app_id>/deny")
def deny_application(app_id):
    uid, vals, app = _marshal_decision(app_id, require_note=True)
    app["status"] = "DENIED"
    app["reviewed_by_user_id"] = uid
    app["decision_note"] = vals["decision_note"]
    bump(app)
    ev = _event_of(app)
    if ev is not None and ev["status"] == "SUBMITTED":
        ev["status"] = "DENIED"
        bump(ev)
    return ok(serialize(app))


@bp.post("/pyro/permit-applications/<app_id>/request-info")
def request_info_application(app_id):
    uid, vals, app = _marshal_decision(app_id, require_note=True)
    app["status"] = "INFO_REQUESTED"
    app["reviewed_by_user_id"] = uid
    app["decision_note"] = vals["decision_note"]
    bump(app)
    ev = _event_of(app)
    if ev is not None and ev["status"] == "SUBMITTED":
        ev["status"] = "REVISION_REQUESTED"
        bump(ev)
    return ok(serialize(app))


@bp.post("/pyro/permit-applications/<app_id>/resubmit")
def resubmit_application(app_id):
    uid, _ = require_roles("Operator")
    vals = validate_schema(request.get_json(silent=True),
                           [("site_plan_id", "str", True, None)])
    app = _get_application(app_id)
    plan = store.site_plans.get(vals["site_plan_id"])
    if plan is None:
        err("ERR_NOT_FOUND", f"site plan {vals['site_plan_id']} not found")
    ev = _event_of(app)
    if ev is None or ev["operator_id"] != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", "application belongs to another operator")
    if app["status"] != "INFO_REQUESTED":
        err("ERR_INVALID_STATE", "application is not INFO_REQUESTED")
    check_operator_active(uid)
    # Foreign plan -> ERR_SCOPE_MISMATCH; merely superseded -> ERR_INVALID_STATE.
    if plan["display_event_id"] != ev["id"]:
        err("ERR_SCOPE_MISMATCH", "referenced site plan belongs to another display")
    if plan["status"] != "CURRENT":
        err("ERR_INVALID_STATE", "referenced site plan is not CURRENT")
    app["status"] = "SUBMITTED"
    app["site_plan_id"] = plan["id"]
    app["site_plan_version"] = plan["version"]
    app["revision_count"] += 1
    bump(app)
    if ev["status"] == "REVISION_REQUESTED":
        ev["status"] = "SUBMITTED"
        bump(ev)
    return ok(serialize(app))
