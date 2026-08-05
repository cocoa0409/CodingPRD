"""Routes: payouts (open, project accrual, release cash)."""
from decimal import Decimal

from flask import Blueprint, g

import helpers as h
import domain as d
from state import S

bp = Blueprint("payouts", __name__)


def _cycle_invoices(payout):
    hid = payout["house_id"]
    cs = h.parse_date(payout["cycle_start"])
    ce = h.parse_date(payout["cycle_end"])
    out = []
    for inv in S.invoices.values():
        m = S.memberships.get(inv["membership_id"])
        if m is None or m["house_id"] != hid:
            continue
        ps = h.parse_date(inv["period_start"])
        if cs <= ps <= ce:
            out.append(inv)
    return out


def _maintenance_credit(payout):
    hid = payout["house_id"]
    cs = h.parse_date(payout["cycle_start"])
    ce = h.parse_date(payout["cycle_end"])
    total = 0
    for t in S.tickets.values():
        if t["house_id"] != hid or t["status"] != "RESOLVED":
            continue
        rdate = h.parse_instant(t["resolved_at"]).date()
        if cs <= rdate <= ce:
            total += t["rent_credit_cents"]
    return total


@bp.post("/co-living/payouts")
def create_payout():
    h.authorize("FinanceAdmin")
    b = h.body()
    house_id = h.req_str(b, "house_id")
    cycle_start = h.req_date(b, "cycle_start")
    cycle_end = h.req_date(b, "cycle_end")
    # Priority 6: FK
    h.find_or_404(S.houses, house_id, "ERR_HOUSE_NOT_FOUND")
    # Priority 18: date range
    if cycle_end < cycle_start:
        raise h.ApiError("ERR_INVALID_DATE_RANGE", "cycle_end precedes cycle_start")
    # Priority 24: non-overlap with existing payouts of same house
    for p in S.payouts.values():
        if p["house_id"] != house_id:
            continue
        if p["status"] not in ("DRAFT", "PROJECTED", "RELEASED"):
            continue
        ps = h.parse_date(p["cycle_start"])
        pe = h.parse_date(p["cycle_end"])
        if cycle_start <= pe and ps <= cycle_end:
            raise h.ApiError("ERR_PAYOUT_CYCLE_OVERLAP", "cycle overlaps an existing payout")

    payout = h.new_common()
    payout.update({
        "house_id": house_id,
        "cycle_start": b["cycle_start"],
        "cycle_end": b["cycle_end"],
        "status": "DRAFT",
        "variant_applied": "NONE",
        "gross_cents": 0,
        "platform_fee_cents": 0,
        "maintenance_credit_cents": 0,
        "reserve_cents": 0,
        "net_payout_cents": 0,
        "projected_by_user_id": None,
        "released_by_user_id": None,
        "released_at": None,
    })
    S.payouts[payout["id"]] = payout
    return h.ok(d.serialize(payout), 201)


@bp.post("/co-living/payouts/<pid>/project")
def project_payout(pid):
    h.authorize("FinanceAdmin")
    payout = h.find_or_404(S.payouts, pid, "ERR_PAYOUT_NOT_FOUND")
    # Priority 10: state
    if payout["status"] != "DRAFT":
        raise h.ApiError("ERR_INVALID_PAYOUT_STATE", "payout is not DRAFT")

    invoices = _cycle_invoices(payout)
    credit = _maintenance_credit(payout)
    gross = sum(i["total_amount_cents"] for i in invoices)
    fee = sum(h.round_half_up(Decimal(i["total_amount_cents"]) * d.PLATFORM_FEE_RATE)
              for i in invoices)
    reserve = h.round_half_up(Decimal(gross) * d.PAYOUT_RESERVE_RATE)
    net = max(gross - fee - credit - reserve, 0)

    payout.update({
        "gross_cents": gross,
        "platform_fee_cents": fee,
        "maintenance_credit_cents": credit,
        "reserve_cents": reserve,
        "net_payout_cents": net,
        "variant_applied": "ACCRUAL_PROJECTION",
        "projected_by_user_id": g.user_id,
        "status": "PROJECTED",
    })
    h.touch(payout)
    return h.ok(d.serialize(payout), 200)


@bp.post("/co-living/payouts/<pid>/release")
def release_payout(pid):
    h.authorize("FinanceAdmin")
    payout = h.find_or_404(S.payouts, pid, "ERR_PAYOUT_NOT_FOUND")
    # Priority 10: state
    if payout["status"] != "PROJECTED":
        raise h.ApiError("ERR_INVALID_PAYOUT_STATE", "payout is not PROJECTED")
    # Priority 16: house freeze gate (fresh)
    house = S.houses[payout["house_id"]]
    if d.eval_posture(house) == "FROZEN":
        raise h.ApiError("ERR_HOUSE_FROZEN", "house is FROZEN")
    # Priority 17: segregation of duties
    if g.user_id == payout["projected_by_user_id"]:
        raise h.ApiError("ERR_SEGREGATION_OF_DUTIES", "releaser equals projector")

    invoices = _cycle_invoices(payout)
    credit = _maintenance_credit(payout)
    gross = sum(i["amount_paid_cents"] for i in invoices)
    fee = sum(h.round_half_up(Decimal(i["amount_paid_cents"]) * d.PLATFORM_FEE_RATE)
              for i in invoices)
    net = max(gross - fee - credit, 0)

    payout.update({
        "gross_cents": gross,
        "platform_fee_cents": fee,
        "maintenance_credit_cents": credit,
        "reserve_cents": 0,
        "net_payout_cents": net,
        "variant_applied": "CASH_FINAL",
        "released_by_user_id": g.user_id,
        "released_at": h.fmt_instant(S.clock),
        "status": "RELEASED",
    })
    h.touch(payout)
    return h.ok(d.serialize(payout), 200)


@bp.get("/co-living/payouts/<pid>")
def get_payout(pid):
    h.authorize(*h.ROLES)
    payout = h.find_or_404(S.payouts, pid, "ERR_PAYOUT_NOT_FOUND")
    return h.ok(d.serialize(payout), 200)


@bp.get("/co-living/payouts")
def list_payouts():
    h.authorize(*h.ROLES)
    limit, offset = h.parse_pagination()
    house_id = h.query_val("house_id")
    status = h.query_val("status")
    rows = []
    for p in S.payouts.values():
        if house_id is not None and p["house_id"] != house_id:
            continue
        if status is not None and p["status"] != status:
            continue
        rows.append(p)
    rows = h.sort_created(rows)
    page, pag = h.paginate(rows, limit, offset)
    return h.ok([d.serialize(x) for x in page], 200, "array", pag)
