"""Store master data (PRD section 2.5)."""
from flask import Blueprint

import db
import domain
import response
import serializers
import validation
from auth import endpoint
from errors import bad_request

bp = Blueprint("stores", __name__)

SEASONAL_PROFILES = ("BASELINE", "BACK_TO_SCHOOL", "HOLIDAY")


@bp.post("/cash-ops/stores")
@endpoint(["TreasuryAnalyst"])
def create_store():
    data = validation.body()
    store_code = validation.req_str(data, "store_code")
    if len(store_code) < 1 or len(store_code) > 16:
        raise bad_request("store_code must be between 1 and 16 characters")
    name = validation.req_str(data, "name")
    region_code = validation.req_str(data, "region_code")
    record = db.base_record()
    record.update(
        {
            "store_code": store_code,
            "name": name,
            "region_code": region_code,
            "safe_time_delay_minutes": validation.opt_int(
                data, "safe_time_delay_minutes", 5, minimum=0, maximum=120
            ),
            "safe_open_window_minutes": validation.opt_int(
                data, "safe_open_window_minutes", 10, minimum=1, maximum=240
            ),
            "dual_control_required": validation.opt_bool(data, "dual_control_required", True),
            "pickup_buffer_minutes": validation.opt_int(
                data, "pickup_buffer_minutes", 30, minimum=0, maximum=240
            ),
            "max_daily_pickups": validation.opt_int(
                data, "max_daily_pickups", 2, minimum=1, maximum=6
            ),
            "single_event_variance_threshold_cents": validation.opt_int(
                data, "single_event_variance_threshold_cents", 2500, minimum=0
            ),
            "rolling_variance_threshold_cents": validation.opt_int(
                data, "rolling_variance_threshold_cents", 10000, minimum=0
            ),
            "rolling_window_days": validation.opt_int(
                data, "rolling_window_days", 30, minimum=1, maximum=365
            ),
            "theft_escalation_threshold_cents": validation.opt_int(
                data, "theft_escalation_threshold_cents", 50000, minimum=0
            ),
            "provisional_credit_cap_cents": validation.opt_int(
                data, "provisional_credit_cap_cents", 500000, minimum=0
            ),
            "seasonal_profile": validation.opt_enum(
                data, "seasonal_profile", SEASONAL_PROFILES, "BASELINE"
            ),
        }
    )
    for existing in db.stores.values():
        if existing["store_code"] == store_code:
            raise bad_request("store_code %s is already registered" % store_code)
    db.stores[record["id"]] = record
    return response.object_response(serializers.store(record), 201)


@bp.get("/cash-ops/stores/<store_id>")
@endpoint(["TreasuryAnalyst", "CashOfficeClerk", "StoreManager", "LossPreventionInvestigator"])
def read_store(store_id):
    record = domain.get_store(store_id)
    return response.object_response(serializers.store(record))
