"""Death benefit claims and the beneficiary split (PRD 3.7)."""

from decimal import Decimal

from flask import Blueprint

import calc
from cascades import rerate_carrier, unmatch_policy_from_plans
from errors import ApiError
from response import collection_response, resource_response
from store import create_record, db, touch
from validation import (
    actor,
    authorize,
    find_allocation,
    find_claim,
    find_policy,
    get_datetime,
    get_enum,
    get_id,
    get_int,
    get_money,
    get_string,
    guard_terminal,
    guard_transition,
    json_body,
    pagination,
    query_enum,
    query_str,
)

bp = Blueprint("claims", __name__)

ADJUDICATION_STATUSES = ("FILED", "UNDER_ADJUDICATION", "APPROVED", "DENIED", "VOIDED")
ADJUDICATION_TERMINAL = ("DENIED", "VOIDED")
DISTRIBUTION_STATUSES = ("NOT_STARTED", "ALLOCATED", "DISTRIBUTED")
DISTRIBUTION_TERMINAL = ("DISTRIBUTED",)
RELATIONSHIPS = ("SPOUSE", "CHILD", "TRUST", "ESTATE")
ALLOCATION_STATUSES = ("ACTIVE", "VOIDED")
CLAIM_READ_ROLES = ("ClaimsAdministrator", "RiskOfficer", "BenefitsAnalyst")
ALLOCATION_READ_ROLES = ("ClaimsAdministrator", "RiskOfficer")
ZERO = Decimal("0.00")


def _policy_of(claim):
    policy = db.policies.get(claim["policy_id"])
    if policy is None:
        raise ApiError("ERR_POLICY_NOT_FOUND")
    return policy


def _employee_of(policy):
    employee = db.employees.get(policy["employee_id"])
    if employee is None:
        raise ApiError("ERR_EMPLOYEE_NOT_FOUND")
    return employee


# ---- claims -------------------------------------------------------------


@bp.post("/death-claims")
def file_claim():
    authorize(("ClaimsAdministrator",))
    body = json_body()
    policy_id = get_id(body, "policy_id")
    raw_dod, date_of_death = get_datetime(body, "date_of_death")
    terminal_dividend = get_money(
        body, "terminal_dividend_usd", required=False, default=ZERO
    )
    proof_reference = get_string(body, "proof_reference")

    policy = find_policy(policy_id)
    guard_transition(policy["status"] == "IN_FORCE")
    employee = _employee_of(policy)

    claim = create_record(
        db.death_claims,
        {
            "policy_id": policy["id"],
            "date_of_death": raw_dod,
            "_date_of_death": date_of_death,
            "terminal_dividend_usd": terminal_dividend,
            "proof_reference": proof_reference,
            "total_death_benefit_usd": ZERO,
            "survivor_entitlement_usd": ZERO,
            "bank_portion_usd": ZERO,
            "adjudication_status": "FILED",
            "distribution_status": "NOT_STARTED",
            "allocated_bps_total": 0,
            "filed_by_user_id": actor(),
            "adjudicated_by_user_id": None,
        },
    )

    policy["status"] = "CLAIM_PENDING"
    touch(policy)
    employee["employment_status"] = "DECEASED"
    touch(employee)
    return resource_response(claim, 201)


@bp.get("/death-claims")
def list_claims():
    authorize(CLAIM_READ_ROLES)
    limit, offset = pagination()
    policy_id = query_str("policy_id")
    adjudication_status = query_enum("adjudication_status", ADJUDICATION_STATUSES)
    distribution_status = query_enum("distribution_status", DISTRIBUTION_STATUSES)
    rows = []
    for claim in db.death_claims.values():
        if policy_id is not None and claim["policy_id"] != policy_id:
            continue
        if adjudication_status is not None and claim["adjudication_status"] != adjudication_status:
            continue
        if distribution_status is not None and claim["distribution_status"] != distribution_status:
            continue
        rows.append(claim)
    return collection_response(rows, limit, offset)


@bp.get("/death-claims/<claim_id>")
def read_claim(claim_id):
    authorize(CLAIM_READ_ROLES)
    return resource_response(find_claim(claim_id))


@bp.post("/death-claims/<claim_id>/start-adjudication")
def start_adjudication(claim_id):
    authorize(("ClaimsAdministrator",))
    claim = find_claim(claim_id)
    guard_terminal(claim["adjudication_status"], ADJUDICATION_TERMINAL)
    guard_transition(claim["adjudication_status"] == "FILED")
    claim["adjudication_status"] = "UNDER_ADJUDICATION"
    touch(claim)
    return resource_response(claim)


@bp.post("/death-claims/<claim_id>/approve")
def approve_claim(claim_id):
    authorize(("RiskOfficer",))
    claim = find_claim(claim_id)
    guard_terminal(claim["adjudication_status"], ADJUDICATION_TERMINAL)
    guard_transition(claim["adjudication_status"] == "UNDER_ADJUDICATION")
    if actor() == claim["filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    policy = _policy_of(claim)
    employee = _employee_of(policy)
    split = calc.death_benefit_split(policy, claim, employee)
    claim.update(split)
    claim["adjudication_status"] = "APPROVED"
    claim["adjudicated_by_user_id"] = actor()
    touch(claim)
    return resource_response(claim)


@bp.post("/death-claims/<claim_id>/deny")
def deny_claim(claim_id):
    authorize(("RiskOfficer",))
    claim = find_claim(claim_id)
    guard_terminal(claim["adjudication_status"], ADJUDICATION_TERMINAL)
    guard_transition(claim["adjudication_status"] == "UNDER_ADJUDICATION")
    if actor() == claim["filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    claim["adjudication_status"] = "DENIED"
    claim["adjudicated_by_user_id"] = actor()
    touch(claim)

    policy = db.policies.get(claim["policy_id"])
    if policy is not None and policy["status"] == "CLAIM_PENDING":
        policy["status"] = "IN_FORCE"
        touch(policy)
        employee = db.employees.get(policy["employee_id"])
        if employee is not None:
            employee["employment_status"] = "ACTIVE"
            touch(employee)
    return resource_response(claim)


@bp.post("/death-claims/<claim_id>/void")
def void_claim(claim_id):
    authorize(("ClaimsAdministrator",))
    claim = find_claim(claim_id)
    guard_terminal(claim["adjudication_status"], ADJUDICATION_TERMINAL)
    guard_transition(
        claim["adjudication_status"] in ("FILED", "UNDER_ADJUDICATION", "APPROVED")
    )
    guard_transition(claim["distribution_status"] != "DISTRIBUTED")

    claim["adjudication_status"] = "VOIDED"
    for allocation in calc.active_allocations(claim["id"]):
        allocation["status"] = "VOIDED"
        allocation["gross_amount_usd"] = ZERO
        touch(allocation)
    claim["allocated_bps_total"] = 0
    touch(claim)

    policy = db.policies.get(claim["policy_id"])
    if policy is not None and policy["status"] == "CLAIM_PENDING":
        policy["status"] = "IN_FORCE"
        touch(policy)
        employee = db.employees.get(policy["employee_id"])
        if employee is not None:
            employee["employment_status"] = "ACTIVE"
            touch(employee)
    return resource_response(claim)


@bp.post("/death-claims/<claim_id>/seal-allocations")
def seal_allocations(claim_id):
    authorize(("ClaimsAdministrator",))
    claim = find_claim(claim_id)
    guard_terminal(claim["distribution_status"], DISTRIBUTION_TERMINAL)
    guard_transition(claim["distribution_status"] == "NOT_STARTED")
    guard_transition(claim["adjudication_status"] == "APPROVED")

    allocations = calc.active_allocations(claim["id"])
    total_bps = sum(int(a["allocation_pct_bps"]) for a in allocations)
    if total_bps != calc.ALLOCATION_BPS_TOTAL:
        raise ApiError("ERR_BENEFICIARY_TOTAL_INVALID")

    shares = calc.allocation_shares(claim["survivor_entitlement_usd"], allocations)
    for allocation, share in zip(allocations, shares):
        allocation["gross_amount_usd"] = share
        touch(allocation)

    claim["distribution_status"] = "ALLOCATED"
    touch(claim)
    return resource_response(claim)


@bp.post("/death-claims/<claim_id>/distribute")
def distribute_claim(claim_id):
    authorize(("ClaimsAdministrator",))
    claim = find_claim(claim_id)
    guard_terminal(claim["distribution_status"], DISTRIBUTION_TERMINAL)
    guard_transition(claim["distribution_status"] == "ALLOCATED")
    guard_transition(claim["adjudication_status"] == "APPROVED")

    claim["distribution_status"] = "DISTRIBUTED"
    touch(claim)

    # first hop - the policy is paid out
    policy = _policy_of(claim)
    guard_transition(policy["status"] == "CLAIM_PENDING")
    policy["status"] = "PAID_OUT"
    policy["cash_surrender_value_usd"] = ZERO
    touch(policy)

    # second hop - carrier exposure and the hysteresis
    carrier = db.carriers.get(policy["carrier_id"])
    if carrier is not None:
        rerate_carrier(carrier)

    # third hop - the deferred compensation ledger
    unmatch_policy_from_plans(policy)
    return resource_response(claim)


# ---- beneficiary allocations -------------------------------------------


@bp.post("/beneficiary-allocations")
def add_allocation():
    authorize(("ClaimsAdministrator",))
    body = json_body()
    claim_id = get_id(body, "claim_id")
    beneficiary_name = get_string(body, "beneficiary_name")
    relationship = get_enum(body, "relationship", RELATIONSHIPS)
    allocation_pct_bps = get_int(body, "allocation_pct_bps", minimum=1, maximum=10000)

    claim = find_claim(claim_id)
    active = calc.active_allocations(claim["id"])
    running = sum(int(a["allocation_pct_bps"]) for a in active)
    if running + allocation_pct_bps > calc.ALLOCATION_BPS_TOTAL:
        raise ApiError("ERR_BENEFICIARY_TOTAL_INVALID")

    allocation = create_record(
        db.beneficiary_allocations,
        {
            "claim_id": claim["id"],
            "beneficiary_name": beneficiary_name,
            "relationship": relationship,
            "allocation_pct_bps": allocation_pct_bps,
            "gross_amount_usd": ZERO,
            "status": "ACTIVE",
        },
    )
    claim["allocated_bps_total"] = int(claim["allocated_bps_total"]) + allocation_pct_bps
    touch(claim)
    return resource_response(allocation, 201)


@bp.get("/beneficiary-allocations")
def list_allocations():
    authorize(ALLOCATION_READ_ROLES)
    limit, offset = pagination()
    claim_id = query_str("claim_id")
    status = query_enum("status", ALLOCATION_STATUSES)
    rows = []
    for allocation in db.beneficiary_allocations.values():
        if claim_id is not None and allocation["claim_id"] != claim_id:
            continue
        if status is not None and allocation["status"] != status:
            continue
        rows.append(allocation)
    return collection_response(rows, limit, offset)


@bp.get("/beneficiary-allocations/<allocation_id>")
def read_allocation(allocation_id):
    authorize(ALLOCATION_READ_ROLES)
    return resource_response(find_allocation(allocation_id))


@bp.post("/beneficiary-allocations/<allocation_id>/void")
def void_allocation(allocation_id):
    authorize(("ClaimsAdministrator",))
    allocation = find_allocation(allocation_id)
    guard_terminal(allocation["status"], ("VOIDED",))
    claim = db.death_claims.get(allocation["claim_id"])
    if claim is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND")
    guard_transition(claim["distribution_status"] == "ALLOCATED")

    allocation["status"] = "VOIDED"
    allocation["gross_amount_usd"] = ZERO
    touch(allocation)

    claim["allocated_bps_total"] = int(claim["allocated_bps_total"]) - int(
        allocation["allocation_pct_bps"]
    )
    claim["distribution_status"] = "NOT_STARTED"
    touch(claim)
    return resource_response(allocation)
