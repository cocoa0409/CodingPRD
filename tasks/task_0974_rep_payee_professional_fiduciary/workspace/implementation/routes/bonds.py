"""Surety bonds endpoints."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_BOND_NOT_FOUND,
    ERR_BOND_WINDOW_CONFLICT,
    ERR_INVALID_STATE,
    err,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import serialize_bond
from services.cascade import clock_now_iso
from services.derived import recompute_bond_rollups
from util import (
    new_id,
    parse_date,
    parse_pagination,
    require_body,
    get_string,
    get_int,
    reject_unexpected,
)

bp = Blueprint("bonds", __name__)

READ_ROLES = ("FiduciaryAdmin", "CaseManager", "FinancialOfficer", "ConservatorOfficer", "ComplianceAuditor")


@bp.route("/surety-bonds", methods=["POST"])
def create_bond():
    require_roles("FiduciaryAdmin")
    body = require_body()
    reject_unexpected(body, {
        "coverage_amount_cents", "coverage_start_date", "coverage_end_date",
        "premium_paid_through_date",
    })
    coverage = get_int(body, "coverage_amount_cents", min_value=1)
    start = parse_date(get_string(body, "coverage_start_date"), "coverage_start_date")
    end = parse_date(get_string(body, "coverage_end_date"), "coverage_end_date")
    premium = parse_date(get_string(body, "premium_paid_through_date"), "premium_paid_through_date")
    from errors import ERR_INVALID_REQUEST
    if end <= start:
        raise err(ERR_INVALID_REQUEST, 400, "coverage_end_date must be > coverage_start_date")

    now = clock_now_iso()
    bid = new_id()
    b = {
        "id": bid,
        "coverage_amount_cents": coverage,
        "coverage_start_date": start,
        "coverage_end_date": end,
        "premium_paid_through_date": premium,
        "status": "PENDING",
        "funds_under_management_cents": 0,
        "utilization_bps": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.bonds[bid] = b
    recompute_bond_rollups()
    return success_object(serialize_bond(b), status=201)


@bp.route("/surety-bonds", methods=["GET"])
def list_bonds():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = list(store.bonds.values())
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: b["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_bond(b) for b in page], limit, offset, total)


@bp.route("/surety-bonds/<bid>", methods=["GET"])
def get_bond(bid):
    require_roles(*READ_ROLES)
    b = store.bonds.get(bid)
    if not b:
        raise err(ERR_BOND_NOT_FOUND, 404, "bond not found")
    return success_object(serialize_bond(b))


@bp.route("/surety-bonds/<bid>/activate", methods=["POST"])
def activate_bond(bid):
    require_roles("FiduciaryAdmin")
    b = store.bonds.get(bid)
    if not b:
        raise err(ERR_BOND_NOT_FOUND, 404, "bond not found")
    if b["status"] == "LAPSED":
        raise err(ERR_ALREADY_TERMINAL, 409, "Bond is LAPSED")
    if b["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, 409, "Only PENDING -> ACTIVE")
    # overlap with other ACTIVE bonds (half-open windows, adjacency allowed)
    s1, e1 = b["coverage_start_date"], b["coverage_end_date"]
    for other in store.bonds.values():
        if other["id"] == bid:
            continue
        if other["status"] != "ACTIVE":
            continue
        s2, e2 = other["coverage_start_date"], other["coverage_end_date"]
        # half-open overlap: s1 < e2 AND s2 < e1
        if s1 < e2 and s2 < e1:
            raise err(ERR_BOND_WINDOW_CONFLICT, 409, "window overlaps another ACTIVE bond")
    now = clock_now_iso()
    b["status"] = "ACTIVE"
    b["updated_at"] = now
    b["version"] += 1
    recompute_bond_rollups()
    return success_object(serialize_bond(b))
