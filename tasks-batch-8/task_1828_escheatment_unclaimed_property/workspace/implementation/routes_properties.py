"""Property, contact-event, escheat, and reactivation endpoints (PRD 3.1/3.3)."""

from flask import Blueprint

import clock
import db
import errors
from errors import raise_error
import middleware as mw
import response as resp
from helpers import (
    new_entity, touch, find_applicable_rule, get_owner_or_404,
    get_property_or_404, check_claimant_owner_scope, validate_evidence_event,
    reactivate_property, property_has_line_in_submitted_or_accepted,
    PROPERTY_TYPES, CONTACT_TYPES, QUALIFYING_CONTACT_TYPES,
)

bp = Blueprint("properties", __name__)


def property_view(p):
    return {
        "id": p["id"],
        "owner_id": p["owner_id"],
        "property_type": p["property_type"],
        "state_code": p["state_code"],
        "original_value_cents": p["original_value_cents"],
        "last_contact_date": p["last_contact_date"].isoformat(),
        "status": p["status"],
        "dormancy_date": p["dormancy_date"].isoformat() if p["dormancy_date"] else None,
        "escheated_date": p["escheated_date"].isoformat() if p["escheated_date"] else None,
        "reunited_date": p["reunited_date"].isoformat() if p["reunited_date"] else None,
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def contact_event_view(e):
    return {
        "id": e["id"],
        "property_id": e["property_id"],
        "contact_type": e["contact_type"],
        "contact_date": e["contact_date"].isoformat(),
        "evidence_ref": e["evidence_ref"],
        "qualifies_for_reactivation": e["qualifies_for_reactivation"],
        "recorded_by_user_id": e["recorded_by_user_id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


@bp.post("/escheatment/properties")
def create_property():
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    data = mw.body_json()
    owner_id = mw.req_string(data, "owner_id")
    property_type = mw.req_enum(data, "property_type", PROPERTY_TYPES)
    state_code = mw.req_string(data, "state_code")
    value = mw.req_int(data, "original_value_cents", min_value=1)
    last_contact = mw.req_date(data, "last_contact_date")

    owner = get_owner_or_404(owner_id)
    if state_code != owner["state_code"]:
        raise_error(
            errors.ERR_OWNER_STATE_MISMATCH,
            "property.state_code must equal the owner's state_code",
        )
    rule = find_applicable_rule(state_code, property_type, last_contact)
    if rule is None:
        raise_error(
            errors.ERR_NO_APPLICABLE_DORMANCY_RULE,
            "No DormancyRule covers this state and property type at last_contact_date",
        )
    prop = new_entity({
        "owner_id": owner["id"],
        "property_type": property_type,
        "state_code": state_code,
        "original_value_cents": value,
        "last_contact_date": last_contact,
        "status": "ACTIVE",
        "dormancy_date": None,
        "escheated_date": None,
        "reunited_date": None,
    })
    db.properties[prop["id"]] = prop
    return resp.success(property_view(prop), "object", 201)


@bp.get("/escheatment/properties")
def list_properties():
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    limit, offset = mw.pagination_params()
    items = list(db.properties.values())
    owner_id = mw.request.args.get("owner_id")
    if owner_id is not None:
        items = [p for p in items if p["owner_id"] == owner_id]
    state_code = mw.request.args.get("state_code")
    if state_code is not None:
        items = [p for p in items if p["state_code"] == state_code]
    status = mw.request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([property_view(p) for p in page], "array", 200, pagination=meta)


@bp.get("/escheatment/properties/<propertyId>")
def get_property(propertyId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    prop = get_property_or_404(propertyId)
    check_claimant_owner_scope(ctx, prop["owner_id"])
    return resp.success(property_view(prop), "object", 200)


@bp.post("/escheatment/properties/<propertyId>/contact-events")
def create_contact_event(propertyId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer", "Claimant"))
    data = mw.body_json()
    contact_type = mw.req_enum(data, "contact_type", CONTACT_TYPES)
    contact_date = mw.req_date(data, "contact_date")
    evidence_ref = mw.req_string(data, "evidence_ref")
    prop = get_property_or_404(propertyId)
    check_claimant_owner_scope(ctx, prop["owner_id"])
    event = new_entity({
        "property_id": prop["id"],
        "contact_type": contact_type,
        "contact_date": contact_date,
        "evidence_ref": evidence_ref,
        "qualifies_for_reactivation": contact_type in QUALIFYING_CONTACT_TYPES,
        "recorded_by_user_id": ctx.user_id,
    })
    db.contact_events[event["id"]] = event
    if contact_date > prop["last_contact_date"]:
        prop["last_contact_date"] = contact_date
        touch(prop)
    return resp.success(contact_event_view(event), "object", 201)


@bp.get("/escheatment/properties/<propertyId>/contact-events")
def list_contact_events(propertyId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    prop = get_property_or_404(propertyId)
    limit, offset = mw.pagination_params()
    items = [e for e in db.contact_events.values() if e["property_id"] == prop["id"]]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([contact_event_view(e) for e in page], "array", 200, pagination=meta)


@bp.get("/escheatment/properties/<propertyId>/report-line-items")
def list_property_line_items(propertyId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    prop = get_property_or_404(propertyId)
    limit, offset = mw.pagination_params()
    from routes_reports import line_item_view
    items = [l for l in db.line_items.values() if l["property_id"] == prop["id"]]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([line_item_view(l) for l in page], "array", 200, pagination=meta)


@bp.get("/escheatment/properties/<propertyId>/owner-claims")
def list_property_claims(propertyId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    prop = get_property_or_404(propertyId)
    limit, offset = mw.pagination_params()
    from routes_claims import claim_view
    items = [c for c in db.claims.values() if c["property_id"] == prop["id"]]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([claim_view(c) for c in page], "array", 200, pagination=meta)


@bp.post("/escheatment/properties/<propertyId>/reactivate")
def reactivate(propertyId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    data = mw.body_json()
    event_id = mw.req_string(data, "evidence_contact_event_id")
    prop = get_property_or_404(propertyId)
    if prop["status"] not in ("DORMANT", "DUE_DILIGENCE", "REPORTABLE"):
        raise_error(
            errors.ERR_PROPERTY_NOT_REACTIVATABLE,
            "Reactivation requires DORMANT, DUE_DILIGENCE, or REPORTABLE",
        )
    event = validate_evidence_event(prop, event_id)
    if prop["status"] == "REPORTABLE" and property_has_line_in_submitted_or_accepted(prop["id"]):
        raise_error(
            errors.ERR_PROPERTY_IN_SUBMITTED_REPORT,
            "Property has a line in a SUBMITTED or ACCEPTED report",
        )
    reactivate_property(prop, event)
    return resp.success(property_view(prop), "object", 200)


@bp.post("/escheatment/properties/<propertyId>/escheat")
def escheat(propertyId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("StateAuditor",))
    mw.body_json(required=False)
    prop = get_property_or_404(propertyId)
    if prop["status"] != "REMITTED":
        raise_error(
            errors.ERR_PROPERTY_NOT_REMITTED,
            "Escheat requires the property to be REMITTED",
        )
    prop["status"] = "ESCHEATED"
    prop["escheated_date"] = clock.today()
    touch(prop)
    return resp.success(property_view(prop), "object", 200)
