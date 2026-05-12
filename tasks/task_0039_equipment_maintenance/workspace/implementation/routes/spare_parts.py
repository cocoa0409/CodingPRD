"""SparePart routes."""
from flask import Blueprint

from db import db, new_id
from errors import ERR_BAD_REQUEST, raise_err
from middleware import require_role
from response import success_object
from services.calculations import replenish_eval
from services.common import (
    bump_version,
    check_version,
    get_json_body,
    get_site_or_404,
    get_spare_part_or_404,
)
from services.serialize import serialize_spare_part

bp = Blueprint("spare_parts", __name__)


@bp.route("/sites/<site_id>/spare-parts", methods=["POST"])
def create_spare_part(site_id):
    require_role(["Storekeeper"])
    get_site_or_404(site_id)
    body = get_json_body()

    for f in ["sku", "name", "unit_cost_cents", "reorder_point"]:
        if f not in body or body.get(f) in (None, ""):
            raise_err(ERR_BAD_REQUEST, f"{f} is required")

    sku = body["sku"]
    if not isinstance(sku, str) or not sku.strip():
        raise_err(ERR_BAD_REQUEST, "sku must be a non-empty string")
    for sp in db.spare_parts_for_site(site_id):
        if sp["sku"] == sku:
            raise_err(ERR_BAD_REQUEST, "sku must be unique per site")

    uc = body["unit_cost_cents"]
    if not isinstance(uc, int) or isinstance(uc, bool) or uc < 0:
        raise_err(ERR_BAD_REQUEST, "unit_cost_cents must be a non-negative integer")

    rp = body["reorder_point"]
    if not isinstance(rp, int) or isinstance(rp, bool) or rp < 0:
        raise_err(ERR_BAD_REQUEST, "reorder_point must be a non-negative integer")

    soh = body.get("stock_on_hand", 0)
    if not isinstance(soh, int) or isinstance(soh, bool) or soh < 0:
        raise_err(ERR_BAD_REQUEST, "stock_on_hand must be a non-negative integer")

    name = body["name"]
    if not isinstance(name, str) or not name.strip():
        raise_err(ERR_BAD_REQUEST, "name must be a non-empty string")

    sid = new_id()
    clock = db.site_clock(site_id)
    sp = {
        "id": sid,
        "created_at": clock,
        "updated_at": clock,
        "version": 1,
        "site_id": site_id,
        "sku": sku,
        "name": name,
        "unit_cost_cents": uc,
        "stock_on_hand": soh,
        "stock_reserved": 0,
        "reorder_point": rp,
        "replenish_pending": False,
    }
    replenish_eval(sp)
    db.spare_parts[sid] = sp
    return success_object(serialize_spare_part(sp), 201)


@bp.route("/sites/<site_id>/spare-parts/<part_id>", methods=["GET"])
def get_spare_part(site_id, part_id):
    require_role(["Any"])
    get_site_or_404(site_id)
    sp = get_spare_part_or_404(site_id, part_id)
    return success_object(serialize_spare_part(sp))


@bp.route("/sites/<site_id>/spare-parts/<part_id>", methods=["PATCH"])
def patch_spare_part(site_id, part_id):
    require_role(["Storekeeper"])
    get_site_or_404(site_id)
    sp = get_spare_part_or_404(site_id, part_id)
    body = get_json_body()
    check_version(sp, body)

    if "unit_cost_cents" in body:
        v = body["unit_cost_cents"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise_err(ERR_BAD_REQUEST, "unit_cost_cents must be a non-negative integer")
        sp["unit_cost_cents"] = v

    if "reorder_point" in body:
        v = body["reorder_point"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise_err(ERR_BAD_REQUEST, "reorder_point must be a non-negative integer")
        sp["reorder_point"] = v

    if "stock_delta" in body:
        v = body["stock_delta"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise_err(ERR_BAD_REQUEST, "stock_delta must be integer")
        # Spec says "stock_delta>0 increases stock_on_hand (replenishment delivery)"
        if v <= 0:
            raise_err(ERR_BAD_REQUEST, "stock_delta must be a positive integer")
        sp["stock_on_hand"] += v

    bump_version(sp, site_id)
    replenish_eval(sp)
    return success_object(serialize_spare_part(sp))
