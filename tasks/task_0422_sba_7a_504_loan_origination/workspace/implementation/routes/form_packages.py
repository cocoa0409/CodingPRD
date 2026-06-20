"""FormPackage endpoints — PRD §3.3, §4. Branching review state machine."""
from flask import Blueprint

import db
import errors
from middleware import get_user_context, require_roles
from response import object_response, array_response
from services.common import (
    serialize, get_json_body, require_string, optional_bool,
    paginate, sort_by_created,
)

bp = Blueprint("form_packages", __name__)

READ_ROLES = ["SbaOfficer", "LoanOfficer", "CreditApprover"]


@bp.post("/sba/form-packages")
def create_form_package():
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    body = get_json_body()
    application_id = require_string(body, "application_id")
    f1919 = optional_bool(body, "form_1919_complete", default=False)
    f1920 = optional_bool(body, "form_1920_complete", default=False)
    character = optional_bool(body, "character_cleared", default=False)
    with db.LOCK:
        if application_id not in db.applications:
            raise errors.invalid_request("application_id does not reference an existing Application")
        rec = db.init_record({
            "application_id": application_id,
            "form_1919_complete": f1919,
            "form_1920_complete": f1920,
            "character_cleared": character,
            "status": "INCOMPLETE",
        })
        db.form_packages[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/sba/applications/<application_id>/form-packages")
def list_form_packages(application_id):
    user_id, role = get_user_context()
    require_roles(role, READ_ROLES)
    with db.LOCK:
        if application_id not in db.applications:
            raise errors.not_found("Application not found")
        items = [f for f in db.form_packages.values() if f["application_id"] == application_id]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


def _get_fp_or_404(form_package_id):
    rec = db.form_packages.get(form_package_id)
    if rec is None:
        raise errors.not_found("FormPackage not found")
    return rec


@bp.post("/sba/form-packages/<form_package_id>/submit")
def submit_form_package(form_package_id):
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    with db.LOCK:
        fp = _get_fp_or_404(form_package_id)
        if fp["status"] != "INCOMPLETE":
            raise errors.invalid_state("FormPackage is not INCOMPLETE")
        if not (fp["form_1919_complete"] and fp["form_1920_complete"]):
            raise errors.err(errors.ERR_FORM_INCOMPLETE, 409,
                             "Form 1919 and 1920 must both be complete")
        fp["status"] = "SUBMITTED"
        db.touch(fp)
        return object_response(serialize(fp), 200)


@bp.post("/sba/form-packages/<form_package_id>/review")
def review_form_package(form_package_id):
    user_id, role = get_user_context()
    require_roles(role, ["CreditApprover"])
    with db.LOCK:
        fp = _get_fp_or_404(form_package_id)
        if fp["status"] != "SUBMITTED":
            raise errors.invalid_state("FormPackage is not SUBMITTED")
        # Branch on character_cleared.
        if fp["character_cleared"]:
            fp["status"] = "CLEARED"
        else:
            fp["status"] = "FLAGGED"
        db.touch(fp)
        return object_response(serialize(fp), 200)


@bp.post("/sba/form-packages/<form_package_id>/reopen")
def reopen_form_package(form_package_id):
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    body = get_json_body()
    with db.LOCK:
        fp = _get_fp_or_404(form_package_id)
        if fp["status"] != "FLAGGED":
            raise errors.invalid_state("FormPackage is not FLAGGED")
        fp["status"] = "INCOMPLETE"
        # Optionally accept an updated character_cleared value.
        if "character_cleared" in body and body["character_cleared"] is not None:
            val = body["character_cleared"]
            if not isinstance(val, bool):
                raise errors.invalid_request("character_cleared must be a boolean")
            fp["character_cleared"] = val
        db.touch(fp)
        return object_response(serialize(fp), 200)
