"""PricingOffer endpoints (pricing/concession display, publish/retire)."""
from decimal import Decimal

from flask import Blueprint

from db import DB, clock_now, new_id
from errors import ApiError
from middleware import APPLICANT, AGENT, PM, auth
from response import ok, ok_list
from services import (
    CONCESSION_TYPES,
    effective_monthly_rent,
    get_floorplan,
    get_offer,
    get_property,
    ser_offer,
    sorted_created,
    stamp,
    touch,
)
from util import (
    apply_filters,
    as_dt,
    as_enum,
    as_int,
    as_nonneg_int,
    as_num,
    as_str,
    body,
    opt,
    pagination,
    required,
)

bp = Blueprint("offers", __name__)

READ_ALL = [PM, AGENT, APPLICANT]


@bp.post("/leasing/pricing-offers")
def create_offer():
    auth([PM])
    data = body()
    property_id = as_str(required(data, "property_id"), "property_id")
    floorplan_id = as_str(required(data, "floorplan_id"), "floorplan_id")
    base_rent_cents = as_nonneg_int(required(data, "base_rent_cents"), "base_rent_cents")
    concession_type = as_enum(
        opt(data, "concession_type", "NONE"), "concession_type", CONCESSION_TYPES
    )
    concession_value = as_num(opt(data, "concession_value", 0), "concession_value")
    lease_term_months = as_int(opt(data, "lease_term_months", 12), "lease_term_months")
    effective_start = as_dt(required(data, "effective_start"), "effective_start")
    expires_at = as_dt(required(data, "expires_at"), "expires_at")

    get_property(property_id)
    get_floorplan(floorplan_id)

    if lease_term_months < 1:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "lease_term_months must be at least 1"
        )
    if Decimal(str(concession_value)) < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "concession_value must not be negative"
        )
    if concession_type == "PERCENT_OFF" and Decimal(str(concession_value)) > 100:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "concession_value must be between 0 and 100"
        )
    # Interval rule: expires_at must fall strictly after effective_start.
    if not expires_at > effective_start:
        raise ApiError(
            "ERR_INVALID_TIME_RANGE",
            400,
            "expires_at must be strictly after effective_start",
        )

    rec = {
        "id": new_id(),
        "property_id": property_id,
        "floorplan_id": floorplan_id,
        "base_rent_cents": base_rent_cents,
        "concession_type": concession_type,
        "concession_value": concession_value,
        "lease_term_months": lease_term_months,
        "effective_start": effective_start,
        "expires_at": expires_at,
        "effective_monthly_rent_cents": effective_monthly_rent(
            base_rent_cents, concession_type, concession_value, lease_term_months
        ),
        "status": "DRAFT",
    }
    stamp(rec)
    DB["offers"][rec["id"]] = rec
    return ok(ser_offer(rec), status=201)


@bp.get("/leasing/pricing-offers")
def list_offers():
    auth(READ_ALL)
    limit, offset = pagination()
    items = apply_filters(
        DB["offers"].values(),
        [
            ("property_id", "property_id"),
            ("floorplan_id", "floorplan_id"),
            ("status", "status"),
        ],
    )
    items = sorted_created(items)
    total = len(items)
    return ok_list(
        [ser_offer(o) for o in items[offset : offset + limit]], total, limit, offset
    )


@bp.get("/leasing/pricing-offers/<oid>")
def get_one_offer(oid):
    auth(READ_ALL)
    return ok(ser_offer(get_offer(oid)))


@bp.post("/leasing/pricing-offers/<oid>/publish")
def publish_offer(oid):
    auth([PM])
    offer = get_offer(oid)
    if offer["status"] != "DRAFT":
        raise ApiError(
            "ERR_PRICING_OFFER_INVALID_STATE", 409, "Only a DRAFT offer can be published"
        )
    for o in DB["offers"].values():
        if (
            o["id"] != offer["id"]
            and o["floorplan_id"] == offer["floorplan_id"]
            and o["status"] == "PUBLISHED"
        ):
            raise ApiError(
                "ERR_OFFER_ALREADY_PUBLISHED",
                409,
                "Another offer for this floorplan is already PUBLISHED",
            )
    if not offer["expires_at"] > clock_now():
        raise ApiError(
            "ERR_INVALID_TIME_RANGE",
            400,
            "Cannot publish an offer whose expires_at has already passed",
        )
    offer["status"] = "PUBLISHED"
    touch(offer)
    return ok(ser_offer(offer))


@bp.post("/leasing/pricing-offers/<oid>/retire")
def retire_offer(oid):
    auth([PM])
    offer = get_offer(oid)
    if offer["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError(
            "ERR_PRICING_OFFER_INVALID_STATE",
            409,
            "Only a DRAFT or PUBLISHED offer can be retired",
        )
    offer["status"] = "RETIRED"
    touch(offer)
    return ok(ser_offer(offer))
