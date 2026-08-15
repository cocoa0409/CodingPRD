"""QuarterlyDistribution lifecycle: create, calculate (OCC), approve,
disburse (pool-guarded), reconcile (PRD §3.6)."""

from flask import Blueprint, request

import db
from db import store, new_entity, touch, public
from errors import (err_not_found, err_state, err_invalid_request, ApiError,
                    ERR_INSUFFICIENT_POOL, ERR_STALE_DISTRIBUTION_VERSION)
from middleware import require_roles, body_json, req_int
from response import success_object, success_list, parse_pagination, paginate
from services import lifecycle

bp = Blueprint("distributions", __name__)

READ_ROLES = ("CoopAdmin", "FinanceOfficer", "ProgramAuditor", "MemberRep")
LIST_ROLES = ("CoopAdmin", "FinanceOfficer", "ProgramAuditor")


def get_distribution_or_404(dist_id):
    dist = store.distributions.get(dist_id)
    if dist is None:
        raise err_not_found("QuarterlyDistribution not found")
    return dist


def _arg(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


def _arg_int(name):
    v = request.args.get(name)
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise err_invalid_request("%s must be an integer" % name)


@bp.route("/coop/distributions", methods=["POST"])
@require_roles("FinanceOfficer")
def create_distribution(uid, role):
    coop = db.get_coop()
    dist = new_entity()
    dist.update({
        "coop_id": coop["id"],
        "quarter_index": coop["current_quarter_index"],
        "gross_rebate_cents": 0,
        "total_pass_through_cents": 0,
        "total_retained_cents": 0,
        "holdback_cents": 0,
        "clawback_offset_cents": 0,
        "net_disbursed_cents": 0,
        "status": "DRAFT",
        "_included": [],
        "_per_member": {},
    })
    store.distributions[dist["id"]] = dist
    return success_object(public(dist), code=201)


@bp.route("/coop/distributions/<dist_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_distribution(uid, role, dist_id):
    return success_object(public(get_distribution_or_404(dist_id)), code=200)


@bp.route("/coop/distributions", methods=["GET"])
@require_roles(*LIST_ROLES)
def list_distributions(uid, role):
    limit, offset = parse_pagination()
    items = list(store.distributions.values())
    coop_id = _arg("coop_id")
    if coop_id is not None:
        items = [d for d in items if d["coop_id"] == coop_id]
    quarter = _arg_int("quarter_index")
    if quarter is not None:
        items = [d for d in items if d["quarter_index"] == quarter]
    status = _arg("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public(d) for d in page], limit, offset, total)


@bp.route("/coop/distributions/<dist_id>/calculate", methods=["POST"])
@require_roles("FinanceOfficer")
def calculate(uid, role, dist_id):
    dist = get_distribution_or_404(dist_id)
    body = body_json(required=True)
    expected = req_int(body, "expected_distribution_version")
    if dist["status"] != "DRAFT":
        raise err_state("Only a DRAFT distribution can be calculated")
    if expected != dist["version"]:
        raise ApiError(ERR_STALE_DISTRIBUTION_VERSION, 412,
                       "expected_distribution_version does not match current version")
    lifecycle.calculate_distribution(dist)
    return success_object(public(dist), code=200)


@bp.route("/coop/distributions/<dist_id>/approve", methods=["POST"])
@require_roles("FinanceOfficer")
def approve(uid, role, dist_id):
    dist = get_distribution_or_404(dist_id)
    if dist["status"] != "CALCULATED":
        raise err_state("Only a CALCULATED distribution can be approved")
    dist["status"] = "APPROVED"
    touch(dist)
    return success_object(public(dist), code=200)


@bp.route("/coop/distributions/<dist_id>/disburse", methods=["POST"])
@require_roles("FinanceOfficer")
def disburse(uid, role, dist_id):
    dist = get_distribution_or_404(dist_id)
    if dist["status"] != "APPROVED":
        raise err_state("Only an APPROVED distribution can be disbursed")
    coop = db.get_coop()
    if coop["pool_reserve_cents"] < dist["net_disbursed_cents"]:
        raise ApiError(ERR_INSUFFICIENT_POOL, 409,
                       "pool_reserve_cents is less than net_disbursed_cents")
    lifecycle.disburse_distribution(dist)
    return success_object(public(dist), code=200)


@bp.route("/coop/distributions/<dist_id>/reconcile", methods=["POST"])
@require_roles("FinanceOfficer")
def reconcile(uid, role, dist_id):
    dist = get_distribution_or_404(dist_id)
    if dist["status"] != "DISBURSED":
        raise err_state("Only a DISBURSED distribution can be reconciled")
    dist["status"] = "RECONCILED"
    touch(dist)
    return success_object(public(dist), code=200)
