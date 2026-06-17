"""Service bay routes (PRD 3.9)."""

from flask import Blueprint, request

import db
from common import (body, new_entity, require_str, require_enum, opt_int,
                    paginate, get_or_404, find_dealership)
from middleware import get_auth, require_role
from response import ok, created, ok_list

bp = Blueprint("service_bays", __name__)

BAY_KINDS = {"REPAIR", "WASH_PDI"}


@bp.post("/service-bays")
def create_bay():
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor", "DealerManager"})
    data = body()
    did = data.get("dealership_id")
    find_dealership(did)
    name = require_str(data, "name")
    bay_kind = require_enum(data, "bay_kind", BAY_KINDS)
    buffer_minutes = opt_int(data, "cleanup_buffer_minutes", default=0, minimum=0)
    rec = new_entity({
        "dealership_id": did,
        "name": name,
        "bay_kind": bay_kind,
        "cleanup_buffer_minutes": buffer_minutes,
    })
    db.store["service_bays"][rec["id"]] = rec
    return created(rec)


@bp.get("/service-bays")
def list_bays():
    _, role = get_auth()
    require_role(role, {"DealerManager", "ServiceAdvisor", "SalesAgent"})
    items = list(db.store["service_bays"].values())
    did = request.args.get("dealership_id")
    if did is not None:
        items = [b for b in items if b["dealership_id"] == did]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@bp.get("/service-bays/<bay_id>")
def get_bay(bay_id):
    _, role = get_auth()
    require_role(role, {"DealerManager", "ServiceAdvisor", "SalesAgent"})
    rec = get_or_404("service_bays", bay_id)
    return ok(rec)
