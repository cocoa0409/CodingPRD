"""Fine routes."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_invalid_state, err_fine_not_waivable, err_write_off_too_early,
    err_invalid_request,
)
from middleware import require_roles, check_applicant_owner
from response import ok_object, ok_list, parse_pagination
from services.serializers import fine_out

bp = Blueprint("fines", __name__)

FINE_READ_ROLES = ("RightsAdmin", "FinanceOfficer", "Applicant")
WAIVABLE_KINDS = {"OVERDUE_MATERIAL", "LOSS"}


def _maybe_restore_standing(fine):
    """When a fine is paid or waived and it was the org's last ASSESSED fine, restore GOOD."""
    org_id = fine["organization_id"]
    any_assessed = any(
        f["organization_id"] == org_id and f["status"] == "ASSESSED"
        for f in db.fines.values()
    )
    if not any_assessed:
        org = db.organizations.get(org_id)
        if org and org["standing"] != "GOOD":
            org["standing"] = "GOOD"
            org["updated_at"] = db.clock_now()
            org["version"] += 1


@bp.get("/licensing/fines/<fine_id>")
def get_fine(fine_id):
    user_id, role = require_roles(*FINE_READ_ROLES)
    f = db.fines.get(fine_id)
    if not f:
        raise err_not_found("Fine not found")
    check_applicant_owner(user_id, role, f["organization_id"])
    return ok_object(fine_out(f))


@bp.get("/licensing/fines")
def list_fines():
    user_id, role = require_roles(*FINE_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.fines.values())
    if role == "Applicant":
        items = [f for f in items if f["organization_id"] == user_id]
    for field in ("organization_id", "status", "fine_kind", "rental_id", "agreement_id"):
        v = request.args.get(field)
        if v is not None:
            items = [f for f in items if f.get(field) == v]
    items.sort(key=lambda f: (f["created_at"], f["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([fine_out(f) for f in page], limit, offset, total)


@bp.post("/licensing/fines/<fine_id>/pay")
def pay_fine(fine_id):
    require_roles("FinanceOfficer")
    f = db.fines.get(fine_id)
    if not f:
        raise err_not_found("Fine not found")
    if f["status"] != "ASSESSED":
        raise err_invalid_state("Fine must be ASSESSED to pay")
    f["status"] = "PAID"
    f["updated_at"] = db.clock_now()
    f["version"] += 1
    _maybe_restore_standing(f)
    return ok_object(fine_out(f))


@bp.post("/licensing/fines/<fine_id>/waive")
def waive_fine(fine_id):
    require_roles("FinanceOfficer")
    f = db.fines.get(fine_id)
    if not f:
        raise err_not_found("Fine not found")
    if f["status"] != "ASSESSED":
        raise err_invalid_state("Fine must be ASSESSED to waive")
    if f["fine_kind"] not in WAIVABLE_KINDS:
        raise err_fine_not_waivable()
    f["status"] = "WAIVED"
    f["updated_at"] = db.clock_now()
    f["version"] += 1
    _maybe_restore_standing(f)
    return ok_object(fine_out(f))


@bp.post("/licensing/fines/<fine_id>/write_off")
def write_off_fine(fine_id):
    require_roles("FinanceOfficer")
    f = db.fines.get(fine_id)
    if not f:
        raise err_not_found("Fine not found")
    if f["status"] != "ASSESSED":
        raise err_invalid_state("Fine must be ASSESSED to write off")
    now = db.clock_now()
    if f["created_at"] > now - timedelta(days=180):
        raise err_write_off_too_early()
    f["status"] = "WRITTEN_OFF"
    f["updated_at"] = now
    f["version"] += 1
    # Write-off does NOT restore standing.
    return ok_object(fine_out(f))
