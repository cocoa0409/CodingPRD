"""Package specifications and the cushioning safety margin (PRD §3.2)."""
from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role, forbid_unless_owner
from response import success_object
from services.calculations import cushion_required_ild
from services.common import (
    body, get_or_404, get_single, list_many, opt_int, opt_num, owner_of_spec,
    pub, req_int, req_num, req_str, stamp_new, touch,
)
from services.workflows import return_spec_for_revision

bp = Blueprint("package_specs", __name__)

SPEC_STATUSES = ("DRAFT", "SUBMITTED", "IN_VALIDATION", "VALIDATED", "APPROVED")


def _validate_spec_body(data, partial=False):
    """Validate spec fields; returns a dict of validated values (present keys only)."""
    out = {}
    if not partial:
        out["customer_id"] = req_str(data, "customer_id")
        out["material_id"] = req_str(data, "material_id")
        out["part_name"] = req_str(data, "part_name")
        out["part_length_in"] = req_num(data, "part_length_in", minimum=0, strict_min=True)
        out["part_width_in"] = req_num(data, "part_width_in", minimum=0, strict_min=True)
        out["product_weight_lb"] = req_num(data, "product_weight_lb", minimum=0, strict_min=True)
        out["required_drop_height_in"] = req_int(data, "required_drop_height_in", minimum=0)
        out["max_fragility_g"] = req_int(data, "max_fragility_g", minimum=0)
    else:
        if "material_id" in data and data["material_id"] is not None:
            out["material_id"] = req_str(data, "material_id")
        if "part_length_in" in data and data["part_length_in"] is not None:
            out["part_length_in"] = req_num(data, "part_length_in", minimum=0, strict_min=True)
        if "part_width_in" in data and data["part_width_in"] is not None:
            out["part_width_in"] = req_num(data, "part_width_in", minimum=0, strict_min=True)
        if "product_weight_lb" in data and data["product_weight_lb"] is not None:
            out["product_weight_lb"] = req_num(data, "product_weight_lb", minimum=0, strict_min=True)
        if "required_drop_height_in" in data and data["required_drop_height_in"] is not None:
            out["required_drop_height_in"] = req_int(data, "required_drop_height_in", minimum=0)
        if "max_fragility_g" in data and data["max_fragility_g"] is not None:
            out["max_fragility_g"] = req_int(data, "max_fragility_g", minimum=0)
    return out


@bp.route("/package-specs", methods=["POST"])
def create_spec():
    user_id, role = get_auth_context()
    require_role(role, ("SalesEngineer",))
    data = body()
    vals = _validate_spec_body(data)
    get_or_404(db.customers, vals["customer_id"], "Customer")
    get_or_404(db.materials, vals["material_id"], "Material")
    rec = stamp_new({
        **vals,
        "required_ild_lb": cushion_required_ild(vals["product_weight_lb"], vals["required_drop_height_in"]),
        "revision_no": 1,
        "status": "DRAFT",
        "signed_off_at": None,
    })
    db.package_specs[rec["id"]] = rec
    return success_object(pub(rec), 201)


@bp.route("/package-specs", methods=["GET"])
def list_specs():
    return list_many(db.package_specs, owner_of_spec, ("customer_id", "material_id", "status"))


@bp.route("/package-specs/<rid>", methods=["GET"])
def get_spec(rid):
    return get_single(db.package_specs, rid, owner_of_spec, "PackageSpec")


@bp.route("/package-specs/<rid>", methods=["PATCH"])
def update_spec(rid):
    user_id, role = get_auth_context()
    require_role(role, ("SalesEngineer",))
    data = body()
    vals = _validate_spec_body(data, partial=True)
    rec = get_or_404(db.package_specs, rid, "PackageSpec")
    if "material_id" in vals:
        get_or_404(db.materials, vals["material_id"], "Material")
    if rec["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE, "Only DRAFT package specs may be edited", 409)
    recompute = ("product_weight_lb" in vals) or ("required_drop_height_in" in vals)
    rec.update(vals)
    if recompute:
        rec["required_ild_lb"] = cushion_required_ild(rec["product_weight_lb"], rec["required_drop_height_in"])
    touch(rec)
    return success_object(pub(rec))


@bp.route("/package-specs/<rid>/submit", methods=["POST"])
def submit_spec(rid):
    user_id, role = get_auth_context()
    require_role(role, ("SalesEngineer",))
    rec = get_or_404(db.package_specs, rid, "PackageSpec")
    if rec["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot submit a spec in {rec['status']}", 409)
    material = db.materials.get(rec["material_id"])
    if material is None or material["ild_lb_25"] < rec["required_ild_lb"]:
        raise ApiError(
            errors.ERR_ILD_SAFETY_MARGIN,
            "Material ild_lb_25 is below the spec's required_ild_lb",
            422,
        )
    rec["status"] = "SUBMITTED"
    touch(rec)
    return success_object(pub(rec))


@bp.route("/package-specs/<rid>/begin-validation", methods=["POST"])
def begin_validation(rid):
    user_id, role = get_auth_context()
    require_role(role, ("QualityEngineer",))
    rec = get_or_404(db.package_specs, rid, "PackageSpec")
    if rec["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot begin validation from {rec['status']}", 409)
    rec["status"] = "IN_VALIDATION"
    touch(rec)
    return success_object(pub(rec))


@bp.route("/package-specs/<rid>/return-for-revision", methods=["POST"])
def return_for_revision(rid):
    user_id, role = get_auth_context()
    require_role(role, ("QualityEngineer",))
    rec = get_or_404(db.package_specs, rid, "PackageSpec")
    if rec["status"] not in ("IN_VALIDATION", "VALIDATED"):
        raise ApiError(
            errors.ERR_INVALID_STATE,
            f"Cannot return for revision from {rec['status']}",
            409,
        )
    return_spec_for_revision(rec)
    return success_object(pub(rec))


@bp.route("/package-specs/<rid>/approve", methods=["POST"])
def approve_spec(rid):
    user_id, role = get_auth_context()
    require_role(role, ("Customer",))
    rec = get_or_404(db.package_specs, rid, "PackageSpec")
    forbid_unless_owner(role, user_id, rec["customer_id"])
    if rec["status"] != "VALIDATED":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot approve a spec in {rec['status']}", 409)
    from services.common import now_iso
    rec["status"] = "APPROVED"
    rec["signed_off_at"] = now_iso()
    touch(rec)
    return success_object(pub(rec))
