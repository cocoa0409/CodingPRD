"""Routes: rate schedules, invoices, payments, discharge records."""

from flask import Blueprint, g, request

from db import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_STALE_VERSION, ERR_RATE_OVERLAP, ERR_OVERPAYMENT,
)
from util import (
    ok_object, ok_list, paginate, require_roles, get_or_404, body,
    need_str, need_int, need_enum, need, need_date, opt_date,
    stamp_new, touch, pub, sort_created, fmt_ts, now_ts, parse_date,
)
from logic import (
    build_invoice_lines, compute_late_fee, invoice_paid_cents,
)

bp = Blueprint("routes_e", __name__)

PROVIDER = ("Provider",)
PROVIDER_NURSE = ("Provider", "Nurse")

PAYER_TYPES = ("PRIVATE_PAY", "MEDICAID")
PAYMENT_METHODS = ("CASH", "CHECK", "ACH", "CARD", "MEDICAID_REMIT")


# ---------------------------------------------------------------------------
# Rate schedules
# ---------------------------------------------------------------------------

def _windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open intersection; None upper bound = open-ended."""
    a_hi = a_to or a_from.max
    b_hi = b_to or b_from.max
    return a_from < b_hi and b_from < a_hi


@bp.post("/api/homes/<id>/rate-schedules")
@require_roles(*PROVIDER)
def create_rate_schedule(id):
    get_or_404(db.homes, id, "home")
    b = body()
    # Business rule first where computable (structural validity is last per
    # PRD §2.9): overlap detection needs parseable effective bounds.
    eff_from = None
    eff_to = None
    if isinstance(b.get("effective_from"), str):
        try:
            eff_from = parse_date(b["effective_from"])
        except ValueError:
            eff_from = None
    if b.get("effective_to") is not None and isinstance(b.get("effective_to"), str):
        try:
            eff_to = parse_date(b["effective_to"])
        except ValueError:
            eff_to = None
    payer = b.get("payer_type")
    if eff_from is not None and payer in PAYER_TYPES:
        for rs in db.rate_schedules.values():
            if rs["home_id"] == id and rs["payer_type"] == payer:
                if _windows_overlap(eff_from, eff_to, rs["_effective_from"], rs["_effective_to"]):
                    raise_err(ERR_RATE_OVERLAP,
                              "effective window overlaps an existing schedule for this payer_type")
    # structural validity
    payer = need_enum(b, "payer_type", PAYER_TYPES)
    rnb = need_int(b, "room_and_board_daily_cents")
    if rnb <= 0:
        raise_err(ERR_INVALID_REQUEST, "room_and_board_daily_cents must be > 0")
    low = need_int(b, "care_low_daily_cents")
    if low < 0:
        raise_err(ERR_INVALID_REQUEST, "care_low_daily_cents must be >= 0")
    medium = need_int(b, "care_medium_daily_cents")
    if medium < low:
        raise_err(ERR_INVALID_REQUEST, "care_medium_daily_cents must be >= care_low_daily_cents")
    high = need_int(b, "care_high_daily_cents")
    if high < medium:
        raise_err(ERR_INVALID_REQUEST, "care_high_daily_cents must be >= care_medium_daily_cents")
    eff_from = need_date(b, "effective_from")
    eff_to = opt_date(b, "effective_to")
    if eff_to is not None and eff_to <= eff_from:
        raise_err(ERR_INVALID_REQUEST, "effective_to must be after effective_from")
    rec = stamp_new({
        "home_id": id,
        "payer_type": payer,
        "room_and_board_daily_cents": rnb,
        "care_low_daily_cents": low,
        "care_medium_daily_cents": medium,
        "care_high_daily_cents": high,
        "effective_from": eff_from.isoformat(),
        "effective_to": eff_to.isoformat() if eff_to else None,
        "_effective_from": eff_from,
        "_effective_to": eff_to,
    })
    db.rate_schedules[rec["id"]] = rec
    return ok_object(pub(rec), 201)


@bp.get("/api/homes/<id>/rate-schedules")
@require_roles(*PROVIDER_NURSE)
def list_rate_schedules(id):
    get_or_404(db.homes, id, "home")
    items = sort_created([r for r in db.rate_schedules.values() if r["home_id"] == id])
    payer = request.args.get("payer_type")
    if payer is not None:
        items = [r for r in items if r["payer_type"] == payer]
    page, meta = paginate(items)
    return ok_list([pub(r) for r in page], meta)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@bp.post("/api/residents/<id>/invoices/generate")
@require_roles(*PROVIDER)
def generate_invoice(id):
    resident = get_or_404(db.residents, id, "resident")
    b = body()
    # 4. OCC on the resident
    if "expected_resident_version" in b and b["expected_resident_version"] is not None:
        if b["expected_resident_version"] != resident["version"]:
            raise_err(ERR_STALE_VERSION,
                      "expected_resident_version does not match resident version")
    # 5. state legality: only ADMITTED (provisional) or DISCHARGED (final)
    if resident["status"] not in ("ADMITTED", "DISCHARGED"):
        raise_err(ERR_INVALID_STATE,
                  "invoices generate only for ADMITTED or DISCHARGED residents")
    # lenient date parsing so the rate check (17) can precede structural (22)
    period_start = period_end = None
    if isinstance(b.get("period_start"), str):
        try:
            period_start = parse_date(b["period_start"])
        except ValueError:
            period_start = None
    if isinstance(b.get("period_end"), str):
        try:
            period_end = parse_date(b["period_end"])
        except ValueError:
            period_end = None
    home = get_or_404(db.homes, resident["home_id"], "home")
    lines = subtotal = None
    if period_start is not None and period_end is not None and period_end > period_start:
        # 17. rate-schedule availability for every occupied day
        lines, subtotal = build_invoice_lines(home, resident, period_start, period_end)
    # 22. structural validity
    period_start = need_date(b, "period_start")
    period_end = need_date(b, "period_end")
    if period_end <= period_start:
        raise_err(ERR_INVALID_REQUEST, "period_end must be after period_start")
    due_date = need_date(b, "due_date")
    need(b, "expected_resident_version")

    rec = stamp_new({
        "resident_id": id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "payer_type_snapshot": resident["payer_type"],
        "line_items": lines,
        "subtotal_cents": subtotal,
        "late_fee_cents": 0,
        "total_cents": subtotal,
        "due_date": due_date.isoformat(),
        "status": "DRAFT",
    })
    db.invoices[rec["id"]] = rec
    touch(resident)  # generation increments the resident's version
    return ok_object(pub(rec), 201)


@bp.get("/api/residents/<id>/invoices")
@require_roles(*PROVIDER_NURSE)
def list_invoices(id):
    get_or_404(db.residents, id, "resident")
    items = sort_created([i for i in db.invoices.values() if i["resident_id"] == id])
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    page, meta = paginate(items)
    return ok_list([pub(i) for i in page], meta)


@bp.get("/api/invoices/<id>")
@require_roles(*PROVIDER_NURSE)
def get_invoice(id):
    rec = get_or_404(db.invoices, id, "invoice")
    return ok_object(pub(rec))


@bp.post("/api/invoices/<id>/issue")
@require_roles(*PROVIDER)
def issue_invoice(id):
    rec = get_or_404(db.invoices, id, "invoice")
    if rec["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "invoice is not DRAFT")
    if not rec["line_items"]:
        raise_err(ERR_INVALID_STATE, "invoice has no line items")
    resident = db.residents.get(rec["resident_id"])
    home = db.homes.get(resident["home_id"]) if resident else None
    due = parse_date(rec["due_date"])
    fee = compute_late_fee(home, rec["subtotal_cents"], due) if home else 0
    rec["late_fee_cents"] = fee
    rec["total_cents"] = rec["subtotal_cents"] + fee
    rec["status"] = "ISSUED"
    touch(rec)
    return ok_object(pub(rec))


@bp.post("/api/invoices/<id>/void")
@require_roles(*PROVIDER)
def void_invoice(id):
    rec = get_or_404(db.invoices, id, "invoice")
    if rec["status"] == "DRAFT":
        pass
    elif rec["status"] == "ISSUED":
        if invoice_paid_cents(id) > 0 or any(p["invoice_id"] == id for p in db.payments.values()):
            raise_err(ERR_INVALID_STATE, "ISSUED invoice with payments cannot be voided")
    else:
        raise_err(ERR_INVALID_STATE, "invoice cannot be voided from its current state")
    rec["status"] = "VOID"
    touch(rec)
    return ok_object(pub(rec))


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

@bp.post("/api/payments")
@require_roles(*PROVIDER)
def create_payment():
    b = body()
    # 3. existence, left-to-right
    resident = get_or_404(db.residents, b.get("resident_id"), "resident") \
        if "resident_id" in b else None
    invoice = get_or_404(db.invoices, b.get("invoice_id"), "invoice") \
        if "invoice_id" in b else None
    if resident is not None and invoice is not None and invoice["resident_id"] != resident["id"]:
        raise_err(ERR_NOT_FOUND, "invoice does not belong to the resident")
    # 5. state legality
    if invoice is not None and invoice["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise_err(ERR_INVALID_STATE, "invoice is not payable")
    # 18. amount bounds
    amount = b.get("amount_cents")
    if invoice is not None and isinstance(amount, int) and not isinstance(amount, bool):
        outstanding = invoice["total_cents"] - invoice_paid_cents(invoice["id"])
        if amount <= 0 or amount > outstanding:
            raise_err(ERR_OVERPAYMENT,
                      "amount must be positive and must not exceed the outstanding balance")
    # 22. structural validity
    resident_id = need_str(b, "resident_id")
    invoice_id = need_str(b, "invoice_id")
    amount = need_int(b, "amount_cents")
    method = need_enum(b, "method", PAYMENT_METHODS)
    rec = stamp_new({
        "resident_id": resident_id,
        "invoice_id": invoice_id,
        "amount_cents": amount,
        "method": method,
        "received_at": now_ts(),
    }, common=False)
    db.payments[rec["id"]] = rec
    paid = invoice_paid_cents(invoice_id)
    if paid >= invoice["total_cents"]:
        invoice["status"] = "PAID"
    else:
        invoice["status"] = "PARTIALLY_PAID"
    touch(invoice)
    return ok_object(pub(rec), 201)


@bp.get("/api/payments")
@require_roles(*PROVIDER_NURSE)
def list_payments():
    items = sort_created(list(db.payments.values()))
    for f in ("resident_id", "invoice_id"):
        v = request.args.get(f)
        if v is not None:
            items = [p for p in items if p.get(f) == v]
    page, meta = paginate(items)
    return ok_list([pub(p) for p in page], meta)


@bp.get("/api/payments/<id>")
@require_roles(*PROVIDER_NURSE)
def get_payment(id):
    rec = get_or_404(db.payments, id, "payment")
    return ok_object(pub(rec))


# ---------------------------------------------------------------------------
# Discharge records
# ---------------------------------------------------------------------------

@bp.get("/api/discharge-records")
@require_roles(*PROVIDER_NURSE)
def list_discharge_records():
    items = sort_created(list(db.discharge_records.values()))
    v = request.args.get("resident_id")
    if v is not None:
        items = [r for r in items if r["resident_id"] == v]
    page, meta = paginate(items)
    return ok_list([pub(r) for r in page], meta)


@bp.get("/api/discharge-records/<id>")
@require_roles(*PROVIDER_NURSE)
def get_discharge_record(id):
    rec = get_or_404(db.discharge_records, id, "discharge record")
    return ok_object(pub(rec))
