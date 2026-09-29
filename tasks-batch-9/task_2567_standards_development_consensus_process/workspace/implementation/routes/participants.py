"""Participant registry (PRD 3.1)."""

from flask import Blueprint

from core import auth, envelope
from core.enums import INTEREST_CATEGORY
from core.store import insert, public, rows
from core.validation import Body, apply_filters, load_path

bp = Blueprint("participants", __name__)

FILTERS = ("interest_category", "organization", "employer_affiliation_code")


@bp.post("/sdo/participants")
def create_participant():
    auth.authenticate((auth.STANDARDS_STAFF,))
    body = Body(("full_name", "organization", "interest_category",
                 "employer_affiliation_code"))
    full_name = body.string("full_name", required=True, min_len=1, max_len=120)
    organization = body.string("organization", required=True, min_len=1, max_len=160)
    interest_category = body.enum("interest_category", INTEREST_CATEGORY, required=True)
    affiliation = body.string("employer_affiliation_code", min_len=1, max_len=32,
                              nullable=True, default=None)
    row = insert("participants", {
        "full_name": full_name,
        "organization": organization,
        "interest_category": interest_category,
        "employer_affiliation_code": affiliation,
    })
    return envelope.created(public(row))


@bp.get("/sdo/participants")
def list_participants():
    auth.authenticate(auth.READ_ROLES)
    return envelope.list_response(apply_filters(rows("participants"), FILTERS))


@bp.get("/sdo/participants/<participant_id>")
def get_participant(participant_id):
    auth.authenticate(auth.READ_ROLES)
    return envelope.object_response(public(load_path("participants", participant_id)))
