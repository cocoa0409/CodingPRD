"""Applicant registration + read."""
from flask import Blueprint

import serializers
from db import STORE, new_id
from errors import ApiError
from helpers import as_enum, as_list, as_str, body, get_applicant, req_field, stamp_new
from middleware import ANY_ROLE, require_roles
from response import ok

bp = Blueprint("applicants", __name__)

HU_CATEGORIES = {"NONE", "BEGINNING_FARMER", "SOCIALLY_DISADVANTAGED", "LIMITED_RESOURCE", "VETERAN"}


@bp.post("/eqip/applicants")
@require_roles("ProgramAdmin", "ConservationPlanner")
def create_applicant(_uid, _role):
    data = body()
    legal_name = as_str(req_field(data, "legal_name"), "legal_name")
    hu_category = data.get("hu_category", "NONE")
    hu_category = as_enum(hu_category, "hu_category", HU_CATEGORIES)
    parcel_ids = as_list(req_field(data, "parcel_ids"), "parcel_ids")
    for pid in parcel_ids:
        if not isinstance(pid, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "parcel_ids must be strings")
    a = {
        "id": new_id(),
        "legal_name": legal_name,
        "hu_category": hu_category,
        "historically_underserved": hu_category != "NONE",
        "parcel_ids": list(parcel_ids),
    }
    stamp_new(a)
    STORE.applicants[a["id"]] = a
    return ok(serializers.applicant(a), 201)


@bp.get("/eqip/applicants/<aid>")
@require_roles(*ANY_ROLE)
def get_one_applicant(aid, _uid, _role):
    return ok(serializers.applicant(get_applicant(aid)))
