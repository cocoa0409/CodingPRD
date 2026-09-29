"""Tenants, leases, the TI negotiation and the TI ledger (PRD 3.3, 3.4, 3.9)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import cascades
import clock
import constants
import db
import helpers
import queries
import response
import serializers
import validation
from errors import fail
from util import dec, q2

bp = Blueprint("leasing", __name__)

ZERO = Decimal("0.00")
NEGOTIABLE_STATES = ("LOI", "NEGOTIATING", "COUNTER_PENDING")
CONVERTED_STATES = ("CONVERSION_APPROVED", "CONVERSION_COMPLETE")
QUIESCE_BLOCKING = ("SCHEDULED", "VIBRATION_HOLD", "BLOCKED", "IN_PROGRESS")


# ---------------------------------------------------------------------- tenants
@bp.post("/tenants")
def create_tenant():
    body = validation.body()
    research_type = validation.req_enum(body, "research_type", constants.RESEARCH_TYPES)
    fields = {
        "legal_name": validation.req_str(body, "legal_name"),
        "research_type": research_type,
        "credit_tier": validation.req_enum(body, "credit_tier", constants.CREDIT_TIERS),
    }
    auth.require(constants.ROLE_LANDLORD)
    fields["lab_premium_psf"] = constants.LAB_PREMIUM_BY_RESEARCH_TYPE[research_type]
    fields["required_commissioning_scripts"] = list(
        constants.REQUIRED_SCRIPTS_BY_RESEARCH_TYPE[research_type])
    record = db.create(db.tenants, fields)
    return response.created(serializers.tenant(record))


@bp.get("/tenants/<tenant_id>")
def get_tenant(tenant_id):
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_TENANT,
                 constants.ROLE_AHJ, constants.ROLE_CX)
    record = helpers.fetch(db.tenants, tenant_id, "ERR_TENANT_NOT_FOUND")
    return response.ok(serializers.tenant(record))


# ----------------------------------------------------------------------- leases
@bp.post("/leases")
def create_lease():
    body = validation.body()
    tenant_id = validation.req_id(body, "tenant_id")
    building_id = validation.req_id(body, "building_id")
    premises_floor_id = validation.req_id(body, "premises_floor_id")
    fields = {
        "rentable_sf": validation.req_int(body, "rentable_sf", gt=0),
        "term_months": validation.req_int(body, "term_months", ge=12),
        "base_rent_psf": validation.req_num(body, "base_rent_psf", gt=0),
        "delivery_deadline": validation.req_dt(body, "delivery_deadline"),
    }
    auth.require(constants.ROLE_LANDLORD)

    helpers.fetch(db.tenants, tenant_id, "ERR_TENANT_NOT_FOUND")
    helpers.fetch(db.buildings, building_id, "ERR_BUILDING_NOT_FOUND")
    floor = helpers.fetch(db.floors, premises_floor_id, "ERR_FLOOR_NOT_FOUND")
    if floor["building_id"] != building_id:
        fail("ERR_FLOOR_NOT_IN_PREMISES")

    fields.update({
        "tenant_id": tenant_id,
        "building_id": building_id,
        "premises_floor_id": premises_floor_id,
        "status": "LOI",
        "accepted_proposal_round": None,
        "accepted_allowance_psf": None,
        "lab_premium_psf_applied": None,
        "provisional_authorized_ti_usd": None,
        "volume_credit_psf": None,
        "final_allowance_psf": None,
        "ti_authorized_usd": ZERO,
        "ti_uncommitted_usd": ZERO,
        "ti_committed_usd": ZERO,
        "ti_disbursed_usd": ZERO,
        "ti_forfeited_usd": ZERO,
        "last_disbursement_usd": ZERO,
        "restoration_escrow_required_usd": ZERO,
        "restoration_escrow_held_usd": ZERO,
        "restoration_liability_usd": ZERO,
        "restoration_cash_due_usd": ZERO,
        "restoration_escrow_refunded_usd": ZERO,
        "terms_accepted_by_user_id": None,
        "executed_by_user_id": None,
        "executed_at": None,
        "expiration_date": None,
        "_last_draw_allocations": {},
    })
    record = db.create(db.leases, fields)
    return response.created(serializers.lease(record))


@bp.get("/leases/<lease_id>")
def get_lease(lease_id):
    user_id, role = auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER,
                                 constants.ROLE_TENANT, constants.ROLE_AHJ, constants.ROLE_CX)
    lease = helpers.fetch(db.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    auth.guard_lease(lease, user_id, role)
    return response.ok(serializers.lease(lease))


@bp.get("/leases")
def list_leases():
    limit, offset = validation.pagination()
    filters = {
        "tenant_id": validation.query_str("tenant_id"),
        "building_id": validation.query_str("building_id"),
        "premises_floor_id": validation.query_str("premises_floor_id"),
        "status": validation.query_enum("status", constants.LEASE_STATUSES),
    }
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_TENANT)
    records = helpers.filtered(db.ordered(db.leases.values()), filters)
    return helpers.page(records, serializers.lease, limit, offset)


# -------------------------------------------------------------------- proposals
@bp.post("/leases/<lease_id>/ti-proposals")
def create_proposal(lease_id):
    body = validation.body()
    expected_version = validation.req_int(body, "expected_lease_version")
    proposed_allowance_psf = validation.req_num(body, "proposed_allowance_psf", ge=0)
    note = validation.opt_str(body, "note")
    user_id, role = auth.require(constants.ROLE_LANDLORD, constants.ROLE_TENANT)
    lease = helpers.fetch(db.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    auth.guard_lease(lease, user_id, role)

    if expected_version != lease["version"]:
        fail("ERR_STALE_LEASE_VERSION")
    if lease["status"] not in NEGOTIABLE_STATES:
        fail("ERR_INVALID_LEASE_STATE")
    building = db.buildings.get(lease["building_id"])
    if building is None or building["suitability_state"] not in CONVERTED_STATES:
        fail("ERR_BUILDING_NOT_CONVERSION_APPROVED")

    party = auth.party(role)
    open_proposal = queries.open_proposal(lease["id"])
    if open_proposal is not None and open_proposal["proposed_by"] == party:
        fail("ERR_NOT_YOUR_TURN")

    rounds = queries.proposals_of(lease["id"])
    if len(rounds) >= constants.NEGOTIATION_ROUND_LIMIT:
        fail("ERR_NEGOTIATION_ROUND_LIMIT")

    now = clock.now()
    if open_proposal is not None:
        open_proposal["status"] = "COUNTERED" if open_proposal["expires_at"] >= now else "EXPIRED"
        db.touch(open_proposal)

    record = db.create(db.proposals, {
        "lease_id": lease["id"],
        "round_number": len(rounds) + 1,
        "proposed_by": party,
        "authored_by_user_id": user_id,
        "proposed_allowance_psf": proposed_allowance_psf,
        "note": note,
        "expires_at": now + timedelta(days=constants.PROPOSAL_TTL_DAYS),
        "status": "OPEN",
        "accepted_by_user_id": None,
    })
    lease["status"] = "NEGOTIATING" if party == "LANDLORD" else "COUNTER_PENDING"
    db.touch(lease)
    return response.created(serializers.proposal(record))


@bp.get("/leases/<lease_id>/ti-proposals")
def list_lease_proposals(lease_id):
    limit, offset = validation.pagination()
    status = validation.query_enum("status", constants.PROPOSAL_STATUSES)
    user_id, role = auth.require(constants.ROLE_LANDLORD, constants.ROLE_TENANT)
    lease = helpers.fetch(db.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    auth.guard_lease(lease, user_id, role)
    records = helpers.filtered(queries.proposals_of(lease["id"]), {"status": status})
    return helpers.page(records, serializers.proposal, limit, offset)


@bp.get("/ti-proposals/<proposal_id>")
def get_proposal(proposal_id):
    user_id, role = auth.require(constants.ROLE_LANDLORD, constants.ROLE_TENANT)
    record = helpers.fetch(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
    auth.guard_by_lease_id(record["lease_id"], user_id, role)
    return response.ok(serializers.proposal(record))


@bp.get("/ti-proposals")
def list_proposals():
    limit, offset = validation.pagination()
    filters = {
        "lease_id": validation.query_str("lease_id"),
        "proposed_by": validation.query_enum("proposed_by", constants.PARTIES),
        "status": validation.query_enum("status", constants.PROPOSAL_STATUSES),
    }
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_TENANT)
    records = helpers.filtered(db.ordered(db.proposals.values()), filters)
    return helpers.page(records, serializers.proposal, limit, offset)


@bp.post("/ti-proposals/<proposal_id>/accept")
def accept_proposal(proposal_id):
    user_id, role = auth.require(constants.ROLE_LANDLORD, constants.ROLE_TENANT)
    record = helpers.fetch(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
    auth.guard_by_lease_id(record["lease_id"], user_id, role)

    if record["status"] != "OPEN":
        fail("ERR_INVALID_PROPOSAL_STATE")
    party = auth.party(role)
    if user_id == record["authored_by_user_id"] or party == record["proposed_by"]:
        fail("ERR_SELF_ACCEPT_FORBIDDEN")
    if record["expires_at"] < clock.now():
        fail("ERR_PROPOSAL_EXPIRED")

    record["status"] = "ACCEPTED"
    record["accepted_by_user_id"] = user_id
    db.touch(record)

    lease = db.leases[record["lease_id"]]
    tenant = queries.tenant_of_lease(lease)
    premises_floor = db.floors.get(lease["premises_floor_id"])
    economics = calc.ti_economics(tenant, premises_floor, lease["rentable_sf"],
                                 record["proposed_allowance_psf"])
    lease["status"] = "TERMS_ACCEPTED"
    lease["accepted_proposal_round"] = record["round_number"]
    lease["accepted_allowance_psf"] = record["proposed_allowance_psf"]
    lease["terms_accepted_by_user_id"] = user_id
    lease.update(economics)
    lease["ti_uncommitted_usd"] = economics["ti_authorized_usd"]
    db.touch(lease)
    return response.ok(serializers.lease(lease))


# ---------------------------------------------------------- escrow and execution
@bp.post("/leases/<lease_id>/escrow-deposits")
def deposit_escrow(lease_id):
    body = validation.body()
    amount = validation.req_num(body, "amount_usd", gt=0)
    user_id, role = auth.require(constants.ROLE_TENANT, constants.ROLE_LANDLORD)
    lease = helpers.fetch(db.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    auth.guard_lease(lease, user_id, role)
    lease["restoration_escrow_held_usd"] = q2(dec(lease["restoration_escrow_held_usd"]) + amount)
    db.touch(lease)
    return response.ok(serializers.lease(lease))


@bp.post("/leases/<lease_id>/execute")
def execute_lease(lease_id):
    user_id, _role = auth.require(constants.ROLE_LANDLORD)
    lease = helpers.fetch(db.leases, lease_id, "ERR_LEASE_NOT_FOUND")

    if lease["status"] != "TERMS_ACCEPTED":
        fail("ERR_INVALID_LEASE_STATE")
    if dec(lease["restoration_escrow_held_usd"]) < dec(lease["restoration_escrow_required_usd"]):
        fail("ERR_ESCROW_DEPOSIT_INSUFFICIENT")
    accepted = queries.accepted_proposal(lease["id"])
    author = accepted["authored_by_user_id"] if accepted is not None else None
    if user_id == author or user_id == lease["terms_accepted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    lease["status"] = "EXECUTED"
    lease["executed_by_user_id"] = user_id
    lease["executed_at"] = clock.now()
    db.touch(lease)
    return response.ok(serializers.lease(lease))


@bp.post("/leases/<lease_id>/ti-disbursements")
def disburse_ti(lease_id):
    body = validation.body()
    requested = validation.req_num(body, "requested_usd", gt=0)
    auth.require(constants.ROLE_LANDLORD)
    lease = helpers.fetch(db.leases, lease_id, "ERR_LEASE_NOT_FOUND")

    if lease["status"] not in ("EXECUTED", "ACTIVE"):
        fail("ERR_INVALID_LEASE_STATE")
    if dec(lease["ti_committed_usd"]) == 0:
        fail("ERR_TI_ALLOWANCE_EXHAUSTED")

    disbursed, allocations = calc.draw_allocation(lease, requested)
    for phase_id, allocated in allocations.items():
        phase = db.phases[phase_id]
        phase["ti_disbursed_usd"] = q2(dec(phase["ti_disbursed_usd"]) + dec(allocated))
        db.touch(phase)
    lease["ti_committed_usd"] = q2(dec(lease["ti_committed_usd"]) - disbursed)
    lease["ti_disbursed_usd"] = q2(dec(lease["ti_disbursed_usd"]) + disbursed)
    lease["last_disbursement_usd"] = disbursed
    lease["_last_draw_allocations"] = dict(allocations)
    db.touch(lease)
    return response.ok(serializers.lease(lease))


# ------------------------------------------------------------------- wind-down
@bp.post("/leases/<lease_id>/expiration-notice")
def expiration_notice(lease_id):
    body = validation.body()
    expiration_date = validation.req_dt(body, "expiration_date")
    if expiration_date < clock.now():
        fail("ERR_VALIDATION", "expiration_date must be at or after the current instant")
    auth.require(constants.ROLE_LANDLORD)
    lease = helpers.fetch(db.leases, lease_id, "ERR_LEASE_NOT_FOUND")

    if lease["status"] != "ACTIVE":
        fail("ERR_INVALID_LEASE_STATE")

    lease["status"] = "EXPIRING"
    lease["expiration_date"] = expiration_date
    lease["restoration_liability_usd"] = calc.restoration_liability(lease)
    db.touch(lease)
    return response.ok(serializers.lease(lease))


@bp.post("/leases/<lease_id>/restoration-settlement")
def restoration_settlement(lease_id):
    auth.require(constants.ROLE_LANDLORD)
    lease = helpers.fetch(db.leases, lease_id, "ERR_LEASE_NOT_FOUND")

    if lease["status"] != "EXPIRING":
        fail("ERR_RESTORATION_ALREADY_SETTLED")
    for phase in queries.phases_of_lease(lease["id"]):
        if phase["status"] in QUIESCE_BLOCKING:
            fail("ERR_PHASES_NOT_QUIESCED")

    cascades.settle_restoration(lease)
    return response.ok(serializers.lease(lease))
