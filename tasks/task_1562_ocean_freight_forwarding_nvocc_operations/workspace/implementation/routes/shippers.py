"""Shipper endpoints (PRD section 3.1)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_SHIPPER_INVALID_STATE,
    ERR_SHIPPER_NOT_FOUND,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import domain
from util import (
    apply_filters,
    get_json_body,
    optional_enum,
    optional_int,
    paginate,
    parse_pagination,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("shippers", __name__)

CREDIT_TERMS = {"PREPAID_ONLY", "NET_7", "NET_30"}


def _get_shipper(shipper_id: str) -> dict:
    shipper = db.shippers.get(shipper_id)
    if shipper is None:
        raise_err(ERR_SHIPPER_NOT_FOUND, "Shipper id does not exist")
    return shipper


@bp.route("/freight/shippers", methods=["POST"])
@require_roles("OperationsManager")
def create_shipper(_user_id: str, _role: str):
    body = get_json_body()
    legal_name = require_string(body, "legal_name")
    credit_limit_cents = require_int(body, "credit_limit_cents", minimum=0)
    credit_terms = optional_enum(body, "credit_terms", CREDIT_TERMS) or "PREPAID_ONLY"

    shipper = {
        "legal_name": legal_name,
        "credit_limit_cents": credit_limit_cents,
        "credit_terms": credit_terms,
        "credit_exposure_posted_cents": 0,
        "credit_exposure_forward_cents": 0,
        "status": "ACTIVE",
    }
    db.stamp_new(shipper)
    db.shippers[shipper["id"]] = shipper
    return success_object(domain.serialize_shipper(shipper), 201)


@bp.route("/freight/shippers", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_shippers(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.shippers.values()))
    items = apply_filters(items, ["status"])
    page, total = paginate(items, limit, offset)
    return success_list([domain.serialize_shipper(s) for s in page], limit, offset, total)


@bp.route("/freight/shippers/<shipper_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_shipper(shipper_id: str, _user_id: str, _role: str):
    return success_object(domain.serialize_shipper(_get_shipper(shipper_id)))


@bp.route("/freight/shippers/<shipper_id>/credit-terms", methods=["PATCH"])
@require_roles("FinanceController")
def patch_credit_terms(shipper_id: str, _user_id: str, _role: str):
    shipper = _get_shipper(shipper_id)
    body = get_json_body()
    credit_limit_cents = optional_int(body, "credit_limit_cents", minimum=0)
    credit_terms = optional_enum(body, "credit_terms", CREDIT_TERMS)

    if credit_limit_cents is not None:
        shipper["credit_limit_cents"] = credit_limit_cents
    if credit_terms is not None:
        shipper["credit_terms"] = credit_terms
    db.touch(shipper)
    # Exposures recompute; a SUSPENDED shipper stays SUSPENDED until reinstate.
    domain.recompute_shipper_exposure(shipper)
    return success_object(domain.serialize_shipper(shipper))


@bp.route("/freight/shippers/<shipper_id>/suspend", methods=["POST"])
@require_roles("FinanceController")
def suspend_shipper(shipper_id: str, _user_id: str, _role: str):
    shipper = _get_shipper(shipper_id)
    if shipper["status"] != "ACTIVE":
        raise_err(ERR_SHIPPER_INVALID_STATE, "Shipper must be ACTIVE to suspend")
    shipper["status"] = "SUSPENDED"
    db.touch(shipper)
    return success_object(domain.serialize_shipper(shipper))


@bp.route("/freight/shippers/<shipper_id>/reinstate", methods=["POST"])
@require_roles("FinanceController")
def reinstate_shipper(shipper_id: str, _user_id: str, _role: str):
    shipper = _get_shipper(shipper_id)
    if shipper["status"] != "SUSPENDED":
        raise_err(ERR_SHIPPER_INVALID_STATE, "Shipper must be SUSPENDED to reinstate")
    domain.recompute_shipper_exposure(shipper)
    if shipper["credit_exposure_posted_cents"] > shipper["credit_limit_cents"]:
        raise_err(
            ERR_CREDIT_LIMIT_EXCEEDED,
            "Posted credit exposure exceeds the credit limit",
        )
    shipper["status"] = "ACTIVE"
    db.touch(shipper)
    return success_object(domain.serialize_shipper(shipper))
