"""Invoice endpoints."""
from decimal import Decimal
from flask import Blueprint, request
import db
from db import clock, format_ts, parse_ts
from errors import err
from middleware import require_role, get_body, require_fields, check_enum, paginate_args
from response import success_obj, success_list
from services.common import (
    base_record, touch, get_or_404, serialize_invoice,
    find_job_document_package, round_half_up_int, PRIORITY_MULTIPLIER,
)
from routes.permits import lazily_expire_notification

bp = Blueprint("invoices", __name__)


def _market_rate(market, kind):
    if kind == "BOARD":
        return market["board_rate_per_sheet_cents"]
    if kind == "TARP":
        return market["tarp_rate_per_sqft_cents"]
    if kind == "FENCE":
        return market["fence_rate_per_linear_ft_cents"]
    return 0


def _work_lines_for(job, market, variant):
    items = [s for s in db.scope_items.values() if s["job_id"] == job["id"]]
    if variant == "PROVISIONAL":
        eligible = [s for s in items if s["status"] in ("PLANNED", "INSTALLED")]
        qty_key = "planned_qty"
    else:
        eligible = [s for s in items if s["status"] == "INSTALLED"]
        qty_key = "actual_qty"
    multiplier = PRIORITY_MULTIPLIER[job["priority"]]
    lines = []
    subtotal = 0
    for s in eligible:
        qty = s.get(qty_key) or 0
        rate = _market_rate(market, s["kind"])
        line_cents = round_half_up_int(Decimal(str(qty)) * Decimal(rate) * multiplier)
        lines.append({
            "label": s["kind"],
            "quantity": qty,
            "unit": s["unit"],
            "rate_cents": rate,
            "multiplier": float(multiplier),
            "line_cents": line_cents,
        })
        subtotal += line_cents
    return lines, subtotal


def _compute_invoice(job, market, variant):
    lines, work_subtotal = _work_lines_for(job, market, variant)
    service_subtotal = 0
    removal_fee = 0
    if variant == "FINAL":
        for s in db.temporary_services.values():
            if s["job_id"] != job["id"]:
                continue
            if s["kind"] in ("POWER", "LIGHTING") and s["status"] == "COMPLETED":
                service_subtotal += s.get("service_total_cents") or 0
        # patrol: sum of fee_cents over visits in terminal states
        for s in db.temporary_services.values():
            if s["job_id"] != job["id"] or s["kind"] != "PATROL":
                continue
            for v in db.patrol_visits.values():
                if v["temporary_service_id"] == s["id"] and v["status"] in ("CHECKED_IN", "MISSED"):
                    service_subtotal += v.get("fee_cents") or 0
        removal_fee = market["removal_flat_fee_cents"]
    penalty = 0
    penalty_case = None
    for p in db.permit_cases.values():
        if p["job_id"] != job["id"]:
            continue
        if p["kind"] == "NOTIFICATION" and p["status"] == "FILED" and p.get("is_late") and not p.get("penalty_billed"):
            penalty = market["late_notification_fee_cents"]
            penalty_case = p
            break
    pre_discount_total = work_subtotal + service_subtotal + removal_fee + penalty
    if pre_discount_total >= 500000:
        tier_pct = Decimal("0.10")
    elif pre_discount_total >= 200000:
        tier_pct = Decimal("0.05")
    else:
        tier_pct = Decimal("0")
    discount = round_half_up_int(Decimal(work_subtotal) * tier_pct)
    total = pre_discount_total - discount
    return {
        "lines": lines,
        "work_subtotal_cents": work_subtotal,
        "service_subtotal_cents": service_subtotal,
        "removal_fee_cents": removal_fee,
        "penalty_cents": penalty,
        "discount_cents": discount,
        "pre_discount_total_cents": pre_discount_total,
        "total_cents": total,
        "_penalty_case": penalty_case,
    }


@bp.route("/jobs/<jid>/invoices", methods=["POST"])
def create_invoice(jid):
    require_role("Dispatcher")
    job = get_or_404(db.jobs, jid, "Job")
    body = get_body()
    require_fields(body, ["variant"])
    variant = check_enum(body["variant"], {"PROVISIONAL", "FINAL"}, "variant")
    if job["work_status"] == "CLOSED":
        raise err("ERR_ALREADY_TERMINAL", "Job is CLOSED")
    # variant validity
    if variant == "PROVISIONAL":
        if job["work_status"] != "SECURED":
            raise err("ERR_INVOICE_VARIANT_INVALID", "PROVISIONAL requires job SECURED")
    else:
        if job["work_status"] != "REMOVED":
            raise err("ERR_INVOICE_VARIANT_INVALID", "FINAL requires job REMOVED")
        # FINAL requires existing PROVISIONAL
        has_prov = any(
            i for i in db.invoices.values()
            if i["job_id"] == job["id"] and i["variant"] == "PROVISIONAL"
        )
        if not has_prov:
            raise err("ERR_INVOICE_VARIANT_INVALID", "FINAL requires an existing PROVISIONAL")
    # one open invoice per job
    for i in db.invoices.values():
        if i["job_id"] == job["id"] and i["status"] in ("DRAFT", "SUBMITTED", "DISPUTED"):
            raise err("ERR_INVOICE_OPEN_EXISTS", "Open invoice exists")
    prop = db.properties.get(job["property_id"])
    market = db.markets.get(prop["market_id"])
    calc = _compute_invoice(job, market, variant)
    penalty_case = calc.pop("_penalty_case")
    rec = base_record()
    rec.update({
        "job_id": job["id"],
        "variant": variant,
        "status": "DRAFT",
        "lines": calc["lines"],
        "work_subtotal_cents": calc["work_subtotal_cents"],
        "service_subtotal_cents": calc["service_subtotal_cents"],
        "removal_fee_cents": calc["removal_fee_cents"],
        "penalty_cents": calc["penalty_cents"],
        "discount_cents": calc["discount_cents"],
        "pre_discount_total_cents": calc["pre_discount_total_cents"],
        "total_cents": calc["total_cents"],
        "submitted_at": None,
        "paid_at": None,
    })
    db.invoices[rec["id"]] = rec
    if penalty_case is not None:
        penalty_case["penalty_billed"] = True
        touch(penalty_case)
    return success_obj(serialize_invoice(rec), 201)


@bp.route("/jobs/<jid>/invoices", methods=["GET"])
def list_invoices(jid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    get_or_404(db.jobs, jid, "Job")
    limit, offset = paginate_args()
    items = [i for i in db.invoices.values() if i["job_id"] == jid]
    items.sort(key=lambda i: i["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_invoice(i) for i in page], total, limit, offset)


@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    rec = get_or_404(db.invoices, iid, "Invoice")
    return success_obj(serialize_invoice(rec))


def _submit_gates(invoice, job, variance_override):
    """Run submission gates in priority order."""
    prop = db.properties.get(job["property_id"])
    market = db.markets.get(prop["market_id"])
    # (iii) permit
    if market.get("permit_required"):
        has_approved = any(
            p for p in db.permit_cases.values()
            if p["job_id"] == job["id"] and p["kind"] == "PERMIT" and p["status"] == "APPROVED"
        )
        if not has_approved:
            raise err("ERR_PERMIT_NOT_APPROVED", "Permit not approved")
    # (iv) documentation
    pkg = find_job_document_package(job["id"])
    if pkg is None or pkg["status"] == "INCOMPLETE":
        raise err("ERR_DOCS_INCOMPLETE", "Document package incomplete")
    # (v) notification
    if market.get("notification_required"):
        # lazy-expire pending notifications first
        for p in db.permit_cases.values():
            if p["job_id"] == job["id"] and p["kind"] == "NOTIFICATION":
                lazily_expire_notification(p)
        pending = any(
            p for p in db.permit_cases.values()
            if p["job_id"] == job["id"] and p["kind"] == "NOTIFICATION" and p["status"] == "PENDING"
        )
        if pending:
            raise err("ERR_NOTIFICATION_PENDING", "Notification still pending")
        if job.get("compliance_breach"):
            raise err("ERR_NOTIFICATION_DEADLINE_EXPIRED", "Compliance breach latched")
    # fiscal: variance cap (FINAL only)
    if invoice["variant"] == "FINAL" and not variance_override:
        provisional = None
        for i in db.invoices.values():
            if i["job_id"] == job["id"] and i["variant"] == "PROVISIONAL":
                provisional = i
                break
        if provisional is not None:
            cap = round_half_up_int(Decimal(provisional["work_subtotal_cents"]) * Decimal("1.20"))
            if invoice["work_subtotal_cents"] > cap:
                raise err("ERR_VARIANCE_CAP_EXCEEDED", "FINAL work subtotal exceeds 120% of provisional")
    return pkg


@bp.route("/invoices/<iid>/submit", methods=["POST"])
def submit_invoice(iid):
    require_role("Dispatcher")
    invoice = get_or_404(db.invoices, iid, "Invoice")
    body = get_body()
    variance_override = body.get("variance_override", False)
    if not isinstance(variance_override, bool):
        variance_override = bool(variance_override)
    if invoice["status"] == "PAID":
        raise err("ERR_ALREADY_TERMINAL", "Invoice is PAID")
    if invoice["status"] not in ("DRAFT", "DISPUTED"):
        raise err("ERR_INVALID_STATE", "Invoice must be DRAFT or DISPUTED to submit")
    job = db.jobs.get(invoice["job_id"])
    pkg = _submit_gates(invoice, job, variance_override)
    invoice["status"] = "SUBMITTED"
    invoice["submitted_at"] = format_ts(clock.now())
    touch(invoice)
    if pkg is not None:
        if pkg["status"] in ("COMPLETE", "AMENDED"):
            pkg["status"] = "LOCKED"
            touch(pkg)
    return success_obj(serialize_invoice(invoice))


@bp.route("/invoices/<iid>/dispute", methods=["POST"])
def dispute_invoice(iid):
    user_id, _ = require_role("Customer")
    invoice = get_or_404(db.invoices, iid, "Invoice")
    job = db.jobs.get(invoice["job_id"])
    if job is None:
        raise err("ERR_NOT_FOUND", "Job not found")
    if job["customer_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Caller does not own this job")
    if invoice["status"] == "PAID":
        raise err("ERR_ALREADY_TERMINAL", "Invoice is PAID")
    if invoice["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Invoice must be SUBMITTED")
    invoice["status"] = "DISPUTED"
    touch(invoice)
    pkg = find_job_document_package(job["id"])
    if pkg is not None and pkg["status"] == "LOCKED":
        pkg["status"] = "AMENDED"
        touch(pkg)
    return success_obj(serialize_invoice(invoice))


@bp.route("/invoices/<iid>/record-payment", methods=["POST"])
def record_payment(iid):
    require_role("Dispatcher")
    invoice = get_or_404(db.invoices, iid, "Invoice")
    if invoice["status"] == "PAID":
        raise err("ERR_ALREADY_TERMINAL", "Invoice is PAID")
    if invoice["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Invoice must be SUBMITTED")
    invoice["status"] = "PAID"
    invoice["paid_at"] = format_ts(clock.now())
    touch(invoice)
    return success_obj(serialize_invoice(invoice))
