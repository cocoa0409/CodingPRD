"""Outsourced partners, the allocation waterfall and settlement (PRD 3.9)."""
from flask import Blueprint, g

import calc
from cascade import recompute_interval_capacity, require_not_frozen, set_fields
from core import (
    D, bad, body, created, envelope, fail, get, iso_date, new_row, ok, public, q4,
    rows, require_auth, v_date, v_enum, v_id, v_int, v_num, v_skill_array,
)
from listing import std_list, array_contains_filter

bp = Blueprint("partners", __name__)

PARTNER_READERS = ["CapacityPlanner", "WorkforceAnalyst", "SchedulingManager",
                   "SourcingManager", "PartnerRep"]
PARTNER_LIST_READERS = ["CapacityPlanner", "WorkforceAnalyst", "SchedulingManager",
                        "SourcingManager"]


def allocations_of_partner(partner_id):
    return [a for a in rows("partner_allocations") if a["outsource_partner_id"] == partner_id]


def allocations_of_interval(interval_plan_id):
    return [a for a in rows("partner_allocations") if a["interval_plan_id"] == interval_plan_id]


def partner_cap(partner):
    if partner["status"] == "PROBATION":
        return int(partner["commitment_floor_volume"])
    return int(partner["interval_max_volume"])


def recompute_partner_ledgers(partner):
    outstanding = 0
    invoice = 0
    for alloc in allocations_of_partner(partner["id"]):
        if alloc["status"] == "COMMITTED":
            outstanding += int(alloc["allocated_volume"])
        elif alloc["status"] == "SETTLED":
            invoice += int(alloc["settlement_amount_cents"])
    set_fields(partner, {
        "committed_volume_outstanding": outstanding,
        "invoice_total_cents": invoice,
    })


# ---------------------------------------------------------------------------
# Partner registration and the performance ladder
# ---------------------------------------------------------------------------
@bp.post("/outsource-partners")
def create_outsource_partner():
    require_auth(["SourcingManager"])
    b = body()
    from core import v_string
    legal_name = v_string(b, "legal_name", maxlen=120)
    skills = v_skill_array(b, "skill_codes")
    rate = v_int(b, "rate_per_contact_millicents", minimum=1)
    interval_max = v_int(b, "interval_max_volume", minimum=1)
    floor = v_int(b, "commitment_floor_volume", minimum=0)
    threshold = v_num(b, "performance_threshold_pct", exclusive_min=0, maximum=1)
    basis = v_enum(b, "billing_basis", ("COMMITMENT_FLOOR", "DELIVERED_ONLY"))
    if floor > interval_max:
        bad("commitment_floor_volume", "may not exceed interval_max_volume")
    if any(p["legal_name"] == legal_name for p in rows("outsource_partners")):
        bad("legal_name", "must be unique across all partners")
    row = new_row("outsource_partners", {
        "legal_name": legal_name,
        "skill_codes": skills,
        "rate_per_contact_millicents": rate,
        "interval_max_volume": interval_max,
        "commitment_floor_volume": floor,
        "performance_threshold_pct": q4(threshold),
        "billing_basis": basis,
        "status": "ACTIVE",
        "performance_report_count": 0,
        "latest_sl_attainment_pcts": [],
        "rolling_sl_attainment_pct": None,
        "consecutive_breach_count": 0,
        "committed_volume_outstanding": 0,
        "invoice_total_cents": 0,
    })
    return created(public(row))


@bp.get("/outsource-partners/<outsource_partner_id>")
def read_outsource_partner(outsource_partner_id):
    require_auth(PARTNER_READERS)
    return ok(public(get("outsource_partners", outsource_partner_id)))


@bp.get("/outsource-partners")
def list_outsource_partners():
    require_auth(PARTNER_LIST_READERS)
    return std_list(
        "outsource_partners",
        [("status", "status"), ("billing_basis", "billing_basis")],
        extra=array_contains_filter("skill_code", "skill_codes"),
    )


@bp.post("/outsource-partners/<outsource_partner_id>/performance-reports")
def file_performance_report(outsource_partner_id):
    require_auth(["SourcingManager"])
    b = body()
    period_end = v_date(b, "period_end_date")
    attainment = v_num(b, "sl_attainment_pct", minimum=0, maximum=1)
    partner = get("outsource_partners", outsource_partner_id)
    if partner["status"] == "SUSPENDED":
        fail("ERR_INVALID_STATE", "SUSPENDED is terminal on the partner ladder")
    entries = list(partner["latest_sl_attainment_pcts"])
    entries.append({
        "period_end_date": iso_date(period_end),
        "sl_attainment_pct": q4(attainment),
    })
    rolling = calc.rolling_sl_attainment(entries)
    breach = rolling is not None and rolling < D(partner["performance_threshold_pct"])
    updates = {
        "latest_sl_attainment_pcts": entries,
        "performance_report_count": int(partner["performance_report_count"]) + 1,
        "rolling_sl_attainment_pct": rolling,
    }
    suspend = False
    if partner["status"] == "ACTIVE":
        if breach:
            updates["status"] = "PROBATION"
            updates["consecutive_breach_count"] = 1
        else:
            updates["consecutive_breach_count"] = 0
    else:
        if breach:
            updates["status"] = "SUSPENDED"
            updates["consecutive_breach_count"] = 2
            suspend = True
        else:
            updates["status"] = "ACTIVE"
            updates["consecutive_breach_count"] = 0
    set_fields(partner, updates)
    from core import touch
    touch(partner)
    if suspend:
        intervals = {}
        for alloc in allocations_of_partner(partner["id"]):
            if alloc["status"] in ("PROPOSED", "COMMITTED"):
                set_fields(alloc, {"status": "REVOKED"})
                ip = get("interval_plans", alloc["interval_plan_id"])
                intervals[ip["id"]] = ip
        recompute_partner_ledgers(partner)
        for ip in intervals.values():
            recompute_interval_capacity(ip)
    return ok(public(partner))


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------
def eligible_for(partner, group):
    if partner["status"] == "SUSPENDED":
        fail("ERR_PARTNER_NOT_ELIGIBLE", "The partner is suspended")
    if group["skill_code"] not in partner["skill_codes"]:
        fail("ERR_PARTNER_NOT_ELIGIBLE",
             "The partner is not certified for skill %s" % group["skill_code"])


def new_allocation(partner, ip, volume, user_id):
    return new_row("partner_allocations", {
        "outsource_partner_id": partner["id"],
        "interval_plan_id": ip["id"],
        "allocated_volume": int(volume),
        "proposed_by_user_id": user_id,
        "committed_by_user_id": None,
        "delivered_volume": None,
        "settlement_floor_cents": None,
        "settlement_delivered_cents": None,
        "shortfall_penalty_cents": None,
        "settlement_amount_cents": None,
        "status": "PROPOSED",
    })


@bp.post("/partner-allocations")
def create_partner_allocation():
    uid, _role = require_auth(["SourcingManager"])
    b = body()
    partner_id = v_id(b, "outsource_partner_id")
    interval_id = v_id(b, "interval_plan_id")
    volume = v_int(b, "allocated_volume", minimum=1)
    partner = get("outsource_partners", partner_id)
    ip = get("interval_plans", interval_id)
    group = calc.group_of(ip)
    cycle = calc.cycle_of_group(group)
    require_not_frozen(cycle)
    eligible_for(partner, group)
    cap = partner_cap(partner)
    if volume < int(partner["commitment_floor_volume"]) or volume > cap:
        fail("ERR_PARTNER_VOLUME_OUT_OF_RANGE",
             "allocated_volume must lie between %s and %s for this partner"
             % (partner["commitment_floor_volume"], cap))
    row = new_allocation(partner, ip, volume, uid)
    return created(public(row))


@bp.post("/partner-allocations/generate")
def generate_partner_allocations():
    uid, _role = require_auth(["SourcingManager"])
    b = body()
    interval_id = v_id(b, "interval_plan_id")
    ip = get("interval_plans", interval_id)
    group = calc.group_of(ip)
    cycle = calc.cycle_of_group(group)
    require_not_frozen(cycle)
    need = int(ip["allocatable_volume"]) - int(ip["partner_committed_volume"])
    candidates = [
        p for p in rows("outsource_partners")
        if p["status"] in ("ACTIVE", "PROBATION")
        and group["skill_code"] in p["skill_codes"]
    ]
    candidates.sort(key=lambda p: (int(p["rate_per_contact_millicents"]),
                                   p["created_at"], p["_seq"]))
    minted = []
    for partner in candidates:
        if need <= 0:
            break
        take = min(partner_cap(partner), need)
        if take < int(partner["commitment_floor_volume"]):
            continue
        minted.append(new_allocation(partner, ip, take, uid))
        need -= take
    return envelope([public(r) for r in minted], "array", 201)


@bp.get("/partner-allocations/<partner_allocation_id>")
def read_partner_allocation(partner_allocation_id):
    require_auth(PARTNER_READERS)
    return ok(public(get("partner_allocations", partner_allocation_id)))


@bp.get("/partner-allocations")
def list_partner_allocations():
    uid, role = require_auth(PARTNER_READERS)
    from core import filter_arg
    if role == "PartnerRep":
        requested = filter_arg("outsource_partner_id")
        if requested is not None and requested != uid:
            fail("ERR_OWNERSHIP_VIOLATION",
                 "A partner representative may only list their own allocations")

        def own_only(items):
            return [r for r in items if r["outsource_partner_id"] == uid]

        return std_list(
            "partner_allocations",
            [("outsource_partner_id", "outsource_partner_id"),
             ("interval_plan_id", "interval_plan_id"),
             ("status", "status")],
            extra=own_only,
        )
    return std_list("partner_allocations", [
        ("outsource_partner_id", "outsource_partner_id"),
        ("interval_plan_id", "interval_plan_id"),
        ("status", "status"),
    ])


@bp.post("/partner-allocations/<partner_allocation_id>/commit")
def commit_partner_allocation(partner_allocation_id):
    uid, _role = require_auth(["SourcingManager"])
    b = body()
    expected = v_int(b, "expected_partner_version", minimum=1)
    alloc = get("partner_allocations", partner_allocation_id)
    partner = get("outsource_partners", alloc["outsource_partner_id"])
    if uid == alloc["proposed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The committing manager may not be the proposing manager")
    if expected != int(partner["version"]):
        fail("ERR_STALE_PARTNER_VERSION",
             "expected_partner_version %d does not match the partner's version %d"
             % (expected, int(partner["version"])))
    ip = get("interval_plans", alloc["interval_plan_id"])
    cycle = calc.cycle_of_interval(ip)
    require_not_frozen(cycle)
    if alloc["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "Only a proposed allocation may be committed")
    if partner["status"] == "SUSPENDED":
        fail("ERR_PARTNER_NOT_ELIGIBLE", "The partner is suspended")
    volume = int(alloc["allocated_volume"])
    if int(ip["partner_committed_volume"]) + volume > int(ip["allocatable_volume"]):
        fail("ERR_ALLOCATION_CAPACITY_EXCEEDED",
             "The interval cannot absorb another %d committed contacts" % volume)
    if volume < int(partner["commitment_floor_volume"]):
        fail("ERR_PARTNER_VOLUME_OUT_OF_RANGE",
             "allocated_volume is below the partner's commitment floor")
    set_fields(alloc, {"status": "COMMITTED", "committed_by_user_id": uid})
    recompute_partner_ledgers(partner)
    from core import touch
    touch(partner)
    recompute_interval_capacity(ip)
    return ok(public(alloc))


@bp.post("/partner-allocations/<partner_allocation_id>/revoke")
def revoke_partner_allocation(partner_allocation_id):
    require_auth(["SourcingManager"])
    alloc = get("partner_allocations", partner_allocation_id)
    ip = get("interval_plans", alloc["interval_plan_id"])
    cycle = calc.cycle_of_interval(ip)
    require_not_frozen(cycle)
    if alloc["status"] not in ("PROPOSED", "COMMITTED"):
        fail("ERR_INVALID_STATE", "Only a proposed or committed allocation may be revoked")
    was_committed = alloc["status"] == "COMMITTED"
    set_fields(alloc, {"status": "REVOKED"})
    if was_committed:
        recompute_partner_ledgers(get("outsource_partners", alloc["outsource_partner_id"]))
        recompute_interval_capacity(ip)
    return ok(public(alloc))


@bp.post("/partner-allocations/<partner_allocation_id>/settle")
def settle_partner_allocation(partner_allocation_id):
    require_auth(["SourcingManager"])
    b = body()
    delivered = v_int(b, "delivered_volume", minimum=0)
    alloc = get("partner_allocations", partner_allocation_id)
    partner = get("outsource_partners", alloc["outsource_partner_id"])
    ip = get("interval_plans", alloc["interval_plan_id"])
    cycle = calc.cycle_of_interval(ip)
    require_not_frozen(cycle)
    if alloc["status"] != "COMMITTED":
        fail("ERR_ALLOCATION_NOT_COMMITTED", "Settlement is only legal from COMMITTED")
    if partner["billing_basis"] == "COMMITMENT_FLOOR" \
            and delivered < int(partner["commitment_floor_volume"]):
        fail("ERR_COMMITMENT_FLOOR_BREACH",
             "delivered_volume is below the partner's commitment floor")
    floor_cents, delivered_cents, penalty, amount = calc.partner_settlement(
        int(alloc["allocated_volume"]), delivered, partner
    )
    set_fields(alloc, {
        "delivered_volume": delivered,
        "settlement_floor_cents": floor_cents,
        "settlement_delivered_cents": delivered_cents,
        "shortfall_penalty_cents": penalty,
        "settlement_amount_cents": amount,
        "status": "SETTLED",
    })
    recompute_partner_ledgers(partner)
    recompute_interval_capacity(ip)
    return ok(public(alloc))
