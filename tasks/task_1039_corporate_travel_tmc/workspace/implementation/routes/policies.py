"""TravelPolicy endpoints."""

from flask import Blueprint

import store
from common import get_or_404, single
from auth import authenticate
from validate import get_body, req_str, req_int, req_enum

bp = Blueprint("policies", __name__)

AIR_CLASSES = {"ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"}
READERS = {"TravelManager", "Traveler", "Approver", "FinanceOfficer"}


@bp.post("/tmc/travel-policies")
def create_policy():
    authenticate({"TravelManager"})
    body = get_body()
    rec = {
        "name": req_str(body, "name"),
        "region": req_str(body, "region"),
        "max_air_class": req_enum(body, "max_air_class", AIR_CLASSES),
        "max_hotel_nightly_cents": req_int(body, "max_hotel_nightly_cents", min_value=0),
        "advance_purchase_days": req_int(body, "advance_purchase_days", min_value=0),
        "requires_manager_approval_over_cents": req_int(body, "requires_manager_approval_over_cents", min_value=0),
        "requires_exec_approval_over_cents": req_int(body, "requires_exec_approval_over_cents", min_value=0),
        "exchange_penalty_cents": req_int(body, "exchange_penalty_cents", min_value=0),
        "credit_validity_days": req_int(body, "credit_validity_days", min_value=0),
    }
    store.stamp_new(rec)
    store.policies[rec["id"]] = rec
    return single(rec, 201)


@bp.get("/tmc/travel-policies/<pid>")
def get_policy(pid):
    authenticate(READERS)
    return single(get_or_404(store.policies, pid))
