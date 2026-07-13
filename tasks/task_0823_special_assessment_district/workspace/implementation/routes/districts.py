from fractions import Fraction

from flask import Blueprint

import store
from store import make, touch, ser, now, by_seq, parcels_of_district, rolls_of_district, bonds_of_district
from web import (protected, ALL_ROLES, ok, ok_list, pagination, body_json,
                 require, as_int, as_number, as_str, as_enum, ApiError)
from fetch import get_district
import calc
from util import parse_dt

bp = Blueprint("districts", __name__)

METHODS = {"BENEFIT_UNITS", "FRONT_FOOTAGE", "LAND_AREA"}


@bp.post("/districts")
@protected(["DistrictAdministrator"])
def create_district():
    b = body_json()
    name = as_str(require(b, "name"), "name")
    method = as_enum(require(b, "formation_method"), "formation_method", METHODS)
    tpc = as_int(require(b, "total_project_cost_cents"), "total_project_cost_cents", minimum=0)
    inc = 0
    if b.get("incidental_cost_cents") is not None:
        inc = as_int(b["incidental_cost_cents"], "incidental_cost_cents", minimum=0)
    threshold = 50
    if b.get("protest_threshold_pct") is not None:
        threshold = as_number(b["protest_threshold_pct"], "protest_threshold_pct",
                              minimum_exclusive=0, maximum=100)
    d = make("districts", {
        "name": name,
        "formation_method": method,
        "total_project_cost_cents": tpc,
        "incidental_cost_cents": inc,
        "protest_threshold_pct": threshold,
        "status": "PROPOSED",
        "total_benefit_units": 0,
        "total_apportioned_principal_cents": None,
        "formed_at": None,
    })
    return ok(ser(d), status=201)


@bp.get("/districts/<did>")
@protected(ALL_ROLES)
def get_district_route(did):
    d = get_district(did)
    return ok(ser(d))


@bp.post("/districts/<did>/open-protest")
@protected(["DistrictAdministrator"])
def open_protest(did):
    d = get_district(did)
    if d["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_DISTRICT_STATE")
    active = [p for p in parcels_of_district(did) if p["status"] == "ACTIVE"]
    if not active:
        raise ApiError("ERR_INVALID_DISTRICT_STATE", "district has no active parcels")
    total = sum(calc.weight_of(p, d["formation_method"]) for p in active)
    d["total_benefit_units"] = total
    d["status"] = "PROTEST_PERIOD"
    touch(d)
    return ok(ser(d))


@bp.post("/districts/<did>/close-hearing")
@protected(["DistrictAdministrator"])
def close_hearing(did):
    d = get_district(did)
    if d["status"] != "PROTEST_PERIOD":
        raise ApiError("ERR_INVALID_DISTRICT_STATE")
    active = [p for p in parcels_of_district(did) if p["status"] == "ACTIVE"]
    protest_weight = 0
    for p in active:
        if store.protests_of_parcel(p["id"]):
            protest_weight += calc.weight_of(p, d["formation_method"])
    tbu = d["total_benefit_units"] or 0
    majority = False
    if tbu > 0:
        ratio = Fraction(str(protest_weight)) / Fraction(str(tbu))
        threshold = Fraction(str(d["protest_threshold_pct"])) / 100
        majority = ratio > threshold
    if majority:
        d["status"] = "ABANDONED"
        touch(d)
        for p in active:
            p["status"] = "WITHDRAWN"
            touch(p)
            for inst in store.installments_of_parcel(p["id"]):
                if inst["status"] in ("SCHEDULED", "DUE"):
                    inst["status"] = "CANCELLED"
                    touch(inst)
    else:
        d["status"] = "FORMED"
        d["formed_at"] = now()
        touch(d)
    return ok(ser(d))


@bp.post("/districts/<did>/parcels")
@protected(["DistrictAdministrator"])
def add_parcel(did):
    d = get_district(did)
    b = body_json()
    apn = as_str(require(b, "apn"), "apn")
    owner = as_str(require(b, "owner_name"), "owner_name")
    bu = as_number(b["benefit_units"], "benefit_units", minimum=0) if b.get("benefit_units") is not None else 0
    la = as_number(b["land_area_sqft"], "land_area_sqft", minimum=0) if b.get("land_area_sqft") is not None else 0
    ff = as_number(b["front_footage_ft"], "front_footage_ft", minimum=0) if b.get("front_footage_ft") is not None else 0
    for p in parcels_of_district(did):
        if p["apn"] == apn and p["status"] != "WITHDRAWN":
            raise ApiError("ERR_APN_DUPLICATE")
    p = make("parcels", {
        "district_id": did,
        "parent_parcel_id": None,
        "apn": apn,
        "owner_name": owner,
        "land_area_sqft": la,
        "front_footage_ft": ff,
        "benefit_units": bu,
        "assessed_principal_cents": 0,
        "remaining_principal_cents": 0,
        "status": "ACTIVE",
    })
    return ok(ser(p), status=201)


@bp.get("/districts/<did>/parcels")
@protected(ALL_ROLES)
def list_district_parcels(did):
    get_district(did)
    from flask import request
    items = parcels_of_district(did)
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    items = by_seq(items)
    page, meta = pagination(items)
    return ok_list([ser(x) for x in page], meta)


@bp.post("/districts/<did>/rolls")
@protected(["DistrictAdministrator"])
def create_roll(did):
    d = get_district(did)
    b = body_json()
    method = d["formation_method"]
    if b.get("method") is not None:
        method = as_enum(b["method"], "method", METHODS)
    total = d["total_project_cost_cents"] + d["incidental_cost_cents"]
    r = make("rolls", {
        "district_id": did,
        "method": method,
        "status": "DRAFT",
        "total_apportioned_cents": total,
        "confirmed_at": None,
    })
    return ok(ser(r), status=201)


@bp.get("/districts/<did>/rolls")
@protected(ALL_ROLES)
def list_rolls(did):
    get_district(did)
    from flask import request
    items = rolls_of_district(did)
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    items = by_seq(items)
    page, meta = pagination(items)
    return ok_list([ser(x) for x in page], meta)


@bp.post("/districts/<did>/bonds")
@protected(["DistrictAdministrator"])
def create_bond(did):
    get_district(did)
    b = body_json()
    issuance = parse_dt(as_str(require(b, "issuance_date"), "issuance_date"))
    coupon = 500
    if b.get("coupon_rate_bps") is not None:
        coupon = as_int(b["coupon_rate_bps"], "coupon_rate_bps", minimum=1)
    term = 10
    if b.get("term_years") is not None:
        term = as_int(b["term_years"], "term_years", minimum=1)
    reserve_pct = 0.10
    if b.get("reserve_fund_pct") is not None:
        reserve_pct = as_number(b["reserve_fund_pct"], "reserve_fund_pct", minimum=0)
    iss_cost = 0
    if b.get("issuance_cost_cents") is not None:
        iss_cost = as_int(b["issuance_cost_cents"], "issuance_cost_cents", minimum=0)
    admin_bps = 0
    if b.get("admin_fee_bps") is not None:
        admin_bps = as_int(b["admin_fee_bps"], "admin_fee_bps", minimum=0)
    prepay = 0.03
    if b.get("prepayment_premium_pct") is not None:
        prepay = as_number(b["prepayment_premium_pct"], "prepayment_premium_pct", minimum=0)
    bond = make("bonds", {
        "district_id": did,
        "coupon_rate_bps": coupon,
        "term_years": term,
        "issuance_date": issuance,
        "reserve_fund_pct": reserve_pct,
        "reserve_fund_cents": None,
        "issuance_cost_cents": iss_cost,
        "admin_fee_bps": admin_bps,
        "prepayment_premium_pct": prepay,
        "par_amount_cents": None,
        "status": "AUTHORIZED",
    })
    return ok(ser(bond), status=201)


@bp.get("/districts/<did>/bonds")
@protected(ALL_ROLES)
def list_bonds(did):
    get_district(did)
    from flask import request
    items = bonds_of_district(did)
    status = request.args.get("status")
    if status:
        items = [x for x in items if x["status"] == status]
    items = by_seq(items)
    page, meta = pagination(items)
    return ok_list([ser(x) for x in page], meta)
