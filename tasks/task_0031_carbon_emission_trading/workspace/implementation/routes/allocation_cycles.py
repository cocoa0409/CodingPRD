"""AllocationCycle, Allocation, Objection, Settlement endpoints."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import clock
import db
import errors
import helpers
import response
from middleware import auth_required, get_actor
from serializers import (
    allocation_cycle_dict,
    allocation_dict,
    objection_dict,
    annual_settlement_dict,
)
from services import audit
from services.calculations import (
    calc_allocation_total,
    calc_revised_allocation,
    calc_annual_settlement,
)
from helpers import to_dec, bump


bp = Blueprint("allocation_cycles", __name__)


def _validate_ratios(free_paid_ratio, ccer_cap_pct):
    fpr = to_dec(free_paid_ratio)
    cap = to_dec(ccer_cap_pct)
    if fpr < 0 or fpr > 1:
        errors.raise_error(errors.ERR_INVALID_RATIO, "free_paid_ratio must be in [0, 1].")
    if cap < 0 or cap > Decimal("0.20"):
        errors.raise_error(errors.ERR_INVALID_RATIO, "ccer_cap_pct must be in [0, 0.20].")


@bp.route("/allocation-cycles", methods=["POST"])
@auth_required("Regulator")
def create_cycle():
    body = helpers.get_json_body()
    helpers.require_fields(body, ["cycle_year", "free_paid_ratio", "ccer_cap_pct",
                                  "objection_deadline", "compliance_deadline"])
    # Ratio validation (priority 13).
    _validate_ratios(body["free_paid_ratio"], body["ccer_cap_pct"])
    # Uniqueness on cycle_year.
    for c in db.allocation_cycles.values():
        if c["cycle_year"] == body["cycle_year"]:
            errors.raise_error(errors.ERR_INVALID_INPUT,
                               f"AllocationCycle for cycle_year {body['cycle_year']} already exists.")
    common = helpers.common_create()
    c = {
        "id": db.new_id(),
        "cycle_year": int(body["cycle_year"]),
        "status": "DRAFT",
        "free_paid_ratio": to_dec(body["free_paid_ratio"]),
        "ccer_cap_pct": to_dec(body["ccer_cap_pct"]),
        "publication_date": None,
        "objection_deadline": clock.parse_iso(body["objection_deadline"]),
        "compliance_deadline": clock.parse_iso(body["compliance_deadline"]),
        "settlement_date": None,
        **common,
    }
    db.allocation_cycles[c["id"]] = c
    return response.created(allocation_cycle_dict(c))


@bp.route("/allocation-cycles/<cid>", methods=["GET"])
@auth_required("Regulator", "Enterprise")
def read_cycle(cid):
    c = db.allocation_cycles.get(cid)
    if c is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"AllocationCycle {cid} not found.")
    out = allocation_cycle_dict(c)
    # Nested allocations: PRD §3.2's publish/finalize cascade mutates each
    # Allocation's status and computed quotas; surface them here so callers
    # can observe the cascade without an enumerate-allocations endpoint
    # (which PRD does not expose).
    cycle_allocs = [a for a in db.allocations.values() if a["cycle_id"] == cid]
    cycle_allocs.sort(key=lambda a: a["created_at"])
    out["allocations"] = [allocation_dict(a) for a in cycle_allocs]
    return response.ok(out)


@bp.route("/allocation-cycles/<cid>/allocations", methods=["POST"])
@auth_required("Regulator")
def propose_allocation(cid):
    c = db.allocation_cycles.get(cid)
    if c is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"AllocationCycle {cid} not found.")
    if c["status"] != "DRAFT":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Cycle must be DRAFT to add allocations; is {c['status']}.")
    body = helpers.get_json_body()
    helpers.require_fields(body, ["enterprise_id", "method"])
    if body["method"] not in ("INDUSTRY_BENCHMARK", "HISTORICAL_EMISSION"):
        errors.raise_error(errors.ERR_INVALID_INPUT, "Invalid method.")
    enterprise_id = body["enterprise_id"]
    if enterprise_id not in db.enterprises:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Enterprise {enterprise_id} not found.")

    # Method-specific inputs
    if body["method"] == "INDUSTRY_BENCHMARK":
        if "activity_volume" not in body or "benchmark_factor" not in body:
            errors.raise_error(errors.ERR_INVALID_INPUT,
                               "INDUSTRY_BENCHMARK requires activity_volume and benchmark_factor.")
    else:
        if "historical_baseline" not in body:
            errors.raise_error(errors.ERR_INVALID_INPUT,
                               "HISTORICAL_EMISSION requires historical_baseline.")

    common = helpers.common_create()
    a = {
        "id": db.new_id(),
        "cycle_id": cid,
        "enterprise_id": enterprise_id,
        "method": body["method"],
        "activity_volume": to_dec(body["activity_volume"]) if body.get("activity_volume") is not None else None,
        "benchmark_factor": to_dec(body["benchmark_factor"]) if body.get("benchmark_factor") is not None else None,
        "historical_baseline": to_dec(body["historical_baseline"]) if body.get("historical_baseline") is not None else None,
        "total_quota": None,
        "free_quota": None,
        "paid_quota": None,
        "status": "PROPOSED",
        **common,
    }
    db.allocations[a["id"]] = a
    return response.created(allocation_dict(a))


@bp.route("/allocation-cycles/<cid>/publish", methods=["POST"])
@auth_required("Regulator")
def publish_cycle(cid):
    c = db.allocation_cycles.get(cid)
    if c is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"AllocationCycle {cid} not found.")
    if c["status"] != "DRAFT":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Cycle must be DRAFT to publish; is {c['status']}.")
    body = helpers.get_json_body()
    helpers.check_occ(c, body.get("version"))

    cycle_allocations = [a for a in db.allocations.values() if a["cycle_id"] == cid]
    for a in cycle_allocations:
        if a["status"] != "PROPOSED":
            errors.raise_error(errors.ERR_INVALID_STATE,
                               "All allocations in cycle must be in PROPOSED state to publish.")

    # Cascade: compute totals, transition each Allocation.
    for a in cycle_allocations:
        total, free, paid = calc_allocation_total(
            a["method"], a.get("activity_volume"), a.get("benchmark_factor"),
            a.get("historical_baseline"), c["free_paid_ratio"],
        )
        a["total_quota"] = total
        a["free_quota"] = free
        a["paid_quota"] = paid
        a["status"] = "PUBLISHED"
        bump(a)

    c["status"] = "PUBLISHED"
    c["publication_date"] = clock.now()
    bump(c)
    # Audit log
    audit.append(
        subject_type="QUOTA_CHANGE",
        subject_id=c["id"],
        enterprise_id=None,
        action="ALLOCATIONS_PUBLISHED",
    )

    # Auto-transition to OBJECTION_OPEN if before objection_deadline.
    if clock.now() < c["objection_deadline"]:
        c["status"] = "OBJECTION_OPEN"
        bump(c)

    return response.ok(allocation_cycle_dict(c))


@bp.route("/allocations/<aid>/objections", methods=["POST"])
@auth_required("Enterprise")
def file_objection(aid):
    a = db.allocations.get(aid)
    if a is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Allocation {aid} not found.")
    body = helpers.get_json_body()
    helpers.require_fields(body, ["filer_enterprise_id", "ground"])
    user_id, _ = get_actor()
    # Ownership: filer_enterprise_id must equal allocation's enterprise_id AND acting user.
    if body["filer_enterprise_id"] != a["enterprise_id"] or user_id != a["enterprise_id"]:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION,
                           "Acting enterprise does not own this allocation.")
    # Duplicate objection check (concurrency-rule error) takes priority over generic
    # state error: a second filing while the first is still PENDING returns
    # ERR_OBJECTION_ALREADY_PENDING (scaffold §1.2.1).
    for o in db.objections.values():
        if o["allocation_id"] == aid and o["status"] == "PENDING":
            errors.raise_error(errors.ERR_OBJECTION_ALREADY_PENDING,
                               "An objection on this allocation is already pending.")
    if a["status"] != "PUBLISHED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Allocation must be PUBLISHED to file an objection; is {a['status']}.")
    # Window check
    cycle = db.allocation_cycles[a["cycle_id"]]
    if clock.now() >= cycle["objection_deadline"]:
        errors.raise_error(errors.ERR_WINDOW_CLOSED, "Objection window closed.")

    now = clock.now()
    obj = {
        "id": db.new_id(),
        "allocation_id": aid,
        "filer_enterprise_id": body["filer_enterprise_id"],
        "ground": body["ground"],
        "status": "PENDING",
        "revised_total_quota": None,
        "filed_at": now,
        "resolved_at": None,
        "created_at": now,
    }
    db.objections[obj["id"]] = obj
    a["status"] = "OBJECTED"
    bump(a)
    return response.created(objection_dict(obj))


@bp.route("/objections/<oid>/uphold", methods=["POST"])
@auth_required("Regulator")
def uphold_objection(oid):
    o = db.objections.get(oid)
    if o is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Objection {oid} not found.")
    if o["status"] != "PENDING":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Objection must be PENDING; is {o['status']}.")
    body = helpers.get_json_body()
    helpers.require_fields(body, ["revised_total_quota"])
    a = db.allocations[o["allocation_id"]]
    cycle = db.allocation_cycles[a["cycle_id"]]
    revised = to_dec(body["revised_total_quota"])
    total, free, paid = calc_revised_allocation(revised, cycle["free_paid_ratio"])
    a["total_quota"] = total
    a["free_quota"] = free
    a["paid_quota"] = paid
    a["status"] = "REVISED"
    bump(a)
    o["status"] = "UPHELD"
    o["revised_total_quota"] = revised
    o["resolved_at"] = clock.now()
    return response.ok(objection_dict(o))


@bp.route("/objections/<oid>/reject", methods=["POST"])
@auth_required("Regulator")
def reject_objection(oid):
    o = db.objections.get(oid)
    if o is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Objection {oid} not found.")
    if o["status"] != "PENDING":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Objection must be PENDING; is {o['status']}.")
    a = db.allocations[o["allocation_id"]]
    a["status"] = "PUBLISHED"
    bump(a)
    o["status"] = "REJECTED"
    o["resolved_at"] = clock.now()
    return response.ok(objection_dict(o))


@bp.route("/allocation-cycles/<cid>/finalize", methods=["POST"])
@auth_required("Regulator")
def finalize_cycle(cid):
    c = db.allocation_cycles.get(cid)
    if c is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"AllocationCycle {cid} not found.")
    if c["status"] != "OBJECTION_OPEN":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Cycle must be OBJECTION_OPEN to finalize; is {c['status']}.")
    body = helpers.get_json_body()
    helpers.check_occ(c, body.get("version"))
    if clock.now() < c["objection_deadline"]:
        errors.raise_error(errors.ERR_WINDOW_CLOSED,
                           "Cannot finalize before objection_deadline.")
    # Any pending objection blocks finalize.
    for o in db.objections.values():
        a = db.allocations[o["allocation_id"]]
        if a["cycle_id"] == cid and o["status"] == "PENDING":
            errors.raise_error(errors.ERR_INVALID_STATE,
                               "All objections must be resolved before finalize.")

    cycle_allocations = [a for a in db.allocations.values() if a["cycle_id"] == cid]
    for a in cycle_allocations:
        if a["status"] not in ("PUBLISHED", "REVISED"):
            errors.raise_error(errors.ERR_INVALID_STATE,
                               f"Allocation {a['id']} not in PUBLISHED/REVISED.")
        a["status"] = "FINALIZED"
        bump(a)
        # Cascade to enterprise.
        e = db.enterprises[a["enterprise_id"]]
        e["quota_balance"] = to_dec(e["quota_balance"]) + to_dec(a["free_quota"])
        e["paid_quota_balance"] = to_dec(e["paid_quota_balance"]) + to_dec(a["paid_quota"])
        if e["account_status"] == "PENDING":
            e["account_status"] = "OPEN"
        bump(e)
        # Audit log per enterprise.
        delta = to_dec(a["free_quota"]) + to_dec(a["paid_quota"])
        audit.append(
            subject_type="QUOTA_CHANGE",
            subject_id=e["id"],
            enterprise_id=e["id"],
            action="QUOTA_ALLOCATED",
            delta_quota=delta,
        )

    c["status"] = "FINALIZED"
    bump(c)
    # Auto-transition to COMPLIANCE_OPEN (per scaffold; emission reporting begins).
    c["status"] = "COMPLIANCE_OPEN"
    bump(c)
    return response.ok(allocation_cycle_dict(c))


@bp.route("/allocation-cycles/<cid>/settle", methods=["POST"])
@auth_required("Regulator")
def settle_cycle(cid):
    c = db.allocation_cycles.get(cid)
    if c is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"AllocationCycle {cid} not found.")
    if c["status"] != "COMPLIANCE_OPEN":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Cycle must be COMPLIANCE_OPEN to settle; is {c['status']}.")
    if clock.now() < c["compliance_deadline"]:
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Cannot settle before compliance_deadline.")
    # All declarations for enterprises in this cycle must be in {COMPLIANT, NON_COMPLIANT, PENALIZED, FINALIZED}.
    cycle_year = c["cycle_year"]
    cycle_enterprise_ids = {a["enterprise_id"] for a in db.allocations.values() if a["cycle_id"] == cid}
    declarations_by_ent = {}
    for d in db.compliance_declarations.values():
        if d["cycle_year"] == cycle_year and d["enterprise_id"] in cycle_enterprise_ids:
            declarations_by_ent[d["enterprise_id"]] = d

    for eid in cycle_enterprise_ids:
        d = declarations_by_ent.get(eid)
        if d is None:
            errors.raise_error(errors.ERR_INVALID_STATE,
                               f"Enterprise {eid} has not submitted a declaration for cycle {cycle_year}.")
        if d["status"] not in ("COMPLIANT", "NON_COMPLIANT", "PENALIZED", "FINALIZED"):
            errors.raise_error(errors.ERR_INVALID_STATE,
                               f"Declaration for enterprise {eid} not in finalized status (got {d['status']}).")

    # For each enterprise, create AnnualSettlement.
    for eid in cycle_enterprise_ids:
        e = db.enterprises[eid]
        d = declarations_by_ent[eid]
        retired_quota = to_dec(d["declared_offset_quota"])
        opening_quota = to_dec(e["quota_balance"]) + to_dec(e["paid_quota_balance"]) + retired_quota

        # Net traded (QUOTA only).
        net = Decimal("0")
        for t in db.trades.values():
            if t["instrument"] != "QUOTA":
                continue
            buy_o = db.trading_orders.get(t["buy_order_id"])
            sell_o = db.trading_orders.get(t["sell_order_id"])
            if buy_o is None or sell_o is None:
                continue
            if buy_o["enterprise_id"] == eid:
                net += to_dec(t["quantity"])
            if sell_o["enterprise_id"] == eid:
                net -= to_dec(t["quantity"])

        # Mandatory deductions: sum of penalty mandatory_deduction_amount for this enterprise this cycle.
        deductions = Decimal("0")
        for p in db.penalty_orders.values():
            if p["enterprise_id"] == eid and p["cycle_year"] == cycle_year:
                deductions += to_dec(p["mandatory_deduction_amount"])

        # Next cycle's allocation total for this enterprise (0 if none).
        next_cycle = None
        for cc in db.allocation_cycles.values():
            if cc["cycle_year"] == cycle_year + 1:
                next_cycle = cc
                break
        next_alloc_total = Decimal("0")
        if next_cycle is not None:
            for a in db.allocations.values():
                if a["cycle_id"] == next_cycle["id"] and a["enterprise_id"] == eid:
                    if a.get("total_quota") is not None:
                        next_alloc_total = to_dec(a["total_quota"])
                    break

        result = calc_annual_settlement(opening_quota, net, retired_quota,
                                        deductions, next_alloc_total)
        common = helpers.common_create()
        s = {
            "id": db.new_id(),
            "cycle_id": cid,
            "cycle_year": cycle_year,
            "enterprise_id": eid,
            "opening_quota": opening_quota,
            "net_traded_quota": net,
            "retired_quota": retired_quota,
            "closing_balance": result["closing_balance"],
            "carry_forward_amount": result["carry_forward_amount"],
            "repurchase_amount": result["repurchase_amount"],
            "deficit_purchase_amount": result["deficit_purchase_amount"],
            "status": "RECONCILED",
            **common,
        }
        db.annual_settlements[s["id"]] = s

    c["status"] = "SETTLED"
    c["settlement_date"] = clock.now()
    bump(c)
    return response.ok(allocation_cycle_dict(c))


@bp.route("/allocation-cycles/<cid>/close", methods=["POST"])
@auth_required("Regulator")
def close_cycle(cid):
    c = db.allocation_cycles.get(cid)
    if c is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"AllocationCycle {cid} not found.")
    if c["status"] != "SETTLED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Cycle must be SETTLED to close; is {c['status']}.")
    cycle_year = c["cycle_year"]
    # All settlements for this cycle must transition to CLOSED first.
    cycle_settlements = [s for s in db.annual_settlements.values() if s["cycle_id"] == cid]
    for s in cycle_settlements:
        if s["status"] not in ("RECONCILED", "CLOSED"):
            errors.raise_error(errors.ERR_INVALID_STATE,
                               f"AnnualSettlement {s['id']} not ready for close.")
    # All penalty orders for this cycle must be PAID.
    for p in db.penalty_orders.values():
        if p["cycle_year"] == cycle_year and p["payment_status"] != "PAID":
            errors.raise_error(errors.ERR_INVALID_STATE,
                               f"PenaltyOrder {p['id']} is not PAID.")
    # Transition settlements to CLOSED.
    for s in cycle_settlements:
        s["status"] = "CLOSED"
        bump(s)
    # Cascade declarations for this cycle: COMPLIANT/PENALIZED -> FINALIZED.
    cycle_enterprise_ids = {a["enterprise_id"] for a in db.allocations.values() if a["cycle_id"] == cid}
    for d in db.compliance_declarations.values():
        if d["cycle_year"] == cycle_year and d["enterprise_id"] in cycle_enterprise_ids:
            if d["status"] == "COMPLIANT":
                d["status"] = "FINALIZED"
                bump(d)
            elif d["status"] == "PENALIZED":
                # Need penalty paid + credit_record_reported (which is set on PAID).
                penalty = next((p for p in db.penalty_orders.values()
                                if p["declaration_id"] == d["id"]), None)
                if penalty and penalty["payment_status"] == "PAID" and penalty["credit_record_reported"]:
                    d["status"] = "FINALIZED"
                    bump(d)
    # Cascade enterprise account_status: OPEN -> CLOSED.
    for eid in cycle_enterprise_ids:
        e = db.enterprises[eid]
        if e["account_status"] == "OPEN":
            e["account_status"] = "CLOSED"
            bump(e)
    c["status"] = "CLOSED"
    bump(c)
    audit.append(
        subject_type="QUOTA_CHANGE",
        subject_id=c["id"],
        enterprise_id=None,
        action="CYCLE_CLOSED",
    )
    return response.ok(allocation_cycle_dict(c))


# --- Annual Settlements list ---

@bp.route("/annual-settlements", methods=["GET"])
@auth_required("Regulator", "Enterprise")
def list_settlements():
    limit, offset = helpers.parse_pagination()
    user_id, user_role = get_actor()
    items = list(db.annual_settlements.values())
    eid = request.args.get("enterprise_id")
    cy = request.args.get("cycle_year")
    if eid is not None:
        items = [s for s in items if s["enterprise_id"] == eid]
    if cy is not None:
        try:
            cy_i = int(cy)
        except ValueError:
            errors.raise_error(errors.ERR_INVALID_INPUT, "cycle_year must be int.")
        items = [s for s in items if s["cycle_year"] == cy_i]
    if user_role == "Enterprise":
        items = [s for s in items if s["enterprise_id"] == user_id]
    items.sort(key=lambda x: x["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok([annual_settlement_dict(s) for s in page],
                            limit=limit, offset=offset, total_count=total)
