"""Annexation petitions: file, review, recommend, withdraw, resubmit."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import (ALL_ROLES, body, get_district, get_scoped, req_int,
                        req_str, require_roles)
from response import ok_list, ok_object, paginate
from services import annexation_fee_split, new_common, ser_petition, touch

bp = Blueprint("petitions", __name__)


def get_petition(district_id, petition_id):
    return get_scoped(db.petitions, petition_id, district_id, "ERR_PETITION_NOT_FOUND", "AnnexationPetition")


@bp.post("/districts/<district_id>/annexation-petitions")
@require_roles(["BillingClerk"])
def create_petition(user_id, role, district_id):
    b = body()
    name = req_str(b, "petitioner_name")
    acres = req_int(b, "parcel_acres", strict_minimum=1)
    area_id = req_str(b, "parent_service_area_id")
    deposit = req_int(b, "deposit_cents", minimum=0)
    d = get_district(district_id)
    get_scoped(db.service_areas, area_id, d["id"], "ERR_AREA_NOT_FOUND", "ServiceArea")
    p = new_common()
    p.update({
        "district_id": d["id"],
        "petitioner_name": name,
        "parcel_acres": acres,
        "parent_service_area_id": area_id,
        "deposit_cents": deposit,
        "feasibility_fee_cents": None,
        "refund_cents": None,
        "status": "SUBMITTED",
    })
    db.petitions[p["id"]] = p
    return ok_object(ser_petition(p), 201)


@bp.get("/districts/<district_id>/annexation-petitions")
@require_roles(ALL_ROLES)
def list_petitions(user_id, role, district_id):
    d = get_district(district_id)
    items = [p for p in db.petitions.values() if p["district_id"] == d["id"]]
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_petition(p) for p in page], limit, offset, total)


@bp.post("/districts/<district_id>/annexation-petitions/<petition_id>/begin-review")
@require_roles(["BillingClerk"])
def begin_review(user_id, role, district_id, petition_id):
    d = get_district(district_id)
    p = get_petition(d["id"], petition_id)
    if p["status"] != "SUBMITTED":
        raise ApiError("ERR_PETITION_NOT_REVIEWABLE", 409, "Petition is not SUBMITTED")
    p["status"] = "FEASIBILITY_REVIEW"
    touch(p)
    return ok_object(ser_petition(p))


@bp.post("/districts/<district_id>/annexation-petitions/<petition_id>/recommend")
@require_roles(["FieldOperator"])
def recommend(user_id, role, district_id, petition_id):
    d = get_district(district_id)
    p = get_petition(d["id"], petition_id)
    if p["status"] != "FEASIBILITY_REVIEW":
        raise ApiError("ERR_PETITION_NOT_REVIEWABLE", 409, "Petition is not in FEASIBILITY_REVIEW")
    area = db.service_areas.get(p["parent_service_area_id"])
    if area is None or area["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Parent service area must be ACTIVE for recommendation")
    p["status"] = "APPROVED_PENDING_VOTE"
    touch(p)
    return ok_object(ser_petition(p))


@bp.post("/districts/<district_id>/annexation-petitions/<petition_id>/withdraw")
@require_roles(["BillingClerk"])
def withdraw(user_id, role, district_id, petition_id):
    d = get_district(district_id)
    p = get_petition(d["id"], petition_id)
    if p["status"] != "FEASIBILITY_REVIEW":
        raise ApiError("ERR_PETITION_NOT_REVIEWABLE", 409, "Only a petition in FEASIBILITY_REVIEW may be withdrawn")
    fee, refund = annexation_fee_split(p["deposit_cents"])
    p["feasibility_fee_cents"] = fee
    p["refund_cents"] = refund
    p["status"] = "WITHDRAWN"
    touch(p)
    return ok_object(ser_petition(p))


@bp.post("/districts/<district_id>/annexation-petitions/<petition_id>/resubmit")
@require_roles(["BillingClerk"])
def resubmit(user_id, role, district_id, petition_id):
    b = body()
    additional = req_int(b, "additional_deposit_cents", minimum=0)
    d = get_district(district_id)
    p = get_petition(d["id"], petition_id)
    if p["status"] != "REJECTED":
        raise ApiError("ERR_PETITION_NOT_REVIEWABLE", 409, "Only a REJECTED petition may be resubmitted")
    p["deposit_cents"] += additional
    p["status"] = "SUBMITTED"
    touch(p)
    return ok_object(ser_petition(p))
