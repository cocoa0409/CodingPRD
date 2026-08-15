"""Catalog registration: titles, rights holders, platforms (PRD §3.1)."""
from flask import Blueprint, request

from auth import (
    require_roles,
    ROLE_RIGHTS_MANAGER,
    ROLE_FINANCE_ANALYST,
    ROLE_FINANCE_CONTROLLER,
    ROLE_PLATFORM_BUYER,
)
from domain import (
    CONTENT_TYPES,
    PLATFORM_TYPES,
    list_page,
    ser_holder,
    ser_platform,
    ser_title,
)
from errors import (
    err,
    ERR_TITLE_NOT_FOUND,
    ERR_HOLDER_NOT_FOUND,
    ERR_PLATFORM_NOT_FOUND,
    ERR_FEE_STRUCTURE_INVALID,
)
from response import ok_list, ok_object
from store import DB
from validate import field_arr, field_enum, field_int, field_num, field_str, json_body

bp = Blueprint("catalog", __name__)

_CATALOG_READERS = (ROLE_RIGHTS_MANAGER, ROLE_FINANCE_ANALYST, ROLE_FINANCE_CONTROLLER)


# --------------------------------------------------------------------- titles
@bp.route("/licensing/titles", methods=["POST"])
def create_title():
    require_roles(ROLE_RIGHTS_MANAGER)
    body = json_body()
    title_code = field_str(body, "title_code")
    name = field_str(body, "name")
    content_type = field_enum(body, "content_type", CONTENT_TYPES)
    original_language = field_str(body, "original_language")
    production_year = field_int(body, "production_year")
    embargoed = field_arr(body, "embargoed_territories", required=False, default=[], elem_str=True)
    rec = DB.insert(
        "titles",
        {
            "title_code": title_code,
            "name": name,
            "content_type": content_type,
            "original_language": original_language,
            "production_year": production_year,
            "embargoed_territories": list(embargoed or []),
        },
    )
    return ok_object(ser_title(rec), status=201)


@bp.route("/licensing/titles", methods=["GET"])
def list_titles():
    require_roles(*_CATALOG_READERS)
    records = DB.all("titles")
    content_type = request.args.get("content_type")
    if content_type is not None:
        records = [t for t in records if t["content_type"] == content_type]
    page, limit, offset, total = list_page(records, request.args)
    return ok_list([ser_title(t) for t in page], limit, offset, total)


@bp.route("/licensing/titles/<tid>", methods=["GET"])
def get_title(tid):
    require_roles(*_CATALOG_READERS)
    rec = DB.get("titles", tid)
    if rec is None:
        err(ERR_TITLE_NOT_FOUND, "referenced title does not exist")
    return ok_object(ser_title(rec))


# -------------------------------------------------------------- rights holders
@bp.route("/licensing/rights-holders", methods=["POST"])
def create_holder():
    require_roles(ROLE_RIGHTS_MANAGER)
    body = json_body()
    name = field_str(body, "name")
    payee_reference = field_str(body, "payee_reference")
    royalty_share_pct = field_num(body, "royalty_share_pct")
    # business-fiscal: share must be in (0, 100]
    if not (0 < royalty_share_pct <= 100):
        err(ERR_FEE_STRUCTURE_INVALID, "royalty_share_pct must be in (0,100]")
    rec = DB.insert(
        "holders",
        {
            "name": name,
            "payee_reference": payee_reference,
            "royalty_share_pct": royalty_share_pct,
        },
    )
    return ok_object(ser_holder(rec), status=201)


@bp.route("/licensing/rights-holders", methods=["GET"])
def list_holders():
    require_roles(*_CATALOG_READERS)
    records = DB.all("holders")
    page, limit, offset, total = list_page(records, request.args)
    return ok_list([ser_holder(h) for h in page], limit, offset, total)


@bp.route("/licensing/rights-holders/<hid>", methods=["GET"])
def get_holder(hid):
    require_roles(*_CATALOG_READERS)
    rec = DB.get("holders", hid)
    if rec is None:
        err(ERR_HOLDER_NOT_FOUND, "referenced rights holder does not exist")
    return ok_object(ser_holder(rec))


# ------------------------------------------------------------------- platforms
@bp.route("/licensing/platforms", methods=["POST"])
def create_platform():
    require_roles(ROLE_RIGHTS_MANAGER)
    body = json_body()
    name = field_str(body, "name")
    platform_type = field_enum(body, "platform_type", PLATFORM_TYPES)
    metadata_spec_version = field_str(body, "metadata_spec_version")
    required_asset_profiles = field_arr(
        body, "required_asset_profiles", min_len=1, elem_str=True
    )
    rec = DB.insert(
        "platforms",
        {
            "name": name,
            "platform_type": platform_type,
            "metadata_spec_version": metadata_spec_version,
            "required_asset_profiles": list(required_asset_profiles),
        },
    )
    return ok_object(ser_platform(rec), status=201)


@bp.route("/licensing/platforms", methods=["GET"])
def list_platforms():
    require_roles(*_CATALOG_READERS, ROLE_PLATFORM_BUYER)
    records = DB.all("platforms")
    platform_type = request.args.get("platform_type")
    if platform_type is not None:
        records = [p for p in records if p["platform_type"] == platform_type]
    page, limit, offset, total = list_page(records, request.args)
    return ok_list([ser_platform(p) for p in page], limit, offset, total)


@bp.route("/licensing/platforms/<pid>", methods=["GET"])
def get_platform(pid):
    require_roles(*_CATALOG_READERS, ROLE_PLATFORM_BUYER)
    rec = DB.get("platforms", pid)
    if rec is None:
        err(ERR_PLATFORM_NOT_FOUND, "referenced platform does not exist")
    return ok_object(ser_platform(rec))
