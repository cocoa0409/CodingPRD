"""Child, EmergencyContact, AuthorizationForm routes (PRD §3.3)."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_roles, ROLE_GUARDIAN, ROLE_DIRECTOR
from response import ok_object, ok_array, paginate_params, slice_page
from services.calculations import compute_child_age
from services.common import (
    make_record,
    serialize,
    serialize_list,
    sort_by_created,
    touch,
    audit,
    get_body,
    require_str,
    require_int,
    require_enum,
)
from services.lookups import (
    get_child,
    get_guardian,
    get_session,
    get_authorization_form,
    require_child_owner,
)

bp = Blueprint("children", __name__)


# ---------------------------------------------------------------------------
# Child
# ---------------------------------------------------------------------------
@bp.post("/children")
def create_child():
    caller = require_roles(ROLE_GUARDIAN)
    body = get_body()
    guardian_id = require_str(body, "guardian_id")
    first_name = require_str(body, "first_name")
    birth_date = require_str(body, "birth_date")
    # existence of the referenced guardian (priority 3) before ownership (priority 4)
    get_guardian(guardian_id)
    # the acting guardian must be creating a child under themselves
    if guardian_id != caller.user_id:
        from errors import ERR_NOT_RESOURCE_OWNER

        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Cannot create a child under another guardian")

    household_size = 1
    if "household_size" in body and body["household_size"] is not None:
        household_size = require_int(body, "household_size", minimum=1)

    rec = make_record(
        {
            "guardian_id": guardian_id,
            "first_name": first_name,
            "birth_date": birth_date,
            "age_years": None,
            "household_size": household_size,
        }
    )
    db.children[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/children/<cid>")
def fetch_child(cid):
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR)
    rec = get_child(cid)
    return ok_object(serialize(rec), 200)


@bp.get("/children/<cid>/age-eligibility")
def child_age_eligibility(cid):
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR)
    child = get_child(cid)
    session_id = request.args.get("session_id")
    if not session_id:
        raise APIError(ERR_INVALID_REQUEST, 400, "session_id query parameter is required")
    session = get_session(session_id)
    age = compute_child_age(child, session)
    out = serialize(child)
    out["age_years"] = age
    return ok_object(out, 200)


@bp.get("/children/<cid>/emergency-contacts")
def list_emergency_contacts(cid):
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR)
    get_child(cid)
    limit, offset = paginate_params(request.args)
    items = [e for e in db.emergency_contacts.values() if e["child_id"] == cid]
    items = sort_by_created(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.get("/children/<cid>/authorization-forms")
def list_authorization_forms(cid):
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR)
    get_child(cid)
    limit, offset = paginate_params(request.args)
    form_type = request.args.get("form_type")
    items = [f for f in db.authorization_forms.values() if f["child_id"] == cid]
    if form_type is not None:
        items = [f for f in items if f["form_type"] == form_type]
    items = sort_by_created(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.get("/children/<cid>/scholarship-awards")
def list_scholarship_awards(cid):
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR)
    get_child(cid)
    limit, offset = paginate_params(request.args)
    items = [s for s in db.scholarship_awards.values() if s["child_id"] == cid]
    items = sort_by_created(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


# ---------------------------------------------------------------------------
# EmergencyContact
# ---------------------------------------------------------------------------
@bp.post("/emergency-contacts")
def create_emergency_contact():
    caller = require_roles(ROLE_GUARDIAN)
    body = get_body()
    child_id = require_str(body, "child_id")
    contact_name = require_str(body, "contact_name")
    contact_phone = require_str(body, "contact_phone")
    relationship = require_str(body, "relationship")
    child = get_child(child_id)
    require_child_owner(child, caller.user_id)

    rec = make_record(
        {
            "child_id": child_id,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "relationship": relationship,
        }
    )
    db.emergency_contacts[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


# ---------------------------------------------------------------------------
# AuthorizationForm
# ---------------------------------------------------------------------------
@bp.post("/authorization-forms")
def create_authorization_form():
    caller = require_roles(ROLE_GUARDIAN)
    body = get_body()
    child_id = require_str(body, "child_id")
    form_type = require_enum(body, "form_type", {"MEDICAL", "PICKUP"})
    child = get_child(child_id)
    require_child_owner(child, caller.user_id)

    medication_notes = None
    authorized_pickup_names = []
    if form_type == "MEDICAL":
        if "medication_notes" in body and body["medication_notes"] is not None:
            medication_notes = require_str(body, "medication_notes", allow_empty=True)
    else:  # PICKUP
        if "authorized_pickup_names" in body and body["authorized_pickup_names"] is not None:
            val = body["authorized_pickup_names"]
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                raise APIError(
                    ERR_INVALID_REQUEST, 400, "authorized_pickup_names must be an array of strings"
                )
            authorized_pickup_names = val

    rec = make_record(
        {
            "child_id": child_id,
            "form_type": form_type,
            "status": "SUBMITTED",
            "medication_notes": medication_notes,
            "authorized_pickup_names": authorized_pickup_names,
        }
    )
    db.authorization_forms[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.post("/authorization-forms/<fid>/approve")
def approve_authorization_form(fid):
    caller = require_roles(ROLE_DIRECTOR)
    form = get_authorization_form(fid)
    if form["status"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, 409, "Form is not SUBMITTED")
    # content gating by form type
    if form["form_type"] == "MEDICAL":
        if not form.get("medication_notes"):
            raise APIError(ERR_INVALID_REQUEST, 400, "MEDICAL form requires non-empty medication_notes")
    else:  # PICKUP
        if not form.get("authorized_pickup_names"):
            raise APIError(
                ERR_INVALID_REQUEST, 400, "PICKUP form requires non-empty authorized_pickup_names"
            )
    form["status"] = "APPROVED"
    touch(form)
    audit("AuthorizationForm", form["id"], "AUTH_APPROVED", caller.role)
    return ok_object(serialize(form), 200)


@bp.post("/authorization-forms/<fid>/revoke")
def revoke_authorization_form(fid):
    caller = require_roles(ROLE_GUARDIAN)
    form = get_authorization_form(fid)
    child = get_child(form["child_id"])
    require_child_owner(child, caller.user_id)
    if form["status"] not in ("SUBMITTED", "APPROVED"):
        raise APIError(ERR_INVALID_STATE, 409, "Form cannot be revoked from its current state")
    was_approved = form["status"] == "APPROVED"
    form["status"] = "REVOKED"
    touch(form)
    if was_approved:
        audit("AuthorizationForm", form["id"], "AUTH_REVOKED", caller.role)
    return ok_object(serialize(form), 200)
