"""Revenue reports: list/get/reverse (PRD §3.8)."""
from flask import Blueprint, request

from auth import (
    check_buyer_owns,
    require_roles,
    ROLE_RIGHTS_MANAGER,
    ROLE_PLATFORM_BUYER,
    ROLE_FINANCE_ANALYST,
    ROLE_FINANCE_CONTROLLER,
)
from domain import list_page, replay_recoupment, ser_report
from errors import err, ERR_REPORT_NOT_FOUND, ERR_INVALID_REQUEST
from response import ok_list, ok_object
from store import DB, mutate

bp = Blueprint("reports", __name__)

_READERS = (
    ROLE_RIGHTS_MANAGER,
    ROLE_PLATFORM_BUYER,
    ROLE_FINANCE_ANALYST,
    ROLE_FINANCE_CONTROLLER,
)


def _get_report_or_404(rid):
    rec = DB.get("reports", rid)
    if rec is None:
        err(ERR_REPORT_NOT_FOUND, "referenced revenue report does not exist")
    return rec


def _report_platform_id(report):
    lic = DB.get("licenses", report["license_id"])
    return lic["platform_id"] if lic else None


@bp.route("/licensing/revenue-reports", methods=["GET"])
def list_reports():
    user_id, role = require_roles(*_READERS)
    records = DB.all("reports")
    if role == ROLE_PLATFORM_BUYER:
        records = [r for r in records if _report_platform_id(r) == user_id]
    license_id = request.args.get("license_id")
    if license_id is not None:
        records = [r for r in records if r["license_id"] == license_id]
    status = request.args.get("report_status")
    if status is not None:
        records = [r for r in records if r["report_status"] == status]
    page, limit, offset, total = list_page(records, request.args)
    return ok_list([ser_report(r) for r in page], limit, offset, total)


@bp.route("/licensing/revenue-reports/<rid>", methods=["GET"])
def get_report(rid):
    user_id, role = require_roles(*_READERS)
    rec = _get_report_or_404(rid)
    check_buyer_owns(user_id, role, _report_platform_id(rec))
    return ok_object(ser_report(rec))


@bp.route("/licensing/revenue-reports/<rid>/reverse", methods=["POST"])
def reverse_report(rid):
    require_roles(ROLE_FINANCE_ANALYST)
    rec = _get_report_or_404(rid)
    if rec["report_status"] != "SUBMITTED":
        err(ERR_INVALID_REQUEST, "only a SUBMITTED report can be reversed")
    rec["report_status"] = "REVERSED"
    mutate(rec)
    lic = DB.get("licenses", rec["license_id"])
    if lic is not None:
        replay_recoupment(lic)
    return ok_object(ser_report(rec))
