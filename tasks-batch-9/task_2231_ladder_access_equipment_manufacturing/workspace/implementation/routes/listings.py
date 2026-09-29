"""ListingBody and ListingRecord endpoints (PRD 3.5)."""

from flask import Blueprint, g

import calc
import cascade
import lookup
import response
import serialize
import store
import validate
from auth import authorize
from errors import fail
from routes._common import paged
from store import db, mark_dirty, now

bp = Blueprint("listings", __name__)

RECORD_READERS = ("ComplianceOfficer", "CertificationBody", "DesignApprover", "SafetyDirector")


@bp.post("/listing-bodies")
@authorize("ComplianceOfficer")
def create_listing_body():
    data = validate.body()
    body_code = validate.req_str(data, "body_code")
    accredited_standards = validate.req_str_array(
        data, "accredited_standards", allowed=calc.STANDARD_CODES
    )
    audit_interval_days = validate.req_int(data, "audit_interval_days", minimum=1, maximum=730)

    for existing in db.listing_bodies.values():
        if existing["body_code"] == body_code:
            fail("ERR_DUPLICATE_KEY", "body_code already exists: %s" % body_code)

    body = store.base_record()
    body.update(
        {
            "body_code": body_code,
            "accredited_standards": list(accredited_standards),
            "audit_interval_days": audit_interval_days,
        }
    )
    db.listing_bodies[body["id"]] = body
    store.register_new(body)
    return response.created(body, serialize.listing_body)


@bp.post("/listing-records")
@authorize("ComplianceOfficer")
def create_listing_record():
    data = validate.body()

    product = None
    if validate.present(data, "product_id"):
        product = lookup.product(data["product_id"])
    body = None
    if validate.present(data, "listing_body_id"):
        body = lookup.listing_body(data["listing_body_id"])

    validate.req_id(data, "product_id")
    validate.req_id(data, "listing_body_id")
    standard_code = validate.req_enum(data, "standard_code", calc.STANDARD_CODES)

    record = store.base_record()
    record.update(
        {
            "product_id": product["id"],
            "listing_body_id": body["id"],
            "standard_code": standard_code,
            "status": "APPLIED",
            "listed_at": None,
            "audit_due_at": None,
            "listing_expires_at": None,
            "suspended_at": None,
            "suspension_reason": None,
        }
    )
    db.listing_records[record["id"]] = record
    store.register_new(record)
    return response.created(record, serialize.listing_record)


@bp.get("/listing-records/<record_id>")
@authorize(*RECORD_READERS)
def get_listing_record(record_id):
    record = lookup.listing_record(record_id)
    return response.obj(record, serialize.listing_record)


@bp.get("/listing-records")
@authorize(*RECORD_READERS)
def list_listing_records():
    spec = {
        "product_id": "product_id",
        "listing_body_id": "listing_body_id",
        "status": "status",
        "standard_code": "standard_code",
    }
    return paged(lookup.rows(db.listing_records), spec, serialize.listing_record)


def _require_ownership(record):
    """Ladder step 5 — the acting CertificationBody must own the record."""
    if record["listing_body_id"] != g.user_id:
        fail("ERR_LISTING_BODY_MISMATCH", "only the owning listing body may act on this record")


@bp.post("/listing-records/<record_id>/list")
@authorize("CertificationBody")
def grant_listing(record_id):
    record = lookup.listing_record(record_id)
    _require_ownership(record)

    # step 17
    if record["status"] != "APPLIED":
        fail("ERR_LISTING_STATE_INVALID", "status must be APPLIED to grant a listing")

    product = db.products[record["product_id"]]
    # step 37
    if product["design_status"] != "DESIGN_FROZEN":
        fail("ERR_DESIGN_NOT_FROZEN", "design_status must be DESIGN_FROZEN")

    # step 38 — PASSED CERTIFICATION_LISTING campaign on the frozen revision
    qualified = False
    for campaign in lookup.campaigns_of_product(product["id"]):
        if (
            campaign["design_revision_id"] == product["frozen_revision_id"]
            and campaign["purpose"] == "CERTIFICATION_LISTING"
            and campaign["status"] == "PASSED"
        ):
            qualified = True
            break
    if not qualified:
        fail(
            "ERR_QUALIFYING_CAMPAIGN_MISSING",
            "a PASSED CERTIFICATION_LISTING campaign on the frozen revision is required",
        )

    body = db.listing_bodies[record["listing_body_id"]]
    # step 39
    if record["standard_code"] not in body["accredited_standards"]:
        fail("ERR_STANDARD_NOT_ACCREDITED", "the body is not accredited for that standard")

    record["status"] = "LISTED"
    record["listed_at"] = now()
    record["audit_due_at"] = calc.add_days(now(), body["audit_interval_days"])
    record["listing_expires_at"] = calc.add_days(now(), calc.LISTING_TERM_DAYS)
    mark_dirty(record)
    return response.obj(record, serialize.listing_record)


@bp.post("/listing-records/<record_id>/suspend")
@authorize("CertificationBody")
def suspend_listing(record_id):
    record = lookup.listing_record(record_id)
    _require_ownership(record)

    data = validate.body()
    suspension_reason = validate.req_enum(data, "suspension_reason", calc.SUSPENSION_REASONS)

    if record["status"] != "LISTED":
        fail("ERR_LISTING_STATE_INVALID", "status must be LISTED to suspend")

    cascade.listing_suspend(record, suspension_reason)
    return response.obj(record, serialize.listing_record)
