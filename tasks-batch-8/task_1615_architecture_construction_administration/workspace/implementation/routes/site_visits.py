"""SiteVisit endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_SITE_VISIT_INVALID_STATE,
    ERR_VISIT_DATE_CONFLICT,
)
from middleware import get_user_context, require_role, get_body
from response import success_object, success_list
from services.helpers import (
    base_entity, touch, paginate, get_project, get_site_visit,
    req_str, req_date, opt_enum,
)
from services.lifecycle import require_project_active

bp = Blueprint("site_visits", __name__)

ALL_ROLES = ("FirmAdmin", "ArchitectCA", "Contractor", "Owner")
PURPOSES = ("PROGRESS_OBSERVATION", "PAYMENT_VERIFICATION", "PUNCH_INSPECTION", "FINAL_INSPECTION")


@bp.post("/ca/site-visits")
def create_site_visit():
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    body = get_body(required=True)
    project_id = req_str(body, "project_id")
    visit_date = req_date(body, "visit_date")
    purpose = opt_enum(body, "purpose", PURPOSES)
    performed_by_user_id = req_str(body, "performed_by_user_id")

    project = get_project(project_id)
    require_project_active(project)

    # Visit-date uniqueness: no other non-CANCELLED visit on the same project
    # with the same visit_date (calendar-day equality; CANCELLED releases).
    conflict = any(
        v["project_id"] == project_id
        and v["visit_date"] == visit_date
        and v["status"] in ("SCHEDULED", "PERFORMED", "REPORT_ISSUED")
        for v in db.site_visits.values()
    )
    if conflict:
        raise ApiError(
            ERR_VISIT_DATE_CONFLICT,
            "Another non-CANCELLED visit already occupies the same visit_date on the project",
            409,
        )

    visit = base_entity()
    visit.update({
        "project_id": project_id,
        "visit_date": visit_date,
        "purpose": purpose,
        "performed_by_user_id": performed_by_user_id,
        "performed_at": None,
        "status": "SCHEDULED",
    })
    db.site_visits[visit["id"]] = visit
    return success_object(visit, 201)


@bp.get("/ca/site-visits")
def list_site_visits():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.site_visits.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [v for v in items if v["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    purpose = request.args.get("purpose")
    if purpose is not None:
        items = [v for v in items if v["purpose"] == purpose]
    performer = request.args.get("performed_by_user_id")
    if performer is not None:
        items = [v for v in items if v["performed_by_user_id"] == performer]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/ca/site-visits/<vid>")
def get_one_site_visit(vid):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success_object(get_site_visit(vid))


@bp.post("/ca/site-visits/<vid>/perform")
def perform_site_visit(vid):
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    visit = get_site_visit(vid)
    if visit["status"] != "SCHEDULED":
        raise ApiError(ERR_SITE_VISIT_INVALID_STATE, "visit perform requires SCHEDULED", 409)
    visit["status"] = "PERFORMED"
    visit["performed_at"] = db.now_iso()
    touch(visit)
    return success_object(visit)


@bp.post("/ca/site-visits/<vid>/cancel")
def cancel_site_visit(vid):
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    visit = get_site_visit(vid)
    if visit["status"] != "SCHEDULED":
        raise ApiError(ERR_SITE_VISIT_INVALID_STATE, "visit cancel requires SCHEDULED", 409)
    visit["status"] = "CANCELLED"
    touch(visit)
    return success_object(visit)
