"""Railcar registry, compliance view, fleet utilization (PRD 3.2, 3.11, 3.12)."""
from datetime import date, timedelta

from flask import Blueprint, request

import domain
from calc import month_bounds, retrofit_penalty, utilization_pct
from envelope import ok, ok_list
from errors import ApiError, not_found, validation
from http_util import CAR_TYPES, get_body, parse_pagination, require_roles, v_enum, v_int, v_str
from store import db, new_entity, today

bp_railcars = Blueprint("railcars", __name__)

CAR_STATUSES = {"AVAILABLE", "ON_LEASE", "IN_SHOP", "RETIREMENT_PENDING", "RETIRED"}
POSTURES = {"COMPLIANT", "RETROFIT_DUE", "NON_COMPLIANT"}


def _load_car(railcar_id):
    car = db.railcars.get(railcar_id)
    if car is None:
        raise not_found("ERR_RAILCAR_NOT_FOUND", f"Railcar {railcar_id} not found")
    return car


def _date_of(ts):
    return date.fromisoformat(ts[:10])


@bp_railcars.route("/railcars", methods=["POST"])
@require_roles("FleetPlanner")
def create_railcar():
    body = get_body()
    car_mark = v_str(body, "car_mark")
    car_type = v_enum(body, "car_type", CAR_TYPES)
    built_year = v_int(body, "built_year", min=1900, max=2100)
    if any(c["car_mark"] == car_mark for c in db.railcars.values()):
        raise ApiError("ERR_DUPLICATE_CAR_MARK", 409, f"car_mark {car_mark} already registered")
    car = new_entity(
        {
            "car_mark": car_mark,
            "car_type": car_type,
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
    # A newly registered car may already be covered by announced directives;
    # the initial posture is part of creation (no extra version bump).
    db.railcars[car["id"]] = car
    domain.recompute_posture(car, bump=False)
    return ok(domain.serialize_railcar(car), status=201)


@bp_railcars.route("/railcars", methods=["GET"])
@require_roles(
    "SystemAdmin", "LeaseAdmin", "FleetPlanner", "MaintenanceController",
    "BillingAnalyst", "ComplianceOfficer",
)
def list_railcars():
    limit, offset = parse_pagination()
    items = sorted(db.railcars.values(), key=lambda c: (c["created_at"], c["_created_seq"]))
    status = request.args.get("status")
    car_type = request.args.get("car_type")
    posture = request.args.get("compliance_posture")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if car_type is not None:
        items = [c for c in items if c["car_type"] == car_type]
    if posture is not None:
        items = [c for c in items if c["compliance_posture"] == posture]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.serialize_railcar(c) for c in page], limit, offset, total)


@bp_railcars.route("/railcars/<railcar_id>", methods=["GET"])
@require_roles(
    "SystemAdmin", "LeaseAdmin", "FleetPlanner", "MaintenanceController",
    "BillingAnalyst", "ComplianceOfficer", "LesseeRep",
)
def get_railcar(railcar_id):
    car = _load_car(railcar_id)
    return ok(domain.serialize_railcar(car))


@bp_railcars.route("/railcars/<railcar_id>/compliance", methods=["GET"])
@require_roles(
    "SystemAdmin", "FleetPlanner", "MaintenanceController",
    "ComplianceOfficer", "BillingAnalyst",
)
def car_compliance(railcar_id):
    car = _load_car(railcar_id)
    domain.recompute_posture(car)
    now = today()
    open_dirs = sorted(
        domain.open_directives_for_car(car),
        key=lambda d: (d["created_at"], d["_created_seq"]),
    )
    accrued = 0
    assessed = 0
    oldest_days = 0
    for d in open_dirs:
        a, s, days = retrofit_penalty(d, now)
        accrued += a
        assessed += s
        oldest_days = max(oldest_days, days)
    return ok(
        {
            "car_id": car["id"],
            "posture": car["compliance_posture"],
            "open_directive_ids": [d["id"] for d in open_dirs],
            "days_since_oldest_effective": oldest_days,
            "accrued_penalty_cents": accrued,
            "assessed_penalty_cents": assessed,
        }
    )


@bp_railcars.route("/fleet/utilization", methods=["GET"])
@require_roles("SystemAdmin", "LeaseAdmin", "FleetPlanner", "BillingAnalyst")
def fleet_utilization():
    month = request.args.get("month")
    if month is None:
        raise validation("Query parameter month is required (YYYY-MM)")
    if not isinstance(month, str) or len(month) != 7:
        raise validation("Query parameter month must be YYYY-MM")
    try:
        first, last = month_bounds(month)
    except (ValueError, IndexError):
        raise validation("Query parameter month must be YYYY-MM")

    eligible = 0
    for car in db.railcars.values():
        created = _date_of(car["created_at"])
        frm = max(first, created)
        if car["status"] == "RETIRED" and car["retired_at"]:
            to = min(last, _date_of(car["retired_at"]) - timedelta(days=1))
        else:
            to = last
        if to >= frm:
            eligible += (to - frm).days + 1

    on_lease = 0
    month_end_excl = last + timedelta(days=1)
    for a in db.assignments.values():
        if a["status"] not in ("ON_LEASE", "RETURNED", "SETTLED"):
            continue
        on = a["actual_on_lease_date"]
        if on is None:
            continue
        start = max(on, first)
        off = a["actual_off_lease_date"] or month_end_excl
        end_excl = min(off, month_end_excl)
        if end_excl > start:
            on_lease += (end_excl - start).days

    return ok(
        {
            "month": month,
            "on_lease_car_days": on_lease,
            "eligible_car_days": eligible,
            "utilization_pct": utilization_pct(on_lease, eligible),
        }
    )
