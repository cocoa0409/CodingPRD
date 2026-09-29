"""Promotional campaigns: scheduling with cadence spacing, activation, withdrawal."""

from flask import Blueprint

import calcs
import cascade
import shape
import store
from auth import actor
from envelope import created, list_response, object_response
from errors import ApiError

bp = Blueprint("promotions", __name__)

READ_ROLES = ("RevenueManager", "ReservationAgent", "GroupSalesAgent")
AUDIENCES = ("GENERAL", "REPEAT_GUEST", "GROUP")
OPEN_STATUSES = ("SCHEDULED", "ACTIVE")


def _gap_days_ok(earlier_end, later_start):
    """At least PROMO_CADENCE_GAP_DAYS whole days must separate two campaigns."""
    return (later_start - earlier_end).total_seconds() >= calcs.PROMO_CADENCE_GAP_DAYS * 86400


def _cadence_conflict(sailing_id, starts_on, ends_on):
    for other in cascade.promotions_of(sailing_id):
        if other["status"] == "WITHDRAWN":
            continue
        other_start = store.parse_iso(other["starts_on"])
        other_end = store.parse_iso(other["ends_on"])
        if other_start is None or other_end is None:
            continue
        if starts_on > other_end and _gap_days_ok(other_end, starts_on):
            continue
        if other_start > ends_on and _gap_days_ok(ends_on, other_start):
            continue
        return True
    return False


def _posture_gate(sailing):
    posture = sailing["inventory_posture"]
    if posture == "FROZEN":
        raise ApiError("ERR_POSTURE_FROZEN")
    if posture == "RESTRICTED":
        raise ApiError("ERR_POSTURE_RESTRICTED")


@bp.post("/promotions")
def create_promotion():
    actor("RevenueManager")
    data = shape.body()

    sailing_id = shape.req_str(data, "sailing_id")
    code = shape.req_str(data, "code", max_len=24)
    audience = shape.req_enum(data, "audience", AUDIENCES)
    discount_pct = shape.req_decimal(data, "discount_pct", gt=0, lte="0.5")
    starts_on = shape.req_dt(data, "starts_on")
    ends_on = shape.req_dt(data, "ends_on")
    if ends_on < starts_on:
        raise ApiError("ERR_INVALID_REQUEST")
    max_redemptions = shape.req_int(data, "max_redemptions", minimum=1)
    expected = shape.req_int(data, "expected_sailing_version")

    # Tier 4 uniqueness: code is unique among the promotions of the same sailing.
    for other in store.promotions.values():
        if other["sailing_id"] == sailing_id and other["code"] == code:
            raise ApiError("ERR_DUPLICATE_PROMO_CODE")

    # Tier 6.
    sailing = cascade.sailing_or_404(sailing_id)

    # Tier 9: the campaign calendar the author saw must still be current.
    if expected != sailing["version"]:
        raise ApiError("ERR_STALE_SAILING_VERSION")

    # Tier 16: cadence spacing against every non-withdrawn campaign.
    if _cadence_conflict(sailing_id, starts_on, ends_on):
        raise ApiError("ERR_PROMO_CADENCE_CONFLICT")

    row = store.stamp_new({})
    row.update({
        "sailing_id": sailing["id"],
        "code": code,
        "audience": audience,
        "discount_pct": float(discount_pct),
        "starts_on": store.iso(starts_on),
        "ends_on": store.iso(ends_on),
        "max_redemptions": max_redemptions,
        "redemption_count": 0,
        "status": "SCHEDULED",
        "withdraw_reason": None,
    })
    store.promotions[row["id"]] = row
    # Creating a campaign moves the parent sailing's version by exactly 1.
    store.touch(sailing)
    return created(row)


@bp.get("/promotions/<promotion_id>")
def read_promotion(promotion_id):
    actor(*READ_ROLES)
    return object_response(cascade.promotion_or_404(promotion_id))


@bp.get("/promotions")
def list_promotions():
    actor(*READ_ROLES)
    limit, offset = shape.pagination()
    sailing_id = shape.filter_str("sailing_id")
    status = shape.filter_str("status")
    audience = shape.filter_str("audience")
    code = shape.filter_str("code")

    rows = []
    for row in store.promotions.values():
        if sailing_id is not None and row["sailing_id"] != sailing_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if audience is not None and row["audience"] != audience:
            continue
        if code is not None and row["code"] != code:
            continue
        rows.append(row)
    rows.sort(key=lambda r: r["created_at"])
    return list_response(rows, limit, offset)


@bp.post("/promotions/<promotion_id>/activate")
def activate_promotion(promotion_id):
    actor("RevenueManager")
    shape.body()
    promotion = cascade.promotion_or_404(promotion_id)

    # Tier 10.
    if promotion["status"] != "SCHEDULED":
        raise ApiError("ERR_PROMOTION_NOT_SCHEDULED")

    # Tier 16: the current instant must lie inside the inclusive campaign interval.
    now = store.now_dt()
    starts_on = store.parse_iso(promotion["starts_on"])
    ends_on = store.parse_iso(promotion["ends_on"])
    if starts_on is None or ends_on is None or not (starts_on <= now <= ends_on):
        raise ApiError("ERR_PROMO_WINDOW_NOT_CURRENT")

    # Tier 18: posture gate.
    sailing = store.sailings.get(promotion["sailing_id"])
    if sailing is not None:
        _posture_gate(sailing)

    promotion["status"] = "ACTIVE"
    store.touch(promotion)
    return object_response(promotion)


@bp.post("/promotions/<promotion_id>/withdraw")
def withdraw_promotion(promotion_id):
    actor("RevenueManager")
    data = shape.body()
    reason = shape.req_str(data, "reason")
    promotion = cascade.promotion_or_404(promotion_id)

    # Tier 10: EXHAUSTED, EXPIRED and WITHDRAWN are terminal.
    if promotion["status"] not in OPEN_STATUSES:
        raise ApiError("ERR_PROMOTION_ALREADY_CLOSED")

    promotion["status"] = "WITHDRAWN"
    promotion["withdraw_reason"] = reason
    # Withdrawal is not a repricing event: pinned booking discounts stand.
    store.touch(promotion)
    return object_response(promotion)
