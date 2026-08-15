"""Foam material catalogue (PRD §3.1). Edits never retroactively alter values
pinned elsewhere (inventory-program locked cost, scheduled drop-test limits)."""
from flask import Blueprint

import db
from middleware import get_auth_context, require_role
from response import success_object
from services.common import (
    body, get_or_404, get_single, opt_int, opt_num, owner_of_material, pub,
    req_bool, req_enum, req_int, req_num, stamp_new, touch,
)

bp = Blueprint("materials", __name__)

FOAM_FAMILIES = ("PE", "EPE", "PU", "XLPE")


@bp.route("/materials", methods=["POST"])
def create_material():
    user_id, role = get_auth_context()
    require_role(role, ("PlantManager",))
    data = body()
    rec = stamp_new({
        "foam_family": req_enum(data, "foam_family", FOAM_FAMILIES),
        "density_pcf": req_num(data, "density_pcf", minimum=0, strict_min=True),
        "ild_lb_25": req_int(data, "ild_lb_25", minimum=0),
        "sheet_length_in": req_num(data, "sheet_length_in", minimum=0, strict_min=True),
        "sheet_width_in": req_num(data, "sheet_width_in", minimum=0, strict_min=True),
        "sheet_thickness_in": req_num(data, "sheet_thickness_in", minimum=0, strict_min=True),
        "cost_per_board_ft_cents": req_int(data, "cost_per_board_ft_cents", minimum=0),
        "recyclable": req_bool(data, "recyclable"),
        "scrap_credit_per_lb_cents": req_int(data, "scrap_credit_per_lb_cents", minimum=0),
    })
    db.materials[rec["id"]] = rec
    return success_object(pub(rec), 201)


@bp.route("/materials/<rid>", methods=["GET"])
def get_material(rid):
    return get_single(db.materials, rid, owner_of_material, "Material")


@bp.route("/materials/<rid>", methods=["PATCH"])
def update_material(rid):
    user_id, role = get_auth_context()
    require_role(role, ("PlantManager",))
    data = body()
    cost = opt_int(data, "cost_per_board_ft_cents", None, minimum=0)
    ild = opt_int(data, "ild_lb_25", None, minimum=0)
    density = opt_num(data, "density_pcf", None, minimum=0, strict_min=True)
    scrap_rate = opt_int(data, "scrap_credit_per_lb_cents", None, minimum=0)
    rec = get_or_404(db.materials, rid, "Material")
    changed = False
    if cost is not None:
        rec["cost_per_board_ft_cents"] = cost
        changed = True
    if ild is not None:
        rec["ild_lb_25"] = ild
        changed = True
    if density is not None:
        rec["density_pcf"] = density
        changed = True
    if scrap_rate is not None:
        rec["scrap_credit_per_lb_cents"] = scrap_rate
        changed = True
    if changed:
        touch(rec)
    return success_object(pub(rec))
