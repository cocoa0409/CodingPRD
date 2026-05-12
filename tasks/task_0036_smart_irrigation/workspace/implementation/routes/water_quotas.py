"""WaterQuota routes."""

from flask import Blueprint, g, request

from clock import parse_iso
from db import DB, LOCK, new_id
from errors import (
    forbidden,
    invalid_state,
    not_found,
    override_already_decided,
    override_amount_invalid,
    validation_error,
)
from middleware import require_roles
from response import success_array, success_object
from services.audit import append_audit
from services.calculations import effective_allocation
from services.common import (
    bump_version,
    check_occ,
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_str,
    round_half_up_2,
    stamp_create,
    to_aware_utc,
)
from services.quota import (
    on_quota_state_change,
    recompute_quota_aggregates,
)
from services.serializers import water_quota_view


bp = Blueprint("water_quotas", __name__)


def _compute_carry_forward(plot_id, period_start):
    """Find the immediately prior period for the same plot.

    Carry forward = min(prior.unused_liters, prior.allocated_liters * 0.20).
    unused_liters = max(0, prior.allocated_liters + prior.carry_forward_liters
                          + prior.approval_extra_liters - prior.final_used_liters)
    """
    period_start = to_aware_utc(period_start)
    prior = None
    for q in DB.water_quotas.values():
        if q.get("plot_id") != plot_id:
            continue
        pe = to_aware_utc(q["period_end"])
        if pe == period_start:
            prior = q
            break
    if prior is None:
        return 0.0

    # Recompute prior to ensure aggregates are fresh
    recompute_quota_aggregates(prior)
    eff = effective_allocation(prior)
    used = float(prior.get("final_used_liters", 0))
    unused = max(0.0, eff - used)
    cap = float(prior.get("allocated_liters", 0)) * 0.20
    return round_half_up_2(min(unused, cap))


@bp.route("/water-quotas", methods=["POST"])
@require_roles("WaterAdmin")
def create_quota():
    body = get_json_body()
    plot_id = require_str(body, "plot_id")
    if "period_start" not in body or body["period_start"] is None:
        raise validation_error("period_start is required")
    if "period_end" not in body or body["period_end"] is None:
        raise validation_error("period_end is required")
    if "allocated_liters" not in body or body["allocated_liters"] is None:
        raise validation_error("allocated_liters is required")
    alloc = body["allocated_liters"]
    if isinstance(alloc, bool) or not isinstance(alloc, (int, float)):
        raise validation_error("allocated_liters must be a number")
    if alloc < 0:
        raise validation_error("allocated_liters must be >= 0")
    try:
        period_start = parse_iso(body["period_start"])
        period_end = parse_iso(body["period_end"])
    except Exception:
        raise validation_error("period bounds must be ISO 8601")
    if period_end <= period_start:
        raise validation_error("period_end must be > period_start")

    threshold = body.get("warning_threshold_pct", 80)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise validation_error("warning_threshold_pct must be a number")
    if threshold < 1 or threshold > 100:
        raise validation_error("warning_threshold_pct must be in [1, 100]")

    with LOCK:
        if plot_id not in DB.plots:
            raise validation_error("plot_id does not exist")
        carry = _compute_carry_forward(plot_id, period_start)
        rec = stamp_create({
            "id": new_id(),
            "plot_id": plot_id,
            "period_start": period_start,
            "period_end": period_end,
            "allocated_liters": round_half_up_2(alloc),
            "carry_forward_liters": carry,
            "provisional_used_liters": 0,
            "final_used_liters": 0,
            "warning_threshold_pct": float(threshold),
            "usage_state": "UNDER",
            "approval_state": "NOT_REQUIRED",
            "approval_extra_liters": 0,
        })
        DB.water_quotas[rec["id"]] = rec
        recompute_quota_aggregates(rec)
        append_audit(
            action_type="QUOTA_ALLOCATED",
            subject_type="WATER_QUOTA",
            subject_id=rec["id"],
            payload={"allocated_liters": rec["allocated_liters"], "carry_forward_liters": carry},
        )
    return success_object(water_quota_view(rec), status=201)


@bp.route("/water-quotas/<quota_id>", methods=["GET"])
def read_quota(quota_id):
    if g.role not in {"PlatformAdmin", "WaterAdmin", "Operator", "Tenant"}:
        raise forbidden()
    with LOCK:
        rec = fetch_or_404(DB.water_quotas, quota_id)
        if g.role == "Tenant":
            plot = DB.plots.get(rec["plot_id"])
            if plot is None or plot.get("tenant_id") != g.user_id:
                raise forbidden()
        recompute_quota_aggregates(rec)
    return success_object(water_quota_view(rec))


@bp.route("/water-quotas/<quota_id>", methods=["PATCH"])
@require_roles("WaterAdmin")
def update_quota(quota_id):
    body = get_json_body()
    with LOCK:
        rec = fetch_or_404(DB.water_quotas, quota_id)
        check_occ(rec, body)
        if "allocated_liters" in body and body["allocated_liters"] is not None:
            v = body["allocated_liters"]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise validation_error("allocated_liters must be a number")
            if v < 0:
                raise validation_error("allocated_liters must be >= 0")
            rec["allocated_liters"] = round_half_up_2(v)
        if "warning_threshold_pct" in body and body["warning_threshold_pct"] is not None:
            v = body["warning_threshold_pct"]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise validation_error("warning_threshold_pct must be a number")
            if v < 1 or v > 100:
                raise validation_error("warning_threshold_pct must be in [1, 100]")
            rec["warning_threshold_pct"] = float(v)

        prev_usage = rec.get("usage_state", "UNDER")
        bump_version(rec)
        recompute_quota_aggregates(rec)
        # Reallocation may move WARNING -> UNDER (no alerting on this drop).
        # No new side effects required.
    return success_object(water_quota_view(rec))


@bp.route("/water-quotas", methods=["GET"])
def list_quotas():
    if g.role not in {"PlatformAdmin", "WaterAdmin", "Operator", "Tenant"}:
        raise forbidden()
    limit, offset = parse_pagination()
    plot_filter = request.args.get("plot_id")
    with LOCK:
        items = list(DB.water_quotas.values())
        if plot_filter:
            items = [q for q in items if q.get("plot_id") == plot_filter]
        if g.role == "Tenant":
            tenant_id = g.user_id
            items = [
                q for q in items
                if (DB.plots.get(q.get("plot_id")) or {}).get("tenant_id") == tenant_id
            ]
        items.sort(key=lambda r: r.get("created_at"))
        for q in items:
            recompute_quota_aggregates(q)
        page, total, has_more = paginate(items, limit, offset)
        data = [water_quota_view(q) for q in page]
    return success_array(data, limit, offset, total, has_more)


@bp.route("/water-quotas/<quota_id>/request-override", methods=["POST"])
@require_roles("Operator")
def request_override(quota_id):
    body = get_json_body()
    reason = require_str(body, "reason", allow_empty=True)
    with LOCK:
        rec = fetch_or_404(DB.water_quotas, quota_id)
        recompute_quota_aggregates(rec)
        if rec.get("approval_state") != "NOT_REQUIRED":
            raise invalid_state("Override already requested or decided")
        if rec.get("usage_state") != "OVER":
            raise invalid_state("Override may only be requested when usage_state == OVER")
        rec["approval_state"] = "PENDING_APPROVAL"
        bump_version(rec)
    return success_object(water_quota_view(rec))


@bp.route("/water-quotas/<quota_id>/approve-override", methods=["POST"])
@require_roles("WaterAdmin")
def approve_override(quota_id):
    body = get_json_body()
    if "extra_liters" not in body or body["extra_liters"] is None:
        raise validation_error("extra_liters is required")
    extra = body["extra_liters"]
    if isinstance(extra, bool) or not isinstance(extra, (int, float)):
        raise validation_error("extra_liters must be a number")
    with LOCK:
        rec = fetch_or_404(DB.water_quotas, quota_id)
        if rec.get("approval_state") in ("APPROVED", "REJECTED"):
            raise override_already_decided()
        if rec.get("approval_state") != "PENDING_APPROVAL":
            raise invalid_state("Override is not PENDING_APPROVAL")
        max_extra = float(rec.get("allocated_liters", 0)) * 0.5
        if extra <= 0 or extra > max_extra:
            raise override_amount_invalid()

        rec["approval_extra_liters"] = round_half_up_2(extra)
        rec["approval_state"] = "APPROVED"
        prev_usage = rec.get("usage_state", "UNDER")
        bump_version(rec)
        recompute_quota_aggregates(rec)
        append_audit(
            action_type="QUOTA_OVERRIDE_APPROVED",
            subject_type="WATER_QUOTA",
            subject_id=rec["id"],
            payload={"extra_liters": rec["approval_extra_liters"]},
        )
    return success_object(water_quota_view(rec))


@bp.route("/water-quotas/<quota_id>/reject-override", methods=["POST"])
@require_roles("WaterAdmin")
def reject_override(quota_id):
    body = get_json_body()
    with LOCK:
        rec = fetch_or_404(DB.water_quotas, quota_id)
        if rec.get("approval_state") in ("APPROVED", "REJECTED"):
            raise override_already_decided()
        if rec.get("approval_state") != "PENDING_APPROVAL":
            raise invalid_state("Override is not PENDING_APPROVAL")
        rec["approval_state"] = "REJECTED"
        bump_version(rec)
        append_audit(
            action_type="QUOTA_OVERRIDE_REJECTED",
            subject_type="WATER_QUOTA",
            subject_id=rec["id"],
            payload={"reason": body.get("reason")},
        )
    return success_object(water_quota_view(rec))
