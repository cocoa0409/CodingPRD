from flask import Blueprint, request, g

import store
from store import (DB, make, touch, ser, by_seq,
                   installments_of_parcel, liens_of_parcel, foreclosures_of_parcel,
                   bonds_of_district)
from web import (protected, ALL_ROLES, ok, ok_list, pagination, body_json,
                 require, as_enum, ApiError)
from fetch import get_parcel, get_foreclosure
import calc

bp = Blueprint("foreclosures", __name__)

TO_STATUSES = {"NOTICED", "JUDGMENT", "SALE", "REDEEMED", "CANCELLED"}
ACTOR = {
    "NOTICED": "DistrictAdministrator",
    "JUDGMENT": "DistrictAdministrator",
    "CANCELLED": "DistrictAdministrator",
    "SALE": "CountyTreasurer",
    "REDEEMED": "CountyTreasurer",
}
LEGAL_FROM = {
    "NOTICED": {"INITIATED"},
    "JUDGMENT": {"NOTICED"},
    "SALE": {"JUDGMENT"},
    "REDEEMED": {"JUDGMENT"},
    "CANCELLED": {"INITIATED"},
}


@bp.post("/parcels/<pid>/foreclosures")
@protected(["DistrictAdministrator"])
def initiate_foreclosure(pid):
    parcel = get_parcel(pid)
    if parcel["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_PARCEL_STATE")
    delinquent = [i for i in installments_of_parcel(pid) if i["status"] == "DELINQUENT"]
    if len(delinquent) < calc.FORECLOSURE_DELINQUENT_THRESHOLD:
        raise ApiError("ERR_FORECLOSURE_THRESHOLD_NOT_MET")
    fa = make("foreclosures", {
        "parcel_id": parcel["id"],
        "delinquent_installment_count": len(delinquent),
        "delinquent_amount_cents": sum(i["amount_due_cents"] for i in delinquent),
        "redemption_amount_cents": None,
        "status": "INITIATED",
    })
    parcel["status"] = "IN_FORECLOSURE"
    touch(parcel)
    return ok(ser(fa), status=201)


@bp.get("/parcels/<pid>/foreclosures")
@protected(ALL_ROLES)
def list_foreclosures(pid):
    get_parcel(pid)
    items = foreclosures_of_parcel(pid)
    status = request.args.get("status")
    if status:
        items = [f for f in items if f["status"] == status]
    items = by_seq(items)
    page, meta = pagination(items)
    return ok_list([ser(x) for x in page], meta)


@bp.post("/foreclosures/<fid>/advance")
@protected(["DistrictAdministrator", "CountyTreasurer"])
def advance_foreclosure(fid):
    fa = get_foreclosure(fid)
    b = body_json()
    to_status = as_enum(require(b, "to_status"), "to_status", TO_STATUSES)

    if g.role != ACTOR[to_status]:
        raise ApiError("ERR_UNAUTHORIZED")
    if fa["status"] not in LEGAL_FROM[to_status]:
        raise ApiError("ERR_INVALID_FORECLOSURE_STATE")

    parcel = get_parcel(fa["parcel_id"])

    if to_status == "NOTICED":
        fa["status"] = "NOTICED"
    elif to_status == "JUDGMENT":
        fa["redemption_amount_cents"] = fa["delinquent_amount_cents"]
        fa["status"] = "JUDGMENT"
    elif to_status == "SALE":
        _apply_sale(parcel)
        fa["status"] = "SALE"
    elif to_status == "REDEEMED":
        _apply_redeem(parcel)
        fa["status"] = "REDEEMED"
    elif to_status == "CANCELLED":
        if parcel["status"] == "IN_FORECLOSURE":
            others = [f for f in foreclosures_of_parcel(parcel["id"])
                      if f["id"] != fa["id"] and f["status"] in ("INITIATED", "NOTICED", "JUDGMENT")]
            if not others:
                parcel["status"] = "ACTIVE"
                touch(parcel)
        fa["status"] = "CANCELLED"

    touch(fa)
    return ok(ser(fa))


def _apply_sale(parcel):
    bond_ids = set()
    for inst in installments_of_parcel(parcel["id"]):
        if inst["status"] == "DELINQUENT":
            inst["status"] = "DEFAULTED"
            touch(inst)
            bond_ids.add(inst["bond_id"])
    for lien in liens_of_parcel(parcel["id"]):
        if lien["status"] == "RECORDED":
            lien["status"] = "FORECLOSED"
            touch(lien)
    targets = set(bond_ids)
    for b in bonds_of_district(parcel["district_id"]):
        if b["status"] == "ISSUED" and (not targets or b["id"] in targets):
            b["status"] = "DEFAULTED"
            touch(b)


def _apply_redeem(parcel):
    for inst in installments_of_parcel(parcel["id"]):
        if inst["status"] == "DELINQUENT":
            inst["status"] = "PAID"
            touch(inst)
            parcel["remaining_principal_cents"] -= inst["principal_cents"]
    for lien in liens_of_parcel(parcel["id"]):
        if lien["lien_type"] == "DELINQUENCY" and lien["status"] == "RECORDED":
            lien["status"] = "RELEASED"
            touch(lien)
    if parcel["remaining_principal_cents"] < 0:
        parcel["remaining_principal_cents"] = 0
    parcel["status"] = "ACTIVE"
    touch(parcel)
