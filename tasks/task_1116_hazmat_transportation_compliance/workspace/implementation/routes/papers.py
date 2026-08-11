"""ShippingPaper endpoints."""

from flask import Blueprint

import errors
import serializers
from db import stamp_new, store, touch
from envelope import ok
from listing import page_out
from validators import as_bool, as_str, body, endpoint, get_or_404, req

bp = Blueprint("papers", __name__)

ALL_ROLES = ["CarrierAdmin", "ShipperComplianceOfficer", "Regulator"]


def _paper_or_404(paper_id):
    return get_or_404(store.papers, paper_id, errors.ERR_SHIPPING_PAPER_NOT_FOUND,
                      "ShippingPaper")


@bp.route("/hazmat/shipments/<shipmentId>/shipping-papers", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def create_paper(uid, role, shipmentId):
    shipment = get_or_404(store.shipments, shipmentId, errors.ERR_SHIPMENT_NOT_FOUND,
                          "Shipment")
    b = body()
    phone = as_str(req(b, "emergency_contact_phone"), "emergency_contact_phone")
    summary = as_str(req(b, "emergency_response_summary"),
                     "emergency_response_summary")
    signed = as_bool(req(b, "shipper_certification_signed"),
                     "shipper_certification_signed")
    for p in store.papers.values():
        if p["shipment_id"] == shipment["id"]:
            raise errors.conflict(errors.ERR_DUPLICATE_SHIPPING_PAPER,
                                  "Shipment already has a shipping paper")
    paper = {
        "shipment_id": shipment["id"],
        "emergency_contact_phone": phone,
        "er_response_guide_number": None,
        "emergency_response_summary": summary,
        "shipper_certification_signed": signed,
        "certified_by_user_id": None,
        "amendment_count": 0,
        "status": "DRAFT",
    }
    stamp_new(paper)
    store.papers[paper["id"]] = paper
    return ok(serializers.shipping_paper(paper), 201)


@bp.route("/hazmat/shipments/<shipmentId>/shipping-papers", methods=["GET"])
@endpoint(ALL_ROLES)
def list_papers(uid, role, shipmentId):
    shipment = get_or_404(store.shipments, shipmentId, errors.ERR_SHIPMENT_NOT_FOUND,
                          "Shipment")
    rows = [p for p in store.papers.values() if p["shipment_id"] == shipment["id"]]
    return page_out(rows, serializers.shipping_paper)


@bp.route("/hazmat/shipping-papers/<paperId>/certify", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def certify_paper(uid, role, paperId):
    paper = _paper_or_404(paperId)
    if paper["status"] not in ("DRAFT", "UNDER_AMENDMENT"):
        raise errors.conflict(errors.ERR_PAPER_NOT_CERTIFIABLE,
                              "Certify requires DRAFT or UNDER_AMENDMENT")
    if paper["shipper_certification_signed"] is not True:
        raise errors.invalid("shipper_certification_signed must be true to certify")
    shipment = store.shipments[paper["shipment_id"]]
    if uid == shipment["classified_by_user_id"]:
        raise errors.ApiError(errors.ERR_SOD_VIOLATION, 403,
                              "Certifying officer may not be the shipment classifier")
    material = store.materials[shipment["material_id"]]
    paper["certified_by_user_id"] = uid
    paper["er_response_guide_number"] = material["erg_guide_number"]
    paper["status"] = "CERTIFIED"
    touch(paper)
    return ok(serializers.shipping_paper(paper), 200)


@bp.route("/hazmat/shipping-papers/<paperId>/amend", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def amend_paper(uid, role, paperId):
    paper = _paper_or_404(paperId)
    if paper["status"] != "CERTIFIED":
        raise errors.conflict(errors.ERR_PAPER_NOT_CERTIFIED,
                              "Amend requires CERTIFIED")
    b = body()
    if "emergency_contact_phone" in b and b["emergency_contact_phone"] is not None:
        paper["emergency_contact_phone"] = as_str(b["emergency_contact_phone"],
                                                  "emergency_contact_phone")
    if "emergency_response_summary" in b and b["emergency_response_summary"] is not None:
        paper["emergency_response_summary"] = as_str(
            b["emergency_response_summary"], "emergency_response_summary")
    paper["status"] = "UNDER_AMENDMENT"
    paper["amendment_count"] += 1
    touch(paper)
    return ok(serializers.shipping_paper(paper), 200)
