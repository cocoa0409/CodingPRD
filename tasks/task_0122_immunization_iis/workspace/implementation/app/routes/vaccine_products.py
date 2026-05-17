"""Vaccine product routes: create, read, list."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from .. import store
from ..auth import require_roles
from ..errors import APIError
from ..helpers import (
    ensure_enum,
    is_int,
    is_list,
    is_nonneg_int,
    optional_field,
    paginate,
    parse_json_body,
    parse_pagination,
    require_field,
)
from ..responses import build_envelope


bp = Blueprint("vaccine_products", __name__)


ANTIGEN_VALUES = {
    "DTAP_DIPHTHERIA",
    "DTAP_TETANUS",
    "DTAP_PERTUSSIS",
    "MMR_MEASLES",
    "MMR_MUMPS",
    "MMR_RUBELLA",
    "HEPB",
    "HPV",
    "POLIO",
    "VARICELLA",
}
ROUTE_VALUES = {"IM", "SC", "ORAL", "INTRANASAL"}
ALLERGEN_VALUES = {"EGG", "LATEX", "NEOMYCIN", "GELATIN", "YEAST", "OTHER"}
PRODUCT_STATUSES = {"ACTIVE", "DISCONTINUED"}


def _serialize(p: dict) -> dict:
    return {
        "id": p["id"],
        "cvx_code": p["cvx_code"],
        "trade_name": p["trade_name"],
        "antigens": p["antigens"],
        "min_age_days": p["min_age_days"],
        "max_age_days": p["max_age_days"],
        "route": p["route"],
        "contraindication_flags": p["contraindication_flags"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/vaccine-products")
@require_roles(["PublicHealthOfficer"])
def create_product():
    body = parse_json_body()
    cvx = require_field(body, "cvx_code")
    if not isinstance(cvx, str) or not (1 <= len(cvx) <= 6):
        raise APIError("ERR_VALIDATION", "cvx_code must be a string 1..6 chars.")
    # Global uniqueness among ACTIVE products.
    for existing in store.vaccine_products.values():
        if existing["cvx_code"] == cvx and existing["status"] == "ACTIVE":
            raise APIError("ERR_VALIDATION", "cvx_code already in use by an active product.")
    trade_name = require_field(body, "trade_name")
    if not isinstance(trade_name, str) or not trade_name:
        raise APIError("ERR_VALIDATION", "trade_name must be a non-empty string.")
    antigens = require_field(body, "antigens", type_check=is_list)
    if not antigens:
        raise APIError("ERR_VALIDATION", "antigens must have at least 1 element.")
    for a in antigens:
        ensure_enum(a, ANTIGEN_VALUES, "antigens")
    min_age = require_field(body, "min_age_days", type_check=is_nonneg_int)
    max_age = optional_field(body, "max_age_days", default=None,
                             type_check=lambda v: v is None or (is_int(v) and v >= 0))
    route = ensure_enum(require_field(body, "route"), ROUTE_VALUES, "route")
    contras = optional_field(body, "contraindication_flags", default=[], type_check=is_list)
    if contras is None:
        contras = []
    for c in contras:
        ensure_enum(c, ALLERGEN_VALUES, "contraindication_flags")

    with store.lock:
        record = {
            "cvx_code": cvx,
            "trade_name": trade_name,
            "antigens": list(antigens),
            "min_age_days": min_age,
            "max_age_days": max_age,
            "route": route,
            "contraindication_flags": list(contras),
            "status": "ACTIVE",
        }
        store.stamp_create(record)
        store.vaccine_products[record["id"]] = record

    return jsonify(build_envelope(_serialize(record), "object")), 201


@bp.get("/vaccine-products/<product_id>")
@require_roles(["SchoolRegistrar", "ProviderClinician", "ReviewingClinician", "PublicHealthOfficer"])
def read_product(product_id: str):
    p = store.vaccine_products.get(product_id)
    if not p:
        raise APIError("ERR_PRODUCT_NOT_FOUND", f"VaccineProduct {product_id} not found.")
    return jsonify(build_envelope(_serialize(p), "object")), 200


@bp.get("/vaccine-products")
@require_roles(["SchoolRegistrar", "ProviderClinician", "ReviewingClinician", "PublicHealthOfficer"])
def list_products():
    limit, offset = parse_pagination()
    status_q = request.args.get("status")
    antigen_q = request.args.get("antigen")
    if status_q is not None and status_q not in PRODUCT_STATUSES:
        raise APIError("ERR_VALIDATION", "status filter has invalid value.")
    if antigen_q is not None and antigen_q not in ANTIGEN_VALUES:
        raise APIError("ERR_VALIDATION", "antigen filter has invalid value.")

    rows = list(store.vaccine_products.values())
    if status_q is not None:
        rows = [r for r in rows if r["status"] == status_q]
    if antigen_q is not None:
        rows = [r for r in rows if antigen_q in r["antigens"]]
    rows.sort(key=lambda r: r["created_at"])
    page, meta = paginate(rows, limit, offset)
    return jsonify(build_envelope([_serialize(r) for r in page], "array", meta)), 200
