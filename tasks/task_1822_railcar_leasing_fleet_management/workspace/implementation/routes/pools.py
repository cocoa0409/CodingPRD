"""Capital pools and purchase commitments (PRD 3.14, 2.11, 2.12)."""
from flask import Blueprint, request

import domain
from envelope import ok, ok_list
from errors import ApiError, invalid_state, not_found
from http_util import CAR_TYPES, get_body, parse_pagination, require_roles, v_enum, v_int, v_str
from store import db, new_entity, touch

bp_pools = Blueprint("pools", __name__)

ROLES = ("SystemAdmin", "FleetPlanner", "ComplianceOfficer", "BillingAnalyst")


def _load_pool(pool_id):
    p = db.pools.get(pool_id)
    if p is None:
        raise not_found("ERR_POOL_NOT_FOUND", f"Capital pool {pool_id} not found")
    domain.recompute_pool(p)
    return p


def _load_commitment(pool, commitment_id):
    c = db.commitments.get(commitment_id)
    if c is None or c["pool_id"] != pool["id"]:
        raise not_found(
            "ERR_COMMITMENT_NOT_FOUND",
            f"Commitment {commitment_id} not found within pool {pool['id']}",
        )
    return c


@bp_pools.route("/capital-pools", methods=["POST"])
@require_roles("SystemAdmin")
def create_pool():
    body = get_body()
    year = v_int(body, "fiscal_year")
    opening = v_int(body, "opening_balance_cents", min=0)
    if any(p["fiscal_year"] == year for p in db.pools.values()):
        raise ApiError(
            "ERR_DUPLICATE_POOL_YEAR", 409,
            f"A capital pool for fiscal year {year} already exists",
        )
    pool = new_entity(
        {
            "fiscal_year": year,
            "opening_balance_cents": opening,
            "replenishment_cents": 0,
            "committed_cents": 0,
            "delivered_spend_cents": 0,
            "available_cents": opening,
        }
    )
    db.pools[pool["id"]] = pool
    return ok(domain.serialize_pool(pool), status=201)


@bp_pools.route("/capital-pools/<pool_id>", methods=["GET"])
@require_roles(*ROLES)
def get_pool(pool_id):
    return ok(domain.serialize_pool(_load_pool(pool_id)))


@bp_pools.route("/capital-pools/<pool_id>/commitments", methods=["POST"])
@require_roles("FleetPlanner")
def create_commitment(pool_id):
    pool = _load_pool(pool_id)
    body = get_body()
    car_type = v_enum(body, "car_type", CAR_TYPES)
    unit_cost = v_int(body, "unit_cost_cents", min=1)
    expected = v_int(body, "expected_pool_version")
    if expected != pool["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412,
            f"expected_pool_version {expected} does not match current version {pool['version']}",
        )
    if unit_cost > pool["available_cents"]:
        raise ApiError(
            "ERR_CAPITAL_POOL_INSUFFICIENT", 422,
            "unit_cost_cents exceeds the pool's available_cents",
        )
    commitment = new_entity(
        {
            "pool_id": pool["id"],
            "car_type": car_type,
            "unit_cost_cents": unit_cost,
            "delivered_car_mark": None,
            "status": "COMMITTED",
        }
    )
    db.commitments[commitment["id"]] = commitment
    pool["committed_cents"] += unit_cost
    domain.recompute_pool(pool)
    touch(pool)
    return ok(domain.serialize_commitment(commitment), status=201)


@bp_pools.route("/capital-pools/<pool_id>/commitments", methods=["GET"])
@require_roles(*ROLES)
def list_commitments(pool_id):
    pool = _load_pool(pool_id)
    limit, offset = parse_pagination()
    items = [
        c for c in db.commitments.values() if c["pool_id"] == pool["id"]
    ]
    items.sort(key=lambda c: (c["created_at"], c["_created_seq"]))
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.serialize_commitment(c) for c in page], limit, offset, total)


@bp_pools.route("/capital-pools/<pool_id>/commitments/<commitment_id>", methods=["GET"])
@require_roles(*ROLES)
def get_commitment(pool_id, commitment_id):
    pool = _load_pool(pool_id)
    c = _load_commitment(pool, commitment_id)
    return ok(domain.serialize_commitment(c))


@bp_pools.route("/capital-pools/<pool_id>/commitments/<commitment_id>/deliver", methods=["POST"])
@require_roles("FleetPlanner")
def deliver_commitment(pool_id, commitment_id):
    pool = _load_pool(pool_id)
    c = _load_commitment(pool, commitment_id)
    body = get_body()
    car_mark = v_str(body, "car_mark")
    built_year = v_int(body, "built_year", min=1900, max=2100)
    if c["status"] != "COMMITTED":
        raise invalid_state(f"Commitment in status {c['status']} cannot be delivered")
    if any(car["car_mark"] == car_mark for car in db.railcars.values()):
        raise ApiError("ERR_DUPLICATE_CAR_MARK", 409, f"car_mark {car_mark} already registered")
    pool["committed_cents"] -= c["unit_cost_cents"]
    pool["delivered_spend_cents"] += c["unit_cost_cents"]
    domain.recompute_pool(pool)
    touch(pool)
    car = new_entity(
        {
            "car_mark": car_mark,
            "car_type": c["car_type"],
            "built_year": built_year,
            "cumulative_miles": 0,
            "last_commodity": "NONE",
            "compliance_posture": "COMPLIANT",
            "status": "AVAILABLE",
            "status_before_shop": None,
            "open_shop_repair_count": 0,
            "retired_at": None,
            "_last_return_seq": 0,
        }
    )
    db.railcars[car["id"]] = car
    domain.recompute_posture(car, bump=False)
    c["status"] = "DELIVERED"
    c["delivered_car_mark"] = car_mark
    touch(c)
    return ok(domain.serialize_commitment(c))


@bp_pools.route("/capital-pools/<pool_id>/commitments/<commitment_id>/cancel", methods=["POST"])
@require_roles("FleetPlanner")
def cancel_commitment(pool_id, commitment_id):
    pool = _load_pool(pool_id)
    c = _load_commitment(pool, commitment_id)
    if c["status"] != "COMMITTED":
        raise invalid_state(f"Commitment in status {c['status']} cannot be cancelled")
    c["status"] = "CANCELLED"
    touch(c)
    pool["committed_cents"] -= c["unit_cost_cents"]
    domain.recompute_pool(pool)
    touch(pool)
    return ok(domain.serialize_commitment(c))
