"""Variety registration, the release ladder and the brand dimension."""

from decimal import Decimal

from flask import Blueprint

from common import (filtered, resolve, terminal, transition)
from derive import (apply, close_quota_and_void_requests, ordered_children)
from errors import ApiError
from middleware import BREEDER_ADMIN, ALL_ROLES, endpoint
from response import collection, created, ok
from store import new_id, parse_dt, store
from validation import DateTime, Enum, Int, Str, UPPER_2_12

bp = Blueprint("varieties", __name__)

CREATE_SCHEMA = [
    ("denomination", Str(1, 80), True),
    ("species", Str(1, 60), True),
    ("breeder_code", UPPER_2_12, True),
    ("royalty_basis_default", Enum(["PER_PLANT", "PER_ACRE"]), False),
    ("base_royalty_cents_per_plant", Int(1), True),
    ("base_royalty_cents_per_acre", Int(1), True),
]

BRAND_REGISTER_SCHEMA = [
    ("brand_mark_text", Str(1, 60), True),
    ("brand_registry_class", Int(1, 45), True),
    ("brand_renewal_due_at", DateTime(), True),
]

BRAND_RENEW_SCHEMA = [
    ("brand_mark_text", Str(1, 60), True),
    ("brand_renewal_due_at", DateTime(), True),
]

LIFECYCLE_TERMINAL = "RETIRED"
BRAND_TERMINAL = "BRAND_ABANDONED"


def norm(text):
    return (text or "").strip().casefold()


def brand_conflict(variety, mark_text):
    """The deliberately broad three-way separation check (PRD 3.3)."""
    target = norm(mark_text)
    if target == norm(variety["denomination"]):
        return True
    for other in store.varieties.values():
        if other["id"] == variety["id"]:
            continue
        if target == norm(other["denomination"]):
            return True
        if other["brand_mark_text"] and target == norm(other["brand_mark_text"]):
            return True
    return False


@endpoint(bp, "POST", "/varieties", [BREEDER_ADMIN], CREATE_SCHEMA)
def create_variety(actor, body):
    for other in store.varieties.values():
        if norm(other["denomination"]) == norm(body["denomination"]):
            raise ApiError("ERR_DUPLICATE_DENOMINATION")
    record = {
        "id": new_id(),
        "denomination": body["denomination"],
        "species": body["species"],
        "breeder_code": body["breeder_code"],
        "lifecycle_state": "CANDIDATE",
        "brand_status": "BRAND_NONE",
        "brand_mark_text": None,
        "brand_registry_class": None,
        "brand_registered_on": None,
        "brand_renewal_due_at": None,
        "brand_renewal_count": 0,
        "protection_posture": "UNPROTECTED",
        "protected_jurisdictions": [],
        "royalty_basis_default": body["royalty_basis_default"] or "PER_PLANT",
        "base_royalty_cents_per_plant": body["base_royalty_cents_per_plant"],
        "base_royalty_cents_per_acre": body["base_royalty_cents_per_acre"],
        "regional_performance_index": Decimal("0.00"),
        "passed_trial_region_count": 0,
        "active_sublicense_count": 0,
        "released_at": None,
    }
    store.stamp_new(record)
    store.varieties[record["id"]] = record
    return created(record)


@endpoint(bp, "GET", "/varieties", ALL_ROLES)
def list_varieties(actor):
    records, limit, offset, total = filtered(
        "varieties", "species", "lifecycle_state", "protection_posture")
    return collection(records, limit, offset, total)


@endpoint(bp, "GET", "/varieties/<variety_id>", ALL_ROLES)
def get_variety(actor, variety_id):
    return ok(resolve("variety_id", variety_id))


@endpoint(bp, "POST", "/varieties/<variety_id>/release", [BREEDER_ADMIN], [])
def release_variety(actor, body, variety_id):
    variety = resolve("variety_id", variety_id)
    terminal(variety["lifecycle_state"] == LIFECYCLE_TERMINAL)
    transition(variety["lifecycle_state"] == "TRIAL_COMPLETE")
    if (int(variety["passed_trial_region_count"]) < 2
            or Decimal(variety["regional_performance_index"]) < Decimal("72.00")
            or variety["protection_posture"] not in ("PENDING", "PROTECTED")):
        raise ApiError("ERR_RELEASE_CRITERIA_NOT_MET")
    apply(variety, {
        "lifecycle_state": "RELEASED",
        "released_at": store.now_iso(),
    }, force=True)
    return ok(variety)


@endpoint(bp, "POST", "/varieties/<variety_id>/retire", [BREEDER_ADMIN], [])
def retire_variety(actor, body, variety_id):
    variety = resolve("variety_id", variety_id)
    terminal(variety["lifecycle_state"] == LIFECYCLE_TERMINAL)
    transition(variety["lifecycle_state"] == "RELEASED")
    if int(variety["active_sublicense_count"]) > 0:
        raise ApiError("ERR_ACTIVE_SUBLICENSES_EXIST")
    apply(variety, {"lifecycle_state": "RETIRED"}, force=True)
    quotas = ordered_children("quotas", "variety_id", variety["id"],
                              lambda q: q["season_code"])
    for quota in quotas:
        if quota["status"] in ("ACTIVE", "FROZEN"):
            close_quota_and_void_requests(quota)
    return ok(variety)


@endpoint(bp, "POST", "/varieties/<variety_id>/brand-register", [BREEDER_ADMIN],
          BRAND_REGISTER_SCHEMA)
def brand_register(actor, body, variety_id):
    variety = resolve("variety_id", variety_id)
    terminal(variety["brand_status"] == BRAND_TERMINAL)
    transition(variety["brand_status"] == "BRAND_NONE")
    if brand_conflict(variety, body["brand_mark_text"]):
        raise ApiError("ERR_BRAND_CONFLICTS_DENOMINATION")
    if parse_dt(body["brand_renewal_due_at"]) <= store.now:
        raise ApiError("ERR_INVALID_INTERVAL")
    apply(variety, {
        "brand_status": "BRAND_REGISTERED",
        "brand_mark_text": body["brand_mark_text"],
        "brand_registry_class": body["brand_registry_class"],
        "brand_renewal_due_at": body["brand_renewal_due_at"],
        "brand_registered_on": store.now_iso(),
    }, force=True)
    return ok(variety)


@endpoint(bp, "POST", "/varieties/<variety_id>/brand-renew", [BREEDER_ADMIN],
          BRAND_RENEW_SCHEMA)
def brand_renew(actor, body, variety_id):
    variety = resolve("variety_id", variety_id)
    terminal(variety["brand_status"] == BRAND_TERMINAL)
    transition(variety["brand_status"] == "BRAND_RENEWAL_DUE")
    if brand_conflict(variety, body["brand_mark_text"]):
        raise ApiError("ERR_BRAND_CONFLICTS_DENOMINATION")
    if parse_dt(body["brand_renewal_due_at"]) <= store.now:
        raise ApiError("ERR_INVALID_INTERVAL")
    apply(variety, {
        "brand_status": "BRAND_REGISTERED",
        "brand_mark_text": body["brand_mark_text"],
        "brand_renewal_due_at": body["brand_renewal_due_at"],
        "brand_registered_on": store.now_iso(),
        "brand_renewal_count": int(variety["brand_renewal_count"]) + 1,
    }, force=True)
    return ok(variety)


@endpoint(bp, "POST", "/varieties/<variety_id>/brand-abandon", [BREEDER_ADMIN], [])
def brand_abandon(actor, body, variety_id):
    variety = resolve("variety_id", variety_id)
    terminal(variety["brand_status"] == BRAND_TERMINAL)
    transition(variety["brand_status"] in ("BRAND_REGISTERED", "BRAND_RENEWAL_DUE"))
    apply(variety, {"brand_status": "BRAND_ABANDONED"}, force=True)
    return ok(variety)
