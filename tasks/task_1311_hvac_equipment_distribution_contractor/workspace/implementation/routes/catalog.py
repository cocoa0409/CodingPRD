"""Equipment catalog and AHRI system ratings."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_DUPLICATE, ERR_INVALID_SYSTEM_PAIRING, \
    ERR_MODEL_NOT_ORDERABLE
from middleware import authenticate, authorize
from response import success
from serializers import equipment_model as ser_model, ahri_rating as ser_rating
from utils import StructErrors, check_unknown_fields, get_str, get_enum, \
    get_int, get_decimal
from routes.common import body, get_path, new_common, list_response

bp = Blueprint("catalog", __name__)

READ_ROLES = {"DistributorAdmin", "ContractorUser", "WarrantyProcessor",
              "ComplianceOfficer", "TrainingCoordinator"}
EQUIPMENT_TYPES = {"CONDENSER", "HEAT_PUMP", "COIL", "FURNACE", "AIR_HANDLER"}
REFRIGERANT_TYPES = {"R410A", "R454B", "R32", "NONE"}
MODEL_STATUSES = {"ACTIVE", "DISCONTINUED", "ALLOCATED_ONLY"}


@bp.post("/equipment-models")
def create_model():
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"model_number", "equipment_type",
                                "refrigerant_type", "capacity_btuh",
                                "family_code", "list_price_cents", "status"},
                         struct)
    model_number = get_str(data, "model_number", struct)
    equipment_type = get_enum(data, "equipment_type", struct, EQUIPMENT_TYPES)
    refrigerant_type = get_enum(data, "refrigerant_type", struct, REFRIGERANT_TYPES)
    capacity = get_int(data, "capacity_btuh", struct)
    family_code = get_str(data, "family_code", struct)
    list_price = get_int(data, "list_price_cents", struct, minimum=0)
    status = get_enum(data, "status", struct, MODEL_STATUSES,
                      required=False, default="ACTIVE")

    if isinstance(model_number, str):
        for m in db.equipment_models.values():
            if m["model_number"] == model_number:
                raise ApiError(ERR_DUPLICATE, 409, "model_number already exists")
    struct.raise_if_bad()

    m = new_common()
    m.update({
        "model_number": model_number,
        "equipment_type": equipment_type,
        "refrigerant_type": refrigerant_type,
        "capacity_btuh": capacity,
        "family_code": family_code,
        "list_price_cents": list_price,
        "status": status or "ACTIVE",
    })
    db.equipment_models[m["id"]] = m
    return success(ser_model(m), 201)


@bp.get("/equipment-models/<mid>")
def get_model(mid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    m = get_path(db.equipment_models, mid)
    return success(ser_model(m))


@bp.get("/equipment-models")
def list_models():
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    filters = {"equipment_type": request.args.get("equipment_type"),
               "family_code": request.args.get("family_code"),
               "status": request.args.get("status")}
    return list_response(db.equipment_models.values(), ser_model, filters)


def classify_rating(seer2, eer2, hspf2):
    """ahri_matchup_classification: inclusive thresholds, no rounding."""
    from decimal import Decimal
    if seer2 >= Decimal("17.0") and eer2 >= Decimal("12.0"):
        eff = "PREMIUM"
    elif seer2 >= Decimal("15.2") and eer2 >= Decimal("11.7"):
        eff = "HIGH"
    else:
        eff = "STANDARD"
    eligible = (eff == "PREMIUM") or (
        eff == "HIGH" and hspf2 is not None and hspf2 >= Decimal("8.1"))
    return eff, eligible


@bp.post("/ahri-ratings")
def create_rating():
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"ahri_reference_number", "outdoor_unit_id",
                                "indoor_unit_id", "furnace_id", "seer2",
                                "eer2", "hspf2", "status"}, struct)
    ref_number = get_str(data, "ahri_reference_number", struct)
    outdoor_id = get_str(data, "outdoor_unit_id", struct)
    indoor_id = get_str(data, "indoor_unit_id", struct)
    furnace_id = data.get("furnace_id")
    if furnace_id is not None and not isinstance(furnace_id, str):
        struct.add("Field furnace_id must be a string")
        furnace_id = None
    seer2 = get_decimal(data, "seer2", struct)
    eer2 = get_decimal(data, "eer2", struct)
    hspf2 = get_decimal(data, "hspf2", struct, required=False)
    status = get_enum(data, "status", struct, {"ACTIVE", "WITHDRAWN"},
                      required=False, default="ACTIVE")

    # Body reference existence (priority 4).
    outdoor = indoor = furnace = None
    if isinstance(outdoor_id, str):
        from routes.common import get_ref
        outdoor = get_ref(db.equipment_models, outdoor_id, "outdoor_unit_id")
    if isinstance(indoor_id, str):
        from routes.common import get_ref
        indoor = get_ref(db.equipment_models, indoor_id, "indoor_unit_id")
    if isinstance(furnace_id, str):
        from routes.common import get_ref
        furnace = get_ref(db.equipment_models, furnace_id, "furnace_id")

    # AHRI pairing sanity (priority 13).
    if outdoor is not None and indoor is not None:
        pairing_ok = True
        if outdoor["equipment_type"] not in ("CONDENSER", "HEAT_PUMP"):
            pairing_ok = False
        if indoor["equipment_type"] not in ("COIL", "AIR_HANDLER"):
            pairing_ok = False
        if furnace is not None and furnace["equipment_type"] != "FURNACE":
            pairing_ok = False
        if pairing_ok and indoor["refrigerant_type"] != "NONE" and \
                outdoor["refrigerant_type"] != indoor["refrigerant_type"]:
            pairing_ok = False
        if not pairing_ok:
            raise ApiError(ERR_INVALID_SYSTEM_PAIRING, 422,
                           "AHRI pairing violates component-type or "
                           "refrigerant-compatibility rules")

    # Uniqueness (priority 14).
    if isinstance(ref_number, str):
        for r in db.ahri_ratings.values():
            if r["ahri_reference_number"] == ref_number:
                raise ApiError(ERR_DUPLICATE, 409,
                               "ahri_reference_number already exists")

    # Referenced-model orderability (priority 16).
    for comp in (outdoor, indoor, furnace):
        if comp is not None and comp["status"] == "DISCONTINUED":
            raise ApiError(ERR_MODEL_NOT_ORDERABLE, 422,
                           "Component model %s is DISCONTINUED" % comp["id"])

    struct.raise_if_bad()

    eff, eligible = classify_rating(seer2, eer2, hspf2)
    r = new_common()
    r.update({
        "ahri_reference_number": ref_number,
        "outdoor_unit_id": outdoor_id,
        "indoor_unit_id": indoor_id,
        "furnace_id": furnace_id,
        "seer2": seer2,
        "eer2": eer2,
        "hspf2": hspf2,
        "efficiency_class": eff,
        "tax_credit_eligible": eligible,
        "status": status or "ACTIVE",
    })
    db.ahri_ratings[r["id"]] = r
    return success(ser_rating(r), 201)


@bp.get("/ahri-ratings/<rid>")
def get_rating(rid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    r = get_path(db.ahri_ratings, rid)
    return success(ser_rating(r))


@bp.get("/ahri-ratings")
def list_ratings():
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    filters = {"outdoor_unit_id": request.args.get("outdoor_unit_id"),
               "indoor_unit_id": request.args.get("indoor_unit_id"),
               "furnace_id": request.args.get("furnace_id"),
               "efficiency_class": request.args.get("efficiency_class")}
    return list_response(db.ahri_ratings.values(), ser_rating, filters)
