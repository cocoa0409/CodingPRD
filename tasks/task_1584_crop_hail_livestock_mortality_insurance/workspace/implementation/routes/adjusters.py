"""Adjuster roster endpoints (PRD 3.1)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from routes.common import resolve_carrier, resolve_adjuster
from serializers import adjuster_view
from services.core import OPEN_CLAIM_STATES  # noqa: F401  (re-export context)
from util import (
    get_json_body, reject_unknown_fields, require_string, require_int,
    require_string_list,
)

bp = Blueprint("adjusters", __name__)

READ_ROLES = ("PlatformAdmin", "Underwriter", "Adjuster", "ClaimsApprover")

SPECIES = {"CATTLE", "SWINE", "POULTRY", "EQUINE", "SHEEP"}

CREATE_FIELDS = {
    "full_name", "license_number", "county_codes", "species_qualified",
    "capacity_max_open_claims",
}


@bp.route("/carriers/<carrierId>/adjusters", methods=["POST"])
@require_roles("Underwriter")
def create_adjuster(carrierId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    full_name = require_string(body, "full_name")
    license_number = require_string(body, "license_number")
    county_codes = require_string_list(body, "county_codes")
    species_qualified = require_string_list(body, "species_qualified", allowed=SPECIES)
    capacity = require_int(body, "capacity_max_open_claims", minimum=0)

    for other in db.adjusters.values():
        if (other["carrier_id"] == carrier["id"]
                and other["license_number"] == license_number):
            raise_err(ERR_INVALID_REQUEST,
                      f"license_number {license_number} already registered for this carrier")

    adjuster = db.stamp_new({
        "carrier_id": carrier["id"],
        "full_name": full_name,
        "license_number": license_number,
        "county_codes": county_codes,
        "species_qualified": species_qualified,
        "capacity_max_open_claims": capacity,
        "status": "ACTIVE",
    }, carrier["current_utc"])
    db.adjusters[adjuster["id"]] = adjuster
    return success_object(adjuster_view(adjuster), 201)


@bp.route("/carriers/<carrierId>/adjusters/<adjusterId>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_adjuster(carrierId: str, adjusterId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    adjuster = resolve_adjuster(carrier["id"], adjusterId)
    return success_object(adjuster_view(adjuster))
