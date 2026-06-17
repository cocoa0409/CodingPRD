"""PDI inspection routes (PRD 3.5)."""

from flask import Blueprint, request

import db
from common import (body, new_entity, touch, require_int, paginate, get_or_404,
                    find_dealership)
from middleware import get_auth, require_role
from response import ok, created, ok_list

bp = Blueprint("pdi", __name__)


@bp.post("/pdi-inspections")
def create_pdi():
    user_id, role = get_auth()
    require_role(role, {"ServiceAdvisor"})
    data = body()
    did = data.get("dealership_id")
    find_dealership(did)
    deal = get_or_404("deals", data.get("deal_id"))
    defects = require_int(data, "defects_found", minimum=0)

    unit = db.store["units"][deal["unit_id"]]
    result = "PASS" if (defects == 0 and unit["open_recall_count"] == 0) else "FAIL"

    rec = new_entity({
        "dealership_id": did,
        "deal_id": deal["id"],
        "unit_id": unit["id"],
        "technician_user_id": user_id,
        "defects_found": defects,
        "result": result,
    })
    db.store["pdi_inspections"][rec["id"]] = rec

    # PASS advances a PDI_PENDING deal to WALKTHROUGH.
    if result == "PASS" and deal["sale_status"] == "PDI_PENDING":
        deal["pdi_passed"] = True
        deal["sale_status"] = "WALKTHROUGH"
        touch(deal)
    return created(rec)


@bp.get("/pdi-inspections")
def list_pdi():
    _, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent", "ServiceAdvisor"})
    items = list(db.store["pdi_inspections"].values())
    a = request.args
    for field in ("deal_id", "unit_id", "dealership_id"):
        val = a.get(field)
        if val is not None:
            items = [p for p in items if p.get(field) == val]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@bp.get("/pdi-inspections/<pdi_id>")
def get_pdi(pdi_id):
    _, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent", "ServiceAdvisor"})
    rec = db.store["pdi_inspections"].get(pdi_id)
    if rec is None:
        from errors import ApiError
        raise ApiError("ERR_PDI_INSPECTION_NOT_FOUND", 404, "PDI inspection not found.")
    return ok(rec)
