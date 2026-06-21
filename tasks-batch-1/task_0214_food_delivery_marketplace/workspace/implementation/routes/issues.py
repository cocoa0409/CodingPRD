"""OrderIssue and EarningsRecord endpoints, plus the test clock (PRD §3.12, §3.13)."""
from flask import Blueprint, request

import common
import errors
import lookups
from db import store
from middleware import get_user_context, require_roles
from response import success, list_success
from serializers import serialize_order_issue, serialize_earnings_record
from services import issue_service

bp = Blueprint("issues", __name__)


@bp.route("/order-issues", methods=["GET"])
def list_order_issues():
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Customer", "Support"])
    limit, offset = common.parse_pagination()
    items = list(store.order_issues.values())
    for key in ("order_id", "line_item_id"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i[key] == val]
    items = common.sorted_by_creation(items)
    page, total = common.paginate(items, limit, offset)
    return list_success([serialize_order_issue(i) for i in page], limit, offset, total)


@bp.route("/order-issues/<iid>", methods=["GET"])
def get_order_issue(iid):
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Customer", "Support"])
    i = lookups.get_order_issue(iid)
    return success(serialize_order_issue(i))


@bp.route("/order-issues/<iid>/approve", methods=["POST"])
def approve_issue(iid):
    _, role = get_user_context()
    require_roles(role, ["Support"])
    issue = lookups.get_order_issue(iid)
    order = store.orders[issue["order_id"]]
    issue_service.approve_issue(issue, order)
    return success(serialize_order_issue(issue))


@bp.route("/order-issues/<iid>/reject", methods=["POST"])
def reject_issue(iid):
    _, role = get_user_context()
    require_roles(role, ["Support"])
    issue = lookups.get_order_issue(iid)
    issue_service.reject_issue(issue)
    return success(serialize_order_issue(issue))


@bp.route("/earnings-records/<eid>", methods=["GET"])
def get_earnings_record(eid):
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Dasher"])
    e = lookups.get_earnings_record(eid)
    return success(serialize_earnings_record(e))


# ---------------------------------------------------------------------------
# Test clock (PRD §3.13). Exempt from header authentication per PRD §2.1,
# but role-restricted to PlatformAdmin per the endpoint table.
# ---------------------------------------------------------------------------
@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    body = common.get_json_body()
    to_iso8601 = common.require_str(body, "to_iso8601")
    dt = common.parse_iso8601(to_iso8601)
    if dt is None:
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "to_iso8601 must be ISO 8601")
    store.set_clock(dt)
    # 2xx response with no data -> empty object.
    return success({}, status=200)
