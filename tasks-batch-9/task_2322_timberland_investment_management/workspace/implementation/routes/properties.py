"""Tract registration, the appraisal dimension, risk review and the closing.

PRD 3.1 (registration and market access), 3.3 (appraisal, NAV, acquisition) and
3.8 (hazard review and insurance pricing).
"""

from flask import Blueprint

import calc
import db
import middleware
import response
import serializers
import services
import validate
from db import store
from errors import ApiError
from routes.helpers import paginated

bp = Blueprint("properties", __name__)

APPRAISAL_INPUTS = {
    "INCOME": ("stabilized_noi_usd", "cap_rate_bps"),
    "MARKET": ("comparable_price_per_acre_usd",),
    "COST": ("bare_land_value_per_acre_usd", "timber_unit_value_usd_per_ton"),
}


@bp.post("/properties")
def create_property():
    middleware.require("AcquisitionAnalyst")
    body = validate.json_body()

    # Step 4: body foreign keys resolve before the request shape is inspected.
    raw_fund_id = validate.opt_str_id(body, "fund_id")
    fund = None
    if raw_fund_id is not None:
        fund = services.find(store.funds, raw_fund_id, "ERR_FUND_NOT_FOUND")

    fund_id = validate.string(body, "fund_id")
    name = validate.string(body, "name", 1, 120)
    region_code = validate.enum(body, "region_code", calc.REGIONS)
    total_acres = validate.number(body, "total_acres", minimum=0,
                                  exclusive_min=True, dp=2)
    haul_miles = validate.integer(body, "haul_distance_miles", 0, 600)
    insured_value = validate.number(body, "insured_value_usd", minimum=0, dp=2)
    hbu_acres = validate.number(body, "hbu_acres", minimum=0, dp=2)
    hbu_price = validate.number(body, "hbu_price_per_acre_usd", minimum=0, dp=2)
    annual_rec = validate.number(body, "annual_rec_income_usd", minimum=0, dp=2)
    scheme = validate.enum(body, "certification_scheme", ("SFI", "FSC", "NONE"))
    if fund is None:
        fund = services.find(store.funds, fund_id, "ERR_FUND_NOT_FOUND")

    tier, discount_pct = calc.market_access(haul_miles)
    rec = db.base_fields()
    rec.update({
        "fund_id": fund["id"],
        "name": name,
        "region_code": region_code,
        "total_acres": total_acres,
        "haul_distance_miles": haul_miles,
        "insured_value_usd": insured_value,
        "hbu_acres": hbu_acres,
        "hbu_price_per_acre_usd": hbu_price,
        "annual_rec_income_usd": annual_rec,
        "certification_scheme": scheme,
        "status": "PROSPECT",
        "appraisal_status": "NONE",
        "appraisal_methodology": None,
        "appraised_value_usd": None,
        "appraisal_submitted_by_user_id": None,
        "appraisal_signed_by_user_id": None,
        "appraisal_signed_at": None,
        "_appraisal_signed_dt": None,
        "certification_posture": "UNCERTIFIED" if scheme == "NONE" else "CERTIFIED",
        "harvest_plan_status": "ALIGNED",
        "market_access_tier": tier,
        "market_access_discount_pct": discount_pct,
        "insurance_rating_basis": None,
        "wildfire_hazard_index": None,
        "insect_hazard_index": None,
        "weather_hazard_index": None,
        "composite_risk_score": None,
        "insurance_premium_usd": None,
        "acquisition_price_usd": None,
    })
    store.properties[rec["id"]] = rec
    return response.created(serializers.prop(rec))


@bp.get("/properties/<property_id>")
def get_property(property_id):
    middleware.require(*middleware.ANY_ROLE)
    prop = services.find(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")
    services.apply_lazy_appraisal_stale(prop)
    return response.ok(serializers.prop(prop))


@bp.get("/properties/<property_id>/stands")
def list_property_stands(property_id):
    middleware.require(*middleware.ANY_ROLE)
    prop = services.find(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")
    return paginated(services.stands_of_property(prop["id"]), serializers.stand)


@bp.get("/properties/<property_id>/underwriting-cases")
def list_property_cases(property_id):
    middleware.require(*middleware.ANY_ROLE)
    prop = services.find(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")
    return paginated(services.rows(store.underwriting_cases, property_id=prop["id"]),
                     serializers.underwriting_case)


@bp.get("/properties/<property_id>/carbon-projects")
def list_property_carbon_projects(property_id):
    middleware.require(*middleware.ANY_ROLE)
    prop = services.find(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")
    return paginated(services.rows(store.carbon_projects, property_id=prop["id"]),
                     serializers.carbon_project)


@bp.get("/properties/<property_id>/recreational-leases")
def list_property_leases(property_id):
    middleware.require(*middleware.ANY_ROLE)
    prop = services.find(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")
    leases = services.rows(store.recreational_leases, property_id=prop["id"])
    for lease in leases:
        services.apply_lazy_lease_expiry(lease)
    return paginated(leases, serializers.recreational_lease)


@bp.get("/properties/<property_id>/certification-audits")
def list_property_audits(property_id):
    middleware.require(*middleware.ANY_ROLE)
    prop = services.find(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")
    return paginated(services.rows(store.certification_audits, property_id=prop["id"]),
                     serializers.certification_audit)


# ---------------------------------------------------------------- appraisal

@bp.post("/properties/<property_id>/appraisal")
def appraisal(property_id):
    user_id = middleware.require("IndependentAppraiser")
    prop = services.find(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")
    body = validate.json_body()
    action = validate.enum(body, "action", ("SUBMIT", "SIGN", "INVALIDATE"))

    methodology = None
    if action == "SUBMIT":
        methodology = validate.enum(body, "appraisal_methodology",
                                    ("INCOME", "MARKET", "COST"))
    # Present-but-malformed methodology inputs are a shape failure; a merely
    # missing one is the 422 completeness failure checked further down.
    inputs = {
        "stabilized_noi_usd": validate.number(
            body, "stabilized_noi_usd", minimum=0, dp=2, required=False),
        "cap_rate_bps": validate.number(
            body, "cap_rate_bps", minimum=0, exclusive_min=True, dp=2, required=False),
        "comparable_price_per_acre_usd": validate.number(
            body, "comparable_price_per_acre_usd", minimum=0, dp=2, required=False),
        "bare_land_value_per_acre_usd": validate.number(
            body, "bare_land_value_per_acre_usd", minimum=0, dp=2, required=False),
        "timber_unit_value_usd_per_ton": validate.number(
            body, "timber_unit_value_usd_per_ton", minimum=0, dp=2, required=False),
    }

    # Step 8: segregation of duties, evaluated before state legality.
    if action == "SIGN":
        if prop["appraisal_submitted_by_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        for case in store.underwriting_cases.values():
            if case["property_id"] == prop["id"] and case["authored_by_user_id"] == user_id:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    status = prop["appraisal_status"]
    if action == "SUBMIT":
        if status not in ("NONE", "STALE"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        for field in APPRAISAL_INPUTS[methodology]:
            if inputs[field] is None:
                raise ApiError("ERR_APPRAISAL_INPUTS_INCOMPLETE")
        timber_basis, _acres = services.inventoried_totals(prop["id"])
        prop["appraised_value_usd"] = calc.appraised_value(
            methodology, prop["total_acres"], timber_basis, inputs)
        prop["appraisal_methodology"] = methodology
        prop["appraisal_submitted_by_user_id"] = user_id
        prop["appraisal_status"] = "SUBMITTED"
    elif action == "SIGN":
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        prop["appraisal_signed_by_user_id"] = user_id
        prop["appraisal_signed_at"] = db.logical_now_iso()
        prop["_appraisal_signed_dt"] = db.logical_now()
        prop["appraisal_status"] = "SIGNED"
    else:
        if status not in ("SUBMITTED", "SIGNED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if status == "SUBMITTED":
            prop["appraisal_status"] = "NONE"
            prop["appraised_value_usd"] = None
            prop["appraisal_methodology"] = None
            prop["appraisal_submitted_by_user_id"] = None
        else:
            prop["appraisal_status"] = "STALE"

    services.mark(prop)
    fund = services.fund_of_property(prop)
    if fund is not None:
        services.recompute_fund(fund)
    return response.ok(serializers.prop(prop))


# -------------------------------------------------------------- risk review

@bp.post("/properties/<property_id>/risk-review")
def risk_review(property_id):
    middleware.require("FundAdmin")
    prop = services.find(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")
    body = validate.json_body()
    basis = validate.enum(body, "insurance_rating_basis",
                          ("ACTUARIAL", "EXPERIENCE_RATED"))
    wildfire = validate.number(body, "wildfire_hazard_index", minimum=0, maximum=100, dp=2)
    insect = validate.number(body, "insect_hazard_index", minimum=0, maximum=100, dp=2)
    weather = validate.number(body, "weather_hazard_index", minimum=0, maximum=100, dp=2)

    species = services.dominant_species(prop["id"])
    composite = calc.composite_risk_score(prop["region_code"], species,
                                          wildfire, insect, weather)
    trailing = services.trailing_settled_claims(prop["id"])
    premium, _loss_ratio = calc.insurance_premium(
        basis, prop["insured_value_usd"], composite, trailing)

    fund = services.fund_of_property(prop)
    services.guard_fund_cash(fund, premium)

    prop["insurance_rating_basis"] = basis
    prop["wildfire_hazard_index"] = wildfire
    prop["insect_hazard_index"] = insect
    prop["weather_hazard_index"] = weather
    prop["composite_risk_score"] = composite
    prop["insurance_premium_usd"] = premium
    services.mark(prop)
    services.debit_fund(fund, premium, operating=True)
    return response.ok(serializers.prop(prop))


# ---------------------------------------------------------------- acquisition

@bp.post("/properties/<property_id>/acquire")
def acquire(property_id):
    middleware.require("FundAdmin")
    prop = services.find(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")
    body = validate.json_body()

    raw_case_id = validate.opt_str_id(body, "underwriting_case_id")
    case = None
    if raw_case_id is not None:
        case = services.find(store.underwriting_cases, raw_case_id,
                             "ERR_UNDERWRITING_CASE_NOT_FOUND")
    case_id = validate.string(body, "underwriting_case_id")
    expected_fund_version = validate.integer(body, "expected_fund_version")
    if case is None:
        case = services.find(store.underwriting_cases, case_id,
                             "ERR_UNDERWRITING_CASE_NOT_FOUND")

    fund = services.fund_of_property(prop)
    if expected_fund_version != fund["version"]:
        raise ApiError("ERR_STALE_FUND_VERSION")

    if case["status"] != "APPROVED":
        raise ApiError("ERR_UNDERWRITING_NOT_APPROVED")
    if prop["status"] != "APPROVED_FOR_BID":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if prop["appraisal_status"] != "SIGNED":
        raise ApiError("ERR_APPRAISAL_NOT_SIGNED")
    if case["property_id"] != prop["id"]:
        raise ApiError("ERR_CASE_PROPERTY_MISMATCH")

    price = case["bid_price_usd"]
    services.guard_fund_cash(fund, price)

    prop["status"] = "OWNED"
    prop["acquisition_price_usd"] = price
    services.mark(prop)
    # The bid is a capital call, so net_operating_cash_usd is deliberately
    # untouched (PRD 2.11 / 3.3).
    services.debit_fund(fund, price, operating=False)
    return response.ok(serializers.prop(prop))
