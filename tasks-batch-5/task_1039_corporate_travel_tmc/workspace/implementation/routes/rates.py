"""NegotiatedRate endpoints."""

from flask import Blueprint, request

import store
from common import get_or_404, single, list_result, filter_by, as_str
from auth import authenticate
from validate import get_body, req_str, req_int, req_dt
from errors import not_found

bp = Blueprint("rates", __name__)

READERS = {"TravelManager", "Traveler", "Approver", "FinanceOfficer"}


@bp.post("/tmc/negotiated-rates")
def create_rate():
    authenticate({"TravelManager"})
    body = get_body()
    # Existence (priority 3): vendor_id FK
    vendor_id = body.get("vendor_id")
    if isinstance(vendor_id, str) and vendor_id != "" and vendor_id not in store.vendors:
        raise not_found("Vendor not found")
    rec = {
        "vendor_id": req_str(body, "vendor_id"),
        "rate_code": req_str(body, "rate_code"),
        "origin": req_str(body, "origin"),
        "destination": req_str(body, "destination"),
        "negotiated_fare_cents": req_int(body, "negotiated_fare_cents", min_value=0),
        "market_fare_cents": req_int(body, "market_fare_cents", min_value=0),
        "cap_usage_count": req_int(body, "cap_usage_count", min_value=1),
        "valid_from": req_dt(body, "valid_from"),
        "valid_to": req_dt(body, "valid_to"),
        "consumed_count": 0,
        "status": "ACTIVE",
    }
    if rec["vendor_id"] not in store.vendors:
        raise not_found("Vendor not found")
    store.stamp_new(rec)
    store.rates[rec["id"]] = rec
    return single(rec, 201)


@bp.get("/tmc/negotiated-rates/<rid>")
def get_rate(rid):
    authenticate(READERS)
    return single(get_or_404(store.rates, rid))


@bp.get("/tmc/negotiated-rates")
def list_rates():
    authenticate(READERS)
    recs = filter_by(store.rates.values(), request.args,
                     {"vendor_id": as_str, "origin": as_str,
                      "destination": as_str, "status": as_str})
    return list_result(recs)
