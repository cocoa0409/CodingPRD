"""Catalog routes: plants, mix designs, price lists, cement price indices,
customers, and the test-driving clock."""

from flask import Blueprint

import clock
import errors
import middleware as mw
import response
from db import stores
from services import calc

bp = Blueprint("catalog", __name__)

PM = ["PlantManager"]


def get_or_404(store, rid):
    rec = stores[store].get(rid)
    if rec is None:
        raise errors.err_not_found()
    return rec


# ------------------------------------------------------------------- plants

@bp.post("/v1/plants")
def create_plant():
    mw.require_auth(PM)
    body = mw.get_json_body()
    rec = mw.new_record()
    rec["name"] = mw.require_string(body, "name")
    rec["batch_cycle_minutes"] = mw.require_int(body, "batch_cycle_minutes")
    rec["daily_capacity_yd3"] = mw.require_number(body, "daily_capacity_yd3")
    rec["status"] = "ACTIVE"
    stores["plants"][rec["id"]] = rec
    return response.success_object(rec, 201)


@bp.get("/v1/plants/<rid>")
def get_plant(rid):
    mw.require_auth(mw.ALL_ROLES)
    return response.success_object(get_or_404("plants", rid))


# -------------------------------------------------------------- mix designs

@bp.post("/v1/mix-designs")
def create_mix_design():
    mw.require_auth(PM)
    body = mw.get_json_body()
    plant_id = mw.require_string(body, "plant_id")
    get_or_404("plants", plant_id)
    code = mw.require_string(body, "code")
    admixtures = body.get("admixtures")
    if admixtures is None:
        admixtures = []
    if not isinstance(admixtures, list):
        raise errors.err_validation("admixtures must be an array")
    for adm in admixtures:
        if not isinstance(adm, dict) or not isinstance(adm.get("admixture_code"), str) \
                or not mw.is_number(adm.get("dose_oz_per_cwt")):
            raise errors.err_validation(
                "admixtures entries must be {admixture_code, dose_oz_per_cwt}")
    for m in stores["mix_designs"].values():
        if m["plant_id"] == plant_id and m["code"] == code:
            raise errors.err_validation("Duplicate mix code for plant")
    rec = mw.new_record()
    rec["plant_id"] = plant_id
    rec["code"] = code
    rec["name"] = mw.require_string(body, "name")
    rec["design_strength_psi"] = mw.require_int(body, "design_strength_psi")
    rec["slump_in"] = mw.require_number(body, "slump_in")
    rec["cement_content_lb_per_yd3"] = mw.require_int(body, "cement_content_lb_per_yd3")
    rec["design_wc_ratio"] = mw.require_number(body, "design_wc_ratio")
    rec["max_wc_ratio"] = mw.require_number(body, "max_wc_ratio")
    rec["admixtures"] = admixtures
    rec["status"] = "DRAFT"
    stores["mix_designs"][rec["id"]] = rec
    return response.success_object(rec, 201)


@bp.get("/v1/mix-designs/<rid>")
def get_mix_design(rid):
    mw.require_auth(mw.ALL_ROLES)
    return response.success_object(get_or_404("mix_designs", rid))


@bp.get("/v1/mix-designs")
def list_mix_designs():
    mw.require_auth(mw.ALL_ROLES)
    limit, offset = mw.parse_pagination()
    items = list(stores["mix_designs"].values())
    plant_id = mw.optional_string(request_args(), "plant_id")
    status = mw.optional_string(request_args(), "status")
    if plant_id is not None:
        items = [m for m in items if m["plant_id"] == plant_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array(page, limit, offset, total)


@bp.post("/v1/mix-designs/<rid>/activate")
def activate_mix_design(rid):
    mw.require_auth(PM)
    rec = get_or_404("mix_designs", rid)
    if rec["status"] == "RETIRED":
        raise errors.err_already_terminal("RETIRED is terminal")
    if rec["status"] != "DRAFT":
        raise errors.err_invalid_state()
    rec["status"] = "ACTIVE"
    mw.touch(rec)
    return response.success_object(rec)


@bp.post("/v1/mix-designs/<rid>/retire")
def retire_mix_design(rid):
    mw.require_auth(PM)
    rec = get_or_404("mix_designs", rid)
    if rec["status"] == "RETIRED":
        raise errors.err_already_terminal("RETIRED is terminal")
    if rec["status"] != "ACTIVE":
        raise errors.err_invalid_state()
    rec["status"] = "RETIRED"
    mw.touch(rec)
    return response.success_object(rec)


# -------------------------------------------------------------- price lists

@bp.post("/v1/price-lists")
def create_price_list():
    mw.require_auth(PM)
    body = mw.get_json_body()
    plant_id = mw.require_string(body, "plant_id")
    plant = get_or_404("plants", plant_id)
    mix_design_id = mw.require_string(body, "mix_design_id")
    get_or_404("mix_designs", mix_design_id)
    expected_plant_version = mw.require_int(body, "expected_plant_version")
    rec = mw.new_record()
    rec["plant_id"] = plant_id
    rec["mix_design_id"] = mix_design_id
    rec["base_price_per_yd3_cents"] = mw.require_int(body, "base_price_per_yd3_cents")
    rec["escalation_base_index_points"] = mw.require_number(body, "escalation_base_index_points")
    rec["min_load_yd3"] = mw.require_number(body, "min_load_yd3")
    rec["short_load_fee_cents"] = mw.require_int(body, "short_load_fee_cents")
    rec["wait_free_minutes"] = mw.require_int(body, "wait_free_minutes")
    rec["wait_rate_per_minute_cents"] = mw.require_int(body, "wait_rate_per_minute_cents")
    rec["wait_fee_cap_cents"] = mw.require_int(body, "wait_fee_cap_cents")
    rec["saturday_surcharge_pct"] = mw.require_number(body, "saturday_surcharge_pct")
    activate = mw.optional_bool(body, "activate", False)
    if activate:
        if expected_plant_version != plant["version"]:
            raise errors.err_stale_version()
        for pl in stores["price_lists"].values():
            if pl["plant_id"] == plant_id and pl["mix_design_id"] == mix_design_id \
                    and pl["status"] == "ACTIVE":
                pl["status"] = "SUPERSEDED"
                mw.touch(pl)
        rec["status"] = "ACTIVE"
        rec["activated_at"] = clock.iso(clock.now())
        mw.touch(plant)
    else:
        rec["status"] = "DRAFT"
        rec["activated_at"] = None
    stores["price_lists"][rec["id"]] = rec
    return response.success_object(rec, 201)


@bp.get("/v1/price-lists/<rid>")
def get_price_list(rid):
    mw.require_auth(mw.ALL_ROLES)
    return response.success_object(get_or_404("price_lists", rid))


@bp.get("/v1/price-lists")
def list_price_lists():
    mw.require_auth(mw.ALL_ROLES)
    limit, offset = mw.parse_pagination()
    items = list(stores["price_lists"].values())
    plant_id = mw.optional_string(request_args(), "plant_id")
    mix_design_id = mw.optional_string(request_args(), "mix_design_id")
    status = mw.optional_string(request_args(), "status")
    if plant_id is not None:
        items = [p for p in items if p["plant_id"] == plant_id]
    if mix_design_id is not None:
        items = [p for p in items if p["mix_design_id"] == mix_design_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array(page, limit, offset, total)


# ------------------------------------------------------ cement price indices

@bp.post("/v1/cement-price-indices")
def create_cement_index():
    mw.require_auth(PM)
    body = mw.get_json_body()
    plant_id = mw.require_string(body, "plant_id")
    get_or_404("plants", plant_id)
    effective_month = mw.require_month(body, "effective_month")
    index_points = mw.require_number(body, "index_points")
    for idx in stores["cement_price_indices"].values():
        if idx["plant_id"] == plant_id and idx["effective_month"] == effective_month:
            raise errors.err_index_dup()
    rec = mw.new_record(common=False)
    rec["plant_id"] = plant_id
    rec["effective_month"] = effective_month
    rec["index_points"] = index_points
    stores["cement_price_indices"][rec["id"]] = rec
    return response.success_object(rec, 201)


@bp.get("/v1/cement-price-indices/<rid>")
def get_cement_index(rid):
    mw.require_auth(mw.ALL_ROLES)
    return response.success_object(get_or_404("cement_price_indices", rid))


@bp.get("/v1/cement-price-indices")
def list_cement_indices():
    mw.require_auth(mw.ALL_ROLES)
    limit, offset = mw.parse_pagination()
    items = list(stores["cement_price_indices"].values())
    plant_id = mw.optional_string(request_args(), "plant_id")
    effective_month = mw.optional_string(request_args(), "effective_month")
    if plant_id is not None:
        items = [i for i in items if i["plant_id"] == plant_id]
    if effective_month is not None:
        items = [i for i in items if i["effective_month"] == effective_month]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array(page, limit, offset, total)


# ---------------------------------------------------------------- customers

@bp.post("/v1/customers")
def create_customer():
    mw.require_auth(PM)
    body = mw.get_json_body()
    rec = mw.new_record()
    rec["name"] = mw.require_string(body, "name")
    rec["credit_limit_cents"] = mw.require_int(body, "credit_limit_cents")
    rec["short_load_allowed"] = mw.optional_bool(body, "short_load_allowed", True)
    rec["credit_status"] = "GOOD"
    rec["credit_exposure_cents"] = 0
    stores["customers"][rec["id"]] = rec
    return response.success_object(rec, 201)


@bp.get("/v1/customers/<rid>")
def get_customer(rid):
    mw.require_auth(mw.ALL_ROLES)
    return response.success_object(get_or_404("customers", rid))


@bp.post("/v1/customers/<rid>/credit-review")
def credit_review(rid):
    mw.require_auth(PM)
    rec = get_or_404("customers", rid)
    changed = calc.recompute_credit_exposure(rec)
    if changed:
        mw.touch(rec)
    return response.success_object(rec)


# -------------------------------------------------------------------- clock

@bp.post("/v1/_clock/set_current_utc")
def set_clock():
    mw.require_auth(PM)
    body = mw.get_json_body()
    to_iso8601 = mw.require_string(body, "to_iso8601")
    try:
        dt = clock.parse_iso(to_iso8601)
    except (ValueError, TypeError):
        raise errors.err_validation("to_iso8601 must be a valid ISO 8601 timestamp")
    clock.set_current(dt)
    return response.success_object({"current_utc": clock.iso(clock.now())})


def request_args():
    from flask import request
    return request.args
