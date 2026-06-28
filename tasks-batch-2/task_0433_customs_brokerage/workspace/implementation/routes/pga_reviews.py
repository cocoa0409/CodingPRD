"""Partner Government Agency review endpoints (PRD §3.6)."""
from flask import Blueprint, g

from db import db
from errors import err
from helpers import (
    get_body, require_enum, stamp_create, bump_version, lookup, list_response,
)
from middleware import require_roles
from response import object_response
from serializers import pga_view

bp = Blueprint("pga_reviews", __name__)


@bp.post("/pga-reviews")
@require_roles("LicensedBroker", "CBPOfficer")
def create_pga():
    body = get_body()
    entry_id = body.get("entry_id")
    if not isinstance(entry_id, str) or entry_id == "":
        raise err("ERR_VALIDATION", "entry_id is required.")
    agency = require_enum(body, "agency", {"FDA", "USDA"})

    lookup(db.entries, entry_id)

    rec = {
        "entry_id": entry_id,
        "agency": agency,
        "decision": "PENDING",
        "reviewed_by_user_id": None,
    }
    stamp_create(rec)
    db.pga_reviews[rec["id"]] = rec
    return object_response(pga_view(rec), status=201)


@bp.get("/pga-reviews/<id>")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def get_pga(id):
    return object_response(pga_view(lookup(db.pga_reviews, id)))


@bp.get("/pga-reviews")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def list_pga():
    return list_response(
        db.pga_reviews.values(), pga_view, filters=[("entry_id", "entry_id")]
    )


# Allowed (from_decision) -> set of target decisions.
_ALLOWED = {
    "PENDING": {"MAY_PROCEED", "HOLD"},
    "HOLD": {"MAY_PROCEED", "REFUSED"},
}


@bp.post("/pga-reviews/<id>/decide")
@require_roles("CBPOfficer")
def decide_pga(id):
    pga = lookup(db.pga_reviews, id)
    body = get_body()
    decision = require_enum(body, "decision", {"MAY_PROCEED", "HOLD", "REFUSED"})

    current = pga["decision"]
    if decision not in _ALLOWED.get(current, set()):
        raise err("ERR_INVALID_STATE", "PGA review cannot transition %s -> %s." % (current, decision))

    # Entry under review must be in FILED or HOLD_EXAM.
    entry = db.entries.get(pga["entry_id"])
    if entry is None:
        raise err("ERR_NOT_FOUND", "Entry not found.")
    if entry["status"] not in ("FILED", "HOLD_EXAM"):
        raise err("ERR_INVALID_STATE", "Entry under review is not FILED or HOLD_EXAM.")

    pga["decision"] = decision
    # PENDING->{MAY_PROCEED,HOLD} stamp reviewed_by_user_id; HOLD-> transitions
    # do not re-stamp per the scaffold side effects.
    if current == "PENDING":
        pga["reviewed_by_user_id"] = g.user_id
    bump_version(pga)
    return object_response(pga_view(pga))
