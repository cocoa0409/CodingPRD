"""Domain services: aggregates, posture, calculations, sweeps, cascades.

Everything here reads and writes the in-memory store directly; routes call
into these helpers after auth/existence/shape validation.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import STORE, touch
from util import (
    dec, money2_dec, frac4, pct2, quarter_end, quarter_index, quarter_label,
    quarters_held, parse_quarter,
)

STRATEGIES = ["BUYOUT", "VENTURE", "GROWTH", "CREDIT", "REAL_ASSETS", "SECONDARIES"]

# Built-in 12-quarter vintage call curve (sums to 1.0), keyed by
# quarters-since-vintage offset 0..11. A fixed plausible front-loaded curve.
VINTAGE_CALL_CURVE = [
    Decimal("0.20"), Decimal("0.15"), Decimal("0.12"), Decimal("0.10"),
    Decimal("0.10"), Decimal("0.08"), Decimal("0.07"), Decimal("0.06"),
    Decimal("0.05"), Decimal("0.03"), Decimal("0.02"), Decimal("0.02"),
]

LOW_CASH_BAND = Decimal("1.10")
DD_APPROVAL_THRESHOLD = Decimal("70")
WRAPPER_RATE = Decimal("0.005")
EPSILON = Decimal("0.01")
LAG_DAYS = 90
FORECAST_QUARTERS = 8


# ---------------------------------------------------------------------------
# Program aggregates (PRD 2.6) and posture (PRD 2.4).
# ---------------------------------------------------------------------------

def recompute_program_aggregates(prog):
    """Recompute committed/deployed/returned/unfunded/secondary totals and
    unrestricted_cash from source rows. Does not touch version/posture."""
    pid = prog["id"]
    committed = Decimal("0")
    for c in STORE.commitments.values():
        # EXECUTED rows count at sized_amount; REDUCED rows count at their
        # reduced sized_amount (concentration_check input set, PRD 3.4/3.5).
        if c["program_id"] == pid and c["status"] in ("EXECUTED", "REDUCED"):
            committed += dec(c["sized_amount"])
    deployed = Decimal("0")
    for c in STORE.calls.values():
        if c["program_id"] == pid and c["status"] == "PAID":
            deployed += dec(c["amount"])
    returned = Decimal("0")
    for d in STORE.distributions.values():
        if d["program_id"] == pid and d["status"] == "RECEIVED":
            returned += dec(d["amount"])
    secondary_unfunded = Decimal("0")
    for b in STORE.secondary_bids.values():
        if b["program_id"] == pid and b["status"] == "SETTLED" and b["side"] == "PURCHASE":
            secondary_unfunded += dec(b["unfunded_assumed"])
    cash = Decimal("0")
    for e in STORE.ledger_entries.values():
        if e["program_id"] == pid:
            cash += dec(e["amount"])
    # unfunded_total: sum of unfunded_amount over EXECUTED commitments. The
    # secondary-purchase settle creates its commitment already EXECUTED with
    # unfunded_amount == unfunded_assumed, so that amount is carried by the
    # commitment itself; adding secondary_purchase_unfunded_total again would
    # double count it (PRD 3.5 read together with the settle side effects).
    unfunded = Decimal("0")
    for c in STORE.commitments.values():
        if c["program_id"] == pid and c["status"] == "EXECUTED":
            unfunded += dec(c["unfunded_amount"])
    prog["committed_total"] = float(money2_dec(committed))
    prog["deployed_total"] = float(money2_dec(deployed))
    prog["returned_total"] = float(money2_dec(returned))
    prog["secondary_purchase_unfunded_total"] = float(money2_dec(secondary_unfunded))
    prog["unfunded_total"] = float(money2_dec(unfunded))
    prog["unrestricted_cash"] = float(money2_dec(cash))


def compute_posture(prog):
    """PRD 2.4: FROZEN when SUSPENDED/CLOSED; RESTRICTED on any OVERDUE call
    or cash strictly below buffer*1.10; else NORMAL."""
    if prog["status"] in ("SUSPENDED", "CLOSED"):
        return "FROZEN"
    pid = prog["id"]
    for c in STORE.calls.values():
        if c["program_id"] == pid and c["status"] == "OVERDUE":
            return "RESTRICTED"
    if dec(prog["unrestricted_cash"]) < dec(prog["liquidity_buffer_min"]) * LOW_CASH_BAND:
        return "RESTRICTED"
    return "NORMAL"


def recompute_posture(prog):
    prog["posture"] = compute_posture(prog)


def program_mutated(prog):
    """Aggregate + posture recompute and version bump after any contributing
    event lands (ledger append, call pay, distribution receive, settle)."""
    recompute_program_aggregates(prog)
    recompute_posture(prog)
    touch(prog)


def append_ledger(prog, entry_kind, amount, ref_entity=None, ref_id=None, note=None):
    """Append an entry and recompute unrestricted_cash + posture + version.
    amount is a signed JSON number (Decimal-safe via str())."""
    cash = dec(prog["unrestricted_cash"]) + dec(amount)
    entry = db.new_entity(STORE.ledger_entries, {
        "program_id": prog["id"],
        "entry_kind": entry_kind,
        "amount": float(money2_dec(amount)),
        "ref_entity": ref_entity,
        "ref_id": ref_id,
        "note": note,
        "balance_after": float(money2_dec(cash)),
    }, common=False)
    prog["unrestricted_cash"] = float(money2_dec(cash))
    recompute_program_aggregates(prog)
    recompute_posture(prog)
    touch(prog)
    return entry


# ---------------------------------------------------------------------------
# Overdue sweep (logical clock advance).
# ---------------------------------------------------------------------------

def overdue_sweep():
    """ISSUED calls whose due_date + program.overdue_grace_days has passed
    flip to OVERDUE; affected programs get posture recomputed."""
    now = db.now()
    affected = set()
    for call in STORE.calls.values():
        if call["status"] != "ISSUED":
            continue
        prog = STORE.programs.get(call["program_id"])
        if prog is None:
            continue
        from util import parse_datetime as _pdt
        due = _pdt(call["due_date"])
        if due is None:
            continue
        deadline = due + timedelta(days=prog["overdue_grace_days"])
        if deadline < now:
            call["status"] = "OVERDUE"
            touch(call)
            affected.add(prog["id"])
    for pid in affected:
        prog = STORE.programs.get(pid)
        if prog is not None:
            recompute_posture(prog)
            touch(prog)


# ---------------------------------------------------------------------------
# calculations.pacing_targets (waterfall allocation with remainder sweep).
# ---------------------------------------------------------------------------

def run_pacing_targets(prog, plan):
    """Populate target_commit_by_year and projected_total_commit.

    remaining_budget = total_nav_budget - committed_total (EXECUTED only)
    annual_pool = remaining_budget / horizon_years
    one row per (vintage_year, mix entry); per-row rounding THEN the
    remainder cents sweep into the first row (earliest year, first mix
    strategy in input order) so rows sum exactly to round(remaining, 2).
    """
    remaining = dec(prog["total_nav_budget"]) - dec(prog["committed_total"])
    horizon = plan["horizon_years"]
    mix = plan["target_strategy_mix"]
    annual_pool = remaining / Decimal(horizon)
    rows = []
    for yi in range(horizon):
        year = plan["start_vintage_year"] + yi
        for m in mix:
            amt = money2_dec(annual_pool * dec(m["weight"]))
            rows.append({
                "vintage_year": year,
                "strategy": m["strategy"],
                "amount": float(amt),
            })
    target_total = money2_dec(remaining)
    row_sum = sum((dec(r["amount"]) for r in rows), Decimal("0"))
    remainder = target_total - row_sum
    if rows:
        rows[0]["amount"] = float(money2_dec(dec(rows[0]["amount"]) + remainder))
    plan["target_commit_by_year"] = rows
    plan["projected_total_commit"] = float(
        money2_dec(sum((dec(r["amount"]) for r in rows), Decimal("0"))))


# ---------------------------------------------------------------------------
# calculations.dd_composite_score.
# ---------------------------------------------------------------------------

def dd_composite(review):
    comp = (Decimal("0.30") * dec(review["score_strategy_fit"])
            + Decimal("0.25") * dec(review["score_track_record"])
            + Decimal("0.25") * dec(review["score_operations"])
            + Decimal("0.20") * dec(review["score_compliance"]))
    return float(comp.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# calculations.concentration_check (proposal recommend).
# ---------------------------------------------------------------------------

def concentration_check(prog, proposal, vehicle):
    """Post-trade strategy and manager shares of total_nav_budget.
    EXECUTED commitments count at sized_amount; REDUCED count at their
    reduced sized_amount; PENDING_DOCS / CANCELLED excluded."""
    base = dec(prog["total_nav_budget"])
    strat_total = Decimal("0")
    mgr_total = Decimal("0")
    for c in STORE.commitments.values():
        if c["program_id"] != prog["id"]:
            continue
        if c["status"] not in ("EXECUTED", "REDUCED"):
            continue
        v = STORE.vehicles.get(c["vehicle_id"])
        if v is None:
            continue
        if v["strategy"] == vehicle["strategy"]:
            strat_total += dec(c["sized_amount"])
        if v["manager_id"] == vehicle["manager_id"]:
            mgr_total += dec(c["sized_amount"])
    proposed = dec(proposal["proposed_amount"])
    strat_pct = frac4((strat_total + proposed) / base)
    mgr_pct = frac4((mgr_total + proposed) / base)
    proposal["concentration_strategy_pct"] = strat_pct
    proposal["concentration_manager_pct"] = mgr_pct


# ---------------------------------------------------------------------------
# Commitment unfunded invariant.
# ---------------------------------------------------------------------------

def paid_calls_total(commitment_id):
    total = Decimal("0")
    for c in STORE.calls.values():
        if c["commitment_id"] == commitment_id and c["status"] == "PAID":
            total += dec(c["amount"])
    return total


def recompute_commitment_unfunded(commitment):
    paid = paid_calls_total(commitment["id"])
    commitment["unfunded_amount"] = float(
        money2_dec(dec(commitment["sized_amount"]) - paid))


# ---------------------------------------------------------------------------
# calculations.nav_rollup + irr_dual + fee_layering (valuation publish).
# ---------------------------------------------------------------------------

def _program_quarter_snapshots(program_id, quarter):
    """Snapshots for this program+quarter, excluding RESTATED, grouped by
    commitment."""
    by_commitment = {}
    for s in STORE.snapshots.values():
        if s["as_of_quarter"] != quarter or s["status"] == "RESTATED":
            continue
        commitment = STORE.commitments.get(s["commitment_id"])
        if commitment is None or commitment["program_id"] != program_id:
            continue
        by_commitment.setdefault(s["commitment_id"], []).append(s)
    return by_commitment


def nav_rollup(prog, quarter):
    """Returns (nav_provisional, nav_final, nav_reported) as floats.

    Per commitment with at least one snapshot this quarter: a FINAL snapshot
    reported within 90 days after quarter end contributes to nav_final and
    nav_reported (latest by reported_at ASC, tie-break created_at ASC);
    otherwise the latest PROVISIONAL contributes to nav_provisional and
    nav_reported. RESTATED snapshots are excluded everywhere.
    """
    pq = parse_quarter(quarter)
    qend = quarter_end(*pq)
    lag_deadline = qend + timedelta(days=LAG_DAYS)
    nav_final = Decimal("0")
    nav_prov = Decimal("0")
    for _cid, snaps in _program_quarter_snapshots(prog["id"], quarter).items():
        finals = [s for s in snaps if s["status"] == "FINAL"]
        provs = [s for s in snaps if s["status"] == "PROVISIONAL"]
        from util import parse_datetime as _pdt
        qualifying_finals = [s for s in finals
                             if _pdt(s["reported_at"]) is not None
                             and _pdt(s["reported_at"]) <= lag_deadline]
        if qualifying_finals:
            best = max(qualifying_finals,
                       key=lambda s: (_pdt(s["reported_at"]), s["created_at"], s["_seq"]))
            nav_final += dec(best["reported_nav"])
        elif provs:
            best = max(provs, key=lambda s: (s["created_at"], s["_seq"]))
            nav_prov += dec(best["reported_nav"])
    nav_final = money2_dec(nav_final)
    nav_prov = money2_dec(nav_prov)
    return float(nav_prov), float(nav_final), float(money2_dec(nav_final + nav_prov))


def _program_cashflows(prog):
    """Chronological (date ASC, created_at ASC tie-break) cashflow series of
    (datetime, signed Decimal) from PAID calls and RECEIVED distributions."""
    from util import parse_datetime as _pdt
    flows = []
    for c in STORE.calls.values():
        if c["program_id"] == prog["id"] and c["status"] == "PAID":
            pay_time = c.get("paid_at") or c["updated_at"]
            flows.append((_pdt(pay_time), c["created_at"], c["_seq"],
                          -dec(c["amount"])))
    for d in STORE.distributions.values():
        if d["program_id"] == prog["id"] and d["status"] == "RECEIVED":
            flows.append((_pdt(d["received_at"]), d["created_at"], d["_seq"],
                          dec(d["amount"])))
    flows.sort(key=lambda f: (f[0], f[1], f[2]))
    return [(f[0], f[3]) for f in flows]


def _solve_irr(flows, terminal_value, terminal_time):
    """Solve NPV=0 for an annual rate; flows are (datetime, Decimal). Returns
    a float percentage (2 decimals), or None when no sign change exists."""
    if not flows and terminal_value == 0:
        return None
    series = [(t, amt) for (t, amt) in flows]
    if terminal_value != 0:
        series.append((terminal_time, dec(terminal_value)))
    if not series:
        return None
    t0 = series[0][0]

    def npv(rate):
        total = Decimal("0")
        for (t, amt) in series:
            years = Decimal(str((t - t0).total_seconds())) / Decimal("31557600")
            base = Decimal("1") + dec(rate)
            if base <= 0:
                return None
            total += amt / (base ** years)
        return total

    def npv_f(rate):
        v = npv(rate)
        if v is None:
            return None
        return float(v)

    # Bracket a sign change. NPV decreases with rate for a normal
    # outflows-then-inflows series, so expand the upper bound until it turns
    # negative (short horizons with large gains can need very high rates).
    lo = -0.9999
    f_lo = npv_f(lo)
    if f_lo is None:
        return None
    if f_lo == 0:
        return pct2(lo * 100)
    hi = 1.0
    f_hi = npv_f(hi)
    for _ in range(20):
        if f_hi is None:
            return None
        if f_lo * f_hi <= 0:
            break
        hi = hi * 10.0
        f_hi = npv_f(hi)
    else:
        return None
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = npv_f(mid)
        if f_mid is None:
            return None
        if abs(f_mid) < 1e-10:
            return pct2(mid * 100)
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return pct2(((lo + hi) / 2.0) * 100)


def irr_dual(prog, quarter, nav_provisional, nav_final):
    """Two IRR variants over the program cashflow series with the given
    terminal NAV at quarter end; percentages with 2 decimals."""
    pq = parse_quarter(quarter)
    qend = quarter_end(*pq)
    flows = _program_cashflows(prog)
    irr_p = _solve_irr(flows, nav_provisional, qend)
    irr_f = _solve_irr(flows, nav_final, qend)
    return irr_p, irr_f


def fee_layering(prog, quarter, nav_reported):
    """total_fee_burden_pct: trailing min(4, quarters_held) quarters of
    layered fees over max(nav_reported, EPSILON), as a percentage.

    Per commitment quarterly fee = round2(mgmt quarterly accrual) +
    round2(carry quarterly) + round2(wrapper quarterly), each component
    rounded to 2 decimals BEFORE summing (round-then-sum pinned order)."""
    pq = parse_quarter(quarter)
    ry, rq = pq
    total = Decimal("0")
    for c in STORE.commitments.values():
        if c["program_id"] != prog["id"] or c["status"] not in ("EXECUTED", "REDUCED"):
            continue
        vehicle = STORE.vehicles.get(c["vehicle_id"])
        if vehicle is None:
            continue
        held = quarters_held(vehicle["vintage_year"], ry, rq)
        if held <= 0:
            continue
        sized = dec(c["sized_amount"])
        # Management-fee rate at the report quarter: early while quarters
        # since vintage <= investment_period_years * 4, else late.
        early_quarters = vehicle["investment_period_years"] * 4
        rate = dec(vehicle["mgmt_fee_rate_early"]) if held <= early_quarters \
            else dec(vehicle["mgmt_fee_rate_late"])
        mgmt_q = money2_dec(sized * rate / Decimal(4))
        # Carry layer on the report quarter.
        paid = paid_calls_total(c["id"])
        latest_nav = _latest_reported_nav(c["id"])
        nav_gain = latest_nav - paid
        hurdle_return = paid * dec(vehicle["hurdle_rate"]) * (Decimal(held) / Decimal(4))
        carry = max(Decimal("0"), nav_gain - hurdle_return) * dec(vehicle["carry_rate"])
        carry_q = money2_dec(carry)
        wrapper_q = money2_dec(sized * WRAPPER_RATE / Decimal(4))
        quarterly = mgmt_q + carry_q + wrapper_q
        trailing = min(4, held)
        total += quarterly * Decimal(trailing)
    denom = max(dec(nav_reported), EPSILON)
    return pct2(total / denom * Decimal(100))


def _latest_reported_nav(commitment_id):
    """Latest non-RESTATED snapshot NAV for a commitment (by reported_at ASC,
    tie-break created_at ASC); zero when none exists."""
    best = None
    from util import parse_datetime as _pdt
    for s in STORE.snapshots.values():
        if s["commitment_id"] != commitment_id or s["status"] == "RESTATED":
            continue
        key = (_pdt(s["reported_at"]) or db.CLOCK_START, s["created_at"], s["_seq"])
        if best is None or key > best[0]:
            best = (key, s)
    return dec(best[1]["reported_nav"]) if best else Decimal("0")


# ---------------------------------------------------------------------------
# calculations.capital_call_forecast (liquidity forecast).
# ---------------------------------------------------------------------------

def liquidity_forecast(prog, stress=False):
    """8-quarter forward net-cash projection from the logical clock quarter.

    forecast_net_cash[q] = unrestricted_cash
        - expected_calls[q] - issued/overdue due in q - accepted purchases
        + pending distributions in q.
    Stress variant: distributions excluded, expected calls scaled by 1.15.
    """
    now = db.now()
    base_idx = quarter_index(now.year, (now.month - 1) // 3 + 1)
    outflows = [Decimal("0")] * FORECAST_QUARTERS
    inflows = [Decimal("0")] * FORECAST_QUARTERS

    # Expected calls from EXECUTED commitments via the vintage call curve.
    for c in STORE.commitments.values():
        if c["program_id"] != prog["id"] or c["status"] != "EXECUTED":
            continue
        vehicle = STORE.vehicles.get(c["vehicle_id"])
        if vehicle is None:
            continue
        vintage_idx = quarter_index(vehicle["vintage_year"], 1)
        unfunded = dec(c["unfunded_amount"])
        for offset in range(12):
            q_abs = vintage_idx + offset
            rel = q_abs - base_idx
            if 0 <= rel < FORECAST_QUARTERS:
                amt = unfunded * VINTAGE_CALL_CURVE[offset]
                if stress:
                    amt = amt * Decimal("1.15")
                outflows[rel] += amt

    # ISSUED / OVERDUE calls count in full in the quarter of their due_date.
    from util import parse_datetime as _pdt
    for c in STORE.calls.values():
        if c["program_id"] != prog["id"] or c["status"] not in ("ISSUED", "OVERDUE"):
            continue
        due = _pdt(c["due_date"])
        if due is None:
            continue
        rel = quarter_index(due.year, (due.month - 1) // 3 + 1) - base_idx
        if 0 <= rel < FORECAST_QUARTERS:
            outflows[rel] += dec(c["amount"])

    # ACCEPTED PURCHASE bids: full price in the current quarter.
    for b in STORE.secondary_bids.values():
        if (b["program_id"] == prog["id"] and b["status"] == "ACCEPTED"
                and b["side"] == "PURCHASE"):
            outflows[0] += dec(b["price"])

    # PENDING distributions: inflow in the quarter of received_at.
    if not stress:
        for d in STORE.distributions.values():
            if d["program_id"] != prog["id"] or d["status"] != "PENDING":
                continue
            recv = _pdt(d["received_at"])
            if recv is None:
                continue
            rel = quarter_index(recv.year, (recv.month - 1) // 3 + 1) - base_idx
            if 0 <= rel < FORECAST_QUARTERS:
                inflows[rel] += dec(d["amount"])

    cash = dec(prog["unrestricted_cash"])
    forecast = [float(money2_dec(cash - outflows[i] + inflows[i]))
                for i in range(FORECAST_QUARTERS)]
    return {
        "program_id": prog["id"],
        "base_quarter": quarter_label(now),
        "forecast_net_cash": forecast,
        "posture": prog["posture"],
    }


# ---------------------------------------------------------------------------
# Look-through aggregation.
# ---------------------------------------------------------------------------

def look_through(prog, group_by, quarter=None):
    """Aggregate look-through lines across the program's latest-quarter
    snapshots, grouped by sector or geography."""
    snaps = [s for s in STORE.snapshots.values()
             if s.get("vehicle_id") is not None]
    # Snapshots scoped to the program via their commitment.
    scoped = []
    for s in snaps:
        c = STORE.commitments.get(s["commitment_id"])
        if c is not None and c["program_id"] == prog["id"]:
            scoped.append(s)
    if quarter is None:
        if scoped:
            quarter = max(s["as_of_quarter"] for s in scoped)
        else:
            quarter = None
    buckets = {}
    if quarter is not None:
        for s in scoped:
            if s["as_of_quarter"] != quarter:
                continue
            for line in STORE.look_through_lines.values():
                if line["snapshot_id"] != s["id"]:
                    continue
                key = line[group_by]
                buckets[key] = buckets.get(key, Decimal("0")) + dec(line["exposure_amount"])
    out = [{"key": k, "exposure_amount": float(money2_dec(v))}
           for k, v in sorted(buckets.items())]
    return {
        "program_id": prog["id"],
        "as_of_quarter": quarter,
        "group_by": group_by,
        "buckets": out,
    }
