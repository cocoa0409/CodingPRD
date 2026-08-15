"""Vendor endpoints: registry, residency review, revocation cascade."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_STATE_TRANSITION
from helpers import check_producer_owns, get_one, list_query, public
from middleware import authorized
from response import success_object
from services.core import new_record, touch, vendor_revocation_cascade
from util import CLOCK
from validate import (
    get_body,
    reject_unknown_fields,
    req_enum,
    req_str,
    require_body_ref,
    require_path_resource,
)

bp = Blueprint("vendors", __name__)

RESIDENCY_DECISIONS = {"VERIFIED", "REJECTED"}


@bp.post("/vendors")
def create_vendor():
    caller = authorized(["Producer"])
    body = get_body()
    reject_unknown_fields(body, {"production_id", "legal_name", "tax_id", "residency_jurisdiction"})
    production_id = req_str(body, "production_id")
    legal_name = req_str(body, "legal_name")
    tax_id = req_str(body, "tax_id")
    residency_jurisdiction = req_str(body, "residency_jurisdiction")
    production = require_body_ref("productions", production_id, "production_id")
    check_producer_owns(caller, production["production_company_id"])
    rec = new_record("vendors", {
        "production_id": production_id,
        "legal_name": legal_name,
        "tax_id": tax_id,
        "residency_jurisdiction": residency_jurisdiction,
        "residency_status": "UNVERIFIED",
        "verified_at": None,
        "residency_reviewed_by": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/vendors")
def list_vendors():
    return list_query("vendors", {
        "production_id": request.args.get("production_id"),
        "residency_status": request.args.get("residency_status"),
    })


@bp.get("/vendors/<vendorId>")
def get_vendor(vendorId):
    return get_one("vendors", vendorId)


@bp.post("/vendors/<vendorId>/review-residency")
def review_residency(vendorId):
    caller = authorized(["FilmOfficeReviewer"])
    vendor = require_path_resource("vendors", vendorId)
    body = get_body()
    reject_unknown_fields(body, {"decision", "rejection_reason"})
    decision = req_enum(body, "decision", RESIDENCY_DECISIONS)
    current = vendor["residency_status"]
    # Declared transitions: UNVERIFIED -> {VERIFIED, REJECTED},
    # REJECTED -> VERIFIED, VERIFIED -> REJECTED (the revocation cascade).
    declared = {
        ("UNVERIFIED", "VERIFIED"),
        ("UNVERIFIED", "REJECTED"),
        ("REJECTED", "VERIFIED"),
        ("VERIFIED", "REJECTED"),
    }
    if (current, decision) not in declared:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"residency decision {decision} is not declared from {current}")
    vendor["residency_reviewed_by"] = caller.user_id
    if decision == "VERIFIED":
        vendor["residency_status"] = "VERIFIED"
        vendor["verified_at"] = CLOCK.now_iso()
        touch(vendor)
    else:
        was_verified = current == "VERIFIED"
        vendor["residency_status"] = "REJECTED"
        touch(vendor)
        if was_verified:
            # Deep cascade: disqualify this vendor's QUALIFIED entries across
            # all applications of the production, recompute totals, refresh
            # certificate exposure, auto-open/update SPEND_SHORTFALL cases.
            vendor_revocation_cascade(vendor)
    return success_object(public(vendor))
