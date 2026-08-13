"""Tariff schedules (effective-dated; status computed by resolution)."""
from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import ANY_ROLE, auth
from response import ok, ok_list
from services import base_entity, schedule_status, tariff_view
from util import body, pagination_args, paginate, req_dt, req_int, req_num

bp = Blueprint("tariffs", __name__)


def _validate_tiers(data):
    tiers = data.get("tiers")
    if not isinstance(tiers, list) or not tiers:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "tiers must be a non-empty array"
        )
    cleaned = []
    for tier in tiers:
        if not isinstance(tier, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "tier must be an object")
        lo = tier.get("min_gt_exclusive")
        hi = tier.get("max_gt_inclusive")
        rate = tier.get("rate_cents_per_gt")
        if not isinstance(lo, int) or isinstance(lo, bool) or lo < 0:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "tier min_gt_exclusive must be an integer >= 0"
            )
        if hi is not None and (not isinstance(hi, int) or isinstance(hi, bool)):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "tier max_gt_inclusive must be an integer or null",
            )
        if hi is not None and hi <= lo:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "tier max_gt_inclusive must exceed min_gt_exclusive",
            )
        if not isinstance(rate, int) or isinstance(rate, bool) or rate < 0:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "tier rate_cents_per_gt must be an integer >= 0"
            )
        cleaned.append(
            {
                "min_gt_exclusive": lo,
                "max_gt_inclusive": hi,
                "rate_cents_per_gt": rate,
            }
        )
    return cleaned


@bp.post("/pilotage/tariff-schedules")
def create_schedule():
    auth(["AssociationAdmin"])
    data = body()
    effective_from = req_dt(data, "effective_from")
    tiers = _validate_tiers(data)
    threshold = req_int(data, "draft_surcharge_threshold_dm", minimum=0)
    pct = req_num(data, "draft_surcharge_pct")
    if pct < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "draft_surcharge_pct must be >= 0"
        )
    free_minutes = req_int(data, "detention_free_minutes", minimum=0)
    detention_rate = req_int(data, "detention_rate_cents_per_minute", minimum=0)
    delay_rate = req_int(data, "delay_rate_cents_per_minute", minimum=0)

    schedule = base_entity()
    schedule.update(
        {
            "effective_from": effective_from,
            "tiers": tiers,
            "draft_surcharge_threshold_dm": threshold,
            "draft_surcharge_pct": pct,
            "detention_free_minutes": free_minutes,
            "detention_rate_cents_per_minute": detention_rate,
            "delay_rate_cents_per_minute": delay_rate,
        }
    )
    DB["tariff_schedules"][schedule["id"]] = schedule
    return ok(tariff_view(schedule), status=201)


@bp.get("/pilotage/tariff-schedules")
def list_schedules():
    auth(ANY_ROLE)
    limit, offset = pagination_args()
    status = request.args.get("status")
    items = list(DB["tariff_schedules"].values())
    if status is not None:
        items = [s for s in items if schedule_status(s) == status]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list([tariff_view(s) for s in page], total, limit, offset)
