"""Funding batches and the recordkeeper exchange (PRD 3.6)."""

from flask import Blueprint, request

import db
from errors import fail
from middleware import auth, body, req_enum, req_str
from response import object_response, paginated
from services import calc, effects, lookup, serialize

bp = Blueprint("funding", __name__)

OUTCOMES = ("SETTLED", "REJECTED")


@bp.post("/funding-batches")
def create_funding_batch():
    auth("PayrollOperator")
    payload = body()
    plan_year_id = req_str(payload, "plan_year_id")
    payroll_period_id = req_str(payload, "payroll_period_id")
    plan_year = lookup.plan_year(plan_year_id)
    period = lookup.payroll_period(payroll_period_id)

    if effects.pending_batch_for(plan_year["id"], period["id"]) is not None:
        fail("ERR_DUPLICATE_PERIOD_RESOURCE",
             "a PENDING funding batch already exists for this period")

    row = {
        "plan_year_id": plan_year["id"],
        "payroll_period_id": period["id"],
        "status": "PENDING",
        "transmitted_at": None,
        "settled_at": None,
        "rejection_code": None,
        "retransmit_count": 0,
        "_frozen_offset": 0,
    }
    db.stamp_new(row)
    db.db.funding_batches[row["id"]] = row
    return object_response(serialize.funding_batch(row), 201)


@bp.get("/funding-batches")
def list_funding_batches():
    auth("PayrollOperator", "Recordkeeper", "BenefitsAdministrator",
         "ComplianceAuditor")
    rows = db.rows("funding_batches")
    for name in ("plan_year_id", "payroll_period_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    return paginated(rows, serialize.funding_batch)


@bp.get("/funding-batches/<funding_batch_id>")
def get_funding_batch(funding_batch_id):
    auth("PayrollOperator", "Recordkeeper", "BenefitsAdministrator",
         "ComplianceAuditor")
    return object_response(serialize.funding_batch(
        lookup.funding_batch(funding_batch_id)))


@bp.post("/funding-batches/<funding_batch_id>/transmit")
def transmit_batch(funding_batch_id):
    auth("PayrollOperator")
    body()
    batch = lookup.funding_batch(funding_batch_id)

    period = db.db.payroll_periods.get(batch["payroll_period_id"])
    if period is None or period["status"] != "CLOSED":
        fail("ERR_PERIOD_NOT_CLOSED",
             "the batch's payroll period is not CLOSED")

    if batch["status"] not in ("PENDING", "REJECTED"):
        fail("ERR_BATCH_STATE_INVALID",
             "a batch in %s may not be transmitted" % batch["status"])

    if calc.batch_allocation_count(batch) < 1:
        fail("ERR_BATCH_EMPTY", "the batch carries no live allocation")

    if batch["status"] == "REJECTED":
        # REJECTED -> PENDING -> TRANSMITTED inside one request.
        batch["status"] = "PENDING"
        batch["retransmit_count"] += 1
        batch["rejection_code"] = None

    calc.freeze_batch_offset(batch)
    batch["status"] = "TRANSMITTED"
    batch["transmitted_at"] = db.now_iso()
    db.touch(batch)
    return object_response(serialize.funding_batch(batch))


@bp.post("/funding-batches/<funding_batch_id>/settlement")
def settle_batch(funding_batch_id):
    auth("Recordkeeper")
    payload = body()
    outcome = req_enum(payload, "outcome", OUTCOMES)
    rejection_code = None
    if outcome == "REJECTED":
        rejection_code = req_str(payload, "rejection_code")

    batch = lookup.funding_batch(funding_batch_id)
    if batch["status"] != "TRANSMITTED":
        fail("ERR_BATCH_STATE_INVALID",
             "a batch in %s may not be settled" % batch["status"])

    if outcome == "SETTLED":
        batch["status"] = "SETTLED"
        batch["settled_at"] = db.now_iso()
        for alloc in calc.allocations_of_batch(batch["id"]):
            if alloc["funding_status"] == "SCHEDULED":
                alloc["funding_status"] = "FUNDED"
                db.touch(alloc)
        period = db.db.payroll_periods.get(batch["payroll_period_id"])
        if period is not None and period["status"] == "CLOSED":
            period["status"] = "FUNDED"
            db.touch(period)
    else:
        batch["status"] = "REJECTED"
        batch["rejection_code"] = rejection_code

    db.touch(batch)
    return object_response(serialize.funding_batch(batch))
