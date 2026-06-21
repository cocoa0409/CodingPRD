"""Citation endpoints: issue, read, pay, citation-scoped appeal list."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_STALE_ZONE_VERSION,
)
from middleware import get_json_body, require_auth
from response import ok_object
from services import calculations, recompute
from services.common import (
    list_response,
    lookup,
    normalize_plate,
    require_int,
    require_owner_motorist,
    require_enum,
    require_string,
)
from services.serialize import public

bp = Blueprint("citations", __name__)

VIOLATION_CODES = {"NO_PERMIT", "EXPIRED_PERMIT", "WRONG_ZONE", "OVERSTAY"}


def _resolve_motorist_id(plate: str):
    """Resolve a Motorist whose default_plate matches the cited plate."""
    for m in db.motorists.values():
        if m.get("default_plate") == plate:
            return m["id"]
    return None


@bp.post("/parking/citations")
def issue_citation():
    require_auth(["EnforcementOfficer"])()
    body = get_json_body()
    garage_id = require_string(body, "garage_id")
    plate_raw = require_string(body, "plate")
    plate_read_id = require_string(body, "plate_read_id")
    violation_code = require_enum(body, "violation_code", VIOLATION_CODES, required=True)
    base_fine_cents = require_int(body, "base_fine_cents", required=True, minimum=0)

    lookup(db.garages, garage_id)
    lookup(db.plate_reads, plate_read_id)

    plate = normalize_plate(plate_raw)

    fine = calculations.citation_fine(base_fine_cents, plate)
    motorist_id = _resolve_motorist_id(plate)

    c = db.stamp_common(
        {
            "garage_id": garage_id,
            "plate": plate,
            "motorist_id": motorist_id,
            "plate_read_id": plate_read_id,
            "violation_code": violation_code,
            "base_fine_cents": base_fine_cents,
            "amount_due_cents": fine["amount_due_cents"],
            "prior_citation_count": fine["prior_citation_count"],
            "status": "ISSUED",
        }
    )
    db.citations[c["id"]] = c

    if motorist_id is not None:
        motorist = db.motorists.get(motorist_id)
        if motorist is not None:
            recompute.recompute_motorist_balance(motorist, bump=True)

    return ok_object(public(c), 201)


@bp.get("/parking/citations/<cid>")
def read_citation(cid):
    require_auth(["FacilityAdmin", "EnforcementOfficer", "Motorist"])()
    c = lookup(db.citations, cid)
    return ok_object(public(c), 200)


@bp.post("/parking/citations/<cid>/pay")
def pay_citation(cid):
    require_auth(["Motorist"])()
    c = lookup(db.citations, cid)
    body = get_json_body()
    expected_citation_version = require_int(body, "expected_citation_version", required=True)

    # state (priority 4): must be ISSUED or UPHELD.
    if c["status"] not in ("ISSUED", "UPHELD"):
        raise APIError(ERR_INVALID_STATE, 409, "Citation is not payable")

    # ownership (priority 5)
    require_owner_motorist(c.get("motorist_id"))

    # OCC (priority 14)
    if expected_citation_version != c["version"]:
        raise APIError(ERR_STALE_ZONE_VERSION, 412, "expected_citation_version does not match citation version")

    c["status"] = "PAID"
    db.bump(c)

    if c.get("motorist_id") is not None:
        motorist = db.motorists.get(c["motorist_id"])
        if motorist is not None:
            recompute.recompute_motorist_balance(motorist, bump=True)

    return ok_object(public(c), 200)


@bp.get("/parking/citations/<cid>/appeals")
def list_citation_appeals(cid):
    require_auth(["FacilityAdmin", "EnforcementOfficer", "Motorist"])()
    lookup(db.citations, cid)
    items = [a for a in db.appeals.values() if a["citation_id"] == cid]
    return list_response(items, request.args)
