"""Shared registries: departments, licences, ingest runners and members."""

from flask import Blueprint, request

import calc
import services
from calc import D, q2
from common import find
from core import (
    body,
    caller,
    db,
    err,
    new_row,
    now,
    ok,
    opt_bool,
    opt_enum,
    opt_int,
    opt_str,
    page,
    req_enum,
    req_num,
    req_str,
    touch,
)

bp = Blueprint("registry", __name__)

POSTURES = ("OPEN", "RESTRICTED", "SUSPENDED")
PERMISSION_CLASSES = ("UNRESTRICTED", "ATTRIBUTION", "COPYLEFT", "NONCOMMERCIAL")


def _bool_arg(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    err("ERR_INVALID_REQUEST", "%s must be a boolean." % name)


# --------------------------------------------------------------------------
# Departments
# --------------------------------------------------------------------------
@bp.post("/departments")
def create_department():
    caller("PortalAdmin")
    data = body()
    name = req_str(data, "name")
    code = req_str(data, "code")
    contact_email = req_str(data, "contact_email")
    for existing in db.departments.values():
        if existing["code"] == code:
            err("ERR_DUPLICATE_DEPARTMENT_CODE", "Department code %s already exists." % code)
    row = new_row()
    row.update(
        {
            "name": name,
            "code": code,
            "contact_email": contact_email,
            "credits_issued_units": calc.ZERO,
            "credit_balance_units": calc.ZERO,
            "credits_escrowed_units": calc.ZERO,
            "credits_consumed_units": calc.ZERO,
            "breached_dataset_count": 0,
            "stale_dataset_count": 0,
            "remediation_dataset_count": 0,
            "overdue_correction_count": 0,
            "risk_points": 0,
            "compliance_posture": "OPEN",
        }
    )
    db.departments[row["id"]] = row
    return ok(services.department_out(row), 201)


@bp.get("/departments")
def list_departments():
    caller()
    code = request.args.get("code")
    posture = request.args.get("compliance_posture")
    if posture is not None and posture not in POSTURES:
        err("ERR_INVALID_REQUEST", "compliance_posture must be one of %s." % ", ".join(POSTURES))
    rows = list(db.departments.values())
    if code is not None:
        rows = [r for r in rows if r["code"] == code]
    if posture is not None:
        rows = [r for r in rows if r["compliance_posture"] == posture]
    return page(rows, services.department_out)


@bp.get("/departments/<department_id>")
def get_department(department_id):
    caller()
    return ok(services.department_out(find("departments", department_id)))


@bp.get("/departments/<department_id>/scorecard")
def department_scorecard(department_id):
    caller("DataCoordinator", "PortalAdmin")
    dept = find("departments", department_id)
    issued = D(dept["credits_issued_units"])
    balanced = (
        q2(
            D(dept["credit_balance_units"])
            + D(dept["credits_escrowed_units"])
            + D(dept["credits_consumed_units"])
        )
        == q2(issued)
    )
    return ok(
        {
            "department_id": dept["id"],
            "compliance_posture": dept["compliance_posture"],
            "risk_points": dept["risk_points"],
            "breached_dataset_count": dept["breached_dataset_count"],
            "stale_dataset_count": dept["stale_dataset_count"],
            "remediation_dataset_count": dept["remediation_dataset_count"],
            "overdue_correction_count": dept["overdue_correction_count"],
            "credits_issued_units": services.num(dept["credits_issued_units"]),
            "credit_balance_units": services.num(dept["credit_balance_units"]),
            "credits_escrowed_units": services.num(dept["credits_escrowed_units"]),
            "credits_consumed_units": services.num(dept["credits_consumed_units"]),
            "credit_ledger_balanced": balanced,
        }
    )


@bp.post("/departments/<department_id>/credit-grants")
def grant_credits(department_id):
    caller("PortalAdmin")
    dept = find("departments", department_id)
    data = body()
    units = req_num(data, "credit_units")
    if units <= 0:
        err("ERR_INVALID_REQUEST", "credit_units must be strictly greater than zero.")
    opt_str(data, "memo")
    dept["credits_issued_units"] = q2(D(dept["credits_issued_units"]) + units)
    dept["credit_balance_units"] = q2(D(dept["credit_balance_units"]) + units)
    touch(dept)
    return ok(services.department_out(dept))


# --------------------------------------------------------------------------
# Licence terms
# --------------------------------------------------------------------------
def _permission_class(attribution_required, commercial_use_allowed, share_alike):
    if not attribution_required and commercial_use_allowed and not share_alike:
        return "UNRESTRICTED"
    if attribution_required and commercial_use_allowed and not share_alike:
        return "ATTRIBUTION"
    if share_alike:
        return "COPYLEFT"
    return "NONCOMMERCIAL"


@bp.post("/licenses")
def create_license():
    caller("PortalAdmin")
    data = body()
    code = req_str(data, "code")
    name = req_str(data, "name")
    attribution_required = opt_bool(data, "attribution_required", False)
    commercial_use_allowed = opt_bool(data, "commercial_use_allowed", True)
    share_alike = opt_bool(data, "share_alike", False)
    template = opt_str(data, "attribution_text_template")
    for existing in db.licenses.values():
        if existing["code"] == code:
            err("ERR_DUPLICATE_LICENSE_CODE", "Licence code %s already exists." % code)
    row = new_row()
    row.update(
        {
            "code": code,
            "name": name,
            "attribution_required": attribution_required,
            "commercial_use_allowed": commercial_use_allowed,
            "share_alike": share_alike,
            "attribution_text_template": template,
            "reuse_permission_class": _permission_class(
                attribution_required, commercial_use_allowed, share_alike
            ),
            "retired": False,
        }
    )
    db.licenses[row["id"]] = row
    return ok(services.license_out(row), 201)


@bp.get("/licenses")
def list_licenses():
    caller()
    code = request.args.get("code")
    permission = request.args.get("reuse_permission_class")
    if permission is not None and permission not in PERMISSION_CLASSES:
        err(
            "ERR_INVALID_REQUEST",
            "reuse_permission_class must be one of %s." % ", ".join(PERMISSION_CLASSES),
        )
    retired = _bool_arg("retired")
    rows = list(db.licenses.values())
    if code is not None:
        rows = [r for r in rows if r["code"] == code]
    if permission is not None:
        rows = [r for r in rows if r["reuse_permission_class"] == permission]
    if retired is not None:
        rows = [r for r in rows if r["retired"] == retired]
    return page(rows, services.license_out)


@bp.get("/licenses/<license_id>")
def get_license(license_id):
    caller()
    return ok(services.license_out(find("licenses", license_id)))


@bp.post("/licenses/<license_id>/retire")
def retire_license(license_id):
    caller("PortalAdmin")
    row = find("licenses", license_id)
    row["retired"] = True
    touch(row)
    return ok(services.license_out(row))


# --------------------------------------------------------------------------
# Ingest runners
# --------------------------------------------------------------------------
@bp.post("/ingest-runners")
def create_runner():
    caller("PortalAdmin")
    data = body()
    name = req_str(data, "name")
    cooldown = opt_int(data, "cooldown_minutes", 0, 120, 15)
    row = new_row()
    row.update(
        {
            "name": name,
            "cooldown_minutes": cooldown,
            "armed_window_count": 0,
            "status": "ACTIVE",
        }
    )
    db.runners[row["id"]] = row
    return ok(services.runner_out(row), 201)


@bp.get("/ingest-runners")
def list_runners():
    caller("DataCoordinator", "PortalAdmin")
    status = request.args.get("status")
    if status is not None and status not in calc.RUNNER_STATUSES:
        err(
            "ERR_INVALID_REQUEST",
            "status must be one of %s." % ", ".join(calc.RUNNER_STATUSES),
        )
    rows = list(db.runners.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(rows, services.runner_out)


@bp.get("/ingest-runners/<runner_id>")
def get_runner(runner_id):
    caller("DataCoordinator", "PortalAdmin")
    return ok(services.runner_out(find("runners", runner_id)))


@bp.patch("/ingest-runners/<runner_id>")
def update_runner(runner_id):
    caller("PortalAdmin")
    row = find("runners", runner_id)
    data = body()
    status = opt_enum(data, "status", calc.RUNNER_STATUSES)
    cooldown = opt_int(data, "cooldown_minutes", 0, 120)
    if status is not None:
        row["status"] = status
    if cooldown is not None:
        row["cooldown_minutes"] = cooldown
    touch(row)
    return ok(services.runner_out(row))


# --------------------------------------------------------------------------
# Community members
# --------------------------------------------------------------------------
@bp.post("/members/register")
def register_member():
    caller("Anonymous", "PortalAdmin")
    data = body()
    email = req_str(data, "email")
    display_name = req_str(data, "display_name")
    organization = opt_str(data, "organization")
    for existing in db.members.values():
        if existing["email"] == email:
            err("ERR_DUPLICATE_MEMBER_EMAIL", "Member email %s already exists." % email)
    row = new_row()
    row.update(
        {
            "email": email,
            "display_name": display_name,
            "organization": organization,
            "accepted_issue_count": 0,
            "rejected_issue_count": 0,
            "approved_showcase_count": 0,
            "last_credited_at": row["created_at"],
            "decay_epochs": 0,
            "reputation_score": D("50.00"),
            "vote_weight": 2,
            "status": "ACTIVE",
        }
    )
    db.members[row["id"]] = row
    return ok(services.member_out(row), 201)


@bp.get("/members/<member_id>")
def get_member(member_id):
    caller("CommunityMember", "DataCoordinator", "PortalAdmin")
    row = find("members", member_id)
    services.recompute_member(row, mutate=False)
    return ok(services.member_out(row))
