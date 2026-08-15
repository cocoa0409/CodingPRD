"""Commercial Printing Plant API — Flask implementation.

Storage is in-memory only (dicts keyed by id). State starts empty on every
boot; the logical clock starts at exactly 2026-08-01T00:00:00Z.
"""
import math
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
LOGICAL_CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now_dt():
    return LOGICAL_CLOCK["now"]


def fmt_ts(dt):
    """ISO8601 UTC with 3 fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_dt(value):
    """Parse an ISO8601 datetime string into an aware datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    # Accept trailing Z as UTC
    if s.endswith("Z"):
        s2 = s[:-1] + "+00:00"
    else:
        s2 = s
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "customers": {},
    "estimates": {},
    "jobs": {},
    "proofs": {},
    "paper_stocks": {},
    "paper_purchase_orders": {},
    "paper_lots": {},
    "presses": {},
    "press_runs": {},
    "gang_runs": {},
    "bindery_tickets": {},
    "mail_drops": {},
    "invoices": {},
    "reprint_claims": {},
}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or unknown X-User-Role or X-User-ID header"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden_role(msg="Role not permitted on this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", msg, 403)


def err_not_own(msg="Customer role accessing a resource whose customer_id does not match X-User-ID"):
    return ApiError("ERR_NOT_OWN_RESOURCE", msg, 403)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_validation(msg="Invalid request field"):
    return ApiError("ERR_VALIDATION", msg, 400)


def err_stale(msg="Stale version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_invalid_state(msg="Invalid state"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def make_meta(extra=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_ts(now_dt()),
    }
    if extra:
        m.update(extra)
    return m


def success_object(data, status=200):
    return jsonify({"meta": make_meta(), "response_type": "object", "data": data}), status


def success_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta = make_meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------
ROLES = {
    "Estimator",
    "Customer",
    "PrepressOperator",
    "PressScheduler",
    "PurchasingManager",
    "MailSpecialist",
    "PlantManager",
}


def get_auth():
    """Returns (user_id, role) or raises ApiError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_role(allowed_roles):
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise err_forbidden_role()
    return user_id, role


def check_customer_ownership(user_id, role, resource_customer_id):
    if role == "Customer" and resource_customer_id != user_id:
        raise err_not_own()


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_field(body, name):
    if not isinstance(body, dict) or name not in body or body[name] is None:
        raise err_validation(f"Missing required field: {name}")
    return body[name]


def opt_field(body, name, default=None):
    if not isinstance(body, dict):
        return default
    v = body.get(name, default)
    return default if v is None else v


def as_int(v, name, min_v=None, max_v=None):
    if not is_int(v):
        raise err_validation(f"{name} must be an integer")
    if min_v is not None and v < min_v:
        raise err_validation(f"{name} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise err_validation(f"{name} must be <= {max_v}")
    return v


def as_num(v, name, min_v=None):
    if not is_num(v):
        raise err_validation(f"{name} must be a number")
    if min_v is not None and v < min_v:
        raise err_validation(f"{name} must be >= {min_v}")
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise err_validation(f"{name} must be one of {sorted(allowed)}")
    return v


def as_str(v, name):
    if not isinstance(v, str):
        raise err_validation(f"{name} must be a string")
    return v


def parse_limit_offset():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_validation("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_validation("offset must be an integer")
        if offset < 0:
            raise err_validation("offset must be >= 0")
    return limit, offset


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------
def rhu(dec_val):
    """Round half-up to integer. Accepts int/Decimal."""
    if isinstance(dec_val, int):
        return dec_val
    return int(Decimal(dec_val).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_customer(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "credit_limit_cents": c["credit_limit_cents"],
        "default_tolerance_pct": c["default_tolerance_pct"],
        "exposure_cents": compute_customer_exposure(c["id"]),
        "posture": compute_customer_posture(c["id"]),
        "reprint_credit_balance_cents": c["reprint_credit_balance_cents"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_estimate(e):
    return {
        "id": e["id"],
        "customer_id": e["customer_id"],
        "job_name": e["job_name"],
        "quantity_ordered": e["quantity_ordered"],
        "press_type": e["press_type"],
        "binding_method": e["binding_method"],
        "fulfillment_type": e["fulfillment_type"],
        "signatures": e["signatures"],
        "finishing_options": e["finishing_options"],
        "press_spoilage_pct": e["press_spoilage_pct"],
        "bindery_spoilage_pct": e["bindery_spoilage_pct"],
        "included_proof_rounds": e["included_proof_rounds"],
        "quote_valid_days": e["quote_valid_days"],
        "due_date": e["due_date"],
        "impressions_per_signature": e["impressions_per_signature"],
        "total_impressions": e["total_impressions"],
        "make_ready_total_cents": e["make_ready_total_cents"],
        "running_cost_cents": e["running_cost_cents"],
        "paper_sheets_total": e["paper_sheets_total"],
        "paper_cost_cents": e["paper_cost_cents"],
        "finishing_cost_cents": e["finishing_cost_cents"],
        "subtotal_cents": e["subtotal_cents"],
        "discount_pct": e["discount_pct"],
        "total_price_cents": e["total_price_cents"],
        "status": e["status"],
        "quoted_at": e["quoted_at"],
        "expires_at": e["expires_at"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_job(j):
    return {
        "id": j["id"],
        "estimate_id": j["estimate_id"],
        "parent_job_id": j["parent_job_id"],
        "customer_id": j["customer_id"],
        "zero_charge": j["zero_charge"],
        "quantity_ordered": j["quantity_ordered"],
        "due_date": j["due_date"],
        "press_type": j["press_type"],
        "fulfillment_type": j["fulfillment_type"],
        "binding_method": j["binding_method"],
        "signatures": j["signatures"],
        "press_spoilage_pct": j["press_spoilage_pct"],
        "bindery_spoilage_pct": j["bindery_spoilage_pct"],
        "included_proof_rounds": j["included_proof_rounds"],
        "tolerance_pct": j["tolerance_pct"],
        "total_impressions": j["total_impressions"],
        "make_ready_total_cents": j["make_ready_total_cents"],
        "total_price_cents": j["total_price_cents"],
        "discount_pct": j["discount_pct"],
        "subtotal_cents": j["subtotal_cents"],
        "production_status": j["production_status"],
        "billing_status": j["billing_status"],
        "gang_run_id": j["gang_run_id"],
        "allocated_make_ready_cents": j["allocated_make_ready_cents"],
        "delivered_quantity": j["delivered_quantity"],
        "proof_rounds_used": j["proof_rounds_used"],
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
    }


def ser_proof(p):
    return {
        "id": p["id"],
        "job_id": p["job_id"],
        "file_uri": p["file_uri"],
        "round_number": p["round_number"],
        "status": p["status"],
        "decided_at": p["decided_at"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_paper_stock(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "grade": s["grade"],
        "cost_per_sheet_cents": s["cost_per_sheet_cents"],
        "reorder_threshold_sheets": s["reorder_threshold_sheets"],
        "reorder_quantity_sheets": s["reorder_quantity_sheets"],
        "available_sheets": compute_stock_available(s["id"]),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_po(po):
    return {
        "id": po["id"],
        "paper_stock_id": po["paper_stock_id"],
        "ordered_sheets": po["ordered_sheets"],
        "cost_per_sheet_cents": po["cost_per_sheet_cents"],
        "source": po["source"],
        "received_sheets_total": po["received_sheets_total"],
        "status": po["status"],
        "created_at": po["created_at"],
        "updated_at": po["updated_at"],
        "version": po["version"],
    }


def ser_lot(l):
    return {
        "id": l["id"],
        "paper_stock_id": l["paper_stock_id"],
        "paper_purchase_order_id": l["paper_purchase_order_id"],
        "received_sheets": l["received_sheets"],
        "damaged_sheets": l["damaged_sheets"],
        "reserved_sheets": l["reserved_sheets"],
        "consumed_sheets": l["consumed_sheets"],
        "remaining_sheets": l["received_sheets"] - l["reserved_sheets"] - l["consumed_sheets"] - l["damaged_sheets"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_press(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "press_type": p["press_type"],
        "rated_impressions_per_hour": p["rated_impressions_per_hour"],
        "make_ready_minutes_base": p["make_ready_minutes_base"],
        "washup_buffer_minutes": p["washup_buffer_minutes"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_press_run(r):
    return {
        "id": r["id"],
        "press_id": r["press_id"],
        "job_id": r["job_id"],
        "gang_run_id": r["gang_run_id"],
        "run_quantity": r["run_quantity"],
        "scheduled_start": r["scheduled_start"],
        "planned_impressions": r["planned_impressions"],
        "planned_sheets": r["planned_sheets"],
        "duration_minutes": r["duration_minutes"],
        "scheduled_end": r["scheduled_end"],
        "status": r["status"],
        "gross_impressions": r["gross_impressions"],
        "sheets_used": r["sheets_used"],
        "waste_sheets": r["waste_sheets"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_gang(g):
    return {
        "id": g["id"],
        "paper_stock_id": g["paper_stock_id"],
        "press_type": g["press_type"],
        "anchor_due_date": g["anchor_due_date"],
        "status": g["status"],
        "members": g["members"],
        "make_ready_total_cents": g["make_ready_total_cents"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def ser_ticket(t):
    return {
        "id": t["id"],
        "job_id": t["job_id"],
        "operation": t["operation"],
        "sequence_no": t["sequence_no"],
        "pieces_completed": t["pieces_completed"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_mail_drop(m):
    return {
        "id": m["id"],
        "job_id": m["job_id"],
        "drop_date": m["drop_date"],
        "destination_entry": m["destination_entry"],
        "piece_weight_oz": m["piece_weight_oz"],
        "zip_counts": m["zip_counts"],
        "total_pieces": m["total_pieces"],
        "tier_breakdown": m["tier_breakdown"],
        "postage_cents": m["postage_cents"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_invoice(i):
    return {
        "id": i["id"],
        "job_id": i["job_id"],
        "customer_id": i["customer_id"],
        "kind": i["kind"],
        "quantity_ordered": i["quantity_ordered"],
        "delivered_quantity": i["delivered_quantity"],
        "billable_quantity": i["billable_quantity"],
        "base_amount_cents": i["base_amount_cents"],
        "postage_cents": i["postage_cents"],
        "proof_overage_cents": i["proof_overage_cents"],
        "shortage_credit_cents": i["shortage_credit_cents"],
        "gang_make_ready_allocated_cents": i["gang_make_ready_allocated_cents"],
        "total_due_cents": i["total_due_cents"],
        "amount_paid_cents": i["amount_paid_cents"],
        "credit_applied_cents": i["credit_applied_cents"],
        "amount_outstanding_cents": compute_invoice_outstanding(i),
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def ser_claim(c):
    return {
        "id": c["id"],
        "job_id": c["job_id"],
        "invoice_id": c["invoice_id"],
        "claimed_defect": c["claimed_defect"],
        "defect_qty": c["defect_qty"],
        "status": c["status"],
        "reviewed_by": c["reviewed_by"],
        "resolution": c["resolution"],
        "liability_pct": c["liability_pct"],
        "provisional_credit_cents": c["provisional_credit_cents"],
        "final_credit_cents": c["final_credit_cents"],
        "reprint_job_id": c["reprint_job_id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


# ---------------------------------------------------------------------------
# Entity mutation helpers (bump version + refresh updated_at)
# ---------------------------------------------------------------------------
def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = fmt_ts(now_dt())


def new_id():
    return str(uuid.uuid4())


def new_ts():
    return fmt_ts(now_dt())


# ---------------------------------------------------------------------------
# Computed helpers
# ---------------------------------------------------------------------------
def compute_stock_available(stock_id):
    total = 0
    for lot in DB["paper_lots"].values():
        if lot["paper_stock_id"] == stock_id:
            total += lot["received_sheets"] - lot["reserved_sheets"] - lot["consumed_sheets"] - lot["damaged_sheets"]
    return total


def compute_invoice_outstanding(inv):
    return inv["total_due_cents"] - inv["amount_paid_cents"] - inv["credit_applied_cents"]


def compute_customer_exposure(customer_id):
    total = 0
    for inv in DB["invoices"].values():
        if inv["customer_id"] == customer_id and inv["status"] in ("ISSUED", "PARTIALLY_PAID", "DISPUTED"):
            total += compute_invoice_outstanding(inv)
    for job in DB["jobs"].values():
        if (job["customer_id"] == customer_id
                and job["billing_status"] == "UNBILLED"
                and job["production_status"] not in ("CLOSED", "CANCELLED")):
            total += job["total_price_cents"]
    return total


def compute_customer_posture(customer_id):
    c = DB["customers"][customer_id]
    exposure = compute_customer_exposure(customer_id)
    return "CREDIT_HOLD" if exposure > c["credit_limit_cents"] else "ACTIVE"


def get_or_404(collection, entity_id, name="resource"):
    if entity_id is None:
        raise err_not_found(f"{name} not found")
    e = DB[collection].get(entity_id)
    if e is None:
        raise err_not_found(f"{name} not found")
    return e


# ---------------------------------------------------------------------------
# Pricing pipeline (estimate_provisional_total + signature_impressions + paper_sheets_with_spoilage)
# ---------------------------------------------------------------------------
FINISHING_FEES = {
    "PERF": 18000,
    "SCORE": 12000,
    "UV_COAT": 40000,
    "LAMINATE": 55000,
    "FOIL": 75000,
    "DIE_CUT": 60000,
}


def compute_signature_impressions(quantity_ordered, signatures):
    return [math.ceil(quantity_ordered / s["up_count"]) for s in signatures]


def compute_per_signature_sheets(impressions, signatures, press_spoilage_pct, bindery_spoilage_pct):
    """Compounded ceil per stage. Returns list of per-signature sheets."""
    sheets = []
    for imp, sig in zip(impressions, signatures):
        press_stage = math.ceil(Decimal(imp) * (Decimal(1) + Decimal(str(press_spoilage_pct)) / Decimal(100)))
        bindery_stage = math.ceil(Decimal(press_stage) * (Decimal(1) + Decimal(str(bindery_spoilage_pct)) / Decimal(100)))
        sheets.append(bindery_stage)
    return sheets


def compute_pricing(quantity_ordered, signatures, finishing_options, press_spoilage_pct, bindery_spoilage_pct):
    """Returns dict with all derived pricing fields."""
    impressions_per = compute_signature_impressions(quantity_ordered, signatures)
    total_impressions = sum(impressions_per)

    running_cost = 0
    for imp, sig in zip(impressions_per, signatures):
        per_sig = Decimal(imp) * Decimal(sig["rate_per_thousand_cents"]) / Decimal(1000)
        running_cost += rhu(per_sig)

    make_ready_total = sum(s["make_ready_cents"] for s in signatures)

    sheets_per = compute_per_signature_sheets(impressions_per, signatures, press_spoilage_pct, bindery_spoilage_pct)
    paper_sheets_total = sum(sheets_per)

    paper_cost = 0
    for sheets, sig in zip(sheets_per, signatures):
        stock = DB["paper_stocks"].get(sig["paper_stock_id"])
        if stock is None:
            raise err_not_found(f"paper_stock {sig['paper_stock_id']} not found")
        paper_cost += sheets * stock["cost_per_sheet_cents"]

    finishing_cost = sum(FINISHING_FEES[opt] for opt in finishing_options)

    subtotal = make_ready_total + running_cost + paper_cost + finishing_cost
    if subtotal < 500000:
        discount_pct = 0
    elif subtotal < 2000000:
        discount_pct = 3
    else:
        discount_pct = 5
    total_price = rhu(Decimal(subtotal) * (Decimal(1) - Decimal(discount_pct) / Decimal(100)))

    return {
        "impressions_per_signature": impressions_per,
        "total_impressions": total_impressions,
        "make_ready_total_cents": make_ready_total,
        "running_cost_cents": running_cost,
        "paper_sheets_total": paper_sheets_total,
        "paper_cost_cents": paper_cost,
        "finishing_cost_cents": finishing_cost,
        "subtotal_cents": subtotal,
        "discount_pct": discount_pct,
        "total_price_cents": total_price,
        "sheets_per_signature": sheets_per,  # internal, used by reservation math
    }


# ---------------------------------------------------------------------------
# Gang-adjusted total (final_invoice variant)
# ---------------------------------------------------------------------------
def compute_job_total_basis(job):
    """For gang members: re-run pipeline with allocated_make_ready; else use snapshot."""
    if job.get("allocated_make_ready_cents") is None:
        return job["total_price_cents"], None
    # PRD §3.12: "The gang-adjusted total re-runs the provisional pricing
    # pipeline with the member's `allocated_make_ready_cents` substituted for
    # the standalone make-ready total, and re-derives the discount tier from
    # the adjusted subtotal before applying it."
    # The provisional pipeline's subtotal (§3.2) is make_ready + running +
    # paper + finishing; substituting only the make-ready component leaves the
    # other three components (all integer cents, already rounded at estimate
    # time) unchanged, so the adjusted subtotal is exactly
    # subtotal_cents - make_ready_total_cents + allocated_make_ready_cents.
    adjusted_subtotal = (
        job["subtotal_cents"] - job["make_ready_total_cents"] + job["allocated_make_ready_cents"]
    )
    if adjusted_subtotal < 500000:
        discount_pct = 0
    elif adjusted_subtotal < 2000000:
        discount_pct = 3
    else:
        discount_pct = 5
    total = rhu(Decimal(adjusted_subtotal) * (Decimal(1) - Decimal(discount_pct) / Decimal(100)))
    return total, job["allocated_make_ready_cents"]


# ---------------------------------------------------------------------------
# FIFO paper reservation / consumption
# ---------------------------------------------------------------------------
def fifo_lots_for_stock(stock_id):
    """All lots of a stock ordered by created_at ASC (only created_at tiebreak; ids never used)."""
    lots = [l for l in DB["paper_lots"].values() if l["paper_stock_id"] == stock_id]
    lots.sort(key=lambda l: l["created_at"])
    return lots


def compute_run_planned_sheets_per_signature(run_quantity, signatures, press_spoilage_pct, bindery_spoilage_pct):
    impressions_per = [math.ceil(run_quantity / s["up_count"]) for s in signatures]
    return compute_per_signature_sheets(impressions_per, signatures, press_spoilage_pct, bindery_spoilage_pct)


def reserve_sheets(stock_id, quantity):
    """Reserve `quantity` sheets across FIFO lots. Returns list of (lot_id, qty) reservations.
    Raises ERR_PAPER_INSUFFICIENT if aggregate remaining is insufficient."""
    lots = fifo_lots_for_stock(stock_id)
    total_available = sum(
        l["received_sheets"] - l["reserved_sheets"] - l["consumed_sheets"] - l["damaged_sheets"] for l in lots
    )
    if total_available < quantity:
        raise ApiError("ERR_PAPER_INSUFFICIENT", "Insufficient paper available", 409)
    reservations = []
    remaining = quantity
    for lot in lots:
        if remaining <= 0:
            break
        lot_remaining = lot["received_sheets"] - lot["reserved_sheets"] - lot["consumed_sheets"] - lot["damaged_sheets"]
        take = min(lot_remaining, remaining)
        if take > 0:
            lot["reserved_sheets"] += take
            touch(lot)
            reservations.append({"lot_id": lot["id"], "qty": take})
            remaining -= take
    return reservations


def release_reservations(reservations):
    """Release all reserved sheets back (used on cancel)."""
    for r in reservations:
        lot = DB["paper_lots"].get(r["lot_id"])
        if lot:
            lot["reserved_sheets"] -= r["qty"]
            touch(lot)


def consume_reserved_and_excess(stock_id, reservations, sheets_used):
    """Convert reserved sheets to consumed per the recorded FIFO draw; consume
    additional sheets beyond reserved FIFO; release unused reservation.
    reservations: list of {lot_id, qty} reserved at schedule time.
    Returns list of stocks consumed from (for auto-replenishment check)."""
    # Step 1: walk recorded reservations; consume min(reserved, sheets_used) per lot in order.
    remaining_used = sheets_used
    for r in reservations:
        if remaining_used <= 0:
            # Entire reservation for this lot is unused -> release it
            lot = DB["paper_lots"].get(r["lot_id"])
            if lot and r["qty"] > 0:
                lot["reserved_sheets"] -= r["qty"]
                touch(lot)
            continue
        lot = DB["paper_lots"].get(r["lot_id"])
        if not lot:
            continue
        consume_here = min(r["qty"], remaining_used)
        lot["reserved_sheets"] -= consume_here
        lot["consumed_sheets"] += consume_here
        # Release unused portion of this lot's reservation
        unused = r["qty"] - consume_here
        if unused > 0:
            lot["reserved_sheets"] -= unused
        touch(lot)
        remaining_used -= consume_here
    # Step 2: any excess beyond reserved draws additional sheets FIFO from this stock
    if remaining_used > 0:
        lots = fifo_lots_for_stock(stock_id)
        total_available = sum(
            l["received_sheets"] - l["reserved_sheets"] - l["consumed_sheets"] - l["damaged_sheets"] for l in lots
        )
        if total_available < remaining_used:
            raise ApiError("ERR_PAPER_INSUFFICIENT", "Insufficient paper for excess consumption", 409)
        for lot in lots:
            if remaining_used <= 0:
                break
            lot_remaining = lot["received_sheets"] - lot["reserved_sheets"] - lot["consumed_sheets"] - lot["damaged_sheets"]
            take = min(lot_remaining, remaining_used)
            if take > 0:
                lot["consumed_sheets"] += take
                touch(lot)
                remaining_used -= take
    return [stock_id]


def maybe_auto_replenish(stock_id):
    """After consumption, check threshold and auto-create PO if needed."""
    stock = DB["paper_stocks"].get(stock_id)
    if stock is None:
        return
    available = compute_stock_available(stock_id)
    if available < stock["reorder_threshold_sheets"]:
        # Check no open AUTO_REPLENISH PO exists
        for po in DB["paper_purchase_orders"].values():
            if (po["paper_stock_id"] == stock_id
                    and po["source"] == "AUTO_REPLENISH"
                    and po["status"] in ("ORDERED", "PARTIALLY_RECEIVED")):
                return
        ts = new_ts()
        po = {
            "id": new_id(),
            "paper_stock_id": stock_id,
            "ordered_sheets": stock["reorder_quantity_sheets"],
            "cost_per_sheet_cents": stock["cost_per_sheet_cents"],
            "source": "AUTO_REPLENISH",
            "received_sheets_total": 0,
            "status": "ORDERED",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        DB["paper_purchase_orders"][po["id"]] = po


# ---------------------------------------------------------------------------
# Customer exposure / posture recompute (no-op since computed on read)
# ---------------------------------------------------------------------------
def recompute_customer(customer_id):
    # exposure/posture are computed on read; nothing to persist. Kept for clarity.
    pass


# ---------------------------------------------------------------------------
# Job SETTLED cascade on invoice PAID
# ---------------------------------------------------------------------------
def cascade_invoice_paid(invoice):
    """After an invoice reaches PAID, update job billing and possibly production."""
    job = DB["jobs"].get(invoice["job_id"])
    if job is None:
        return
    # Every non-void invoice of this job PAID -> SETTLED
    job_invoices = [i for i in DB["invoices"].values() if i["job_id"] == job["id"]]
    all_paid = all(i["status"] == "PAID" for i in job_invoices) if job_invoices else False
    if all_paid and job["billing_status"] == "INVOICED":
        job["billing_status"] = "SETTLED"
        if job["production_status"] == "FULFILLED":
            job["production_status"] = "CLOSED"
        touch(job)
    recompute_customer(job["customer_id"])


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(err_not_found("Not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(err_not_found("Method not allowed"))


@app.errorhandler(Exception)
def handle_generic(err):
    # Surface unexpected errors as 400 ERR_VALIDATION rather than crashing
    if isinstance(err, ApiError):
        return error_response(err)
    import traceback
    traceback.print_exc()
    return error_response(ApiError("ERR_VALIDATION", f"Unhandled: {err}", 400))


# ===========================================================================
# CUSTOMERS
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    user_id, role = require_role(["PlantManager"])
    body = request.get_json(silent=True) or {}
    name = as_str(req_field(body, "name"), "name")
    credit_limit_cents = as_int(req_field(body, "credit_limit_cents"), "credit_limit_cents", min_v=0)
    default_tolerance_pct = opt_field(body, "default_tolerance_pct", 5)
    default_tolerance_pct = as_int(default_tolerance_pct, "default_tolerance_pct", min_v=0)
    ts = new_ts()
    c = {
        "id": new_id(),
        "name": name,
        "credit_limit_cents": credit_limit_cents,
        "default_tolerance_pct": default_tolerance_pct,
        "reprint_credit_balance_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["customers"][c["id"]] = c
    return success_object(ser_customer(c), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    user_id, role = require_role(["Estimator", "Customer", "PrepressOperator", "PressScheduler",
                                   "PurchasingManager", "MailSpecialist", "PlantManager"])
    c = get_or_404("customers", cid, "customer")
    check_customer_ownership(user_id, role, c["id"])
    return success_object(ser_customer(c))


@app.route("/customers", methods=["GET"])
def list_customers():
    user_id, role = require_role(["Estimator", "Customer", "PrepressOperator", "PressScheduler",
                                   "PurchasingManager", "MailSpecialist", "PlantManager"])
    limit, offset = parse_limit_offset()
    posture = request.args.get("posture")
    items = list(DB["customers"].values())
    if role == "Customer":
        items = [c for c in items if c["id"] == user_id]
    if posture:
        items = [c for c in items if compute_customer_posture(c["id"]) == posture]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_customer(c) for c in page], limit, offset, total)


# ===========================================================================
# ESTIMATES
# ===========================================================================
def validate_signatures(signatures):
    if not isinstance(signatures, list) or len(signatures) < 1:
        raise err_validation("signatures must be a non-empty array")
    out = []
    for s in signatures:
        if not isinstance(s, dict):
            raise err_validation("signature must be an object")
        name = as_str(req_field(s, "name"), "signature.name")
        pages = as_int(req_field(s, "pages"), "signature.pages", min_v=1)
        up_count = as_int(req_field(s, "up_count"), "signature.up_count", min_v=1)
        paper_stock_id = as_str(req_field(s, "paper_stock_id"), "signature.paper_stock_id")
        make_ready_cents = as_int(req_field(s, "make_ready_cents"), "signature.make_ready_cents", min_v=0)
        rate_per_thousand_cents = as_int(req_field(s, "rate_per_thousand_cents"),
                                          "signature.rate_per_thousand_cents", min_v=0)
        out.append({
            "name": name,
            "pages": pages,
            "up_count": up_count,
            "paper_stock_id": paper_stock_id,
            "make_ready_cents": make_ready_cents,
            "rate_per_thousand_cents": rate_per_thousand_cents,
        })
    return out


def validate_finishing(opts):
    if opts is None:
        return []
    if not isinstance(opts, list):
        raise err_validation("finishing_options must be an array")
    for o in opts:
        if o not in FINISHING_FEES:
            raise err_validation(f"finishing_options contains unknown option {o}")
    return list(opts)


@app.route("/estimates", methods=["POST"])
def create_estimate():
    user_id, role = require_role(["Estimator"])
    body = request.get_json(silent=True) or {}
    customer_id = as_str(req_field(body, "customer_id"), "customer_id")
    job_name = as_str(req_field(body, "job_name"), "job_name")
    quantity_ordered = as_int(req_field(body, "quantity_ordered"), "quantity_ordered", min_v=1)
    press_type = as_enum(req_field(body, "press_type"), "press_type", {"WEB", "SHEETFED"})
    binding_method = as_enum(req_field(body, "binding_method"), "binding_method",
                              {"SADDLE_STITCH", "PERFECT_BIND", "CASE_BIND", "PLASTIC_COIL"})
    fulfillment_type = as_enum(req_field(body, "fulfillment_type"), "fulfillment_type", {"SHIP", "MAIL"})
    signatures = validate_signatures(req_field(body, "signatures"))
    press_spoilage_pct = as_num(req_field(body, "press_spoilage_pct"), "press_spoilage_pct", min_v=0)
    bindery_spoilage_pct = as_num(req_field(body, "bindery_spoilage_pct"), "bindery_spoilage_pct", min_v=0)
    due_date_raw = as_str(req_field(body, "due_date"), "due_date")
    try:
        due_dt = parse_dt(due_date_raw)
    except Exception:
        raise err_validation("due_date must be ISO8601")
    finishing_options = validate_finishing(body.get("finishing_options", []))
    included_proof_rounds = as_int(opt_field(body, "included_proof_rounds", 2), "included_proof_rounds", min_v=0)
    quote_valid_days = as_int(opt_field(body, "quote_valid_days", 30), "quote_valid_days", min_v=0)

    # FK resolution
    customer = DB["customers"].get(customer_id)
    if customer is None:
        raise err_not_found("customer not found")
    for sig in signatures:
        if sig["paper_stock_id"] not in DB["paper_stocks"]:
            raise err_not_found(f"paper_stock {sig['paper_stock_id']} not found")

    pricing = compute_pricing(quantity_ordered, signatures, finishing_options,
                              press_spoilage_pct, bindery_spoilage_pct)
    ts = new_ts()
    est = {
        "id": new_id(),
        "customer_id": customer_id,
        "job_name": job_name,
        "quantity_ordered": quantity_ordered,
        "press_type": press_type,
        "binding_method": binding_method,
        "fulfillment_type": fulfillment_type,
        "signatures": signatures,
        "finishing_options": finishing_options,
        "press_spoilage_pct": press_spoilage_pct,
        "bindery_spoilage_pct": bindery_spoilage_pct,
        "included_proof_rounds": included_proof_rounds,
        "quote_valid_days": quote_valid_days,
        "due_date": fmt_ts(due_dt),
        "impressions_per_signature": pricing["impressions_per_signature"],
        "total_impressions": pricing["total_impressions"],
        "make_ready_total_cents": pricing["make_ready_total_cents"],
        "running_cost_cents": pricing["running_cost_cents"],
        "paper_sheets_total": pricing["paper_sheets_total"],
        "paper_cost_cents": pricing["paper_cost_cents"],
        "finishing_cost_cents": pricing["finishing_cost_cents"],
        "subtotal_cents": pricing["subtotal_cents"],
        "discount_pct": pricing["discount_pct"],
        "total_price_cents": pricing["total_price_cents"],
        "status": "DRAFT",
        "quoted_at": None,
        "expires_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["estimates"][est["id"]] = est
    return success_object(ser_estimate(est), 201)


@app.route("/estimates/<eid>", methods=["GET"])
def get_estimate(eid):
    user_id, role = require_role(["Estimator", "Customer", "PlantManager"])
    est = get_or_404("estimates", eid, "estimate")
    check_customer_ownership(user_id, role, est["customer_id"])
    return success_object(ser_estimate(est))


@app.route("/estimates", methods=["GET"])
def list_estimates():
    user_id, role = require_role(["Estimator", "Customer", "PlantManager"])
    limit, offset = parse_limit_offset()
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = list(DB["estimates"].values())
    if role == "Customer":
        items = [e for e in items if e["customer_id"] == user_id]
    if customer_id:
        items = [e for e in items if e["customer_id"] == customer_id]
    if status:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_estimate(e) for e in page], limit, offset, total)


@app.route("/estimates/<eid>", methods=["PUT"])
def revise_estimate(eid):
    user_id, role = require_role(["Estimator"])
    est = get_or_404("estimates", eid, "estimate")
    body = request.get_json(silent=True) or {}
    expected = req_field(body, "expected_estimate_version")
    if not is_int(expected):
        raise err_validation("expected_estimate_version must be an integer")
    if expected != est["version"]:
        raise err_stale("Estimate version mismatch")
    if est["status"] != "DRAFT":
        raise err_invalid_state("Only DRAFT estimates can be revised")

    quantity_ordered = est["quantity_ordered"]
    signatures = est["signatures"]
    finishing_options = est["finishing_options"]
    press_spoilage_pct = est["press_spoilage_pct"]
    bindery_spoilage_pct = est["bindery_spoilage_pct"]
    due_date_str = est["due_date"]
    quote_valid_days = est["quote_valid_days"]
    press_type = est["press_type"]
    binding_method = est["binding_method"]
    fulfillment_type = est["fulfillment_type"]
    included_proof_rounds = est["included_proof_rounds"]

    if "quantity_ordered" in body and body["quantity_ordered"] is not None:
        quantity_ordered = as_int(body["quantity_ordered"], "quantity_ordered", min_v=1)
    if "signatures" in body and body["signatures"] is not None:
        signatures = validate_signatures(body["signatures"])
    if "finishing_options" in body and body["finishing_options"] is not None:
        finishing_options = validate_finishing(body["finishing_options"])
    if "press_spoilage_pct" in body and body["press_spoilage_pct"] is not None:
        press_spoilage_pct = as_num(body["press_spoilage_pct"], "press_spoilage_pct", min_v=0)
    if "bindery_spoilage_pct" in body and body["bindery_spoilage_pct"] is not None:
        bindery_spoilage_pct = as_num(body["bindery_spoilage_pct"], "bindery_spoilage_pct", min_v=0)
    if "due_date" in body and body["due_date"] is not None:
        try:
            due_dt = parse_dt(body["due_date"])
            due_date_str = fmt_ts(due_dt)
        except Exception:
            raise err_validation("due_date must be ISO8601")
    if "quote_valid_days" in body and body["quote_valid_days"] is not None:
        quote_valid_days = as_int(body["quote_valid_days"], "quote_valid_days", min_v=0)
    if "press_type" in body and body["press_type"] is not None:
        press_type = as_enum(body["press_type"], "press_type", {"WEB", "SHEETFED"})
    if "binding_method" in body and body["binding_method"] is not None:
        binding_method = as_enum(body["binding_method"], "binding_method",
                                  {"SADDLE_STITCH", "PERFECT_BIND", "CASE_BIND", "PLASTIC_COIL"})
    if "fulfillment_type" in body and body["fulfillment_type"] is not None:
        fulfillment_type = as_enum(body["fulfillment_type"], "fulfillment_type", {"SHIP", "MAIL"})
    if "included_proof_rounds" in body and body["included_proof_rounds"] is not None:
        included_proof_rounds = as_int(body["included_proof_rounds"], "included_proof_rounds", min_v=0)

    # FK resolution for new signatures
    for sig in signatures:
        if sig["paper_stock_id"] not in DB["paper_stocks"]:
            raise err_not_found(f"paper_stock {sig['paper_stock_id']} not found")

    pricing = compute_pricing(quantity_ordered, signatures, finishing_options,
                              press_spoilage_pct, bindery_spoilage_pct)
    est["quantity_ordered"] = quantity_ordered
    est["signatures"] = signatures
    est["finishing_options"] = finishing_options
    est["press_spoilage_pct"] = press_spoilage_pct
    est["bindery_spoilage_pct"] = bindery_spoilage_pct
    est["due_date"] = due_date_str
    est["quote_valid_days"] = quote_valid_days
    est["press_type"] = press_type
    est["binding_method"] = binding_method
    est["fulfillment_type"] = fulfillment_type
    est["included_proof_rounds"] = included_proof_rounds
    est["impressions_per_signature"] = pricing["impressions_per_signature"]
    est["total_impressions"] = pricing["total_impressions"]
    est["make_ready_total_cents"] = pricing["make_ready_total_cents"]
    est["running_cost_cents"] = pricing["running_cost_cents"]
    est["paper_sheets_total"] = pricing["paper_sheets_total"]
    est["paper_cost_cents"] = pricing["paper_cost_cents"]
    est["finishing_cost_cents"] = pricing["finishing_cost_cents"]
    est["subtotal_cents"] = pricing["subtotal_cents"]
    est["discount_pct"] = pricing["discount_pct"]
    est["total_price_cents"] = pricing["total_price_cents"]
    touch(est)
    return success_object(ser_estimate(est))


@app.route("/estimates/<eid>/quote", methods=["POST"])
def quote_estimate(eid):
    user_id, role = require_role(["Estimator"])
    est = get_or_404("estimates", eid, "estimate")
    if est["status"] != "DRAFT":
        raise err_invalid_state("Estimate must be DRAFT to quote")
    est["status"] = "QUOTED"
    qdt = now_dt()
    est["quoted_at"] = fmt_ts(qdt)
    est["expires_at"] = fmt_ts(qdt + timedelta(days=est["quote_valid_days"]))
    touch(est)
    return success_object(ser_estimate(est))


@app.route("/estimates/<eid>/accept", methods=["POST"])
def accept_estimate(eid):
    user_id, role = require_role(["Customer"])
    est = get_or_404("estimates", eid, "estimate")
    # ownership
    check_customer_ownership(user_id, role, est["customer_id"])
    # existence of customer (FK)
    customer = DB["customers"].get(est["customer_id"])
    if customer is None:
        raise err_not_found("customer not found")
    # state
    if est["status"] != "QUOTED":
        raise err_invalid_state("Estimate must be QUOTED to accept")
    # temporal (before fiscal)
    exp = parse_dt(est["expires_at"]) if est["expires_at"] else None
    if exp is not None and now_dt() > exp:
        est["status"] = "EXPIRED"
        touch(est)
        raise ApiError("ERR_ESTIMATE_EXPIRED", "Estimate has expired", 409)
    # fiscal
    posture = compute_customer_posture(customer["id"])
    if posture != "ACTIVE":
        raise ApiError("ERR_CREDIT_HOLD", "Customer is on credit hold", 409)

    # Create Job snapshot
    ts = new_ts()
    job = {
        "id": new_id(),
        "estimate_id": est["id"],
        "parent_job_id": None,
        "customer_id": est["customer_id"],
        "zero_charge": False,
        "quantity_ordered": est["quantity_ordered"],
        "due_date": est["due_date"],
        "press_type": est["press_type"],
        "fulfillment_type": est["fulfillment_type"],
        "binding_method": est["binding_method"],
        "signatures": [dict(s) for s in est["signatures"]],
        "press_spoilage_pct": est["press_spoilage_pct"],
        "bindery_spoilage_pct": est["bindery_spoilage_pct"],
        "included_proof_rounds": est["included_proof_rounds"],
        "tolerance_pct": customer["default_tolerance_pct"],
        "total_impressions": est["total_impressions"],
        "make_ready_total_cents": est["make_ready_total_cents"],
        "total_price_cents": est["total_price_cents"],
        "discount_pct": est["discount_pct"],
        "subtotal_cents": est["subtotal_cents"],
        "production_status": "PREPRESS",
        "billing_status": "UNBILLED",
        "gang_run_id": None,
        "allocated_make_ready_cents": None,
        "delivered_quantity": None,
        "proof_rounds_used": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["jobs"][job["id"]] = job
    est["status"] = "ACCEPTED"
    touch(est)
    recompute_customer(customer["id"])
    return success_object(ser_job(job))


@app.route("/estimates/<eid>/decline", methods=["POST"])
def decline_estimate(eid):
    user_id, role = require_role(["Customer"])
    est = get_or_404("estimates", eid, "estimate")
    check_customer_ownership(user_id, role, est["customer_id"])
    if est["status"] != "QUOTED":
        raise err_invalid_state("Estimate must be QUOTED to decline")
    est["status"] = "DECLINED"
    touch(est)
    return success_object(ser_estimate(est))


# ===========================================================================
# JOBS
# ===========================================================================
@app.route("/jobs/<jid>", methods=["GET"])
def get_job(jid):
    user_id, role = require_role(["Estimator", "Customer", "PrepressOperator", "PressScheduler",
                                   "PurchasingManager", "MailSpecialist", "PlantManager"])
    job = get_or_404("jobs", jid, "job")
    check_customer_ownership(user_id, role, job["customer_id"])
    return success_object(ser_job(job))


@app.route("/jobs", methods=["GET"])
def list_jobs():
    user_id, role = require_role(["Estimator", "Customer", "PrepressOperator", "PressScheduler",
                                   "PurchasingManager", "MailSpecialist", "PlantManager"])
    limit, offset = parse_limit_offset()
    items = list(DB["jobs"].values())
    if role == "Customer":
        items = [j for j in items if j["customer_id"] == user_id]
    for f in ("customer_id", "estimate_id", "gang_run_id", "parent_job_id",
              "production_status", "billing_status"):
        v = request.args.get(f)
        if v is not None:
            items = [j for j in items if j.get(f) == v]
    items.sort(key=lambda j: j["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_job(j) for j in page], limit, offset, total)


@app.route("/jobs/<jid>/record-delivery", methods=["POST"])
def record_delivery(jid):
    user_id, role = require_role(["PlantManager"])
    job = get_or_404("jobs", jid, "job")
    body = request.get_json(silent=True) or {}
    delivered_quantity = as_int(req_field(body, "delivered_quantity"), "delivered_quantity", min_v=1)
    if job["fulfillment_type"] != "SHIP":
        raise ApiError("ERR_FULFILLMENT_CHANNEL_MISMATCH", "record-delivery requires SHIP job", 409)
    if job["production_status"] != "READY_TO_SHIP":
        raise ApiError("ERR_JOB_INVALID_STATE", "Job must be READY_TO_SHIP", 409)
    job["delivered_quantity"] = delivered_quantity
    job["production_status"] = "FULFILLED"
    touch(job)
    return success_object(ser_job(job))


@app.route("/jobs/<jid>/cancel", methods=["POST"])
def cancel_job(jid):
    user_id, role = require_role(["PlantManager"])
    job = get_or_404("jobs", jid, "job")
    _ = opt_field(request.get_json(silent=True) or {}, "reason", None)
    current = job["production_status"]
    if current in ("BINDERY", "READY_TO_SHIP", "FULFILLED", "CLOSED"):
        raise ApiError("ERR_JOB_PAST_CANCEL_POINT", "Cannot cancel from BINDERY or later", 409)
    if current in ("CANCELLED",):
        raise err_invalid_state("Job already cancelled")
    if current not in ("PREPRESS", "PROOF_REVIEW", "PLATED", "PRESS_SCHEDULED"):
        raise err_invalid_state("Job cannot be cancelled from current state")
    # Locked/consumed gang membership blocks cancel
    if job["gang_run_id"]:
        gang = DB["gang_runs"].get(job["gang_run_id"])
        if gang and gang["status"] in ("LOCKED", "CONSUMED"):
            raise ApiError("ERR_JOB_IN_LOCKED_GANG", "Job is member of a locked/consumed gang", 409)

    # Compensation cascade
    if current in ("PREPRESS",):
        job["production_status"] = "CANCELLED"
        job["billing_status"] = "NOT_BILLABLE"
    elif current == "PROOF_REVIEW":
        job["production_status"] = "CANCELLED"
        job["billing_status"] = "NOT_BILLABLE"
        # Supersede non-terminal proofs
        for p in DB["proofs"].values():
            if p["job_id"] == job["id"] and p["status"] in ("AWAITING_CUSTOMER", "CHANGES_REQUESTED"):
                p["status"] = "SUPERSEDED"
                touch(p)
    elif current == "PLATED":
        # Remove from FORMING gang if member
        if job["gang_run_id"]:
            gang = DB["gang_runs"].get(job["gang_run_id"])
            if gang and gang["status"] == "FORMING":
                gang["members"] = [m for m in gang["members"] if m["job_id"] != job["id"]]
                touch(gang)
            job["gang_run_id"] = None
        job["production_status"] = "CANCELLED"
        job["billing_status"] = "INVOICED"
        # Auto-create CANCELLATION_FEE invoice in ISSUED
        ts = new_ts()
        fee = job["make_ready_total_cents"]
        inv = {
            "id": new_id(),
            "job_id": job["id"],
            "customer_id": job["customer_id"],
            "kind": "CANCELLATION_FEE",
            "quantity_ordered": job["quantity_ordered"],
            "delivered_quantity": job["delivered_quantity"] if job["delivered_quantity"] is not None else 0,
            "billable_quantity": 0,
            "base_amount_cents": 0,
            "postage_cents": 0,
            "proof_overage_cents": 0,
            "shortage_credit_cents": 0,
            "gang_make_ready_allocated_cents": None,
            "total_due_cents": fee,
            "amount_paid_cents": 0,
            "credit_applied_cents": 0,
            "status": "ISSUED",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        DB["invoices"][inv["id"]] = inv
    elif current == "PRESS_SCHEDULED":
        # Cancel all SCHEDULED press runs of this job and release reservations
        for r in list(DB["press_runs"].values()):
            if r["job_id"] == job["id"] and r["status"] == "SCHEDULED":
                for stock_id, reservations in r.get("_reservations", {}).items():
                    release_reservations(reservations)
                r["status"] = "CANCELLED"
                touch(r)
        # Remove from FORMING gang if member
        if job["gang_run_id"]:
            gang = DB["gang_runs"].get(job["gang_run_id"])
            if gang and gang["status"] == "FORMING":
                gang["members"] = [m for m in gang["members"] if m["job_id"] != job["id"]]
                touch(gang)
            job["gang_run_id"] = None
        job["production_status"] = "CANCELLED"
        job["billing_status"] = "INVOICED"
        ts = new_ts()
        fee = job["make_ready_total_cents"]
        inv = {
            "id": new_id(),
            "job_id": job["id"],
            "customer_id": job["customer_id"],
            "kind": "CANCELLATION_FEE",
            "quantity_ordered": job["quantity_ordered"],
            "delivered_quantity": job["delivered_quantity"] if job["delivered_quantity"] is not None else 0,
            "billable_quantity": 0,
            "base_amount_cents": 0,
            "postage_cents": 0,
            "proof_overage_cents": 0,
            "shortage_credit_cents": 0,
            "gang_make_ready_allocated_cents": None,
            "total_due_cents": fee,
            "amount_paid_cents": 0,
            "credit_applied_cents": 0,
            "status": "ISSUED",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        DB["invoices"][inv["id"]] = inv

    touch(job)
    recompute_customer(job["customer_id"])
    return success_object(ser_job(job))


# ===========================================================================
# PROOFS
# ===========================================================================
@app.route("/proofs", methods=["POST"])
def create_proof():
    user_id, role = require_role(["PrepressOperator"])
    body = request.get_json(silent=True) or {}
    job_id = as_str(req_field(body, "job_id"), "job_id")
    file_uri = as_str(req_field(body, "file_uri"), "file_uri")
    job = DB["jobs"].get(job_id)
    if job is None:
        raise err_not_found("job not found")
    if job["production_status"] not in ("PREPRESS", "PROOF_REVIEW"):
        raise ApiError("ERR_JOB_INVALID_STATE", "Job must be in PREPRESS or PROOF_REVIEW", 409)
    # Supersede prior open proofs
    for p in DB["proofs"].values():
        if p["job_id"] == job_id and p["status"] in ("AWAITING_CUSTOMER", "CHANGES_REQUESTED"):
            p["status"] = "SUPERSEDED"
            touch(p)
    # Compute round_number
    existing = [p["round_number"] for p in DB["proofs"].values() if p["job_id"] == job_id]
    round_number = (max(existing) + 1) if existing else 1
    ts = new_ts()
    proof = {
        "id": new_id(),
        "job_id": job_id,
        "file_uri": file_uri,
        "round_number": round_number,
        "status": "AWAITING_CUSTOMER",
        "decided_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["proofs"][proof["id"]] = proof
    job["proof_rounds_used"] += 1
    if job["production_status"] == "PREPRESS":
        job["production_status"] = "PROOF_REVIEW"
    touch(job)
    return success_object(ser_proof(proof), 201)


@app.route("/proofs/<pid>", methods=["GET"])
def get_proof(pid):
    user_id, role = require_role(["Estimator", "Customer", "PrepressOperator", "PlantManager"])
    p = get_or_404("proofs", pid, "proof")
    job = DB["jobs"].get(p["job_id"])
    if job and role == "Customer":
        check_customer_ownership(user_id, role, job["customer_id"])
    return success_object(ser_proof(p))


@app.route("/proofs", methods=["GET"])
def list_proofs():
    user_id, role = require_role(["Estimator", "Customer", "PrepressOperator", "PlantManager"])
    limit, offset = parse_limit_offset()
    job_id = request.args.get("job_id")
    status = request.args.get("status")
    items = list(DB["proofs"].values())
    if role == "Customer":
        # only own proofs
        own_job_ids = {j["id"] for j in DB["jobs"].values() if j["customer_id"] == user_id}
        items = [p for p in items if p["job_id"] in own_job_ids]
    if job_id:
        items = [p for p in items if p["job_id"] == job_id]
    if status:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_proof(p) for p in page], limit, offset, total)


@app.route("/proofs/<pid>/approve", methods=["POST"])
def approve_proof(pid):
    user_id, role = require_role(["Customer"])
    p = get_or_404("proofs", pid, "proof")
    job = DB["jobs"].get(p["job_id"])
    if job is None:
        raise err_not_found("job not found")
    check_customer_ownership(user_id, role, job["customer_id"])
    # PRD §2.7: state-machine validity of the target entity (the proof must be
    # AWAITING_CUSTOMER -> ERR_PROOF_NOT_AWAITING) precedes the cross-entity
    # job-state gate (job must be PROOF_REVIEW -> ERR_JOB_INVALID_STATE).
    if p["status"] != "AWAITING_CUSTOMER":
        raise ApiError("ERR_PROOF_NOT_AWAITING", "Proof not awaiting customer", 409)
    if job["production_status"] != "PROOF_REVIEW":
        raise ApiError("ERR_JOB_INVALID_STATE", "Job must be PROOF_REVIEW", 409)
    p["status"] = "APPROVED"
    p["decided_at"] = new_ts()
    touch(p)
    job["production_status"] = "PLATED"
    touch(job)
    return success_object(ser_proof(p))


@app.route("/proofs/<pid>/request-changes", methods=["POST"])
def request_changes_proof(pid):
    user_id, role = require_role(["Customer"])
    p = get_or_404("proofs", pid, "proof")
    job = DB["jobs"].get(p["job_id"])
    if job is None:
        raise err_not_found("job not found")
    check_customer_ownership(user_id, role, job["customer_id"])
    # PRD §2.7: target-entity state (proof) before the cross-entity job gate.
    if p["status"] != "AWAITING_CUSTOMER":
        raise ApiError("ERR_PROOF_NOT_AWAITING", "Proof not awaiting customer", 409)
    if job["production_status"] != "PROOF_REVIEW":
        raise ApiError("ERR_JOB_INVALID_STATE", "Job must be PROOF_REVIEW", 409)
    p["status"] = "CHANGES_REQUESTED"
    p["decided_at"] = new_ts()
    touch(p)
    return success_object(ser_proof(p))


# ===========================================================================
# PAPER STOCKS
# ===========================================================================
@app.route("/paper-stocks", methods=["POST"])
def create_paper_stock():
    user_id, role = require_role(["PurchasingManager"])
    body = request.get_json(silent=True) or {}
    name = as_str(req_field(body, "name"), "name")
    grade = as_enum(req_field(body, "grade"), "grade", {"COATED", "UNCOATED", "NEWSPRINT"})
    cost = as_int(req_field(body, "cost_per_sheet_cents"), "cost_per_sheet_cents", min_v=0)
    threshold = as_int(req_field(body, "reorder_threshold_sheets"), "reorder_threshold_sheets", min_v=0)
    qty = as_int(req_field(body, "reorder_quantity_sheets"), "reorder_quantity_sheets", min_v=1)
    ts = new_ts()
    s = {
        "id": new_id(),
        "name": name,
        "grade": grade,
        "cost_per_sheet_cents": cost,
        "reorder_threshold_sheets": threshold,
        "reorder_quantity_sheets": qty,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["paper_stocks"][s["id"]] = s
    return success_object(ser_paper_stock(s), 201)


@app.route("/paper-stocks/<sid>", methods=["GET"])
def get_paper_stock(sid):
    user_id, role = require_role(["Estimator", "PressScheduler", "PurchasingManager", "PlantManager"])
    s = get_or_404("paper_stocks", sid, "paper_stock")
    return success_object(ser_paper_stock(s))


@app.route("/paper-stocks", methods=["GET"])
def list_paper_stocks():
    user_id, role = require_role(["Estimator", "PressScheduler", "PurchasingManager", "PlantManager"])
    limit, offset = parse_limit_offset()
    items = list(DB["paper_stocks"].values())
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_paper_stock(s) for s in page], limit, offset, total)


# ===========================================================================
# PAPER PURCHASE ORDERS
# ===========================================================================
@app.route("/paper-purchase-orders", methods=["POST"])
def create_po():
    user_id, role = require_role(["PurchasingManager"])
    body = request.get_json(silent=True) or {}
    paper_stock_id = as_str(req_field(body, "paper_stock_id"), "paper_stock_id")
    ordered_sheets = as_int(req_field(body, "ordered_sheets"), "ordered_sheets", min_v=1)
    cost = as_int(req_field(body, "cost_per_sheet_cents"), "cost_per_sheet_cents", min_v=0)
    if paper_stock_id not in DB["paper_stocks"]:
        raise err_not_found("paper_stock not found")
    ts = new_ts()
    po = {
        "id": new_id(),
        "paper_stock_id": paper_stock_id,
        "ordered_sheets": ordered_sheets,
        "cost_per_sheet_cents": cost,
        "source": "MANUAL",
        "received_sheets_total": 0,
        "status": "ORDERED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["paper_purchase_orders"][po["id"]] = po
    return success_object(ser_po(po), 201)


@app.route("/paper-purchase-orders/<pid>", methods=["GET"])
def get_po(pid):
    user_id, role = require_role(["PurchasingManager", "PlantManager"])
    po = get_or_404("paper_purchase_orders", pid, "paper_purchase_order")
    return success_object(ser_po(po))


@app.route("/paper-purchase-orders", methods=["GET"])
def list_pos():
    user_id, role = require_role(["PurchasingManager", "PlantManager"])
    limit, offset = parse_limit_offset()
    items = list(DB["paper_purchase_orders"].values())
    for f in ("paper_stock_id", "status", "source"):
        v = request.args.get(f)
        if v is not None:
            items = [p for p in items if p.get(f) == v]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_po(p) for p in page], limit, offset, total)


@app.route("/paper-purchase-orders/<pid>/receive", methods=["POST"])
def receive_po(pid):
    user_id, role = require_role(["PurchasingManager"])
    po = get_or_404("paper_purchase_orders", pid, "paper_purchase_order")
    body = request.get_json(silent=True) or {}
    sheets_received = as_int(req_field(body, "sheets_received"), "sheets_received", min_v=1)
    sheets_damaged = as_int(opt_field(body, "sheets_damaged", 0), "sheets_damaged", min_v=0)
    if po["status"] in ("RECEIVED", "CANCELLED"):
        raise ApiError("ERR_PO_STATE", "PO is RECEIVED or CANCELLED", 409)
    cap = math.floor(po["ordered_sheets"] * 1.10)
    if po["received_sheets_total"] + sheets_received > cap:
        raise ApiError("ERR_OVER_RECEIPT", "Cumulative receipts exceed cap", 422)

    # Find or create lot for this PO
    lot = None
    for l in DB["paper_lots"].values():
        if l["paper_purchase_order_id"] == po["id"]:
            lot = l
            break
    ts = new_ts()
    if lot is None:
        lot = {
            "id": new_id(),
            "paper_stock_id": po["paper_stock_id"],
            "paper_purchase_order_id": po["id"],
            "received_sheets": 0,
            "damaged_sheets": 0,
            "reserved_sheets": 0,
            "consumed_sheets": 0,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        DB["paper_lots"][lot["id"]] = lot
    lot["received_sheets"] += sheets_received
    lot["damaged_sheets"] += sheets_damaged
    touch(lot)
    po["received_sheets_total"] += sheets_received
    if po["received_sheets_total"] >= po["ordered_sheets"]:
        po["status"] = "RECEIVED"
    else:
        po["status"] = "PARTIALLY_RECEIVED"
    touch(po)
    return success_object(ser_po(po))


@app.route("/paper-purchase-orders/<pid>/cancel", methods=["POST"])
def cancel_po(pid):
    user_id, role = require_role(["PurchasingManager"])
    po = get_or_404("paper_purchase_orders", pid, "paper_purchase_order")
    if po["status"] in ("RECEIVED", "CANCELLED"):
        raise ApiError("ERR_PO_STATE", "PO is RECEIVED or CANCELLED", 409)
    po["status"] = "CANCELLED"
    touch(po)
    return success_object(ser_po(po))


# ===========================================================================
# PAPER LOTS
# ===========================================================================
@app.route("/paper-lots/<lid>", methods=["GET"])
def get_lot(lid):
    user_id, role = require_role(["PurchasingManager", "PressScheduler", "PlantManager"])
    l = get_or_404("paper_lots", lid, "paper_lot")
    return success_object(ser_lot(l))


@app.route("/paper-lots", methods=["GET"])
def list_lots():
    user_id, role = require_role(["PurchasingManager", "PressScheduler", "PlantManager"])
    limit, offset = parse_limit_offset()
    items = list(DB["paper_lots"].values())
    for f in ("paper_stock_id", "paper_purchase_order_id"):
        v = request.args.get(f)
        if v is not None:
            items = [l for l in items if l.get(f) == v]
    items.sort(key=lambda l: l["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_lot(l) for l in page], limit, offset, total)


# ===========================================================================
# PRESSES
# ===========================================================================
@app.route("/presses", methods=["POST"])
def create_press():
    user_id, role = require_role(["PlantManager"])
    body = request.get_json(silent=True) or {}
    name = as_str(req_field(body, "name"), "name")
    press_type = as_enum(req_field(body, "press_type"), "press_type", {"WEB", "SHEETFED"})
    rated = as_int(req_field(body, "rated_impressions_per_hour"), "rated_impressions_per_hour", min_v=1)
    mr_base = as_int(req_field(body, "make_ready_minutes_base"), "make_ready_minutes_base", min_v=0)
    washup = as_int(req_field(body, "washup_buffer_minutes"), "washup_buffer_minutes", min_v=0)
    status = opt_field(body, "status", "AVAILABLE")
    status = as_enum(status, "status", {"AVAILABLE", "DOWN"})
    ts = new_ts()
    p = {
        "id": new_id(),
        "name": name,
        "press_type": press_type,
        "rated_impressions_per_hour": rated,
        "make_ready_minutes_base": mr_base,
        "washup_buffer_minutes": washup,
        "status": status,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["presses"][p["id"]] = p
    return success_object(ser_press(p), 201)


@app.route("/presses/<pid>", methods=["GET"])
def get_press(pid):
    user_id, role = require_role(["PressScheduler", "PlantManager"])
    p = get_or_404("presses", pid, "press")
    return success_object(ser_press(p))


@app.route("/presses", methods=["GET"])
def list_presses():
    user_id, role = require_role(["PressScheduler", "PlantManager"])
    limit, offset = parse_limit_offset()
    press_type = request.args.get("press_type")
    items = list(DB["presses"].values())
    if press_type:
        items = [p for p in items if p["press_type"] == press_type]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_press(p) for p in page], limit, offset, total)


# ===========================================================================
# PRESS RUNS
# ===========================================================================
def check_press_window_conflict(press, candidate_start, candidate_end, exclude_run_id=None):
    washup = timedelta(minutes=press["washup_buffer_minutes"])
    for r in DB["press_runs"].values():
        if r["press_id"] != press["id"]:
            continue
        if r["status"] != "SCHEDULED":
            continue
        if exclude_run_id and r["id"] == exclude_run_id:
            continue
        x_start = parse_dt(r["scheduled_start"])
        x_end = parse_dt(r["scheduled_end"])
        x_buffered_end = x_end + washup
        if candidate_start < x_buffered_end and candidate_end > x_start:
            raise ApiError("ERR_PRESS_WINDOW_CONFLICT", "Press window conflict", 409)


@app.route("/press-runs", methods=["POST"])
def create_press_run():
    user_id, role = require_role(["PressScheduler"])
    body = request.get_json(silent=True) or {}
    press_id = as_str(req_field(body, "press_id"), "press_id")
    run_quantity = as_int(req_field(body, "run_quantity"), "run_quantity", min_v=1)
    scheduled_start_raw = as_str(req_field(body, "scheduled_start"), "scheduled_start")
    expected_press_version = req_field(body, "expected_press_version")
    if not is_int(expected_press_version):
        raise err_validation("expected_press_version must be an integer")
    job_id = body.get("job_id")
    gang_run_id = body.get("gang_run_id")
    try:
        scheduled_start = parse_dt(scheduled_start_raw)
    except Exception:
        raise err_validation("scheduled_start must be ISO8601")

    # existence
    press = DB["presses"].get(press_id)
    if press is None:
        raise err_not_found("press not found")
    job = None
    gang = None
    if job_id and gang_run_id:
        raise err_validation("exactly one of job_id or gang_run_id must be provided")
    if not job_id and not gang_run_id:
        raise err_validation("exactly one of job_id or gang_run_id must be provided")
    if job_id:
        job = DB["jobs"].get(job_id)
        if job is None:
            raise err_not_found("job not found")
    if gang_run_id:
        gang = DB["gang_runs"].get(gang_run_id)
        if gang is None:
            raise err_not_found("gang_run not found")

    # OCC
    if expected_press_version != press["version"]:
        raise err_stale("Press version mismatch")

    # state checks
    if press["status"] != "AVAILABLE":
        raise ApiError("ERR_PRESS_UNAVAILABLE", "Press is DOWN", 409)

    if job:
        if job["production_status"] != "PLATED":
            raise ApiError("ERR_JOB_INVALID_STATE", "Job must be PLATED", 409)
        if run_quantity > job["quantity_ordered"]:
            raise err_validation("run_quantity exceeds job quantity_ordered")
        if press["press_type"] != job["press_type"]:
            raise ApiError("ERR_PRESS_TYPE_MISMATCH", "Press type mismatch", 409)
    else:
        if gang["status"] != "LOCKED":
            raise ApiError("ERR_GANG_NOT_LOCKED", "Gang must be LOCKED", 409)
        member_jobs = [DB["jobs"].get(m["job_id"]) for m in gang["members"]]
        if any(mj is None for mj in member_jobs):
            raise err_not_found("member job not found")
        member_qty_sum = sum(mj["quantity_ordered"] for mj in member_jobs)
        if run_quantity != member_qty_sum:
            raise ApiError("ERR_GANG_RUN_QUANTITY_MISMATCH",
                           "run_quantity must equal sum of member quantity_ordered", 409)
        if press["press_type"] != gang["press_type"]:
            raise ApiError("ERR_PRESS_TYPE_MISMATCH", "Press type mismatch", 409)

    # Compute planned_impressions and planned_sheets
    if job:
        impressions_per = [math.ceil(run_quantity / s["up_count"]) for s in job["signatures"]]
        planned_impressions = sum(impressions_per)
        sheets_per = compute_per_signature_sheets(impressions_per, job["signatures"],
                                                  job["press_spoilage_pct"], job["bindery_spoilage_pct"])
        planned_sheets = sum(sheets_per)
        sheets_by_stock = {}
        for sheets, sig in zip(sheets_per, job["signatures"]):
            sheets_by_stock[sig["paper_stock_id"]] = sheets_by_stock.get(sig["paper_stock_id"], 0) + sheets
    else:
        planned_impressions = sum(mj["total_impressions"] for mj in member_jobs)
        planned_sheets = 0
        sheets_by_stock = {}
        for mj in member_jobs:
            sheets_per_m = compute_run_planned_sheets_per_signature(
                mj["quantity_ordered"], mj["signatures"],
                mj["press_spoilage_pct"], mj["bindery_spoilage_pct"]
            )
            planned_sheets += sum(sheets_per_m)
            for sheets, sig in zip(sheets_per_m, mj["signatures"]):
                sheets_by_stock[sig["paper_stock_id"]] = sheets_by_stock.get(sig["paper_stock_id"], 0) + sheets

    # Duration
    press_time_minutes = math.ceil(Decimal(planned_impressions) / Decimal(press["rated_impressions_per_hour"]) * Decimal(60))
    duration_minutes = press["make_ready_minutes_base"] + press_time_minutes
    scheduled_end = scheduled_start + timedelta(minutes=duration_minutes)

    # Window conflict
    check_press_window_conflict(press, scheduled_start, scheduled_end)

    # Reserve paper FIFO per stock
    reservations = {}
    try:
        for stock_id, qty in sheets_by_stock.items():
            reservations[stock_id] = reserve_sheets(stock_id, qty)
    except ApiError:
        # Release partial reservations
        for s_id, rs in reservations.items():
            release_reservations(rs)
        raise

    ts = new_ts()
    run = {
        "id": new_id(),
        "press_id": press_id,
        "job_id": job_id,
        "gang_run_id": gang_run_id,
        "run_quantity": run_quantity,
        "scheduled_start": fmt_ts(scheduled_start),
        "planned_impressions": planned_impressions,
        "planned_sheets": planned_sheets,
        "duration_minutes": duration_minutes,
        "scheduled_end": fmt_ts(scheduled_end),
        "status": "SCHEDULED",
        "gross_impressions": None,
        "sheets_used": None,
        "waste_sheets": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_reservations": reservations,  # internal: per-stock list of {lot_id, qty}
    }
    DB["press_runs"][run["id"]] = run
    if job:
        job["production_status"] = "PRESS_SCHEDULED"
        touch(job)
    else:
        for mj in member_jobs:
            mj["production_status"] = "PRESS_SCHEDULED"
            touch(mj)
    touch(press)
    return success_object(ser_press_run(run), 201)


@app.route("/press-runs/<rid>", methods=["GET"])
def get_press_run(rid):
    user_id, role = require_role(["PressScheduler", "PlantManager"])
    r = get_or_404("press_runs", rid, "press_run")
    return success_object(ser_press_run(r))


@app.route("/press-runs", methods=["GET"])
def list_press_runs():
    user_id, role = require_role(["PressScheduler", "PlantManager"])
    limit, offset = parse_limit_offset()
    items = list(DB["press_runs"].values())
    for f in ("press_id", "job_id", "gang_run_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if r.get(f) == v]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_press_run(r) for r in page], limit, offset, total)


@app.route("/press-runs/<rid>/complete", methods=["POST"])
def complete_press_run(rid):
    user_id, role = require_role(["PressScheduler"])
    r = get_or_404("press_runs", rid, "press_run")
    body = request.get_json(silent=True) or {}
    gross_impressions = as_int(req_field(body, "gross_impressions"), "gross_impressions", min_v=0)
    sheets_used = as_int(req_field(body, "sheets_used"), "sheets_used", min_v=0)
    waste_sheets = as_int(req_field(body, "waste_sheets"), "waste_sheets", min_v=0)
    if r["status"] != "SCHEDULED":
        raise err_invalid_state("Run must be SCHEDULED")
    if waste_sheets > sheets_used:
        raise err_validation("waste_sheets must be <= sheets_used")

    # Pre-validate: excess coverage per stock
    reservations = r.get("_reservations", {})
    # Compute per-stock reserved total
    reserved_by_stock = {sid: sum(x["qty"] for x in rs) for sid, rs in reservations.items()}
    # sheets_used is aggregate; assume allocation across stocks in proportion to reserved
    # For simplicity: consume stocks in order of reservation listing, allocating sheets_used proportionally
    # Spec: "If sheets_used > reserved: unreserved remainder must be coverable from available lots FIFO"
    total_reserved = sum(reserved_by_stock.values())
    if sheets_used > total_reserved:
        excess = sheets_used - total_reserved
        # Aggregate across all stocks reserved
        # First stock listed takes excess (most runs use 1 stock); for multi-stock, draw from first stock FIFO
        # A more accurate model: consume reserved per stock, then draw excess from first stock with remaining
        # Check if aggregate can cover excess
        # Find any stock with remaining capacity
        ok = False
        for sid in reserved_by_stock.keys():
            avail = 0
            for l in fifo_lots_for_stock(sid):
                avail += l["received_sheets"] - l["reserved_sheets"] - l["consumed_sheets"] - l["damaged_sheets"]
            if avail >= excess:
                ok = True
                break
        if not ok:
            raise ApiError("ERR_PAPER_INSUFFICIENT", "Insufficient paper for excess consumption", 409)

    # Consume: per stock, convert reserved->consumed; excess handled on first stock with capacity
    remaining_excess = max(0, sheets_used - total_reserved)
    consumed_stocks = set()
    for sid, rs in reservations.items():
        # Consume this stock's reservations fully (or release unused portion)
        stock_reserved_total = reserved_by_stock[sid]
        # Assume the run used at least its reservation in each stock (typical case)
        # Allocate: use min(sheets_used, stock_reserved_total) for this stock
        # For simplicity in multi-stock: consume reservation in each stock fully; excess goes to first stock
        for rsv in rs:
            lot = DB["paper_lots"].get(rsv["lot_id"])
            if not lot:
                continue
            lot["reserved_sheets"] -= rsv["qty"]
            lot["consumed_sheets"] += rsv["qty"]
            touch(lot)
        consumed_stocks.add(sid)

    if remaining_excess > 0:
        # Draw excess FIFO from any of the reserved stocks (first with capacity)
        for sid in reserved_by_stock.keys():
            if remaining_excess <= 0:
                break
            lots = fifo_lots_for_stock(sid)
            for lot in lots:
                if remaining_excess <= 0:
                    break
                lot_remaining = (lot["received_sheets"] - lot["reserved_sheets"]
                                 - lot["consumed_sheets"] - lot["damaged_sheets"])
                take = min(lot_remaining, remaining_excess)
                if take > 0:
                    lot["consumed_sheets"] += take
                    touch(lot)
                    remaining_excess -= take
                    consumed_stocks.add(sid)

    r["gross_impressions"] = gross_impressions
    r["sheets_used"] = sheets_used
    r["waste_sheets"] = waste_sheets
    r["status"] = "COMPLETE"
    touch(r)

    # Advance jobs
    if r["job_id"]:
        job = DB["jobs"].get(r["job_id"])
        if job:
            other_scheduled = any(
                other["id"] != r["id"] and other["job_id"] == job["id"] and other["status"] == "SCHEDULED"
                for other in DB["press_runs"].values()
            )
            if not other_scheduled and job["production_status"] == "PRESS_SCHEDULED":
                job["production_status"] = "BINDERY"
                touch(job)
    elif r["gang_run_id"]:
        gang = DB["gang_runs"].get(r["gang_run_id"])
        if gang and gang["status"] == "LOCKED":
            gang["status"] = "CONSUMED"
            touch(gang)
            for m in gang["members"]:
                mj = DB["jobs"].get(m["job_id"])
                if mj and mj["production_status"] == "PRESS_SCHEDULED":
                    mj["production_status"] = "BINDERY"
                    touch(mj)

    # Auto-replenishment per consumed stock
    for sid in consumed_stocks:
        maybe_auto_replenish(sid)

    return success_object(ser_press_run(r))


@app.route("/press-runs/<rid>/cancel", methods=["POST"])
def cancel_press_run(rid):
    user_id, role = require_role(["PressScheduler"])
    r = get_or_404("press_runs", rid, "press_run")
    if r["status"] != "SCHEDULED":
        raise err_invalid_state("Run must be SCHEDULED to cancel")
    reservations = r.get("_reservations", {})
    for sid, rs in reservations.items():
        release_reservations(rs)
    r["status"] = "CANCELLED"
    touch(r)
    return success_object(ser_press_run(r))


# ===========================================================================
# GANG RUNS
# ===========================================================================
@app.route("/gang-runs", methods=["POST"])
def create_gang_run():
    user_id, role = require_role(["PressScheduler"])
    body = request.get_json(silent=True) or {}
    paper_stock_id = as_str(req_field(body, "paper_stock_id"), "paper_stock_id")
    press_type = as_enum(req_field(body, "press_type"), "press_type", {"WEB", "SHEETFED"})
    anchor_due_date_raw = as_str(req_field(body, "anchor_due_date"), "anchor_due_date")
    try:
        anchor_dt = parse_dt(anchor_due_date_raw)
    except Exception:
        raise err_validation("anchor_due_date must be ISO8601")
    if paper_stock_id not in DB["paper_stocks"]:
        raise err_not_found("paper_stock not found")
    ts = new_ts()
    g = {
        "id": new_id(),
        "paper_stock_id": paper_stock_id,
        "press_type": press_type,
        "anchor_due_date": fmt_ts(anchor_dt),
        "status": "FORMING",
        "members": [],
        "make_ready_total_cents": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["gang_runs"][g["id"]] = g
    return success_object(ser_gang(g), 201)


@app.route("/gang-runs/<gid>", methods=["GET"])
def get_gang_run(gid):
    user_id, role = require_role(["PressScheduler", "PlantManager", "Estimator"])
    g = get_or_404("gang_runs", gid, "gang_run")
    return success_object(ser_gang(g))


@app.route("/gang-runs", methods=["GET"])
def list_gang_runs():
    user_id, role = require_role(["PressScheduler", "PlantManager", "Estimator"])
    limit, offset = parse_limit_offset()
    items = list(DB["gang_runs"].values())
    for f in ("status", "paper_stock_id"):
        v = request.args.get(f)
        if v is not None:
            items = [g for g in items if g.get(f) == v]
    items.sort(key=lambda g: g["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_gang(g) for g in page], limit, offset, total)


@app.route("/gang-runs/<gid>/members", methods=["POST"])
def add_gang_member(gid):
    user_id, role = require_role(["PressScheduler"])
    g = get_or_404("gang_runs", gid, "gang_run")
    body = request.get_json(silent=True) or {}
    job_id = as_str(req_field(body, "job_id"), "job_id")
    expected = req_field(body, "expected_gang_run_version")
    if not is_int(expected):
        raise err_validation("expected_gang_run_version must be an integer")
    job = DB["jobs"].get(job_id)
    if job is None:
        raise err_not_found("job not found")
    if expected != g["version"]:
        raise err_stale("Gang run version mismatch")
    if g["status"] != "FORMING":
        raise ApiError("ERR_GANG_NOT_FORMING", "Gang must be FORMING", 409)
    if len(g["members"]) >= 6:
        raise ApiError("ERR_GANG_FULL", "Gang already has 6 members", 409)
    # eligibility
    for sig in job["signatures"]:
        if sig["paper_stock_id"] != g["paper_stock_id"]:
            raise ApiError("ERR_GANG_INELIGIBLE_JOB", "Job signature uses different stock", 409)
    if job["press_type"] != g["press_type"]:
        raise ApiError("ERR_GANG_INELIGIBLE_JOB", "Press type mismatch", 409)
    if job["gang_run_id"] and job["gang_run_id"] != g["id"]:
        raise ApiError("ERR_GANG_INELIGIBLE_JOB", "Job already in another gang", 409)
    if job["gang_run_id"] == g["id"]:
        raise ApiError("ERR_GANG_INELIGIBLE_JOB", "Job already a member of this gang", 409)
    if job["production_status"] != "PLATED":
        raise ApiError("ERR_GANG_INELIGIBLE_JOB", "Job must be PLATED", 409)
    # due window +/- 3 days inclusive
    anchor = parse_dt(g["anchor_due_date"])
    job_due = parse_dt(job["due_date"])
    delta = abs((job_due - anchor).total_seconds())
    if delta > 3 * 86400:
        raise ApiError("ERR_GANG_DUE_WINDOW_EXCEEDED", "Job due_date outside +/-3 days", 409)

    g["members"].append({
        "job_id": job_id,
        "added_at": new_ts(),
        "allocated_make_ready_cents": None,
    })
    job["gang_run_id"] = g["id"]
    touch(job)
    touch(g)
    return success_object(ser_gang(g))


@app.route("/gang-runs/<gid>/remove-member", methods=["POST"])
def remove_gang_member(gid):
    user_id, role = require_role(["PressScheduler"])
    g = get_or_404("gang_runs", gid, "gang_run")
    body = request.get_json(silent=True) or {}
    job_id = as_str(req_field(body, "job_id"), "job_id")
    expected = req_field(body, "expected_gang_run_version")
    if not is_int(expected):
        raise err_validation("expected_gang_run_version must be an integer")
    job = DB["jobs"].get(job_id)
    if job is None:
        raise err_not_found("job not found")
    if expected != g["version"]:
        raise err_stale("Gang run version mismatch")
    if g["status"] != "FORMING":
        raise ApiError("ERR_GANG_NOT_FORMING", "Gang must be FORMING", 409)
    if not any(m["job_id"] == job_id for m in g["members"]):
        raise err_not_found("job is not a member of this gang")
    g["members"] = [m for m in g["members"] if m["job_id"] != job_id]
    if job["gang_run_id"] == g["id"]:
        job["gang_run_id"] = None
        touch(job)
    touch(g)
    return success_object(ser_gang(g))


@app.route("/gang-runs/<gid>/lock", methods=["POST"])
def lock_gang_run(gid):
    user_id, role = require_role(["PressScheduler"])
    g = get_or_404("gang_runs", gid, "gang_run")
    if g["status"] != "FORMING":
        raise ApiError("ERR_GANG_NOT_FORMING", "Gang must be FORMING to lock", 409)
    if len(g["members"]) < 2:
        raise ApiError("ERR_GANG_TOO_SMALL", "Gang must have at least 2 members", 409)
    if len(g["members"]) > 6:
        raise ApiError("ERR_GANG_FULL", "Gang has more than 6 members", 409)
    member_jobs = []
    for m in g["members"]:
        mj = DB["jobs"].get(m["job_id"])
        if mj is None:
            raise err_not_found("member job not found")
        if mj["production_status"] != "PLATED":
            raise ApiError("ERR_GANG_INELIGIBLE_JOB", "Member job not PLATED", 409)
        member_jobs.append(mj)
    gang_make_ready = max(mj["make_ready_total_cents"] for mj in member_jobs)
    sum_impressions = sum(mj["total_impressions"] for mj in member_jobs)
    shares = []
    for mj in member_jobs:
        raw = Decimal(gang_make_ready) * Decimal(mj["total_impressions"]) / Decimal(sum_impressions)
        shares.append(rhu(raw))
    remainder = gang_make_ready - sum(shares)
    # earliest-created member gets remainder
    earliest_idx = min(range(len(member_jobs)), key=lambda i: member_jobs[i]["created_at"])
    shares[earliest_idx] += remainder

    for i, m in enumerate(g["members"]):
        m["allocated_make_ready_cents"] = shares[i]
        mj = DB["jobs"].get(m["job_id"])
        mj["allocated_make_ready_cents"] = shares[i]
        touch(mj)
    g["make_ready_total_cents"] = gang_make_ready
    g["status"] = "LOCKED"
    touch(g)
    return success_object(ser_gang(g))


@app.route("/gang-runs/<gid>/unlock", methods=["POST"])
def unlock_gang_run(gid):
    user_id, role = require_role(["PressScheduler"])
    g = get_or_404("gang_runs", gid, "gang_run")
    if g["status"] != "LOCKED":
        raise ApiError("ERR_GANG_NOT_LOCKED", "Gang must be LOCKED to unlock", 409)
    # any SCHEDULED press run referencing this gang?
    for r in DB["press_runs"].values():
        if r["gang_run_id"] == g["id"] and r["status"] == "SCHEDULED":
            raise ApiError("ERR_GANG_HAS_SCHEDULED_RUN", "Gang has SCHEDULED press run", 409)
    for m in g["members"]:
        m["allocated_make_ready_cents"] = None
        mj = DB["jobs"].get(m["job_id"])
        if mj:
            mj["allocated_make_ready_cents"] = None
            touch(mj)
    g["make_ready_total_cents"] = None
    g["status"] = "FORMING"
    touch(g)
    return success_object(ser_gang(g))


# ===========================================================================
# BINDERY TICKETS
# ===========================================================================
BINDERY_OPS = {"FOLD", "STITCH", "TRIM", "PERF", "SCORE", "UV_COAT", "LAMINATE",
               "FOIL", "DIE_CUT", "COLLATE", "PAD"}


@app.route("/bindery-tickets", methods=["POST"])
def create_ticket():
    user_id, role = require_role(["PlantManager"])
    body = request.get_json(silent=True) or {}
    job_id = as_str(req_field(body, "job_id"), "job_id")
    operation = as_enum(req_field(body, "operation"), "operation", BINDERY_OPS)
    sequence_no = as_int(req_field(body, "sequence_no"), "sequence_no", min_v=1)
    job = DB["jobs"].get(job_id)
    if job is None:
        raise err_not_found("job not found")
    if job["production_status"] not in ("PREPRESS", "PROOF_REVIEW", "PLATED", "PRESS_SCHEDULED", "BINDERY"):
        raise ApiError("ERR_JOB_INVALID_STATE",
                       "Job must be between PREPRESS and BINDERY to add tickets", 409)
    # unique sequence_no within job
    for t in DB["bindery_tickets"].values():
        if t["job_id"] == job_id and t["sequence_no"] == sequence_no:
            raise err_validation("sequence_no must be unique per job")
    ts = new_ts()
    t = {
        "id": new_id(),
        "job_id": job_id,
        "operation": operation,
        "sequence_no": sequence_no,
        "pieces_completed": None,
        "status": "QUEUED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["bindery_tickets"][t["id"]] = t
    return success_object(ser_ticket(t), 201)


@app.route("/bindery-tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    user_id, role = require_role(["PlantManager", "PressScheduler"])
    t = get_or_404("bindery_tickets", tid, "bindery_ticket")
    return success_object(ser_ticket(t))


@app.route("/bindery-tickets", methods=["GET"])
def list_tickets():
    user_id, role = require_role(["PlantManager", "PressScheduler", "Customer"])
    limit, offset = parse_limit_offset()
    items = list(DB["bindery_tickets"].values())
    if role == "Customer":
        own_job_ids = {j["id"] for j in DB["jobs"].values() if j["customer_id"] == user_id}
        items = [t for t in items if t["job_id"] in own_job_ids]
    for f in ("job_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [t for t in items if t.get(f) == v]
    items.sort(key=lambda t: t["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_ticket(t) for t in page], limit, offset, total)


@app.route("/bindery-tickets/<tid>/complete", methods=["POST"])
def complete_ticket(tid):
    user_id, role = require_role(["PlantManager"])
    t = get_or_404("bindery_tickets", tid, "bindery_ticket")
    body = request.get_json(silent=True) or {}
    pieces_completed = as_int(req_field(body, "pieces_completed"), "pieces_completed", min_v=0)
    job = DB["jobs"].get(t["job_id"])
    if job is None:
        raise err_not_found("job not found")
    if job["production_status"] != "BINDERY":
        raise ApiError("ERR_JOB_INVALID_STATE", "Job must be BINDERY", 409)
    if t["status"] != "QUEUED":
        raise err_invalid_state("Ticket must be QUEUED")
    # Sequence check
    for other in DB["bindery_tickets"].values():
        if (other["job_id"] == t["job_id"]
                and other["sequence_no"] < t["sequence_no"]
                and other["status"] != "COMPLETE"):
            raise ApiError("ERR_BINDERY_SEQUENCE", "Lower sequence_no ticket not COMPLETE", 409)
    t["pieces_completed"] = pieces_completed
    t["status"] = "COMPLETE"
    touch(t)
    # If last non-COMPLETE ticket -> job READY_TO_SHIP
    remaining = [x for x in DB["bindery_tickets"].values()
                 if x["job_id"] == t["job_id"] and x["status"] != "COMPLETE"]
    if not remaining and job["production_status"] == "BINDERY":
        job["production_status"] = "READY_TO_SHIP"
        touch(job)
    return success_object(ser_ticket(t))


# ===========================================================================
# MAIL DROPS
# ===========================================================================
@app.route("/mail-drops", methods=["POST"])
def create_mail_drop():
    user_id, role = require_role(["MailSpecialist"])
    body = request.get_json(silent=True) or {}
    job_id = as_str(req_field(body, "job_id"), "job_id")
    drop_date = as_str(req_field(body, "drop_date"), "drop_date")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", drop_date):
        raise err_validation("drop_date must be YYYY-MM-DD")
    destination_entry = as_enum(req_field(body, "destination_entry"), "destination_entry",
                                  {"NONE", "BMC", "SCF", "DDU"})
    piece_weight_oz = as_num(req_field(body, "piece_weight_oz"), "piece_weight_oz", min_v=0)
    zip_counts = req_field(body, "zip_counts")
    if not isinstance(zip_counts, list) or len(zip_counts) < 1:
        raise err_validation("zip_counts must be a non-empty array")
    for z in zip_counts:
        if not isinstance(z, dict):
            raise err_validation("zip_counts entry must be an object")
        zip5 = as_str(req_field(z, "zip5"), "zip5")
        if not re.match(r"^\d{5}$", zip5):
            raise err_validation("zip5 must be a 5-digit string")
        pieces = as_int(req_field(z, "pieces"), "pieces", min_v=1)
    job = DB["jobs"].get(job_id)
    if job is None:
        raise err_not_found("job not found")
    if job["fulfillment_type"] != "MAIL":
        raise ApiError("ERR_FULFILLMENT_CHANNEL_MISMATCH", "Job must have fulfillment_type MAIL", 409)
    total_pieces = sum(z["pieces"] for z in zip_counts)
    ts = new_ts()
    md = {
        "id": new_id(),
        "job_id": job_id,
        "drop_date": drop_date,
        "destination_entry": destination_entry,
        "piece_weight_oz": piece_weight_oz,
        "zip_counts": zip_counts,
        "total_pieces": total_pieces,
        "tier_breakdown": None,
        "postage_cents": None,
        "status": "PLANNED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["mail_drops"][md["id"]] = md
    return success_object(ser_mail_drop(md), 201)


@app.route("/mail-drops/<mid>", methods=["GET"])
def get_mail_drop(mid):
    user_id, role = require_role(["MailSpecialist", "PlantManager", "Customer"])
    md = get_or_404("mail_drops", mid, "mail_drop")
    if role == "Customer":
        job = DB["jobs"].get(md["job_id"])
        if job:
            check_customer_ownership(user_id, role, job["customer_id"])
    return success_object(ser_mail_drop(md))


@app.route("/mail-drops", methods=["GET"])
def list_mail_drops():
    user_id, role = require_role(["MailSpecialist", "PlantManager", "Customer"])
    limit, offset = parse_limit_offset()
    items = list(DB["mail_drops"].values())
    if role == "Customer":
        own_job_ids = {j["id"] for j in DB["jobs"].values() if j["customer_id"] == user_id}
        items = [m for m in items if m["job_id"] in own_job_ids]
    for f in ("job_id", "status", "drop_date"):
        v = request.args.get(f)
        if v is not None:
            items = [m for m in items if m.get(f) == v]
    items.sort(key=lambda m: m["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_mail_drop(m) for m in page], limit, offset, total)


@app.route("/mail-drops/<mid>/presort", methods=["POST"])
def presort_mail_drop(mid):
    user_id, role = require_role(["MailSpecialist"])
    md = get_or_404("mail_drops", mid, "mail_drop")
    if md["status"] != "PLANNED":
        raise err_invalid_state("MailDrop must be PLANNED to presort")
    # Daily capacity
    committed = 0
    for other in DB["mail_drops"].values():
        if (other["id"] != md["id"] and other["drop_date"] == md["drop_date"]
                and other["status"] in ("PRESORTED", "DROPPED")):
            committed += other["total_pieces"]
    if committed + md["total_pieces"] > 100000:
        raise ApiError("ERR_MAIL_CAPACITY_EXCEEDED", "Daily capacity exceeded", 409)

    # Presort waterfall
    total = md["total_pieces"]
    five_digit = 0
    three_digit = 0
    aadc = 0
    if total < 500:
        aadc = total
    else:
        # 5-digit qualification
        pool_3digit = {}
        for z in md["zip_counts"]:
            if z["pieces"] >= 150:
                five_digit += z["pieces"]
            else:
                prefix3 = z["zip5"][:3]
                pool_3digit[prefix3] = pool_3digit.get(prefix3, 0) + z["pieces"]
        # 3-digit qualification
        for prefix, count in pool_3digit.items():
            if count >= 150:
                three_digit += count
            else:
                aadc += count
    postage = five_digit * 24 + three_digit * 28 + aadc * 31
    md["tier_breakdown"] = {
        "five_digit_pieces": five_digit,
        "three_digit_pieces": three_digit,
        "aadc_pieces": aadc,
    }
    md["postage_cents"] = postage
    md["status"] = "PRESORTED"
    touch(md)
    return success_object(ser_mail_drop(md))


@app.route("/mail-drops/<mid>/drop", methods=["POST"])
def drop_mail_drop(mid):
    user_id, role = require_role(["MailSpecialist"])
    md = get_or_404("mail_drops", mid, "mail_drop")
    if md["status"] != "PRESORTED":
        raise err_invalid_state("MailDrop must be PRESORTED to drop")
    job = DB["jobs"].get(md["job_id"])
    if job is None:
        raise err_not_found("job not found")
    if job["production_status"] != "READY_TO_SHIP" or job["fulfillment_type"] != "MAIL":
        raise ApiError("ERR_JOB_INVALID_STATE",
                       "Job must be READY_TO_SHIP with fulfillment_type MAIL", 409)
    md["status"] = "DROPPED"
    touch(md)
    job["production_status"] = "FULFILLED"
    job["delivered_quantity"] = md["total_pieces"]
    touch(job)
    return success_object(ser_mail_drop(md))


# ===========================================================================
# INVOICES
# ===========================================================================
@app.route("/invoices", methods=["POST"])
def create_invoice():
    user_id, role = require_role(["PlantManager"])
    body = request.get_json(silent=True) or {}
    job_id = as_str(req_field(body, "job_id"), "job_id")
    job = DB["jobs"].get(job_id)
    if job is None:
        raise err_not_found("job not found")
    if job["production_status"] != "FULFILLED":
        raise ApiError("ERR_JOB_INVALID_STATE", "Job must be FULFILLED", 409)
    if job["billing_status"] != "UNBILLED":
        raise ApiError("ERR_INVOICE_STATE", "Job is not UNBILLED", 409)
    # duplicate production invoice
    for inv in DB["invoices"].values():
        if inv["job_id"] == job_id and inv["kind"] == "PRODUCTION":
            raise ApiError("ERR_DUPLICATE_INVOICE", "PRODUCTION invoice already exists for job", 409)

    # postage from DROPPED mail drops
    postage = 0
    for md in DB["mail_drops"].values():
        if md["job_id"] == job_id and md["status"] == "DROPPED":
            postage += md["postage_cents"] or 0

    # proof overage
    proof_overage = max(0, job["proof_rounds_used"] - job["included_proof_rounds"]) * 12500

    # tolerance billing
    Q = job["quantity_ordered"]
    D = job["delivered_quantity"] if job["delivered_quantity"] is not None else 0
    t = job["tolerance_pct"]
    allowed = (Q * t) // 100  # floor
    lower = Q - allowed
    upper = Q + allowed

    job_total_basis, gang_alloc = compute_job_total_basis(job)

    if D > upper:
        billable = upper
        shortage_credit = 0
    elif D < lower:
        billable = D
        missing = Q - allowed - D
        shortage_credit = rhu(Decimal(job_total_basis) * Decimal(missing) / Decimal(Q))
    else:
        billable = D
        shortage_credit = 0

    base_amount = rhu(Decimal(job_total_basis) * Decimal(billable) / Decimal(Q))
    total_due = base_amount + postage + proof_overage - shortage_credit

    ts = new_ts()
    inv = {
        "id": new_id(),
        "job_id": job_id,
        "customer_id": job["customer_id"],
        "kind": "PRODUCTION",
        "quantity_ordered": Q,
        "delivered_quantity": D,
        "billable_quantity": billable,
        "base_amount_cents": base_amount,
        "postage_cents": postage,
        "proof_overage_cents": proof_overage,
        "shortage_credit_cents": shortage_credit,
        "gang_make_ready_allocated_cents": gang_alloc,
        "total_due_cents": total_due,
        "amount_paid_cents": 0,
        "credit_applied_cents": 0,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["invoices"][inv["id"]] = inv
    return success_object(ser_invoice(inv), 201)


@app.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    user_id, role = require_role(["PlantManager", "Customer", "Estimator"])
    inv = get_or_404("invoices", iid, "invoice")
    check_customer_ownership(user_id, role, inv["customer_id"])
    return success_object(ser_invoice(inv))


@app.route("/invoices", methods=["GET"])
def list_invoices():
    user_id, role = require_role(["PlantManager", "Customer", "Estimator"])
    limit, offset = parse_limit_offset()
    items = list(DB["invoices"].values())
    if role == "Customer":
        items = [i for i in items if i["customer_id"] == user_id]
    for f in ("job_id", "customer_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [i for i in items if i.get(f) == v]
    items.sort(key=lambda i: i["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_invoice(i) for i in page], limit, offset, total)


@app.route("/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    user_id, role = require_role(["PlantManager"])
    inv = get_or_404("invoices", iid, "invoice")
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_INVOICE_STATE", "Invoice must be DRAFT to issue", 409)
    inv["status"] = "ISSUED"
    touch(inv)
    job = DB["jobs"].get(inv["job_id"])
    if job and job["billing_status"] == "UNBILLED":
        job["billing_status"] = "INVOICED"
        touch(job)
    if job:
        recompute_customer(job["customer_id"])
    return success_object(ser_invoice(inv))


@app.route("/invoices/<iid>/payments", methods=["POST"])
def record_payment(iid):
    user_id, role = require_role(["PlantManager"])
    inv = get_or_404("invoices", iid, "invoice")
    body = request.get_json(silent=True) or {}
    amount_cents = as_int(req_field(body, "amount_cents"), "amount_cents")
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID", "DISPUTED"):
        raise ApiError("ERR_INVOICE_STATE", "Invoice not payable from current status", 409)
    outstanding = compute_invoice_outstanding(inv)
    if amount_cents < 1 or amount_cents > outstanding:
        raise ApiError("ERR_OVERPAYMENT", "Payment amount out of range", 422)
    inv["amount_paid_cents"] += amount_cents
    new_outstanding = compute_invoice_outstanding(inv)
    if new_outstanding == 0:
        inv["status"] = "PAID"
    else:
        inv["status"] = "PARTIALLY_PAID"
    touch(inv)
    if inv["status"] == "PAID":
        cascade_invoice_paid(inv)
    job = DB["jobs"].get(inv["job_id"])
    if job:
        recompute_customer(job["customer_id"])
    return success_object(ser_invoice(inv), 201)


@app.route("/invoices/<iid>/apply-credit", methods=["POST"])
def apply_credit(iid):
    user_id, role = require_role(["PlantManager"])
    inv = get_or_404("invoices", iid, "invoice")
    body = request.get_json(silent=True) or {}
    amount_cents = as_int(req_field(body, "amount_cents"), "amount_cents")
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID", "DISPUTED"):
        raise ApiError("ERR_INVOICE_STATE", "Invoice not open for credit", 409)
    customer = DB["customers"].get(inv["customer_id"])
    if customer is None:
        raise err_not_found("customer not found")
    outstanding = compute_invoice_outstanding(inv)
    cap = min(customer["reprint_credit_balance_cents"], outstanding)
    if amount_cents < 1 or amount_cents > cap:
        raise ApiError("ERR_CREDIT_APPLICATION_INVALID",
                       "amount exceeds min(customer balance, invoice outstanding)", 422)
    inv["credit_applied_cents"] += amount_cents
    customer["reprint_credit_balance_cents"] -= amount_cents
    touch(customer)
    new_outstanding = compute_invoice_outstanding(inv)
    if new_outstanding == 0:
        inv["status"] = "PAID"
    else:
        inv["status"] = "PARTIALLY_PAID"
    touch(inv)
    if inv["status"] == "PAID":
        cascade_invoice_paid(inv)
    recompute_customer(customer["id"])
    return success_object(ser_invoice(inv))


@app.route("/invoices/<iid>/dispute", methods=["POST"])
def dispute_invoice(iid):
    user_id, role = require_role(["Customer", "PlantManager"])
    inv = get_or_404("invoices", iid, "invoice")
    check_customer_ownership(user_id, role, inv["customer_id"])
    _ = req_field(request.get_json(silent=True) or {}, "reason")
    if inv["status"] != "ISSUED":
        raise ApiError("ERR_INVOICE_STATE", "Invoice must be ISSUED to dispute", 409)
    inv["status"] = "DISPUTED"
    touch(inv)
    job = DB["jobs"].get(inv["job_id"])
    if job:
        recompute_customer(job["customer_id"])
    return success_object(ser_invoice(inv))


# ===========================================================================
# REPRINT CLAIMS
# ===========================================================================
@app.route("/reprint-claims", methods=["POST"])
def create_claim():
    user_id, role = require_role(["Customer"])
    body = request.get_json(silent=True) or {}
    job_id = as_str(req_field(body, "job_id"), "job_id")
    claimed_defect = as_enum(req_field(body, "claimed_defect"), "claimed_defect",
                              {"MISREGISTER", "COLOR_SHIFT", "TRIM_ERROR", "BINDING_DEFECT",
                               "PAPER_STOCK_WRONG", "SHORTAGE"})
    defect_qty_raw = req_field(body, "defect_qty")
    if not is_int(defect_qty_raw):
        raise err_validation("defect_qty must be an integer")
    job = DB["jobs"].get(job_id)
    if job is None:
        raise err_not_found("job not found")
    check_customer_ownership(user_id, role, job["customer_id"])
    if job["production_status"] not in ("FULFILLED", "CLOSED"):
        raise ApiError("ERR_JOB_INVALID_STATE", "Job must be FULFILLED or CLOSED", 409)
    # claim uniqueness
    for c in DB["reprint_claims"].values():
        if c["job_id"] == job_id and c["status"] in ("FILED", "UNDER_REVIEW"):
            raise ApiError("ERR_CLAIM_ALREADY_OPEN", "An open claim already exists for this job", 409)
    delivered = job["delivered_quantity"] or 0
    if defect_qty_raw < 1 or defect_qty_raw > delivered:
        raise ApiError("ERR_DEFECT_QTY_INVALID",
                       "defect_qty out of range", 422)
    ts = new_ts()
    c = {
        "id": new_id(),
        "job_id": job_id,
        "invoice_id": None,
        "claimed_defect": claimed_defect,
        "defect_qty": defect_qty_raw,
        "status": "FILED",
        "reviewed_by": None,
        "resolution": None,
        "liability_pct": None,
        "provisional_credit_cents": None,
        "final_credit_cents": None,
        "reprint_job_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["reprint_claims"][c["id"]] = c
    return success_object(ser_claim(c), 201)


@app.route("/reprint-claims/<cid>", methods=["GET"])
def get_claim(cid):
    user_id, role = require_role(["PlantManager", "Customer"])
    c = get_or_404("reprint_claims", cid, "reprint_claim")
    if role == "Customer":
        job = DB["jobs"].get(c["job_id"])
        if job:
            check_customer_ownership(user_id, role, job["customer_id"])
    return success_object(ser_claim(c))


@app.route("/reprint-claims", methods=["GET"])
def list_claims():
    user_id, role = require_role(["PlantManager", "Customer"])
    limit, offset = parse_limit_offset()
    items = list(DB["reprint_claims"].values())
    if role == "Customer":
        own_job_ids = {j["id"] for j in DB["jobs"].values() if j["customer_id"] == user_id}
        items = [c for c in items if c["job_id"] in own_job_ids]
    for f in ("job_id", "invoice_id", "reprint_job_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if c.get(f) == v]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_claim(c) for c in page], limit, offset, total)


@app.route("/reprint-claims/<cid>/review", methods=["POST"])
def review_claim(cid):
    user_id, role = require_role(["PlantManager"])
    c = get_or_404("reprint_claims", cid, "reprint_claim")
    if c["status"] != "FILED":
        raise ApiError("ERR_CLAIM_STATE", "Claim must be FILED to review", 409)
    c["status"] = "UNDER_REVIEW"
    c["reviewed_by"] = user_id
    touch(c)
    return success_object(ser_claim(c))


@app.route("/reprint-claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    user_id, role = require_role(["PlantManager"])
    c = get_or_404("reprint_claims", cid, "reprint_claim")
    body = request.get_json(silent=True) or {}
    resolution = req_field(body, "resolution")
    liability_pct = req_field(body, "liability_pct")
    if c["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CLAIM_STATE", "Claim must be UNDER_REVIEW to approve", 409)
    if c["reviewed_by"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Approver must differ from reviewer", 403)
    if resolution not in ("REPRINT", "CREDIT"):
        raise err_validation("resolution must be REPRINT or CREDIT")
    if liability_pct not in (25, 50, 100):
        raise err_validation("liability_pct must be 25, 50, or 100")

    job = DB["jobs"].get(c["job_id"])
    if job is None:
        raise err_not_found("job not found")

    if resolution == "REPRINT":
        ts = new_ts()
        reprint = {
            "id": new_id(),
            "estimate_id": None,
            "parent_job_id": job["id"],
            "customer_id": job["customer_id"],
            "zero_charge": True,
            "quantity_ordered": c["defect_qty"],
            "due_date": job["due_date"],
            "press_type": job["press_type"],
            "fulfillment_type": job["fulfillment_type"],
            "binding_method": job["binding_method"],
            "signatures": [dict(s) for s in job["signatures"]],
            "press_spoilage_pct": job["press_spoilage_pct"],
            "bindery_spoilage_pct": job["bindery_spoilage_pct"],
            "included_proof_rounds": job["included_proof_rounds"],
            "tolerance_pct": job["tolerance_pct"],
            "total_impressions": job["total_impressions"],
            "make_ready_total_cents": job["make_ready_total_cents"],
            "total_price_cents": job["total_price_cents"],
            "discount_pct": job["discount_pct"],
            "subtotal_cents": job["subtotal_cents"],
            "production_status": "PREPRESS",
            "billing_status": "NOT_BILLABLE",
            "gang_run_id": None,
            "allocated_make_ready_cents": None,
            "delivered_quantity": None,
            "proof_rounds_used": 0,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        DB["jobs"][reprint["id"]] = reprint
        c["reprint_job_id"] = reprint["id"]
    else:  # CREDIT
        # find job's PRODUCTION invoice with open status
        prod_inv = None
        for inv in DB["invoices"].values():
            if inv["job_id"] == job["id"] and inv["kind"] == "PRODUCTION":
                prod_inv = inv
                break
        if (prod_inv is None
                or prod_inv["status"] not in ("ISSUED", "PARTIALLY_PAID", "DISPUTED")
                or compute_invoice_outstanding(prod_inv) <= 0):
            raise ApiError("ERR_CLAIM_NO_OPEN_INVOICE",
                           "No open PRODUCTION invoice for credit", 409)
        c["invoice_id"] = prod_inv["id"]
        defect_qty = c["defect_qty"]
        delivered = prod_inv["delivered_quantity"]
        prov = rhu(Decimal(prod_inv["base_amount_cents"]) * Decimal(liability_pct) / Decimal(100)
                   * Decimal(defect_qty) / Decimal(delivered))
        fin_raw = rhu(Decimal(prod_inv["total_due_cents"]) * Decimal(liability_pct) / Decimal(100)
                      * Decimal(defect_qty) / Decimal(delivered))
        fin = min(fin_raw, prod_inv["total_due_cents"])
        c["provisional_credit_cents"] = prov
        c["final_credit_cents"] = fin
        outstanding = compute_invoice_outstanding(prod_inv)
        applied = min(fin, outstanding)
        remainder = fin - applied
        prod_inv["credit_applied_cents"] += applied
        new_outstanding = compute_invoice_outstanding(prod_inv)
        if new_outstanding == 0:
            prod_inv["status"] = "PAID"
        touch(prod_inv)
        customer = DB["customers"].get(job["customer_id"])
        if customer is None:
            raise err_not_found("customer not found")
        customer["reprint_credit_balance_cents"] += remainder
        touch(customer)
        if prod_inv["status"] == "PAID":
            cascade_invoice_paid(prod_inv)
        recompute_customer(customer["id"])

    c["resolution"] = resolution
    c["liability_pct"] = liability_pct
    c["status"] = "APPROVED"
    touch(c)
    return success_object(ser_claim(c))


@app.route("/reprint-claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    user_id, role = require_role(["PlantManager"])
    c = get_or_404("reprint_claims", cid, "reprint_claim")
    body = request.get_json(silent=True) or {}
    _ = req_field(body, "reason")
    if c["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CLAIM_STATE", "Claim must be UNDER_REVIEW to deny", 409)
    if c["reviewed_by"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Denier must differ from reviewer", 403)
    c["status"] = "DENIED"
    touch(c)
    return success_object(ser_claim(c))


# ===========================================================================
# CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = require_role(["PlantManager"])
    body = request.get_json(silent=True) or {}
    to_iso8601 = as_str(req_field(body, "to_iso8601"), "to_iso8601")
    try:
        target = parse_dt(to_iso8601)
    except Exception:
        raise err_validation("to_iso8601 must be ISO8601")
    LOGICAL_CLOCK["now"] = target
    return success_object({"current_utc": fmt_ts(target)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
