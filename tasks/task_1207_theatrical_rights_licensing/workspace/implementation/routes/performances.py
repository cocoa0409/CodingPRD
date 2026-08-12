"""Performance routes."""
from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_org_suspended,
    err_report_too_early,
)
from middleware import require_roles, check_applicant_owner
from response import ok_object, ok_list, parse_pagination
from services import calculations
from services.serializers import performance_out

bp = Blueprint("performances", __name__)

PERF_READ_ROLES = ("RightsAdmin", "LicensingOfficer", "Applicant", "FinanceOfficer")


@bp.get("/licensing/performances/<performance_id>")
def get_performance(performance_id):
    user_id, role = require_roles(*PERF_READ_ROLES)
    p = db.performances.get(performance_id)
    if not p:
        raise err_not_found("Performance not found")
    if role == "Applicant":
        g = db.agreements[p["agreement_id"]]
        check_applicant_owner(user_id, role, g["organization_id"])
    return ok_object(performance_out(p))


@bp.get("/licensing/performances")
def list_performances():
    user_id, role = require_roles(*PERF_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    items = list(db.performances.values())
    if role == "Applicant":
        items = [p for p in items if db.agreements[p["agreement_id"]]["organization_id"] == user_id]
    if agreement_id is not None:
        items = [p for p in items if p["agreement_id"] == agreement_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([performance_out(p) for p in page], limit, offset, total)


@bp.post("/licensing/performances/<performance_id>/report")
def report_performance(performance_id):
    user_id, role = require_roles("Applicant")
    p = db.performances.get(performance_id)
    if not p:
        raise err_not_found("Performance not found")
    g = db.agreements[p["agreement_id"]]
    check_applicant_owner(user_id, role, g["organization_id"])
    body = request.get_json(silent=True) or {}
    att = body.get("reported_attendance")
    gross = body.get("reported_gross_cents")
    if not isinstance(att, int) or isinstance(att, bool) or att < 0:
        raise err_invalid_request("reported_attendance must be an integer >= 0")
    if not isinstance(gross, int) or isinstance(gross, bool) or gross < 0:
        raise err_invalid_request("reported_gross_cents must be an integer >= 0")
    if p["status"] != "SCHEDULED":
        raise err_invalid_state("Performance must be SCHEDULED to report")
    if g["license_status"] != "ACTIVE":
        raise err_invalid_state("Agreement must be ACTIVE to report")
    # Priority 9: org standing
    org = db.organizations[g["organization_id"]]
    if org["standing"] != "GOOD":
        raise err_org_suspended()
    # Priority 20: report timing
    now = db.clock_now()
    if now < p["performance_at"]:
        raise err_report_too_early()
    p["status"] = "HELD"
    p["gross_reported"] = True
    p["reported_attendance"] = att
    p["reported_gross_cents"] = gross
    title = db.titles[g["title_id"]]
    p["royalty_cents"] = calculations.settled_single_performance_royalty(title, g, p)
    p["updated_at"] = now
    p["version"] += 1
    # Cascade: agreement version bump
    g["version"] += 1
    g["updated_at"] = now
    return ok_object(performance_out(p))


@bp.post("/licensing/performances/<performance_id>/cancel")
def cancel_performance(performance_id):
    user_id, role = require_roles("Applicant")
    p = db.performances.get(performance_id)
    if not p:
        raise err_not_found("Performance not found")
    g = db.agreements[p["agreement_id"]]
    check_applicant_owner(user_id, role, g["organization_id"])
    if p["status"] != "SCHEDULED":
        raise err_invalid_state("Performance must be SCHEDULED to cancel")
    if g["license_status"] != "ACTIVE":
        raise err_invalid_state("Agreement must be ACTIVE")
    now = db.clock_now()
    p["status"] = "CANCELLED"
    # royalty recompute only when agreement still QUOTED
    if g["royalty_mode"] == "QUOTED":
        title = db.titles[g["title_id"]]
        # Recompute this performance's royalty excluding it from contracted count
        remaining = max(1, g["contracted_performance_count"] - 1)
        synthetic_app = {
            "determined_classification": g["classification"],
            "venue_seating_capacity": g["house_seating_capacity"],
            "projected_gross_cents": db.applications[g["application_id"]]["projected_gross_cents"],
            "performance_count": remaining,
        }
        # per-performance royalty under reduced count
        per_perf = calculations.per_performance_royalty(
            title,
            g["classification"],
            g["house_seating_capacity"],
            db.applications[g["application_id"]]["projected_gross_cents"],
            remaining,
        )
        p["royalty_cents"] = per_perf
    p["updated_at"] = now
    p["version"] += 1
    return ok_object(performance_out(p))
