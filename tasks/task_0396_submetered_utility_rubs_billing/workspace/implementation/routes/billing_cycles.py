"""BillingCycle orchestration: lock, allocate, issue, close (PRD §3.6, §3.7)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import success, list_success
from services.common import (
    get_json_body, require_fields, serialize, parse_iso, parse_date_field,
    pagination_params, paginate, sort_by_creation,
)
from services.calculations import (
    largest_remainder_allocation, admin_fee_proration,
    recompute_statement_totals, NET_DAYS,
)

billing_cycles_bp = Blueprint("billing_cycles", __name__)


@billing_cycles_bp.route("/billing-cycles", methods=["POST"])
@require_roles("PropertyManager")
def create_cycle():
    body = get_json_body()
    require_fields(body, "property_id", "utility_id", "vendor_bill_id",
                   "period_label", "period_start", "period_end")

    property_id = body["property_id"]
    if property_id not in db.properties:
        raise ApiError("ERR_NOT_FOUND", "Property not found")
    utility_id = body["utility_id"]
    if utility_id not in db.utilities:
        raise ApiError("ERR_NOT_FOUND", "Utility not found")
    vendor_bill_id = body["vendor_bill_id"]
    if vendor_bill_id not in db.vendor_bills:
        raise ApiError("ERR_NOT_FOUND", "VendorBill not found")

    period_label = body["period_label"]
    if not isinstance(period_label, str) or not period_label.strip():
        raise ApiError("ERR_INVALID_REQUEST", "period_label must be a non-empty string")

    period_start = parse_date_field(body["period_start"], "period_start")
    period_end = parse_date_field(body["period_end"], "period_end")
    if period_end < period_start:
        raise ApiError("ERR_INVALID_REQUEST", "period_end must be >= period_start")

    record = {
        "property_id": property_id,
        "utility_id": utility_id,
        "vendor_bill_id": vendor_bill_id,
        "period_label": period_label,
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "allocated_total_cents": 0,
        "status": "OPEN",
    }
    db.stamp_create(record)
    db.billing_cycles[record["id"]] = record

    # Opening a cycle sets the property's current_period_label.
    prop = db.properties[property_id]
    prop["current_period_label"] = period_label
    db.touch(prop)

    return success(serialize(record), status=201)


@billing_cycles_bp.route("/billing-cycles/<cycle_id>", methods=["GET"])
@require_roles("PropertyManager", "Auditor")
def get_cycle(cycle_id):
    record = db.billing_cycles.get(cycle_id)
    if record is None:
        raise ApiError("ERR_NOT_FOUND", "BillingCycle not found")
    return success(serialize(record), status=200)


@billing_cycles_bp.route("/billing-cycles", methods=["GET"])
@require_roles("PropertyManager", "Auditor")
def list_cycles():
    property_id = request.args.get("property_id")
    utility_id = request.args.get("utility_id")
    period_label = request.args.get("period_label")
    vendor_bill_id = request.args.get("vendor_bill_id")
    status = request.args.get("status")
    items = list(db.billing_cycles.values())
    if property_id is not None:
        items = [c for c in items if c["property_id"] == property_id]
    if utility_id is not None:
        items = [c for c in items if c["utility_id"] == utility_id]
    if period_label is not None:
        items = [c for c in items if c["period_label"] == period_label]
    if vendor_bill_id is not None:
        items = [c for c in items if c["vendor_bill_id"] == vendor_bill_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_by_creation(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return list_success([serialize(c) for c in page], limit, offset, total)


def _lease_overlaps_period(lease, period_start, period_end):
    """Does the lease's occupancy interval overlap [period_start, period_end]?"""
    move_in = parse_date_field(lease["move_in_date"], "move_in_date")
    move_out = (parse_date_field(lease["move_out_date"], "move_out_date")
                if lease["move_out_date"] else None)
    # Occupancy [move_in, move_out] (move_out inclusive; null=open-ended).
    if move_in > period_end:
        return False
    if move_out is not None and move_out < period_start:
        return False
    return True


def _billed_units_consumption(cycle):
    """Map unit_id -> total VALIDATED-read consumption for the cycle period."""
    property_id = cycle["property_id"]
    utility_id = cycle["utility_id"]
    period_label = cycle["period_label"]
    per_unit = {}
    for read in db.meter_reads.values():
        if read["status"] != "VALIDATED":
            continue
        if read["property_id"] != property_id or read["period_label"] != period_label:
            continue
        meter = db.meters.get(read["meter_id"])
        if meter is None or meter["utility_id"] != utility_id:
            continue
        unit_id = meter["assigned_unit_id"]
        if unit_id is None:
            continue
        per_unit[unit_id] = per_unit.get(unit_id, 0) + read["consumption"]
    return per_unit


def _active_leases_for_period(cycle):
    """Map unit_id -> chosen Lease (ACTIVE/NOTICE_GIVEN/MOVED_OUT) overlapping period.

    If multiple eligible leases overlap a unit, pick the earliest-created one.
    """
    property_id = cycle["property_id"]
    period_start = parse_date_field(cycle["period_start"], "period_start")
    period_end = parse_date_field(cycle["period_end"], "period_end")
    eligible = {}
    for lease in sort_by_creation(list(db.leases.values())):
        if lease["property_id"] != property_id:
            continue
        if lease["status"] not in ("ACTIVE", "NOTICE_GIVEN", "MOVED_OUT"):
            continue
        if not _lease_overlaps_period(lease, period_start, period_end):
            continue
        unit_id = lease["unit_id"]
        if unit_id not in eligible:
            eligible[unit_id] = lease
    return eligible


@billing_cycles_bp.route("/billing-cycles/<cycle_id>/lock-reads", methods=["POST"])
@require_roles("PropertyManager")
def lock_reads(cycle_id):
    cycle = db.billing_cycles.get(cycle_id)
    if cycle is None:
        raise ApiError("ERR_NOT_FOUND", "BillingCycle not found")
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "BillingCycle is not OPEN")

    utility = db.utilities[cycle["utility_id"]]
    if utility["allocation_method"] == "CONSUMPTION":
        # Every assigned, non-RETIRED meter of the property+utility must have
        # exactly one VALIDATED read for the period, none in
        # SUBMITTED/FLAGGED/RE_READ_REQUESTED.
        for meter in db.meters.values():
            if meter["property_id"] != cycle["property_id"]:
                continue
            if meter["utility_id"] != cycle["utility_id"]:
                continue
            if meter["status"] != "ASSIGNED":
                continue
            reads = [r for r in db.meter_reads.values()
                     if r["meter_id"] == meter["id"]
                     and r["period_label"] == cycle["period_label"]]
            validated = [r for r in reads if r["status"] == "VALIDATED"]
            unresolved = [r for r in reads
                          if r["status"] in ("SUBMITTED", "FLAGGED", "RE_READ_REQUESTED")]
            if len(validated) != 1 or unresolved:
                raise ApiError("ERR_READS_NOT_VALIDATED", "Reads not fully validated")

    cycle["status"] = "READS_LOCKED"
    db.touch(cycle)
    return success(serialize(cycle), status=200)


@billing_cycles_bp.route("/billing-cycles/<cycle_id>/allocate", methods=["POST"])
@require_roles("PropertyManager")
def allocate(cycle_id):
    cycle = db.billing_cycles.get(cycle_id)
    if cycle is None:
        raise ApiError("ERR_NOT_FOUND", "BillingCycle not found")
    if cycle["status"] != "READS_LOCKED":
        raise ApiError("ERR_INVALID_STATE", "BillingCycle is not READS_LOCKED")

    vb = db.vendor_bills[cycle["vendor_bill_id"]]
    if vb["status"] != "APPROVED":
        raise ApiError("ERR_VENDOR_BILL_NOT_APPROVED", "VendorBill is not APPROVED")

    utility = db.utilities[cycle["utility_id"]]
    recoverable = vb["recoverable_cents"]

    if utility["allocation_method"] == "CONSUMPTION":
        per_unit_weight = _billed_units_consumption(cycle)
    else:  # RUBS
        eligible_leases = _active_leases_for_period(cycle)
        per_unit_weight = {uid: lease["occupant_count"]
                           for uid, lease in eligible_leases.items()}

    weighted_units = []
    for unit_id, weight in per_unit_weight.items():
        unit = db.units.get(unit_id)
        seq = unit["_seq"] if unit is not None else 0
        weighted_units.append({"unit_id": unit_id, "weight": weight, "seq": seq})

    charges = largest_remainder_allocation(recoverable, weighted_units)

    # Stash per-unit charges on the cycle for use at issue-statements time.
    cycle["_unit_charges"] = charges
    cycle["allocated_total_cents"] = sum(charges.values())
    cycle["status"] = "ALLOCATED"
    db.touch(cycle)

    # Cascade: VendorBill APPROVED -> ALLOCATED.
    vb["status"] = "ALLOCATED"
    db.touch(vb)

    return success(serialize(cycle), status=200)


@billing_cycles_bp.route("/billing-cycles/<cycle_id>/issue-statements", methods=["POST"])
@require_roles("PropertyManager")
def issue_statements(cycle_id):
    cycle = db.billing_cycles.get(cycle_id)
    if cycle is None:
        raise ApiError("ERR_NOT_FOUND", "BillingCycle not found")
    if cycle["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE", "BillingCycle is not ALLOCATED")

    eligible_leases = _active_leases_for_period(cycle)
    if not eligible_leases:
        raise ApiError("ERR_NO_BILLABLE_LEASES", "No billable leases for the period")

    utility = db.utilities[cycle["utility_id"]]
    unit_charges = cycle.get("_unit_charges", {})
    period_start = parse_date_field(cycle["period_start"], "period_start")
    period_end = parse_date_field(cycle["period_end"], "period_end")

    # Issue date = server clock date; due_date = issue date + NET_DAYS.
    issue_dt = db.get_clock()
    due_dt = issue_dt
    from datetime import timedelta
    due_dt = issue_dt + timedelta(days=NET_DAYS)
    due_date_str = due_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{due_dt.microsecond // 1000:03d}Z"

    # Order statements by lease creation order for determinism.
    for unit_id, lease in sorted(eligible_leases.items(),
                                 key=lambda kv: kv[1]["_seq"]):
        utility_charge = unit_charges.get(unit_id, 0)
        move_in = parse_date_field(lease["move_in_date"], "move_in_date")
        move_out = (parse_date_field(lease["move_out_date"], "move_out_date")
                    if lease["move_out_date"] else None)
        admin_fee = admin_fee_proration(
            utility["monthly_admin_fee_cents"], period_start, period_end, move_in, move_out
        )

        stmt = {
            "billing_cycle_id": cycle["id"],
            "lease_id": lease["id"],
            "unit_id": unit_id,
            "property_id": cycle["property_id"],
            "utility_charge_cents": utility_charge,
            "admin_fee_cents": admin_fee,
            "late_fee_cents": 0,
            "credit_cents": 0,
            "amount_paid_cents": 0,
            "total_due_cents": 0,
            "balance_due_cents": 0,
            "due_date": due_date_str,
            "delivery_status": "ISSUED",
            "payment_status": "UNPAID",
        }
        recompute_statement_totals(stmt)
        db.stamp_create(stmt)
        db.tenant_statements[stmt["id"]] = stmt

    cycle["status"] = "STATEMENTS_ISSUED"
    db.touch(cycle)
    return success(serialize(cycle), status=200)


@billing_cycles_bp.route("/billing-cycles/<cycle_id>/close", methods=["POST"])
@require_roles("PropertyManager")
def close_cycle(cycle_id):
    cycle = db.billing_cycles.get(cycle_id)
    if cycle is None:
        raise ApiError("ERR_NOT_FOUND", "BillingCycle not found")
    if cycle["status"] != "STATEMENTS_ISSUED":
        raise ApiError("ERR_INVALID_STATE", "BillingCycle is not STATEMENTS_ISSUED")

    # No statement of this cycle with an OPEN/UNDER_REVIEW dispute.
    cycle_stmt_ids = {s["id"] for s in db.tenant_statements.values()
                      if s["billing_cycle_id"] == cycle_id}
    for disp in db.disputes.values():
        if disp["statement_id"] in cycle_stmt_ids and disp["status"] in ("OPEN", "UNDER_REVIEW"):
            raise ApiError("ERR_CYCLE_HAS_OPEN_DISPUTES", "Cycle has open disputes")

    cycle["status"] = "CLOSED"
    db.touch(cycle)

    # Recompute allocation invariant: sum of issued statements' utility charges
    # reconciles to the cycle's allocated total.
    stmt_sum = sum(s["utility_charge_cents"] for s in db.tenant_statements.values()
                   if s["billing_cycle_id"] == cycle_id)
    invariant_ok = (stmt_sum == cycle["allocated_total_cents"])

    prop = db.properties[cycle["property_id"]]
    if not invariant_ok:
        if prop["integrity_status"] != "NEEDS_REVIEW":
            prop["integrity_status"] = "NEEDS_REVIEW"
            db.touch(prop)
    # Leave OK as-is otherwise (a prior NEEDS_REVIEW stays until something clears it).

    return success(serialize(cycle), status=200)
