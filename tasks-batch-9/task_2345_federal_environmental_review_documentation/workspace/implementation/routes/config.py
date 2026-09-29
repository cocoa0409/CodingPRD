"""Review offices, agencies and the logical clock (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import db
import response
import validation as v
from errors import fail, invalid
from middleware import endpoint

bp = Blueprint("config", __name__)

ALL_ROLES = (
    "PolicyAdmin",
    "NepaCoordinator",
    "ResourceSpecialist",
    "ReviewingOfficial",
    "AgencyLiaison",
    "DecidingOfficial",
    "ObjectionReviewingOfficer",
    "PublicCommenter",
)

OFFICE_SPEC = {
    "office_code": {"required": True, "check": v.c_str(2, 16)},
    "name": {"required": True, "check": v.c_str(1)},
    "ce_threshold_disturbance_hectares": {
        "check": v.c_num(lo=0, lo_exclusive=True),
        "default": 5.0,
    },
    "ea_threshold_disturbance_hectares": {
        "check": v.c_num(lo=0, lo_exclusive=True),
        "default": 100.0,
    },
    "min_scoping_days": {"check": v.c_int(lo=1), "default": 30},
    "min_ea_comment_days": {"check": v.c_int(lo=1), "default": 30},
    "min_eis_comment_days": {"check": v.c_int(lo=1), "default": 45},
    "objection_window_days": {"check": v.c_int(lo=1), "default": 45},
    "cumulative_radius_km": {"check": v.c_num(lo=0, lo_exclusive=True), "default": 25.0},
    "significance_threshold": {
        "check": v.c_num(lo=0, hi=100, lo_exclusive=True),
        "default": 60.0,
    },
    "intensity_weight": {
        "check": v.c_num(lo=0, hi=1, lo_exclusive=True, hi_exclusive=True),
        "default": 0.6,
    },
    "context_weight": {
        "check": v.c_num(lo=0, hi=1, lo_exclusive=True, hi_exclusive=True),
        "default": 0.4,
    },
    "max_mitigated_reduction_points": {
        "check": v.c_num(lo=0, lo_exclusive=True),
        "default": 18.0,
    },
    "cost_per_reduction_point_cents": {"check": v.c_int(lo=0), "default": 250000},
    "monitoring_escalation_factor": {"check": v.c_num(lo=1.0), "default": 1.035},
    "max_binding_obligation_cents": {"check": v.c_int(lo=0), "default": 900000000},
    "extraordinary_circumstance_codes": {
        "check": v.c_enum_array(v.EC_CODES, min_items=1),
        "default": ["EC_HISTORIC", "EC_ENDANGERED_SPECIES", "EC_WETLAND"],
    },
    "ec_severity_trigger_threshold": {"check": v.c_int(lo=1, hi=5), "default": 3},
    "min_screened_in_alternatives_ea": {"check": v.c_int(lo=0), "default": 1},
    "min_screened_in_alternatives_eis": {"check": v.c_int(lo=0), "default": 2},
    "min_alternative_feasibility": {"check": v.c_num(lo=0, hi=100), "default": 60.0},
}

AGENCY_SPEC = {
    "agency_code": {"required": True, "check": v.c_str(2, 16)},
    "name": {"required": True, "check": v.c_str(1)},
    "agency_role": {
        "required": True,
        "check": v.c_enum(("COOPERATING", "CONSULTING", "BOTH")),
    },
    "max_concurrent_consultations": {"check": v.c_int(lo=1), "default": 2},
    "handoff_buffer_days": {"check": v.c_int(lo=0), "default": 3},
    "statutory_response_days": {"check": v.c_int(lo=1), "default": 135},
    "status": {"check": v.c_enum(("ACTIVE", "SUSPENDED")), "default": "ACTIVE"},
}


@endpoint(bp, "/review-offices", ["POST"], ["PolicyAdmin"])
def create_office():
    body = v.parse_body(OFFICE_SPEC)

    if not Decimal(str(body["ce_threshold_disturbance_hectares"])) < Decimal(
        str(body["ea_threshold_disturbance_hectares"])
    ):
        raise invalid(
            "ce_threshold_disturbance_hectares must be strictly below "
            "ea_threshold_disturbance_hectares"
        )
    if body["min_eis_comment_days"] < body["min_ea_comment_days"]:
        raise invalid("min_eis_comment_days must be at least min_ea_comment_days")
    if body["min_screened_in_alternatives_eis"] < body["min_screened_in_alternatives_ea"]:
        raise invalid(
            "min_screened_in_alternatives_eis must be at least min_screened_in_alternatives_ea"
        )
    if Decimal(str(body["intensity_weight"])) + Decimal(str(body["context_weight"])) != Decimal(
        "1.0"
    ):
        raise invalid("intensity_weight and context_weight must sum to exactly 1.0")

    for office in db.db["offices"].values():
        if office["office_code"] == body["office_code"]:
            fail("ERR_CONSTRAINT_VIOLATION", "office_code is already in use")

    fields = dict(body)
    fields["binding_obligation_cents"] = 0
    row = db.new_row("offices", fields)
    return response.created(db.public(row))


@endpoint(bp, "/review-offices/<office_id>", ["GET"], [
    "PolicyAdmin",
    "NepaCoordinator",
    "ReviewingOfficial",
    "DecidingOfficial",
    "ObjectionReviewingOfficer",
    "ResourceSpecialist",
])
def get_office(office_id):
    office = db.find("offices", office_id)
    if office is None:
        fail("ERR_NOT_FOUND", "review office not found")
    return response.ok(db.public(office))


@endpoint(bp, "/review-offices", ["GET"], ["PolicyAdmin", "NepaCoordinator", "ReviewingOfficial"])
def list_offices():
    limit, offset = v.pagination()
    items = db.rows("offices")
    page, total = response.paginate(items, limit, offset)
    return response.listing(db.public_list(page), limit, offset, total)


@endpoint(bp, "/agencies", ["POST"], ["PolicyAdmin"])
def create_agency():
    body = v.parse_body(AGENCY_SPEC)
    for agency in db.db["agencies"].values():
        if agency["agency_code"] == body["agency_code"]:
            fail("ERR_CONSTRAINT_VIOLATION", "agency_code is already in use")
    fields = dict(body)
    fields["active_consultation_count"] = 0
    row = db.new_row("agencies", fields)
    return response.created(db.public(row))


@endpoint(bp, "/agencies/<agency_id>", ["GET"], [
    "PolicyAdmin",
    "NepaCoordinator",
    "AgencyLiaison",
    "ReviewingOfficial",
])
def get_agency(agency_id):
    agency = db.find("agencies", agency_id)
    if agency is None:
        fail("ERR_NOT_FOUND", "agency not found")
    return response.ok(db.public(agency))


@endpoint(bp, "/agencies", ["GET"], [
    "PolicyAdmin",
    "NepaCoordinator",
    "AgencyLiaison",
    "ReviewingOfficial",
])
def list_agencies():
    limit, offset = v.pagination()
    items = v.apply_filters(db.rows("agencies"), v.filters("status"))
    page, total = response.paginate(items, limit, offset)
    return response.listing(db.public_list(page), limit, offset, total)


@endpoint(bp, "/_clock/set_current_utc", ["POST"], ["PolicyAdmin"])
def set_clock():
    body = v.parse_body({"current_utc": {"required": True, "check": v.c_datetime}})
    db.set_logical_now(db.parse_dt(body["current_utc"]))
    return response.ok({})
