"""Settlement batch endpoints."""

from flask import Blueprint, g

from clock import CLOCK, parse_iso
from db import DB, LOCK, new_id
from errors import (
    cross_project,
    forbidden,
    invalid_state,
    not_found,
    pending_refunds_block,
    update_frequency_breach,
    validation_error,
)
from middleware import require_roles
from response import success_object
from services.audit import append_audit
from services.calculations import (
    MAX_SILENCE_DAYS,
    commission_for_order,
    channel_fee_for_order,
    tax_withholding,
)
from services.common import bump_version, get_json_body, stamp_create
from services.serializers import settlement_view


bp = Blueprint("settlement", __name__)


def _aggregate_batch_amounts(project, batch):
    """Compute gross_charged_cents, commission_cents, channel_fee_cents,
    refund_reversal_cents using per-order pinned values for the period."""
    period_start = batch["period_start"]
    period_end = batch["period_end"]
    gross = 0
    commission_total = 0
    channel_total = 0
    for o in DB.orders.values():
        if o["project_id"] != project["id"]:
            continue
        if o["payment_status"] not in ("CHARGED", "PARTIALLY_REFUNDED", "REFUNDED"):
            continue
        pin = DB.order_charge_pins.get(o["id"])
        if pin is None:
            continue
        ts = pin.get("charged_at")
        if ts is None:
            continue
        if not (period_start <= ts < period_end):
            continue
        gross += int(o.get("order_total_cents", 0))
        commission_total += int(pin.get("commission_cents", 0))
        channel_total += int(pin.get("channel_fee_cents", 0))

    # Refund reversals: aggregate magnitudes of COMMISSION_REVERSAL ledger entries within period
    refund_reversal = 0
    for entry in DB.escrow_ledger:
        if entry["project_id"] != project["id"]:
            continue
        if entry["entry_type"] != "COMMISSION_REVERSAL":
            continue
        if not (period_start <= entry["created_at"] < period_end):
            continue
        refund_reversal += abs(int(entry["amount_cents"]))
    return gross, commission_total, channel_total, refund_reversal


@bp.route("/projects/<project_id>/settlement-batches", methods=["POST"])
@require_roles("PlatformAdmin")
def create_batch(project_id):
    body = get_json_body()
    period_start_raw = body.get("period_start")
    period_end_raw = body.get("period_end")
    if not period_start_raw or not period_end_raw:
        raise validation_error("period_start and period_end required")
    try:
        period_start = parse_iso(period_start_raw)
        period_end = parse_iso(period_end_raw)
    except ValueError as e:
        raise validation_error(str(e))
    if period_end <= period_start:
        raise validation_error("period_end must be > period_start")

    with LOCK:
        project = DB.projects.get(project_id)
        if project is None:
            raise not_found()

        gross, commission_total, channel_total, refund_reversal = _aggregate_batch_amounts(
            project, {"period_start": period_start, "period_end": period_end}
        )
        # Tax withholding on the taxable base
        initiator = DB.initiators.get(project["initiator_id"])
        tax_id = initiator.get("tax_id") if initiator else None
        taxable_base = gross - commission_total - channel_total - refund_reversal
        tax_withheld = tax_withholding(taxable_base, tax_id)
        net_payout = taxable_base - tax_withheld

        rec = stamp_create({
            "id": new_id(),
            "project_id": project_id,
            "period_start": period_start,
            "period_end": period_end,
            "gross_charged_cents": gross,
            "commission_cents": commission_total,
            "channel_fee_cents": channel_total,
            "refund_reversal_cents": refund_reversal,
            "tax_withheld_cents": tax_withheld,
            "net_payout_cents": net_payout,
            "status": "DRAFT",
        })
        DB.settlement_batches[rec["id"]] = rec
        append_audit(
            subject_type="SETTLEMENT_BATCH",
            subject_id=rec["id"],
            event_type="STATUS_CHANGE",
            payload={"from": None, "to": "DRAFT", "project_id": project_id},
            actor_role=g.role,
            actor_id=g.user_id,
        )
    return success_object(settlement_view(rec), status=201)


@bp.route("/projects/<project_id>/settlement-batches/<batch_id>/finalize", methods=["POST"])
@require_roles("PlatformAdmin")
def finalize_batch(project_id, batch_id):
    with LOCK:
        project = DB.projects.get(project_id)
        if project is None:
            raise not_found()
        batch = DB.settlement_batches.get(batch_id)
        if batch is None:
            raise not_found()
        if batch["project_id"] != project_id:
            raise cross_project("Batch does not belong to project")
        if batch["status"] != "DRAFT":
            raise invalid_state("Batch not DRAFT")
        if project["status"] != "SUCCEEDED":
            raise invalid_state("Project must be SUCCEEDED to finalize")

        # Update-frequency compliance (priority 16)
        last_update = project.get("last_update_published_at")
        now = CLOCK.now()
        if last_update is not None:
            days_silent = (now - last_update).days
        else:
            # If no update has ever been published, treat as silent since project creation
            days_silent = (now - project["created_at"]).days
        if days_silent > MAX_SILENCE_DAYS:
            raise update_frequency_breach()

        # Pending refund block (priority 17)
        period_start = batch["period_start"]
        period_end = batch["period_end"]
        for r in DB.refund_requests.values():
            order = DB.orders.get(r["order_id"])
            if order is None or order["project_id"] != project_id:
                continue
            pin = DB.order_charge_pins.get(order["id"])
            ts = pin.get("charged_at") if pin else None
            if ts is None:
                continue
            if not (period_start <= ts < period_end):
                continue
            if r["status"] in ("PENDING_REVIEW", "APPROVED"):
                raise pending_refunds_block()

        # Recompute amounts in pinned evaluation order
        gross, commission_total, channel_total, refund_reversal = _aggregate_batch_amounts(project, batch)
        initiator = DB.initiators.get(project["initiator_id"])
        tax_id = initiator.get("tax_id") if initiator else None
        taxable_base = gross - commission_total - channel_total - refund_reversal
        tax_withheld = tax_withholding(taxable_base, tax_id)
        net_payout = taxable_base - tax_withheld

        batch["gross_charged_cents"] = gross
        batch["commission_cents"] = commission_total
        batch["channel_fee_cents"] = channel_total
        batch["refund_reversal_cents"] = refund_reversal
        batch["tax_withheld_cents"] = tax_withheld
        batch["net_payout_cents"] = net_payout
        batch["status"] = "FINALIZED"
        bump_version(batch)
        append_audit(
            subject_type="SETTLEMENT_BATCH",
            subject_id=batch["id"],
            event_type="STATUS_CHANGE",
            payload={"from": "DRAFT", "to": "FINALIZED", "net_payout_cents": net_payout},
            actor_role=g.role,
            actor_id=g.user_id,
        )
    return success_object(settlement_view(batch))


@bp.route("/projects/<project_id>/settlement-batches/<batch_id>", methods=["GET"])
@require_roles("Initiator", "PlatformAdmin")
def get_batch(project_id, batch_id):
    with LOCK:
        project = DB.projects.get(project_id)
        if project is None:
            raise not_found()
        batch = DB.settlement_batches.get(batch_id)
        if batch is None:
            raise not_found()
        if batch["project_id"] != project_id:
            raise cross_project("Batch does not belong to project")
        if g.role == "Initiator" and project["initiator_id"] != g.user_id:
            raise forbidden()
        return success_object(settlement_view(batch))
