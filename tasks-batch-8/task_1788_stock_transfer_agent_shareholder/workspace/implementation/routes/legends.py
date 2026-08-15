"""Legend removal request endpoints (Rule 144 restricted stock)."""
from datetime import timedelta

from flask import Blueprint, request

from db import STORE
from errors import fail
from helpers import get_body, req_str, req_int, req_dt, pagination_params, parse_dt, fmt_dt
from middleware import auth, require_role, shareholder_owns
from response import success_list, success_object
from services import stamp_new, touch, audit, sorted_recs, legend_view, now_dt

bp = Blueprint("legends", __name__)

LEGEND_READ_ROLES = {"AgentAdmin", "ComplianceOfficer", "Shareholder"}
HOLDING_PERIOD_DAYS = 180


def get_legend_or_404(request_id):
    req = STORE["legend_requests"].get(request_id)
    if req is None:
        fail("ERR_LEGEND_REQUEST_NOT_FOUND",
             "legend-removal request %s does not exist" % request_id)
    return req


@bp.post("/legend-removal-requests")
def create_legend_request():
    user_id, role = auth()
    require_role(role, {"Shareholder"})
    body = get_body()
    if body.get("account_id") is not None:
        shareholder_owns(user_id, body.get("account_id"))
    # existence (stage 3)
    position_id = req_str(body, "position_id")
    position = STORE["positions"].get(position_id)
    if position is None:
        fail("ERR_POSITION_NOT_FOUND", "position %s does not exist" % position_id)
    account_id = req_str(body, "account_id")
    account = STORE["accounts"].get(account_id)
    if account is None:
        fail("ERR_ACCOUNT_NOT_FOUND", "account %s does not exist" % account_id)
    # optimistic concurrency (stage 4)
    expected_version = req_int(body, "expected_position_version")
    if expected_version != position["version"]:
        fail("ERR_STALE_POSITION_VERSION",
             "expected_position_version %d does not match current version %d"
             % (expected_version, position["version"]))
    # state gates (stage 5)
    if account["account_status"] == "ESCHEATED":
        fail("ERR_ACCOUNT_ESCHEATED", "account %s is escheated and terminal" % account_id)
    # shape (stage 8)
    rule_basis = req_str(body, "rule_basis")
    if rule_basis != "RULE_144":
        fail("ERR_INVALID_REQUEST", "rule_basis must be RULE_144")
    share_quantity = req_int(body, "share_quantity")
    if share_quantity < 1:
        fail("ERR_ZERO_SHARE_QUANTITY", "share_quantity must be at least 1")
    acquisition_date = req_dt(body, "acquisition_date")
    # cross-reference consistency (stage 9)
    if position["account_id"] != account["id"]:
        fail("ERR_POSITION_ACCOUNT_MISMATCH",
             "referenced position does not belong to the given account")
    # sufficiency (stage 10)
    if share_quantity > position["restricted_shares"]:
        fail("ERR_INSUFFICIENT_RESTRICTED_SHARES",
             "share_quantity exceeds the position's restricted_shares")
    req = stamp_new({
        "position_id": position["id"],
        "account_id": account["id"],
        "share_quantity": share_quantity,
        "rule_basis": rule_basis,
        "acquisition_date": fmt_dt(acquisition_date),
        "counsel_opinion_reference": None,
        "deficiency_reason": None,
        "status": "SUBMITTED",
    })
    STORE["legend_requests"][req["id"]] = req
    position["pending_legend_removal_count"] += 1
    touch(position)
    audit("LegendRemovalRequest", req["id"], role, user_id, "legend.create",
          "", "SUBMITTED", "legend-removal request filed")
    return success_object(legend_view(req), 201)


@bp.get("/legend-removal-requests")
def list_legend_requests():
    user_id, role = auth()
    require_role(role, LEGEND_READ_ROLES)
    position_filter = request.args.get("position_id")
    account_filter = request.args.get("account_id")
    status_filter = request.args.get("status")
    if role == "Shareholder" and account_filter is not None:
        shareholder_owns(user_id, account_filter)
    items = sorted_recs("legend_requests")
    if position_filter is not None:
        items = [r for r in items if r["position_id"] == position_filter]
    if account_filter is not None:
        items = [r for r in items if r["account_id"] == account_filter]
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([legend_view(r) for r in page], limit, offset, total)


@bp.get("/legend-removal-requests/<request_id>")
def read_legend_request(request_id):
    user_id, role = auth()
    require_role(role, LEGEND_READ_ROLES)
    req = get_legend_or_404(request_id)
    if role == "Shareholder":
        shareholder_owns(user_id, req["account_id"])
    return success_object(legend_view(req))


@bp.post("/legend-removal-requests/<request_id>/submit-opinion")
def submit_opinion(request_id):
    user_id, role = auth()
    require_role(role, {"Shareholder", "ComplianceOfficer"})
    req = get_legend_or_404(request_id)
    if role == "Shareholder":
        shareholder_owns(user_id, req["account_id"])
    if req["status"] not in ("SUBMITTED", "DEFICIENT"):
        fail("ERR_INVALID_STATE",
             "opinion can only be submitted from SUBMITTED or DEFICIENT")
    body = get_body()
    reference = req_str(body, "counsel_opinion_reference")
    frm = req["status"]
    req["counsel_opinion_reference"] = reference
    req["deficiency_reason"] = None
    req["status"] = "OPINION_UNDER_REVIEW"
    touch(req)
    audit("LegendRemovalRequest", req["id"], role, user_id, "legend.submit_opinion",
          frm, "OPINION_UNDER_REVIEW", "counsel opinion submitted")
    return success_object(legend_view(req))


@bp.post("/legend-removal-requests/<request_id>/flag-deficient")
def flag_legend_deficient(request_id):
    user_id, role = auth()
    require_role(role, {"ComplianceOfficer"})
    req = get_legend_or_404(request_id)
    if req["status"] != "OPINION_UNDER_REVIEW":
        fail("ERR_INVALID_STATE",
             "only an OPINION_UNDER_REVIEW request can be flagged deficient")
    body = get_body()
    reason = req_str(body, "deficiency_reason")
    req["deficiency_reason"] = reason
    req["status"] = "DEFICIENT"
    touch(req)
    audit("LegendRemovalRequest", req["id"], role, user_id, "legend.flag_deficient",
          "OPINION_UNDER_REVIEW", "DEFICIENT", "opinion package flagged deficient")
    return success_object(legend_view(req))


@bp.post("/legend-removal-requests/<request_id>/approve")
def approve_legend(request_id):
    user_id, role = auth()
    require_role(role, {"ComplianceOfficer"})
    req = get_legend_or_404(request_id)
    if req["status"] != "OPINION_UNDER_REVIEW":
        fail("ERR_INVALID_STATE",
             "only an OPINION_UNDER_REVIEW request can be approved")
    # temporal gate: Rule 144 holding period, inclusive boundary
    horizon = parse_dt(req["acquisition_date"], "acquisition_date") + timedelta(days=HOLDING_PERIOD_DAYS)
    if now_dt() < horizon:
        fail("ERR_HOLDING_PERIOD_NOT_MET",
             "Rule 144 holding period of 180 days has not elapsed")
    position = STORE["positions"].get(req["position_id"])
    if position is None:
        fail("ERR_POSITION_NOT_FOUND", "position does not exist")
    position["restricted_shares"] -= req["share_quantity"]
    position["pending_legend_removal_count"] -= 1
    touch(position)
    audit("Position", position["id"], role, user_id, "position.legend_update",
          position["status"], position["status"],
          "released %d restricted shares" % req["share_quantity"])
    req["status"] = "LEGEND_REMOVED"
    touch(req)
    audit("LegendRemovalRequest", req["id"], role, user_id, "legend.removed",
          "OPINION_UNDER_REVIEW", "LEGEND_REMOVED", "restrictive legend removed")
    return success_object(legend_view(req))


@bp.post("/legend-removal-requests/<request_id>/reject")
def reject_legend(request_id):
    user_id, role = auth()
    require_role(role, {"ComplianceOfficer"})
    req = get_legend_or_404(request_id)
    if req["status"] not in ("SUBMITTED", "OPINION_UNDER_REVIEW", "DEFICIENT"):
        fail("ERR_INVALID_STATE", "request cannot be rejected from %s" % req["status"])
    frm = req["status"]
    req["status"] = "REJECTED"
    touch(req)
    position = STORE["positions"].get(req["position_id"])
    if position is not None:
        position["pending_legend_removal_count"] -= 1
        touch(position)
    audit("LegendRemovalRequest", req["id"], role, user_id, "legend.rejected",
          frm, "REJECTED", "legend-removal request rejected")
    return success_object(legend_view(req))
