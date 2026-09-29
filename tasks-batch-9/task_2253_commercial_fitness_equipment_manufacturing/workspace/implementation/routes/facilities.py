"""Gym facility accounts (PRD 3.5)."""

from flask import Blueprint

from auth import check_facility_scope, get_facility, require
from constants import FREIGHT_ZONES, WEEKDAYS
from envelope import created, ok
from errors import ApiError
from store import mutate, new_entity, store
from validation import (
    field_enum,
    field_enum_array,
    field_int,
    field_str,
    get_body,
)

bp = Blueprint("facilities", __name__)


@bp.post("/facilities")
@require("OrderPlanner", "ServiceOpsAdmin")
def create_facility():
    body = get_body()
    account_name = field_str(body, "account_name", min_len=1, max_len=120)
    freight_zone = field_enum(body, "freight_zone", FREIGHT_ZONES)
    credit_limit_cents = field_int(body, "credit_limit_cents", minimum=0)
    install_blackout_weekdays = field_enum_array(
        body,
        "install_blackout_weekdays",
        WEEKDAYS,
        required=False,
        non_empty=False,
        default=[],
    )

    facility = new_entity(
        {
            "account_name": account_name,
            "freight_zone": freight_zone,
            "credit_limit_cents": credit_limit_cents,
            "install_blackout_weekdays": install_blackout_weekdays,
            "status": "ACTIVE",
            "open_order_exposure_cents": 0,
            "tradein_credit_granted_cents": 0,
            "tradein_credit_applied_cents": 0,
            "tradein_credit_balance_cents": 0,
        }
    )
    store.facilities[facility["id"]] = facility
    return created(facility)


@bp.get("/facilities/<facility_id>")
@require(
    "OrderPlanner",
    "ComplianceOfficer",
    "ServiceOpsAdmin",
    "FacilityManager",
    "ServicePartnerTech",
)
def read_facility(facility_id):
    facility = get_facility(facility_id)
    check_facility_scope(facility["id"])
    return ok(facility)


@bp.post("/facilities/<facility_id>/suspend")
@require("OrderPlanner", "ServiceOpsAdmin")
def suspend_facility(facility_id):
    facility = get_facility(facility_id)
    body = get_body()
    field_str(body, "suspend_reason", min_len=1)

    if facility["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE facility may be suspended."
        )

    with mutate(facility):
        facility["status"] = "SUSPENDED"
    return ok(facility)
