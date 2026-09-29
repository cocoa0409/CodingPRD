"""Part specifications (PRD 3.1)."""

from flask import Blueprint, g

import enums
from db import db, new_record, touch
from middleware import ANY_ROLE, endpoint
from response import created, ok
from services import calc
from services.lookup import part_spec_or_404, require_unique, snapshot_part_spec
from validate import (
    field_enum,
    field_enum_list,
    field_int,
    field_num,
    field_str,
)

bp = Blueprint("part_specs", __name__)

WRITE_ROLES = ("ProcessEngineer", "PlantAdmin")


def _derive_bake(spec):
    spec["he_bake_required"] = calc.he_bake_required(
        spec["plating_spec"], spec["strength_class"]
    )
    spec["he_bake_min_minutes"] = calc.he_bake_min_minutes(
        spec["plating_spec"], spec["strength_class"]
    )


@bp.post("/part-specs")
@endpoint(WRITE_ROLES)
def create_part_spec():
    body = g.body
    fields = {
        "part_number": field_str(body, "part_number"),
        "thread_designation": field_str(body, "thread_designation"),
        "strength_class": field_enum(body, "strength_class", enums.STRENGTH_CLASSES),
        "qualification_program": field_enum(
            body,
            "qualification_program",
            enums.QUALIFICATION_PROGRAMS,
            required=False,
            default="NONE",
        ),
        "allowed_steel_grades": field_enum_list(
            body, "allowed_steel_grades", enums.STEEL_GRADES
        ),
        "blank_mass_g": field_num(body, "blank_mass_g", exclusive_min=0),
        "scrap_allowance_pct": field_num(
            body,
            "scrap_allowance_pct",
            required=False,
            default=None,
            minimum=0,
            maximum="0.20",
        ),
        "station_count_required": field_int(body, "station_count_required", minimum=1),
        "thread_timing": field_enum(body, "thread_timing", enums.THREAD_TIMINGS),
        "required_secondary_ops": field_enum_list(
            body,
            "required_secondary_ops",
            enums.SECONDARY_OP_TYPES,
            must_contain="THREAD_ROLL",
        ),
        "min_core_hardness_hv": field_num(body, "min_core_hardness_hv"),
        "max_core_hardness_hv": field_num(body, "max_core_hardness_hv"),
        "max_decarb_depth_mm": field_num(body, "max_decarb_depth_mm"),
        "plating_spec": field_enum(body, "plating_spec", enums.PLATING_SPECS),
        "packaging_mode": field_enum(body, "packaging_mode", enums.PACKAGING_MODES),
        "nominal_pack_count": field_int(body, "nominal_pack_count", minimum=1),
        "pieces_per_kg": field_num(body, "pieces_per_kg", exclusive_min=0),
        "count_tolerance_pct": field_num(
            body, "count_tolerance_pct", required=False, default=None, minimum=0
        ),
        "proof_load_kn": field_num(body, "proof_load_kn"),
    }
    if fields["scrap_allowance_pct"] is None:
        fields["scrap_allowance_pct"] = calc.D("0.05")
    if fields["count_tolerance_pct"] is None:
        fields["count_tolerance_pct"] = calc.D("0.02")

    require_unique("part_specs", "part_number", fields["part_number"])

    spec = new_record(fields)
    _derive_bake(spec)
    db.part_specs[spec["id"]] = spec
    snapshot_part_spec(spec)
    return created(spec)


@bp.get("/part-specs/<spec_id>")
@endpoint(ANY_ROLE)
def get_part_spec(spec_id):
    return ok(part_spec_or_404(spec_id))


@bp.patch("/part-specs/<spec_id>")
@endpoint(WRITE_ROLES)
def patch_part_spec(spec_id):
    body = g.body
    updates = {}

    def maybe(name, value):
        if name in body and body[name] is not None:
            updates[name] = value

    # PRD 3.1: a revision may touch exactly these seven fields, each optional.
    maybe("min_core_hardness_hv", field_num(body, "min_core_hardness_hv", required=False))
    maybe("max_core_hardness_hv", field_num(body, "max_core_hardness_hv", required=False))
    maybe("max_decarb_depth_mm", field_num(body, "max_decarb_depth_mm", required=False))
    maybe(
        "nominal_pack_count",
        field_int(body, "nominal_pack_count", required=False, minimum=1),
    )
    maybe(
        "count_tolerance_pct",
        field_num(body, "count_tolerance_pct", required=False, minimum=0),
    )
    maybe(
        "plating_spec",
        field_enum(body, "plating_spec", enums.PLATING_SPECS, required=False),
    )
    maybe("proof_load_kn", field_num(body, "proof_load_kn", required=False))

    spec = part_spec_or_404(spec_id)
    spec.update(updates)
    _derive_bake(spec)
    touch(spec)
    snapshot_part_spec(spec)
    return ok(spec)
