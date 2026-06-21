"""Package endpoints + renewal (PRD §3.7)."""
from flask import Blueprint, request, g

import errors
import response
from db import db
from middleware import require_roles
from services import serialize
from services.common import (stamp_create, touch, get_body, require_fields,
                             require_enum, parse_date)
from services.query import paginate_params, sort_by_created, apply_page, owner_guard
from routes.owners import get_owner_or_404

bp = Blueprint("packages", __name__)

TIERS = {"DAYCARE_10": 10, "DAYCARE_20": 20}


def get_package_or_404(pid):
    p = db.packages.get(pid)
    if p is None:
        raise errors.err_not_found()
    return p


def _package_owner_guard(pkg):
    if g.role == "Owner" and g.user_id != pkg["owner_id"]:
        raise errors.err_not_resource_owner()


@bp.route("/owners/<oid>/packages", methods=["POST"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def buy_package(oid):
    owner = get_owner_or_404(oid)
    owner_guard(oid)
    body = get_body()
    require_fields(body, ["tier", "cycle_start_date"])
    tier = body["tier"]
    require_enum(tier, set(TIERS.keys()), "tier")
    cycle_start_date = body["cycle_start_date"]
    parse_date(cycle_start_date)
    auto_renew = body.get("auto_renew", False)
    if not isinstance(auto_renew, bool):
        raise errors.err_invalid_request("auto_renew must be a boolean.")

    credits_total = TIERS[tier]
    pkg = {
        "owner_id": oid,
        "facility_id": owner["facility_id"],
        "tier": tier,
        "credits_total": credits_total,
        "credits_remaining": credits_total,
        "cycle_start_date": cycle_start_date,
        "auto_renew": auto_renew,
        "status": "ACTIVE",
    }
    stamp_create(pkg)
    db.packages[pkg["id"]] = pkg
    return response.success(serialize.package(pkg), status=201)


@bp.route("/packages/<pid>", methods=["GET"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def get_package(pid):
    pkg = get_package_or_404(pid)
    _package_owner_guard(pkg)
    return response.success(serialize.package(pkg), status=200)


@bp.route("/owners/<oid>/packages", methods=["GET"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def list_packages(oid):
    get_owner_or_404(oid)
    owner_guard(oid)
    limit, offset = paginate_params()
    status_filter = request.args.get("status")
    items = [p for p in db.packages.values() if p["owner_id"] == oid]
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    items = sort_by_created(items)
    page, total = apply_page(items, limit, offset)
    return response.list_success([serialize.package(p) for p in page],
                                 limit, offset, total)


@bp.route("/packages/<pid>/renew", methods=["POST"])
@require_roles("FacilityManager", "Owner")
def renew_package(pid):
    pkg = get_package_or_404(pid)
    _package_owner_guard(pkg)

    # state check first (ERR_INVALID_STATE), then auto_renew (ERR_RENEWAL_NOT_ALLOWED).
    if pkg["status"] != "EXPIRED":
        raise errors.err_invalid_state()
    if not pkg["auto_renew"]:
        raise errors.err_renewal_not_allowed()

    facility = db.facilities.get(pkg["facility_id"])
    pkg["cycle_start_date"] = facility["current_date"]
    pkg["status"] = "ACTIVE"
    # Renewal resets credits_remaining to credits_total (PRD §3.7).
    pkg["credits_remaining"] = pkg["credits_total"]
    touch(pkg)
    return response.success(serialize.package(pkg), status=200)


@bp.route("/packages/<pid>/redemptions", methods=["GET"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def list_redemptions(pid):
    pkg = get_package_or_404(pid)
    _package_owner_guard(pkg)
    limit, offset = paginate_params()
    reversed_filter = request.args.get("reversed")
    items = [r for r in db.package_redemptions.values() if r["package_id"] == pid]
    if reversed_filter is not None:
        want = reversed_filter.lower() == "true"
        items = [r for r in items if r["reversed"] == want]
    items = sort_by_created(items)
    page, total = apply_page(items, limit, offset)
    return response.list_success([serialize.redemption(r) for r in page],
                                 limit, offset, total)
