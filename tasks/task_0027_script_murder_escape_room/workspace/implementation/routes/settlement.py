"""Settlement run routes & audit log query."""
from flask import Blueprint, request

from db import store, make_common, bump, parse_iso, fmt_iso
from middleware import require_role
from response import success_object, success_array
from validators import (
    get_json_body, require_string, parse_pagination, paginate_list, sort_by_created_at,
)
from errors import (
    raise_error,
    ERR_SETTLEMENT_RUN_NOT_FOUND, ERR_SETTLEMENT_HAS_OPEN_SESSIONS,
    ERR_SETTLEMENT_ALREADY_FINALIZED, ERR_INVALID_REQUEST, ERR_REVENUE_SPLIT_INVALID,
)
from audit import write_audit
from services import settlement_service

settlement_bp = Blueprint("settlement", __name__)


def run_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "chain_id": r["chain_id"],
        "period_starts_at": r["period_starts_at"],
        "period_ends_at": r["period_ends_at"],
        "included_session_ids": r.get("included_session_ids", []),
        "gross_total_cents": r["gross_total_cents"],
        "venue_payout_cents": r["venue_payout_cents"],
        "author_payout_cents": r["author_payout_cents"],
        "host_payout_cents": r["host_payout_cents"],
        "platform_fee_cents": r["platform_fee_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@settlement_bp.route("/settlement-runs", methods=["POST"])
def create_run():
    user_id, role = require_role("PlatformAdmin")
    body = get_json_body()
    chain_id = require_string(body, "chain_id")
    period_starts_at = require_string(body, "period_starts_at")
    period_ends_at = require_string(body, "period_ends_at")
    try:
        ps = parse_iso(period_starts_at)
        pe = parse_iso(period_ends_at)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, "invalid period timestamps")
    if pe <= ps:
        raise_error(ERR_INVALID_REQUEST, "period_ends_at must be > period_starts_at")

    sids = settlement_service.sweep_included_sessions(chain_id, ps, pe)

    payouts = settlement_service.compute_payouts(sids)

    r = make_common({
        "chain_id": chain_id,
        "period_starts_at": fmt_iso(ps),
        "period_ends_at": fmt_iso(pe),
        "included_session_ids": sids,
        "gross_total_cents": payouts["gross_total_cents"],
        "venue_payout_cents": payouts["venue_payout_cents"],
        "author_payout_cents": payouts["author_payout_cents"],
        "host_payout_cents": payouts["host_payout_cents"],
        "platform_fee_cents": payouts["platform_fee_cents"],
        "status": "DRAFT",
    })
    store.settlement_runs[r["id"]] = r
    return success_object(run_view(r), 201)


@settlement_bp.route("/settlement-runs/<run_id>/finalize", methods=["POST"])
def finalize_run(run_id):
    user_id, role = require_role("PlatformAdmin")
    r = store.settlement_runs.get(run_id)
    if not r:
        raise_error(ERR_SETTLEMENT_RUN_NOT_FOUND, "run not found")
    if r["status"] != "DRAFT":
        raise_error(ERR_SETTLEMENT_ALREADY_FINALIZED, "run not DRAFT")
    sids = r.get("included_session_ids") or []
    if not settlement_service.all_included_completed(sids):
        raise_error(ERR_SETTLEMENT_HAS_OPEN_SESSIONS, "some sessions not COMPLETED")
    settlement_service.validate_revenue_split_for_finalize(sids, r["chain_id"])
    # Recompute payouts again (just in case)
    payouts = settlement_service.compute_payouts(sids)
    r["gross_total_cents"] = payouts["gross_total_cents"]
    r["author_payout_cents"] = payouts["author_payout_cents"]
    r["host_payout_cents"] = payouts["host_payout_cents"]
    r["venue_payout_cents"] = payouts["venue_payout_cents"]
    r["platform_fee_cents"] = payouts["platform_fee_cents"]
    r["status"] = "FINALIZED"
    bump(r)
    write_audit(user_id, role, "SettlementRun", r["id"], "SETTLEMENT_FINALIZED", r)
    return success_object(run_view(r))


@settlement_bp.route("/settlement-runs/<run_id>", methods=["GET"])
def get_run(run_id):
    require_role("PlatformAdmin")
    r = store.settlement_runs.get(run_id)
    if not r:
        raise_error(ERR_SETTLEMENT_RUN_NOT_FOUND, "run not found")
    return success_object(run_view(r))


# =========================================================
# Audit log query
# =========================================================
@settlement_bp.route("/audit-log", methods=["GET"])
def query_audit_log():
    require_role("PlatformAdmin")
    limit, offset = parse_pagination()
    sub_type = request.args.get("subject_entity_type")
    sub_id = request.args.get("subject_entity_id")
    actor = request.args.get("actor_user_id")
    items = list(store.audit_log)
    if sub_type:
        items = [x for x in items if x["subject_entity_type"] == sub_type]
    if sub_id:
        items = [x for x in items if x["subject_entity_id"] == sub_id]
    if actor:
        items = [x for x in items if x["actor_user_id"] == actor]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate_list(items, limit, offset)
    return success_array(page, limit, offset, total)
