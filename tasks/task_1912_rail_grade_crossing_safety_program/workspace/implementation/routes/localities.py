"""Locality registration endpoints (PRD §3.1).

Locality carries only id + created_at (PRD §2.4 exception — no updated_at,
no version).
"""
import uuid

from flask import Blueprint

from db import now_iso, store
from errors import ERR_LOCALITY_NOT_FOUND
from helpers import body_or_empty, get_or_404, reject_unknown, req_str
from middleware import auth
from response import ok

bp = Blueprint("localities", __name__)

ALL_ROLES = ("ProgramAdministrator", "RailSafetyOfficer", "LocalAuthority", "RailroadMaintainer")


def serialize_locality(rec):
    return {
        "id": rec["id"],
        "locality_name": rec["locality_name"],
        "state_code": rec["state_code"],
        "contact_email": rec["contact_email"],
        "created_at": rec["created_at"],
    }


@bp.post("/localities")
def create_locality():
    auth(["ProgramAdministrator"])
    body = body_or_empty()
    reject_unknown(body, ("locality_name", "state_code", "contact_email"))
    rec = {
        "id": str(uuid.uuid4()),
        "locality_name": req_str(body, "locality_name"),
        "state_code": req_str(body, "state_code"),
        "contact_email": req_str(body, "contact_email"),
        "created_at": now_iso(),
    }
    store.localities[rec["id"]] = rec
    return ok(serialize_locality(rec), 201)


@bp.get("/localities/<locality_id>")
def get_locality(locality_id):
    auth(ALL_ROLES)
    rec = get_or_404(store.localities, locality_id, ERR_LOCALITY_NOT_FOUND,
                     f"Locality {locality_id} does not exist")
    return ok(serialize_locality(rec))
