"""Takedown notices: read-only surface (PRD §3.10)."""
from flask import Blueprint, request

from auth import check_buyer_owns, require_roles, ROLE_RIGHTS_MANAGER, ROLE_PLATFORM_BUYER
from domain import list_page, ser_notice
from errors import err, ERR_NOTICE_NOT_FOUND
from response import ok_list, ok_object
from store import DB

bp = Blueprint("notices", __name__)


def _notice_platform_id(notice):
    lic = DB.get("licenses", notice["license_id"])
    return lic["platform_id"] if lic else None


@bp.route("/licensing/takedown-notices", methods=["GET"])
def list_notices():
    user_id, role = require_roles(ROLE_RIGHTS_MANAGER, ROLE_PLATFORM_BUYER)
    records = DB.all("notices")
    if role == ROLE_PLATFORM_BUYER:
        records = [n for n in records if _notice_platform_id(n) == user_id]
    license_id = request.args.get("license_id")
    if license_id is not None:
        records = [n for n in records if n["license_id"] == license_id]
    status = request.args.get("notice_status")
    if status is not None:
        records = [n for n in records if n["notice_status"] == status]
    page, limit, offset, total = list_page(records, request.args)
    return ok_list([ser_notice(n) for n in page], limit, offset, total)


@bp.route("/licensing/takedown-notices/<nid>", methods=["GET"])
def get_notice(nid):
    user_id, role = require_roles(ROLE_RIGHTS_MANAGER, ROLE_PLATFORM_BUYER)
    rec = DB.get("notices", nid)
    if rec is None:
        err(ERR_NOTICE_NOT_FOUND, "referenced takedown notice does not exist")
    check_buyer_owns(user_id, role, _notice_platform_id(rec))
    return ok_object(ser_notice(rec))
