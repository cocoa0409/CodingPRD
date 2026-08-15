"""Surety bond endpoints (PRD section 3.4).

Bond windows are HALF-OPEN [effective_from, effective_to). Activation requires
the logical clock inside the window; bonds age lazily ACTIVE -> EXPIRED when
the clock reaches effective_to.
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_BOND_INVALID_STATE,
    ERR_BOND_NOT_FOUND,
    ERR_BOND_NOT_IN_WINDOW,
    ERR_INVALID_REQUEST,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import domain
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_int,
    require_string,
    require_ts,
    sort_by_created_at,
)

bp = Blueprint("surety_bonds", __name__)


def _get_bond(bond_id: str) -> dict:
    bond = db.surety_bonds.get(bond_id)
    if bond is None:
        raise_err(ERR_BOND_NOT_FOUND, "SuretyBond id does not exist")
    return bond


@bp.route("/freight/surety-bonds", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_bond(_user_id: str, _role: str):
    body = get_json_body()
    bond_number = require_string(body, "bond_number")
    surety_company = require_string(body, "surety_company")
    coverage_amount_cents = require_int(body, "coverage_amount_cents", minimum=1)
    effective_from = require_ts(body, "effective_from")
    effective_to = require_ts(body, "effective_to")
    if not (effective_from < effective_to):
        raise_err(ERR_INVALID_REQUEST, "effective_from must be strictly before effective_to")

    bond = {
        "bond_number": bond_number,
        "surety_company": surety_company,
        "coverage_amount_cents": coverage_amount_cents,
        "available_coverage_cents": coverage_amount_cents,
        "effective_from": db.format_iso(effective_from),
        "effective_to": db.format_iso(effective_to),
        "status": "INACTIVE",
    }
    db.stamp_new(bond)
    db.surety_bonds[bond["id"]] = bond
    return success_object(domain.serialize_bond(bond), 201)


@bp.route("/freight/surety-bonds", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_bonds(_user_id: str, _role: str):
    domain.lazy_expire_all_bonds()
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.surety_bonds.values()))
    items = apply_filters(items, ["status"])
    page, total = paginate(items, limit, offset)
    return success_list([domain.serialize_bond(b) for b in page], limit, offset, total)


@bp.route("/freight/surety-bonds/<bond_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_bond(bond_id: str, _user_id: str, _role: str):
    return success_object(domain.serialize_bond(_get_bond(bond_id)))


@bp.route("/freight/surety-bonds/<bond_id>/activate", methods=["POST"])
@require_roles("ComplianceOfficer")
def activate_bond(bond_id: str, _user_id: str, _role: str):
    bond = _get_bond(bond_id)
    if bond["status"] != "INACTIVE":
        raise_err(ERR_BOND_INVALID_STATE, "Bond must be INACTIVE to activate")
    now = db.clock()
    if not (db.parse_iso(bond["effective_from"]) <= now < db.parse_iso(bond["effective_to"])):
        raise_err(ERR_BOND_NOT_IN_WINDOW, "Logical clock is outside the bond's effective window")
    bond["status"] = "ACTIVE"
    db.touch(bond)
    return success_object(domain.serialize_bond(bond))
