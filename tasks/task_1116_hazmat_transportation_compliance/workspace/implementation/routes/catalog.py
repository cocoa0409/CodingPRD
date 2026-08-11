"""HazmatMaterial and PackagingSpec catalog endpoints."""

from flask import Blueprint, request

import errors
import serializers
from db import stamp_new, store, touch
from envelope import ok
from listing import page_out
from validators import (
    CATEGORIES,
    HAZARD_CLASSES,
    PACKING_GROUPS,
    PLACARD_TABLES,
    SEGREGATION_GROUPS,
    SPEC_PACKING_GROUPS,
    as_bool,
    as_enum,
    as_enum_list,
    as_num,
    as_str,
    body,
    endpoint,
    get_or_404,
    opt,
    req,
)

bp = Blueprint("catalog", __name__)

ALL_ROLES = ["CarrierAdmin", "ShipperComplianceOfficer", "Regulator"]


@bp.route("/hazmat/hazmat-materials", methods=["POST"])
@endpoint(["Regulator"])
def create_material(uid, role):
    b = body()
    un_na = as_str(req(b, "un_na_number"), "un_na_number")
    psn = as_str(req(b, "proper_shipping_name"), "proper_shipping_name")
    hazard_class = as_enum(req(b, "hazard_class"), "hazard_class", HAZARD_CLASSES)
    packing_group = as_enum(req(b, "packing_group"), "packing_group", PACKING_GROUPS)
    placard_table = as_enum(req(b, "placard_table"), "placard_table", PLACARD_TABLES)
    category = as_enum(req(b, "transport_category"), "transport_category", CATEGORIES)
    rq = as_num(req(b, "reportable_quantity_lbs"), "reportable_quantity_lbs")
    inh = as_bool(opt(b, "is_inhalation_hazard", False), "is_inhalation_hazard")
    seg = as_enum(opt(b, "segregation_group", "SG_NONE"), "segregation_group",
                  SEGREGATION_GROUPS)
    erg = as_str(req(b, "erg_guide_number"), "erg_guide_number")
    for m in store.materials.values():
        if m["un_na_number"] == un_na:
            raise errors.conflict(errors.ERR_DUPLICATE_UN_NA,
                                  "un_na_number already in catalog")
    material = {
        "un_na_number": un_na,
        "proper_shipping_name": psn,
        "hazard_class": hazard_class,
        "packing_group": packing_group,
        "placard_table": placard_table,
        "transport_category": category,
        "reportable_quantity_lbs": rq,
        "is_inhalation_hazard": inh,
        "segregation_group": seg,
        "erg_guide_number": erg,
    }
    stamp_new(material)
    store.materials[material["id"]] = material
    return ok(serializers.material(material), 201)


@bp.route("/hazmat/hazmat-materials", methods=["GET"])
@endpoint(ALL_ROLES)
def list_materials(uid, role):
    rows = list(store.materials.values())
    hazard_class = request.args.get("hazard_class")
    if hazard_class is not None:
        rows = [m for m in rows if m["hazard_class"] == hazard_class]
    placard_table = request.args.get("placard_table")
    if placard_table is not None:
        rows = [m for m in rows if m["placard_table"] == placard_table]
    return page_out(rows, serializers.material)


@bp.route("/hazmat/packaging-specs", methods=["POST"])
@endpoint(["Regulator"])
def create_spec(uid, role):
    b = body()
    spec_code = as_str(req(b, "spec_code"), "spec_code")
    classes = as_enum_list(req(b, "authorized_hazard_classes"),
                           "authorized_hazard_classes", HAZARD_CLASSES)
    max_pg = as_enum(req(b, "max_packing_group"), "max_packing_group",
                     SPEC_PACKING_GROUPS)
    max_qty = as_num(req(b, "max_net_quantity_kg"), "max_net_quantity_kg")
    for s in store.specs.values():
        if s["spec_code"] == spec_code:
            raise errors.conflict(errors.ERR_DUPLICATE_SPEC_CODE,
                                  "spec_code already in catalog")
    spec = {
        "spec_code": spec_code,
        "authorized_hazard_classes": classes,
        "max_packing_group": max_pg,
        "max_net_quantity_kg": max_qty,
        "status": "ACTIVE",
    }
    stamp_new(spec)
    store.specs[spec["id"]] = spec
    return ok(serializers.spec(spec), 201)


@bp.route("/hazmat/packaging-specs", methods=["GET"])
@endpoint(ALL_ROLES)
def list_specs(uid, role):
    rows = list(store.specs.values())
    status = request.args.get("status")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return page_out(rows, serializers.spec)


@bp.route("/hazmat/packaging-specs/<specId>/retire", methods=["POST"])
@endpoint(["Regulator"])
def retire_spec(uid, role, specId):
    spec = store.specs.get(specId)
    if spec is None:
        # No ERR_SPEC_NOT_FOUND exists in the catalog; reuse the spec-state error.
        raise errors.conflict(errors.ERR_SPEC_NOT_ACTIVE, "Packaging spec not found")
    if spec["status"] != "ACTIVE":
        raise errors.conflict(errors.ERR_SPEC_NOT_ACTIVE,
                              "Retire requires spec ACTIVE")
    spec["status"] = "RETIRED"
    touch(spec)
    # Link 1: pre-DOCUMENTED shipments on this spec -> CANCELLED.
    for s in store.shipments.values():
        if s["packaging_spec_id"] == spec["id"] and s["status"] in (
            "DRAFT", "CLASSIFIED", "PACKAGING_VERIFIED",
        ):
            s["status"] = "CANCELLED"
            touch(s)
            # Link 2: that shipment's paper -> VOIDED (caused by cancellation).
            for p in store.papers.values():
                if p["shipment_id"] == s["id"] and p["status"] in (
                    "DRAFT", "CERTIFIED", "UNDER_AMENDMENT",
                ):
                    p["status"] = "VOIDED"
                    touch(p)
    return ok(serializers.spec(spec), 200)
