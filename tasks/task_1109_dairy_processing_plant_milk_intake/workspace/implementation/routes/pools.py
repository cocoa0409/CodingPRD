"""Marketing order pools and the PPD waterfall (PRD 3.10)."""
from datetime import datetime, timezone

from flask import Blueprint

from db import STORE, base_record, now, touch
from errors import (
    ApiError,
    ERR_ANNOUNCEMENT_TOO_EARLY,
    ERR_PRICES_INCOMPLETE,
    ERR_SETTLEMENTS_ALREADY_APPROVED,
    ERR_STALE_POOL_VERSION,
    bad_input,
    invalid_state,
    not_found,
)
from helpers import body, parse_pool_month, req_int
from middleware import require_roles
from response import success_object
from services import compute_ppd, recompute_settlement, ser_pool

bp = Blueprint("pools", __name__)

_PC = "PlantController"


def _get_pool(pid):
    pool = STORE["pools"].get(pid)
    if pool is None:
        raise not_found("MarketingOrderPool not found")
    return pool


def _announcement_threshold(pool_month):
    """23rd of the month following pool_month at 00:00 UTC."""
    year = int(pool_month[:4])
    month = int(pool_month[5:7])
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    return datetime(year, month, 23, 0, 0, 0, tzinfo=timezone.utc)


@bp.route("/dairy/marketing-order-pools", methods=["POST"])
def create_pool():
    require_roles(_PC)
    data = body()
    pool_month = parse_pool_month(data.get("pool_month"))
    class_i = req_int(data, "announced_class_i_price_cents")
    butterfat = req_int(data, "butterfat_price_cents_per_lb")
    protein = req_int(data, "protein_price_cents_per_lb")
    other_solids = req_int(data, "other_solids_price_cents_per_lb")
    rec = base_record()
    rec.update({
        "pool_month": pool_month,
        "announced_class_i_price_cents": class_i,
        "butterfat_price_cents_per_lb": butterfat,
        "protein_price_cents_per_lb": protein,
        "other_solids_price_cents_per_lb": other_solids,
        "producer_price_differential_cents": None,
        "status": "DRAFT",
    })
    STORE["pools"][rec["id"]] = rec
    return success_object(ser_pool(rec), 201)


@bp.route("/dairy/marketing-order-pools/<pid>", methods=["GET"])
def get_pool(pid):
    require_roles(_PC, "StateInspector")
    return success_object(ser_pool(_get_pool(pid)))


@bp.route("/dairy/marketing-order-pools/<pid>/announce", methods=["POST"])
def announce_pool(pid):
    require_roles(_PC)
    pool = _get_pool(pid)
    if pool["status"] != "DRAFT":
        raise invalid_state("MarketingOrderPool is not in DRAFT")
    if not (
        pool["butterfat_price_cents_per_lb"] > 0
        and pool["protein_price_cents_per_lb"] > 0
        and pool["other_solids_price_cents_per_lb"] > 0
    ):
        raise ApiError(ERR_PRICES_INCOMPLETE, 422,
                       "All component prices must be positive")
    if now() < _announcement_threshold(pool["pool_month"]):
        raise ApiError(
            ERR_ANNOUNCEMENT_TOO_EARLY, 422,
            "Pool cannot be announced before the 23rd of the following month",
        )
    pool["producer_price_differential_cents"] = compute_ppd(pool)
    pool["status"] = "ANNOUNCED"
    touch(pool)
    return success_object(ser_pool(pool), 200)


@bp.route("/dairy/marketing-order-pools/<pid>/finalize", methods=["POST"])
def finalize_pool(pid):
    require_roles(_PC)
    pool = _get_pool(pid)
    if pool["status"] != "ANNOUNCED":
        raise invalid_state("MarketingOrderPool is not in ANNOUNCED")
    data = body()
    expected = data.get("expected_pool_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise bad_input("Field 'expected_pool_version' must be an integer")
    if pool["version"] != expected:
        raise ApiError(
            ERR_STALE_POOL_VERSION, 412,
            "expected_pool_version does not match MarketingOrderPool.version",
        )
    month = pool["pool_month"]
    settlements = [
        s for s in STORE["settlements"].values()
        if s["period_start_date"].strftime("%Y-%m") == month
    ]
    if any(not (s["status"] == "DRAFT" and s["pricing_variant"] == "PROVISIONAL")
           for s in settlements):
        raise ApiError(
            ERR_SETTLEMENTS_ALREADY_APPROVED, 422,
            "Settlements for this pool month are no longer DRAFT/PROVISIONAL",
        )
    pool["status"] = "FINALIZED"
    touch(pool)
    for settlement in settlements:
        settlement["pricing_variant"] = "FINAL"
        recompute_settlement(settlement, pool=pool)
        touch(settlement)
    return success_object(ser_pool(pool), 200)
