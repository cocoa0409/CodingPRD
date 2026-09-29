"""Removed-pack logistics: the frozen hazmat declaration, tender and receipt."""
from flask import Blueprint, request

import calc
import cascade
import claim_service as svc
from common import (API_PREFIX, ApiError, CERT_RANK, D, R_ADMIN, R_TECH, READ_ROLES,
                    auth, by_created, db, get_body, invalid, must, new_record, now, ok,
                    ok_list, opt_dec, opt_enum, opt_str, page, pack_modules, pagination,
                    present, refresh_technician, req_dec, req_enum, req_str, touch)

bp = Blueprint("ship", __name__, url_prefix=API_PREFIX)

CONTENTS = ("FULL_PACK", "MODULES_ONLY")
PACKAGING = ("STANDARD_UN_4G", "SP376_STRONG_OUTER")
MODES = ("GROUND", "AIR")
DESTINATIONS = ("REMAN_CENTER", "RECYCLER")
OUTCOMES = ("ACCEPTED", "REJECTED")
DISPOSITIONS = ("REMANUFACTURE", "SCRAP")
REJECTIONS = ("PACKAGING_NONCONFORMANT", "SOC_OUT_OF_LIMIT", "DOCUMENTATION_MISSING")
SHIPPABLE = ("REMOVED", "QUARANTINED")


def _filter_eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


def _claims_touching_pack(pack_id):
    for claim in by_created(list(db.claims.values())):
        if claim["replacement_pack_id"] == pack_id:
            yield claim
            continue
        assessment = db.assessments.get(claim["assessment_id"])
        if assessment is not None and assessment["pack_id"] == pack_id:
            yield claim


@bp.route("/pack-shipments", methods=["POST"])
def create_shipment():
    auth((R_TECH,))
    body = get_body()
    pack_id = req_str(body, "pack_id")
    center_id = req_str(body, "origin_service_center_id")
    technician_id = req_str(body, "certifying_technician_id")
    contents = req_enum(body, "shipment_contents", CONTENTS)
    packaging = req_enum(body, "packaging_spec", PACKAGING)
    soc = req_dec(body, "state_of_charge_pct", 2, minimum="0.00", maximum="100.00")
    mode = opt_enum(body, "transport_mode", MODES, "GROUND")
    destination = opt_enum(body, "destination", DESTINATIONS, "REMAN_CENTER")
    pack = must("packs", pack_id)
    center = must("centers", center_id)
    technician = refresh_technician(must("technicians", technician_id))
    if pack["status"] not in SHIPPABLE:
        raise ApiError("ERR_SHIPMENT_PACK_NOT_REMOVED", 409,
                       "Only a REMOVED or QUARANTINED pack may ship.")
    if center["status"] != "ACTIVE":
        raise ApiError("ERR_CENTER_SHIPPING_SUSPENDED", 409,
                       "The origin center may not tender hazardous freight.")
    if technician["service_center_id"] != center_id:
        raise ApiError("ERR_TECHNICIAN_CENTER_MISMATCH", 422,
                       "The certifying technician does not belong to the origin center.")
    if technician["status"] == "CERT_LAPSED":
        raise ApiError("ERR_TECHNICIAN_CERT_EXPIRED", 409,
                       "The certifying technician's certification has expired.")
    if CERT_RANK[technician["hv_cert_level"]] < CERT_RANK["L2"]:
        raise ApiError("ERR_TECHNICIAN_LEVEL_INSUFFICIENT", 409,
                       "Certifying a hazardous shipment demands an L2 or L3 technician.")
    for claim in _claims_touching_pack(pack_id):
        if (claim["fulfilment_technician_id"] is not None
                and claim["fulfilment_technician_id"] == technician_id):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                           "The technician who removed the pack may not certify its "
                           "shipment.")
    frozen = calc.shipment_hazmat(pack, contents, mode)
    if frozen["hazmat_classification"] == "UN3536" and mode == "AIR":
        raise ApiError("ERR_AIR_TRANSPORT_FORBIDDEN", 409,
                       "A damaged pack may not travel by air.")
    record = new_record()
    record.update({
        "pack_id": pack_id,
        "origin_service_center_id": center_id,
        "certifying_technician_id": technician_id,
        "shipment_contents": contents,
        "packaging_spec": packaging,
        "transport_mode": mode,
        "destination": destination,
        "state_of_charge_pct": soc,
        "status": "DRAFT",
        "tendered_at": None,
        "received_at": None,
        "disposition": None,
        "rejection_reason": None,
    })
    record.update(frozen)
    db.shipments[record["id"]] = record
    return ok(record, 201)


@bp.route("/pack-shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    auth(READ_ROLES)
    return ok(must("shipments", shipment_id))


@bp.route("/pack-shipments", methods=["GET"])
def list_shipments():
    auth(READ_ROLES)
    limit, offset = pagination()
    rows = by_created(list(db.shipments.values()))
    for field in ("pack_id", "origin_service_center_id", "certifying_technician_id",
                  "status", "hazmat_classification"):
        rows = _filter_eq(rows, field, request.args.get(field))
    window, total = page(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/pack-shipments/<shipment_id>/tender", methods=["POST"])
def tender(shipment_id):
    role, user_id = auth((R_TECH,), actor_required=True)
    body = get_body()
    opt_str(body, "carrier_reference")
    shipment = must("shipments", shipment_id)
    if shipment["status"] != "DRAFT":
        raise ApiError("ERR_SHIPMENT_NOT_TENDERED", 409,
                       "Only a DRAFT shipment may be tendered.")
    center = db.centers[shipment["origin_service_center_id"]]
    technician = refresh_technician(db.technicians[shipment["certifying_technician_id"]])
    if center["status"] != "ACTIVE":
        raise ApiError("ERR_CENTER_SHIPPING_SUSPENDED", 409,
                       "The origin center may no longer tender hazardous freight.")
    if technician["status"] == "CERT_LAPSED":
        raise ApiError("ERR_TECHNICIAN_CERT_EXPIRED", 409,
                       "The certifying technician's certification has expired.")
    if shipment["packaging_spec"] != shipment["required_packaging_spec"]:
        raise ApiError("ERR_PACKAGING_NONCONFORMANT", 409,
                       "The packaging does not conform to the frozen declaration.")
    if D(shipment["state_of_charge_pct"]) > D(shipment["soc_limit_pct"]):
        raise ApiError("ERR_SOC_LIMIT_EXCEEDED", 409,
                       "The state of charge exceeds the declared limit.")
    shipment["status"] = "TENDERED"
    shipment["tendered_at"] = now()
    touch(shipment)
    return ok(shipment)


@bp.route("/pack-shipments/<shipment_id>/receive", methods=["POST"])
def receive(shipment_id):
    auth((R_ADMIN,))
    body = get_body()
    outcome = req_enum(body, "outcome", OUTCOMES)
    disposition = opt_enum(body, "disposition", DISPOSITIONS)
    rejection_reason = opt_enum(body, "rejection_reason", REJECTIONS)
    refurb = opt_dec(body, "refurb_soh_pct", 2, None, minimum=0, maximum=100)
    if outcome == "ACCEPTED":
        if disposition is None:
            raise invalid("disposition is required to accept a shipment.")
        if rejection_reason is not None:
            raise invalid("rejection_reason must be absent on an acceptance.")
    else:
        if rejection_reason is None:
            raise invalid("rejection_reason is required to reject a shipment.")
        if disposition is not None:
            raise invalid("disposition must be absent on a rejection.")
    shipment = must("shipments", shipment_id)
    if shipment["status"] != "TENDERED":
        raise ApiError("ERR_SHIPMENT_NOT_TENDERED", 409,
                       "Only a TENDERED shipment may be received.")
    pack = db.packs[shipment["pack_id"]]
    center = db.centers[shipment["origin_service_center_id"]]
    was_quarantined = pack["status"] == "QUARANTINED"
    if outcome == "ACCEPTED":
        if disposition == "REMANUFACTURE":
            if shipment["destination"] != "REMAN_CENTER":
                raise invalid("A REMANUFACTURE disposition requires a REMAN_CENTER "
                              "destination.")
            if refurb is None:
                raise invalid("refurb_soh_pct is required for a REMANUFACTURE "
                              "disposition.")
        elif shipment["destination"] != "RECYCLER":
            raise invalid("A SCRAP disposition requires a RECYCLER destination.")
    shipment["received_at"] = now()
    if outcome == "REJECTED":
        shipment["status"] = "REJECTED"
        shipment["rejection_reason"] = rejection_reason
        touch(shipment)
        cascade.shipment_rejection_cascade(pack, center)
        return ok(shipment)
    shipment["status"] = "RECEIVED"
    shipment["disposition"] = disposition
    touch(shipment)
    if disposition == "REMANUFACTURE":
        pack["status"] = "STOCK"
        pack["pack_type"] = "REMANUFACTURED"
        pack["remanufacture_count"] = pack["remanufacture_count"] + 1
        pack["refurb_soh_pct"] = refurb
        pack["damaged_defective"] = False
        pack["faulted_module_count"] = 0
        touch(pack)
        for module in pack_modules(pack["id"]):
            if module["status"] != "HEALTHY" or module["thermal_runaway_flag"]:
                module["status"] = "HEALTHY"
                module["thermal_runaway_flag"] = False
                touch(module)
        cascade.refresh_reman_stock()
    else:
        pack["status"] = "SCRAPPED"
        pack["hazmat_classification"] = None
        pack["faulted_module_count"] = 0
        touch(pack)
        for module in pack_modules(pack["id"]):
            if module["status"] != "REPLACED":
                module["status"] = "REPLACED"
                touch(module)
        cascade.refresh_reman_stock()
    if was_quarantined:
        cascade.lower_hazmat_hold(center)
    return ok(shipment)
