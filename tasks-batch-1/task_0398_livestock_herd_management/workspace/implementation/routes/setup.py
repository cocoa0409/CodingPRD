"""Herd, Pasture, DrugProduct, FeedRation setup endpoints, plus the clock."""
from flask import Blueprint

import errors
from db import db
from clock import clock
from middleware import authenticate, require_role
from response import object_response
from util import (get_json_body, as_str, as_enum, as_number, as_int,
                  datetime_field)
from services.common import base_record, get_or_404, touch
from services import serializers as S
from services.domain import (recompute_mortality_rate, rederive_clearance_for_animal,
                             active_withholding_treatments)

bp = Blueprint("setup", __name__)

SPECIES = {"CATTLE", "SHEEP", "GOAT"}
PASTURE_KINDS = {"PASTURE", "PEN"}
DRUG_CATEGORIES = {"VACCINE", "ANTIBIOTIC", "ANTIPARASITIC", "HORMONE"}
ROUTES = {"INJECTION_IM", "INJECTION_SC", "ORAL", "TOPICAL_POUR_ON", "INTRAMAMMARY"}
ALL_ROLES = {"HerdManager", "Veterinarian", "SaleClerk", "FeedlotOperator", "Auditor"}


# ---------------------------------------------------------------- Herd
@bp.route("/herds", methods=["POST"])
def create_herd():
    role = authenticate()
    require_role(role, {"HerdManager"})
    body = get_json_body()
    name = as_str(body, "name", min_len=1, max_len=120)
    species = as_enum(body, "species", SPECIES)
    premises_id = as_str(body, "premises_id", min_len=1, max_len=40)

    # premises_id unique across Herd
    for h in db.herds.values():
        if h["premises_id"] == premises_id:
            raise errors.invalid_request("premises_id must be unique across herds")

    rec = base_record()
    rec.update({
        "name": name,
        "species": species,
        "premises_id": premises_id,
        "active_animal_count": 0,
        "total_au_load": 0.0,
        "mortality_rate_pct": 0.0,
    })
    db.herds[rec["id"]] = rec
    return object_response(S.herd_out(rec), 201)


@bp.route("/herds/<hid>", methods=["GET"])
def get_herd(hid):
    role = authenticate()
    require_role(role, ALL_ROLES)
    h = get_or_404(db.herds, hid)
    # recompute mortality rate over the trailing window on read
    recompute_mortality_rate(h)
    return object_response(S.herd_out(h), 200)


# ---------------------------------------------------------------- Pasture
@bp.route("/pastures", methods=["POST"])
def create_pasture():
    role = authenticate()
    require_role(role, {"HerdManager"})
    body = get_json_body()
    name = as_str(body, "name", min_len=1, max_len=80)
    kind = as_enum(body, "kind", PASTURE_KINDS)
    capacity_au = as_number(body, "capacity_au", gt=0)
    rest_days = as_int(body, "rest_days", required=False, default=0, ge=0)

    rec = base_record()
    rec.update({
        "name": name,
        "kind": kind,
        "capacity_au": capacity_au,
        "rest_days": rest_days,
        "current_au_load": 0.0,
    })
    db.pastures[rec["id"]] = rec
    return object_response(S.pasture_out(rec), 201)


@bp.route("/pastures/<pid>", methods=["GET"])
def get_pasture(pid):
    role = authenticate()
    require_role(role, ALL_ROLES)
    p = get_or_404(db.pastures, pid)
    return object_response(S.pasture_out(p), 200)


# ---------------------------------------------------------------- DrugProduct
@bp.route("/drug-products", methods=["POST"])
def create_drug_product():
    role = authenticate()
    require_role(role, {"Veterinarian"})
    body = get_json_body()
    name = as_str(body, "name", min_len=1, max_len=120)
    category = as_enum(body, "category", DRUG_CATEGORIES)

    if "route_withdrawals" not in body or body["route_withdrawals"] is None:
        raise errors.invalid_request("Missing required field: route_withdrawals")
    rw = body["route_withdrawals"]
    if not isinstance(rw, dict) or len(rw) == 0:
        raise errors.invalid_request("route_withdrawals must be a non-empty object")
    for k, v in rw.items():
        if k not in ROUTES:
            raise errors.invalid_request("Unknown route key: %s" % k)
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise errors.invalid_request("route_withdrawals values must be non-negative integers")

    milk = as_int(body, "milk_withdrawal_hours", required=False, default=0, ge=0)

    rec = base_record()
    rec.update({
        "name": name,
        "category": category,
        "route_withdrawals": dict(rw),
        "milk_withdrawal_hours": milk,
    })
    db.drug_products[rec["id"]] = rec
    return object_response(S.drug_product_out(rec), 201)


# ---------------------------------------------------------------- FeedRation
@bp.route("/feed-rations", methods=["POST"])
def create_feed_ration():
    role = authenticate()
    require_role(role, {"FeedlotOperator"})
    body = get_json_body()
    name = as_str(body, "name", min_len=1, max_len=80)
    target_dmi = as_number(body, "target_dmi_kg", gt=0)

    if "ingredients" not in body or body["ingredients"] is None:
        raise errors.invalid_request("Missing required field: ingredients")
    ings = body["ingredients"]
    if not isinstance(ings, list) or len(ings) < 1:
        raise errors.invalid_request("ingredients must be a non-empty array")
    norm = []
    for ing in ings:
        if not isinstance(ing, dict):
            raise errors.invalid_request("each ingredient must be an object")
        feedstuff = as_str(ing, "feedstuff", min_len=1)
        dm = as_number(ing, "dry_matter_pct", gt=0, le=1)
        maxinc = as_number(ing, "max_inclusion_pct", gt=0, le=1)
        cost = as_number(ing, "cost_per_kg_as_fed", ge=0)
        norm.append({
            "feedstuff": feedstuff,
            "dry_matter_pct": dm,
            "max_inclusion_pct": maxinc,
            "cost_per_kg_as_fed": cost,
        })

    rec = base_record()
    rec.update({
        "name": name,
        "target_dmi_kg": target_dmi,
        "ingredients": norm,
        "status": "ACTIVE",
    })
    db.feed_rations[rec["id"]] = rec
    return object_response(S.feed_ration_out(rec), 201)


@bp.route("/feed-rations/<fid>/computed-ration", methods=["GET"])
def computed_ration(fid):
    role = authenticate()
    require_role(role, {"FeedlotOperator", "HerdManager", "Auditor"})
    f = get_or_404(db.feed_rations, fid)
    from services.ration import compute_ration
    result = compute_ration(f)
    return object_response(result, 200)


# ---------------------------------------------------------------- Clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role = authenticate()
    require_role(role, {"HerdManager", "Veterinarian", "SaleClerk", "FeedlotOperator"})
    body = get_json_body()
    new_dt = datetime_field(body, "to_iso8601", required=True)
    clock.set(new_dt)

    # Re-derive residue state: auto-transition WITHDRAWAL_ACTIVE treatments whose
    # clearance_date <= clock date to CLEARED, then re-derive each animal's
    # meat_clearance_status / meat_clear_on.
    today = clock.today()
    for t in db.health_treatments.values():
        if t["status"] == "WITHDRAWAL_ACTIVE" and t["clearance_date"] is not None \
                and today >= t["clearance_date"]:
            t["status"] = "CLEARED"
            touch(t)
    for a in db.animals.values():
        if rederive_clearance_for_animal(a):
            touch(a)

    from util import iso_datetime
    return object_response({"current_utc": iso_datetime(new_dt)}, 200)
