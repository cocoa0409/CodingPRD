"""Payout batches, the waterfall, approval and disbursement."""
from flask import Blueprint, g

from core import (
    BACKUP_WITHHOLDING_BPS,
    CHARGEBACK_RESERVE_BPS,
    MIN_PAYOUT_CENTS,
    authenticate,
    bps_of,
    db,
    fail,
    filter_eq,
    get_body,
    iso,
    new_record,
    ok,
    ok_list,
    ordered,
    pagination,
    paginate,
    parse_iso,
    public,
    req_dt,
    req_enum,
    req_str,
    opt_str,
    touch,
)
from services import (
    executed_refunds,
    lookup,
    recompute_accrual,
    recompute_batch_totals,
    select_tier,
    write_entry,
)

bp = Blueprint("payouts", __name__)


@bp.post("/api/payout-batches")
def create_batch():
    authenticate({"FinanceOps"})
    body = get_body()
    payout_currency = req_str(body, "payout_currency")
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")

    if not period_start < period_end:
        fail("ERR_BATCH_PERIOD_OVERLAP", "period_start must be strictly before period_end.")
    for existing in ordered(db.payout_batches):
        if existing["status"] == "FAILED":
            continue
        if existing["payout_currency"] != payout_currency:
            continue
        if period_start < existing["_period_end"] and existing["_period_start"] < period_end:
            fail("ERR_BATCH_PERIOD_OVERLAP", "Window intersects an existing batch window.")

    rec = new_record(
        payout_currency=payout_currency,
        period_start=iso(period_start),
        period_end=iso(period_end),
        status="OPEN",
        line_count=0,
        total_payable_cents=0,
        total_withholding_cents=0,
        total_reserve_cents=0,
        submitted_by_user_id=None,
        approved_by_user_id=None,
        failure_reason=None,
    )
    rec["_period_start"] = period_start
    rec["_period_end"] = period_end
    db.payout_batches[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/api/payout-batches")
def list_batches():
    authenticate({"FinanceOps", "PlatformAdmin"})
    limit, offset = pagination()
    rows = ordered(db.payout_batches)
    rows = filter_eq(rows, "status")
    rows = filter_eq(rows, "payout_currency")
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/payout-batches/<payout_batch_id>")
def read_batch(payout_batch_id):
    authenticate({"FinanceOps", "PlatformAdmin"})
    rec = lookup("payout_batches", payout_batch_id)
    return ok(public(rec))


@bp.get("/api/payout-batches/<payout_batch_id>/lines")
def batch_lines(payout_batch_id):
    authenticate({"FinanceOps", "PlatformAdmin"})
    batch = lookup("payout_batches", payout_batch_id)
    limit, offset = pagination()
    rows = [l for l in ordered(db.payout_lines) if l["payout_batch_id"] == batch["id"]]
    rows = filter_eq(rows, "status")
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/payout-lines")
def list_lines():
    authenticate({"FinanceOps", "PlatformAdmin", "Developer"})
    limit, offset = pagination()
    rows = ordered(db.payout_lines)
    for field in ("payout_batch_id", "developer_id", "status"):
        rows = filter_eq(rows, field)
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/payout-lines/<payout_line_id>")
def read_line(payout_line_id):
    authenticate({"FinanceOps", "PlatformAdmin", "Developer"})
    rec = lookup("payout_lines", payout_line_id)
    return ok(public(rec))


def _eligible_purchases(batch):
    out = []
    for p in ordered(db.purchases):
        if p["settlement_status"] != "ACCRUED":
            continue
        if not p.get("captured_at"):
            continue
        captured = parse_iso(p["captured_at"])
        if captured < batch["_period_start"] or captured >= batch["_period_end"]:
            continue
        plan = db.pricing_plans.get(p["pricing_plan_id"])
        if plan is None or plan["currency"] != batch["payout_currency"]:
            continue
        out.append(p)
    return out


@bp.post("/api/payout-batches/<payout_batch_id>/calculate")
def calculate(payout_batch_id):
    authenticate({"FinanceOps"})
    batch = lookup("payout_batches", payout_batch_id)
    if batch["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Batch is not OPEN.")

    eligible = _eligible_purchases(batch)
    by_developer = {}
    for p in eligible:
        by_developer.setdefault(p["developer_id"], []).append(p)

    line_count = 0
    total_reserve = 0
    for dev in ordered(db.developers):
        purchases = by_developer.get(dev["id"])
        if not purchases:
            continue

        final_share_bps = select_tier(dev["lifetime_revenue_base_cents"])
        final_nets = {p["id"]: bps_of(p["revenue_base_cents"], final_share_bps) for p in purchases}
        tier_trueup = sum(
            final_nets[p["id"]] - (p["provisional_developer_net_cents"] or 0) for p in purchases
        )

        reversals = 0
        for p in purchases:
            reversals += sum(
                r["developer_net_reversal_cents"] or 0 for r in executed_refunds(p["id"])
            )

        gross_earnings = (
            sum(final_nets[p["id"]] for p in purchases)
            + sum(p["developer_tax_remittance_cents"] for p in purchases)
            - reversals
            + dev["carryover_cents"]
        )
        reserve = bps_of(max(0, gross_earnings), CHARGEBACK_RESERVE_BPS)
        after_reserve = gross_earnings - reserve
        recovery = min(max(0, after_reserve), dev["negative_balance_cents"])
        after_recovery = after_reserve - recovery
        if dev["tax_id_provided"]:
            withholding = 0
        else:
            withholding = bps_of(max(0, after_recovery), BACKUP_WITHHOLDING_BPS)
        payable = after_recovery - withholding

        if payable < MIN_PAYOUT_CENTS:
            status = "HELD_BELOW_MINIMUM"
            payout_amount = 0
            carryover_added = max(0, payable)
        else:
            status = "PAYABLE"
            payout_amount = payable
            carryover_added = 0

        line = new_record(
            payout_batch_id=batch["id"],
            developer_id=dev["id"],
            gross_earnings_cents=gross_earnings,
            final_share_bps=final_share_bps,
            tier_trueup_cents=tier_trueup,
            reserve_cents=reserve,
            recovery_cents=recovery,
            withholding_cents=withholding,
            payout_amount_cents=payout_amount,
            carryover_added_cents=carryover_added,
            status=status,
        )
        line["_purchase_ids"] = [p["id"] for p in purchases]
        db.payout_lines[line["id"]] = line
        line_count += 1
        total_reserve += reserve

        if status == "HELD_BELOW_MINIMUM":
            dev["carryover_cents"] = carryover_added
            touch(dev)

    batch["line_count"] = line_count
    batch["total_reserve_cents"] = total_reserve
    batch["status"] = "CALCULATED"
    recompute_batch_totals(batch)
    return ok(public(batch))


@bp.post("/api/payout-batches/<payout_batch_id>/submit")
def submit(payout_batch_id):
    authenticate({"FinanceOps"})
    batch = lookup("payout_batches", payout_batch_id)
    if batch["status"] != "CALCULATED":
        fail("ERR_INVALID_STATE", "Batch is not CALCULATED.")
    batch["status"] = "PENDING_APPROVAL"
    batch["submitted_by_user_id"] = g.user_id
    touch(batch)
    return ok(public(batch))


@bp.post("/api/payout-batches/<payout_batch_id>/approve")
def approve(payout_batch_id):
    authenticate({"PlatformAdmin"})
    batch = lookup("payout_batches", payout_batch_id)
    if batch["status"] != "PENDING_APPROVAL":
        fail("ERR_INVALID_STATE", "Batch is not PENDING_APPROVAL.")
    for line in ordered(db.payout_lines):
        if line["payout_batch_id"] != batch["id"] or line["status"] != "PAYABLE":
            continue
        dev = db.developers.get(line["developer_id"])
        if dev is not None and dev["payout_hold"]:
            fail("ERR_DEVELOPER_PAYOUT_HELD", "A payable line belongs to a held developer.")
    batch["status"] = "APPROVED"
    batch["approved_by_user_id"] = g.user_id
    touch(batch)
    return ok(public(batch))


@bp.post("/api/payout-batches/<payout_batch_id>/pay")
def pay(payout_batch_id):
    authenticate({"FinanceOps"})
    batch = lookup("payout_batches", payout_batch_id)
    body = get_body()
    outcome = req_enum(body, "outcome", {"SUCCEEDED", "FAILED"})
    failure_reason = opt_str(body, "failure_reason")
    if batch["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Batch is not APPROVED.")

    lines = [
        l for l in ordered(db.payout_lines)
        if l["payout_batch_id"] == batch["id"] and l["status"] == "PAYABLE"
    ]

    if outcome == "FAILED":
        batch["status"] = "FAILED"
        batch["failure_reason"] = failure_reason
        touch(batch)
        for line in lines:
            line["status"] = "FAILED"
            touch(line)
        return ok(public(batch))

    batch["status"] = "PAID"
    touch(batch)
    for line in lines:
        line["status"] = "PAID"
        touch(line)
        dev = db.developers.get(line["developer_id"])
        purchase_ids = set(line.get("_purchase_ids") or [])

        for entry in ordered(db.ledger_entries):
            if entry["developer_id"] != line["developer_id"] or entry["settled"]:
                continue
            if entry["purchase_id"] in purchase_ids:
                entry["settled"] = True
                entry["payout_line_id"] = line["id"]

        write_entry(line["developer_id"], "PAYOUT", -line["payout_amount_cents"],
                    "Payout disbursed", payout_line_id=line["id"], settled=True)
        write_entry(line["developer_id"], "RESERVE", -line["reserve_cents"],
                    "Chargeback reserve withheld", payout_line_id=line["id"], settled=True)
        write_entry(line["developer_id"], "RECOVERY", -line["recovery_cents"],
                    "Negative balance recovery", payout_line_id=line["id"], settled=True)
        write_entry(line["developer_id"], "WITHHOLDING", -line["withholding_cents"],
                    "Backup withholding", payout_line_id=line["id"], settled=True)
        write_entry(line["developer_id"], "CARRYOVER", line["carryover_added_cents"],
                    "Carryover deferred to the next batch",
                    payout_line_id=line["id"], settled=True)

        for purchase_id in line.get("_purchase_ids") or []:
            purchase = db.purchases.get(purchase_id)
            if purchase is not None and purchase["settlement_status"] == "ACCRUED":
                purchase["settlement_status"] = "PAID"
                touch(purchase)

        if dev is not None:
            recompute_accrual(dev)
            dev["negative_balance_cents"] = max(
                0, dev["negative_balance_cents"] - line["recovery_cents"]
            )
            dev["carryover_cents"] = line["carryover_added_cents"]
            touch(dev)
    return ok(public(batch))


@bp.post("/api/payout-batches/<payout_batch_id>/retry")
def retry(payout_batch_id):
    authenticate({"FinanceOps"})
    batch = lookup("payout_batches", payout_batch_id)
    if batch["status"] != "FAILED":
        fail("ERR_INVALID_STATE", "Batch is not FAILED.")
    batch["status"] = "PENDING_APPROVAL"
    batch["failure_reason"] = None
    touch(batch)
    for line in ordered(db.payout_lines):
        if line["payout_batch_id"] == batch["id"] and line["status"] == "FAILED":
            line["status"] = "PAYABLE"
            touch(line)
    return ok(public(batch))
