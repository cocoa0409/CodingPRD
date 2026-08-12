"""Shipment endpoints: pipeline transitions, amendment (OCC), tender."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import errors
import serializers
from db import stamp_new, store, touch
from envelope import ok
from listing import page_out
from validators import (
    as_int,
    as_num,
    as_str,
    body,
    endpoint,
    get_or_404,
    req,
)

bp = Blueprint("shipments", __name__)

ALL_ROLES = ["CarrierAdmin", "ShipperComplianceOfficer", "Regulator"]


def _shipment_or_404(sid):
    return get_or_404(store.shipments, sid, errors.ERR_SHIPMENT_NOT_FOUND,
                      "Shipment")


def normalize_name(name):
    """Uppercase, trim, collapse inner whitespace."""
    return " ".join(name.split()).upper()


def _paper_of(shipment_id):
    for p in store.papers.values():
        if p["shipment_id"] == shipment_id:
            return p
    return None


@bp.route("/hazmat/carriers/<carrierId>/shipments", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def create_shipment(uid, role, carrierId):
    carrier = get_or_404(store.carriers, carrierId, errors.ERR_CARRIER_NOT_FOUND,
                         "Carrier")
    b = body()
    material_id = as_str(req(b, "material_id"), "material_id")
    spec_id = as_str(req(b, "packaging_spec_id"), "packaging_spec_id")
    declared_name = as_str(req(b, "declared_shipping_name"), "declared_shipping_name")
    quantity = as_num(req(b, "quantity_kg"), "quantity_kg")
    if quantity <= 0:
        raise errors.invalid("quantity_kg must be > 0")
    declared_value = as_int(req(b, "declared_value_cents"), "declared_value_cents")
    if declared_value < 0:
        raise errors.invalid("declared_value_cents must be >= 0")
    material = store.materials.get(material_id)
    if material is None:
        raise errors.ApiError(errors.ERR_INVALID_REFERENCE, 422,
                              "material_id does not reference an existing material")
    spec = store.specs.get(spec_id)
    if spec is None:
        raise errors.ApiError(errors.ERR_INVALID_REFERENCE, 422,
                              "packaging_spec_id does not reference an existing spec")
    if carrier["registration_status"] != "APPROVED_ACTIVE":
        raise errors.conflict(errors.ERR_CARRIER_NOT_ACTIVE,
                              "Carrier must be APPROVED_ACTIVE to create shipments")
    if material["transport_category"] not in carrier["hazmat_categories"]:
        raise errors.conflict(errors.ERR_CATEGORY_NOT_AUTHORIZED,
                              "Material transport_category is not carrier-authorized")
    shipment = {
        "carrier_id": carrier["id"],
        "material_id": material_id,
        "packaging_spec_id": spec_id,
        "driver_id": None,
        "declared_shipping_name": declared_name,
        "normalized_shipping_name": None,
        "quantity_kg": quantity,
        "declared_value_cents": declared_value,
        "status": "DRAFT",
        "classified_by_user_id": None,
        "pinned_security_plan_id": None,
        "pinned_security_plan_version": None,
    }
    stamp_new(shipment)
    store.shipments[shipment["id"]] = shipment
    return ok(serializers.shipment(shipment), 201)


def _shipment_filters(rows):
    status = request.args.get("status")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    material_id = request.args.get("material_id")
    if material_id is not None:
        rows = [s for s in rows if s["material_id"] == material_id]
    spec_id = request.args.get("packaging_spec_id")
    if spec_id is not None:
        rows = [s for s in rows if s["packaging_spec_id"] == spec_id]
    driver_id = request.args.get("driver_id")
    if driver_id is not None:
        rows = [s for s in rows if s["driver_id"] == driver_id]
    return rows


@bp.route("/hazmat/carriers/<carrierId>/shipments", methods=["GET"])
@endpoint(ALL_ROLES)
def list_carrier_shipments(uid, role, carrierId):
    carrier = get_or_404(store.carriers, carrierId, errors.ERR_CARRIER_NOT_FOUND,
                         "Carrier")
    rows = [s for s in store.shipments.values() if s["carrier_id"] == carrier["id"]]
    return page_out(_shipment_filters(rows), serializers.shipment)


@bp.route("/hazmat/shipments", methods=["GET"])
@endpoint(ALL_ROLES)
def list_shipments(uid, role):
    rows = list(store.shipments.values())
    carrier_id = request.args.get("carrier_id")
    if carrier_id is not None:
        rows = [s for s in rows if s["carrier_id"] == carrier_id]
    return page_out(_shipment_filters(rows), serializers.shipment)


@bp.route("/hazmat/shipments/<shipmentId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_shipment(uid, role, shipmentId):
    return ok(serializers.shipment(_shipment_or_404(shipmentId)), 200)


@bp.route("/hazmat/shipments/<shipmentId>", methods=["PATCH"])
@endpoint(["ShipperComplianceOfficer"])
def amend_shipment(uid, role, shipmentId):
    shipment = _shipment_or_404(shipmentId)
    b = body()
    expected = as_int(req(b, "expected_shipment_version"),
                      "expected_shipment_version")
    # Optional field shape checks (request shape precedes OCC per §2.8).
    new_material = None
    new_spec = None
    new_name = None
    new_qty = None
    new_value = None
    if "material_id" in b and b["material_id"] is not None:
        new_material = as_str(b["material_id"], "material_id")
    if "packaging_spec_id" in b and b["packaging_spec_id"] is not None:
        new_spec = as_str(b["packaging_spec_id"], "packaging_spec_id")
    if "declared_shipping_name" in b and b["declared_shipping_name"] is not None:
        new_name = as_str(b["declared_shipping_name"], "declared_shipping_name")
    if "quantity_kg" in b and b["quantity_kg"] is not None:
        new_qty = as_num(b["quantity_kg"], "quantity_kg")
        if new_qty <= 0:
            raise errors.invalid("quantity_kg must be > 0")
    if "declared_value_cents" in b and b["declared_value_cents"] is not None:
        new_value = as_int(b["declared_value_cents"], "declared_value_cents")
        if new_value < 0:
            raise errors.invalid("declared_value_cents must be >= 0")
    # Body FK references (priority 5).
    if new_material is not None and new_material not in store.materials:
        raise errors.ApiError(errors.ERR_INVALID_REFERENCE, 422,
                              "material_id does not reference an existing material")
    if new_spec is not None and new_spec not in store.specs:
        raise errors.ApiError(errors.ERR_INVALID_REFERENCE, 422,
                              "packaging_spec_id does not reference an existing spec")
    # OCC (priority 6).
    if expected != shipment["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412,
                              "expected_shipment_version does not match the current version")
    # From-state gate (priority 8).
    if shipment["status"] not in ("DRAFT", "CLASSIFIED", "PACKAGING_VERIFIED"):
        raise errors.conflict(errors.ERR_SHIPMENT_NOT_AMENDABLE,
                              "PATCH requires DRAFT, CLASSIFIED, or PACKAGING_VERIFIED")
    classification_changed = False
    if new_material is not None and new_material != shipment["material_id"]:
        shipment["material_id"] = new_material
        classification_changed = True
    if new_spec is not None and new_spec != shipment["packaging_spec_id"]:
        shipment["packaging_spec_id"] = new_spec
        classification_changed = True
    if new_name is not None and new_name != shipment["declared_shipping_name"]:
        shipment["declared_shipping_name"] = new_name
        classification_changed = True
    if new_qty is not None and Decimal(str(new_qty)) != Decimal(str(shipment["quantity_kg"])):
        shipment["quantity_kg"] = new_qty
        classification_changed = True
    if new_value is not None and new_value != shipment["declared_value_cents"]:
        shipment["declared_value_cents"] = new_value
    if classification_changed:
        shipment["status"] = "DRAFT"
        shipment["normalized_shipping_name"] = None
        shipment["classified_by_user_id"] = None
    touch(shipment)
    return ok(serializers.shipment(shipment), 200)


@bp.route("/hazmat/shipments/<shipmentId>/classify", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def classify_shipment(uid, role, shipmentId):
    shipment = _shipment_or_404(shipmentId)
    if shipment["status"] != "DRAFT":
        raise errors.conflict(errors.ERR_SHIPMENT_NOT_DRAFT,
                              "Classify requires DRAFT")
    material = store.materials[shipment["material_id"]]
    normalized = normalize_name(shipment["declared_shipping_name"])
    if normalized != normalize_name(material["proper_shipping_name"]):
        raise errors.ApiError(errors.ERR_SHIPPING_NAME_MISMATCH, 422,
                              "Declared shipping name does not match the material PSN")
    shipment["normalized_shipping_name"] = normalized
    shipment["classified_by_user_id"] = uid
    shipment["status"] = "CLASSIFIED"
    touch(shipment)
    return ok(serializers.shipment(shipment), 200)


@bp.route("/hazmat/shipments/<shipmentId>/verify-packaging", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def verify_packaging(uid, role, shipmentId):
    shipment = _shipment_or_404(shipmentId)
    if shipment["status"] != "CLASSIFIED":
        raise errors.conflict(errors.ERR_SHIPMENT_NOT_CLASSIFIED,
                              "Verify-packaging requires CLASSIFIED")
    spec = store.specs[shipment["packaging_spec_id"]]
    material = store.materials[shipment["material_id"]]
    if spec["status"] != "ACTIVE":
        raise errors.conflict(errors.ERR_SPEC_NOT_ACTIVE,
                              "Packaging spec must be ACTIVE")
    if material["hazard_class"] not in spec["authorized_hazard_classes"]:
        raise errors.conflict(errors.ERR_PACKAGING_CLASS_MISMATCH,
                              "Material hazard class not authorized for this spec")
    if not calc.packing_group_compatible(material["packing_group"],
                                         spec["max_packing_group"]):
        raise errors.conflict(errors.ERR_PACKING_GROUP_INCOMPATIBLE,
                              "Material packing group exceeds spec max_packing_group")
    if Decimal(str(shipment["quantity_kg"])) > Decimal(str(spec["max_net_quantity_kg"])):
        raise errors.conflict(errors.ERR_QUANTITY_EXCEEDS_CAPACITY,
                              "quantity_kg exceeds spec max_net_quantity_kg")
    shipment["status"] = "PACKAGING_VERIFIED"
    touch(shipment)
    return ok(serializers.shipment(shipment), 200)


@bp.route("/hazmat/shipments/<shipmentId>/document", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def document_shipment(uid, role, shipmentId):
    shipment = _shipment_or_404(shipmentId)
    if shipment["status"] != "PACKAGING_VERIFIED":
        raise errors.conflict(errors.ERR_SHIPMENT_NOT_PACKAGING_VERIFIED,
                              "Document requires PACKAGING_VERIFIED")
    paper = _paper_of(shipment["id"])
    if paper is None or paper["status"] != "CERTIFIED":
        raise errors.conflict(errors.ERR_PAPER_NOT_CERTIFIED,
                              "Document requires the shipment's paper CERTIFIED")
    shipment["status"] = "DOCUMENTED"
    touch(shipment)
    return ok(serializers.shipment(shipment), 200)


@bp.route("/hazmat/shipments/<shipmentId>/reject", methods=["POST"])
@endpoint(["Regulator"])
def reject_shipment(uid, role, shipmentId):
    shipment = _shipment_or_404(shipmentId)
    if shipment["status"] != "DOCUMENTED":
        raise errors.conflict(errors.ERR_SHIPMENT_NOT_DOCUMENTED,
                              "Reject requires DOCUMENTED")
    shipment["status"] = "REJECTED"
    touch(shipment)
    paper = _paper_of(shipment["id"])
    if paper is not None and paper["status"] == "CERTIFIED":
        paper["status"] = "UNDER_AMENDMENT"
        paper["amendment_count"] += 1
        touch(paper)
    return ok(serializers.shipment(shipment), 200)


@bp.route("/hazmat/shipments/<shipmentId>/rework", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def rework_shipment(uid, role, shipmentId):
    shipment = _shipment_or_404(shipmentId)
    if shipment["status"] != "REJECTED":
        raise errors.conflict(errors.ERR_SHIPMENT_NOT_REJECTED,
                              "Rework requires REJECTED")
    shipment["status"] = "DRAFT"
    shipment["normalized_shipping_name"] = None
    shipment["classified_by_user_id"] = None
    touch(shipment)
    return ok(serializers.shipment(shipment), 200)


@bp.route("/hazmat/shipments/<shipmentId>/tender", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def tender_shipment(uid, role, shipmentId):
    shipment = _shipment_or_404(shipmentId)
    b = body()
    driver_id = as_str(req(b, "driver_id"), "driver_id")
    carrier = store.carriers[shipment["carrier_id"]]
    material = store.materials[shipment["material_id"]]
    # Gate order per PRD §3.6: carrier active -> shipment state -> plan ->
    # driver reference -> driver qualified -> fiscal.
    if carrier["registration_status"] != "APPROVED_ACTIVE":
        raise errors.conflict(errors.ERR_CARRIER_NOT_ACTIVE,
                              "Tender requires carrier APPROVED_ACTIVE")
    if shipment["status"] not in ("DOCUMENTED", "TENDERED"):
        raise errors.conflict(errors.ERR_SHIPMENT_NOT_DOCUMENTED,
                              "Tender requires DOCUMENTED (or TENDERED re-pin)")
    plan = None
    if calc.material_requires_security_plan(material):
        plan = calc.security_plan_selector(carrier["id"],
                                           material["transport_category"])
        if plan is None:
            raise errors.conflict(errors.ERR_SECURITY_PLAN_REQUIRED,
                                  "No APPROVED in-window security plan covers this category")
    driver = store.drivers.get(driver_id)
    if driver is None or driver["carrier_id"] != shipment["carrier_id"]:
        raise errors.ApiError(errors.ERR_INVALID_REFERENCE, 422,
                              "driver_id does not reference a driver of this carrier")
    if calc.driver_posture(driver) != "QUALIFIED":
        raise errors.conflict(errors.ERR_DRIVER_NOT_QUALIFIED,
                              "Driver qualification_posture is not QUALIFIED")
    if calc.outstanding_balance(carrier["id"]) != 0:
        raise errors.ApiError(errors.ERR_OUTSTANDING_FEES, 402,
                              "Carrier outstanding_balance_cents is not 0")
    shipment["driver_id"] = driver_id
    shipment["pinned_security_plan_id"] = plan["id"] if plan else None
    shipment["pinned_security_plan_version"] = plan["version"] if plan else None
    shipment["status"] = "TENDERED"
    touch(shipment)
    return ok(serializers.shipment(shipment), 200)


@bp.route("/hazmat/shipments/<shipmentId>/cancel", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def cancel_shipment(uid, role, shipmentId):
    shipment = _shipment_or_404(shipmentId)
    if shipment["status"] not in ("DRAFT", "CLASSIFIED", "PACKAGING_VERIFIED"):
        raise errors.conflict(errors.ERR_SHIPMENT_NOT_CANCELLABLE,
                              "Cancel requires DRAFT, CLASSIFIED, or PACKAGING_VERIFIED")
    from_pv = shipment["status"] == "PACKAGING_VERIFIED"
    shipment["status"] = "CANCELLED"
    touch(shipment)
    paper = _paper_of(shipment["id"])
    if paper is not None:
        voidable = ("DRAFT", "CERTIFIED", "UNDER_AMENDMENT") if from_pv else (
            "DRAFT", "UNDER_AMENDMENT")
        if paper["status"] in voidable:
            paper["status"] = "VOIDED"
            touch(paper)
    return ok(serializers.shipment(shipment), 200)


@bp.route("/hazmat/shipments/<shipmentId>/load-items", methods=["GET"])
@endpoint(ALL_ROLES)
def list_shipment_load_items(uid, role, shipmentId):
    shipment = _shipment_or_404(shipmentId)
    rows = [i for i in store.load_items.values()
            if i["shipment_id"] == shipment["id"]]
    return page_out(rows, serializers.load_item)
