"""Key risk indicators (PRD 3.6): dual state dimensions, observations,
threshold evaluation, and the red/normal alert cascade."""
from datetime import timedelta

from flask import Blueprint

from db import store, clock_now
from errors import ApiError
from middleware import authenticate, ALL_ROLES
from response import ok_object, ok_list
from services import (new_entity, new_event, touch, serialize_kri,
                      serialize_observation, eval_kri_breach, kri_cascade)
from util import json_body, req_str, opt_str, req_num, opt_int, req_dt, paginate

bp = Blueprint("kris", __name__)


def get_kri_or_404(kid):
    k = store["kris"].get(kid)
    if k is None:
        raise ApiError("ERR_NOT_FOUND", 404, "KRI not found")
    return k


@bp.post("/kris")
def create_kri():
    authenticate(("RiskManager",))
    data = json_body()
    category_id = req_str(data, "category_id")
    name = req_str(data, "name")
    direction = req_str(data, "direction")
    if direction not in ("ABOVE", "BELOW"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "direction must be ABOVE or BELOW")
    amber = req_num(data, "amber_threshold")
    red = req_num(data, "red_threshold")
    min_interval = opt_int(data, "min_observation_interval_days")
    if min_interval is None:
        min_interval = 1
    if min_interval < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "min_observation_interval_days must be >= 0")
    unit = opt_str(data, "unit")
    if category_id not in store["categories"]:
        raise ApiError("ERR_NOT_FOUND", 404, "category_id does not exist")
    if direction == "ABOVE" and not amber < red:
        raise ApiError("ERR_THRESHOLD_ORDER_INVALID", 422,
                       "ABOVE indicators require amber_threshold < red_threshold")
    if direction == "BELOW" and not amber > red:
        raise ApiError("ERR_THRESHOLD_ORDER_INVALID", 422,
                       "BELOW indicators require amber_threshold > red_threshold")
    k = new_entity()
    k.update({
        "category_id": category_id,
        "name": name,
        "direction": direction,
        "amber_threshold": amber,
        "red_threshold": red,
        "min_observation_interval_days": min_interval,
        "unit": unit,
        "status": "DRAFT",
        "current_breach_status": "NORMAL",
        "last_observation_at": None,
    })
    store["kris"][k["id"]] = k
    return ok_object(serialize_kri(k), 201)


@bp.get("/kris/<kid>")
def get_kri(kid):
    authenticate(ALL_ROLES)
    return ok_object(serialize_kri(get_kri_or_404(kid)))


def _kri_transition(kid, allowed_from, target):
    authenticate(("RiskManager",))
    k = get_kri_or_404(kid)
    if k["status"] != allowed_from:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "KRI in status %s cannot perform this transition" % k["status"])
    k["status"] = target
    touch(k)
    return k


@bp.post("/kris/<kid>/activate")
def activate_kri(kid):
    return ok_object(serialize_kri(_kri_transition(kid, "DRAFT", "ACTIVE")))


@bp.post("/kris/<kid>/retire")
def retire_kri(kid):
    # retirement freezes the breach dimension at its last value
    return ok_object(serialize_kri(_kri_transition(kid, "ACTIVE", "RETIRED")))


@bp.post("/kris/<kid>/observations")
def create_observation(kid):
    authenticate(("RiskManager",))
    data = json_body()
    value = req_num(data, "observed_value")
    observed_at = req_dt(data, "observed_at")
    k = get_kri_or_404(kid)
    if k["status"] != "ACTIVE":
        raise ApiError("ERR_KRI_NOT_ACTIVE", 409,
                       "Observations require an ACTIVE indicator")
    if observed_at > clock_now():
        raise ApiError("ERR_OBSERVATION_IN_FUTURE", 422,
                       "observed_at is after the current logical clock")
    last = k["last_observation_at"]
    if last is not None:
        earliest = last + timedelta(days=k["min_observation_interval_days"])
        if not observed_at > last or observed_at < earliest:
            raise ApiError("ERR_OBSERVATION_TOO_SOON", 409,
                           "observed_at must be strictly after the last observation "
                           "and at least min_observation_interval_days after it")
    result = eval_kri_breach(k["direction"], k["amber_threshold"], k["red_threshold"], value)
    o = new_event()
    o.update({"kri_id": k["id"], "observed_value": value, "observed_at": observed_at,
              "resulting_breach_status": result})
    store["observations"][o["id"]] = o
    k["current_breach_status"] = result
    k["last_observation_at"] = observed_at
    touch(k)
    kri_cascade(k, result)
    return ok_object(serialize_observation(o), 201)


@bp.get("/kris/<kid>/observations")
def list_observations(kid):
    authenticate(ALL_ROLES)
    get_kri_or_404(kid)
    # chronological by observed_at; spacing rules make observed_at unique per KRI
    items = sorted((o for o in store["observations"].values() if o["kri_id"] == kid),
                   key=lambda o: (o["observed_at"], o["_seq"]))
    page, meta = paginate(items)
    return ok_list([serialize_observation(o) for o in page], meta)
