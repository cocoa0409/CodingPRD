"""Region endpoints."""
from flask import Blueprint

import db
import errors
from auth import require_roles
from respond import success
from services.domain import get_or_404
from validate import (apply_filters, json_body, opt_bool, paginate, req_int,
                      req_str)

bp = Blueprint("regions", __name__)


@bp.post("/chair-massage/regions")
@require_roles("PlatformAdmin")
def create_region():
    body = json_body()
    code = req_str(body, "code")
    name = req_str(body, "name")
    mileage = req_int(body, "base_mileage_rate_cents", min_v=0)
    included = req_int(body, "travel_included_miles", min_v=0)
    setup = req_int(body, "setup_buffer_minutes", min_v=0)
    teardown = req_int(body, "teardown_buffer_minutes", min_v=0)
    is_active = opt_bool(body, "is_active", True)
    for existing in db.stores["regions"].values():
        if existing["code"] == code:
            raise errors.invalid_request(f"Region code '{code}' already exists")
    region = db.stamp_new({
        "id": db.new_id(),
        "code": code,
        "name": name,
        "base_mileage_rate_cents": mileage,
        "travel_included_miles": included,
        "setup_buffer_minutes": setup,
        "teardown_buffer_minutes": teardown,
        "is_active": is_active,
    })
    db.insert("regions", region)
    return success(db.public(region), status=201)


@bp.get("/chair-massage/regions")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def list_regions():
    items = db.all_sorted("regions")
    items = apply_filters(items, {
        "is_active": (lambda e: e["is_active"], "bool"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/regions/<rid>")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def get_region(rid):
    region = get_or_404("regions", rid, "Region")
    return success(db.public(region))
