"""Trial sites, regional trials, evaluation scoring and certification."""

from decimal import Decimal

from flask import Blueprint

from calculations import (PASS_INDEX_THRESHOLD, PASS_RATE_THRESHOLD,
                          trial_performance_index)
from common import filtered, resolve, terminal, transition
from derive import (TRIAL_OCCUPYING, apply, children,
                    recompute_trial_site_occupancy, variety_trial_aggregates)
from errors import ApiError
from middleware import ALL_ROLES, BREEDER_ADMIN, TRIAL_COORDINATOR, endpoint
from response import collection, created, ok
from store import new_id, parse_dt, store
from validation import ID, DateTime, Dec, Int, Str, UPPER_2_6

bp = Blueprint("trials", __name__)

TRIAL_TERMINAL = ("PASSED", "FAILED")

SITE_SCHEMA = [
    ("site_name", Str(1, 60), True),
    ("region_code", UPPER_2_6, True),
    ("plot_capacity", Int(1), True),
]

TRIAL_SCHEMA = [
    ("variety_id", ID, True),
    ("trial_site_id", ID, True),
    ("plot_count", Int(1), True),
    ("plant_date", DateTime(), True),
    ("harvest_date", DateTime(), True),
]

EVALUATE_SCHEMA = [
    ("yield_index", Dec(2, 0, 100), True),
    ("vigor_score", Dec(2, 0, 100), True),
    ("uniformity_score", Dec(2, 0, 100), True),
    ("disease_resistance_score", Dec(2, 0, 100), True),
    ("propagation_pass_rate", Dec(4, 0, 1), True),
]


# ---------------------------------------------------------------- sites
@endpoint(bp, "POST", "/trial-sites", [TRIAL_COORDINATOR], SITE_SCHEMA)
def create_site(actor, body):
    record = {
        "id": new_id(),
        "site_name": body["site_name"],
        "region_code": body["region_code"],
        "plot_capacity": body["plot_capacity"],
        "occupied_plot_count": 0,
    }
    store.stamp_new(record)
    store.trial_sites[record["id"]] = record
    return created(record)


@endpoint(bp, "GET", "/trial-sites", ALL_ROLES)
def list_sites(actor):
    records, limit, offset, total = filtered("trial_sites", "region_code")
    return collection(records, limit, offset, total)


@endpoint(bp, "GET", "/trial-sites/<trial_site_id>", ALL_ROLES)
def get_site(actor, trial_site_id):
    return ok(resolve("trial_site_id", trial_site_id))


# ---------------------------------------------------------------- trials
@endpoint(bp, "POST", "/variety-trials", [TRIAL_COORDINATOR], TRIAL_SCHEMA)
def create_trial(actor, body):
    variety = resolve("variety_id", body["variety_id"])
    site = resolve("trial_site_id", body["trial_site_id"])
    plant_date = parse_dt(body["plant_date"])
    harvest_date = parse_dt(body["harvest_date"])
    if harvest_date <= plant_date:
        raise ApiError("ERR_INVALID_INTERVAL")
    record = {
        "id": new_id(),
        "variety_id": variety["id"],
        "trial_site_id": site["id"],
        "plot_count": body["plot_count"],
        "plant_date": body["plant_date"],
        "harvest_date": body["harvest_date"],
        "status": "PLANNED",
        "yield_index": None,
        "vigor_score": None,
        "uniformity_score": None,
        "disease_resistance_score": None,
        "propagation_pass_rate": None,
        "performance_index": Decimal("0.00"),
        "evaluated_at": None,
    }
    store.stamp_new(record)
    store.trials[record["id"]] = record
    recompute_trial_site_occupancy(site)
    return created(record)


@endpoint(bp, "GET", "/variety-trials", ALL_ROLES)
def list_trials(actor):
    records, limit, offset, total = filtered(
        "trials", "variety_id", "trial_site_id", "status")
    return collection(records, limit, offset, total)


@endpoint(bp, "GET", "/variety-trials/<trial_id>", ALL_ROLES)
def get_trial(actor, trial_id):
    return ok(resolve("trial_id", trial_id))


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open windows: adjacency is not overlap (PRD 3.4)."""
    return a_start < b_end and b_start < a_end


@endpoint(bp, "POST", "/variety-trials/<trial_id>/plant", [TRIAL_COORDINATOR], [])
def plant_trial(actor, body, trial_id):
    trial = resolve("trial_id", trial_id)
    terminal(trial["status"] in TRIAL_TERMINAL)
    transition(trial["status"] == "PLANNED")
    variety = store.varieties[trial["variety_id"]]
    terminal(variety["lifecycle_state"] == "RETIRED")
    plant_date = parse_dt(trial["plant_date"])
    if store.now < plant_date:
        raise ApiError("ERR_TRIAL_DATE_NOT_REACHED")
    site = store.trial_sites[trial["trial_site_id"]]
    harvest_date = parse_dt(trial["harvest_date"])
    occupied = 0
    for other in children("trials", "trial_site_id", site["id"]):
        if other["id"] != trial["id"] and other["status"] not in TRIAL_OCCUPYING:
            continue
        if other["id"] != trial["id"] and not _overlaps(
                plant_date, harvest_date,
                parse_dt(other["plant_date"]), parse_dt(other["harvest_date"])):
            continue
        occupied += int(other["plot_count"])
    if occupied > int(site["plot_capacity"]):
        raise ApiError("ERR_TRIAL_SITE_CAPACITY_EXCEEDED")

    apply(trial, {"status": "PLANTED"}, force=True)
    recompute_trial_site_occupancy(site, force=True)
    if variety["lifecycle_state"] == "CANDIDATE":
        apply(variety, {"lifecycle_state": "IN_TRIAL"})
    elif variety["lifecycle_state"] == "TRIAL_COMPLETE" and variety["released_at"] is None:
        apply(variety, {"lifecycle_state": "IN_TRIAL"})
    return ok(trial)


@endpoint(bp, "POST", "/variety-trials/<trial_id>/evaluate", [TRIAL_COORDINATOR],
          EVALUATE_SCHEMA)
def evaluate_trial(actor, body, trial_id):
    trial = resolve("trial_id", trial_id)
    terminal(trial["status"] in TRIAL_TERMINAL)
    transition(trial["status"] == "PLANTED")
    if store.now < parse_dt(trial["harvest_date"]):
        raise ApiError("ERR_TRIAL_DATE_NOT_REACHED")
    index = trial_performance_index(
        body["yield_index"], body["vigor_score"], body["uniformity_score"],
        body["disease_resistance_score"], body["propagation_pass_rate"])
    apply(trial, {
        "status": "EVALUATED",
        "yield_index": body["yield_index"],
        "vigor_score": body["vigor_score"],
        "uniformity_score": body["uniformity_score"],
        "disease_resistance_score": body["disease_resistance_score"],
        "propagation_pass_rate": body["propagation_pass_rate"],
        "performance_index": index,
        "evaluated_at": store.now_iso(),
    }, force=True)
    return ok(trial)


@endpoint(bp, "POST", "/variety-trials/<trial_id>/certify", [BREEDER_ADMIN], [])
def certify_trial(actor, body, trial_id):
    trial = resolve("trial_id", trial_id)
    terminal(trial["status"] in TRIAL_TERMINAL)
    transition(trial["status"] == "EVALUATED")
    passed = (Decimal(trial["performance_index"]) >= PASS_INDEX_THRESHOLD
              and Decimal(trial["propagation_pass_rate"]) >= PASS_RATE_THRESHOLD)
    apply(trial, {"status": "PASSED" if passed else "FAILED"}, force=True)
    site = store.trial_sites[trial["trial_site_id"]]
    recompute_trial_site_occupancy(site, force=True)
    if passed:
        variety = store.varieties[trial["variety_id"]]
        region_count, index = variety_trial_aggregates(variety)
        updates = {
            "passed_trial_region_count": region_count,
            "regional_performance_index": index,
        }
        if region_count >= 2 and variety["lifecycle_state"] == "IN_TRIAL":
            updates["lifecycle_state"] = "TRIAL_COMPLETE"
        apply(variety, updates, force=True)
    return ok(trial)
