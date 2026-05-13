"""Ridership endpoint: PATCH alighting on existing record."""
from flask import Blueprint, g

import db
from clock import iso, now
from errors import err
from middleware import require_auth, get_json_body
from response import success


bp = Blueprint("ridership", __name__)


@bp.route("/shuttle/ridership/<rid>", methods=["PATCH"])
@require_auth(roles={"Driver", "Dispatcher"})
def update_ridership(rid):
    rr = db.ridership_records.get(rid)
    if not rr:
        raise err("ERR_NOT_FOUND", "RidershipRecord not found")
    body = get_json_body()
    asid = body.get("alighted_stop_id")
    if not isinstance(asid, str) or not asid:
        raise err("ERR_VALIDATION", "alighted_stop_id is required")
    if asid not in db.stops:
        raise err("ERR_REFERENCE_NOT_FOUND", "alighted_stop_id not found")
    rr["alighted_stop_id"] = asid
    rr["alighted_at"] = iso(now())
    return success({k: v for k, v in rr.items() if not k.startswith("_")})
