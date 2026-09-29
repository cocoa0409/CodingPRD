"""Lease agreements: drafting, filing, activation, termination and withdrawal."""

from flask import Blueprint, request

from db import db, new_row, touch, public, clock_now
from errors import ApiError, bad_request
from middleware import (
    require, check_ownership, scope_for_lessee,
    LESSOR_OPS, LESSEE, BILLING_ADMIN, MAINTENANCE_CONTROLLER,
    REGULATORY_AUTHORITY, INSURANCE_UNDERWRITER,
)
from response import object_response, pagination, paged
from routes.common import find_lessee, find_aircraft, find_lease, filtered
from services import calculations as C
from services import workflows as W
import validate as V

bp = Blueprint("leases", __name__)

PARTY = ("LESSOR", "LESSEE")


def operational_control_lawful(lease_like):
    if (lease_like["crew_provided_by"] == "LESSOR"
            and lease_like["maintenance_provided_by"] == "LESSOR"
            and lease_like["operational_control"] != "LESSOR"):
        return False
    return True


def live_determination(lease):
    today = clock_now().date()
    for approval in W.approvals_of_lease(lease["id"]):
        if approval["determination"] in ("APPROVED", "CONDITIONAL"):
            expires_on = approval["expires_on"]
            if expires_on is None or C.date_from_iso(expires_on) >= today:
                return approval
    return None


def conforming_certificate_at(lease, instant):
    for cert in W.certificates_of_lease(lease["id"]):
        if cert["status"] != "ACTIVE":
            continue
        if not cert["additional_insured_lessee"]:
            continue
        if not cert["breach_of_warranty_endorsed"]:
            continue
        if cert["hull_limit_usd_cents"] < C.HULL_LIMIT_FLOOR_CENTS:
            continue
        if cert["liability_limit_usd_cents"] < C.LIABILITY_LIMIT_FLOOR_CENTS:
            continue
        if cert["_effective_from"] <= instant <= cert["_expires_at"]:
            return cert
    return None


def qualified_captain(lease):
    for qual in W.qualifications_of_lease(lease["id"]):
        if qual["status"] != "QUALIFIED":
            continue
        crew = db.crew_members.get(qual["crew_member_id"])
        if crew is not None and crew["crew_role"] == "CAPTAIN":
            return qual
    return None


# ------------------------------------------------------------------ create / read

@bp.post("/wetlease/leases")
def create_lease():
    require((LESSOR_OPS,))
    body = V.json_body()

    lessee_id = V.req_str(body, "lessee_id")
    primary_aircraft_id = V.req_str(body, "primary_aircraft_id")
    term_start_raw, term_start = V.req_date(body, "term_start_date")
    term_end_raw, term_end = V.req_date(body, "term_end_date")
    if term_end < term_start:
        raise bad_request("term_end_date must not be earlier than term_start_date")
    block_hour_rate = V.req_int(body, "block_hour_rate_usd_cents", minimum=1)
    min_guaranteed = V.req_num(body, "min_guaranteed_block_hours_per_month",
                               exclusive_min=0)
    shortfall_pct = V.req_num(body, "shortfall_credit_pct", minimum=0, maximum=1)
    crew_provided_by = V.req_enum(body, "crew_provided_by", PARTY)
    maintenance_provided_by = V.req_enum(body, "maintenance_provided_by", PARTY)
    insurance_provided_by = V.req_enum(body, "insurance_provided_by", PARTY)
    operational_control = V.req_enum(body, "operational_control", PARTY)
    substitution_rights = V.req_enum(body, "substitution_rights",
                                     ("LESSOR_UNILATERAL", "LESSEE_CONSENT_REQUIRED"))
    reliability_basis = V.req_enum(body, "reliability_basis", ("DEPARTURE", "SCHEDULED"))
    required_program = V.req_str(body, "required_maintenance_program_ref")
    return_hours_max = V.req_num(body, "return_hours_since_check_max", minimum=0)
    return_cycles_max = V.req_int(body, "return_cycles_since_check_max", minimum=0)
    return_fuel = V.req_num(body, "return_fuel_kg_required", minimum=0)
    return_cap = V.req_int(body, "return_liability_cap_cents", minimum=0)
    return_deposit = V.req_int(body, "return_deposit_cents", minimum=0)
    redelivery_icao = V.req_icao(body, "redelivery_icao", 4)

    find_lessee(lessee_id)
    find_aircraft(primary_aircraft_id)

    row = new_row()
    row.update({
        "lessee_id": lessee_id,
        "primary_aircraft_id": primary_aircraft_id,
        "term_start_date": term_start_raw,
        "term_end_date": term_end_raw,
        "block_hour_rate_usd_cents": block_hour_rate,
        "min_guaranteed_block_hours_per_month": C.hours4(min_guaranteed),
        "shortfall_credit_pct": C.hours4(shortfall_pct),
        "crew_provided_by": crew_provided_by,
        "maintenance_provided_by": maintenance_provided_by,
        "insurance_provided_by": insurance_provided_by,
        "operational_control": operational_control,
        "substitution_rights": substitution_rights,
        "reliability_basis": reliability_basis,
        "required_maintenance_program_ref": required_program,
        "return_hours_since_check_max": C.money2(return_hours_max),
        "return_cycles_since_check_max": return_cycles_max,
        "return_fuel_kg_required": C.money2(return_fuel),
        "return_liability_cap_cents": return_cap,
        "return_deposit_cents": return_deposit,
        "redelivery_icao": redelivery_icao,
        "return_deposit_applied_cents": 0,
        "return_deposit_remaining_cents": return_deposit,
        "lifetime_credited_block_minutes": 0,
        "status": "DRAFT",
        "suspension_reason": None,
    })

    if not operational_control_lawful(row):
        raise ApiError("ERR_OPERATIONAL_CONTROL_MISMATCH")

    db.leases[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/wetlease/leases/<lease_id>")
def get_lease(lease_id):
    actor = require((LESSOR_OPS, BILLING_ADMIN, MAINTENANCE_CONTROLLER,
                     REGULATORY_AUTHORITY, INSURANCE_UNDERWRITER, LESSEE))
    lease = find_lease(lease_id)
    check_ownership(actor, "lease", lease)
    return object_response(public(lease))


@bp.get("/wetlease/leases")
def list_leases():
    actor = require((LESSOR_OPS, BILLING_ADMIN, REGULATORY_AUTHORITY, LESSEE))
    limit, offset = pagination(request.args)
    if "lessee_id" in request.args:
        find_lessee(request.args.get("lessee_id"))
    rows = filtered(list(db.leases.values()), request.args, {
        "lessee_id": "lessee_id",
        "primary_aircraft_id": "primary_aircraft_id",
        "status": "status",
    })
    rows = scope_for_lessee(actor, "lease", rows)
    return paged(rows, limit, offset)


@bp.get("/wetlease/leases/<lease_id>/regulatory-approvals")
def list_lease_approvals(lease_id):
    actor = require((REGULATORY_AUTHORITY, LESSOR_OPS, LESSEE))
    limit, offset = pagination(request.args)
    lease = find_lease(lease_id)
    check_ownership(actor, "lease", lease)
    rows = W.approvals_of_lease(lease_id)
    return paged(rows, limit, offset)


@bp.get("/wetlease/leases/<lease_id>/insurance-certificates")
def list_lease_certificates(lease_id):
    actor = require((INSURANCE_UNDERWRITER, LESSOR_OPS, LESSEE))
    limit, offset = pagination(request.args)
    lease = find_lease(lease_id)
    check_ownership(actor, "lease", lease)
    rows = W.certificates_of_lease(lease_id)
    return paged(rows, limit, offset)


# ------------------------------------------------------------------ filing

@bp.post("/wetlease/leases/<lease_id>/submit-for-approval")
def submit_for_approval(lease_id):
    require((LESSOR_OPS,))
    body = V.json_body()
    docket_no = V.req_str(body, "authority_docket_no")
    lease = find_lease(lease_id)

    lessee = db.lessees.get(lease["lessee_id"])
    if lessee is None or lessee["status"] != "ACTIVE":
        raise ApiError("ERR_LESSEE_SUSPENDED")
    if lease["status"] != "DRAFT":
        raise ApiError("ERR_LEASE_INVALID_STATE")
    if not operational_control_lawful(lease):
        raise ApiError("ERR_OPERATIONAL_CONTROL_MISMATCH")

    denied = None
    for approval in sorted(W.approvals_of_lease(lease_id),
                           key=lambda r: (r["created_at"], r["_seq"])):
        if approval["determination"] == "DENIED":
            denied = approval
    if denied is not None:
        denied["determination"] = "UNDER_REVIEW"
        denied["review_round"] = denied["review_round"] + 1
        denied["conditions"] = []
        denied["open_condition_codes"] = []
        denied["decided_at"] = None
        denied["authority_docket_no"] = docket_no
        touch(denied)
        approval = denied
    else:
        approval = new_row()
        approval.update({
            "lease_id": lease_id,
            "authority_docket_no": docket_no,
            "determination": "UNDER_REVIEW",
            "conditions": [],
            "open_condition_codes": [],
            "review_round": 1,
            "decided_at": None,
            "expires_on": None,
            "revocation_reason": None,
        })
        db.regulatory_approvals[approval["id"]] = approval

    lease["status"] = "PENDING_REGULATORY_APPROVAL"
    touch(lease)
    return object_response(public(approval), 201)


# ------------------------------------------------------------------ activation

@bp.post("/wetlease/leases/<lease_id>/activate")
def activate_lease(lease_id):
    require((LESSOR_OPS,))
    V.json_body()
    lease = find_lease(lease_id)

    lessee = db.lessees.get(lease["lessee_id"])
    if lessee is None or lessee["status"] != "ACTIVE":
        raise ApiError("ERR_LESSEE_SUSPENDED")

    status = lease["status"]
    reactivation = (status == "SUSPENDED" and lease["suspension_reason"] == "AIRFRAME_AOG")
    if status != "APPROVED" and not reactivation:
        raise ApiError("ERR_LEASE_INVALID_STATE")

    aircraft = db.aircraft.get(lease["primary_aircraft_id"])
    if aircraft is None:
        raise ApiError("ERR_AIRCRAFT_NOT_FOUND")

    if reactivation:
        if aircraft["status"] != "ASSIGNED" or aircraft["assigned_lease_id"] != lease_id:
            raise ApiError("ERR_AIRCRAFT_UNAVAILABLE")
        if W.active_certificate_covering(lease_id, clock_now()) is None:
            raise ApiError("ERR_INSURANCE_COVERAGE_MISSING")
        lease["status"] = "ACTIVE"
        lease["suspension_reason"] = None
        touch(lease)
        return object_response(public(lease))

    if aircraft["status"] != "AVAILABLE" or aircraft["assigned_lease_id"] is not None:
        raise ApiError("ERR_AIRCRAFT_UNAVAILABLE")
    if qualified_captain(lease) is None:
        raise ApiError("ERR_CREW_NOT_QUALIFIED_FOR_LESSEE_PROCEDURES")
    if live_determination(lease) is None:
        raise ApiError("ERR_REGULATORY_APPROVAL_MISSING")
    term_start = C.date_from_iso(lease["term_start_date"])
    if conforming_certificate_at(lease, C.midnight_utc(term_start)) is None:
        raise ApiError("ERR_INSURANCE_COVERAGE_MISSING")
    if aircraft["maintenance_program_ref"] != lease["required_maintenance_program_ref"]:
        raise ApiError("ERR_MAINTENANCE_PROGRAM_MISALIGNED")

    lease["status"] = "ACTIVE"
    lease["suspension_reason"] = None
    lease["return_deposit_applied_cents"] = 0
    lease["return_deposit_remaining_cents"] = lease["return_deposit_cents"]
    touch(lease)

    aircraft["status"] = "ASSIGNED"
    aircraft["assigned_lease_id"] = lease_id
    touch(aircraft)

    today = clock_now().date()
    anchor = term_start if term_start > today else today
    period_month = "%04d-%02d" % (anchor.year, anchor.month)
    if W.period_for(lease_id, period_month) is None:
        W.create_period(lease, period_month)

    return object_response(public(lease))


# ------------------------------------------------------------------ termination

@bp.post("/wetlease/leases/<lease_id>/terminate")
def terminate_lease(lease_id):
    require((LESSOR_OPS,))
    body = V.json_body()
    V.req_enum(body, "termination_reason", ("EXPIRY", "NOTICE", "DEFAULT"))
    lease = find_lease(lease_id)

    if lease["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_LEASE_INVALID_STATE")
    legs = W.legs_of_lease(lease_id)
    for leg in legs:
        if leg["status"] == "DISPATCHED":
            raise ApiError("ERR_LEG_INVALID_STATE")

    lease["status"] = "TERMINATING"
    lease["suspension_reason"] = None
    touch(lease)

    for leg in legs:
        if leg["status"] == "SCHEDULED" and leg["leg_class"] != "REPOSITIONING":
            W.cancel_leg(leg, "LESSOR", "COMMERCIAL")

    for period in W.periods_of_lease(lease_id):
        if period["status"] == "OPEN":
            W.close_period(period, open_next_month=False)

    record = new_row()
    record.update({
        "lease_id": lease_id,
        "aircraft_id": lease["primary_aircraft_id"],
        "repositioning_leg_id": None,
        "hours_since_check_at_return": None,
        "cycles_since_check_at_return": None,
        "fuel_on_board_kg": None,
        "discrepancy_codes": [],
        "discrepancy_cost_cents": 0,
        "billed_to_lessee_cents": 0,
        "status": "PENDING_INSPECTION",
    })
    db.return_conditions[record["id"]] = record
    return object_response(public(record), 201)


@bp.post("/wetlease/leases/<lease_id>/withdraw")
def withdraw_lease(lease_id):
    require((LESSOR_OPS,))
    body = V.json_body()
    V.req_str(body, "withdrawal_reason")
    lease = find_lease(lease_id)

    if lease["status"] not in ("DRAFT", "PENDING_REGULATORY_APPROVAL", "APPROVED"):
        raise ApiError("ERR_LEASE_INVALID_STATE")

    lease["status"] = "WITHDRAWN"
    lease["suspension_reason"] = None
    touch(lease)

    for approval in W.approvals_of_lease(lease_id):
        if approval["determination"] in ("UNDER_REVIEW", "CONDITIONAL", "APPROVED"):
            approval["determination"] = "REVOKED"
            approval["decided_at"] = None if approval["decided_at"] is None \
                else approval["decided_at"]
            touch(approval)

    W.revoke_qualifications(lease)
    W.release_airframe(lease)
    return object_response(public(lease))
