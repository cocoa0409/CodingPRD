"""PalletSpec endpoints: create/list/get/activate/retire."""

from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import (
    require_roles, get_json_body, parse_pagination, paginate,
    req_field, opt_field, as_str, as_int, as_number, as_bool, as_enum,
)
from response import success
from services.calc import compute_board_feet_per_pallet, compute_unit_cube_cuft
from services.helpers import (
    init_common, touch, serialize, serialize_list, sorted_by_creation, get_or_404,
)

bp = Blueprint("specs", __name__)

SPECIES = ("PINE", "OAK", "MIXED")


@bp.post("/pallet-ops/specs")
def create_spec():
    require_roles("PlantManager")
    body = get_json_body()
    spec_code = as_str(req_field(body, "spec_code"), "spec_code")
    length_in = as_number(req_field(body, "length_in"), "length_in", minimum=0, exclusive_min=True)
    width_in = as_number(req_field(body, "width_in"), "width_in", minimum=0, exclusive_min=True)
    height_in = as_number(req_field(body, "height_in"), "height_in", minimum=0, exclusive_min=True)
    board_count = as_int(req_field(body, "board_count"), "board_count", minimum=5)
    lumber_species = as_enum(req_field(body, "lumber_species"), "lumber_species", SPECIES)
    requires_ht = opt_field(body, "requires_heat_treatment_default", False)
    requires_ht = as_bool(requires_ht, "requires_heat_treatment_default")

    if any(s["spec_code"] == spec_code for s in db.specs.values()):
        raise_err("ERR_INVALID_REQUEST", "spec_code must be unique: %s" % spec_code)

    spec = {
        "spec_code": spec_code,
        "length_in": length_in,
        "width_in": width_in,
        "height_in": height_in,
        "board_count": board_count,
        "lumber_species": lumber_species,
        "board_feet_per_pallet": compute_board_feet_per_pallet(length_in, board_count),
        "unit_cube_cuft": compute_unit_cube_cuft(length_in, width_in, height_in),
        "requires_heat_treatment_default": requires_ht,
        "status": "DRAFT",
    }
    init_common(spec)
    db.specs[spec["id"]] = spec
    return success(serialize(spec), status=201)


@bp.get("/pallet-ops/specs")
def list_specs():
    require_roles()
    limit, offset = parse_pagination()
    items = list(db.specs.values())
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    species = request.args.get("lumber_species")
    if species is not None:
        items = [s for s in items if s["lumber_species"] == species]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success(serialize_list(page), pagination=pagination, is_list=True)


@bp.get("/pallet-ops/specs/<sid>")
def get_spec(sid):
    require_roles()
    spec = get_or_404(db.specs, sid, "PalletSpec")
    return success(serialize(spec))


@bp.post("/pallet-ops/specs/<sid>/activate")
def activate_spec(sid):
    require_roles("PlantManager")
    spec = get_or_404(db.specs, sid, "PalletSpec")
    if spec["status"] != "DRAFT":
        raise_err("ERR_SPEC_NOT_DRAFT", "Spec activate requires status == DRAFT")
    spec["status"] = "ACTIVE"
    touch(spec)
    return success(serialize(spec))


@bp.post("/pallet-ops/specs/<sid>/retire")
def retire_spec(sid):
    require_roles("PlantManager")
    spec = get_or_404(db.specs, sid, "PalletSpec")
    if spec["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Spec retire requires status == ACTIVE")
    if any(
        lot["spec_id"] == sid and lot["status"] == "AVAILABLE"
        for lot in db.inventory_lots.values()
    ):
        raise_err("ERR_SPEC_HAS_STOCK", "Spec retire blocked by AVAILABLE inventory lots")
    if any(
        line["spec_id"] == sid and line["status"] in ("OPEN", "ALLOCATED")
        for line in db.order_lines.values()
    ):
        raise_err("ERR_SPEC_ON_OPEN_ORDER", "Spec retire blocked by OPEN/ALLOCATED order lines")
    spec["status"] = "RETIRED"
    touch(spec)
    return success(serialize(spec))
