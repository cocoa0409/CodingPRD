"""Alloy compatibility rule endpoints."""
from flask import Blueprint, request

from db import store
from errors import (
    ERR_DUPLICATE_COMPATIBILITY_RULE,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    raise_err,
)
from helpers import (
    body_json,
    check_enum,
    check_string,
    paginate,
    parse_pagination,
    stamp_new,
)
from middleware import require_roles, STAFF_ROLES
from response import no_content, success_list, success_object
from serializers import compat_rule_view

bp = Blueprint("compat_rules", __name__)

CHEMISTRY_FAMILIES = {"SULFURIC", "CHROMIC", "NICKEL", "ZINC", "COPPER", "CYANIDE"}
PROCESS_TYPES = {"ANODIZE", "PLATE"}
COMPATIBILITIES = {"COMPATIBLE", "CONDITIONAL", "INCOMPATIBLE"}


@bp.route("/alloy-compatibility-rules", methods=["POST"])
def create_rule():
    user_id, role = require_roles({"LabChemist", "ShopManager"})
    data = body_json()
    alloy_code = check_string(data, "alloy_code", required=True)
    process_type = check_enum(data, "process_type", PROCESS_TYPES, required=True)
    chemistry_family = check_enum(data, "chemistry_family", CHEMISTRY_FAMILIES, required=True)
    compatibility = check_enum(data, "compatibility", COMPATIBILITIES, required=True)
    notes = check_string(data, "notes", required=False)

    # Uniqueness on (alloy_code, process_type, chemistry_family)
    for r in store.compat_rules.values():
        if (
            r["alloy_code"] == alloy_code
            and r["process_type"] == process_type
            and r["chemistry_family"] == chemistry_family
        ):
            raise_err(ERR_DUPLICATE_COMPATIBILITY_RULE, "compatibility rule already exists for this triple")

    rule = stamp_new({
        "alloy_code": alloy_code,
        "process_type": process_type,
        "chemistry_family": chemistry_family,
        "compatibility": compatibility,
        "notes": notes,
    })
    store.compat_rules[rule["id"]] = rule
    return success_object(compat_rule_view(rule), status=201)


@bp.route("/alloy-compatibility-rules", methods=["GET"])
def list_rules():
    user_id, role = require_roles(STAFF_ROLES)
    limit, offset = parse_pagination()
    alloy_code = request.args.get("alloy_code")
    chemistry_family = request.args.get("chemistry_family")
    items = sorted(store.compat_rules.values(), key=lambda r: (r["created_at"], r["id"]))
    if alloy_code is not None:
        items = [r for r in items if r["alloy_code"] == alloy_code]
    if chemistry_family is not None:
        items = [r for r in items if r["chemistry_family"] == chemistry_family]
    page, total = paginate(items, limit, offset)
    return success_list([compat_rule_view(r) for r in page], limit, offset, total)


@bp.route("/alloy-compatibility-rules/<rule_id>", methods=["DELETE"])
def delete_rule(rule_id):
    user_id, role = require_roles({"LabChemist", "ShopManager"})
    rule = store.compat_rules.get(rule_id)
    if rule is None:
        raise_err(ERR_NOT_FOUND, "compatibility rule not found")
    del store.compat_rules[rule_id]
    return no_content()
