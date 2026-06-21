"""Reference catalogs: service-addresses, service-plans, technicians (PRD §3.1)."""
from flask import Blueprint, request

import db
from db import touch
from errors import err
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.helpers import (get_json_body, lookup, require_fields,
                              require_positive_int, require_int, require_enum,
                              paginate, sorted_by_created)
from services.serialize import public, public_list

bp = Blueprint("catalogs", __name__)

COVERAGE = {"SERVICEABLE", "NOT_SERVICEABLE", "PRE_ORDER"}
TECHNOLOGY = {"FIBER", "CABLE", "DSL", "FIXED_WIRELESS"}
TIER = {"BASIC", "PLUS", "GIG", "MULTI_GIG"}
OVERAGE_POLICY = {"BILL", "THROTTLE", "UNLIMITED"}


# --- ServiceAddress ---

@bp.route("/service-addresses", methods=["POST"])
def create_service_address():
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent", "NetworkOps"})
    body = get_json_body()
    require_fields(body, ["line1", "postal_code", "coverage_status",
                          "technology", "max_serviceable_mbps",
                          "self_install_eligible"])
    coverage = require_enum(body, "coverage_status", COVERAGE)
    technology = require_enum(body, "technology", TECHNOLOGY)
    max_mbps = require_int(body, "max_serviceable_mbps")
    if not isinstance(body["line1"], str) or not isinstance(body["postal_code"], str):
        err("ERR_INVALID_REQUEST", "line1 and postal_code must be strings.")
    if not isinstance(body["self_install_eligible"], bool):
        err("ERR_INVALID_REQUEST", "self_install_eligible must be a boolean.")
    rec = db.make_record({
        "line1": body["line1"],
        "postal_code": body["postal_code"],
        "coverage_status": coverage,
        "technology": technology,
        "max_serviceable_mbps": max_mbps,
        "self_install_eligible": body["self_install_eligible"],
    }, versioned=db.LEAN)
    db.service_addresses[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.route("/service-addresses/<rid>", methods=["GET"])
def get_service_address(rid):
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps", "Dispatcher"})
    rec = lookup(db.service_addresses, rid)
    return object_response(public(rec), 200)


@bp.route("/service-addresses/<rid>/serviceability", methods=["GET"])
def serviceability(rid):
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps", "Dispatcher"})
    rec = lookup(db.service_addresses, rid)
    return object_response(public(rec), 200)


# --- ServicePlan ---

@bp.route("/service-plans", methods=["POST"])
def create_service_plan():
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent", "NetworkOps"})
    body = get_json_body()
    require_fields(body, ["code", "tier", "download_mbps", "throttled_mbps",
                          "monthly_fee_cents", "included_gb", "overage_policy",
                          "contract_term_months", "etf_full_cents"])
    if not isinstance(body["code"], str) or body["code"] == "":
        err("ERR_INVALID_REQUEST", "code must be a non-empty string.")
    tier = require_enum(body, "tier", TIER)
    policy = require_enum(body, "overage_policy", OVERAGE_POLICY)
    download = require_int(body, "download_mbps")
    throttled = require_int(body, "throttled_mbps")
    monthly = require_int(body, "monthly_fee_cents")
    included = require_int(body, "included_gb")
    term = require_int(body, "contract_term_months")
    etf = require_int(body, "etf_full_cents")
    # Uniqueness on code (PRD §2.10).
    for p in db.service_plans.values():
        if p["code"] == body["code"]:
            err("ERR_DUPLICATE_PLAN_CODE", "ServicePlan code already in use.")
    rec = db.make_record({
        "code": body["code"],
        "tier": tier,
        "download_mbps": download,
        "throttled_mbps": throttled,
        "monthly_fee_cents": monthly,
        "included_gb": included,
        "overage_policy": policy,
        "contract_term_months": term,
        "etf_full_cents": etf,
    }, versioned=db.LEAN)
    db.service_plans[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.route("/service-plans/<rid>", methods=["GET"])
def get_service_plan(rid):
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps", "Dispatcher"})
    rec = lookup(db.service_plans, rid)
    return object_response(public(rec), 200)


# --- Technician ---

@bp.route("/technicians", methods=["POST"])
def create_technician():
    _uid, role = get_user_context()
    require_role(role, {"Dispatcher"})
    body = get_json_body()
    require_fields(body, ["name"])
    if not isinstance(body["name"], str) or body["name"] == "":
        err("ERR_INVALID_REQUEST", "name must be a non-empty string.")
    travel_buffer = 30
    if "travel_buffer_minutes" in body and body["travel_buffer_minutes"] is not None:
        travel_buffer = require_int(body, "travel_buffer_minutes")
    active = True
    if "active" in body and body["active"] is not None:
        if not isinstance(body["active"], bool):
            err("ERR_INVALID_REQUEST", "active must be a boolean.")
        active = body["active"]
    rec = db.make_record({
        "name": body["name"],
        "travel_buffer_minutes": travel_buffer,
        "active": active,
    }, versioned=db.VERSIONED)
    db.technicians[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.route("/technicians/<rid>", methods=["GET"])
def get_technician(rid):
    _uid, role = get_user_context()
    require_role(role, {"Dispatcher", "ProvisioningAgent", "NetworkOps"})
    rec = lookup(db.technicians, rid)
    return object_response(public(rec), 200)
