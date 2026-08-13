"""Charge-scoped child resources: ChargePiece, RetentionAssay, DripPadLog,
WarrantyRegistration (PRD sections 3.6-3.8)."""

from flask import Blueprint

import calc
from db import store, new_entity, touch, public, fmt_ts
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_ENUM,
    ERR_PLANT_NOT_LICENSED,
    ERR_INVALID_STATE,
    ERR_CHARGE_NOT_TAGGED,
    ERR_ASSAY_CYCLE_MISMATCH,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_CUSTOMER_CREDIT_HOLD,
    ERR_STALE_VERSION,
)
from middleware import authenticate, authorize
from response import success
from util import (
    body_json, req_field, as_str, as_number, as_int, as_bool, as_enum, parse_ts,
    resolve_plant, resolve_charge, resolve_piece, resolve_assay,
    resolve_drip_log, resolve_warranty, paginate, query_filter, query_bool,
)

bp = Blueprint("charge_children", __name__)

PIECE_READ_ROLES = ["PlantOperator", "LabTechnician", "QualityManager", "QualityAgencyInspector", "ComplianceOfficer"]
ASSAY_READ_ROLES = ["LabTechnician", "QualityManager", "QualityAgencyInspector", "ComplianceOfficer", "PlantOperator"]
DRIP_READ_ROLES = ["PlantOperator", "QualityManager", "QualityAgencyInspector", "ComplianceOfficer", "LabTechnician"]
WARRANTY_READ_ROLES = ["PlantOperator", "QualityManager", "AccountsReceivable", "ComplianceOfficer", "QualityAgencyInspector"]

ASSAY_METHODS = {"XYLENE_EXTRACTION", "ASHING", "TITRATION"}
RECORDED_BY = {"PLANT_LAB", "THIRD_PARTY_AGENCY"}
WARRANTY_TERMS = (5, 25, 50)


# --- ChargePiece ---

@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/pieces", methods=["GET"])
def list_pieces(plantId, chargeId):
    _, role = authenticate()
    authorize(role, PIECE_READ_ROLES)
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)
    items = [p for p in store.pieces.values() if p["charge_id"] == charge["id"]]
    status = query_filter("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/pieces/<pieceId>", methods=["GET"])
def get_piece(plantId, chargeId, pieceId):
    _, role = authenticate()
    authorize(role, PIECE_READ_ROLES)
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)
    return success(public(resolve_piece(pieceId, charge)))


@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/pieces/<pieceId>/incise", methods=["POST"])
def incise_piece(plantId, chargeId, pieceId):
    _, role = authenticate()
    authorize(role, ["PlantOperator"])
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)
    piece = resolve_piece(pieceId, charge)
    if charge["status"] not in ("STAGED", "IN_CYLINDER"):
        raise ApiError(ERR_INVALID_STATE, 409, "Incising requires parent Charge status STAGED or IN_CYLINDER")
    if not charge["requires_incising"]:
        raise ApiError(ERR_INVALID_STATE, 409, "Incising requires parent Charge requires_incising == true")
    if piece["status"] != "RAW":
        raise ApiError(ERR_INVALID_STATE, 409, "Incising requires piece status RAW")
    piece["incised"] = True
    piece["status"] = "INCISED"
    touch(piece)
    return success(public(piece))


# --- RetentionAssay ---

@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/retention-assays", methods=["POST"])
def create_assay(plantId, chargeId):
    body = body_json()
    cycle_id = as_str(req_field(body, "cycle_id"), "cycle_id")
    assay_method = as_enum(req_field(body, "assay_method"), "assay_method", ASSAY_METHODS)
    sample_count = as_int(req_field(body, "sample_count"), "sample_count")
    mean_retention = as_number(req_field(body, "mean_retention_pcf"), "mean_retention_pcf")
    min_sample = as_number(req_field(body, "min_sample_retention_pcf"), "min_sample_retention_pcf")
    recorded_by = as_enum(req_field(body, "recorded_by_agency"), "recorded_by_agency", RECORDED_BY)
    recorded_at_raw = req_field(body, "recorded_at")
    recorded_at = parse_ts(recorded_at_raw, "recorded_at")
    _, role = authenticate()
    authorize(role, ["LabTechnician"])
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)
    if charge["status"] != "CYCLE_COMPLETE":
        raise ApiError(ERR_INVALID_STATE, 409, "Retention assay requires charge status CYCLE_COMPLETE")
    cycle = store.cycles.get(cycle_id)
    if cycle is None or cycle["charge_id"] != charge["id"]:
        raise ApiError(ERR_ASSAY_CYCLE_MISMATCH, 422, "cycle_id must reference a TreatmentCycle belonging to this charge")

    mean_3 = calc.round3(mean_retention)
    min_3 = calc.round3(min_sample)
    threshold, outcome = calc.assay_outcome(charge["target_retention_pcf"], mean_3, min_3)

    assay = new_entity(with_version=False)
    assay.update({
        "charge_id": charge["id"],
        "cycle_id": cycle["id"],
        "assay_method": assay_method,
        "sample_count": sample_count,
        "mean_retention_pcf": mean_3,
        "min_sample_retention_pcf": min_3,
        "recorded_by_agency": recorded_by,
        "pass_threshold_pcf": threshold,
        "outcome": outcome,
        "recorded_at": fmt_ts(recorded_at),
    })
    store.assays[assay["id"]] = assay

    pieces = [p for p in store.pieces.values() if p["charge_id"] == charge["id"]]
    charge["final_retention_pcf"] = calc.final_retention(charge, pieces, mean_3)
    charge["status"] = "ASSAYED_PASS" if outcome == "PASS" else "ASSAYED_FAIL"
    touch(charge)
    piece_target = "ASSAYED_PASS" if outcome == "PASS" else "ASSAYED_FAIL"
    for piece in pieces:
        if piece["status"] == "TREATED":
            piece["status"] = piece_target
            touch(piece)
    return success(public(assay), status=201)


@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/retention-assays", methods=["GET"])
def list_assays(plantId, chargeId):
    _, role = authenticate()
    authorize(role, ASSAY_READ_ROLES)
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)
    items = [a for a in store.assays.values() if a["charge_id"] == charge["id"]]
    cycle_id = query_filter("cycle_id")
    if cycle_id is not None:
        items = [a for a in items if a["cycle_id"] == cycle_id]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/retention-assays/<assayId>", methods=["GET"])
def get_assay(plantId, chargeId, assayId):
    _, role = authenticate()
    authorize(role, ASSAY_READ_ROLES)
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)
    return success(public(resolve_assay(assayId, charge)))


# --- DripPadLog ---

@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/drip-pad-logs", methods=["POST"])
def create_drip_log(plantId, chargeId):
    body = body_json()
    pad_code = as_str(req_field(body, "pad_code"), "pad_code")
    entered = parse_ts(req_field(body, "entered_pad_at"), "entered_pad_at")
    exited = parse_ts(req_field(body, "exited_pad_at"), "exited_pad_at")
    drip_volume = as_number(req_field(body, "drip_volume_liters"), "drip_volume_liters")
    breach = False
    if "containment_breach" in body and body["containment_breach"] is not None:
        breach = as_bool(body["containment_breach"], "containment_breach")
    if exited <= entered:
        from errors import ERR_INVALID_TIME_RANGE
        raise ApiError(ERR_INVALID_TIME_RANGE, 400, "exited_pad_at must be > entered_pad_at")
    _, role = authenticate()
    authorize(role, ["PlantOperator"])
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)

    liability = 0
    if breach:
        liability, critical = calc.breach_liability_cents(drip_volume)
        plant["hazardous_waste_liability_cents"] += liability
        if critical:
            plant["compliance_score"] = calc.clamp_score(plant["compliance_score"] - calc.COMPLIANCE_BREACH_PENALTY)
        touch(plant)
        if not charge["hazard_containment_flag"]:
            charge["hazard_containment_flag"] = True
            touch(charge)

    log = new_entity(with_version=False)
    log.update({
        "charge_id": charge["id"],
        "pad_code": pad_code,
        "entered_pad_at": fmt_ts(entered),
        "exited_pad_at": fmt_ts(exited),
        "drip_volume_liters": drip_volume,
        "containment_breach": breach,
        "liability_cents": liability,
        "_entered_dt": entered,
        "_exited_dt": exited,
    })
    store.drip_logs[log["id"]] = log
    return success(public(log), status=201)


@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/drip-pad-logs", methods=["GET"])
def list_drip_logs(plantId, chargeId):
    _, role = authenticate()
    authorize(role, DRIP_READ_ROLES)
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)
    items = [l for l in store.drip_logs.values() if l["charge_id"] == charge["id"]]
    breach = query_bool("containment_breach")
    if breach is not None:
        items = [l for l in items if l["containment_breach"] == breach]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/drip-pad-logs/<logId>", methods=["GET"])
def get_drip_log(plantId, chargeId, logId):
    _, role = authenticate()
    authorize(role, DRIP_READ_ROLES)
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)
    return success(public(resolve_drip_log(logId, charge)))


# --- WarrantyRegistration ---

@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/warranty-registrations", methods=["POST"])
def create_warranty(plantId, chargeId):
    body = body_json()
    registered_by = as_str(req_field(body, "registered_by_user_id"), "registered_by_user_id")
    term = req_field(body, "warranty_term_years")
    if isinstance(term, bool) or not isinstance(term, int) or term not in WARRANTY_TERMS:
        raise ApiError(ERR_INVALID_ENUM, 400, "warranty_term_years must be one of 5, 25, 50")
    expected_version = as_int(req_field(body, "expected_charge_version"), "expected_charge_version")
    _, role = authenticate()
    authorize(role, ["PlantOperator"])
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)
    # Priority 4: plant licensing.
    if plant["status"] != "LICENSED":
        raise ApiError(ERR_PLANT_NOT_LICENSED, 409, "Warranty registration requires plant status LICENSED")
    # Priority 5: charge state.
    if charge["status"] != "TAGGED":
        raise ApiError(ERR_CHARGE_NOT_TAGGED, 409, "Warranty registration requires charge status TAGGED")

    fee = calc.registration_fee_cents(charge, term)

    # Priority 17: customer credit standing (custom-treat only).
    customer = None
    if charge["is_custom_treat"]:
        customer = store.customers.get(charge.get("customer_id"))
        if customer is None:
            raise ApiError(ERR_CUSTOMER_NOT_FOUND, 404, "CustomerAccount not found: " + str(charge.get("customer_id")))
        if customer["status"] != "ACTIVE" or customer["outstanding_balance_cents"] + fee > customer["credit_limit_cents"]:
            raise ApiError(ERR_CUSTOMER_CREDIT_HOLD, 402, "Customer must be ACTIVE and the fee must not push the balance over the credit limit")
    # Priority 19: optimistic concurrency.
    if expected_version != charge["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_charge_version does not match Charge.version")

    war = new_entity()
    war.update({
        "charge_id": charge["id"],
        "registered_by_user_id": registered_by,
        "warranty_term_years": term,
        "registration_fee_cents": fee,
        "status": "ACTIVE",
    })
    store.warranties[war["id"]] = war

    charge["status"] = "RELEASED"
    touch(charge)
    for piece in store.pieces.values():
        if piece["charge_id"] == charge["id"] and piece["status"] == "TAGGED":
            piece["status"] = "RELEASED"
            touch(piece)
    if customer is not None:
        customer["outstanding_balance_cents"] += fee
        calc.refresh_customer_status(customer)
        touch(customer)
    return success(public(war), status=201)


@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/warranty-registrations", methods=["GET"])
def list_warranties(plantId, chargeId):
    _, role = authenticate()
    authorize(role, WARRANTY_READ_ROLES)
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)
    items = [w for w in store.warranties.values() if w["charge_id"] == charge["id"]]
    status = query_filter("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/warranty-registrations/<warrantyId>", methods=["GET"])
def get_warranty(plantId, chargeId, warrantyId):
    _, role = authenticate()
    authorize(role, WARRANTY_READ_ROLES)
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)
    return success(public(resolve_warranty(warrantyId, charge)))
