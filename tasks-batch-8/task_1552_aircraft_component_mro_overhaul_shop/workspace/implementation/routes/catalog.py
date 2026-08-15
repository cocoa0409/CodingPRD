from flask import Blueprint

from db import store
from errors import ApiError
from helpers import (
    base_fields,
    get_part_or_404,
    ledger_fields,
    list_response,
    pub,
)
from middleware import ALL_ROLES, get_json_body, require_roles, validate_body
from response import ok

bp = Blueprint("catalog", __name__, url_prefix="/mro")

PART_SPEC = {
    "part_number": ("str", True),
    "ata_chapter": ("str", True),
    "is_rotable": ("bool", True),
    "cmm_reference": ("str", True),
    "replacement_value_cents": ("int", True),
    "ber_threshold_pct": ("int", False),
    "warranty_cycle_limit": ("int", True),
    "warranty_month_limit": ("int", True),
    "flat_overhaul_price_cents": ("int", True),
}

DIRECTIVE_SPEC = {
    "directive_type": ("enum", True, ["AD", "SB"]),
    "directive_number": ("str", True),
    "mandatory": ("bool", True),
    "description": ("str", True),
}


@bp.route("/part-catalog", methods=["POST"])
@require_roles("ShopManager")
def create_part():
    body = validate_body(get_json_body(), PART_SPEC)
    if any(p["part_number"] == body["part_number"] for p in store.parts.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "part_number already exists")
    p = dict(base_fields())
    p.update(
        {
            "part_number": body["part_number"],
            "ata_chapter": body["ata_chapter"],
            "is_rotable": body["is_rotable"],
            "cmm_reference": body["cmm_reference"],
            "replacement_value_cents": body["replacement_value_cents"],
            "ber_threshold_pct": (
                body["ber_threshold_pct"] if body["ber_threshold_pct"] is not None else 65
            ),
            "warranty_cycle_limit": body["warranty_cycle_limit"],
            "warranty_month_limit": body["warranty_month_limit"],
            "flat_overhaul_price_cents": body["flat_overhaul_price_cents"],
        }
    )
    store.parts[p["id"]] = p
    return ok(pub(p), 201)


@bp.route("/part-catalog/<partId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_part(partId):
    return ok(pub(get_part_or_404(partId)))


@bp.route("/part-catalog/<partId>/directives", methods=["POST"])
@require_roles("ShopManager")
def create_directive(partId):
    part = get_part_or_404(partId)
    body = validate_body(get_json_body(), DIRECTIVE_SPEC)
    if any(
        d["part_id"] == part["id"] and d["directive_number"] == body["directive_number"]
        for d in store.directives.values()
    ):
        raise ApiError("ERR_INVALID_REQUEST", 400, "directive_number already exists for this part")
    d = dict(ledger_fields())
    d.update(
        {
            "part_id": part["id"],
            "directive_type": body["directive_type"],
            "directive_number": body["directive_number"],
            "mandatory": body["mandatory"],
            "description": body["description"],
        }
    )
    store.directives[d["id"]] = d
    return ok(pub(d), 201)


@bp.route("/part-catalog/<partId>/directives", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_directives(partId):
    part = get_part_or_404(partId)
    return list_response([d for d in store.directives.values() if d["part_id"] == part["id"]])


@bp.route("/part-catalog/<partId>/units", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_part_units(partId):
    part = get_part_or_404(partId)
    return list_response([u for u in store.units.values() if u["part_id"] == part["id"]])
