"""GeneratorSite endpoints."""

from __future__ import annotations

from flask import Blueprint, request

from core import (
    base_entity,
    bump,
    compute_category,
    new_id,
    now_iso,
    recompute_category_and_reports,
)
from db import clock, store
from errors import (
    ApiError,
    ERR_DUPLICATE_EPA_ID,
    ERR_INVALID_REQUEST,
    invalid_request,
    not_found,
)
from middleware import require_roles
from response import success_list, success_object
from validators import (
    reject_unknown_fields,
    require_fields,
    require_object,
    req_str,
)

bp = Blueprint("sites", __name__)

ALL_ROLES = ("EHSManager", "WasteCoordinator", "ComplianceAuditor", "TransporterAgent", "TSDFAgent")


def _parse_pagination() -> tuple[int, int]:
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (ValueError, TypeError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (ValueError, TypeError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def site_view(site: dict) -> dict:
    return dict(site)


@bp.route("/hazwaste/generator-sites", methods=["POST"])
def create_site():
    user_id, _ = require_roles("EHSManager")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"name", "epa_id_number"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["name", "epa_id_number"])
    name = req_str(body, "name")
    epa = req_str(body, "epa_id_number", allow_empty=False)

    for s in store.sites.values():
        if s["epa_id_number"] == epa:
            raise ApiError(ERR_DUPLICATE_EPA_ID, 409, "epa_id_number already registered")

    site = base_entity()
    site.update(
        {
            "name": name,
            "epa_id_number": epa,
            "current_month_key": clock.now().strftime("%Y-%m"),
            "current_month_generated_kg": 0,
            "generator_category": "VSQG",
            "open_exception_count": 0,
            "open_discrepancy_count": 0,
        }
    )
    store.sites[site["id"]] = site
    return success_object(site_view(site), status=201)


@bp.route("/hazwaste/generator-sites", methods=["GET"])
def list_sites():
    require_roles(*ALL_ROLES)
    limit, offset = _parse_pagination()
    items = sorted(store.sites.values(), key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([site_view(s) for s in page], limit, offset, total)


@bp.route("/hazwaste/generator-sites/<siteId>", methods=["GET"])
def get_site(siteId: str):
    require_roles(*ALL_ROLES)
    site = store.sites.get(siteId)
    if site is None:
        raise not_found("site not found")
    return success_object(site_view(site))
