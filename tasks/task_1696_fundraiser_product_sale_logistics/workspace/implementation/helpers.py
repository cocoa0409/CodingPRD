"""Shared helpers: field validation, serializers, entity lookup, pagination."""

import uuid
from datetime import timedelta

import db
import errors
from db import clock, _parse_iso, _format_iso


# ---------------------------------------------------------------------------
# Identity / timestamps
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def now_iso():
    return clock.now_iso()


def touch(entity):
    """Refresh updated_at and bump version on a mutable resource."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Field validators (raise ERR_VALIDATION)
# ---------------------------------------------------------------------------

def req_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise errors.err_validation(f"{field} is required and must be a non-empty string")
    return v


def opt_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise errors.err_validation(f"{field} must be a string")
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err_validation(f"{field} is required and must be an integer")
    if minimum is not None and v < minimum:
        raise errors.err_validation(f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise errors.err_validation(f"{field} must be <= {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None, allow_null=False):
    if field not in body:
        return default
    v = body[field]
    if v is None and allow_null:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err_validation(f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise errors.err_validation(f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise errors.err_validation(f"{field} must be <= {maximum}")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise errors.err_validation(f"{field} must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise errors.err_validation(f"{field} must be one of {sorted(allowed)}")
    return v


def req_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise errors.err_validation(f"{field} is required and must be an ISO8601 string")
    try:
        dt = _parse_iso(v)
    except Exception:
        raise errors.err_validation(f"{field} must be a valid ISO8601 timestamp")
    return dt


# ---------------------------------------------------------------------------
# Entity lookups (path-segment existence)
# ---------------------------------------------------------------------------

def get_campaign(cid):
    c = db.campaigns.get(cid)
    if c is None:
        raise errors.err_campaign_not_found()
    return c


def get_group(gid):
    g = db.groups.get(gid)
    if g is None:
        raise errors.err_group_not_found()
    return g


def get_product(pid):
    p = db.products.get(pid)
    if p is None:
        raise errors.err_product_not_found()
    return p


def get_prize(pid):
    p = db.prizes.get(pid)
    if p is None:
        raise errors.err_prize_not_found()
    return p


def get_seller(sid):
    s = db.sellers.get(sid)
    if s is None:
        raise errors.err_seller_not_found()
    return s


def get_order(oid):
    o = db.orders.get(oid)
    if o is None:
        raise errors.err_order_not_found()
    return o


def get_order_line(lid):
    ln = db.order_lines.get(lid)
    if ln is None:
        raise errors.err_order_line_not_found()
    return ln


def get_payment(pid):
    p = db.payments.get(pid)
    if p is None:
        raise errors.err_payment_not_found()
    return p


def get_supplier_order(sid):
    s = db.supplier_orders.get(sid)
    if s is None:
        raise errors.err_supplier_order_not_found()
    return s


def get_event(eid):
    e = db.distribution_events.get(eid)
    if e is None:
        raise errors.err_distribution_event_not_found()
    return e


def get_sort_ticket(tid):
    t = db.sort_tickets.get(tid)
    if t is None:
        raise errors.err_sort_ticket_not_found()
    return t


def get_appointment(aid):
    a = db.pickup_appointments.get(aid)
    if a is None:
        raise errors.err_appointment_not_found()
    return a


def get_claim(cid):
    c = db.claims.get(cid)
    if c is None:
        raise errors.err_claim_not_found()
    return c


def get_return(rid):
    r = db.return_requests.get(rid)
    if r is None:
        raise errors.err_return_not_found()
    return r


def get_prize_award(aid):
    a = db.prize_awards.get(aid)
    if a is None:
        raise errors.err_prize_award_not_found()
    return a


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------

def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


def sort_created(items):
    """Default list ordering: created_at ASC. Ties broken by insertion order (stable)."""
    return sorted(items, key=lambda e: e["created_at"])


# ---------------------------------------------------------------------------
# Serializers (computed fields resolved at read time)
# ---------------------------------------------------------------------------

def serialize_campaign(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "school_name": c["school_name"],
        "order_window_start": c["order_window_start"],
        "order_window_end": c["order_window_end"],
        "expected_delivery_date": c["expected_delivery_date"],
        "default_profit_share_bps": c["default_profit_share_bps"],
        "status": c["status"],
        "distribution_completed_at": c["distribution_completed_at"],
        "gross_sales_cents": c["gross_sales_cents"],
        "family_credits_cents": c["family_credits_cents"],
        "estimated_supplier_cost_cents": c["estimated_supplier_cost_cents"],
        "actual_supplier_cost_cents": c["actual_supplier_cost_cents"],
        "general_fund_cents": c["general_fund_cents"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_group(g):
    return {
        "id": g["id"],
        "campaign_id": g["campaign_id"],
        "name": g["name"],
        "teacher_name": g["teacher_name"],
        "provisional_proceeds_cents": g["provisional_proceeds_cents"],
        "proceeds_balance_cents": g["proceeds_balance_cents"],
        "final_proceeds_cents": g["final_proceeds_cents"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def serialize_product(p):
    return {
        "id": p["id"],
        "campaign_id": p["campaign_id"],
        "name": p["name"],
        "sku": p["sku"],
        "unit_price_cents": p["unit_price_cents"],
        "supplier_unit_cost_cents": p["supplier_unit_cost_cents"],
        "case_pack_size": p["case_pack_size"],
        "profit_share_bps": p["profit_share_bps"],
        "per_seller_limit": p["per_seller_limit"],
        "returnable": p["returnable"],
        "status": p["status"],
        "delivered_units": p["delivered_units"],
        "distributed_units": p["distributed_units"],
        "restocked_units": p["restocked_units"],
        "written_off_units": p["written_off_units"],
        "lost_units": p["lost_units"],
        "surplus_units": p["surplus_units"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_prize(p):
    return {
        "id": p["id"],
        "campaign_id": p["campaign_id"],
        "name": p["name"],
        "tier_type": p["tier_type"],
        "threshold_value": p["threshold_value"],
        "prize_cost_cents": p["prize_cost_cents"],
        "stock_quantity": p["stock_quantity"],
        "remaining_quantity": p["remaining_quantity"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_seller(s):
    return {
        "id": s["id"],
        "group_id": s["group_id"],
        "campaign_id": s["campaign_id"],
        "display_name": s["display_name"],
        "status": s["status"],
        "units_sold": s["units_sold"],
        "revenue_cents": s["revenue_cents"],
        "orders_count": s["orders_count"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_order(o):
    return {
        "id": o["id"],
        "seller_id": o["seller_id"],
        "campaign_id": o["campaign_id"],
        "group_id": o["group_id"],
        "family_contact_name": o["family_contact_name"],
        "status": o["status"],
        "payment_status": o["payment_status"],
        "fulfillment_status": o["fulfillment_status"],
        "total_cents": o["total_cents"],
        "cleared_cents": o["cleared_cents"],
        "provisional_credit_cents": o["provisional_credit_cents"],
        "submitted_at": o["submitted_at"],
        "idempotency_key": o["idempotency_key"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def serialize_order_line(ln):
    return {
        "id": ln["id"],
        "order_id": ln["order_id"],
        "product_id": ln["product_id"],
        "quantity": ln["quantity"],
        "unit_price_cents": ln["unit_price_cents"],
        "unit_cost_cents": ln["unit_cost_cents"],
        "line_total_cents": ln["line_total_cents"],
        "returned_qty": ln["returned_qty"],
        "claim_resolved_refund_qty": ln["claim_resolved_refund_qty"],
        "sort_shortage_qty": ln["sort_shortage_qty"],
        "created_at": ln["created_at"],
        "updated_at": ln["updated_at"],
        "version": ln["version"],
    }


def serialize_payment(p):
    return {
        "id": p["id"],
        "order_id": p["order_id"],
        "amount_cents": p["amount_cents"],
        "method": p["method"],
        "external_ref": p["external_ref"],
        "status": p["status"],
        "recorded_by_user_id": p["recorded_by_user_id"],
        "refunded_amount_cents": p["refunded_amount_cents"],
        "idempotency_key": p["idempotency_key"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_supplier_order(so):
    return {
        "id": so["id"],
        "campaign_id": so["campaign_id"],
        "status": so["status"],
        "submitted_by_user_id": so["submitted_by_user_id"],
        "acknowledged_by_user_id": so["acknowledged_by_user_id"],
        "delivered_by_user_id": so["delivered_by_user_id"],
        "confirmed_delivery_date": so["confirmed_delivery_date"],
        "actual_delivery_date": so["actual_delivery_date"],
        "estimated_cost_cents": so["estimated_cost_cents"],
        "actual_cost_cents": so["actual_cost_cents"],
        "total_ordered_units": so["total_ordered_units"],
        "created_at": so["created_at"],
        "updated_at": so["updated_at"],
        "version": so["version"],
    }


def serialize_supplier_order_line(ln):
    return {
        "id": ln["id"],
        "supplier_order_id": ln["supplier_order_id"],
        "product_id": ln["product_id"],
        "requested_units": ln["requested_units"],
        "case_pack_size": ln["case_pack_size"],
        "ordered_cases": ln["ordered_cases"],
        "ordered_units": ln["ordered_units"],
        "unit_cost_estimated_cents": ln["unit_cost_estimated_cents"],
        "unit_cost_actual_cents": ln["unit_cost_actual_cents"],
        "delivered_units": ln["delivered_units"],
        "shortage_units": ln["shortage_units"],
        "created_at": ln["created_at"],
        "updated_at": ln["updated_at"],
        "version": ln["version"],
    }


def serialize_event(e):
    return {
        "id": e["id"],
        "campaign_id": e["campaign_id"],
        "venue": e["venue"],
        "window_start": e["window_start"],
        "window_end": e["window_end"],
        "slot_capacity": e["slot_capacity"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_sort_ticket(t):
    return {
        "id": t["id"],
        "campaign_id": t["campaign_id"],
        "seller_id": t["seller_id"],
        "product_id": t["product_id"],
        "distribution_event_id": t["distribution_event_id"],
        "expected_qty": t["expected_qty"],
        "verified_qty": t["verified_qty"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_appointment(a):
    return {
        "id": a["id"],
        "distribution_event_id": a["distribution_event_id"],
        "order_id": a["order_id"],
        "slot_start": a["slot_start"],
        "slot_end": a["slot_end"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_claim(c):
    return {
        "id": c["id"],
        "order_id": c["order_id"],
        "order_line_id": c["order_line_id"],
        "campaign_id": c["campaign_id"],
        "claim_type": c["claim_type"],
        "quantity": c["quantity"],
        "note": c["note"],
        "status": c["status"],
        "reported_by_user_id": c["reported_by_user_id"],
        "reviewed_by_user_id": c["reviewed_by_user_id"],
        "resolution": c["resolution"],
        "credit_cents": c["credit_cents"],
        "supersedes_claim_id": c["supersedes_claim_id"],
        "auto_generated": c["auto_generated"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_return(r):
    return {
        "id": r["id"],
        "seller_id": r["seller_id"],
        "order_id": r["order_id"],
        "order_line_id": r["order_line_id"],
        "campaign_id": r["campaign_id"],
        "quantity": r["quantity"],
        "reason": r["reason"],
        "status": r["status"],
        "requested_by_user_id": r["requested_by_user_id"],
        "decided_by_user_id": r["decided_by_user_id"],
        "refund_cents": r["refund_cents"],
        "restocking_fee_cents": r["restocking_fee_cents"],
        "resubmission_count": r["resubmission_count"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_prize_award(a):
    return {
        "id": a["id"],
        "seller_id": a["seller_id"],
        "prize_id": a["prize_id"],
        "campaign_id": a["campaign_id"],
        "status": a["status"],
        "qualifying_metric_value": a["qualifying_metric_value"],
        "qualified_at": a["qualified_at"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_ledger_entry(e):
    return {
        "id": e["id"],
        "group_id": e["group_id"],
        "campaign_id": e["campaign_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "reference_type": e["reference_type"],
        "reference_id": e["reference_id"],
        "seq": e["seq"],
        "balance_after_cents": e["balance_after_cents"],
        "memo": e["memo"],
        "created_at": e["created_at"],
    }


def ledger_sort(entries):
    """Ledger replay order: created_at ASC, seq ASC."""
    return sorted(entries, key=lambda e: (e["created_at"], e["seq"]))
