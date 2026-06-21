"""ProceedsLineItem endpoints — PRD §3.2, §4."""
from flask import Blueprint

import db
import errors
from middleware import get_user_context, require_roles
from response import object_response, array_response
from services.common import (
    serialize, get_json_body, require_string, require_positive_int,
    require_enum, paginate, sort_by_created,
)

bp = Blueprint("proceeds", __name__)

READ_ROLES = ["SbaOfficer", "LoanOfficer", "CreditApprover"]
USE_CATEGORIES = {"WORKING_CAPITAL", "EQUIPMENT", "REAL_ESTATE", "REFINANCE", "INVENTORY", "GOODWILL"}
FIXED_ASSET = {"EQUIPMENT", "REAL_ESTATE"}


@bp.post("/sba/proceeds")
def create_proceeds():
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    body = get_json_body()
    application_id = require_string(body, "application_id")
    use_category = require_enum(body, "use_category", USE_CATEGORIES)
    amount = require_positive_int(body, "amount_cents")
    with db.LOCK:
        app = db.applications.get(application_id)
        if app is None:
            raise errors.invalid_request("application_id does not reference an existing Application")
        # PRD §3.2: proceeds added while application is in DRAFT.
        if app["status"] != "DRAFT":
            raise errors.invalid_state("Application is not in DRAFT")
        rec = db.init_record({
            "application_id": application_id,
            "use_category": use_category,
            "amount_cents": amount,
            "is_fixed_asset": use_category in FIXED_ASSET,
        })
        db.proceeds[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/sba/applications/<application_id>/proceeds")
def list_proceeds(application_id):
    user_id, role = get_user_context()
    require_roles(role, READ_ROLES)
    with db.LOCK:
        if application_id not in db.applications:
            raise errors.not_found("Application not found")
        items = [p for p in db.proceeds.values() if p["application_id"] == application_id]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)
