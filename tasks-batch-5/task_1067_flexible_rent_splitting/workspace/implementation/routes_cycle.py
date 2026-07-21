from flask import Blueprint, request
from core import (db, ApiError, auth, caller, body, ok, ok_list, base_full, touch,
                  as_str, as_int, as_enum, parse_dt, iso_ms, add_days_iso, clock_iso,
                  get_clock, days_floor, paginate, sort_seq)
from domain import (append_ledger, emit_reminder, cycle_installments,
                    recompute_repaid, recompute_net_remitted)
import serial
import calc

bp = Blueprint("cycle", __name__)


def get_cycle_or_404(cid):
    c = db.billing_cycles.get(cid)
    if c is None:
        raise ApiError("ERR_BILLING_CYCLE_NOT_FOUND", 404, "Billing cycle not found.")
    return c


def cycle_read_access(c):
    """PlatformAdmin, owning Renter, owning PropertyManager."""
    uid, role = caller()
    if role == "Renter" and c["renter_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Not your cycle.")
    if role == "PropertyManager" and c["property_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Not your property's cycle.")


def _mint_installment(cycle, seq, offset_days, amount, kind):
    rec = base_full()
    rec.update({
        "cycle_id": cycle["id"],
        "sequence_no": seq,
        "due_date": add_days_iso(cycle["cycle_start_date"], offset_days),
        "amount_cents": amount,
        "kind": kind,
        "attempt_count": 0,
        "paid_at": None,
        "status": "SCHEDULED",
    })
    db.installments[rec["id"]] = rec
    return rec


def _build_split(cycle, n):
    amounts = calc.split_amounts(cycle["portion_cents"], n)
    for k in range(1, n + 1):
        offset = (k - 1) * calc.SPLIT_STEP_DAYS[n]
        kind = "IMMEDIATE" if k == 1 else "SPLIT"
        _mint_installment(cycle, k, offset, amounts[k - 1], kind)


def _build_defer(cycle, deferred, defer_days):
    portion = cycle["portion_cents"]
    _mint_installment(cycle, 1, 0, portion - deferred, "IMMEDIATE")
    _mint_installment(cycle, 2, defer_days, deferred, "DEFERRED")


def _build_custom(cycle, offsets):
    n = len(offsets)
    amounts = calc.split_amounts(cycle["portion_cents"], n)
    for k in range(1, n + 1):
        kind = "IMMEDIATE" if k == 1 else "SPLIT"
        _mint_installment(cycle, k, offsets[k - 1], amounts[k - 1], kind)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@bp.post("/api/billing-cycles")
@auth("PlatformAdmin")
def create_cycle():
    b = body()
    renter_id = as_str(b, "renter_id")
    cycle_month = as_str(b, "cycle_month")
    cycle_start_raw = as_str(b, "cycle_start_date")
    try:
        cycle_start_iso = iso_ms(parse_dt(cycle_start_raw))
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "cycle_start_date is not a valid datetime.")
    mode = as_enum(b, "mode", {"SPLIT", "DEFER"})

    if mode == "SPLIT":
        split_count = as_int(b, "split_count")
        deferred = 0
        planned_defer_days = 0
    else:
        split_count = 2
        deferred = as_int(b, "deferred_amount_cents", non_negative=True)
        planned_defer_days = as_int(b, "planned_defer_days")

    # existence
    renter = db.renters.get(renter_id)
    if renter is None:
        raise ApiError("ERR_RENTER_NOT_FOUND", 404, "Renter not found.")

    # priority 9: enrolled
    if renter["status"] != "ENROLLED":
        raise ApiError("ERR_RENTER_NOT_ENROLLED", 409, "Renter is not ENROLLED.")

    # priority 12: defer window
    if mode == "DEFER" and not (1 <= planned_defer_days <= calc.MAX_DEFER_DAYS):
        raise ApiError("ERR_DEFER_WINDOW_EXCEEDED", 422, "planned_defer_days out of window.")

    # priority 15: split count
    if mode == "SPLIT" and not (calc.MIN_SPLIT_COUNT <= split_count <= calc.MAX_SPLIT_COUNT):
        raise ApiError("ERR_INVALID_SPLIT_COUNT", 422, "split_count out of range.")

    # priority 17: duplicate cycle
    for c in db.billing_cycles.values():
        if c["renter_id"] == renter_id and c["cycle_month"] == cycle_month \
                and c["status"] != "CANCELLED":
            raise ApiError("ERR_DUPLICATE_CYCLE", 409, "Duplicate cycle for renter/month.")

    portion = renter["portion_rent_cents"]

    # priority 18: limit
    if portion > renter["approved_limit_cents"]:
        raise ApiError("ERR_LIMIT_EXCEEDED", 402, "portion exceeds approved limit.")

    prop = db.properties.get(renter["property_id"])
    full_rent = prop["full_rent_cents"] if prop else 0

    fee_provisional = calc.flex_fee(renter["risk_band"], mode, split_count,
                                    deferred, planned_defer_days)

    rec = base_full()
    rec.update({
        "renter_id": renter_id,
        "property_id": renter["property_id"],
        "cycle_month": cycle_month,
        "cycle_start_date": cycle_start_iso,
        "mode": mode,
        "split_count": split_count,
        "deferred_amount_cents": deferred,
        "planned_defer_days": planned_defer_days,
        "full_rent_cents": full_rent,
        "portion_cents": portion,
        "fee_provisional_cents": fee_provisional,
        "fee_final_cents": None,
        "repaid_amount_cents": 0,
        "net_remitted_cents": 0,
        "outstanding_cents": portion,
        "status": "SCHEDULED",
    })
    db.billing_cycles[rec["id"]] = rec

    if mode == "SPLIT":
        _build_split(rec, split_count)
    else:
        _build_defer(rec, deferred, planned_defer_days)

    return ok(serial.cycle_out(rec), 201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/api/billing-cycles/<cid>")
@auth("PlatformAdmin", "Renter", "PropertyManager")
def get_cycle(cid):
    c = get_cycle_or_404(cid)
    cycle_read_access(c)
    return ok(serial.cycle_out(c))


@bp.get("/api/billing-cycles")
@auth("PlatformAdmin")
def list_cycles():
    renter_id = request.args.get("renter_id")
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    items = [c for c in db.billing_cycles.values()
             if (renter_id is None or c["renter_id"] == renter_id)
             and (property_id is None or c["property_id"] == property_id)
             and (status is None or c["status"] == status)]
    items = sort_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serial.cycle_out(c) for c in page], limit, offset, total)


@bp.get("/api/billing-cycles/<cid>/installments")
@auth("PlatformAdmin", "Renter")
def list_cycle_installments(cid):
    c = get_cycle_or_404(cid)
    cycle_read_access(c)
    items = sort_seq(cycle_installments(cid))
    page, limit, offset, total = paginate(items)
    return ok_list([serial.installment_out(i) for i in page], limit, offset, total)


@bp.get("/api/billing-cycles/<cid>/remittances")
@auth("PlatformAdmin", "PropertyManager")
def list_cycle_remittances(cid):
    c = get_cycle_or_404(cid)
    cycle_read_access(c)
    items = sort_seq([r for r in db.remittances.values() if r["cycle_id"] == cid])
    page, limit, offset, total = paginate(items)
    return ok_list([serial.remittance_out(r) for r in page], limit, offset, total)


@bp.get("/api/billing-cycles/<cid>/ledger")
@auth("PlatformAdmin", "PropertyManager")
def list_cycle_ledger(cid):
    c = get_cycle_or_404(cid)
    cycle_read_access(c)
    items = sort_seq([e for e in db.ledger_entries.values() if e["cycle_id"] == cid])
    page, limit, offset, total = paginate(items)
    return ok_list([serial.ledger_out(e) for e in page], limit, offset, total)


@bp.get("/api/billing-cycles/<cid>/reminders")
@auth("PlatformAdmin", "Renter")
def list_cycle_reminders(cid):
    c = get_cycle_or_404(cid)
    cycle_read_access(c)
    items = sort_seq([x for x in db.reminders.values() if x["cycle_id"] == cid])
    page, limit, offset, total = paginate(items)
    return ok_list([serial.reminder_out(x) for x in page], limit, offset, total)


@bp.get("/api/billing-cycles/<cid>/summary")
@auth("PlatformAdmin", "Renter", "PropertyManager")
def cycle_summary(cid):
    c = get_cycle_or_404(cid)
    cycle_read_access(c)
    return ok(serial.cycle_summary_out(c))
