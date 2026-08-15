"""Due-diligence letter endpoints (PRD 3.3)."""

from datetime import timedelta

from flask import Blueprint

import clock
import db
import errors
from errors import raise_error
import middleware as mw
import response as resp
from helpers import (
    new_entity, touch, get_property_or_404, get_letter_or_404,
    find_applicable_rule, applicable_due_date, validate_evidence_event,
    reactivate_property,
)

bp = Blueprint("letters", __name__)

LETTER_RESPONSE_DAYS = 30


def letter_view(l):
    return {
        "id": l["id"],
        "property_id": l["property_id"],
        "sent_date": l["sent_date"].isoformat(),
        "response_deadline": l["response_deadline"].isoformat(),
        "applicable_due_date": l["applicable_due_date"].isoformat(),
        "status": l["status"],
        "response_contact_event_id": l["response_contact_event_id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


@bp.post("/escheatment/properties/<propertyId>/due-diligence-letters")
def create_letter(propertyId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    mw.body_json(required=False)
    prop = get_property_or_404(propertyId)

    # Fixed check order per PRD 3.3: state -> uniqueness -> window -> threshold.
    if prop["status"] not in ("DORMANT", "DUE_DILIGENCE"):
        raise_error(
            errors.ERR_PROPERTY_NOT_DORMANT,
            "Letter creation requires the property to be DORMANT or DUE_DILIGENCE",
        )
    for existing in db.letters.values():
        if existing["property_id"] == prop["id"] and existing["status"] in ("SENT", "DELIVERED"):
            raise_error(
                errors.ERR_DUPLICATE_ACTIVE_LETTER,
                "A letter for this property is already SENT or DELIVERED",
            )
    rule = find_applicable_rule(prop["state_code"], prop["property_type"], prop["last_contact_date"])
    if rule is None:
        raise_error(
            errors.ERR_NO_APPLICABLE_DORMANCY_RULE,
            "No applicable DormancyRule for this property",
        )
    today = clock.today()
    due = applicable_due_date(rule, prop["dormancy_date"], today)
    window_open = due - timedelta(days=rule["dd_window_max_days"])
    window_close = due - timedelta(days=rule["dd_window_min_days"])
    if not (window_open <= today <= window_close):
        raise_error(
            errors.ERR_DUE_DILIGENCE_WINDOW_VIOLATION,
            "sent_date is outside the permitted due-diligence send window",
        )
    if prop["original_value_cents"] < rule["dd_threshold_cents"]:
        raise_error(
            errors.ERR_DUE_DILIGENCE_NOT_REQUIRED,
            "Property value is below the due-diligence threshold",
        )
    letter = new_entity({
        "property_id": prop["id"],
        "sent_date": today,
        "response_deadline": today + timedelta(days=LETTER_RESPONSE_DAYS),
        "applicable_due_date": due,
        "status": "SENT",
        "response_contact_event_id": None,
    })
    db.letters[letter["id"]] = letter
    prop["status"] = "DUE_DILIGENCE"
    touch(prop)
    return resp.success(letter_view(letter), "object", 201)


@bp.get("/escheatment/properties/<propertyId>/due-diligence-letters")
def list_letters(propertyId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    prop = get_property_or_404(propertyId)
    limit, offset = mw.pagination_params()
    items = [l for l in db.letters.values() if l["property_id"] == prop["id"]]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([letter_view(l) for l in page], "array", 200, pagination=meta)


@bp.get("/escheatment/due-diligence-letters/<letterId>")
def get_letter(letterId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    letter = get_letter_or_404(letterId)
    return resp.success(letter_view(letter), "object", 200)


@bp.post("/escheatment/due-diligence-letters/<letterId>/mark-delivered")
def mark_delivered(letterId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    mw.body_json(required=False)
    letter = get_letter_or_404(letterId)
    if letter["status"] != "SENT":
        raise_error(errors.ERR_LETTER_NOT_ACTIONABLE, "Mark-delivered requires SENT")
    letter["status"] = "DELIVERED"
    touch(letter)
    return resp.success(letter_view(letter), "object", 200)


@bp.post("/escheatment/due-diligence-letters/<letterId>/mark-undeliverable")
def mark_undeliverable(letterId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    mw.body_json(required=False)
    letter = get_letter_or_404(letterId)
    if letter["status"] not in ("SENT", "DELIVERED"):
        raise_error(
            errors.ERR_LETTER_NOT_ACTIONABLE,
            "Mark-undeliverable requires SENT or DELIVERED",
        )
    letter["status"] = "UNDELIVERABLE"
    touch(letter)
    prop = db.properties.get(letter["property_id"])
    if prop is not None and prop["status"] == "DUE_DILIGENCE":
        prop["status"] = "REPORTABLE"
        touch(prop)
    return resp.success(letter_view(letter), "object", 200)


@bp.post("/escheatment/due-diligence-letters/<letterId>/record-response")
def record_response(letterId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    data = mw.body_json()
    event_id = mw.req_string(data, "response_contact_event_id")
    letter = get_letter_or_404(letterId)
    if letter["status"] not in ("SENT", "DELIVERED"):
        raise_error(
            errors.ERR_LETTER_NOT_ACTIONABLE,
            "Record-response requires SENT or DELIVERED",
        )
    prop = get_property_or_404(letter["property_id"])
    event = validate_evidence_event(prop, event_id, min_contact_date=letter["sent_date"])
    letter["status"] = "RESPONDED"
    letter["response_contact_event_id"] = event["id"]
    touch(letter)
    # Property DUE_DILIGENCE -> ACTIVE with the full reactivation cascade.
    reactivate_property(prop, event)
    return resp.success(letter_view(letter), "object", 200)
