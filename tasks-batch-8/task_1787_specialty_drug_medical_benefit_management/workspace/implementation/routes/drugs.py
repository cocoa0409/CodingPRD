"""Drug catalog endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_JCODE_NOT_UNIQUE, ERR_INVALID_VIAL_UNIT_RATIO
from middleware import authorized
from response import success_object
from routes.helpers import (
    apply_filters, get_body, is_int, is_num, list_response, one, opt_bool,
    public, read_all, req_bool, req_enum, req_int, req_str, stamp_new,
)
from util import new_id

bp = Blueprint("drugs", __name__)

SOURCING_RULES = ("BUY_AND_BILL_ONLY", "SPECIALTY_PHARMACY_ONLY", "EITHER")
ROUNDING_MODES = ("VIAL", "INCREMENT")


@bp.post("/api/drugs")
def create_drug():
    authorized(["PlanAdmin"])
    body = get_body()
    # ---- shape (stage 4) ----
    j_code = req_str(body, "j_code")
    drug_name = req_str(body, "drug_name")
    billing_unit_mg = req_int(body, "billing_unit_mg", min_v=1)
    vial_size_mg = req_int(body, "vial_size_mg")
    single_dose_vial = req_bool(body, "single_dose_vial")
    sourcing_rule = req_enum(body, "sourcing_rule", SOURCING_RULES)
    weight_based_dosing = opt_bool(body, "weight_based_dosing", False)
    # conditional presence: mg_per_kg exactly when weight_based_dosing
    mg_per_kg = body.get("mg_per_kg")
    if weight_based_dosing:
        if mg_per_kg is None or not is_num(mg_per_kg) or mg_per_kg <= 0:
            raise_error(ERR_INVALID_REQUEST, "mg_per_kg must be present and > 0 for weight-based drugs")
    elif mg_per_kg is not None:
        raise_error(ERR_INVALID_REQUEST, "mg_per_kg must be absent when weight_based_dosing is false")
    dose_rounding_mode = req_enum(body, "dose_rounding_mode", ROUNDING_MODES)
    # conditional presence: rounding_increment_mg exactly when INCREMENT
    rounding_increment_mg = body.get("rounding_increment_mg")
    if dose_rounding_mode == "INCREMENT":
        if not is_int(rounding_increment_mg) or rounding_increment_mg < 1:
            raise_error(ERR_INVALID_REQUEST, "rounding_increment_mg must be present and >= 1 for INCREMENT mode")
    elif rounding_increment_mg is not None:
        raise_error(ERR_INVALID_REQUEST, "rounding_increment_mg must be absent when dose_rounding_mode is VIAL")
    max_single_dose_mg = req_int(body, "max_single_dose_mg", min_v=1)
    site_of_care_eligible = req_bool(body, "site_of_care_eligible")
    # ---- referential geometry (stage 10) ----
    if vial_size_mg < 1 or vial_size_mg % billing_unit_mg != 0:
        raise_error(ERR_INVALID_VIAL_UNIT_RATIO, "vial_size_mg must be a positive multiple of billing_unit_mg")
    for d in db["drugs"].values():
        if d["j_code"] == j_code:
            raise_error(ERR_JCODE_NOT_UNIQUE, f"j_code {j_code} is already registered")
    rec = {
        "id": new_id(),
        "j_code": j_code,
        "drug_name": drug_name,
        "billing_unit_mg": billing_unit_mg,
        "vial_size_mg": vial_size_mg,
        "single_dose_vial": single_dose_vial,
        "sourcing_rule": sourcing_rule,
        "weight_based_dosing": weight_based_dosing,
        "mg_per_kg": mg_per_kg if weight_based_dosing else None,
        "dose_rounding_mode": dose_rounding_mode,
        "rounding_increment_mg": rounding_increment_mg if dose_rounding_mode == "INCREMENT" else None,
        "max_single_dose_mg": max_single_dose_mg,
        "site_of_care_eligible": site_of_care_eligible,
    }
    stamp_new(rec)
    db["drugs"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.get("/api/drugs")
def list_drugs():
    read_all()
    items = list(db["drugs"].values())
    items = apply_filters(items, ["sourcing_rule"])
    sce = request.args.get("site_of_care_eligible")
    if sce is not None:
        want = sce.strip().lower() == "true"
        items = [d for d in items if d["site_of_care_eligible"] is want]
    return list_response(items)


@bp.get("/api/drugs/<drugId>")
def get_drug(drugId):
    read_all()
    return one("drugs", drugId)
