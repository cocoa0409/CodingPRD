"""DisclosureNotice endpoints (PRD 2.9)."""

from datetime import date

from flask import Blueprint

from db import STORE, today
from errors import ApiError, ERR_NOTICE_ALREADY_RESOLVED, bad_request, not_found
from middleware import get_body, paginate, query_enum, require_roles
from response import ok_object
from serialize import serialize, serialize_many
from services.rates import CHANNELS
from utils import bump, now_ts, opt_str, req_enum

bp = Blueprint("notices", __name__)

NOTICE_STATUSES = ("PENDING", "SENT", "WAIVED")
NOTICE_ACTIONS = ("SEND", "WAIVE")


@bp.get("/disclosure-notices")
@require_roles("ComplianceOfficer", "PricingAnalyst")
def list_notices():
    from flask import request
    sheet_id = request.args.get("sheet_id")
    account_id = request.args.get("account_id")
    status = query_enum("status", NOTICE_STATUSES)
    channel = query_enum("channel", CHANNELS)
    rows = list(STORE["notices"].values())
    if sheet_id is not None:
        rows = [r for r in rows if r["sheet_id"] == sheet_id]
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if channel is not None:
        rows = [r for r in rows if r["channel"] == channel]
    return paginate(serialize_many("notices", rows))


@bp.get("/disclosure-notices/<notice_id>")
@require_roles("ComplianceOfficer", "PricingAnalyst")
def get_notice(notice_id):
    row = STORE["notices"].get(notice_id)
    if row is None:
        raise not_found("Disclosure notice not found")
    return ok_object(serialize("notices", row))


@bp.post("/disclosure-notices/<notice_id>/resolution")
@require_roles("ComplianceOfficer")
def resolve_notice(notice_id):
    data = get_body()
    action = req_enum(data, "action", NOTICE_ACTIONS)
    reason = opt_str(data, "reason", None)
    if action == "WAIVE" and not reason:
        raise bad_request("WAIVE requires a reason")
    row = STORE["notices"].get(notice_id)
    if row is None:
        raise not_found("Disclosure notice not found")
    if row["status"] != "PENDING":
        raise ApiError(ERR_NOTICE_ALREADY_RESOLVED, 409,
                       f"Notice already {row['status']}")
    if action == "SEND":
        row["status"] = "SENT"
        row["sent_at"] = now_ts()
        row["is_late"] = today() > date.fromisoformat(row["required_by_date"])
    else:
        row["status"] = "WAIVED"
    bump(row)
    return ok_object(serialize("notices", row))
