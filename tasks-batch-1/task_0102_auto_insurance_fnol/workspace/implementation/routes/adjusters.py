"""Adjuster routes (PRD §3.1)."""
from flask import Blueprint

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import (get_json_body, require_resource, require_fields,
                     require_str, optional_enum, optional_bool)
from response import success

bp = Blueprint("adjusters", __name__)

LICENSE_TIERS = {"STANDARD", "SENIOR"}


@bp.route("/adjusters", methods=["POST"])
def create_adjuster():
    principal = authenticate()
    authorize(principal, {"ClaimsSupervisor"})
    body = get_json_body()
    require_fields(body, ["full_name"])
    full_name = require_str(body, "full_name")
    license_tier = optional_enum(body, "license_tier", LICENSE_TIERS, "STANDARD")
    active = optional_bool(body, "active", True)
    rec = {
        "full_name": full_name,
        "license_tier": license_tier,
        "active": active,
    }
    db.insert(db.adjusters, rec)
    return success(S.adjuster(rec), status=201)


@bp.route("/adjusters/<aid>", methods=["GET"])
def get_adjuster(aid):
    principal = authenticate()
    authorize(principal, {"ClaimsSupervisor", "ClaimsAdjuster", "TotalLossAdjuster"})
    rec = require_resource(db.adjusters, aid, "adjuster")
    return success(S.adjuster(rec), status=200)
