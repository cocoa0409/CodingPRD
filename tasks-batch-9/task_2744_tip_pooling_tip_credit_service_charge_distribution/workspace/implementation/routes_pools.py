"""Shift tip pools: contribution, the card fee, distribution and reversal."""

from flask import Blueprint

import calc
import cascades
import serial
from auth import ALL_ROLES, authorize, check_employee_scope, scope_rows_by_employee
from envelope import object_response
from errors import ApiError
from serial import apply_filters, paged, view
from store import db, stamp_new, touch
from validators import f, parse_body, parse_query

bp = Blueprint("pools", __name__)

CONTRIBUTION_STATUSES = {"CONTRIBUTED", "REVERSED"}
DISTRIBUTION_STATUSES = {"PENDING", "DISTRIBUTED", "REVERSED"}
ENTRY_TYPES = {"DISTRIBUTION", "REVERSAL"}


def day_shifts(location_id, business_date):
    return [
        s
        for s in cascades.rows("shifts")
        if s["location_id"] == location_id and s["business_date"] == business_date
    ]


def role_of(shift):
    return db.job_roles.get(shift["job_role_id"])


def is_management(shift):
    role = role_of(shift)
    return role is not None and role["is_management"]


def contribution_input_set(policy, shifts):
    """The shifts that feed a pool, per the pinned policy."""
    out = []
    for shift in shifts:
        if shift["time_status"] != "CLOSED":
            continue
        if shift["declaration_status"] not in ("DECLARED", "AMENDED"):
            continue
        if shift["shift_tip_pool_id"] is not None:
            continue
        role = role_of(shift)
        if role is None or role["is_management"]:
            continue
        if role["pool_contribution_pct_bps"] <= 0 and role["pool_share_points"] <= 0:
            continue
        if policy["pool_type"] == "TIPPED_ONLY" and role["tip_status"] != "TIPPED":
            continue
        out.append(shift)
    return out


def tips_charges(location_id, business_date):
    return [
        c
        for c in cascades.rows("service_charges")
        if c["location_id"] == location_id
        and c["business_date"] == business_date
        and c["status"] == "RECORDED"
        and c["treatment"] == "TIPS"
    ]


# ---------------------------------------------------------------------------
# POST /shift-tip-pools
# ---------------------------------------------------------------------------

@bp.post("/shift-tip-pools")
def create_pool():
    authorize(["PayrollPreparer"])
    body, _present = parse_body(
        [f("location_id", "id", True), f("business_date", "date", True)]
    )
    location = db.locations.get(body["location_id"])                  # rung 5
    if location is None:
        raise ApiError("ERR_LOCATION_NOT_FOUND")
    business_date = body["business_date"]

    period = cascades.period_covering(location["id"], business_date)  # rung 12
    if period is None or period["status"] != "OPEN":
        raise ApiError("ERR_PAY_PERIOD_NOT_OPEN")

    shifts = day_shifts(location["id"], business_date)

    candidates = [
        s
        for s in shifts
        if s["time_status"] == "CLOSED" and s["shift_tip_pool_id"] is None
    ]
    if candidates and all(is_management(s) for s in candidates):      # rung 25
        raise ApiError("ERR_MANAGER_POOL_PARTICIPATION")

    active = [
        p
        for p in cascades.rows("policies")
        if p["location_id"] == location["id"] and p["status"] == "ACTIVE"
    ]
    if len(active) != 1:                                             # rung 33
        raise ApiError("ERR_NO_ACTIVE_POOL_POLICY")
    policy = active[0]

    for shift in shifts:                                             # rung 34
        if shift["time_status"] == "CLOSED" and shift["declaration_status"] not in (
            "DECLARED",
            "AMENDED",
        ):
            raise ApiError("ERR_UNDECLARED_SHIFT_IN_POOL")

    for pool in cascades.rows("pools"):                               # rung 46
        if (
            pool["location_id"] == location["id"]
            and pool["business_date"] == business_date
            and pool["contribution_status"] == "CONTRIBUTED"
        ):
            raise ApiError("ERR_POOL_DATE_DUPLICATE")

    contributors = contribution_input_set(policy, shifts)
    contributions = {}
    for shift in contributors:
        role = role_of(shift)
        received = (
            shift["declared_cash_tips_cents"] + shift["declared_charged_tips_cents"]
        )
        basis = (
            received
            if policy["contribution_basis"] == "TIPS_RECEIVED_PCT"
            else shift["gross_sales_cents"]
        )
        raw = calc.bps_of(basis, role["pool_contribution_pct_bps"])
        contributions[shift["id"]] = min(raw, received)

    total_contributed = sum(contributions.values())
    charges = tips_charges(location["id"], business_date)
    service_charge_tips = sum(c["amount_cents"] for c in charges)

    if total_contributed + service_charge_tips <= 0:                  # rung 52
        raise ApiError("ERR_EMPTY_POOL_NO_CONTRIBUTIONS")

    record = {
        "location_id": location["id"],
        "tip_pool_policy_id": policy["id"],
        "policy_version_pinned": policy["version"],
        "business_date": business_date,
        "contribution_status": "CONTRIBUTED",
        "distribution_status": "PENDING",
        "contributing_shift_count": sum(
            1 for amount in contributions.values() if amount > 0
        ),
        "participant_count": 0,
        "total_contributed_cents": total_contributed,
        "service_charge_tips_cents": service_charge_tips,
        "cc_fee_deducted_cents": 0,
        "net_pool_cents": total_contributed + service_charge_tips,
        "total_share_weight": 0,
        "distributed_cents": 0,
        "distributed_at": None,
        "reversed_at": None,
    }
    stamp_new(record)
    db.pools[record["id"]] = record

    for shift in contributors:
        contribution = contributions[shift["id"]]
        received = (
            shift["declared_cash_tips_cents"] + shift["declared_charged_tips_cents"]
        )
        shift["pool_contribution_cents"] = contribution
        shift["shift_tip_pool_id"] = record["id"]
        shift["retained_tips_cents"] = received - contribution
        touch(shift)

    for charge in charges:
        charge["status"] = "ALLOCATED"
        charge["allocated_pool_id"] = record["id"]
        touch(charge)

    cascades.recompute_location_pending(location)
    return object_response(view(record, serial.POOL), 201)


@bp.get("/shift-tip-pools/<pool_id>")
def read_pool(pool_id):
    authorize(ALL_ROLES)
    record = db.pools.get(pool_id)
    if record is None:
        raise ApiError("ERR_POOL_NOT_FOUND")
    return object_response(view(record, serial.POOL))


@bp.get("/shift-tip-pools")
def list_pools():
    authorize(ALL_ROLES)
    filters, limit, offset = parse_query(
        [
            f("location_id", "id"),
            f("tip_pool_policy_id", "id"),
            f("business_date", "date"),
            f("contribution_status", "enum", domain=CONTRIBUTION_STATUSES),
            f("distribution_status", "enum", domain=DISTRIBUTION_STATUSES),
        ]
    )
    rows = apply_filters(cascades.rows("pools"), filters)
    return paged(rows, serial.POOL, limit, offset)


# ---------------------------------------------------------------------------
# distribution
# ---------------------------------------------------------------------------

def pool_shifts(pool):
    return [s for s in cascades.rows("shifts") if s["shift_tip_pool_id"] == pool["id"]]


def card_fee(pool, policy, location):
    """The lawfully withholdable card fee, rounded per shift then summed."""
    if not policy["cc_fee_pass_through"] or location["cc_fee_policy"] == "PROHIBITED":
        return 0
    total = 0
    for shift in pool_shifts(pool):
        if shift["pool_contribution_cents"] <= 0:
            continue
        rate = shift["cc_processing_fee_bps"]
        if location["cc_fee_policy"] == "CAPPED_BPS":
            rate = min(rate, location["cc_fee_cap_bps"] or 0)
        total += calc.bps_of(shift["declared_charged_tips_cents"], rate)
    ceiling = pool["total_contributed_cents"] + pool["service_charge_tips_cents"]
    return min(total, ceiling)


def participants(pool, policy):
    out = []
    for shift in pool_shifts(pool):
        if shift["time_status"] != "CLOSED":
            continue
        role = role_of(shift)
        if role is None or role["is_management"]:
            continue
        if role["pool_share_points"] <= 0:
            continue
        if policy["pool_type"] == "TIPPED_ONLY" and role["tip_status"] != "TIPPED":
            continue
        out.append(shift)
    return out


def share_weight(policy, shift):
    points = role_of(shift)["pool_share_points"]
    if policy["share_basis"] == "HOURS_WEIGHTED_POINTS":
        return points * shift["scheduled_minutes"]
    return points


@bp.post("/shift-tip-pools/<pool_id>/distribute")
def distribute_pool(pool_id):
    authorize(["PayrollPreparer"])
    parse_body([])
    pool = db.pools.get(pool_id)
    if pool is None:
        raise ApiError("ERR_POOL_NOT_FOUND")

    if pool["distribution_status"] != "PENDING":                      # rung 16
        raise ApiError("ERR_POOL_ALREADY_DISTRIBUTED")
    if pool["contribution_status"] != "CONTRIBUTED":                   # rung 17
        raise ApiError("ERR_POOL_REVERSED")
    if pool["total_contributed_cents"] + pool["service_charge_tips_cents"] <= 0:
        raise ApiError("ERR_EMPTY_POOL_NO_CONTRIBUTIONS")             # rung 52

    location = db.locations.get(pool["location_id"])
    policy = db.policies.get(pool["tip_pool_policy_id"])
    people = participants(pool, policy)
    if not people:                                                    # rung 53
        raise ApiError("ERR_NO_ELIGIBLE_PARTICIPANTS")

    fee = card_fee(pool, policy, location)
    net = pool["total_contributed_cents"] + pool["service_charge_tips_cents"] - fee

    weights = {}
    items = []
    for shift in people:
        weight = share_weight(policy, shift)
        weights[shift["id"]] = weight
        items.append((shift["id"], weight, (shift["created_at"], shift["_seq"])))

    by_id = dict((s["id"], s) for s in people)
    distributed = 0
    recipients = set()
    for shift_id, allocated, won in calc.largest_remainder(net, items):
        shift = by_id[shift_id]
        row = {
            "shift_tip_pool_id": pool["id"],
            "employee_id": shift["employee_id"],
            "shift_id": shift["id"],
            "entry_type": "DISTRIBUTION",
            "share_weight": weights[shift_id],
            "allocated_cents": allocated,
            "remainder_cent_awarded": bool(won),
            "business_date": pool["business_date"],
        }
        stamp_new(row, with_version=False)
        db.allocations[row["id"]] = row
        distributed += allocated
        recipients.add(shift["employee_id"])

    pool["cc_fee_deducted_cents"] = fee
    pool["net_pool_cents"] = net
    pool["participant_count"] = len(people)
    pool["total_share_weight"] = sum(weights.values())
    pool["distributed_cents"] = distributed
    pool["distributed_at"] = db.now()
    pool["distribution_status"] = "DISTRIBUTED"
    touch(pool)

    for employee_id in sorted(recipients):
        employee = db.employees.get(employee_id)
        if employee is not None:
            cascades.recompute_employee_trailing(employee)

    if location is not None:
        cascades.recompute_location_pending(location)
    return object_response(view(pool, serial.POOL))


# ---------------------------------------------------------------------------
# reversal
# ---------------------------------------------------------------------------

def settled_money_exists(pool):
    """The fiscal guard: settled, already-paid money may not be unwound."""
    for period in cascades.rows("pay_periods"):
        if period["location_id"] != pool["location_id"]:
            continue
        if period["status"] != "APPROVED":
            continue
        if not cascades.date_in_period(period, pool["business_date"]):
            continue
        for line in cascades.period_lines(period["id"]):
            for correction in cascades.line_corrections(line["id"]):
                if correction["status"] == "APPLIED":
                    return True
    return False


@bp.post("/shift-tip-pools/<pool_id>/reverse")
def reverse_pool_endpoint(pool_id):
    authorize(["ComplianceOfficer"])
    parse_body([f("reason", "str")])
    pool = db.pools.get(pool_id)
    if pool is None:
        raise ApiError("ERR_POOL_NOT_FOUND")

    if pool["contribution_status"] != "CONTRIBUTED":                  # rung 17
        raise ApiError("ERR_POOL_REVERSED")
    if settled_money_exists(pool):
        raise ApiError("ERR_PAY_PERIOD_NOT_OPEN")

    cascades.reverse_pool(pool)
    return object_response(view(pool, serial.POOL))


# ---------------------------------------------------------------------------
# the pool-allocation ledger
# ---------------------------------------------------------------------------

@bp.get("/pool-allocations/<allocation_id>")
def read_allocation(allocation_id):
    actor = authorize(ALL_ROLES)
    record = db.allocations.get(allocation_id)
    if record is None:
        raise ApiError("ERR_RECORD_NOT_FOUND")
    check_employee_scope(actor, record["employee_id"])                 # rung 6
    return object_response(view(record, serial.ALLOCATION))


@bp.get("/pool-allocations")
def list_allocations():
    actor = authorize(ALL_ROLES)
    filters, limit, offset = parse_query(
        [
            f("shift_tip_pool_id", "id"),
            f("employee_id", "id"),
            f("shift_id", "id"),
            f("entry_type", "enum", domain=ENTRY_TYPES),
            f("business_date", "date"),
        ]
    )
    rows = apply_filters(cascades.rows("allocations"), filters)
    rows = scope_rows_by_employee(actor, rows)
    return paged(rows, serial.ALLOCATION, limit, offset)
