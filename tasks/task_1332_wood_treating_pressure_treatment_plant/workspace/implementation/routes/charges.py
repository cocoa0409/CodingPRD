"""Charge endpoints: composition/loading, re-treat, reject, scrap, tag
(PRD sections 3.5, 3.7, 3.8)."""

from flask import Blueprint

import calc
from db import store, new_entity, touch, public
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_PLANT_NOT_LICENSED,
    ERR_INVALID_STATE,
    ERR_CYLINDER_NOT_IDLE,
    ERR_CYLINDER_CAPACITY_EXCEEDED,
    ERR_NO_SLOT_FOR_CHARGE,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_CUSTOMER_CREDIT_HOLD,
    ERR_CHARGE_NOT_ASSAYED_FAIL,
    ERR_CHARGE_NOT_ASSAYED_PASS,
    ERR_RETREAT_NOT_PERMITTED,
    ERR_STALE_VERSION,
    ERR_INCISING_REQUIRED,
    ERR_DRIP_PAD_CONTAINMENT_BREACH,
    ERR_DRIP_DWELL_TOO_SHORT,
)
from middleware import authenticate, authorize, ALL_ROLES
from response import success
from util import (
    body_json, req_field, as_str, as_number, as_list, as_enum, as_int,
    resolve_plant, resolve_cylinder, resolve_charge, paginate, query_filter,
)

bp = Blueprint("charges", __name__)

OWNERSHIP_TYPES = {"PLANT_STOCK", "CUSTOM_TREAT"}
SPECIES_GROUPS = {"SPF", "SYP", "DOUGLAS_FIR", "HEM_FIR", "PONDEROSA_PINE"}
USE_CATEGORIES = {"UC3B", "UC4A", "UC4B", "UC4C"}

CHARGE_READ_ROLES = ALL_ROLES
CYL_CHARGE_READ_ROLES = ["PlantOperator", "LabTechnician", "QualityManager", "QualityAgencyInspector", "ComplianceOfficer"]


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>/charges", methods=["POST"])
def create_charge(plantId, cylinderId):
    body = body_json()
    ownership_type = as_enum(req_field(body, "ownership_type"), "ownership_type", OWNERSHIP_TYPES)
    species_group = as_enum(req_field(body, "species_group"), "species_group", SPECIES_GROUPS)
    use_category = as_enum(req_field(body, "use_category"), "use_category", USE_CATEGORIES)
    volume_mbf = as_number(req_field(body, "volume_mbf"), "volume_mbf")
    piece_manifest = as_list(req_field(body, "piece_manifest"), "piece_manifest")
    for entry in piece_manifest:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "piece_manifest entries must be objects")
        as_str(req_field(entry, "piece_tag"), "piece_tag")
        as_number(req_field(entry, "length_ft"), "length_ft")
        as_number(req_field(entry, "width_in"), "width_in")
        as_number(req_field(entry, "thickness_in"), "thickness_in")
    customer_id = body.get("customer_id")
    if ownership_type == "CUSTOM_TREAT":
        if customer_id is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "customer_id is required for CUSTOM_TREAT charges")
        as_str(customer_id, "customer_id")
    else:
        customer_id = None

    _, role = authenticate()
    authorize(role, ["PlantOperator"])
    plant = resolve_plant(plantId)
    cyl = resolve_cylinder(cylinderId, plant)

    # Priority 4: plant licensing.
    if plant["status"] != "LICENSED":
        raise ApiError(ERR_PLANT_NOT_LICENSED, 409, "Charge loading requires plant status LICENSED")
    # Priority 5: cylinder state.
    if cyl["status"] != "IDLE":
        raise ApiError(ERR_CYLINDER_NOT_IDLE, 409, "Charge load requires cylinder status IDLE")
    # Priority 6: exact capacity check (equality with max is allowed).
    current_loaded = sum(
        c["volume_mbf"]
        for c in store.charges.values()
        if c["cylinder_id"] == cyl["id"] and c["status"] in ("IN_CYLINDER", "CYCLE_COMPLETE")
    )
    if current_loaded + volume_mbf > cyl["max_volume_mbf"]:
        raise ApiError(ERR_CYLINDER_CAPACITY_EXCEEDED, 409, "current_loaded_mbf + volume_mbf exceeds max_volume_mbf")
    # Priority 16: a TREATMENT slot covering now must exist for this charge.
    # The charge id is minted up front so a slot pre-assigned to it also
    # qualifies; unassigned slots (charge_id null) qualify for any charge.
    from db import new_id
    charge_id = new_id()
    now = store.clock
    covering = [
        s for s in store.slots.values()
        if s["cylinder_id"] == cyl["id"]
        and s["slot_kind"] == "TREATMENT"
        and s["_start_dt"] <= now <= s["_end_dt"]
        and (s["charge_id"] is None or s["charge_id"] == charge_id)
    ]
    if not covering:
        raise ApiError(ERR_NO_SLOT_FOR_CHARGE, 409, "No TREATMENT CylinderScheduleSlot covering now exists for this charge")
    # Priority 17: customer credit standing (custom-treat only).
    customer = None
    if ownership_type == "CUSTOM_TREAT":
        customer = store.customers.get(customer_id)
        if customer is None:
            raise ApiError(ERR_CUSTOMER_NOT_FOUND, 404, "CustomerAccount not found: " + str(customer_id))
        if customer["status"] != "ACTIVE":
            raise ApiError(ERR_CUSTOMER_CREDIT_HOLD, 402, "CustomerAccount must be ACTIVE for custom-treat work")

    # Compose the charge (begins STAGED at version 1) ...
    charge = new_entity()
    charge["id"] = charge_id
    charge.update({
        "cylinder_id": cyl["id"],
        "plant_id": plant["id"],
        "customer_id": customer_id,
        "ownership_type": ownership_type,
        "species_group": species_group,
        "use_category": use_category,
        "volume_mbf": volume_mbf,
        "target_retention_pcf": calc.TARGET_RETENTION_PCF[use_category],
        "provisional_retention_pcf": 0,
        "final_retention_pcf": 0,
        "requires_incising": calc.requires_incising(species_group, use_category),
        "status": "STAGED",
        "is_custom_treat": ownership_type == "CUSTOM_TREAT",
        "hazard_containment_flag": False,
    })
    store.charges[charge["id"]] = charge
    # ... then the atomic load: STAGED -> IN_CYLINDER, cylinder -> LOADED,
    # pieces auto-created in RAW, both versions increment.
    charge["status"] = "IN_CYLINDER"
    touch(charge)
    cyl["status"] = "LOADED"
    touch(cyl)
    for entry in piece_manifest:
        piece = new_entity()
        piece.update({
            "charge_id": charge["id"],
            "piece_tag": entry["piece_tag"],
            "length_ft": entry["length_ft"],
            "width_in": entry["width_in"],
            "thickness_in": entry["thickness_in"],
            "penetration_pct": 0,
            "incised": False,
            "status": "RAW",
        })
        store.pieces[piece["id"]] = piece
    return success(public(charge), status=201)


@bp.route("/treatment-plants/<plantId>/charges/<chargeId>", methods=["GET"])
def get_charge(plantId, chargeId):
    _, role = authenticate()
    authorize(role, CHARGE_READ_ROLES)
    plant = resolve_plant(plantId)
    return success(public(resolve_charge(chargeId, plant)))


def _charge_pieces(charge):
    return [p for p in store.pieces.values() if p["charge_id"] == charge["id"]]


def _charge_cycles(charge):
    return [c for c in store.cycles.values() if c["charge_id"] == charge["id"]]


def _charge_assays(charge):
    return [a for a in store.assays.values() if a["charge_id"] == charge["id"]]


@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/order-retreat", methods=["POST"])
def order_retreat(plantId, chargeId):
    body = body_json()
    expected_version = as_int(req_field(body, "expected_charge_version"), "expected_charge_version")
    _, role = authenticate()
    authorize(role, ["QualityManager"])
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)
    # Priority 4: plant licensing.
    if plant["status"] != "LICENSED":
        raise ApiError(ERR_PLANT_NOT_LICENSED, 409, "Re-treat ordering requires plant status LICENSED")
    # Priority 5: charge state.
    if charge["status"] != "ASSAYED_FAIL":
        raise ApiError(ERR_CHARGE_NOT_ASSAYED_FAIL, 409, "order-retreat requires charge status ASSAYED_FAIL")
    # Priority 18: re-treat eligibility — last assay FAIL_MARGINAL and cycle_number < 3.
    assays = sorted(_charge_assays(charge), key=lambda a: (a["created_at"], a["_seq"]))
    last_outcome = assays[-1]["outcome"] if assays else None
    max_cycle = max([c["cycle_number"] for c in _charge_cycles(charge)], default=0)
    if last_outcome != "FAIL_MARGINAL" or max_cycle >= 3:
        raise ApiError(ERR_RETREAT_NOT_PERMITTED, 422, "Re-treat permitted only when last assay outcome is FAIL_MARGINAL and cycle_number < 3")
    # Priority 19: optimistic concurrency.
    if expected_version != charge["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_charge_version does not match Charge.version")
    charge["status"] = "RE_TREAT_PENDING"
    for war in store.warranties.values():
        if war["charge_id"] == charge["id"] and war["status"] == "ACTIVE":
            war["status"] = "VOIDED_BY_RETREAT"
            touch(war)
    touch(charge)
    return success(public(charge))


@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/reject", methods=["POST"])
def reject_charge(plantId, chargeId):
    _, role = authenticate()
    authorize(role, ["QualityManager"])
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)
    if charge["status"] != "CYCLE_COMPLETE":
        raise ApiError(ERR_INVALID_STATE, 409, "Reject requires charge status CYCLE_COMPLETE")
    cited = any(
        i for i in store.inspections.values()
        if i["plant_id"] == plant["id"]
        and i["severity"] == "CRITICAL"
        and i["status"] == "FINDINGS_ISSUED"
        and charge["id"] in i.get("charges_in_scope", [])
    )
    if not cited:
        raise ApiError(ERR_INVALID_STATE, 409, "Reject requires a CRITICAL QualityInspection finding citing this charge")
    charge["status"] = "REJECTED"
    touch(charge)
    cyl = store.cylinders.get(charge["cylinder_id"])
    if cyl is not None and cyl["status"] in ("LOADED", "CYCLE_RUNNING", "DRAINING"):
        cyl["status"] = "NEEDS_CLEANING"
        touch(cyl)
    return success(public(charge))


@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/scrap", methods=["POST"])
def scrap_charge(plantId, chargeId):
    _, role = authenticate()
    authorize(role, ["QualityManager"])
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)
    if charge["status"] not in ("ASSAYED_FAIL", "RE_TREAT_PENDING"):
        raise ApiError(ERR_INVALID_STATE, 409, "Scrap requires charge status ASSAYED_FAIL or RE_TREAT_PENDING")
    assays = sorted(_charge_assays(charge), key=lambda a: (a["created_at"], a["_seq"]))
    last_outcome = assays[-1]["outcome"] if assays else None
    max_cycle = max([c["cycle_number"] for c in _charge_cycles(charge)], default=0)
    if not (last_outcome == "FAIL_GROSS" or max_cycle >= 3):
        raise ApiError(ERR_INVALID_STATE, 409, "Scrap requires last assay FAIL_GROSS or cycle_number >= 3")
    charge["status"] = "SCRAPPED"
    touch(charge)
    for piece in _charge_pieces(charge):
        if piece["status"] == "ASSAYED_FAIL":
            piece["status"] = "SCRAPPED"
            touch(piece)
    plant["hazardous_waste_liability_cents"] += calc.scrap_liability_cents(charge["volume_mbf"])
    plant["compliance_score"] = calc.clamp_score(plant["compliance_score"] - calc.COMPLIANCE_SCRAP_PENALTY)
    touch(plant)
    return success(public(charge))


@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/tag", methods=["POST"])
def tag_charge(plantId, chargeId):
    _, role = authenticate()
    authorize(role, ["PlantOperator"])
    plant = resolve_plant(plantId)
    charge = resolve_charge(chargeId, plant)
    if charge["status"] != "ASSAYED_PASS":
        raise ApiError(ERR_CHARGE_NOT_ASSAYED_PASS, 409, "Tag requires charge status ASSAYED_PASS")
    pieces = _charge_pieces(charge)
    # Priority 10: incising completeness.
    if charge["requires_incising"] and any(not p["incised"] for p in pieces):
        raise ApiError(ERR_INCISING_REQUIRED, 422, "Charge requires incising but not all pieces are incised")
    # Priority 11: drip-pad containment (a log must exist and its latest entry
    # must show no breach).
    logs = sorted(
        [l for l in store.drip_logs.values() if l["charge_id"] == charge["id"]],
        key=lambda l: (l["created_at"], l["_seq"]),
    )
    if not logs or logs[-1]["containment_breach"]:
        raise ApiError(ERR_DRIP_PAD_CONTAINMENT_BREACH, 422, "Latest DripPadLog must exist with containment_breach == false")
    # Priority 12: dwell duration >= 24 hours.
    dwell = logs[-1]["_exited_dt"] - logs[-1]["_entered_dt"]
    if dwell.total_seconds() < 24 * 3600:
        raise ApiError(ERR_DRIP_DWELL_TOO_SHORT, 422, "DripPadLog dwell time must be >= 24 hours")
    charge["status"] = "TAGGED"
    touch(charge)
    for piece in pieces:
        if piece["status"] == "ASSAYED_PASS":
            piece["status"] = "TAGGED"
            touch(piece)
    return success(public(charge))
