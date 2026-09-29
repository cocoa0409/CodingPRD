"""RedemptionPeriod endpoints."""
from flask import Blueprint

import calc
import serial
import services
from core import (bad_request, db, ensure_object, fail, filter_str, get_body,
                  mark, now, ok, ok_list, ordered, paginate, req_dt, req_int,
                  req_str, require_auth, resolve_body_ref, resolve_path,
                  stamp_new)
from guards import ANALYST_ADMIN, ALL_READ

bp = Blueprint("periods", __name__)


@bp.post("/redemption-periods")
def create_period():
    require_auth(ANALYST_ADMIN)
    body = get_body()
    ensure_object(body)
    store = resolve_body_ref(body, "store_id", db.stores, "ERR_STORE_NOT_FOUND")
    period_index = req_int(body, "period_index", minimum=1)
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    if store is None:
        req_str(body, "store_id")
    if period_end <= period_start:
        bad_request("Field 'period_end' must be strictly after 'period_start'.")
    if calc.period_overlaps(store["id"], period_start, period_end):
        fail("ERR_REDEMPTION_PERIOD_OVERLAP")
    for other in db.redemption_periods.values():
        if other["store_id"] == store["id"] and \
                other["period_index"] == period_index:
            fail("ERR_DUPLICATE_PERIOD_INDEX")
    row = stamp_new({
        "store_id": store["id"],
        "period_index": period_index,
        "period_start": period_start,
        "period_end": period_end,
        "pos_derived_total_cents": 0,
        "pos_derived_transaction_count": 0,
        "imported_total_cents": None,
        "imported_transaction_count": None,
        "imported_large_transaction_cents": None,
        "imported_even_dollar_transaction_count": None,
        "redemption_total_cents": 0,
        "transaction_count": 0,
        "large_transaction_cents": 0,
        "even_dollar_transaction_count": 0,
        "reconciliation_variance_cents": None,
        "reconciliation_status": "NOT_IMPORTED",
        "size_expectation_cents": None,
        "anomaly_score": None,
        "flag_level": None,
        "closed_at": None,
        "status": "OPEN",
    })
    row.update(calc.period_metrics(row))
    db.redemption_periods[row["id"]] = row
    return ok(serial.redemption_period(row), 201)


@bp.get("/redemption-periods/<period_id>")
def get_period(period_id):
    require_auth(ALL_READ)
    row = resolve_path(db.redemption_periods, period_id,
                       "ERR_REDEMPTION_PERIOD_NOT_FOUND")
    return ok(serial.redemption_period(row))


@bp.get("/redemption-periods")
def list_periods():
    require_auth(ALL_READ)
    rows = ordered(list(db.redemption_periods.values()))
    for name in ("store_id", "status", "flag_level", "reconciliation_status"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    data, pagination = paginate(rows, serial.redemption_period)
    return ok_list(data, pagination)


@bp.post("/redemption-periods/<period_id>/settlement-import")
def settlement_import(period_id):
    require_auth(ANALYST_ADMIN)
    period = resolve_path(db.redemption_periods, period_id,
                          "ERR_REDEMPTION_PERIOD_NOT_FOUND")
    body = get_body()
    ensure_object(body)
    total = req_int(body, "imported_total_cents", minimum=0)
    count = req_int(body, "imported_transaction_count", minimum=0)
    large = req_int(body, "imported_large_transaction_cents", minimum=0)
    even = req_int(body, "imported_even_dollar_transaction_count", minimum=0)
    if period["status"] != "OPEN":
        fail("ERR_REDEMPTION_PERIOD_CLOSED")
    period.update({
        "imported_total_cents": total,
        "imported_transaction_count": count,
        "imported_large_transaction_cents": large,
        "imported_even_dollar_transaction_count": even,
    })
    period.update(calc.period_metrics(period))
    mark(period)
    services.commit()
    return ok(serial.redemption_period(period))


@bp.post("/redemption-periods/<period_id>/close")
def close_period(period_id):
    require_auth(ANALYST_ADMIN)
    period = resolve_path(db.redemption_periods, period_id,
                          "ERR_REDEMPTION_PERIOD_NOT_FOUND")
    if period["status"] != "OPEN":
        fail("ERR_INVALID_STATE")
    if now() < period["period_end"]:
        fail("ERR_PERIOD_NOT_ELAPSED")
    store = db.stores.get(period["store_id"])
    period.update(calc.period_metrics(period))
    size_expectation, score = calc.anomaly_score(period, store)
    period["size_expectation_cents"] = size_expectation
    period["anomaly_score"] = score
    period["flag_level"] = calc.flag_level_for(score)
    period["status"] = "CLOSED"
    period["closed_at"] = now()
    mark(period)
    if store is not None:
        services.refresh_store_flag_level(store)
        if period["flag_level"] == "FLAG_L3":
            investigation = stamp_new({
                "store_id": store["id"],
                "trigger_period_id": period["id"],
                "opened_reason": "ANOMALY_FLAG_L3",
                "evidence_items": [],
                "trafficking_confidence_score": 0,
                "substantiated_violation": None,
                "opened_by_user_id": "system",
                "concluded_by_user_id": None,
                "concluded_at": None,
                "status": "OPEN",
            })
            db.investigations[investigation["id"]] = investigation
            services.open_investigation_cascade(store)
    services.commit()
    return ok(serial.redemption_period(period))
