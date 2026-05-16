"""/recruiting-contacts endpoints."""

from flask import Blueprint, request

from core.auth import require_roles
from core.clock import parse_iso, iso_format
from core.envelope import success_object, success_array
from core.errors import raise_error
from core.models import make_entity, serialize, serialize_list
from core.store import STORE, lock
from core.validation import (
    require_body,
    require_field,
    require_enum,
    require_iso_datetime,
    parse_pagination,
    parse_iso_query,
)
from services.calendar_resolver import resolve_period, is_permitted


bp = Blueprint("recruiting_contacts", __name__)


VALID_CONTACT_TYPES = {
    "PHONE_CALL",
    "IN_PERSON_OFF_CAMPUS",
    "IN_PERSON_ON_CAMPUS",
    "TEXT_MESSAGE",
    "EVALUATION",
}
VALID_PERIOD_TYPES = {"QUIET", "CONTACT", "DEAD", "EVALUATION"}


@bp.route("/recruiting-contacts", methods=["POST"])
@require_roles("Coach")
def create_contact():
    body = require_body(request)
    program_id = require_field(body, "program_id", kind="string")
    athlete_id = require_field(body, "athlete_id", kind="string")
    contact_type = require_enum(body, "contact_type", VALID_CONTACT_TYPES)
    contact_at = require_iso_datetime(body, "contact_at")

    with lock():
        if program_id not in STORE.programs:
            raise_error("ERR_REFERENCE_NOT_FOUND", "Program not found")
        if athlete_id not in STORE.athletes:
            raise_error("ERR_REFERENCE_NOT_FOUND", "Athlete not found")

        period_type = resolve_period(program_id, contact_at)
        permitted = is_permitted(period_type, contact_type)
        if not permitted:
            raise_error(
                "ERR_CONTACT_NOT_PERMITTED",
                f"Contact type {contact_type} not permitted during {period_type}",
            )

        contact = make_entity("RecruitingContact", {
            "program_id": program_id,
            "athlete_id": athlete_id,
            "contact_type": contact_type,
            "contact_at": iso_format(contact_at),
            "contact_period_type": period_type,
            "was_permitted": True,
        })
        STORE.recruiting_contacts[contact["id"]] = contact
        return success_object(serialize(contact), status=201)


@bp.route("/recruiting-contacts/<contact_id>", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Auditor")
def get_contact(contact_id):
    with lock():
        c = STORE.recruiting_contacts.get(contact_id)
        if not c:
            raise_error("ERR_NOT_FOUND", "RecruitingContact not found")
        return success_object(serialize(c))


@bp.route("/recruiting-contacts", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Auditor")
def list_contacts():
    limit, offset = parse_pagination(request)
    program_id = request.args.get("program_id")
    athlete_id = request.args.get("athlete_id")
    period_type = request.args.get("contact_period_type")
    after_raw = request.args.get("after")
    before_raw = request.args.get("before")
    after_dt = parse_iso_query(after_raw, "after") if after_raw else None
    before_dt = parse_iso_query(before_raw, "before") if before_raw else None

    with lock():
        items = list(STORE.recruiting_contacts.values())
        if program_id:
            items = [c for c in items if c.get("program_id") == program_id]
        if athlete_id:
            items = [c for c in items if c.get("athlete_id") == athlete_id]
        if period_type:
            items = [c for c in items if c.get("contact_period_type") == period_type]
        if after_dt is not None:
            items = [c for c in items if parse_iso(c["contact_at"]) >= after_dt]
        if before_dt is not None:
            items = [c for c in items if parse_iso(c["contact_at"]) < before_dt]
        items.sort(key=lambda c: (c["created_at"], c["_seq"]))
        total = len(items)
        page = items[offset:offset + limit]
        return success_array(serialize_list(page), limit, offset, total)
