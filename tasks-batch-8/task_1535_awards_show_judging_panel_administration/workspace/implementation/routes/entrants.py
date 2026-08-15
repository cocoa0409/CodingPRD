"""Entrant endpoints + entrant-scoped collections."""
import re

from flask import Blueprint, request

import services
import store
from auth import authenticate, authorize, forbid
from errors import raise_err, ERR_INVALID_REQUEST, ERR_DUPLICATE
from util import (
    body_json, req_str, new_record, success_object, list_response, get_or_404,
)

bp = Blueprint("entrants", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


@bp.post("/awards/entrants")
def create_entrant():
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    body = body_json()
    legal_name = req_str(body, "legal_name")
    contact_email = req_str(body, "contact_email")
    if not EMAIL_RE.match(contact_email):
        raise_err(ERR_INVALID_REQUEST, "contact_email must be a valid email address")
    country_code = req_str(body, "country_code")
    if not COUNTRY_RE.match(country_code):
        raise_err(ERR_INVALID_REQUEST,
                  "country_code must be an ISO 3166-1 alpha-2 code")
    for e in store.entrants.values():
        if e["contact_email"] == contact_email:
            raise_err(ERR_DUPLICATE, "contact_email already registered: %s" % contact_email)
    rec = new_record()
    rec.update({
        "legal_name": legal_name,
        "contact_email": contact_email,
        "country_code": country_code,
        "standing": "GOOD",
        "delinquent_since": None,
        "lifetime_disqualifications": 0,
    })
    store.entrants[rec["id"]] = rec
    return success_object(services.serialize_entrant(rec), 201)


@bp.get("/awards/entrants")
def list_entrants():
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor"])
    records = list(store.entrants.values())
    standing = request.args.get("standing")
    if standing:
        records = [e for e in records if e["standing"] == standing]
    return list_response(records, services.serialize_entrant)


@bp.get("/awards/entrants/<eid>")
def get_entrant(eid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Entrant"])
    rec = get_or_404(store.entrants, eid, "Entrant")
    if role == "Entrant" and uid != rec["id"]:
        forbid("Entrant may only read their own record")
    return success_object(services.serialize_entrant(rec), 200)


@bp.get("/awards/entrants/<eid>/entries")
def list_entrant_entries(eid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Entrant"])
    rec = get_or_404(store.entrants, eid, "Entrant")
    if role == "Entrant" and uid != rec["id"]:
        forbid("Entrant may only list their own entries")
    records = [e for e in store.entries.values() if e["entrant_id"] == rec["id"]]
    status = request.args.get("status")
    if status:
        records = [e for e in records if e["status"] == status]
    return list_response(records, services.serialize_entry)


@bp.get("/awards/entrants/<eid>/appeals")
def list_entrant_appeals(eid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Entrant"])
    rec = get_or_404(store.entrants, eid, "Entrant")
    if role == "Entrant" and uid != rec["id"]:
        forbid("Entrant may only list their own appeals")
    records = [a for a in store.appeals.values() if a["filed_by_entrant_id"] == rec["id"]]
    status = request.args.get("status")
    if status:
        records = [a for a in records if a["status"] == status]
    return list_response(records, services.serialize_appeal)


@bp.get("/awards/entrants/<eid>/conflict-declarations")
def list_entrant_declarations(eid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor"])
    rec = get_or_404(store.entrants, eid, "Entrant")
    records = [d for d in store.declarations.values() if d.get("entrant_id") == rec["id"]]
    season_id = request.args.get("season_id")
    if season_id:
        records = [d for d in records if d.get("season_id") == season_id]
    return list_response(records, services.serialize_declaration)
