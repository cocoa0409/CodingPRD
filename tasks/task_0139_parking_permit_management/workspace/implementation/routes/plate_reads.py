"""PlateRead (LPR) endpoints: submit, read, zone-scoped list."""
from __future__ import annotations

from flask import Blueprint

import db
from middleware import get_json_body, require_auth
from response import ok_object
from services import calculations
from services.common import (
    list_response,
    lookup,
    normalize_plate,
    require_datetime,
    require_string,
)
from services.serialize import public
from flask import request

bp = Blueprint("plate_reads", __name__)


@bp.post("/parking/plate-reads")
def submit_plate_read():
    require_auth(["EnforcementOfficer"])()
    body = get_json_body()
    garage_id = require_string(body, "garage_id")
    plate_raw = require_string(body, "plate")
    zone_id = require_string(body, "zone_id")
    read_at_utc = require_datetime(body, "read_at_utc", required=True)

    lookup(db.garages, garage_id)
    lookup(db.zones, zone_id)

    plate = normalize_plate(plate_raw)
    outcome = calculations.lpr_enforcement(garage_id, plate, zone_id)

    r = db.stamp_immutable(
        {
            "garage_id": garage_id,
            "plate": plate,
            "zone_id": zone_id,
            "read_at_utc": read_at_utc,
            "enforcement_outcome": outcome["enforcement_outcome"],
            "matched_permit_id": outcome["matched_permit_id"],
        }
    )
    db.plate_reads[r["id"]] = r
    return ok_object(public(r), 201)


@bp.get("/parking/plate-reads/<rid>")
def read_plate_read(rid):
    require_auth(["FacilityAdmin", "EnforcementOfficer"])()
    r = lookup(db.plate_reads, rid)
    return ok_object(public(r), 200)


@bp.get("/parking/plate-reads/<rid>/citations")
def list_plate_read_citations(rid):
    require_auth(["FacilityAdmin", "EnforcementOfficer"])()
    lookup(db.plate_reads, rid)
    items = [c for c in db.citations.values() if c.get("plate_read_id") == rid]
    return list_response(items, request.args)
