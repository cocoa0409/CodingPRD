"""Price observation endpoints: submit, approve, fair-value override."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok
from services import navmath
from services.navmath import D
from validation import parse_body, require_fk, require_path_entity

bp = Blueprint("prices", __name__)

MANUAL_SOURCES = ["EXCHANGE_CLOSE", "PRICING_SERVICE", "BROKER_QUOTE"]
ALL_SOURCES = MANUAL_SOURCES + ["FAIR_VALUE_COMMITTEE"]

OBSERVATION_SCHEMA = {
    "security_id": ("string", True, None),
    "price_date": ("date", True, None),
    "price": ("posnumber", True, None),
    "source": ("enum", True, ALL_SOURCES),
    "pricing_level": ("enum", True, ["LEVEL_1", "LEVEL_2", "LEVEL_3"]),
}

OVERRIDE_SCHEMA = {
    "override_price": ("posnumber", True, None),
    "pricing_level": ("enum", True, ["LEVEL_1", "LEVEL_2", "LEVEL_3"]),
}


@bp.post("/price-observations")
def create_price_observation():
    get_context()
    require_roles(["FundAccountant"])
    body = parse_body(OBSERVATION_SCHEMA)
    security = require_fk(store.securities, body["security_id"], "security_id")

    # Temporal (priority 8): the price date must not lie after the clock date.
    if navmath.date_of(body["price_date"]) > db.clock_today():
        raise ApiError("ERR_PRICE_DATE_FUTURE", 422,
                       "price_date is after the logical clock date")

    # Constraints (priority 9): duplicate live source, then reserved source.
    for other in store.price_observations.values():
        if other["security_id"] == security["id"] \
                and other["price_date"] == body["price_date"] \
                and other["source"] == body["source"] \
                and other["status"] != "OVERRIDDEN":
            raise ApiError("ERR_DUPLICATE_PRICE_SOURCE", 409,
                           "A live observation already exists for this security, date and source")
    if body["source"] == "FAIR_VALUE_COMMITTEE":
        raise ApiError("ERR_OVERRIDE_SOURCE_RESERVED", 422,
                       "FAIR_VALUE_COMMITTEE is reserved to the override flow")

    observation = {
        "id": db.new_id(),
        "security_id": security["id"],
        "price_date": body["price_date"],
        "price": D(body["price"]),
        "source": body["source"],
        "pricing_level": body["pricing_level"],
        "is_fair_value_override": False,
        "status": "SUBMITTED",
    }
    db.new_common(observation)
    store.price_observations[observation["id"]] = observation

    navmath.recompute_estimated_for_price(security["id"], observation["price_date"])
    return created(observation)


@bp.post("/price-observations/<price_observation_id>/approve")
def approve_price_observation(price_observation_id):
    get_context()
    observation = require_path_entity(store.price_observations, price_observation_id)
    require_roles(["PricingCommittee"])
    parse_body({})
    if observation["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SUBMITTED observation can be approved")
    observation["status"] = "APPROVED"
    db.touch(observation)
    navmath.recompute_estimated_for_price(observation["security_id"],
                                          observation["price_date"])
    return ok(observation)


@bp.post("/price-observations/<price_observation_id>/override")
def override_price_observation(price_observation_id):
    get_context()
    observation = require_path_entity(store.price_observations, price_observation_id)
    require_roles(["PricingCommittee"])
    body = parse_body(OVERRIDE_SCHEMA)
    if observation["status"] not in ("SUBMITTED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SUBMITTED or APPROVED observation can be overridden")

    observation["status"] = "OVERRIDDEN"
    db.touch(observation)

    replacement = {
        "id": db.new_id(),
        "security_id": observation["security_id"],
        "price_date": observation["price_date"],
        "price": D(body["override_price"]),
        "source": "FAIR_VALUE_COMMITTEE",
        "pricing_level": body["pricing_level"],
        "is_fair_value_override": True,
        "status": "APPROVED",
    }
    db.new_common(replacement)
    store.price_observations[replacement["id"]] = replacement

    navmath.override_cascade(replacement["security_id"], replacement["price_date"])
    return created(replacement)
