"""WaterBill routes."""

from flask import Blueprint, g, request

from clock import CLOCK, parse_iso
from db import DB, LOCK, new_id
from errors import (
    bill_period_invalid,
    bill_state_conflict,
    forbidden,
    invalid_state,
    not_found,
    validation_error,
)
from middleware import require_roles
from response import success_array, success_object
from services.calculations import (
    compute_bill_total,
    compute_peak_offpeak_split,
    compute_tiered_fee,
)
from services.common import (
    bump_version,
    check_occ,
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_str,
    stamp_create,
    to_aware_utc,
)
from services.serializers import water_bill_view


bp = Blueprint("water_bills", __name__)


def _quota_period_aligned(plot_id, period_start):
    """period_start must align to a period_start of a WaterQuota for the same plot."""
    period_start = to_aware_utc(period_start)
    for q in DB.water_quotas.values():
        if q.get("plot_id") != plot_id:
            continue
        if to_aware_utc(q["period_start"]) == period_start:
            return q
    return None


def _draft_or_recompute(rec):
    """Compute peak/offpeak liters, line items, and total for a DRAFT bill."""
    plot_id = rec["plot_id"]
    period_start = rec["period_start"]
    period_end = rec["period_end"]
    peak_l, offpeak_l = compute_peak_offpeak_split(plot_id, period_start, period_end)
    tenant = DB.tenants.get(rec["tenant_id"])
    tenant_status = tenant.get("status") if tenant else "ACTIVE"
    line_items = compute_tiered_fee(peak_l, offpeak_l, tenant_status)

    # Look up matching WaterQuota for carry-forward credit.
    q = _quota_period_aligned(plot_id, period_start)
    carry = float(q.get("carry_forward_liters", 0)) if q else 0.0
    total = compute_bill_total(line_items, carry)

    rec["peak_liters"] = peak_l
    rec["offpeak_liters"] = offpeak_l
    rec["line_items"] = line_items
    rec["total_amount_cents"] = int(total)


@bp.route("/water-bills", methods=["POST"])
@require_roles("WaterAdmin")
def create_bill():
    body = get_json_body()
    tenant_id = require_str(body, "tenant_id")
    plot_id = require_str(body, "plot_id")
    if "period_start" not in body or "period_end" not in body:
        raise validation_error("period_start and period_end are required")
    try:
        period_start = parse_iso(body["period_start"])
        period_end = parse_iso(body["period_end"])
    except Exception:
        raise validation_error("period bounds must be ISO 8601")
    if period_end <= period_start:
        raise bill_period_invalid("period_end must be > period_start")

    with LOCK:
        if tenant_id not in DB.tenants:
            raise validation_error("tenant_id does not exist")
        if plot_id not in DB.plots:
            raise validation_error("plot_id does not exist")
        if _quota_period_aligned(plot_id, period_start) is None:
            raise bill_period_invalid("period_start must align to a quota period for the plot")

        rec = stamp_create({
            "id": new_id(),
            "tenant_id": tenant_id,
            "plot_id": plot_id,
            "period_start": period_start,
            "period_end": period_end,
            "peak_liters": 0,
            "offpeak_liters": 0,
            "line_items": [],
            "total_amount_cents": 0,
            "amount_paid_cents": 0,
            "status": "DRAFT",
            "dispute_reason": None,
        })
        _draft_or_recompute(rec)
        DB.water_bills[rec["id"]] = rec
    return success_object(water_bill_view(rec), status=201)


@bp.route("/water-bills/<bill_id>", methods=["GET"])
def read_bill(bill_id):
    if g.role not in {"PlatformAdmin", "WaterAdmin", "Tenant"}:
        raise forbidden()
    with LOCK:
        rec = fetch_or_404(DB.water_bills, bill_id)
        if g.role == "Tenant" and rec.get("tenant_id") != g.user_id:
            raise forbidden()
        if rec.get("status") == "DRAFT":
            _draft_or_recompute(rec)
    return success_object(water_bill_view(rec))


@bp.route("/water-bills", methods=["GET"])
def list_bills():
    if g.role not in {"PlatformAdmin", "WaterAdmin", "Tenant"}:
        raise forbidden()
    limit, offset = parse_pagination()
    tenant_filter = request.args.get("tenant_id")
    plot_filter = request.args.get("plot_id")
    status_filter = request.args.get("status")
    with LOCK:
        items = list(DB.water_bills.values())
        if tenant_filter:
            items = [b for b in items if b.get("tenant_id") == tenant_filter]
        if plot_filter:
            items = [b for b in items if b.get("plot_id") == plot_filter]
        if status_filter:
            items = [b for b in items if b.get("status") == status_filter]
        if g.role == "Tenant":
            items = [b for b in items if b.get("tenant_id") == g.user_id]
        items.sort(key=lambda r: r.get("created_at"))
        for b in items:
            if b.get("status") == "DRAFT":
                _draft_or_recompute(b)
        page, total, has_more = paginate(items, limit, offset)
        data = [water_bill_view(b) for b in page]
    return success_array(data, limit, offset, total, has_more)


@bp.route("/water-bills/<bill_id>/issue", methods=["POST"])
@require_roles("WaterAdmin")
def issue_bill(bill_id):
    with LOCK:
        rec = fetch_or_404(DB.water_bills, bill_id)
        if rec.get("status") != "DRAFT":
            raise invalid_state("Bill must be DRAFT to issue")
        _draft_or_recompute(rec)
        if not rec.get("line_items"):
            raise invalid_state("Bill has no line items to issue")
        rec["status"] = "ISSUED"
        bump_version(rec)
    return success_object(water_bill_view(rec))


@bp.route("/water-bills/<bill_id>/payments", methods=["POST"])
@require_roles("WaterAdmin", "Tenant")
def record_payment(bill_id):
    body = get_json_body()
    if "amount_cents" not in body or body["amount_cents"] is None:
        raise validation_error("amount_cents is required")
    amt = body["amount_cents"]
    if isinstance(amt, bool) or not isinstance(amt, int):
        raise validation_error("amount_cents must be an integer")
    if amt <= 0:
        raise validation_error("amount_cents must be > 0")

    with LOCK:
        rec = fetch_or_404(DB.water_bills, bill_id)
        if g.role == "Tenant" and rec.get("tenant_id") != g.user_id:
            raise forbidden()
        if rec.get("status") not in ("ISSUED", "DISPUTED"):
            raise invalid_state("Bill must be ISSUED or DISPUTED for payment")
        # OCC race: optimistic concurrency on WaterBill.version
        if "version" in body and body["version"] is not None:
            try:
                supplied = int(body["version"])
            except (TypeError, ValueError):
                raise bill_state_conflict("version must be integer")
            if supplied != int(rec.get("version", 0)):
                raise bill_state_conflict()
        rec["amount_paid_cents"] = int(rec.get("amount_paid_cents", 0)) + int(amt)
        if rec["amount_paid_cents"] >= int(rec.get("total_amount_cents", 0)):
            rec["status"] = "PAID"
        bump_version(rec)
    return success_object(water_bill_view(rec))


@bp.route("/water-bills/<bill_id>/dispute", methods=["POST"])
@require_roles("Tenant")
def dispute_bill(bill_id):
    body = get_json_body()
    reason = require_str(body, "dispute_reason")
    with LOCK:
        rec = fetch_or_404(DB.water_bills, bill_id)
        if rec.get("tenant_id") != g.user_id:
            raise forbidden()
        if rec.get("status") != "ISSUED":
            raise invalid_state("Bill must be ISSUED to dispute")
        if "version" in body and body["version"] is not None:
            try:
                supplied = int(body["version"])
            except (TypeError, ValueError):
                raise bill_state_conflict("version must be integer")
            if supplied != int(rec.get("version", 0)):
                raise bill_state_conflict()
        rec["status"] = "DISPUTED"
        rec["dispute_reason"] = reason
        bump_version(rec)
    return success_object(water_bill_view(rec))


@bp.route("/water-bills/<bill_id>/dispute-resolve", methods=["POST"])
@require_roles("WaterAdmin")
def resolve_dispute(bill_id):
    body = get_json_body()
    outcome = body.get("outcome")
    if outcome not in ("REJECT", "ACCEPT"):
        raise validation_error("outcome must be REJECT or ACCEPT")
    with LOCK:
        rec = fetch_or_404(DB.water_bills, bill_id)
        if rec.get("status") != "DISPUTED":
            raise invalid_state("Bill must be DISPUTED to resolve")
        if outcome == "REJECT":
            rec["status"] = "ISSUED"
        else:
            rec["status"] = "CANCELLED"
            rec["total_amount_cents"] = 0
        bump_version(rec)
    return success_object(water_bill_view(rec))
