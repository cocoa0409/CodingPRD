"""Landowner endpoints (PRD 3.2)."""

from flask import Blueprint

from db import base_row, db
from middleware import authenticate
from response import created, ok
from services import lookup, serialize
from validation import Payload, raw_body

bp = Blueprint("landowners", __name__)


@bp.post("/landowners")
def create_landowner():
    authenticate(("ProgramAdmin",))
    payload = Payload(raw_body(), ("legal_name", "mailing_state", "tax_id_last4"))
    legal_name = payload.string("legal_name", min_len=1, max_len=160)
    mailing_state = payload.string(
        "mailing_state", min_len=2, max_len=2, pattern=r"[A-Z]{2}"
    )
    tax_id_last4 = payload.string(
        "tax_id_last4", min_len=4, max_len=4, pattern=r"[0-9]{4}"
    )
    row = base_row()
    row.update(
        {
            "legal_name": legal_name,
            "mailing_state": mailing_state,
            "tax_id_last4": tax_id_last4,
            "status": "ACTIVE",
        }
    )
    db.landowners[row["id"]] = row
    return created(serialize.landowner(row))


@bp.get("/landowners/<landowner_id>")
def read_landowner(landowner_id):
    authenticate(("ProgramAdmin", "AcquisitionOfficer", "Landowner"))
    return ok(serialize.landowner(lookup.get_landowner(landowner_id)))
