"""Convert internal row dicts to API-shaped output dicts.

Internal storage may hold datetime objects in some fields (plan clock); these
serializers normalize datetimes to ISO 8601 strings.
"""

from db import DB
from services.time_util import format_iso, parse_iso
from services.calculations import compute_vested_quantity


def _iso(v):
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return format_iso(v)


def serialize_plan(plan):
    pool_reserved = compute_pool_reserved_options(plan)
    return {
        "id": plan["id"],
        "name": plan["name"],
        "pool_total_options": plan["pool_total_options"],
        "pool_reserved_options": pool_reserved,
        "pool_remaining_options": plan["pool_total_options"] - pool_reserved,
        "jurisdiction_code": plan["jurisdiction_code"],
        "current_clock_ts": _iso(plan.get("current_clock_ts")),
        "status": plan["status"],
        "created_at": plan["created_at"],
        "updated_at": plan["updated_at"],
        "version": plan["version"],
    }


def serialize_batch(batch):
    return {
        "id": batch["id"],
        "plan_id": batch["plan_id"],
        "batch_label": batch["batch_label"],
        "cliff_months": batch["cliff_months"],
        "vesting_total_months": batch["vesting_total_months"],
        "vesting_period_months": batch["vesting_period_months"],
        "vesting_algorithm": batch["vesting_algorithm"],
        "performance_condition_required": batch.get("performance_condition_required", False),
        "initial_price_per_option_cents": batch.get("initial_price_per_option_cents"),
        "status": batch["status"],
        "created_at": batch["created_at"],
        "updated_at": batch["updated_at"],
        "version": batch["version"],
    }


def serialize_grantee(g):
    return {
        "id": g["id"],
        "plan_id": g["plan_id"],
        "hr_employee_id": g["hr_employee_id"],
        "full_name": g["full_name"],
        "tax_residency": g["tax_residency"],
        "eligibility_status": g["eligibility_status"],
        "departed_at": _iso(g.get("departed_at")),
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def serialize_grant(grant, recompute=True):
    plan = DB["option_plans"].get(grant["plan_id"]) or {}
    batch = DB["grant_batches"].get(grant["batch_id"]) or {}
    if recompute and grant.get("status") not in (None, "DRAFT"):
        vested = compute_vested_quantity(grant, plan, batch)
    else:
        vested = int(grant.get("vested_quantity", 0))
    grant["vested_quantity"] = vested
    quantity = int(grant["quantity"])
    exercised = int(grant.get("exercised_quantity", 0))
    forfeited = int(grant.get("forfeited_quantity", 0))
    outstanding = quantity - exercised - forfeited

    return {
        "id": grant["id"],
        "plan_id": grant["plan_id"],
        "batch_id": grant["batch_id"],
        "grantee_id": grant["grantee_id"],
        "quantity": quantity,
        "grant_date": _iso(grant.get("grant_date")),
        "grant_date_fair_value_cents": grant["grant_date_fair_value_cents"],
        "pinned_price_version_id": grant.get("pinned_price_version_id"),
        "board_approval_actor_id": grant.get("board_approval_actor_id"),
        "shareholder_approval_actor_id": grant.get("shareholder_approval_actor_id"),
        "submitted_by_actor_id": grant.get("submitted_by_actor_id"),
        "vested_quantity": vested,
        "exercised_quantity": exercised,
        "forfeited_quantity": forfeited,
        "outstanding_quantity": outstanding,
        "performance_attested_at": _iso(grant.get("performance_attested_at")),
        "status": grant["status"],
        "created_at": grant["created_at"],
        "updated_at": grant["updated_at"],
        "version": grant["version"],
    }


def serialize_window(w):
    return {
        "id": w["id"],
        "plan_id": w["plan_id"],
        "label": w["label"],
        "open_ts": _iso(w["open_ts"]),
        "close_ts": _iso(w["close_ts"]),
        "status": w["status"],
        "notified_at": _iso(w.get("notified_at")),
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def serialize_corporate_event(e):
    return {
        "id": e["id"],
        "plan_id": e["plan_id"],
        "event_type": e["event_type"],
        "effective_ts": _iso(e["effective_ts"]),
        "blackout_end_ts": _iso(e.get("blackout_end_ts")),
        "split_ratio_numerator": e.get("split_ratio_numerator"),
        "split_ratio_denominator": e.get("split_ratio_denominator"),
        "dividend_amount_cents": e.get("dividend_amount_cents"),
        "restructure_factor_bps": e.get("restructure_factor_bps"),
        "created_at": e["created_at"],
    }


def serialize_price_version(v):
    return {
        "id": v["id"],
        "plan_id": v["plan_id"],
        "batch_id": v["batch_id"],
        "version_index": v["version_index"],
        "parent_version_id": v.get("parent_version_id"),
        "cause": v["cause"],
        "corporate_event_id": v.get("corporate_event_id"),
        "price_per_option_cents": v["price_per_option_cents"],
        "effective_from_ts": _iso(v.get("effective_from_ts")),
        "disclosed_at": _iso(v.get("disclosed_at")),
        "created_at": v["created_at"],
    }


def serialize_application(app):
    return {
        "id": app["id"],
        "plan_id": app["plan_id"],
        "grant_id": app["grant_id"],
        "window_id": app["window_id"],
        "pinned_price_version_id": app["pinned_price_version_id"],
        "requested_quantity": app["requested_quantity"],
        "settlement_mode": app["settlement_mode"],
        "gross_proceeds_cents": app.get("gross_proceeds_cents"),
        "withholding_tax_cents": app.get("withholding_tax_cents"),
        "net_proceeds_cents": app.get("net_proceeds_cents"),
        "payment_reference": app.get("payment_reference"),
        "share_registry_reference": app.get("share_registry_reference"),
        "status": app["status"],
        "created_at": app["created_at"],
        "updated_at": app["updated_at"],
        "version": app["version"],
    }


def serialize_vesting_record(v):
    return {
        "id": v["id"],
        "grant_id": v["grant_id"],
        "tranche_index": v["tranche_index"],
        "vested_ts": _iso(v.get("vested_ts")),
        "tranche_quantity": v["tranche_quantity"],
        "cause": v["cause"],
        "archived": v.get("archived", False),
        "created_at": v["created_at"],
    }


def serialize_tax_event(t):
    return {
        "id": t["id"],
        "grant_id": t["grant_id"],
        "exercise_application_id": t.get("exercise_application_id"),
        "event_type": t["event_type"],
        "taxable_amount_cents": t["taxable_amount_cents"],
        "withheld_amount_cents": t["withheld_amount_cents"],
        "deferred": t.get("deferred", False),
        "jurisdiction_code": t["jurisdiction_code"],
        "document_id": t.get("document_id"),
        "event_ts": _iso(t.get("event_ts")),
        "created_at": t["created_at"],
    }


def serialize_departure(d):
    return {
        "id": d["id"],
        "grantee_id": d["grantee_id"],
        "departure_type": d["departure_type"],
        "leaver_class": d.get("leaver_class"),
        "departed_ts": _iso(d.get("departed_ts")),
        "post_departure_window_days": d.get("post_departure_window_days"),
        "post_departure_exercise_deadline_ts": _iso(d.get("post_departure_exercise_deadline_ts")),
        "forfeited_options_total": d.get("forfeited_options_total", 0),
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_audit(a):
    return {
        "id": a["id"],
        "plan_id": a.get("plan_id"),
        "actor_id": a.get("actor_id"),
        "actor_role": a.get("actor_role"),
        "action_code": a["action_code"],
        "target_entity": a["target_entity"],
        "target_id": a["target_id"],
        "payload_summary": a.get("payload_summary"),
        "occurred_ts": _iso(a.get("occurred_ts")),
        "created_at": a["created_at"],
    }


# ---------------------------------------------------------------------------
# Pool aggregation
# ---------------------------------------------------------------------------

POOL_STATUSES = {"BOARD_APPROVED", "SHAREHOLDER_APPROVED", "AGREEMENT_SIGNED", "LIVE", "FROZEN"}


def compute_pool_reserved_options(plan):
    total = 0
    for g in DB["grants"].values():
        if g["plan_id"] != plan["id"]:
            continue
        if g["status"] in POOL_STATUSES:
            q = int(g["quantity"])
            ex = int(g.get("exercised_quantity", 0))
            fo = int(g.get("forfeited_quantity", 0))
            total += (q - ex - fo)
    return total
