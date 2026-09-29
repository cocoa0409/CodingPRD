"""State programs and agency appointments (PRD 3.2)."""

from flask import Blueprint

import db
import lookup
import middleware as mw
import response
import shape
from db import store
from errors import ApiError

bp = Blueprint("state_programs", __name__)

CPL_SCOPES = ("FULL_SETTLEMENT", "LENDER_ONLY", "SELLER_PROCEEDS")

APPOINTMENT_TRANSITIONS = {
    "PENDING_LICENSE_VERIFICATION": ("ACTIVE",),
    "ACTIVE": ("LAPSED",),
    "LAPSED": ("ACTIVE",),
}
APPOINTMENT_TERMINALS = ("WITHDRAWN",)
LIVE_APPOINTMENT_STATUSES = ("PENDING_LICENSE_VERIFICATION", "ACTIVE", "LAPSED")


@bp.post("/state-programs")
def create_state_program():
    mw.require_roles(mw.COMPLIANCE_OFFICER)
    payload = shape.body()
    state_code = shape.req_str(payload, "state_code")
    cpl_permitted = shape.req_bool(payload, "cpl_permitted")
    coverage_cap = shape.req_cents(payload, "cpl_coverage_cap_cents")
    scope_allowed = shape.req_string_array(payload, "cpl_scope_allowed", CPL_SCOPES)
    split_pct = shape.req_fraction(payload, "premium_split_agency_pct")
    deadline_days = shape.req_int(payload, "policy_issuance_deadline_days", minimum=1)
    tolerance = shape.req_cents(payload, "three_way_tolerance_cents")
    threshold = shape.req_cents(payload, "counsel_referral_threshold_cents")

    for existing in store.all(db.STATE_PROGRAM):
        if existing["state_code"] == state_code:
            raise ApiError("ERR_DUPLICATE_STATE_CODE")

    program = db.new_row(
        db.STATE_PROGRAM,
        {
            "state_code": state_code,
            "cpl_permitted": cpl_permitted,
            "cpl_coverage_cap_cents": coverage_cap,
            "cpl_scope_allowed": scope_allowed,
            "premium_split_agency_pct": split_pct,
            "policy_issuance_deadline_days": deadline_days,
            "three_way_tolerance_cents": tolerance,
            "counsel_referral_threshold_cents": threshold,
        },
    )
    return response.created(program)


@bp.get("/state-programs/<program_id>")
def read_state_program(program_id):
    mw.require_roles(*mw.ALL_ROLES)
    return response.ok(lookup.state_program(program_id))


@bp.post("/agency-appointments")
def create_appointment():
    mw.require_roles(mw.LICENSING_ANALYST)
    payload = shape.body()
    agency_id = shape.req_id(payload, "agency_id")
    program_id = shape.req_id(payload, "state_program_id")
    license_number = shape.req_str(payload, "license_number")
    license_expires_on = shape.req_date(payload, "license_expires_on")

    # Tier 5 - agency_id then state_program_id
    agency = lookup.agency(agency_id)
    program = lookup.state_program(program_id)

    # Tier 13 - only one live appointment per pair
    for existing in store.where(
        db.APPOINTMENT, agency_id=agency["id"], state_program_id=program["id"]
    ):
        if existing["status"] in LIVE_APPOINTMENT_STATUSES:
            raise ApiError("ERR_DUPLICATE_APPOINTMENT")

    appointment = db.new_row(
        db.APPOINTMENT,
        {
            "agency_id": agency["id"],
            "state_program_id": program["id"],
            "license_number": license_number,
            "license_expires_on": db.date_str(license_expires_on),
            "status": "PENDING_LICENSE_VERIFICATION",
            "verified_license_number": None,
            "verified_expires_on": None,
            "appointed_on": None,
        },
    )
    return response.created(appointment)


@bp.get("/agency-appointments/<appointment_id>")
def read_appointment(appointment_id):
    mw.require_roles(*mw.ALL_ROLES)
    return response.ok(lookup.appointment(appointment_id))


@bp.get("/agency-appointments")
def list_appointments():
    mw.require_roles(*mw.ALL_ROLES)
    limit, offset = shape.pagination()
    filters = {
        "agency_id": shape.query_value("agency_id"),
        "state_program_id": shape.query_value("state_program_id"),
        "status": shape.query_value("status"),
    }
    rows = [
        row
        for row in store.all(db.APPOINTMENT)
        if all(v is None or row.get(k) == v for k, v in filters.items())
    ]
    return response.ok_list(shape.page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/agency-appointments/<appointment_id>/license-verification")
def license_verification(appointment_id):
    user_id, role = mw.require_roles(mw.LICENSING_ANALYST)
    payload = shape.body()
    decision = shape.req_enum(payload, "decision", ("VERIFY", "LAPSE"))
    verified_number = shape.opt_str(payload, "verified_license_number")
    verified_expires = shape.opt_date(payload, "verified_expires_on")

    appointment = lookup.appointment(appointment_id)
    agency = lookup.agency(appointment["agency_id"])

    # Tier 10
    target = "ACTIVE" if decision == "VERIFY" else "LAPSED"
    lookup.guard_transition(
        appointment["status"], target, APPOINTMENT_TRANSITIONS, APPOINTMENT_TERMINALS
    )

    if decision == "VERIFY":
        # Tier 11 - unexpired confirmed expiry, then an accepted financial review.
        if verified_expires is None or verified_expires <= db.clock_date():
            raise ApiError("ERR_LICENSE_EXPIRED")
        if agency["financial_review_status"] != "ACCEPTED":
            raise ApiError("ERR_FINANCIAL_REVIEW_NOT_ACCEPTED")
        appointment["status"] = "ACTIVE"
        if verified_number is not None:
            appointment["verified_license_number"] = verified_number
        appointment["verified_expires_on"] = db.date_str(verified_expires)
        if appointment["appointed_on"] is None:
            appointment["appointed_on"] = db.date_str(db.clock_date())
    else:
        appointment["status"] = "LAPSED"

    return response.ok(appointment)
