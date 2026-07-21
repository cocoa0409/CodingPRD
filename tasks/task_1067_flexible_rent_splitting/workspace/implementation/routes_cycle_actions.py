from flask import Blueprint
from core import (db, ApiError, auth, body, ok, base_full, touch,
                  as_int, parse_dt, clock_iso, get_clock, days_floor, add_days_iso)
from domain import (append_ledger, emit_reminder, cycle_installments,
                    recompute_repaid, recompute_net_remitted)
import serial
import calc

bp = Blueprint("cycle_actions", __name__)


def get_cycle_or_404(cid):
    c = db.billing_cycles.get(cid)
    if c is None:
        raise ApiError("ERR_BILLING_CYCLE_NOT_FOUND", 404, "Billing cycle not found.")
    return c


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


# ---------------------------------------------------------------------------
# Reschedule (OCC-guarded)
# ---------------------------------------------------------------------------
@bp.post("/api/billing-cycles/<cid>/reschedule")
@auth("PlatformAdmin")
def reschedule(cid):
    b = body()
    expected = as_int(b, "expected_cycle_version")
    c = get_cycle_or_404(cid)

    mode = b.get("mode", c["mode"])
    if mode not in ("SPLIT", "DEFER"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid mode.")
    split_count = b.get("split_count", c["split_count"])
    deferred = b.get("deferred_amount_cents", c["deferred_amount_cents"])
    planned = b.get("planned_defer_days", c["planned_defer_days"])
    offsets = b.get("due_offsets_days", None)

    # domain checks (priority 15 split, 16 gap, 12 defer) then OCC (21)
    if offsets is not None:
        if not isinstance(offsets, list) or not offsets or \
                any(isinstance(o, bool) or not isinstance(o, int) for o in offsets):
            raise ApiError("ERR_VALIDATION", 400, "due_offsets_days must be a list of ints.")
        ordered = sorted(offsets)
        for i in range(1, len(ordered)):
            if ordered[i] - ordered[i - 1] < calc.MIN_INSTALLMENT_GAP_DAYS:
                raise ApiError("ERR_INSTALLMENT_GAP_TOO_SHORT", 422,
                               "Consecutive due dates too close.")
    elif mode == "SPLIT":
        if not isinstance(split_count, int) or isinstance(split_count, bool):
            raise ApiError("ERR_VALIDATION", 400, "split_count must be an integer.")
        if not (calc.MIN_SPLIT_COUNT <= split_count <= calc.MAX_SPLIT_COUNT):
            raise ApiError("ERR_INVALID_SPLIT_COUNT", 422, "split_count out of range.")
    else:  # DEFER
        if not isinstance(planned, int) or isinstance(planned, bool):
            raise ApiError("ERR_VALIDATION", 400, "planned_defer_days must be an integer.")
        if not (1 <= planned <= calc.MAX_DEFER_DAYS):
            raise ApiError("ERR_DEFER_WINDOW_EXCEEDED", 422, "defer window exceeded.")

    # OCC
    if expected != c["version"]:
        raise ApiError("ERR_STALE_CYCLE_VERSION", 412, "Stale cycle version.")

    # cancel prior non-terminal installments
    for inst in cycle_installments(cid):
        if inst["status"] in ("SCHEDULED", "FAILED"):
            inst["status"] = "CANCELLED"
            touch(inst)

    # update cycle plan fields and mint fresh set
    c["mode"] = mode
    if offsets is not None:
        n = len(offsets)
        amounts = calc.split_amounts(c["portion_cents"], n)
        ordered = sorted(offsets)
        for k in range(1, n + 1):
            kind = "IMMEDIATE" if k == 1 else "SPLIT"
            _mint_installment(c, k, ordered[k - 1], amounts[k - 1], kind)
        c["split_count"] = n
    elif mode == "SPLIT":
        c["split_count"] = split_count
        c["deferred_amount_cents"] = 0
        c["planned_defer_days"] = 0
        amounts = calc.split_amounts(c["portion_cents"], split_count)
        for k in range(1, split_count + 1):
            offset = (k - 1) * calc.SPLIT_STEP_DAYS[split_count]
            kind = "IMMEDIATE" if k == 1 else "SPLIT"
            _mint_installment(c, k, offset, amounts[k - 1], kind)
    else:  # DEFER
        c["split_count"] = 2
        c["deferred_amount_cents"] = deferred
        c["planned_defer_days"] = planned
        portion = c["portion_cents"]
        _mint_installment(c, 1, 0, portion - deferred, "IMMEDIATE")
        _mint_installment(c, 2, planned, deferred, "DEFERRED")

    recompute_repaid(c)
    touch(c)
    return ok(serial.cycle_out(c))


# ---------------------------------------------------------------------------
# Remit
# ---------------------------------------------------------------------------
@bp.post("/api/billing-cycles/<cid>/remit")
@auth("PlatformAdmin")
def remit(cid):
    c = get_cycle_or_404(cid)
    if c["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Cycle is not SCHEDULED.")
    prop = db.properties.get(c["property_id"])
    if prop is None or prop["integration_status"] != "ACTIVE":
        raise ApiError("ERR_PROPERTY_NOT_ACTIVE", 409, "Property is not ACTIVE.")

    rem = base_full()
    rem.update({
        "cycle_id": cid,
        "property_id": c["property_id"],
        "amount_cents": c["full_rent_cents"],
        "sent_at": clock_iso(),
        "status": "SENT",
    })
    db.remittances[rem["id"]] = rem

    append_ledger(cid, "REMITTANCE_ADVANCE", c["full_rent_cents"],
                  "Full rent advanced to landlord")
    append_ledger(cid, "FEE", c["fee_provisional_cents"], "Provisional flex fee")
    c["net_remitted_cents"] = c["full_rent_cents"]
    c["status"] = "REMITTED"
    touch(c)
    return ok(serial.remittance_out(rem))


# ---------------------------------------------------------------------------
# Settle
# ---------------------------------------------------------------------------
def _final_defer_days(c):
    if c["mode"] != "DEFER":
        return 0
    deferred_inst = None
    for i in cycle_installments(c["id"]):
        if i["kind"] == "DEFERRED" and i["status"] != "CANCELLED":
            deferred_inst = i
    if deferred_inst and deferred_inst["paid_at"]:
        return days_floor(parse_dt(deferred_inst["paid_at"]),
                          parse_dt(c["cycle_start_date"]))
    return c["planned_defer_days"]


@bp.post("/api/billing-cycles/<cid>/settle")
@auth("PlatformAdmin")
def settle(cid):
    c = get_cycle_or_404(cid)
    if c["status"] != "REMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Cycle is not REMITTED.")
    recompute_repaid(c)
    if c["outstanding_cents"] > 0:
        raise ApiError("ERR_INSUFFICIENT_REPAYMENT", 422, "Outstanding balance remains.")

    renter = db.renters.get(c["renter_id"])
    band = renter["risk_band"] if renter else "HIGH"
    defer_days = _final_defer_days(c)
    fee_final = calc.flex_fee(band, c["mode"], c["split_count"],
                              c["deferred_amount_cents"], defer_days)
    c["fee_final_cents"] = fee_final
    if fee_final < c["fee_provisional_cents"]:
        shortfall = c["fee_provisional_cents"] - fee_final
        append_ledger(cid, "FEE_REFUND", -shortfall, "Flex fee overcharge refund")
    c["status"] = "SETTLED"
    touch(c)
    return ok(serial.cycle_out(c))


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------
@bp.post("/api/billing-cycles/<cid>/cancel")
@auth("PlatformAdmin")
def cancel(cid):
    c = get_cycle_or_404(cid)
    if c["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Cycle cannot be cancelled.")
    for inst in cycle_installments(cid):
        if inst["status"] in ("SCHEDULED", "FAILED"):
            inst["status"] = "CANCELLED"
            touch(inst)
    c["status"] = "CANCELLED"
    touch(c)
    return ok(serial.cycle_out(c))


# ---------------------------------------------------------------------------
# Assess delinquency
# ---------------------------------------------------------------------------
@bp.post("/api/billing-cycles/<cid>/assess-delinquency")
@auth("PlatformAdmin")
def assess_delinquency(cid):
    c = get_cycle_or_404(cid)
    if c["status"] != "REMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Cycle is not REMITTED.")

    recompute_repaid(c)
    clock = get_clock()
    unpaid = [i for i in cycle_installments(cid)
              if i["status"] not in ("PAID", "WAIVED", "CANCELLED")]
    overdue = [i for i in unpaid if clock > parse_dt(i["due_date"])]
    if not overdue or c["outstanding_cents"] <= 0:
        raise ApiError("ERR_INVALID_STATE", 409, "Cycle is not delinquent.")

    c["status"] = "DELINQUENT"
    touch(c)

    case = base_full()
    case.update({
        "cycle_id": cid,
        "renter_id": c["renter_id"],
        "recovery_round": 0,
        "accrued_late_fee_cents": 0,
        "principal_outstanding_cents": c["outstanding_cents"],
        "reinstatement_amount_cents": c["outstanding_cents"],
        "settlement_amount_cents": c["outstanding_cents"] + calc.SETTLEMENT_ADMIN_FEE_CENTS,
        "promise_date": None,
        "opened_at": clock_iso(),
        "last_recovery_agent_id": None,
        "status": "OPEN",
    })
    db.delinquency_cases[case["id"]] = case

    earliest = min(unpaid, key=lambda i: parse_dt(i["due_date"]))
    days_overdue = days_floor(clock, parse_dt(earliest["due_date"]))
    if days_overdue >= calc.GRACE_DAYS:
        append_ledger(cid, "LATE_FEE", calc.LATE_FEE_FLAT_CENTS, "Flat late fee on open")
        case["accrued_late_fee_cents"] = calc.LATE_FEE_FLAT_CENTS
        case["reinstatement_amount_cents"] = \
            case["principal_outstanding_cents"] + calc.LATE_FEE_FLAT_CENTS

    emit_reminder(c["renter_id"], cid, "OVERDUE")
    return ok(serial.cycle_out(c))
