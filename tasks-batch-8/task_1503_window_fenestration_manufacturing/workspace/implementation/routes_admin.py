"""Routes: logical clock, dealers, catalog series, glass packages, energy code rules."""
from flask import Blueprint

from common import (ANY_ROLE, ApiError, body_json, err400, fmt_dt, list_response, need,
                    obj_response, paginate, parse_dt, require_roles, v_dt, v_enum, v_int,
                    v_num, v_str)
from services import (FRAME_MATERIALS, SPACER_TYPES, get_or_404, ser_dealer, ser_glass,
                      ser_rule, ser_series)
from store import STORE, new_entity, set_clock, touch

bp_admin = Blueprint("admin", __name__)


# ------------------------------------------------------------------ clock

@bp_admin.post("/_clock/set_current_utc")
@require_roles("PlantManager")
def set_clock_endpoint():
    body = body_json()
    dt = v_dt(need(body, "to_iso8601"), "to_iso8601")
    set_clock(dt)
    return obj_response({"current_utc": fmt_dt(dt)}, 200)


# ------------------------------------------------------------------ dealers

@bp_admin.post("/fenestration/dealers")
@require_roles("PlantManager")
def create_dealer():
    body = body_json()
    name = v_str(need(body, "name"), "name")
    state = v_str(need(body, "ship_to_state_code"), "ship_to_state_code")
    d = new_entity({"name": name, "ship_to_state_code": state, "credit_status": "ACTIVE"})
    STORE.dealers[d["id"]] = d
    return obj_response(ser_dealer(d), 201)


@bp_admin.get("/fenestration/dealers/<dealerId>")
@require_roles(*ANY_ROLE)
def get_dealer(dealerId):
    return obj_response(ser_dealer(get_or_404(STORE.dealers, dealerId)), 200)


@bp_admin.post("/fenestration/dealers/<dealerId>/credit-hold")
@require_roles("PlantManager")
def dealer_credit_hold(dealerId):
    d = get_or_404(STORE.dealers, dealerId)
    if d["credit_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Dealer is not ACTIVE")
    d["credit_status"] = "CREDIT_HOLD"
    touch(d)
    return obj_response(ser_dealer(d), 200)


@bp_admin.post("/fenestration/dealers/<dealerId>/credit-release")
@require_roles("PlantManager")
def dealer_credit_release(dealerId):
    d = get_or_404(STORE.dealers, dealerId)
    if d["credit_status"] != "CREDIT_HOLD":
        raise ApiError("ERR_INVALID_STATE", 409, "Dealer is not on CREDIT_HOLD")
    d["credit_status"] = "ACTIVE"
    touch(d)
    return obj_response(ser_dealer(d), 200)


# ------------------------------------------------------------------ catalog series

@bp_admin.post("/fenestration/catalog-series")
@require_roles("PlantEngineer", "PlantManager")
def create_series():
    body = body_json()
    s = new_entity({
        "series_code": v_str(need(body, "series_code"), "series_code"),
        "frame_material": v_enum(need(body, "frame_material"), "frame_material", FRAME_MATERIALS),
        "base_rate_cents_per_ui": v_int(need(body, "base_rate_cents_per_ui"), "base_rate_cents_per_ui"),
        "min_billable_sqft": v_num(need(body, "min_billable_sqft"), "min_billable_sqft"),
        "max_united_inches": v_int(need(body, "max_united_inches"), "max_united_inches"),
        "special_shape_upcharge_pct": v_int(need(body, "special_shape_upcharge_pct"), "special_shape_upcharge_pct"),
        "lead_time_standard_days": v_int(need(body, "lead_time_standard_days"), "lead_time_standard_days"),
        "lead_time_special_shape_days": v_int(need(body, "lead_time_special_shape_days"), "lead_time_special_shape_days"),
        "frame_warranty_years": v_int(need(body, "frame_warranty_years"), "frame_warranty_years"),
        "status": "ACTIVE",
    })
    STORE.series[s["id"]] = s
    return obj_response(ser_series(s), 201)


@bp_admin.get("/fenestration/catalog-series/<seriesId>")
@require_roles(*ANY_ROLE)
def get_series(seriesId):
    return obj_response(ser_series(get_or_404(STORE.series, seriesId)), 200)


@bp_admin.post("/fenestration/catalog-series/<seriesId>/discontinue")
@require_roles("PlantEngineer", "PlantManager")
def discontinue_series(seriesId):
    s = get_or_404(STORE.series, seriesId)
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Series is not ACTIVE")
    s["status"] = "DISCONTINUED"
    touch(s)
    return obj_response(ser_series(s), 200)


# ------------------------------------------------------------------ glass packages

@bp_admin.post("/fenestration/glass-packages")
@require_roles("PlantEngineer", "PlantManager")
def create_glass_package():
    body = body_json()
    pane_count = v_int(need(body, "pane_count"), "pane_count")
    if pane_count not in (2, 3):
        err400("pane_count must be 2 or 3")
    gp = new_entity({
        "code": v_str(need(body, "code"), "code"),
        "pane_count": pane_count,
        "spacer_type": v_enum(need(body, "spacer_type"), "spacer_type", SPACER_TYPES),
        "argon_target_pct": v_int(need(body, "argon_target_pct"), "argon_target_pct"),
        "argon_min_pct": v_int(need(body, "argon_min_pct"), "argon_min_pct"),
        "catalog_u_factor": v_num(need(body, "catalog_u_factor"), "catalog_u_factor"),
        "catalog_shgc": v_num(need(body, "catalog_shgc"), "catalog_shgc"),
        "price_per_sqft_cents": v_int(need(body, "price_per_sqft_cents"), "price_per_sqft_cents"),
        "ig_warranty_years": v_int(need(body, "ig_warranty_years"), "ig_warranty_years"),
    })
    STORE.glass_packages[gp["id"]] = gp
    return obj_response(ser_glass(gp), 201)


@bp_admin.get("/fenestration/glass-packages/<glassPackageId>")
@require_roles(*ANY_ROLE)
def get_glass_package(glassPackageId):
    return obj_response(ser_glass(get_or_404(STORE.glass_packages, glassPackageId)), 200)


# ------------------------------------------------------------------ energy code rules

@bp_admin.post("/fenestration/energy-code-rules")
@require_roles("PlantEngineer", "PlantManager")
def create_energy_rule():
    body = body_json()
    state_code = v_str(need(body, "state_code"), "state_code")
    max_u = v_num(need(body, "max_u_factor"), "max_u_factor")
    max_shgc = v_num(need(body, "max_shgc"), "max_shgc")
    eff_from = v_dt(need(body, "effective_from"), "effective_from")
    eff_to = None
    if "effective_to" in body and body["effective_to"] is not None:
        eff_to = v_dt(body["effective_to"], "effective_to")
    # Half-open windows per state must not overlap; adjacency allowed.
    for r in STORE.energy_rules.values():
        if r["state_code"] != state_code:
            continue
        r_to = r["effective_to"]
        overlap = (eff_from < r_to if r_to is not None else True) and \
                  (r["effective_from"] < eff_to if eff_to is not None else True)
        if overlap:
            raise ApiError("ERR_ENERGY_RULE_WINDOW_OVERLAP", 409,
                           "Energy code rule window overlaps an existing rule for this state")
    rule = new_entity({
        "state_code": state_code, "max_u_factor": max_u, "max_shgc": max_shgc,
        "effective_from": eff_from, "effective_to": eff_to,
    })
    STORE.energy_rules[rule["id"]] = rule
    return obj_response(ser_rule(rule), 201)


@bp_admin.get("/fenestration/energy-code-rules/<ruleId>")
@require_roles(*ANY_ROLE)
def get_energy_rule(ruleId):
    return obj_response(ser_rule(get_or_404(STORE.energy_rules, ruleId)), 200)
