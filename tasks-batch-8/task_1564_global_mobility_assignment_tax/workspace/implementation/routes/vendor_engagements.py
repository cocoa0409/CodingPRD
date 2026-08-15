"""VendorEngagement endpoints (PRD §3.4): cyclic review loop, mark-filed gate."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_DUPLICATE_ENGAGEMENT, ERR_INVALID_STATE
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record, touch
from validate import get_body, req_enum, req_field, req_int, req_str, require_fk, require_path_resource

bp = Blueprint("vendor_engagements", __name__)

SCOPES = {"HOME_ONLY", "HOST_ONLY", "DUAL"}


@bp.post("/mobility/vendor-engagements")
def create_engagement():
    authorized(["VendorCoordinator"])
    body = get_body()
    asg = require_fk("assignments", req_field(body, "assignment_id"), "assignment_id")
    tax_year = req_int(body, "tax_year")
    scope = req_enum(body, "scope", SCOPES)
    vendor_name = req_str(body, "vendor_name")
    fee_cents = req_int(body, "fee_cents", minimum=0)
    # At most one non-CLOSED engagement per (assignment_id, tax_year).
    for ve in db["vendor_engagements"].values():
        if (ve["assignment_id"] == asg["id"] and ve["tax_year"] == tax_year
                and ve["status"] != "CLOSED"):
            raise_error(ERR_DUPLICATE_ENGAGEMENT, "a non-CLOSED engagement already exists for this tax year")
    rec = new_record("vendor_engagements", {
        "assignment_id": asg["id"],
        "tax_year": tax_year,
        "scope": scope,
        "vendor_name": vendor_name,
        "fee_cents": fee_cents,
        "status": "ENGAGED",
        "revision_count": 0,
        "filed_total_gross_cents": None,
        "filed_home_tax_cents": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/mobility/vendor-engagements/<rid>")
def get_engagement(rid):
    return get_one("vendor_engagements", rid)


@bp.get("/mobility/vendor-engagements")
def list_engagements():
    return list_response("vendor_engagements", {
        "assignment_id": request.args.get("assignment_id"),
        "tax_year": request.args.get("tax_year"),
        "status": request.args.get("status"),
    })


def _transition(rid, allowed_from, to_state, mutate=None):
    ve = require_path_resource("vendor_engagements", rid)
    if ve["status"] not in allowed_from:
        raise_error(ERR_INVALID_STATE, f"engagement in {ve['status']} cannot transition to {to_state}")
    ve["status"] = to_state
    if mutate is not None:
        mutate(ve)
    touch(ve)
    return success_object(public(ve))


@bp.post("/mobility/vendor-engagements/<rid>/send-data")
def send_data(rid):
    authorized(["VendorCoordinator"])
    return _transition(rid, ("ENGAGED",), "DATA_SENT")


@bp.post("/mobility/vendor-engagements/<rid>/return-draft")
def return_draft(rid):
    authorized(["TaxVendor"])
    return _transition(rid, ("DATA_SENT", "REVISION_REQUESTED"), "DRAFT_RETURNED")


@bp.post("/mobility/vendor-engagements/<rid>/start-review")
def start_review(rid):
    authorized(["VendorCoordinator"])
    return _transition(rid, ("DRAFT_RETURNED",), "UNDER_REVIEW")


@bp.post("/mobility/vendor-engagements/<rid>/request-revision")
def request_revision(rid):
    authorized(["VendorCoordinator"])

    def _bump(ve):
        ve["revision_count"] += 1

    return _transition(rid, ("UNDER_REVIEW",), "REVISION_REQUESTED", mutate=_bump)


@bp.post("/mobility/vendor-engagements/<rid>/accept")
def accept(rid):
    authorized(["VendorCoordinator"])
    return _transition(rid, ("UNDER_REVIEW",), "ACCEPTED")


@bp.post("/mobility/vendor-engagements/<rid>/mark-filed")
def mark_filed(rid):
    authorized(["VendorCoordinator"])
    body = get_body()
    filed_total_gross_cents = req_int(body, "filed_total_gross_cents", minimum=0)
    filed_home_tax_cents = req_int(body, "filed_home_tax_cents", minimum=0)

    def _record(ve):
        ve["filed_total_gross_cents"] = filed_total_gross_cents
        ve["filed_home_tax_cents"] = filed_home_tax_cents

    return _transition(rid, ("ACCEPTED",), "FILED", mutate=_record)


@bp.post("/mobility/vendor-engagements/<rid>/close")
def close_engagement(rid):
    authorized(["VendorCoordinator"])
    return _transition(rid, ("FILED",), "CLOSED")
