"""Price observation endpoints (PRD 3.3)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
from errors import err
from middleware import (ALL_ROLES, DATA_COLLECTOR, PRICING_ANALYST, body,
                        endpoint)
from response import object_response
from routes.common import FK_LINK, filtered, list_page, path_lookup, resolve_fks
from services import calc, cascades, serialize
from util import as_bool, as_dt, as_enum, as_int, as_str, get_required, invalid

bp = Blueprint("observations", __name__)

OBSERVATION_METHODS = ("ONLINE", "STORE_AUDIT")


@bp.post("/observations")
@endpoint([DATA_COLLECTOR])
def create_observation(user_id, role):
    payload = body()
    fks = resolve_fks(payload, [FK_LINK])

    link = fks["link_id"]
    if link is None:
        get_required(payload, "link_id")
    observed_price_cents = as_int(get_required(payload, "observed_price_cents"),
                                 "observed_price_cents", gt=0)
    method_raw = as_str(get_required(payload, "collection_method"),
                        "collection_method", min_len=1)
    observed_at = as_dt(get_required(payload, "observed_at"), "observed_at")
    in_stock = True
    if payload.get("in_stock") is not None:
        in_stock = as_bool(payload["in_stock"], "in_stock")
    promo_flag = False
    if payload.get("promo_flag") is not None:
        promo_flag = as_bool(payload["promo_flag"], "promo_flag")

    collection_method = as_enum(method_raw, "collection_method", OBSERVATION_METHODS)

    competitor = db.competitors.get(link["competitor_id"])
    declared = competitor["collection_method"] if competitor else None
    if declared in ("ONLINE", "STORE_AUDIT") and declared != collection_method:
        raise invalid("collection_method",
                      "is incompatible with the competitor's declared method %s."
                      % declared)

    window = timedelta(minutes=calc.OBSERVATION_PROXIMITY_MINUTES)
    for other in calc.link_observations(link["id"]):
        if other["status"] != "ACTIVE":
            continue
        if other["collection_method"] != collection_method:
            continue
        if abs(other["observed_at"] - observed_at) < window:
            raise err("ERR_DUPLICATE_OBSERVATION_WINDOW",
                      "Another ACTIVE observation lies within %d minutes."
                      % calc.OBSERVATION_PROXIMITY_MINUTES)

    if observed_at > clock.now():
        raise err("ERR_OBSERVATION_IN_FUTURE",
                  "observed_at is later than the current logical instant.")

    record = db.new_record()
    record.update({
        "link_id": link["id"],
        "observed_price_cents": observed_price_cents,
        "collection_method": collection_method,
        "observed_at": observed_at,
        "in_stock": in_stock,
        "promo_flag": promo_flag,
        "status": "ACTIVE",
        "void_reason": None,
    })
    db.observations[record["id"]] = record

    cascades.reelect(link)
    return object_response(serialize.observation(record), 201)


@bp.post("/observations/<observation_id>/void")
@endpoint([DATA_COLLECTOR, PRICING_ANALYST])
def void_observation(user_id, role, observation_id):
    observation = path_lookup("observations", observation_id,
                              "ERR_OBSERVATION_NOT_FOUND")
    payload = body()
    void_reason = as_str(get_required(payload, "void_reason"), "void_reason",
                         min_len=1)

    if observation["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE observation may be voided.")

    observation["status"] = "VOIDED"
    observation["void_reason"] = void_reason
    db.touch(observation)

    link = db.links.get(observation["link_id"])
    if link is not None:
        cascades.reelect(link)
    return object_response(serialize.observation(observation))


@bp.get("/observations/<observation_id>")
@endpoint(ALL_ROLES)
def read_observation(user_id, role, observation_id):
    observation = path_lookup("observations", observation_id,
                              "ERR_OBSERVATION_NOT_FOUND")
    return object_response(serialize.observation(observation))


@bp.get("/observations")
@endpoint(ALL_ROLES)
def list_observations(user_id, role):
    rows = filtered(db.ordered(db.observations), request.args,
                    [("link_id", "link_id"), ("status", "status"),
                     ("collection_method", "collection_method")])
    return list_page(rows, serialize.observation)
