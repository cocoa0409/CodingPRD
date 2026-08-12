"""MunicipalityProfile endpoints (§3.3)."""
from flask import Blueprint

from db import store
from errors import invalid_request
from middleware import ALL_ROLES, authed
from response import ok
from routes import list_response
from util import new_entity, serialize
from validate import json_body, req_int, req_str

bp = Blueprint("municipalities", __name__)


def profile_by_code(code):
    for p in store.municipalities.values():
        if p["municipality_code"] == code:
            return p
    return None


@bp.route("/rollout/municipality-profiles", methods=["POST"], strict_slashes=False)
@authed(["PermitCoordinator"])
def create_profile():
    body = json_body()
    code = req_str(body, "municipality_code")
    statutory = req_int(body, "statutory_review_days")
    observed = req_int(body, "observed_avg_review_days")
    validity = req_int(body, "permit_validity_days")
    fee_base = req_int(body, "fee_base_cents")
    fee_sqft = req_int(body, "fee_per_sqft_cents")
    if profile_by_code(code) is not None:
        invalid_request("municipality_code '%s' already exists" % code)
    profile = new_entity(store)
    profile.update({
        "municipality_code": code,
        "statutory_review_days": statutory,
        "observed_avg_review_days": observed,
        "permit_validity_days": validity,
        "fee_base_cents": fee_base,
        "fee_per_sqft_cents": fee_sqft,
    })
    store.municipalities[profile["id"]] = profile
    return ok(serialize(profile), status=201)


@bp.route("/rollout/municipality-profiles", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def list_profiles():
    return list_response(store.municipalities, [
        ("municipality_code", "municipality_code", "str"),
    ])
