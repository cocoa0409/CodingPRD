from flask import Blueprint, request

import db
import errors
import validate
import serialize
from response import ok_object, ok_array
from middleware import require
from services import lookup

bp = Blueprint("permits", __name__)

PERMIT_TYPES = {"DEATH_CERTIFICATE", "BURIAL_TRANSIT"}


@bp.post("/cases/<case_id>/permits")
@require("Arranger", "Registrar")
def apply_permit(case_id):
    lookup.case(case_id)
    body = validate.get_json()
    permit_type = validate.require_enum(body, "permit_type", PERMIT_TYPES)

    permit = {
        "id": db.new_id(),
        "case_id": case_id,
        "permit_type": permit_type,
        "reference_number": None,
        "status": "APPLIED",
    }
    db.stamp_create(permit)
    db.permits[permit["id"]] = permit
    return ok_object(serialize.permit(permit), 201)


@bp.get("/cases/<case_id>/permits")
@require("Admin", "Arranger", "Registrar")
def list_case_permits(case_id):
    lookup.case(case_id)
    limit, offset = validate.pagination()
    items = [p for p in db.permits.values() if p["case_id"] == case_id]
    window, total = validate.paginate(items, limit, offset)
    return ok_array([serialize.permit(p) for p in window], limit, offset, total)


@bp.get("/permits/<permit_id>")
@require("Admin", "Arranger", "Registrar")
def get_permit(permit_id):
    p = lookup.permit(permit_id)
    return ok_object(serialize.permit(p), 200)


@bp.get("/permits")
@require("Admin", "Arranger", "Registrar")
def list_permits():
    limit, offset = validate.pagination()
    case_id = request.args.get("case_id")
    items = list(db.permits.values())
    if case_id is not None:
        items = [p for p in items if p["case_id"] == case_id]
    window, total = validate.paginate(items, limit, offset)
    return ok_array([serialize.permit(p) for p in window], limit, offset, total)


def _issued_permit_exists(case_id, permit_type):
    for p in db.permits.values():
        if p["case_id"] == case_id and p["permit_type"] == permit_type \
                and p["status"] == "ISSUED":
            return True
    return False


@bp.post("/permits/<permit_id>/issue")
@require("Registrar")
def issue_permit(permit_id):
    permit = lookup.permit(permit_id)
    body = validate.get_json()
    reference_number = validate.require_string(body, "reference_number")

    if permit["status"] != "APPLIED":
        raise errors.conflict(errors.ERR_PERMIT_NOT_APPLIED,
                              "Only an APPLIED permit can be issued")

    # BURIAL_TRANSIT requires an already-ISSUED DEATH_CERTIFICATE for the case.
    if permit["permit_type"] == "BURIAL_TRANSIT":
        if not _issued_permit_exists(permit["case_id"], "DEATH_CERTIFICATE"):
            raise errors.conflict(errors.ERR_DEATH_CERT_REQUIRED,
                                  "An ISSUED DEATH_CERTIFICATE is required first")

    permit["status"] = "ISSUED"
    permit["reference_number"] = reference_number
    db.touch(permit)

    # Bubble-up: if both a DEATH_CERTIFICATE and a BURIAL_TRANSIT are now ISSUED
    # for the case and interment is still NOT_READY -> advance to READY.
    case = db.cases.get(permit["case_id"])
    if case is not None and case.get("interment_status") == "NOT_READY":
        if _issued_permit_exists(permit["case_id"], "DEATH_CERTIFICATE") \
                and _issued_permit_exists(permit["case_id"], "BURIAL_TRANSIT"):
            case["interment_status"] = "READY"
            db.touch(case)

    return ok_object(serialize.permit(permit), 200)


@bp.post("/permits/<permit_id>/reject")
@require("Registrar")
def reject_permit(permit_id):
    permit = lookup.permit(permit_id)
    if permit["status"] != "APPLIED":
        raise errors.conflict(errors.ERR_PERMIT_NOT_APPLIED,
                              "Only an APPLIED permit can be rejected")
    permit["status"] = "REJECTED"
    db.touch(permit)
    return ok_object(serialize.permit(permit), 200)


@bp.post("/permits/<permit_id>/reapply")
@require("Registrar")
def reapply_permit(permit_id):
    permit = lookup.permit(permit_id)
    if permit["status"] != "REJECTED":
        raise errors.conflict(errors.ERR_PERMIT_NOT_REJECTED,
                              "Only a REJECTED permit can be re-applied")
    permit["status"] = "APPLIED"
    db.touch(permit)
    return ok_object(serialize.permit(permit), 200)
