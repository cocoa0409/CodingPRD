"""PQR and WPS routes (nested)."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError, ERR_STALE_VERSION, ERR_PQR_NOT_DRAFT, ERR_INVALID_THICKNESS_RANGE,
    ERR_WPS_NOT_DRAFT, ERR_PQR_NOT_APPROVED, ERR_SEGREGATION_OF_DUTIES,
    ERR_WPS_PQR_PROCESS_MISMATCH, ERR_WPS_PQR_MATERIAL_MISMATCH,
    ERR_WPS_THICKNESS_OUTSIDE_PQR, ERR_WPS_REVISION_CONFLICT, invalid_request,
)
from helpers import json_body, require_fields, parse_int, parse_number, paginate, PROCESSES
from middleware import require_roles, require_any
from response import success_object, success_list
from serializers import pqr_out, wps_out
from services import (
    stamp_new, make_versioned, mutate, get_shop, get_pqr, get_wps,
    wps_supersession_cascade,
)

bp = Blueprint("docs", __name__)


# ---------------------------------------------------------------------------
# PQR
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/shops/<shop_id>/pqrs", methods=["POST"])
@require_roles("QCManager")
def create_pqr(user_id, role, shop_id):
    shop = get_shop(shop_id)
    body = json_body()
    require_fields(body, [
        "pqr_number", "process", "base_metal_spec",
        "thickness_range_min_mm", "thickness_range_max_mm", "test_report_id",
    ])
    if body["process"] not in PROCESSES:
        raise invalid_request("process must be one of SMAW, GMAW, FCAW, GTAW, SAW")
    pqr = stamp_new({
        "shop_id": shop["id"],
        "pqr_number": body["pqr_number"],
        "process": body["process"],
        "base_metal_spec": body["base_metal_spec"],
        "thickness_range_min_mm": parse_number(body["thickness_range_min_mm"], "thickness_range_min_mm"),
        "thickness_range_max_mm": parse_number(body["thickness_range_max_mm"], "thickness_range_max_mm"),
        "test_report_id": body["test_report_id"],
        "reviewed_by_user_id": None,
        "status": "DRAFT",
    })
    make_versioned(pqr)
    db.pqrs[pqr["id"]] = pqr
    return success_object(pqr_out(pqr), status=201)


@bp.route("/weld-shop/shops/<shop_id>/pqrs", methods=["GET"])
@require_any
def list_pqrs(user_id, role, shop_id):
    shop = get_shop(shop_id)
    records = [p for p in db.pqrs.values() if p["shop_id"] == shop["id"]]
    page, limit, offset, total = paginate(records)
    return success_list([pqr_out(p) for p in page], limit, offset, total)


@bp.route("/weld-shop/shops/<shop_id>/pqrs/<pqr_id>", methods=["GET"])
@require_any
def get_pqr_route(user_id, role, shop_id, pqr_id):
    get_shop(shop_id)
    return success_object(pqr_out(get_pqr(shop_id, pqr_id)))


@bp.route("/weld-shop/shops/<shop_id>/pqrs/<pqr_id>/approve", methods=["POST"])
@require_roles("QCManager")
def approve_pqr(user_id, role, shop_id, pqr_id):
    get_shop(shop_id)
    pqr = get_pqr(shop_id, pqr_id)
    if pqr["status"] != "DRAFT":
        raise ApiError(ERR_PQR_NOT_DRAFT, 409, "PQR must be DRAFT to approve")
    if not (pqr["thickness_range_max_mm"] > pqr["thickness_range_min_mm"]):
        raise ApiError(ERR_INVALID_THICKNESS_RANGE, 422,
                       "thickness_range_max_mm must be > thickness_range_min_mm")
    pqr["status"] = "APPROVED"
    pqr["reviewed_by_user_id"] = user_id
    mutate(pqr)
    return success_object(pqr_out(pqr))


@bp.route("/weld-shop/shops/<shop_id>/pqrs/<pqr_id>/reject", methods=["POST"])
@require_roles("QCManager")
def reject_pqr(user_id, role, shop_id, pqr_id):
    get_shop(shop_id)
    pqr = get_pqr(shop_id, pqr_id)
    if pqr["status"] != "DRAFT":
        raise ApiError(ERR_PQR_NOT_DRAFT, 409, "PQR must be DRAFT to reject")
    pqr["status"] = "REJECTED"
    mutate(pqr)
    return success_object(pqr_out(pqr))


# ---------------------------------------------------------------------------
# WPS
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/shops/<shop_id>/wps", methods=["POST"])
@require_roles("QCManager")
def create_wps(user_id, role, shop_id):
    shop = get_shop(shop_id)
    body = json_body()
    require_fields(body, [
        "wps_number", "revision", "pqr_id", "process", "base_metal_spec",
        "thickness_min_mm", "thickness_max_mm",
    ])
    if body["process"] not in PROCESSES:
        raise invalid_request("process must be one of SMAW, GMAW, FCAW, GTAW, SAW")
    wps = stamp_new({
        "shop_id": shop["id"],
        "wps_number": body["wps_number"],
        "revision": parse_int(body["revision"], "revision"),
        "pqr_id": body["pqr_id"],
        "pinned_pqr_version": None,
        "process": body["process"],
        "base_metal_spec": body["base_metal_spec"],
        "thickness_min_mm": parse_number(body["thickness_min_mm"], "thickness_min_mm"),
        "thickness_max_mm": parse_number(body["thickness_max_mm"], "thickness_max_mm"),
        "superseded_by_id": None,
        "approved_by_user_id": None,
        "status": "DRAFT",
    })
    make_versioned(wps)
    db.wps[wps["id"]] = wps
    return success_object(wps_out(wps), status=201)


@bp.route("/weld-shop/shops/<shop_id>/wps", methods=["GET"])
@require_any
def list_wps(user_id, role, shop_id):
    shop = get_shop(shop_id)
    records = [w for w in db.wps.values() if w["shop_id"] == shop["id"]]
    for param in ("pqr_id", "superseded_by_id"):
        value = request.args.get(param)
        if value is not None:
            records = [w for w in records if w.get(param) == value]
    page, limit, offset, total = paginate(records)
    return success_list([wps_out(w) for w in page], limit, offset, total)


@bp.route("/weld-shop/shops/<shop_id>/wps/<wps_id>", methods=["GET"])
@require_any
def get_wps_route(user_id, role, shop_id, wps_id):
    get_shop(shop_id)
    return success_object(wps_out(get_wps(shop_id, wps_id)))


@bp.route("/weld-shop/shops/<shop_id>/wps/<wps_id>/approve", methods=["POST"])
@require_roles("QCManager")
def approve_wps(user_id, role, shop_id, wps_id):
    shop = get_shop(shop_id)
    wps = get_wps(shop_id, wps_id)
    # OCC gate (expected_wps_version non-optional)
    body = json_body()
    if "expected_wps_version" not in body or body["expected_wps_version"] is None:
        raise invalid_request("Missing required field: expected_wps_version")
    expected = parse_int(body["expected_wps_version"], "expected_wps_version")
    if expected != wps["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_wps_version does not match current version")
    # lifecycle gates
    if wps["status"] != "DRAFT":
        raise ApiError(ERR_WPS_NOT_DRAFT, 409, "WPS must be DRAFT to approve")
    pqr = db.pqrs.get(wps["pqr_id"])
    if pqr is None or pqr["shop_id"] != shop["id"] or pqr["status"] != "APPROVED":
        raise ApiError(ERR_PQR_NOT_APPROVED, 422,
                       "Referenced PQR must be APPROVED at WPS approval")
    # segregation of duties: approver must differ from the PQR reviewer
    if user_id == pqr["reviewed_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "WPS approver must differ from supporting PQR reviewer")
    # welding-code agreement
    if wps["process"] != pqr["process"]:
        raise ApiError(ERR_WPS_PQR_PROCESS_MISMATCH, 422,
                       "WPS.process != PQR.process")
    if wps["base_metal_spec"] != pqr["base_metal_spec"]:
        raise ApiError(ERR_WPS_PQR_MATERIAL_MISMATCH, 422,
                       "WPS.base_metal_spec != PQR.base_metal_spec")
    # thickness envelope, inclusive boundaries
    if not (
        pqr["thickness_range_min_mm"] <= wps["thickness_min_mm"]
        and wps["thickness_max_mm"] <= pqr["thickness_range_max_mm"]
    ):
        raise ApiError(ERR_WPS_THICKNESS_OUTSIDE_PQR, 422,
                       "WPS thickness envelope not contained in PQR envelope")
    # revision uniqueness
    conflict = any(
        w["id"] != wps["id"]
        and w["shop_id"] == shop["id"]
        and w["wps_number"] == wps["wps_number"]
        and w["revision"] == wps["revision"]
        and w["status"] == "APPROVED"
        for w in db.wps.values()
    )
    if conflict:
        raise ApiError(ERR_WPS_REVISION_CONFLICT, 409,
                       "Another WPS with same wps_number and revision already APPROVED")
    wps["pinned_pqr_version"] = pqr["version"]
    wps["approved_by_user_id"] = user_id
    wps["status"] = "APPROVED"
    mutate(wps)
    wps_supersession_cascade(shop, wps)
    return success_object(wps_out(wps))


@bp.route("/weld-shop/shops/<shop_id>/wps/<wps_id>/reject", methods=["POST"])
@require_roles("QCManager")
def reject_wps(user_id, role, shop_id, wps_id):
    get_shop(shop_id)
    wps = get_wps(shop_id, wps_id)
    if wps["status"] != "DRAFT":
        raise ApiError(ERR_WPS_NOT_DRAFT, 409, "WPS must be DRAFT to reject")
    wps["status"] = "REJECTED"
    mutate(wps)
    return success_object(wps_out(wps))
