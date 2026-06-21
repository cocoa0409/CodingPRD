"""CollateralItem endpoints — PRD §3.2, §4."""
from flask import Blueprint

import db
import errors
from middleware import get_user_context, require_roles
from response import object_response, array_response
from services import calculations as calc
from services.common import (
    serialize, get_json_body, require_string, require_positive_int,
    require_enum, optional_nonneg_int, paginate, sort_by_created,
)

bp = Blueprint("collateral", __name__)

READ_ROLES = ["SbaOfficer", "LoanOfficer", "CreditApprover"]
ASSET_TYPES = {"REAL_ESTATE", "EQUIPMENT", "INVENTORY", "RECEIVABLES"}


@bp.post("/sba/collateral")
def create_collateral():
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    body = get_json_body()
    application_id = require_string(body, "application_id")
    asset_type = require_enum(body, "asset_type", ASSET_TYPES)
    appraised = require_positive_int(body, "appraised_value_cents")
    prior_lien = optional_nonneg_int(body, "prior_lien_cents", default=0)
    with db.LOCK:
        app = db.applications.get(application_id)
        if app is None:
            raise errors.invalid_request("application_id does not reference an existing Application")
        # PRD §3.2: collateral may be added while DRAFT, UNDERWRITING, or REVISION.
        if app["status"] not in ("DRAFT", "UNDERWRITING", "REVISION"):
            raise errors.invalid_state("Application is not in DRAFT/UNDERWRITING/REVISION")
        discounted = calc.collateral_item_discounted_value(asset_type, appraised, prior_lien)
        rec = db.init_record({
            "application_id": application_id,
            "asset_type": asset_type,
            "appraised_value_cents": appraised,
            "prior_lien_cents": prior_lien,
            "discounted_value_cents": discounted,
        })
        db.collateral[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/sba/applications/<application_id>/collateral")
def list_collateral(application_id):
    user_id, role = get_user_context()
    require_roles(role, READ_ROLES)
    with db.LOCK:
        if application_id not in db.applications:
            raise errors.not_found("Application not found")
        items = [c for c in db.collateral.values() if c["application_id"] == application_id]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)
