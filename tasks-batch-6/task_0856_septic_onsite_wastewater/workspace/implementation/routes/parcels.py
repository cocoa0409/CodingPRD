"""Parcel registration, reads, the compliance dossier and fee payments."""
from flask import Blueprint

import calc
import derive
import lookup
import response
import serialize
import store
import validate as v
from auth import ALL_ROLES, authenticate
from errors import ApiError
from store import ordered

bp = Blueprint("parcels", __name__)

READ_PARCEL_CHILD_ROLES = ["Applicant", "DesignProfessional",
                           "EnvironmentalHealthSpecialist", "HealthOfficer",
                           "RecordsClerk"]
DOSSIER_ROLES = ["Applicant", "EnvironmentalHealthSpecialist", "HealthOfficer",
                 "RecordsClerk"]
WATER_SOURCES = ("PUBLIC_WATER", "PRIVATE_WELL")


@bp.post("/parcels")
def create_parcel():
    actor = authenticate(["Applicant"])
    body = v.body()
    apn = v.req_str(body, "apn")
    county_code = v.req_str(body, "county_code")
    site_address = v.req_str(body, "site_address")
    lot_size_sqft = v.req_int(body, "lot_size_sqft", minimum=1)
    water_source = v.req_enum(body, "water_source", WATER_SOURCES)

    for existing in store.parcels.values():
        if existing["apn"] == apn and existing["county_code"] == county_code:
            raise ApiError("ERR_DUPLICATE_APN")

    parcel = store.new_record()
    parcel.update({
        "apn": apn,
        "county_code": county_code,
        "owner_user_id": actor.user_id,
        "site_address": site_address,
        "lot_size_sqft": lot_size_sqft,
        "water_source": water_source,
        "max_design_flow_gpd": calc.parcel_max_design_flow(lot_size_sqft),
        "permitted_design_flow_gpd": 0,
        "fees_assessed_cents": 0,
        "fees_paid_cents": 0,
        "fees_credited_cents": 0,
        "fee_balance_cents": 0,
        "open_repair_order_count": 0,
        "water_quality_flag": False,
        "risk_tier": "LOW",
        "transfer_hold": False,
    })
    store.parcels[parcel["id"]] = parcel
    return response.ok(serialize.parcel(parcel), 201)


@bp.get("/parcels")
def list_parcels():
    authenticate(ALL_ROLES)
    limit, offset = v.pagination()
    county_code = v.q("county_code")
    risk_tier = v.q("risk_tier")
    transfer_hold = v.q_bool("transfer_hold")

    rows = ordered(store.parcels.values())
    if county_code is not None:
        rows = [r for r in rows if r["county_code"] == county_code]
    if risk_tier is not None:
        rows = [r for r in rows if r["risk_tier"] == risk_tier]
    if transfer_hold is not None:
        rows = [r for r in rows if r["transfer_hold"] == transfer_hold]

    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(serialize.many("parcel", page), limit, offset, total)


@bp.get("/parcels/<parcel_id>")
def read_parcel(parcel_id):
    authenticate(ALL_ROLES)
    parcel = lookup.parcel(parcel_id)
    return response.ok(serialize.parcel(parcel))


@bp.get("/parcels/<parcel_id>/wells")
def list_parcel_wells(parcel_id):
    authenticate(READ_PARCEL_CHILD_ROLES)
    parcel = lookup.parcel(parcel_id)
    limit, offset = v.pagination()
    well_type = v.q("well_type")
    rows = derive.wells_of_parcel(parcel["id"])
    if well_type is not None:
        rows = [r for r in rows if r["well_type"] == well_type]
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(serialize.many("well", page), limit, offset, total)


@bp.get("/parcels/<parcel_id>/site-evaluations")
def list_parcel_site_evaluations(parcel_id):
    authenticate(READ_PARCEL_CHILD_ROLES)
    parcel = lookup.parcel(parcel_id)
    limit, offset = v.pagination()
    status = v.q("status")
    rows = [e for e in ordered(store.site_evaluations.values())
            if e["parcel_id"] == parcel["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(serialize.many("site_evaluation", page),
                            limit, offset, total)


@bp.get("/parcels/<parcel_id>/compliance-dossier")
def compliance_dossier(parcel_id):
    authenticate(DOSSIER_ROLES)
    parcel = lookup.parcel(parcel_id)
    permits = derive.operating_permits_of_parcel(parcel["id"])
    certified = [t for t in ordered(store.transfer_inspections.values())
                 if t["parcel_id"] == parcel["id"] and t["certified_at"] is not None]
    latest_grade = None
    if certified:
        latest = max(certified, key=lambda t: (t["certified_at"], t["_seq"]))
        latest_grade = latest["certificate_grade"]
    data = {
        "parcel_id": parcel["id"],
        "risk_tier": parcel["risk_tier"],
        "transfer_hold": parcel["transfer_hold"],
        "fee_balance_cents": parcel["fee_balance_cents"],
        "permitted_design_flow_gpd": parcel["permitted_design_flow_gpd"],
        "max_design_flow_gpd": parcel["max_design_flow_gpd"],
        "open_repair_order_count": parcel["open_repair_order_count"],
        "water_quality_flag": parcel["water_quality_flag"],
        "well_count": len(derive.wells_of_parcel(parcel["id"])),
        "active_operating_permit_count": sum(1 for p in permits
                                             if p["status"] == "ACTIVE"),
        "latest_certificate_grade": latest_grade,
    }
    return response.ok(data)


@bp.post("/parcels/<parcel_id>/fee-payments")
def record_fee_payment(parcel_id):
    actor = authenticate(["Applicant", "RecordsClerk"])
    parcel = lookup.parcel(parcel_id)
    body = v.body()
    amount_cents = v.req_int(body, "amount_cents", minimum=0)
    if actor.role == "Applicant" and parcel["owner_user_id"] != actor.user_id:
        raise ApiError("ERR_NOT_PARCEL_OWNER")

    parcel["fees_paid_cents"] += amount_cents
    derive.recompute_parcel(parcel, force_bump=True)
    return response.ok(serialize.parcel(parcel))
