"""CaProject endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_SOV_SUM_MISMATCH,
    ERR_PUNCH_INSPECTION_REQUIRED,
    ERR_PROJECT_NOT_ACTIVE,
    ERR_PROJECT_NOT_SUBSTANTIAL,
    ERR_PROJECT_NOT_FINAL,
    ERR_OPEN_PUNCH_ITEMS_REMAIN,
    ERR_RECORD_DOCUMENTS_INCOMPLETE,
    ERR_OPEN_PAYMENT_APPLICATIONS,
    ERR_OPEN_INVOICES,
)
from middleware import get_user_context, require_role, get_body
from response import success_object, success_list
from services import calcs
from services.helpers import (
    base_entity, touch, paginate, get_project,
    req_str, req_int, req_date, opt_int, opt_enum, invalid,
)

bp = Blueprint("projects", __name__)

ALL_ROLES = ("FirmAdmin", "ArchitectCA", "Contractor", "Owner")

DOC_TYPES = ("AS_BUILT", "OM_MANUAL", "WARRANTY", "TEST_REPORT")


@bp.post("/ca/projects")
def create_project():
    _, role = get_user_context()
    require_role(role, ("FirmAdmin",))
    body = get_body(required=True)

    name = req_str(body, "name")
    owner_user_id = req_str(body, "owner_user_id")
    contractor_user_id = req_str(body, "contractor_user_id")
    original_sum = req_int(body, "original_contract_sum_cents")
    if original_sum <= 0:
        invalid("original_contract_sum_cents must be > 0")

    sov_lines = body.get("sov_lines")
    if not isinstance(sov_lines, list) or len(sov_lines) == 0:
        invalid("sov_lines must be a non-empty array")
    seen_codes = set()
    total = 0
    for entry in sov_lines:
        if not isinstance(entry, dict):
            invalid("each sov_lines entry must be an object")
        code = entry.get("line_code")
        desc = entry.get("description")
        value = entry.get("scheduled_value_cents")
        if not isinstance(code, str) or not code:
            invalid("each sov_lines entry requires a string line_code")
        if code in seen_codes:
            invalid("sov_lines line_code values must be unique within the project")
        seen_codes.add(code)
        if not isinstance(desc, str):
            invalid("each sov_lines entry requires a string description")
        if not (isinstance(value, int) and not isinstance(value, bool)) or value <= 0:
            invalid("each sov_lines entry requires scheduled_value_cents > 0")
        total += value

    base_date = req_date(body, "base_substantial_completion_date")
    daily_rate = req_int(body, "daily_extension_rate_cents")
    if daily_rate <= 0:
        invalid("daily_extension_rate_cents must be > 0")
    monthly_rate = req_int(body, "monthly_extension_rate_cents")
    if monthly_rate <= 0:
        invalid("monthly_extension_rate_cents must be > 0")
    billing_method = opt_enum(body, "billing_method", ("PER_DIEM_PRORATED", "WHOLE_MONTH"))
    retainage_mode = opt_enum(body, "retainage_mode", ("TIERED_MARGINAL", "REDUCTION_AT_HALFWAY"))
    grace_days = opt_int(body, "grace_days", 0)
    if grace_days < 0:
        invalid("grace_days must be >= 0")
    rw_submittal = opt_int(body, "review_window_days_submittal", 10)
    if rw_submittal < 1:
        invalid("review_window_days_submittal must be >= 1")
    rw_rfi = opt_int(body, "review_window_days_rfi", 7)
    if rw_rfi < 1:
        invalid("review_window_days_rfi must be >= 1")
    fr_window = opt_int(body, "field_report_window_days", 3)
    if fr_window < 1:
        invalid("field_report_window_days must be >= 1")

    # schedule-of-values integrity (ERR_SOV_SUM_MISMATCH)
    if total != original_sum:
        raise ApiError(
            ERR_SOV_SUM_MISMATCH,
            "Sum of sov_lines scheduled values does not equal original_contract_sum_cents",
            422,
        )

    project = base_entity()
    project.update({
        "name": name,
        "owner_user_id": owner_user_id,
        "contractor_user_id": contractor_user_id,
        "original_contract_sum_cents": original_sum,
        "sov_lines": [
            {
                "line_code": e["line_code"],
                "description": e["description"],
                "scheduled_value_cents": e["scheduled_value_cents"],
            }
            for e in sov_lines
        ],
        "base_substantial_completion_date": base_date,
        "adjusted_substantial_completion_date": base_date,
        "adjusted_contract_sum_cents": original_sum,
        "daily_extension_rate_cents": daily_rate,
        "monthly_extension_rate_cents": monthly_rate,
        "billing_method": billing_method,
        "retainage_mode": retainage_mode,
        "grace_days": grace_days,
        "review_window_days_submittal": rw_submittal,
        "review_window_days_rfi": rw_rfi,
        "field_report_window_days": fr_window,
        "excusable_delay_days": 0,
        "certified_to_date_cents": 0,
        "retainage_held_cents": 0,
        "substantial_completion_actual_date": None,
        "ca_posture": "NORMAL",
        "status": "SETUP",
    })
    db.projects[project["id"]] = project
    return success_object(project, 201)


@bp.get("/ca/projects")
def list_projects():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.projects.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    posture = request.args.get("posture")
    if posture is not None:
        items = [p for p in items if p["ca_posture"] == posture]
    owner = request.args.get("owner_user_id")
    if owner is not None:
        items = [p for p in items if p["owner_user_id"] == owner]
    contractor = request.args.get("contractor_user_id")
    if contractor is not None:
        items = [p for p in items if p["contractor_user_id"] == contractor]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/ca/projects/<pid>")
def get_one_project(pid):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success_object(get_project(pid))


@bp.post("/ca/projects/<pid>/activate")
def activate_project(pid):
    _, role = get_user_context()
    require_role(role, ("FirmAdmin",))
    project = get_project(pid)
    if project["status"] != "SETUP":
        raise ApiError(
            ERR_PROJECT_NOT_ACTIVE,
            "activate requires the project in SETUP",
            409,
        )
    project["status"] = "ACTIVE"
    calcs.recompute_posture(project)
    touch(project)
    return success_object(project)


@bp.post("/ca/projects/<pid>/achieve-substantial-completion")
def achieve_substantial_completion(pid):
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    project = get_project(pid)
    if project["status"] != "ACTIVE":
        raise ApiError(ERR_PROJECT_NOT_ACTIVE, "achieve-substantial-completion requires the project in ACTIVE", 409)
    has_punch = any(
        v["project_id"] == pid and v["purpose"] == "PUNCH_INSPECTION" and v["status"] == "REPORT_ISSUED"
        for v in db.site_visits.values()
    )
    if not has_punch:
        raise ApiError(
            ERR_PUNCH_INSPECTION_REQUIRED,
            "No REPORT_ISSUED PUNCH_INSPECTION visit exists for the project",
            409,
        )
    project["substantial_completion_actual_date"] = db.today()
    project["status"] = "SUBSTANTIAL_COMPLETION_ACHIEVED"
    calcs.recompute_posture(project)
    touch(project)
    # Recompute every DRAFT invoice with horizon_end fixed to the actual date.
    calcs.recompute_draft_invoices(project)
    return success_object(project)


@bp.post("/ca/projects/<pid>/achieve-final-completion")
def achieve_final_completion(pid):
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    project = get_project(pid)
    if project["status"] != "SUBSTANTIAL_COMPLETION_ACHIEVED":
        raise ApiError(
            ERR_PROJECT_NOT_SUBSTANTIAL,
            "achieve-final-completion requires SUBSTANTIAL_COMPLETION_ACHIEVED",
            409,
        )
    open_items = any(
        i["project_id"] == pid and i["status"] in ("OPEN", "CLAIMED_COMPLETE", "REOPENED")
        for i in db.punch_list_items.values()
    )
    if open_items:
        raise ApiError(ERR_OPEN_PUNCH_ITEMS_REMAIN, "Punch items remain open on the project", 409)
    for dt in DOC_TYPES:
        accepted = any(
            d["project_id"] == pid and d["doc_type"] == dt and d["status"] == "ACCEPTED"
            for d in db.record_documents.values()
        )
        if not accepted:
            raise ApiError(
                ERR_RECORD_DOCUMENTS_INCOMPLETE,
                "Fewer than four doc types have an ACCEPTED record document",
                409,
            )
    project["status"] = "FINAL_COMPLETION_ACHIEVED"
    touch(project)
    return success_object(project)


@bp.post("/ca/projects/<pid>/close")
def close_project(pid):
    _, role = get_user_context()
    require_role(role, ("FirmAdmin",))
    project = get_project(pid)
    if project["status"] != "FINAL_COMPLETION_ACHIEVED":
        raise ApiError(ERR_PROJECT_NOT_FINAL, "close requires FINAL_COMPLETION_ACHIEVED", 409)
    open_apps = any(
        a["project_id"] == pid and a["status"] in ("SUBMITTED", "REJECTED")
        for a in db.payment_applications.values()
    )
    if open_apps:
        raise ApiError(ERR_OPEN_PAYMENT_APPLICATIONS, "Payment applications remain open on the project", 409)
    open_invs = any(
        i["project_id"] == pid and i["status"] in ("DRAFT", "ISSUED", "OWNER_APPROVED", "DISPUTED")
        for i in db.invoices.values()
    )
    if open_invs:
        raise ApiError(ERR_OPEN_INVOICES, "Invoices remain open on the project", 409)
    project["status"] = "CLOSED"
    touch(project)
    return success_object(project)
