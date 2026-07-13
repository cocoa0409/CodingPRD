from fractions import Fraction

from flask import Blueprint, request, g

import store
from store import (DB, make, touch, ser, by_seq, parcels_of_district,
                   installments_of_parcel, protests_of_parcel, bonds_of_district)
from web import (protected, ALL_ROLES, ok, ok_list, pagination, body_json,
                 require, as_int, as_number, as_str, as_enum, owner_check, ApiError)
from fetch import get_parcel, get_district, get_bond
import calc
import logic
from util import parse_dt

bp = Blueprint("parcels", __name__)

METHODS = {"BENEFIT_UNITS", "FRONT_FOOTAGE", "LAND_AREA"}


@bp.get("/parcels/<pid>")
@protected(ALL_ROLES)
def get_parcel_route(pid):
    return ok(ser(get_parcel(pid)))


@bp.get("/parcels")
@protected(ALL_ROLES)
def list_parcels():
    items = list(DB["parcels"].values())
    did = request.args.get("district_id")
    ppid = request.args.get("parent_parcel_id")
    status = request.args.get("status")
    if did:
        items = [p for p in items if p["district_id"] == did]
    if ppid:
        items = [p for p in items if p["parent_parcel_id"] == ppid]
    if status:
        items = [p for p in items if p["status"] == status]
    items = by_seq(items)
    page, meta = pagination(items)
    return ok_list([ser(x) for x in page], meta)


def _validate_child(c, idx):
    if not isinstance(c, dict):
        raise ApiError("ERR_VALIDATION", "children[%d] must be an object" % idx)
    apn = as_str(require(c, "apn"), "children[%d].apn" % idx)
    owner = as_str(require(c, "owner_name"), "children[%d].owner_name" % idx)
    bu = as_number(c["benefit_units"], "children[%d].benefit_units" % idx, minimum=0) if c.get("benefit_units") is not None else 0
    la = as_number(c["land_area_sqft"], "children[%d].land_area_sqft" % idx, minimum=0) if c.get("land_area_sqft") is not None else 0
    ff = as_number(c["front_footage_ft"], "children[%d].front_footage_ft" % idx, minimum=0) if c.get("front_footage_ft") is not None else 0
    return {"apn": apn, "owner_name": owner, "benefit_units": bu,
            "land_area_sqft": la, "front_footage_ft": ff}


@bp.post("/parcels/<pid>/subdivide")
@protected(["DistrictAdministrator"])
def subdivide(pid):
    parent = get_parcel(pid)
    if parent["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_PARCEL_STATE")
    b = body_json()
    raw_children = require(b, "children")
    if not isinstance(raw_children, list) or not raw_children:
        raise ApiError("ERR_VALIDATION", "children must be a non-empty list")
    children = [_validate_child(c, i) for i, c in enumerate(raw_children)]

    # benefit-unit conservation
    child_sum = sum(Fraction(str(c["benefit_units"])) for c in children)
    if child_sum != Fraction(str(parent["benefit_units"])):
        raise ApiError("ERR_BENEFIT_UNITS_MISMATCH")

    # apn uniqueness within district (existing non-withdrawn + amongst children)
    existing = {p["apn"] for p in parcels_of_district(parent["district_id"])
                if p["status"] != "WITHDRAWN"}
    seen = set()
    for c in children:
        if c["apn"] in existing or c["apn"] in seen:
            raise ApiError("ERR_APN_DUPLICATE")
        seen.add(c["apn"])

    created = []
    for c in children:
        child = make("parcels", {
            "district_id": parent["district_id"],
            "parent_parcel_id": parent["id"],
            "apn": c["apn"],
            "owner_name": c["owner_name"],
            "land_area_sqft": c["land_area_sqft"],
            "front_footage_ft": c["front_footage_ft"],
            "benefit_units": c["benefit_units"],
            "assessed_principal_cents": 0,
            "remaining_principal_cents": 0,
            "status": "ACTIVE",
        })
        created.append(child)

    entries = [{"id": ch["id"], "weight": ch["benefit_units"], "seq": ch["_seq"]}
               for ch in created]
    shares = calc.waterfall(parent["remaining_principal_cents"], entries)
    for ch in created:
        share = shares.get(ch["id"], 0)
        ch["remaining_principal_cents"] = share
        ch["assessed_principal_cents"] = share
        ch["_subdiv_remaining"] = share

    parent["status"] = "SUBDIVIDED"
    touch(parent)

    for bond in bonds_of_district(parent["district_id"]):
        if bond["status"] != "ISSUED":
            continue
        logic.cancel_scheduled_installments(parent, bond["id"])
        for ch in created:
            logic.generate_installments(ch, bond, ch["remaining_principal_cents"])

    return ok(ser(parent))


@bp.post("/parcels/<pid>/consolidate")
@protected(["DistrictAdministrator"])
def consolidate(pid):
    parent = get_parcel(pid)
    if parent["status"] != "SUBDIVIDED":
        raise ApiError("ERR_INVALID_PARCEL_STATE")
    children = [p for p in DB["parcels"].values() if p["parent_parcel_id"] == parent["id"]]
    active_children = [c for c in children if c["status"] == "ACTIVE"]
    for c in active_children:
        if c["remaining_principal_cents"] != c.get("_subdiv_remaining", c["remaining_principal_cents"]):
            raise ApiError("ERR_INVALID_PARCEL_STATE", "child remaining principal changed since subdivision")

    for c in active_children:
        c["status"] = "WITHDRAWN"
        touch(c)
        for inst in installments_of_parcel(c["id"]):
            if inst["status"] == "SCHEDULED":
                inst["status"] = "CANCELLED"
                touch(inst)

    parent["status"] = "ACTIVE"
    touch(parent)

    for bond in bonds_of_district(parent["district_id"]):
        if bond["status"] != "ISSUED":
            continue
        logic.cancel_scheduled_installments(parent, bond["id"])
        logic.generate_installments(parent, bond, parent["remaining_principal_cents"])

    return ok(ser(parent))


@bp.post("/parcels/<pid>/protests")
@protected(["ParcelOwner"])
def file_protest(pid):
    owner_check(pid)
    parcel = get_parcel(pid)
    district = get_district(parcel["district_id"])
    b = body_json()
    filed_by = as_str(require(b, "filed_by"), "filed_by")
    weight = calc.weight_of(parcel, district["formation_method"])
    pf = make("protests", {
        "parcel_id": parcel["id"],
        "filed_by": filed_by,
        "weight_units": weight,
    }, versioned=False)
    return ok(ser(pf), status=201)


@bp.get("/parcels/<pid>/protests")
@protected(ALL_ROLES)
def list_protests(pid):
    get_parcel(pid)
    items = by_seq(protests_of_parcel(pid))
    page, meta = pagination(items)
    return ok_list([ser(x) for x in page], meta)


@bp.post("/parcels/<pid>/installments")
@protected(["DistrictAdministrator"])
def add_installment(pid):
    parcel = get_parcel(pid)
    b = body_json()
    bond_id = as_str(require(b, "bond_id"), "bond_id")
    bond = DB["bonds"].get(bond_id)
    if bond is None:
        raise ApiError("ERR_VALIDATION", "bond_id does not reference an existing bond")
    year = as_int(require(b, "installment_year"), "installment_year", minimum=1)
    due = parse_dt(as_str(require(b, "due_date"), "due_date"))
    principal = as_int(require(b, "principal_cents"), "principal_cents", minimum=0)
    interest = as_int(b["interest_cents"], "interest_cents", minimum=0) if b.get("interest_cents") is not None else 0
    admin = as_int(b["admin_fee_cents"], "admin_fee_cents", minimum=0) if b.get("admin_fee_cents") is not None else 0

    for inst in installments_of_parcel(pid):
        if (inst["bond_id"] == bond_id and inst["installment_year"] == year
                and inst["status"] != "CANCELLED"):
            raise ApiError("ERR_INSTALLMENT_YEAR_CONFLICT")

    inst = make("installments", {
        "parcel_id": parcel["id"],
        "bond_id": bond_id,
        "installment_year": year,
        "due_date": due,
        "principal_cents": principal,
        "interest_cents": interest,
        "admin_fee_cents": admin,
        "penalty_cents": 0,
        "redemption_interest_cents": 0,
        "amount_due_cents": principal + interest + admin,
        "status": "SCHEDULED",
    })
    return ok(ser(inst), status=201)
