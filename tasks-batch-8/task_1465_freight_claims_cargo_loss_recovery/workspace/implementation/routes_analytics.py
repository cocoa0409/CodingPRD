"""Routes: business calendar rows and the three analytics endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import STORE, iso, new_id, next_seq, now, parse_dt
from errors import ApiError, ERR_INVALID_ENUM, ERR_INVALID_REQUEST
from middleware import as_bool, as_enum, as_str, req_field, request_body, require_roles
from response import paginate, success_object
from serializers import ser_calendar, ser_carrier, ser_lane
from services import round_half_up_int

bp = Blueprint("analytics", __name__)

DAY_KINDS = {"BUSINESS", "WEEKEND", "HOLIDAY"}
AGING_OPEN_STATES = {"SUBMITTED", "ACKNOWLEDGED", "UNDER_REVIEW", "OFFERED",
                     "DECLINED", "APPEALED"}


# ---------------------------------------------------------------------------
# ClaimsCalendar
# ---------------------------------------------------------------------------

@bp.post("/freight-claims/calendar")
@require_roles("PlatformAdmin")
def create_calendar_row():
    body = request_body()
    calendar_date = as_str(req_field(body, "calendar_date"), "calendar_date")
    try:
        from datetime import datetime as _dt
        _dt.strptime(calendar_date, "%Y-%m-%d")
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, "calendar_date must be YYYY-MM-DD", 400)
    is_business_day = as_bool(req_field(body, "is_business_day"), "is_business_day")
    day_kind = as_enum(req_field(body, "day_kind"), "day_kind", DAY_KINDS)
    stamp = iso(now())
    row = {
        "id": new_id(),
        "calendar_date": calendar_date,
        "is_business_day": is_business_day,
        "day_kind": day_kind,
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["calendar"][row["id"]] = row
    return success_object(ser_calendar(row), status=201)


@bp.get("/freight-claims/calendar")
@require_roles("Any")
def list_calendar():
    records = list(STORE["calendar"].values())
    day_kind = request.args.get("day_kind")
    if day_kind is not None:
        records = [r for r in records if r["day_kind"] == day_kind]
    return paginate(records, ser_calendar)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@bp.get("/freight-claims/analytics/carrier-claim-ratio")
@require_roles("Any")
def carrier_claim_ratio():
    window = request.args.get("window", "LIFETIME")
    if window not in ("LIFETIME", "TRAILING_12M"):
        raise ApiError(ERR_INVALID_ENUM, "window must be LIFETIME or TRAILING_12M", 400)
    carriers = list(STORE["carriers"].values())
    carrier_id = request.args.get("carrier_id")
    if carrier_id is not None:
        carriers = [c for c in carriers if c["id"] == carrier_id]

    if window == "TRAILING_12M":
        current = now()
        window_start = current - timedelta(days=365)
        filed_in_window = {}
        for event in STORE["events"].values():
            if event["event_kind"] != "FILED":
                continue
            claim = STORE["claims"].get(event["claim_id"])
            if claim is None:
                continue
            event_dt = parse_dt(event["event_at"], "event_at")
            if window_start <= event_dt <= current:
                filed_in_window.setdefault(claim["carrier_id"], []).append(claim)
        snapshot = []
        for carrier in carriers:
            claims = filed_in_window.get(carrier["id"], [])
            filed = len(claims)
            paid = sum(1 for c in claims
                       if c["filing_status"] in ("PAID", "CLOSED_WITH_PAYMENT"))
            clone = dict(carrier)
            clone["claims_filed_count"] = filed
            clone["claims_paid_count"] = paid
            clone["claim_ratio_bp"] = round_half_up_int(paid * 10000, max(filed, 1))
            snapshot.append(clone)
        carriers = snapshot

    return paginate(carriers, ser_carrier)


@bp.get("/freight-claims/analytics/lane-claim-ratio")
@require_roles("Any")
def lane_claim_ratio():
    lanes = list(STORE["lanes"].values())
    lane_id = request.args.get("lane_id")
    if lane_id is not None:
        lanes = [l for l in lanes if l["id"] == lane_id]
    return paginate(lanes, ser_lane)


@bp.get("/freight-claims/analytics/claim-aging")
@require_roles("Any")
def claim_aging():
    current = now()
    buckets = {"B0_30": 0, "B31_60": 0, "B61_90": 0, "B91_PLUS": 0}
    for claim in STORE["claims"].values():
        if claim["filing_status"] not in AGING_OPEN_STATES:
            continue
        received = claim.get("_filing_received_dt")
        if received is None:
            continue
        age_days = int((current - received).total_seconds() // 86400)
        if age_days < 30:
            buckets["B0_30"] += 1
        elif age_days < 60:
            buckets["B31_60"] += 1
        elif age_days < 90:
            buckets["B61_90"] += 1
        else:
            buckets["B91_PLUS"] += 1
    return success_object(buckets)
