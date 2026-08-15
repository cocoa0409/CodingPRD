"""Payer registration, read, and payer-scoped contract listing."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_PAYER_NOT_FOUND
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from util import (
    apply_filters,
    get_json_body,
    optional_enum,
    paginate,
    parse_pagination,
    require_enum,
    require_string,
    sort_created,
)

bp = Blueprint("payers", __name__)

PAYER_TYPES = {"COMMERCIAL", "MEDICARE_ADVANTAGE", "MEDICAID_MANAGED"}
CONF_TIERS = {"STANDARD", "PROPRIETARY"}


def get_payer_or_404(pid: str) -> dict:
    p = db.payers.get(pid)
    if p is None:
        raise_err(ERR_PAYER_NOT_FOUND, "Payer not found")
    return p


@bp.post("/transparency/payers")
@require_roles("ContractManager")
def create_payer(_user_id: str, _role: str):
    body = get_json_body()
    name = require_string(body, "name")
    payer_type = require_enum(body, "payer_type", PAYER_TYPES)
    tier = optional_enum(body, "confidentiality_tier", CONF_TIERS, default="STANDARD")
    payer = db.stamp_new({
        "name": name,
        "payer_type": payer_type,
        "confidentiality_tier": tier,
    })
    db.payers[payer["id"]] = payer
    return success_object(db.public(payer), 201)


@bp.get("/transparency/payers/<pid>")
@require_roles(*ALL_ROLES)
def get_payer(pid: str, _user_id: str, _role: str):
    return success_object(db.public(get_payer_or_404(pid)), 200)


@bp.get("/transparency/payers/<pid>/payer-contracts")
@require_roles(*ALL_ROLES)
def list_payer_contracts(pid: str, _user_id: str, _role: str):
    get_payer_or_404(pid)
    limit, offset = parse_pagination()
    items = [c for c in db.payer_contracts.values() if c["payer_id"] == pid]
    items = apply_filters(items, ["status"])
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([db.public(c) for c in page], limit, offset, total)
