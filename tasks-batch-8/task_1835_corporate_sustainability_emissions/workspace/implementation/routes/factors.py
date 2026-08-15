"""Emission factor library (PRD 3.1)."""
from flask import Blueprint

import domain
from envelope import ok
from errors import err, invalid_state, not_found
from http_util import (
    MANAGER,
    READ_ROLES,
    get_body,
    require_roles,
    v_datetime,
    v_enum,
    v_int,
    v_num,
    v_str,
)
from store import db, new_entity, touch

bp = Blueprint("factors", __name__, url_prefix="/sustainability")

SCOPE_CATEGORIES = {
    "SCOPE1_STATIONARY",
    "SCOPE2_GRID",
    "SCOPE2_RESIDUAL_MIX",
    "SCOPE3_TRAVEL",
    "SCOPE3_EEIO_SPEND",
}
FACTOR_STATUSES = {"DRAFT", "PUBLISHED", "RETIRED"}


def load_factor(factor_id):
    factor = db.factors.get(factor_id)
    if factor is None:
        raise not_found(f"EmissionFactor {factor_id} not found")
    return factor


@bp.route("/emission-factors", methods=["POST"])
@require_roles(MANAGER)
def create_factor():
    body = get_body()
    scope_category = v_enum(body, "scope_category", SCOPE_CATEGORIES)
    region_code = v_str(body, "region_code")
    unit = v_str(body, "unit")
    value = v_num(body, "value_tco2e_per_unit")
    library_version = v_int(body, "library_version")
    valid_from_raw, valid_from = v_datetime(body, "valid_from")
    valid_to_raw, valid_to = v_datetime(body, "valid_to")
    factor = new_entity(
        {
            "scope_category": scope_category,
            "region_code": region_code,
            "unit": unit,
            "value_tco2e_per_unit": value,
            "library_version": library_version,
            "valid_from": valid_from_raw,
            "valid_to": valid_to_raw,
            "status": "DRAFT",
            "_vf": valid_from,
            "_vt": valid_to,
        }
    )
    db.factors[factor["id"]] = factor
    return ok(domain.ser_factor(factor), status=201)


@bp.route("/emission-factors/<factor_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_factor(factor_id):
    return ok(domain.ser_factor(load_factor(factor_id)))


@bp.route("/emission-factors/<factor_id>/transition", methods=["POST"])
@require_roles(MANAGER)
def factor_transition(factor_id):
    factor = load_factor(factor_id)
    body = get_body()
    to_state = v_enum(body, "to_state", FACTOR_STATUSES)
    if (factor["status"], to_state) not in (
        ("DRAFT", "PUBLISHED"),
        ("PUBLISHED", "RETIRED"),
    ):
        raise invalid_state(
            f"EmissionFactor in status {factor['status']} cannot transition to {to_state}"
        )
    if to_state == "PUBLISHED":
        # Closed-window pairwise disjointness among PUBLISHED factors sharing
        # (scope_category, region_code); touching endpoints count as overlap.
        for other in db.factors.values():
            if other["id"] == factor["id"] or other["status"] != "PUBLISHED":
                continue
            if (
                other["scope_category"] == factor["scope_category"]
                and other["region_code"] == factor["region_code"]
                and factor["_vf"] <= other["_vt"]
                and factor["_vt"] >= other["_vf"]
            ):
                raise err(
                    "ERR_FACTOR_WINDOW_OVERLAP",
                    409,
                    "Validity window overlaps another PUBLISHED factor with the "
                    "same scope_category and region_code",
                )
    factor["status"] = to_state
    touch(factor)
    return ok(domain.ser_factor(factor))
