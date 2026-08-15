"""Plan endpoints."""
from decimal import Decimal

from flask import Blueprint

from db import DB, new_id
from errors import ApiError
from middleware import ADMIN, ANY_ROLE, auth
from response import ok
from services import (
    BASIS_METHODS,
    PLAN_STATUSES,
    PRICING_BASES,
    auto_create_modification_notice,
    filter_enum,
    get_plan,
    list_response,
    resume_plan,
    ser_plan,
    stamp,
    suspend_plan,
    terminate_plan,
    touch,
)
from util import (
    as_bool,  # noqa: F401  (kept for parity with other route modules)
    as_decimal,
    as_enum,
    as_int,
    as_nonneg_int,
    as_str,
    body,
    required,
)

bp = Blueprint("plans", __name__)

_PATCHABLE = (
    "name",
    "discount_pct",
    "pricing_basis",
    "basis_method",
    "ocp_min_cents",
    "ocp_max_cents",
    "ocp_fee_pct",
    "ocp_fee_min_cents",
    "sale_fee_cents",
    "transfer_fee_cents",
    "enrollment_fee_cents",
)


def _discount(v):
    d = as_decimal(v, "discount_pct")
    if d < 0 or d >= 1:
        raise ApiError(
            "ERR_VALIDATION", 400, "discount_pct must be in [0, 1)"
        )
    return v


def _fee_pct(v):
    d = as_decimal(v, "ocp_fee_pct")
    if d < 0:
        raise ApiError("ERR_VALIDATION", 400, "ocp_fee_pct must be >= 0")
    return v


def _validate_plan_field(field, value):
    if field == "name":
        return as_str(value, "name")
    if field == "discount_pct":
        return _discount(value)
    if field == "pricing_basis":
        return as_enum(value, "pricing_basis", PRICING_BASES)
    if field == "basis_method":
        return as_enum(value, "basis_method", BASIS_METHODS)
    if field == "ocp_fee_pct":
        return _fee_pct(value)
    return as_nonneg_int(value, field)


@bp.post("/plans")
def create_plan():
    auth(ADMIN)
    data = body()
    rec = {
        "id": new_id(),
        "issuer_name": as_str(required(data, "issuer_name"), "issuer_name"),
        "ticker": as_str(required(data, "ticker"), "ticker"),
        "name": as_str(required(data, "name"), "name"),
        "status": "DRAFT",
        "discount_pct": _discount(required(data, "discount_pct")),
        "pricing_basis": as_enum(
            data.get("pricing_basis", "MARKET_CLOSE"), "pricing_basis", PRICING_BASES
        ),
        "basis_method": as_enum(
            data.get("basis_method", "FIFO"), "basis_method", BASIS_METHODS
        ),
        "ocp_min_cents": as_nonneg_int(
            required(data, "ocp_min_cents"), "ocp_min_cents"
        ),
        "ocp_max_cents": as_nonneg_int(
            required(data, "ocp_max_cents"), "ocp_max_cents"
        ),
        "ocp_fee_pct": _fee_pct(required(data, "ocp_fee_pct")),
        "ocp_fee_min_cents": as_nonneg_int(
            required(data, "ocp_fee_min_cents"), "ocp_fee_min_cents"
        ),
        "sale_fee_cents": as_nonneg_int(
            required(data, "sale_fee_cents"), "sale_fee_cents"
        ),
        "transfer_fee_cents": as_nonneg_int(
            required(data, "transfer_fee_cents"), "transfer_fee_cents"
        ),
        "enrollment_fee_cents": as_nonneg_int(
            required(data, "enrollment_fee_cents"), "enrollment_fee_cents"
        ),
    }
    stamp(rec)
    DB["plans"][rec["id"]] = rec
    return ok(ser_plan(rec), status=201)


@bp.get("/plans")
def list_plans():
    auth(ANY_ROLE)
    from flask import request

    items = filter_enum(
        list(DB["plans"].values()), request.args.get("status"), "status",
        PLAN_STATUSES, "status",
    )
    return list_response(items, ser_plan)


@bp.get("/plans/<pid>")
def get_one_plan(pid):
    auth(ANY_ROLE)
    return ok(ser_plan(get_plan(pid)))


@bp.patch("/plans/<pid>")
def patch_plan(pid):
    auth(ADMIN)
    plan = get_plan(pid)
    data = body()
    expected = as_int(
        required(data, "expected_plan_version"), "expected_plan_version"
    )
    updates = {}
    for field in _PATCHABLE:
        if field in data and data[field] is not None:
            updates[field] = _validate_plan_field(field, data[field])
    # OCC guard (PRD section 2.7).
    if expected != plan["version"]:
        raise ApiError(
            "ERR_STALE_PLAN_VERSION",
            412,
            "expected_plan_version does not match the plan's current version",
        )
    for k, v in updates.items():
        plan[k] = v
    touch(plan)
    if plan["status"] == "ACTIVE":
        auto_create_modification_notice(plan)
    return ok(ser_plan(plan))


@bp.post("/plans/<pid>/publish")
def publish_plan(pid):
    auth(ADMIN)
    plan = get_plan(pid)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Plan is not in DRAFT")
    plan["status"] = "ACTIVE"
    touch(plan)
    return ok(ser_plan(plan))


@bp.post("/plans/<pid>/suspend")
def suspend_plan_route(pid):
    auth(ADMIN)
    plan = get_plan(pid)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Plan is not ACTIVE")
    suspend_plan(plan)
    return ok(ser_plan(plan))


@bp.post("/plans/<pid>/resume")
def resume_plan_route(pid):
    auth(ADMIN)
    plan = get_plan(pid)
    if plan["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Plan is not SUSPENDED")
    resume_plan(plan)
    return ok(ser_plan(plan))


@bp.post("/plans/<pid>/terminate")
def terminate_plan_route(pid):
    auth(ADMIN)
    plan = get_plan(pid)
    if plan["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Plan is not ACTIVE or SUSPENDED"
        )
    data = body()
    sale_price = 0
    if data.get("sale_price_cents") is not None:
        sale_price = as_nonneg_int(data["sale_price_cents"], "sale_price_cents")
    terminate_plan(plan, sale_price)
    return ok(ser_plan(plan))
