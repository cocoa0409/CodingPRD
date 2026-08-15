"""Subcontractor endpoints."""

from flask import Blueprint

from db import store
from errors import validation
from helpers import (
    get_body,
    require_string,
    require_int,
    optional_string,
    make_common_fields,
    get_subcontractor,
)
from middleware import require_roles
from response import success_object

bp = Blueprint("subcontractors", __name__)

SPECIALTY_TYPES = {
    "ART_CONSERVATION",
    "ELECTRONICS_DATA_RECOVERY",
    "DOCUMENT_FREEZE_DRYING",
    "FUR_CLEANING",
    "JEWELRY_APPRAISAL",
}


def serialize_sub(sub):
    return dict(sub)


@bp.route("/api/subcontractors", methods=["POST"])
def create_subcontractor():
    user_id, role = require_roles("ProjectManager")
    body = get_body()
    name = require_string(body, "name")
    specialty_types = body.get("specialty_types")
    if not isinstance(specialty_types, list) or len(specialty_types) == 0:
        raise validation("specialty_types must be a non-empty array")
    for st in specialty_types:
        if st not in SPECIALTY_TYPES:
            raise validation(f"Invalid specialty_type: {st}")
    max_concurrent = require_int(body, "max_concurrent_referrals", min_v=1)
    contact_email = optional_string(body, "contact_email")
    sub = make_common_fields()
    sub.update({
        "name": name,
        "specialty_types": list(specialty_types),
        "max_concurrent_referrals": max_concurrent,
        "active_referral_count": 0,
        "contact_email": contact_email,
    })
    store.subcontractors[sub["id"]] = sub
    return success_object(serialize_sub(sub), status=201)


@bp.route("/api/subcontractors/<sub_id>", methods=["GET"])
def read_subcontractor(sub_id):
    user_id, role = require_roles("ProjectManager", "InventoryTechnician")
    sub = get_subcontractor(sub_id)
    return success_object(serialize_sub(sub))
