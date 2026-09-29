"""CertificationListing endpoints, suspension cascade (PRD Sections 3.1, 3.2)."""
from flask import Blueprint

import validate
from db import db, insert, touch, ordered
from errors import ApiError
from middleware import authorize
from response import ok, created, ok_list
from routes.helpers import find, filter_by, require_reason
from services import calc, derive
from timeutil import add_days

bp = Blueprint("certification_listings", __name__)

STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "CONDITIONS_REQUESTED", "LISTED",
            "SUSPENDED", "REJECTED")
LIVE_APPLICATION_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "CONDITIONS_REQUESTED", "LISTED")
DECISIONS = ("ACKNOWLEDGE_REVIEW", "CONDITIONS", "GRANT", "REJECT", "SUSPEND", "REINSTATE")
READ_ROLES = ("ComplianceEngineer", "ListingReviewer", "ApplicationEngineer",
              "EngineeringApprover", "PlatformAdmin")


def _check_agency_remit(agency_code, scopes):
    remit = calc.AGENCY_SCOPES[agency_code]
    for scope in scopes:
        if scope not in remit:
            raise ApiError("ERR_AGENCY_SCOPE_NOT_COVERED",
                           "%s may not grant %s" % (agency_code, scope))


@bp.post("/certification-listings")
def create_listing():
    authorize("ComplianceEngineer", "PlatformAdmin")
    payload = validate.body()
    equipment_model_id = validate.string_field(payload, "equipment_model_id")
    agency_code = validate.enum_field(payload, "agency_code", calc.AGENCY_CODES)
    scopes = validate.enum_array_field(payload, "scopes", calc.SCOPE_ORDER)

    find(db.equipment_models, equipment_model_id, "ERR_EQUIPMENT_MODEL_NOT_FOUND")
    _check_agency_remit(agency_code, scopes)

    listing = insert(db.certification_listings, {
        "equipment_model_id": equipment_model_id,
        "agency_code": agency_code,
        "scopes": scopes,
        "status": "DRAFT",
        "revision": 0,
        "conditions_note": None,
        "listed_on": None,
        "expires_on": None,
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
    })
    return created(listing)


@bp.get("/certification-listings")
def list_listings():
    authorize(*READ_ROLES)
    limit, offset = validate.pagination()
    equipment_model_id = validate.str_arg("equipment_model_id")
    agency_code = validate.enum_arg("agency_code", calc.AGENCY_CODES)
    status = validate.enum_arg("status", STATUSES)

    items = ordered(db.certification_listings)
    items = filter_by(items, "equipment_model_id", equipment_model_id)
    items = filter_by(items, "agency_code", agency_code)
    items = filter_by(items, "status", status)
    return ok_list(items, limit, offset)


@bp.get("/certification-listings/<listing_id>")
def get_listing(listing_id):
    authorize(*READ_ROLES)
    listing = find(db.certification_listings, listing_id, "ERR_COMPLIANCE_RESOURCE_NOT_FOUND")
    return ok(listing)


@bp.post("/certification-listings/<listing_id>/submissions")
def submit_listing(listing_id):
    actor = authorize("ComplianceEngineer", "PlatformAdmin")
    listing = find(db.certification_listings, listing_id, "ERR_COMPLIANCE_RESOURCE_NOT_FOUND")

    if listing["status"] not in ("DRAFT", "CONDITIONS_REQUESTED"):
        raise ApiError("ERR_LISTING_STATE_INVALID",
                       "a %s listing cannot be submitted" % listing["status"])

    _check_agency_remit(listing["agency_code"], listing["scopes"])

    for sibling in derive.listings_for_model(listing["equipment_model_id"]):
        if sibling["id"] == listing["id"]:
            continue
        if sibling["agency_code"] == listing["agency_code"] \
                and sibling["status"] in LIVE_APPLICATION_STATUSES:
            raise ApiError("ERR_DUPLICATE_LISTING_APPLICATION",
                           "a competing live application exists for this model and agency")

    if listing["revision"] >= calc.MAX_LISTING_REVISIONS:
        raise ApiError("ERR_LISTING_REVISION_LIMIT", "the revision budget is exhausted")

    if listing["status"] == "CONDITIONS_REQUESTED":
        listing["revision"] += 1
    listing["status"] = "SUBMITTED"
    listing["submitted_by_user_id"] = actor.user_id
    touch(listing)
    return ok(listing)


@bp.post("/certification-listings/<listing_id>/agency-decisions")
def decide_listing(listing_id):
    actor = authorize("ListingReviewer", "PlatformAdmin")
    payload = validate.body()
    decision = validate.enum_field(payload, "decision", DECISIONS)
    conditions_note = None
    if decision in ("CONDITIONS", "SUSPEND"):
        conditions_note = require_reason(payload, "conditions_note")

    listing = find(db.certification_listings, listing_id, "ERR_COMPLIANCE_RESOURCE_NOT_FOUND")

    # Segregation of duties applies to every disposition (PRD Section 2.10).
    if listing["submitted_by_user_id"] is not None \
            and actor.user_id == listing["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the operator who submitted the application may not decide it")

    required_state = {
        "ACKNOWLEDGE_REVIEW": "SUBMITTED",
        "CONDITIONS": "UNDER_REVIEW",
        "GRANT": "UNDER_REVIEW",
        "REJECT": "UNDER_REVIEW",
        "SUSPEND": "LISTED",
        "REINSTATE": "SUSPENDED",
    }[decision]
    if listing["status"] != required_state:
        raise ApiError("ERR_LISTING_STATE_INVALID",
                       "%s is not permitted from %s" % (decision, listing["status"]))

    if decision == "REINSTATE":
        if listing["expires_on"] is None or not db.clock < listing["expires_on"]:
            raise ApiError("ERR_LISTING_STATE_INVALID",
                           "an expired suspension cannot be reinstated")

    model = db.equipment_models.get(listing["equipment_model_id"])

    if decision == "ACKNOWLEDGE_REVIEW":
        listing["status"] = "UNDER_REVIEW"
    elif decision == "CONDITIONS":
        listing["status"] = "CONDITIONS_REQUESTED"
        listing["conditions_note"] = conditions_note
    elif decision == "GRANT":
        listing["status"] = "LISTED"
        listing["listed_on"] = db.clock
        listing["expires_on"] = add_days(db.clock, calc.LISTING_TERM_DAYS)
    elif decision == "REJECT":
        listing["status"] = "REJECTED"
    elif decision == "SUSPEND":
        listing["status"] = "SUSPENDED"
        listing["conditions_note"] = conditions_note
    else:  # REINSTATE
        listing["status"] = "LISTED"

    listing["decided_by_user_id"] = actor.user_id
    touch(listing)

    if model is not None and decision in ("GRANT", "SUSPEND", "REINSTATE"):
        posture = derive.recompute_model_posture(model)
        if decision == "SUSPEND":
            derive.cascade_suspension(model)
        elif decision == "REINSTATE" and posture != "SUSPENDED":
            derive.release_compliance_holds(model)

    return ok(listing)
