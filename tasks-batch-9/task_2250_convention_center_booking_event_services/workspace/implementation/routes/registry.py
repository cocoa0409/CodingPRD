"""The venue registry: clients, spaces, policy windows, vendors, union locals (PRD 3.1)."""

from flask import Blueprint

import lookups
import validate
from db import db
from errors import err
from middleware import body, endpoint, filter_rows, require_owner, touch
from response import entity_response
from routes.common import (
    EVENT_CLASSES,
    ORGANIZATION_TYPES,
    SERVICE_CATEGORIES,
    SPACE_CLASSES,
    VENDOR_CATEGORIES,
    VENDOR_TIERS,
    body_fk,
    listing,
)

bp = Blueprint("registry", __name__)


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------
@bp.post("/clients")
@endpoint("VenueAdmin", "SalesManager")
def create_client():
    payload = body()
    record = db.insert(
        "client",
        {
            "legal_name": validate.req_string(payload, "legal_name"),
            "contact_email": validate.req_string(payload, "contact_email"),
            "organization_type": validate.req_enum(payload, "organization_type", ORGANIZATION_TYPES),
            "total_deposits_paid_cents": 0,
            "credit_balance_cents": 0,
            "outstanding_balance_cents": 0,
            "booking_standing": "GOOD",
        },
    )
    return entity_response(record, 201)


@bp.get("/clients")
@endpoint("VenueAdmin", "SalesManager", "SettlementAnalyst")
def list_clients():
    rows = filter_rows(
        "client",
        {"organization_type": "organization_type", "booking_standing": "booking_standing"},
    )
    return listing(rows)


@bp.get("/clients/<client_id>")
@endpoint("VenueAdmin", "SalesManager", "SettlementAnalyst", "Licensee")
def read_client(client_id):
    return entity_response(lookups.fetch("client", client_id))


@bp.post("/clients/<client_id>/deposits")
@endpoint("VenueAdmin", "SettlementAnalyst", "Licensee")
def record_deposit(client_id):
    client = lookups.fetch("client", client_id)
    require_owner(client["id"])
    payload = body()
    amount = validate.req_int(payload, "amount_cents", minimum=1)
    client["total_deposits_paid_cents"] += amount
    client["credit_balance_cents"] += amount
    touch(client)
    return entity_response(client)


# --------------------------------------------------------------------------
# SpaceUnit
# --------------------------------------------------------------------------
@bp.post("/spaces")
@endpoint("VenueAdmin", "FacilitiesPlanner")
def create_space():
    payload = body()
    fields = {
        "name": validate.req_string(payload, "name"),
        "space_class": validate.req_enum(payload, "space_class", SPACE_CLASSES),
        "rentable_sqft": validate.req_int(payload, "rentable_sqft", minimum=0),
        "daily_base_rate_cents": validate.req_int(payload, "daily_base_rate_cents", minimum=0),
        "rigging_capable": validate.opt_bool(payload, "rigging_capable", False),
        "committed_space_days": 0,
        "active_blackout_count": 0,
    }
    parent = body_fk(payload, "parent_space_id", "space", required=False)
    fields["parent_space_id"] = parent["id"] if parent is not None else None
    return entity_response(db.insert("space", fields), 201)


@bp.get("/spaces")
@endpoint("VenueAdmin", "FacilitiesPlanner", "SalesManager", "EventServicesManager")
def list_spaces():
    rows = filter_rows(
        "space", {"parent_space_id": "parent_space_id", "space_class": "space_class"}
    )
    return listing(rows)


@bp.get("/spaces/<space_id>")
@endpoint("VenueAdmin", "FacilitiesPlanner", "SalesManager", "EventServicesManager")
def read_space(space_id):
    return entity_response(lookups.fetch("space", space_id))


# --------------------------------------------------------------------------
# BookingPolicyWindow
# --------------------------------------------------------------------------
@bp.post("/policy-windows")
@endpoint("VenueAdmin")
def create_policy_window():
    payload = body()
    event_class = validate.req_enum(payload, "event_class", EVENT_CLASSES)
    fields = {
        "event_class": event_class,
        "priority_rank": validate.req_int(payload, "priority_rank"),
        "open_months_before": validate.req_int(payload, "open_months_before"),
        "close_months_before": validate.req_int(payload, "close_months_before"),
        "max_holds_per_booking": validate.req_int(payload, "max_holds_per_booking", minimum=0),
        "challenge_response_hours": validate.req_int(payload, "challenge_response_hours", minimum=0),
        "rental_discount_pct": validate.req_number(
            payload, "rental_discount_pct", minimum=0, exclusive_max=1
        ),
        "max_challenge_rounds": validate.req_int(payload, "max_challenge_rounds", minimum=0),
    }
    if lookups.policy_window_for_class(event_class) is not None:
        raise err("ERR_POLICY_WINDOW_EXISTS")
    return entity_response(db.insert("policy_window", fields), 201)


@bp.get("/policy-windows")
@endpoint("VenueAdmin", "SalesManager", "EventServicesManager", "SettlementAnalyst")
def list_policy_windows():
    return listing(filter_rows("policy_window", {"event_class": "event_class"}))


@bp.get("/policy-windows/<window_id>")
@endpoint("VenueAdmin", "SalesManager", "EventServicesManager", "SettlementAnalyst")
def read_policy_window(window_id):
    return entity_response(lookups.fetch("policy_window", window_id))


# --------------------------------------------------------------------------
# Vendor
# --------------------------------------------------------------------------
@bp.post("/vendors")
@endpoint("VenueAdmin", "EventServicesManager")
def create_vendor():
    payload = body()
    fields = {
        "legal_name": validate.req_string(payload, "legal_name"),
        "service_category": validate.req_enum(payload, "service_category", VENDOR_CATEGORIES),
        "vendor_tier": validate.req_enum(payload, "vendor_tier", VENDOR_TIERS),
        "coi_expiry_date": validate.req_date(payload, "coi_expiry_date").isoformat(),
        "is_in_house_caterer": validate.opt_bool(payload, "is_in_house_caterer", False),
    }
    return entity_response(db.insert("vendor", fields), 201)


@bp.get("/vendors")
@endpoint("VenueAdmin", "EventServicesManager", "SalesManager")
def list_vendors():
    rows = filter_rows(
        "vendor", {"service_category": "service_category", "vendor_tier": "vendor_tier"}
    )
    return listing(rows)


@bp.get("/vendors/<vendor_id>")
@endpoint("VenueAdmin", "EventServicesManager", "SalesManager")
def read_vendor(vendor_id):
    return entity_response(lookups.fetch("vendor", vendor_id))


# --------------------------------------------------------------------------
# UnionJurisdiction
# --------------------------------------------------------------------------
@bp.post("/union-jurisdictions")
@endpoint("VenueAdmin")
def create_jurisdiction():
    payload = body()
    fields = {
        "craft_name": validate.req_string(payload, "craft_name"),
        "covered_category": validate.req_enum(payload, "covered_category", SERVICE_CATEGORIES),
        "straight_time_rate_cents": validate.req_int(
            payload, "straight_time_rate_cents", minimum=0
        ),
        "max_crew_hours_per_day": validate.req_number(payload, "max_crew_hours_per_day", minimum=0),
        "overtime_multiplier": validate.opt_number(payload, "overtime_multiplier", 1.5, minimum=0),
        "min_call_hours": validate.opt_number(payload, "min_call_hours", 4, minimum=0),
        "st_window_start_hour": validate.opt_int(
            payload, "st_window_start_hour", 8, minimum=0, maximum=24
        ),
        "st_window_end_hour": validate.opt_int(
            payload, "st_window_end_hour", 17, minimum=0, maximum=24
        ),
        "lockout_active": validate.opt_bool(payload, "lockout_active", False),
        "committed_crew_hours": 0,
    }
    return entity_response(db.insert("jurisdiction", fields), 201)


@bp.get("/union-jurisdictions")
@endpoint("VenueAdmin", "EventServicesManager")
def list_jurisdictions():
    return listing(filter_rows("jurisdiction", {"covered_category": "covered_category"}))


@bp.get("/union-jurisdictions/<jurisdiction_id>")
@endpoint("VenueAdmin", "EventServicesManager")
def read_jurisdiction(jurisdiction_id):
    return entity_response(lookups.fetch("jurisdiction", jurisdiction_id))


@bp.patch("/union-jurisdictions/<jurisdiction_id>")
@endpoint("VenueAdmin")
def update_jurisdiction(jurisdiction_id):
    jurisdiction = lookups.fetch("jurisdiction", jurisdiction_id)
    payload = body()
    lockout = validate.opt_bool(payload, "lockout_active", None)
    capacity = validate.opt_number(payload, "max_crew_hours_per_day", None, minimum=0)
    if lockout is not None:
        jurisdiction["lockout_active"] = lockout
    if capacity is not None:
        jurisdiction["max_crew_hours_per_day"] = capacity
    touch(jurisdiction)
    return entity_response(jurisdiction)
