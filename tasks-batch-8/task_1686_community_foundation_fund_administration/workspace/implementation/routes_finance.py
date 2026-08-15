"""Market value snapshots, spending policy runs, fee assessments, annual statements."""
from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, request

from common import (
    STORE, body, err, executed_agreement, get_path, list_response,
    new_resource, now, parse_dt, q2, req_decimal, req_enum, req_int,
    require_roles, serialize, success, touch,
)

bp = Blueprint("finance", __name__)

SNAPSHOT_KINDS = ("QUARTER_END", "FISCAL_YEAR_END")

TIER1_CAP = Decimal("250000.00")
TIER1_RATE = Decimal("0.0100")
TIER2_CAP = Decimal("750000.00")
TIER2_RATE = Decimal("0.0060")
TIER3_RATE = Decimal("0.0030")
FLAT_RATE = Decimal("0.0075")


def snapshot_view(s):
    return serialize(s)


def run_view(r):
    return serialize(r)


def fee_view(f):
    return serialize(f)


def statement_view(s):
    return serialize(s)


# ---------------------------------------------------------------------------
# Market value snapshots
# ---------------------------------------------------------------------------
@bp.post("/funds/<fundId>/market-value-snapshots")
@require_roles("FinanceOfficer")
def create_snapshot(fundId):
    f = get_path("funds", fundId)
    data = body()
    kind = req_enum(data, "snapshot_kind", SNAPSHOT_KINDS)
    effective = parse_dt(data.get("effective_date"), "effective_date")
    mv = req_decimal(data, "market_value")
    if mv < 0:
        err("ERR_FIELD_CONSTRAINT", 422, "market_value must be >= 0")
    s = new_resource(common_fields=False)
    s.update({
        "fund_id": f["id"],
        "snapshot_kind": kind,
        "effective_date": effective,
        "market_value": q2(mv),
    })
    STORE["snapshots"][s["id"]] = s
    return success(snapshot_view(s), code=201)


@bp.get("/funds/<fundId>/market-value-snapshots")
@require_roles("FoundationAdmin", "FinanceOfficer")
def list_fund_snapshots(fundId):
    f = get_path("funds", fundId)
    items = [s for s in STORE["snapshots"].values() if s["fund_id"] == f["id"]]
    kind = request.args.get("snapshot_kind")
    if kind is not None:
        items = [s for s in items if s["snapshot_kind"] == kind]
    return list_response(items, snapshot_view)


@bp.get("/market-value-snapshots/<snapshotId>")
@require_roles("FoundationAdmin", "FinanceOfficer")
def get_snapshot(snapshotId):
    return success(snapshot_view(get_path("snapshots", snapshotId)))


@bp.get("/market-value-snapshots")
@require_roles("FoundationAdmin", "FinanceOfficer")
def list_snapshots():
    items = list(STORE["snapshots"].values())
    fid = request.args.get("fund_id")
    if fid is not None:
        items = [s for s in items if s["fund_id"] == fid]
    return list_response(items, snapshot_view)


# ---------------------------------------------------------------------------
# Spending policy runs
# ---------------------------------------------------------------------------
@bp.post("/funds/<fundId>/spending-policy-runs")
@require_roles("FinanceOfficer")
def create_spending_run(fundId):
    f = get_path("funds", fundId)
    data = body()
    fiscal_year = req_int(data, "fiscal_year")
    agr = executed_agreement(f["id"])
    if agr is None:
        err("ERR_AGREEMENT_NOT_EXECUTED", 409,
            "Spending policy requires an EXECUTED agreement")
    # Unique per fund per fiscal year.
    for r in STORE["runs"].values():
        if r["fund_id"] == f["id"] and r["fiscal_year"] == fiscal_year:
            err("ERR_UNIQUENESS_VIOLATION", 409,
                "A spending policy run already exists for this fund and fiscal year")
    kind = "QUARTER_END" if agr["spending_formula"] == "AVERAGE_12Q" else "FISCAL_YEAR_END"
    required = 12 if kind == "QUARTER_END" else 3
    run_date = now()
    window = [
        s for s in STORE["snapshots"].values()
        if s["fund_id"] == f["id"]
        and s["snapshot_kind"] == kind
        and s["effective_date"] <= run_date
    ]
    # Most recent first; ties on effective_date broken by earlier created_at first.
    window.sort(key=lambda s: (-s["effective_date"].timestamp(), s["created_at"], s["_seq"]))
    if len(window) < required:
        err("ERR_INSUFFICIENT_HISTORY", 422,
            f"Spending policy run requires {required} {kind} snapshots")
    used = window[:required]
    base = q2(sum(s["market_value"] for s in used) / Decimal(required))
    allowance = q2(base * agr["spending_rate_pct"] / Decimal("100"))
    r = new_resource(common_fields=False)
    r.update({
        "fiscal_year": fiscal_year,
        "fund_id": f["id"],
        "formula_used": agr["spending_formula"],
        "base_value": base,
        "allowance_granted": allowance,
        "market_values_used": [s["market_value"] for s in used],
    })
    STORE["runs"][r["id"]] = r
    f["current_spending_allowance"] = allowance
    f["allowance_used"] = Decimal("0.00")
    touch(f)
    return success(run_view(r), code=201)


@bp.get("/funds/<fundId>/spending-policy-runs")
@require_roles("FoundationAdmin", "FinanceOfficer")
def list_fund_runs(fundId):
    f = get_path("funds", fundId)
    items = [r for r in STORE["runs"].values() if r["fund_id"] == f["id"]]
    return list_response(items, run_view)


@bp.get("/spending-policy-runs/<runId>")
@require_roles("FoundationAdmin", "FinanceOfficer")
def get_run(runId):
    return success(run_view(get_path("runs", runId)))


@bp.get("/spending-policy-runs")
@require_roles("FoundationAdmin", "FinanceOfficer")
def list_runs():
    items = list(STORE["runs"].values())
    fid = request.args.get("fund_id")
    if fid is not None:
        items = [r for r in items if r["fund_id"] == fid]
    return list_response(items, run_view)


# ---------------------------------------------------------------------------
# Fee assessments
# ---------------------------------------------------------------------------
@bp.post("/funds/<fundId>/fee-assessments")
@require_roles("FinanceOfficer")
def create_fee_assessment(fundId):
    f = get_path("funds", fundId)
    data = body()
    qed = parse_dt(data.get("quarter_end_date"), "quarter_end_date")
    balance = req_decimal(data, "quarter_end_balance")
    if balance < 0:
        err("ERR_FIELD_CONSTRAINT", 422, "quarter_end_balance must be >= 0")
    balance = q2(balance)
    agr = executed_agreement(f["id"])
    if agr is None:
        err("ERR_AGREEMENT_NOT_EXECUTED", 409,
            "Fee assessment requires an EXECUTED agreement")
    schedule = agr["fee_tier_schedule"]
    if schedule == "STANDARD":
        t1 = min(balance, TIER1_CAP) * TIER1_RATE
        t2 = max(Decimal("0"), min(balance - TIER1_CAP, TIER2_CAP)) * TIER2_RATE
        t3 = max(Decimal("0"), balance - Decimal("1000000.00")) * TIER3_RATE
        annual = q2(t1 + t2 + t3)
    else:
        annual = q2(balance * FLAT_RATE)
    # Annual fee is rounded to cents first, only then divided by four.
    quarterly = q2(annual / Decimal("4"))
    if quarterly > f["cash_balance"]:
        err("ERR_INSUFFICIENT_CASH", 422,
            "Fee assessment would drive the fund's cash balance below zero")
    fa = new_resource(common_fields=False)
    fa.update({
        "fund_id": f["id"],
        "quarter_end_date": qed,
        "quarter_end_balance": balance,
        "schedule_used": schedule,
        "annual_fee": annual,
        "quarterly_fee": quarterly,
    })
    STORE["fees"][fa["id"]] = fa
    f["cash_balance"] = q2(f["cash_balance"] - quarterly)
    touch(f)
    return success(fee_view(fa), code=201)


@bp.get("/funds/<fundId>/fee-assessments")
@require_roles("FoundationAdmin", "FinanceOfficer")
def list_fund_fees(fundId):
    f = get_path("funds", fundId)
    items = [x for x in STORE["fees"].values() if x["fund_id"] == f["id"]]
    return list_response(items, fee_view)


@bp.get("/fee-assessments/<feeId>")
@require_roles("FoundationAdmin", "FinanceOfficer")
def get_fee(feeId):
    return success(fee_view(get_path("fees", feeId)))


@bp.get("/fee-assessments")
@require_roles("FoundationAdmin", "FinanceOfficer")
def list_fees():
    items = list(STORE["fees"].values())
    fid = request.args.get("fund_id")
    if fid is not None:
        items = [x for x in items if x["fund_id"] == fid]
    return list_response(items, fee_view)


# ---------------------------------------------------------------------------
# Annual statements
# ---------------------------------------------------------------------------
@bp.post("/funds/<fundId>/annual-statements")
@require_roles("FoundationAdmin")
def create_statement(fundId):
    f = get_path("funds", fundId)
    data = body()
    fiscal_year = req_int(data, "fiscal_year")
    for s in STORE["statements"].values():
        if s["fund_id"] == f["id"] and s["fiscal_year"] == fiscal_year:
            err("ERR_UNIQUENESS_VIOLATION", 409,
                "A statement already exists for this fund and fiscal year")
    fy_start = datetime(fiscal_year, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    fy_end = datetime(fiscal_year, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)

    # opening_value: snapshot at fiscal-year open, else prior statement closing, else 0.
    opening_snaps = [
        s for s in STORE["snapshots"].values()
        if s["fund_id"] == f["id"] and s["effective_date"] <= fy_start
    ]
    opening_snaps.sort(key=lambda s: (-s["effective_date"].timestamp(), s["created_at"], s["_seq"]))
    if opening_snaps:
        opening = opening_snaps[0]["market_value"]
    else:
        prior = [s for s in STORE["statements"].values()
                 if s["fund_id"] == f["id"] and s["fiscal_year"] < fiscal_year]
        if prior:
            prior.sort(key=lambda s: s["fiscal_year"], reverse=True)
            opening = prior[0]["closing_value"]
        else:
            opening = Decimal("0.00")

    contributions_total = q2(sum(
        (c["net_proceeds"] for c in STORE["contributions"].values()
         if c["fund_id"] == f["id"]
         and c["acceptance_status"] == "ACCEPTED"
         and c["liquidation_status"] == "LIQUIDATED"
         and c["gift_date"] is not None
         and fy_start <= c["gift_date"] <= fy_end),
        Decimal("0.00"),
    ))
    grants_total = q2(sum(
        (d["amount"] for d in STORE["disbursements"].values()
         if d["fund_id"] == f["id"] and fy_start <= d["created_at"] <= fy_end),
        Decimal("0.00"),
    ))
    fees_total = q2(sum(
        (x["quarterly_fee"] for x in STORE["fees"].values()
         if x["fund_id"] == f["id"] and fy_start <= x["quarter_end_date"] <= fy_end),
        Decimal("0.00"),
    ))
    gain_loss = Decimal("0")
    for e in STORE["events"].values():
        if e["event_kind"] != "MARK_TO_MARKET":
            continue
        if not (fy_start <= e["created_at"] <= fy_end):
            continue
        deltas = e.get("_mtm_fund_deltas") or {}
        if f["id"] in deltas:
            gain_loss += deltas[f["id"]]
    gain_loss = q2(gain_loss)
    closing = q2(opening + contributions_total - grants_total - fees_total + gain_loss)
    st = new_resource(common_fields=False)
    st.update({
        "fund_id": f["id"],
        "fiscal_year": fiscal_year,
        "opening_value": q2(opening),
        "contributions_total": contributions_total,
        "grants_total": grants_total,
        "fees_total": fees_total,
        "investment_gain_loss": gain_loss,
        "closing_value": closing,
        "status": "GENERATED",
    })
    STORE["statements"][st["id"]] = st
    return success(statement_view(st), code=201)


@bp.get("/funds/<fundId>/annual-statements")
@require_roles("FoundationAdmin", "FinanceOfficer", "Advisor")
def list_fund_statements(fundId):
    f = get_path("funds", fundId)
    items = [s for s in STORE["statements"].values() if s["fund_id"] == f["id"]]
    return list_response(items, statement_view)


@bp.get("/statements/<statementId>")
@require_roles("FoundationAdmin", "FinanceOfficer", "Advisor")
def get_statement(statementId):
    return success(statement_view(get_path("statements", statementId)))


@bp.get("/statements")
@require_roles("FoundationAdmin", "FinanceOfficer")
def list_statements():
    items = list(STORE["statements"].values())
    fid = request.args.get("fund_id")
    if fid is not None:
        items = [s for s in items if s["fund_id"] == fid]
    return list_response(items, statement_view)


@bp.post("/statements/<statementId>/deliver")
@require_roles("FoundationAdmin")
def deliver_statement(statementId):
    st = get_path("statements", statementId)
    if st["status"] != "GENERATED":
        err("ERR_INVALID_STATE", 409, "Only a GENERATED statement can be delivered")
    st["status"] = "DELIVERED"
    # Statements are ledger records: no updated_at / version to maintain.
    return success(statement_view(st))
