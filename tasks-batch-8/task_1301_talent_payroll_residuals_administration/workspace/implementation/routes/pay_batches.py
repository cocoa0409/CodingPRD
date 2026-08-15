"""PayBatch and PayLine endpoints: open, close (sweep), approve, recall, disburse."""

from decimal import Decimal
from flask import Blueprint, request

import db
from calculations import (
    jurisdiction_tax_cents, phw_contribution_cents,
    recompute_engagement_ytd_paid, recompute_performer_ytd,
)
from errors import (
    ApiError, ERR_BATCH_INVALID_STATE, ERR_OPEN_BATCH_EXISTS,
    ERR_SEGREGATION_OF_DUTIES, ERR_BATCH_EMPTY,
)
from helpers import new_id, now_timestamp, parse_date, require_string, err_validation, round_half_up
from middleware import require_roles, ALL_ROLES
from response import success_object, list_response
from serializers import serialize, get_or_404, bump_version

bp = Blueprint("pay_batches", __name__)

MAX_GARNISH_PCT = Decimal("0.25")


def _open_batch_exists():
    return any(b["status"] == "OPEN" for b in db.pay_batches.values())


@bp.post("/payroll/pay-batches")
def create_pay_batch():
    user_id, _role = require_roles({"PayrollClerk"})
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object")

    period_label = require_string(body, "period_label")
    cutoff_date = require_string(body, "cutoff_date")
    parse_date(cutoff_date, "cutoff_date")

    # At most one OPEN batch at a time
    if _open_batch_exists():
        raise ApiError(
            ERR_OPEN_BATCH_EXISTS,
            "Another pay batch is currently OPEN",
            409,
        )

    now = now_timestamp()
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "period_label": period_label,
        "cutoff_date": cutoff_date,
        "created_by_user_id": user_id,
        "total_gross_cents": 0,
        "total_tax_cents": 0,
        "total_garnished_cents": 0,
        "total_phw_cents": 0,
        "total_net_cents": 0,
        "status": "OPEN",
    }
    db.pay_batches[record["id"]] = record
    return success_object(serialize(record), 201)


@bp.get("/payroll/pay-batches/<batch_id>")
def get_pay_batch(batch_id):
    require_roles(ALL_ROLES)
    batch = get_or_404(db.pay_batches, batch_id, "PayBatch")
    return success_object(serialize(batch), 200)


def _sweep_set(batch):
    """Eligible timecards and residuals for the batch close sweep."""
    cutoff = parse_date(batch["cutoff_date"], "cutoff_date")
    timecards = []
    for tc in db.timecards.values():
        if tc["review_status"] != "APPROVED":
            continue
        if tc["payment_status"] != "UNBATCHED":
            continue
        if parse_date(tc["work_date"], "work_date") > cutoff:
            continue
        timecards.append(tc)
    residuals = []
    for r in db.residual_obligations.values():
        if r["status"] != "APPROVED":
            continue
        if parse_date(r["window_end"], "window_end") > cutoff:
            continue
        residuals.append(r)
    return timecards, residuals


def _source_sort_key(line_info):
    """Order performer's lines by source work_date/window_start ASC, then created_at ASC."""
    return (line_info["sort_date"], line_info["created_at"])


def _create_pay_line(batch, source_type, source, engagement, agreement,
                     production, performer, sort_date):
    """Create a PayLine with gross/tax/phw; garnishment allocated later per performer.

    Returns the created line record.
    """
    if source_type == "TIMECARD":
        confirmed_penalties = sum(
            pa["amount_cents"]
            for pa in db.penalty_assessments.values()
            if pa["timecard_id"] == source["id"] and pa["status"] == "CONFIRMED"
        )
        gross = source["day_gross_cents"] + confirmed_penalties
        line_jurisdiction = source["jurisdiction_code"]
    elif source_type == "RESIDUAL":
        gross = source["final_amount_cents"]
        line_jurisdiction = performer["tax_residency_state"]
    else:  # GRIEVANCE_ADJUSTMENT
        gross = source["awarded_amount_cents"]
        line_jurisdiction = performer["tax_residency_state"]

    tax = jurisdiction_tax_cents(
        gross, engagement, production, performer, source_type,
        timecard_jurisdiction_code=source.get("jurisdiction_code") if source_type == "TIMECARD" else None,
    )
    phw = phw_contribution_cents(gross, agreement)

    now = now_timestamp()
    line = {
        "id": new_id(),
        "created_at": now,
        "pay_batch_id": batch["id"],
        "engagement_id": engagement["id"],
        "source_type": source_type,
        "source_id": source["id"],
        "gross_cents": gross,
        "jurisdiction_code": line_jurisdiction,
        "tax_cents": tax,
        "garnished_cents": 0,  # set by the waterfall below
        "phw_cents": phw,
        "net_cents": 0,        # set after garnishment
        "status": "UNPAID",
        # Internal fields for waterfall processing (never serialized)
        "_sort_date": sort_date,
        "_performer_id": performer["id"],
        "_exempt": engagement["payee_type"] == "LOAN_OUT" or source_type == "GRIEVANCE_ADJUSTMENT",
    }
    db.pay_lines[line["id"]] = line
    return line


def _run_garnishment_waterfall(batch):
    """Allocate garnishment per performer across that performer's non-exempt lines."""
    # Group this batch's lines by performer
    by_performer = {}
    for line in db.pay_lines.values():
        if line["pay_batch_id"] != batch["id"]:
            continue
        by_performer.setdefault(line["_performer_id"], []).append(line)

    for performer_id, lines in by_performer.items():
        # Process each performer's lines in pinned order
        lines.sort(key=lambda l: (l["_sort_date"], l["created_at"]))
        active_orders = [
            o for o in db.garnishment_orders.values()
            if o["performer_id"] == performer_id and o["status"] == "ACTIVE"
        ]
        active_orders.sort(key=lambda o: (o["priority_rank"], o["created_at"]))

        for line in lines:
            if line["_exempt"]:
                line["garnished_cents"] = 0
                continue
            disposable = line["gross_cents"] - line["tax_cents"]
            line_cap = round_half_up(Decimal(disposable) * MAX_GARNISH_PCT)
            remaining = line_cap
            for order in active_orders:
                if order.get("fixed_amount_cents") is not None:
                    requested = order["fixed_amount_cents"]
                else:
                    requested = round_half_up(
                        Decimal(disposable) * Decimal(str(order["pct_of_disposable"]))
                    )
                allocated = min(requested, remaining)
                if allocated > 0:
                    db.pending_garnishment_allocations[order["id"]] = (
                        db.pending_garnishment_allocations.get(order["id"], 0) + allocated
                    )
                    remaining -= allocated
            line["garnished_cents"] = line_cap - remaining

    # Net after garnishment is known
    for line in db.pay_lines.values():
        if line["pay_batch_id"] != batch["id"]:
            continue
        line["net_cents"] = (
            line["gross_cents"] - line["tax_cents"] - line["garnished_cents"]
        )


def _recompute_batch_totals(batch):
    lines = [l for l in db.pay_lines.values() if l["pay_batch_id"] == batch["id"]]
    batch["total_gross_cents"] = sum(l["gross_cents"] for l in lines)
    batch["total_tax_cents"] = sum(l["tax_cents"] for l in lines)
    batch["total_garnished_cents"] = sum(l["garnished_cents"] for l in lines)
    batch["total_phw_cents"] = sum(l["phw_cents"] for l in lines)
    batch["total_net_cents"] = sum(l["net_cents"] for l in lines)


@bp.post("/payroll/pay-batches/<batch_id>/close")
def close_pay_batch(batch_id):
    require_roles({"PayrollClerk"})
    batch = get_or_404(db.pay_batches, batch_id, "PayBatch")

    if batch["status"] != "OPEN":
        raise ApiError(
            ERR_BATCH_INVALID_STATE,
            "Close requires status OPEN",
            409,
        )

    timecards, residuals = _sweep_set(batch)
    if not timecards and not residuals:
        raise ApiError(
            ERR_BATCH_EMPTY,
            "Batch close sweep set is empty",
            422,
        )

    # Create one PayLine per swept source. Remember swept sources for cascades.
    swept_timecards = []
    swept_residuals = []

    for tc in timecards:
        engagement = get_or_404(db.engagements, tc["engagement_id"], "Engagement")
        agreement = get_or_404(db.union_agreements, engagement["union_agreement_id"], "UnionAgreement")
        production = get_or_404(db.productions, engagement["production_id"], "Production")
        performer = get_or_404(db.performers, engagement["performer_id"], "Performer")
        _create_pay_line(
            batch, "TIMECARD", tc, engagement, agreement, production, performer,
            sort_date=tc["work_date"],
        )
        swept_timecards.append(tc)

    for r in residuals:
        engagement = get_or_404(db.engagements, r["engagement_id"], "Engagement")
        agreement = get_or_404(db.union_agreements, engagement["union_agreement_id"], "UnionAgreement")
        production = get_or_404(db.productions, engagement["production_id"], "Production")
        performer = get_or_404(db.performers, engagement["performer_id"], "Performer")
        _create_pay_line(
            batch, "RESIDUAL", r, engagement, agreement, production, performer,
            sort_date=r["window_start"],
        )
        swept_residuals.append(r)

    # Garnishment waterfall and net per line, then batch totals.
    _run_garnishment_waterfall(batch)

    # Cascade sources' payment dimension.
    for tc in swept_timecards:
        tc["payment_status"] = "BATCHED"
        bump_version(tc)
    for r in swept_residuals:
        r["status"] = "BATCHED"
        bump_version(r)

    _recompute_batch_totals(batch)
    batch["status"] = "CLOSED"
    bump_version(batch)
    return success_object(serialize(batch), 200)


@bp.post("/payroll/pay-batches/<batch_id>/approve")
def approve_pay_batch(batch_id):
    user_id, _role = require_roles({"PayrollSupervisor"})
    batch = get_or_404(db.pay_batches, batch_id, "PayBatch")

    if batch["status"] != "CLOSED":
        raise ApiError(
            ERR_BATCH_INVALID_STATE,
            "Approve requires status CLOSED",
            409,
        )

    # Segregation of duties: approver must differ from creator.
    if user_id == batch["created_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "Batch approver must differ from the batch creator",
            403,
        )

    batch["status"] = "APPROVED"
    bump_version(batch)
    return success_object(serialize(batch), 200)


@bp.post("/payroll/pay-batches/<batch_id>/recall")
def recall_pay_batch(batch_id):
    require_roles({"PayrollSupervisor"})
    batch = get_or_404(db.pay_batches, batch_id, "PayBatch")

    if batch["status"] != "APPROVED":
        raise ApiError(
            ERR_BATCH_INVALID_STATE,
            "Recall requires status APPROVED",
            409,
        )

    # Revert swept sources and delete pay lines.
    lines = [l for l in db.pay_lines.values() if l["pay_batch_id"] == batch_id]
    for line in lines:
        if line["source_type"] == "TIMECARD":
            tc = db.timecards.get(line["source_id"])
            if tc is not None and tc["payment_status"] == "BATCHED":
                tc["payment_status"] = "UNBATCHED"
                bump_version(tc)
        elif line["source_type"] == "RESIDUAL":
            r = db.residual_obligations.get(line["source_id"])
            if r is not None and r["status"] == "BATCHED":
                r["status"] = "APPROVED"
                bump_version(r)
        # GRIEVANCE_ADJUSTMENT lines have no source status to revert.
        del db.pay_lines[line["id"]]

    # Clear pending garnishment allocations recorded at this batch's close.
    # Allocations are only applied at disburse; recall discards them. At most
    # one batch carries pending allocations at a time (close -> approve ->
    # recall/disburse is strictly sequential per batch, and a batch cannot
    # close while another is mid-flight because close requires OPEN status).
    db.pending_garnishment_allocations.clear()

    batch["total_gross_cents"] = 0
    batch["total_tax_cents"] = 0
    batch["total_garnished_cents"] = 0
    batch["total_phw_cents"] = 0
    batch["total_net_cents"] = 0
    batch["status"] = "OPEN"
    bump_version(batch)
    return success_object(serialize(batch), 200)


@bp.post("/payroll/pay-batches/<batch_id>/disburse")
def disburse_pay_batch(batch_id):
    require_roles({"PayrollSupervisor"})
    batch = get_or_404(db.pay_batches, batch_id, "PayBatch")

    if batch["status"] != "APPROVED":
        raise ApiError(
            ERR_BATCH_INVALID_STATE,
            "Disburse requires status APPROVED",
            409,
        )

    lines = [l for l in db.pay_lines.values() if l["pay_batch_id"] == batch_id]
    touched_engagements = set()
    touched_performers = set()

    for line in lines:
        line["status"] = "PAID"
        # Cascade to source
        if line["source_type"] == "TIMECARD":
            tc = db.timecards.get(line["source_id"])
            if tc is not None and tc["payment_status"] == "BATCHED":
                tc["payment_status"] = "PAID"
                bump_version(tc)
        elif line["source_type"] == "RESIDUAL":
            r = db.residual_obligations.get(line["source_id"])
            if r is not None and r["status"] == "BATCHED":
                r["status"] = "PAID"
                bump_version(r)
        touched_engagements.add(line["engagement_id"])

    # Recompute engagement YTD paid, then performer YTD aggregates.
    for engagement_id in touched_engagements:
        engagement = db.engagements.get(engagement_id)
        if engagement is None:
            continue
        recompute_engagement_ytd_paid(engagement)
        touched_performers.add(engagement["performer_id"])
    for performer_id in touched_performers:
        performer = db.performers.get(performer_id)
        if performer is not None:
            recompute_performer_ytd(performer)

    # Apply pending garnishment allocations to orders' total_withheld_cents.
    for order_id, amount in db.pending_garnishment_allocations.items():
        order = db.garnishment_orders.get(order_id)
        if order is not None:
            order["total_withheld_cents"] = order.get("total_withheld_cents", 0) + amount
    db.pending_garnishment_allocations.clear()

    batch["status"] = "DISBURSED"
    bump_version(batch)
    return success_object(serialize(batch), 200)


# ---- PayLine read endpoints ----

@bp.get("/payroll/pay-lines")
def list_pay_lines():
    require_roles(ALL_ROLES)
    items = list(db.pay_lines.values())
    pay_batch_id = request.args.get("pay_batch_id")
    if pay_batch_id is not None:
        items = [l for l in items if l["pay_batch_id"] == pay_batch_id]
    engagement_id = request.args.get("engagement_id")
    if engagement_id is not None:
        items = [l for l in items if l["engagement_id"] == engagement_id]
    source_type = request.args.get("source_type")
    if source_type is not None:
        items = [l for l in items if l["source_type"] == source_type]
    return list_response([serialize(l) for l in items], request.args)


@bp.get("/payroll/pay-lines/<line_id>")
def get_pay_line(line_id):
    require_roles(ALL_ROLES)
    line = get_or_404(db.pay_lines, line_id, "PayLine")
    return success_object(serialize(line), 200)
