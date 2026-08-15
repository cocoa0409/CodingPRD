"""Licensee endpoints."""
from flask import Blueprint

import common
import db
import errors
import middleware
import response

bp = Blueprint("licensees", __name__)

ALL_READERS = ("LicensingAnalyst", "LegalCounsel", "FinanceOfficer", "Licensee", "IPAdmin")


@bp.post("/licensing/licensees")
def create_licensee():
    middleware.require_role("LicensingAnalyst")
    body = common.get_body()
    common.validate_body(body, [
        ("legal_name", "string", True),
        ("tax_id", "string", True),
        ("contact_email", "string", True),
    ])
    for lic in db.licensees.values():
        if lic["tax_id"] == body["tax_id"]:
            raise errors.err_duplicate_tax_id()
    lic = common.new_resource({
        "legal_name": body["legal_name"],
        "tax_id": body["tax_id"],
        "contact_email": body["contact_email"],
        "status": "ACTIVE",
        "outstanding_balance_cents": 0,
        "credit_balance_cents": 0,
    })
    db.licensees[lic["id"]] = lic
    return response.success_object(lic, 201)


@bp.get("/licensing/licensees")
def list_licensees():
    middleware.require_role("LicensingAnalyst", "LegalCounsel", "FinanceOfficer", "IPAdmin")
    status = common.request.args.get("status")
    items = list(db.licensees.values())
    if status is not None:
        items = [l for l in items if l["status"] == status]
    limit, offset = common.get_pagination()
    page, total = common.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.get("/licensing/licensees/<lid>")
def get_licensee(lid):
    user_id, role = middleware.require_role(*ALL_READERS)
    lic = db.licensees.get(lid)
    if lic is None:
        raise errors.err_licensee_not_found()
    if role == "Licensee" and user_id != lid:
        raise errors.err_not_resource_owner()
    return response.success_object(lic)


@bp.post("/licensing/licensees/<lid>/lifecycle")
def licensee_lifecycle(lid):
    middleware.require_role("LicensingAnalyst")
    lic = db.licensees.get(lid)
    if lic is None:
        raise errors.err_licensee_not_found()
    body = common.get_body()
    common.validate_body(body, [
        ("action", "enum:SUSPEND,REINSTATE,TERMINATE", True),
    ])
    action = body["action"]
    cur = lic["status"]
    ok = (
        (action == "SUSPEND" and cur == "ACTIVE")
        or (action == "REINSTATE" and cur == "SUSPENDED")
        or (action == "TERMINATE" and cur in ("ACTIVE", "SUSPENDED"))
    )
    if not ok:
        raise errors.err_validation(
            f"Action {action} not permitted from status {cur}")
    lic["status"] = {"SUSPEND": "SUSPENDED", "REINSTATE": "ACTIVE",
                     "TERMINATE": "TERMINATED"}[action]
    common.touch(lic)
    return response.success_object(lic)
