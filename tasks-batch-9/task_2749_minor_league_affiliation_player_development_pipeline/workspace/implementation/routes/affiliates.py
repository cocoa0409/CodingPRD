"""Affiliate club / academy complex endpoints (PRD Section 3.1)."""
from decimal import Decimal

from flask import Blueprint

import auth
import common
import config
import envelope
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("affiliates", __name__)


@bp.post("/affiliates")
def create_affiliate():
    auth.require(config.ROLE_FARM, config.ROLE_COMPLIANCE)
    body = validate.json_body()
    name = validate.str_field(body, "name", min_len=1, max_len=120)
    level = validate.enum_field(body, "level", config.LEVELS)
    market_city = validate.str_field(body, "market_city", min_len=1, max_len=120)
    stipend = validate.int_field(body, "meal_stipend_cents_per_day")
    roster_limit = validate.int_field(body, "roster_limit", lo=1, hi=40,
                                      required=False, default=None)
    reserve_slots = validate.int_field(body, "reserve_slots", lo=0, hi=40,
                                       required=False, default=35)
    housing_beds = validate.int_field(body, "housing_beds", lo=0, hi=200,
                                      required=False, default=40)
    travel = validate.enum_field(body, "travel_standard_tier", config.TRAVEL_TIERS,
                                 required=False, default="BUS_STANDARD")

    if stipend < config.LEAGUE_MIN_MEAL_STIPEND_CENTS:
        raise ApiError("ERR_MEAL_STIPEND_BELOW_MINIMUM",
                       "meal_stipend_cents_per_day is below the league floor of %d cents."
                       % config.LEAGUE_MIN_MEAL_STIPEND_CENTS)

    if roster_limit is None:
        roster_limit = config.LEVEL_ROSTER_LIMIT[level]

    record = store.base_record()
    record.update({
        "name": name,
        "level": level,
        "market_city": market_city,
        "roster_limit": roster_limit,
        "reserve_slots": reserve_slots,
        "housing_beds": housing_beds,
        "meal_stipend_cents_per_day": stipend,
        "travel_standard_tier": travel,
        "active_roster_count": 0,
        "rehab_assignment_count": 0,
        "reserve_list_count": 0,
        "facility_score": Decimal("100.00"),
        "open_major_deficiency_count": 0,
        "_open_minor_deficiency_count": 0,
        "facility_status": "COMPLIANT",
    })
    store.affiliates[record["id"]] = record
    common.commit()
    return envelope.object_response(serialize.affiliate(record), 201)


@bp.get("/affiliates")
def list_affiliates():
    auth.require(*config.ALL_ROLES)
    rows = list(store.affiliates.values())
    rows = common.apply_filters(rows, (("level", "level"),
                                       ("facility_status", "facility_status")))
    return envelope.paginate(rows, serialize.affiliate)


@bp.get("/affiliates/<affiliate_id>")
def read_affiliate(affiliate_id):
    auth.require(*config.ALL_ROLES)
    record = common.need("affiliates", affiliate_id)
    return envelope.object_response(serialize.affiliate(record))
