"""Payout batch and line endpoints (PRD §3.8): batches, lines, holds,
write-offs, and settlement."""

from flask import Blueprint, request

from db import store
from errors import (
    not_found, invalid_state, invalid_request, validation, ApiError,
    ERR_BATCH_NOT_SUBMITTABLE, ERR_BATCH_NOT_PENDING_APPROVAL,
    ERR_BATCH_NOT_APPROVED, ERR_BATCH_NOT_SETTLED, ERR_LINE_NOT_PENDING,
    ERR_LINE_NOT_HELD, ERR_LINE_NOT_WRITABLE_OFF, ERR_PAYOUT_PERIOD_OVERLAP,
    ERR_SEGREGATION_OF_DUTIES, ERR_INVALID_TIME_RANGE,
)
from middleware import (
    require_roles, ALL_ROLES, ROLE_EXCHANGE_ADMIN, ROLE_FINANCE_OFFICER,
)
from response import success_object, success_list, paginate
from util import get_body, req_date
from services.core import (
    base_record, touch, serialize_batch, serialize_line,
    line_composition, refresh_line, recompute_batch_aggregates,
    recompute_publisher_accruals, _sorted,
)

bp = Blueprint("payouts", __name__)


def _get_batch_or_404(batch_id):
    b = store.payout_batches.get(batch_id)
    if b is None:
        raise not_found("PayoutBatch not found")
    return b


def _get_line_or_404(batch, line_id):
    l = store.payout_lines.get(line_id)
    if l is None or l["batch_id"] != batch["id"]:
        raise not_found("PayoutLine not found")
    return l


@bp.route("/payout-batches", methods=["POST"])
def create_batch():
    role, user_id = require_roles([ROLE_FINANCE_OFFICER])
    body = get_body()
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    if not period_start < period_end:
        raise ApiError(ERR_INVALID_TIME_RANGE, 422,
                       "period_start must be strictly before period_end")
    batch = base_record()
    batch.update({
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "created_by_user_id": user_id,
        "line_count": 0,
        "total_gross_micros": 0,
        "total_payable_micros": 0,
    })
    store.payout_batches[batch["id"]] = batch
    return success_object(serialize_batch(batch), 201)


@bp.route("/payout-batches", methods=["GET"])
def list_batches():
    require_roles(ALL_ROLES)
    status = request.args.get("status")
    items = list(store.payout_batches.values())
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, limit, offset, total = paginate(_sorted(items), request.args)
    return success_list([serialize_batch(b) for b in page], limit, offset, total)


@bp.route("/payout-batches/<batchId>", methods=["GET"])
def get_batch(batchId):
    require_roles(ALL_ROLES)
    return success_object(serialize_batch(_get_batch_or_404(batchId)))


@bp.route("/payout-batches/<batchId>/submit", methods=["POST"])
def submit_batch(batchId):
    require_roles([ROLE_FINANCE_OFFICER])
    batch = _get_batch_or_404(batchId)
    if batch["status"] != "DRAFT":
        raise ApiError(ERR_BATCH_NOT_SUBMITTABLE, 409, "PayoutBatch is not in DRAFT")
    # period exclusivity (stage 11): a batch blocks overlapping submits only
    # while it is outside DRAFT; rejected batches return to DRAFT and never
    # block. Half-open overlap; sharing an exact boundary date is allowed.
    for other in store.payout_batches.values():
        if other["id"] == batch["id"] or other["status"] == "DRAFT":
            continue
        if batch["period_start"] < other["period_end"] and other["period_start"] < batch["period_end"]:
            raise ApiError(ERR_PAYOUT_PERIOD_OVERLAP, 409,
                           "Batch period overlaps another submitted batch")
    # line generation: one line per publisher with at least one non-voided
    # record created inside the window
    publisher_ids = sorted(
        {r["publisher_id"] for r in store.records.values()
         if not r["voided"]
         and batch["period_start"] <= r["_created_dt"].date() < batch["period_end"]},
        key=lambda pid: (store.publishers[pid]["created_at"], store.publishers[pid]["_seq"]))
    for pid in publisher_ids:
        gross, confirmed, unconfirmed, adjustment, payable = line_composition(batch, pid)
        line = base_record()
        line.update({
            "batch_id": batch["id"],
            "publisher_id": pid,
            "status": "PENDING",
            "gross_micros": gross,
            "confirmed_micros": confirmed,
            "unconfirmed_micros": unconfirmed,
            "adjustment_micros": adjustment,
            "payable_micros": payable,
            "paid_micros": None,
            "written_off_amount_micros": None,
            "write_off_reason": None,
        })
        # GUARANTEED publishers promote immediately PENDING -> ELIGIBLE
        if store.publishers[pid]["payment_terms"] == "GUARANTEED":
            line["status"] = "ELIGIBLE"
        store.payout_lines[line["id"]] = line
    batch["status"] = "PENDING_APPROVAL"
    recompute_batch_aggregates(batch)
    touch(batch)
    return success_object(serialize_batch(batch))


@bp.route("/payout-batches/<batchId>/approve", methods=["POST"])
def approve_batch(batchId):
    role, user_id = require_roles([ROLE_EXCHANGE_ADMIN])
    batch = _get_batch_or_404(batchId)
    if batch["status"] != "PENDING_APPROVAL":
        raise ApiError(ERR_BATCH_NOT_PENDING_APPROVAL, 409,
                       "PayoutBatch is not PENDING_APPROVAL")
    # segregation of duties (stage 15): creator may not approve
    if user_id == batch["created_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "Approver must differ from the batch creator")
    batch["status"] = "APPROVED"
    touch(batch)
    return success_object(serialize_batch(batch))


@bp.route("/payout-batches/<batchId>/reject", methods=["POST"])
def reject_batch(batchId):
    require_roles([ROLE_EXCHANGE_ADMIN])
    batch = _get_batch_or_404(batchId)
    if batch["status"] != "PENDING_APPROVAL":
        raise ApiError(ERR_BATCH_NOT_PENDING_APPROVAL, 409,
                       "PayoutBatch is not PENDING_APPROVAL")
    # revision loop: lines are deleted and aggregates reset (§3.8)
    for lid in [l["id"] for l in store.payout_lines.values() if l["batch_id"] == batch["id"]]:
        del store.payout_lines[lid]
    batch["status"] = "DRAFT"
    recompute_batch_aggregates(batch)
    touch(batch)
    return success_object(serialize_batch(batch))


@bp.route("/payout-batches/<batchId>/release", methods=["POST"])
def release_batch(batchId):
    require_roles([ROLE_FINANCE_OFFICER])
    batch = _get_batch_or_404(batchId)
    if batch["status"] != "APPROVED":
        raise ApiError(ERR_BATCH_NOT_APPROVED, 409, "PayoutBatch is not APPROVED")
    lines = _sorted([l for l in store.payout_lines.values() if l["batch_id"] == batch["id"]])
    # Step 1: PENDING lines have their payable basis re-evaluated now;
    # a line whose payable rises above zero promotes to ELIGIBLE, a line with
    # nothing payable stays PENDING into settlement.
    for line in lines:
        if line["status"] != "PENDING":
            continue
        changed = refresh_line(line)
        pub = store.publishers[line["publisher_id"]]
        promotable = (line["payable_micros"] > 0
                      or pub["payment_terms"] == "GUARANTEED")
        if promotable:
            line["status"] = "ELIGIBLE"
            touch(line)
        elif changed:
            touch(line)
    # Step 2: every ELIGIBLE line is paid.
    paid_publishers = set()
    for line in lines:
        if line["status"] != "ELIGIBLE":
            continue
        line["status"] = "PAID"
        line["paid_micros"] = line["payable_micros"]
        touch(line)
        paid_publishers.add(line["publisher_id"])
    for pid in paid_publishers:
        recompute_publisher_accruals(store.publishers[pid])
    # RELEASED -> SETTLED immediately; even a zero-line batch settles.
    batch["status"] = "SETTLED"
    recompute_batch_aggregates(batch)
    touch(batch)
    return success_object(serialize_batch(batch))


@bp.route("/payout-batches/<batchId>/lines", methods=["GET"])
def list_lines(batchId):
    require_roles(ALL_ROLES)
    batch = _get_batch_or_404(batchId)
    status = request.args.get("status")
    items = [l for l in store.payout_lines.values() if l["batch_id"] == batch["id"]]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, limit, offset, total = paginate(_sorted(items), request.args)
    return success_list([serialize_line(l) for l in page], limit, offset, total)


@bp.route("/payout-batches/<batchId>/lines/<lineId>/hold", methods=["POST"])
def hold_line(batchId, lineId):
    require_roles([ROLE_FINANCE_OFFICER])
    batch = _get_batch_or_404(batchId)
    line = _get_line_or_404(batch, lineId)
    if line["status"] != "PENDING":
        raise ApiError(ERR_LINE_NOT_PENDING, 409, "PayoutLine is not PENDING")
    if batch["status"] not in ("PENDING_APPROVAL", "APPROVED"):
        raise invalid_state("Parent batch is not PENDING_APPROVAL or APPROVED")
    line["status"] = "HELD"
    touch(line)
    recompute_batch_aggregates(batch)
    return success_object(serialize_line(line))


@bp.route("/payout-batches/<batchId>/lines/<lineId>/release-hold", methods=["POST"])
def release_hold_line(batchId, lineId):
    require_roles([ROLE_FINANCE_OFFICER])
    batch = _get_batch_or_404(batchId)
    line = _get_line_or_404(batch, lineId)
    if line["status"] != "HELD":
        raise ApiError(ERR_LINE_NOT_HELD, 409, "PayoutLine is not HELD")
    if batch["status"] not in ("PENDING_APPROVAL", "APPROVED"):
        raise invalid_state("Parent batch is not PENDING_APPROVAL or APPROVED")
    # branching transition: a guaranteed publisher's line, or any line with
    # payable above zero, returns to ELIGIBLE; a sequential-liability line
    # with nothing payable falls back to PENDING
    pub = store.publishers[line["publisher_id"]]
    if pub["payment_terms"] == "GUARANTEED" or line["payable_micros"] > 0:
        line["status"] = "ELIGIBLE"
    else:
        line["status"] = "PENDING"
    touch(line)
    recompute_batch_aggregates(batch)
    return success_object(serialize_line(line))


@bp.route("/payout-batches/<batchId>/lines/<lineId>/write-off", methods=["POST"])
def write_off_line(batchId, lineId):
    require_roles([ROLE_FINANCE_OFFICER])
    body = get_body()
    reason = body.get("write_off_reason")
    if reason is None:
        raise invalid_request("write_off_reason is required")
    if not isinstance(reason, str) or reason == "":
        raise validation("write_off_reason must be a non-empty string")
    batch = _get_batch_or_404(batchId)
    line = _get_line_or_404(batch, lineId)
    if batch["status"] != "SETTLED":
        raise ApiError(ERR_BATCH_NOT_SETTLED, 409, "Parent batch is not SETTLED")
    if line["status"] not in ("PENDING", "HELD"):
        raise ApiError(ERR_LINE_NOT_WRITABLE_OFF, 409,
                       "PayoutLine is not PENDING or HELD")
    line["written_off_amount_micros"] = line["payable_micros"]
    line["write_off_reason"] = reason
    line["status"] = "WRITTEN_OFF"
    touch(line)
    recompute_publisher_accruals(store.publishers[line["publisher_id"]])
    recompute_batch_aggregates(batch)
    return success_object(serialize_line(line))
