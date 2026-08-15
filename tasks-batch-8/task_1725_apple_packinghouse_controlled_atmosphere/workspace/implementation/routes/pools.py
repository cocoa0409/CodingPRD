"""Marketing pool endpoints: open, sales, close (OCC), reopen (PRD 3.5, 3.6)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_POOL_EMPTY,
    ERR_POOL_HAS_OPEN_RUNS,
    ERR_POOL_INVALID_STATE,
    ERR_SALE_AMOUNT_INVALID,
    ERR_STALE_VERSION,
    ERR_UNIQUE_CONSTRAINT_VIOLATION,
    ERR_VERSION_REQUIRED,
)
from middleware import authorized, ALL_ROLES
from response import success_object
from routes.helpers import public
from services.core import new_record, touch
from services.domain import (
    pool_close_cascade,
    pool_reopen_cascade,
    recompute_pool_totals,
)
from validate import get_body, req_enum, req_int, req_str, require_path_resource

bp = Blueprint("pools", __name__)

VARIETIES = {"HONEYCRISP", "GALA", "FUJI", "GRANNY_SMITH", "COSMIC_CRISP"}
GRADE_CLASSES = {"EXTRA_FANCY", "FANCY", "UTILITY"}


@bp.post("/pools")
def create_pool():
    authorized(["Admin", "PoolManager"])
    body = get_body()
    variety = req_enum(body, "variety", VARIETIES)
    grade_class = req_enum(body, "grade_class", GRADE_CLASSES)
    season = req_str(body, "season")
    # Uniqueness: (variety, grade_class, season).
    for p in db["pools"].values():
        if (p["variety"] == variety and p["grade_class"] == grade_class
                and p["season"] == season):
            raise_error(ERR_UNIQUE_CONSTRAINT_VIOLATION,
                        "a pool already exists for this variety/grade_class/season")
    rec = new_record("pools", {
        "variety": variety,
        "grade_class": grade_class,
        "season": season,
        "total_packed_cartons": 0,
        "total_sales_cents": 0,
        "total_sale_deductions_cents": 0,
        "total_deductions_cents": 0,
        "estimated_price_cents": 1000,  # ESTIMATED_PRICE_FLOOR_CENTS at zero cartons
        "pool_price_per_carton_cents": None,
        "rounding_drift_cents": 0,
        "status": "OPEN",
    })
    return success_object(public(rec), status=201)


@bp.get("/pools/<poolId>")
def get_pool(poolId):
    authorized(list(ALL_ROLES))
    pool = require_path_resource("pools", poolId)
    return success_object(public(pool))


@bp.post("/pools/<poolId>/sales")
def record_sale(poolId):
    authorized(["Admin", "PoolManager"])
    pool = require_path_resource("pools", poolId)
    body = get_body()
    # Tier 5: presence and JSON types only; sign rules are fiscal (tier 12).
    cartons_sold = req_int(body, "cartons_sold")
    gross_revenue_cents = req_int(body, "gross_revenue_cents")
    deduction_cents = req_int(body, "deduction_cents")
    # Tier 8: sales only while OPEN or REOPENED.
    if pool["status"] not in ("OPEN", "REOPENED"):
        raise_error(ERR_POOL_INVALID_STATE,
                    f"sales require an OPEN or REOPENED pool, found {pool['status']}")
    # Tier 12: fiscal sign rules.
    if cartons_sold <= 0 or gross_revenue_cents <= 0 or deduction_cents < 0:
        raise_error(ERR_SALE_AMOUNT_INVALID,
                    "cartons_sold and gross_revenue_cents must be > 0; deduction_cents >= 0")
    pool["total_sales_cents"] += gross_revenue_cents
    pool["total_sale_deductions_cents"] += deduction_cents
    recompute_pool_totals(pool)
    touch(pool)
    return success_object(public(pool))


@bp.post("/pools/<poolId>/close")
def close_pool(poolId):
    authorized(["Admin", "PoolManager"])
    pool = require_path_resource("pools", poolId)
    body = get_body()
    # Tier 6: OCC presence.
    if "expected_pool_version" not in body or body.get("expected_pool_version") is None:
        raise_error(ERR_VERSION_REQUIRED, "expected_pool_version is required")
    expected = body.get("expected_pool_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_pool_version must be an integer")
    # Tier 7: OCC freshness.
    if expected != pool["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_pool_version does not match the pool's current version")
    # Tier 8: close requires OPEN or REOPENED.
    if pool["status"] not in ("OPEN", "REOPENED"):
        raise_error(ERR_POOL_INVALID_STATE,
                    f"close requires an OPEN or REOPENED pool, found {pool['status']}")
    # Tier 11: no-open-runs is evaluated before the non-empty check.
    for r in db["packing_runs"].values():
        if r["pool_id"] == pool["id"] and r["status"] == "SCHEDULED":
            raise_error(ERR_POOL_HAS_OPEN_RUNS,
                        "a SCHEDULED run still references this pool")
    if pool["total_packed_cartons"] < 1:
        raise_error(ERR_POOL_EMPTY, "pool has no packed cartons")
    # Final price with the pinned rounding order: round the per-carton price to
    # whole cents first, then multiply per grower (calc pool_price, variant final).
    net = pool["total_sales_cents"] - pool["total_deductions_cents"]
    cartons = pool["total_packed_cartons"]
    price = int((Decimal(net) / Decimal(cartons)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    pool["pool_price_per_carton_cents"] = price
    pool["rounding_drift_cents"] = price * cartons - net
    pool["status"] = "CLOSED"
    touch(pool)
    pool_close_cascade(pool)
    return success_object(public(pool))


@bp.post("/pools/<poolId>/reopen")
def reopen_pool(poolId):
    authorized(["Admin", "PoolManager"])
    pool = require_path_resource("pools", poolId)
    get_body()
    if pool["status"] != "CLOSED":
        raise_error(ERR_POOL_INVALID_STATE,
                    f"reopen requires a CLOSED pool, found {pool['status']}")
    pool["status"] = "REOPENED"
    touch(pool)
    pool_reopen_cascade(pool)
    return success_object(public(pool))
