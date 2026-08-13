from flask import Blueprint

import errors
from db import DB, CLOCK, new_id, stamp_new, touch, parse_iso, format_ts
from middleware import (
    get_context, require_role, get_json_body, require_fields, reject_unexpected,
    require_string, require_number, parse_limit_offset,
)
from response import success_object, success_list
from services import bids as bid_svc

bp = Blueprint("bid_packages", __name__)

ESTIMATORS = {"LeadEstimator", "ChiefEstimator", "PrequalReviewer"}


def serialize_package(pkg):
    return {
        "id": pkg["id"],
        "name": pkg["name"],
        "trade_code": pkg["trade_code"],
        "bid_due_at": pkg["bid_due_at"],
        "bid_bond_required_pct": pkg["bid_bond_required_pct"],
        "status": pkg["status"],
        "issued_addendum_count": pkg["issued_addendum_count"],
        "submitted_bid_count": pkg["submitted_bid_count"],
        "compliant_bid_count": pkg["compliant_bid_count"],
        "apparent_low_bid_id": pkg["apparent_low_bid_id"],
        "leveled_low_bid_id": pkg["leveled_low_bid_id"],
        "created_at": pkg["created_at"],
        "updated_at": pkg["updated_at"],
        "version": pkg["version"],
    }


def get_package_or_404(package_id):
    pkg = DB.bid_packages.get(package_id)
    if pkg is None:
        raise errors.err_package_not_found()
    return pkg


@bp.post("/bid-packages")
def create_package():
    _, role = get_context()
    require_role(role, {"LeadEstimator"})
    body = get_json_body()
    reject_unexpected(body, {"name", "trade_code", "bid_due_at", "bid_bond_required_pct"})
    require_fields(body, ["name", "trade_code", "bid_due_at"])
    name = require_string(body, "name")
    trade_code = require_string(body, "trade_code")
    due_raw = body.get("bid_due_at")
    due_dt = parse_iso(due_raw)
    if not isinstance(due_raw, str) or due_dt is None:
        raise errors.err_invalid_request("bid_due_at must be a valid ISO 8601 timestamp")
    pct = body.get("bid_bond_required_pct", 0.05)
    if not isinstance(pct, (int, float)) or isinstance(pct, bool):
        raise errors.err_invalid_request("bid_bond_required_pct must be a number")
    if pct <= 0 or pct > 0.20:
        raise errors.err_invalid_request("bid_bond_required_pct must be > 0 and <= 0.20")

    pkg = {
        "id": new_id(),
        "name": name,
        "trade_code": trade_code,
        "bid_due_at": format_ts(due_dt),
        "_bid_due_at_dt": due_dt,
        "bid_bond_required_pct": pct,
        "status": "DRAFT",
        "issued_addendum_count": 0,
        "submitted_bid_count": 0,
        "compliant_bid_count": None,
        "apparent_low_bid_id": None,
        "leveled_low_bid_id": None,
    }
    stamp_new(pkg)
    pkg["_created_at_dt"] = CLOCK.now()
    DB.bid_packages[pkg["id"]] = pkg
    return success_object(serialize_package(pkg), 201)


@bp.get("/bid-packages")
def list_packages():
    _, role = get_context()
    require_role(role, ESTIMATORS)
    limit, offset = parse_limit_offset(__import__("flask").request.args)
    from flask import request
    status_f = request.args.get("status")
    apparent_f = request.args.get("apparent_low_bid_id")
    leveled_f = request.args.get("leveled_low_bid_id")
    items = sorted(DB.bid_packages.values(), key=lambda p: (p["_created_at_dt"], p["id"]))
    if status_f is not None:
        items = [p for p in items if p["status"] == status_f]
    if apparent_f is not None:
        items = [p for p in items if p["apparent_low_bid_id"] == apparent_f]
    if leveled_f is not None:
        items = [p for p in items if p["leveled_low_bid_id"] == leveled_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_package(p) for p in page], limit, offset, total)


@bp.get("/bid-packages/<package_id>")
def read_package(package_id):
    _, role = get_context()
    require_role(role, ESTIMATORS)
    pkg = get_package_or_404(package_id)
    return success_object(serialize_package(pkg))


@bp.post("/bid-packages/<package_id>/publish")
def publish_package(package_id):
    _, role = get_context()
    require_role(role, {"LeadEstimator"})
    pkg = get_package_or_404(package_id)
    if pkg["status"] != "DRAFT":
        raise errors.err_package_invalid_state("Publish requires DRAFT")
    invited = any(i["bid_package_id"] == pkg["id"] for i in DB.invitations.values())
    if not invited:
        raise errors.err_no_invited_bidders()
    if CLOCK.now() >= pkg["_bid_due_at_dt"]:
        raise errors.err_deadline_passed()
    pkg["status"] = "PUBLISHED"
    touch(pkg)
    return success_object(serialize_package(pkg))


@bp.post("/bid-packages/<package_id>/close-bidding")
def close_bidding(package_id):
    _, role = get_context()
    require_role(role, {"LeadEstimator"})
    pkg = get_package_or_404(package_id)
    if pkg["status"] != "PUBLISHED":
        raise errors.err_package_invalid_state("close-bidding requires PUBLISHED")
    if CLOCK.now() < pkg["_bid_due_at_dt"]:
        raise errors.err_deadline_not_reached()
    pkg["status"] = "BIDDING_CLOSED"
    touch(pkg)
    return success_object(serialize_package(pkg))


@bp.post("/bid-packages/<package_id>/tabulate")
def tabulate(package_id):
    _, role = get_context()
    require_role(role, {"LeadEstimator"})
    pkg = get_package_or_404(package_id)
    if pkg["status"] not in ("BIDDING_CLOSED", "TABULATED"):
        raise errors.err_package_invalid_state("tabulate requires BIDDING_CLOSED or TABULATED")
    # Re-tabulation from TABULATED requires at least one bid still SUBMITTED;
    # the compliant-set check inside run_tabulation covers the BIDDING_CLOSED
    # path and raises ERR_NO_COMPLIANT_BIDS before any state change.
    bid_svc.run_tabulation(pkg)
    pkg["status"] = "TABULATED"
    touch(pkg)
    return success_object(serialize_package(pkg))


@bp.get("/bid-packages/<package_id>/award-recommendations")
def list_package_recommendations(package_id):
    _, role = get_context()
    require_role(role, ESTIMATORS)
    get_package_or_404(package_id)
    limit, offset = parse_limit_offset(__import__("flask").request.args)
    items = sorted(
        (r for r in DB.recommendations.values() if r["bid_package_id"] == package_id),
        key=lambda r: (r["_created_at_dt"], r["id"]),
    )
    total = len(items)
    page = items[offset:offset + limit]
    from routes.recommendations import serialize_recommendation
    return success_list([serialize_recommendation(r) for r in page], limit, offset, total)
