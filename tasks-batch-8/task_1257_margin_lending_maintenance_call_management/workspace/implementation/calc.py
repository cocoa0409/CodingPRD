"""Calculation engine (SCAFFOLD 1.3 / PRD 3.5-3.9).

All money is integer cents; rates/thresholds are integer basis points; ratio
comparisons use cross-multiplied integer arithmetic, never floats. Rounding is
round-half-up to whole cents, applied only at the three pinned points:
per-position requirement lines, per-day interest accruals, Reg T initial.
"""
from db import store

# --- pinned constants -------------------------------------------------------
REG_T_INITIAL_BPS = 5000
REG_MAINT_LONG_BPS = 2500
REG_MAINT_SHORT_BPS = 3000
CONC_MID_CAP_BPS = 7500
CONC_MID_ADDON_BPS = 1000
CONC_HIGH_ADDON_BPS = 2000
DAY_COUNT_YEAR = 360
PDT_MIN_DAY_TRADES = 4
PDT_RATIO_NUM = 6
PDT_MIN_EQUITY_CENTS = 2500000
PDT_BP_MULTIPLIER = 4
NON_PDT_BP_MULTIPLIER = 2

CALL_DEADLINE_HOURS = {
    "FED_REG_T": 96,
    "MAINTENANCE": 72,
    "HOUSE": 48,
    "DAY_TRADE_MIN_EQUITY": 120,
}

NON_TERMINAL_CALL_STATES = ("OPEN", "DISPUTED", "EXPIRED", "LIQUIDATION_IN_PROGRESS")
NON_TERMINAL_ORDER_STATES = ("PENDING", "PARTIALLY_FILLED")


def round_half_up_div(numerator, denominator):
    """round_half_up(numerator / denominator) for integer inputs, den > 0."""
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    # symmetric half-up for negatives (not expected on pinned paths)
    return -((2 * (-numerator) + denominator) // (2 * denominator))


# --- marks ------------------------------------------------------------------
def latest_mark_price(security_id, mark_type):
    """Latest mark of the type by marked_at DESC; when several marks share a
    marked_at the most recently posted one supersedes (PRD 2.6 ordering with
    the created_at tie-break resolved by insertion sequence)."""
    best = None
    for m in store.marks.values():
        if m["security_id"] != security_id or m["mark_type"] != mark_type:
            continue
        if best is None or (m["marked_at"], m["_seq"]) >= (best["marked_at"], best["_seq"]):
            best = m
    return None if best is None else best["price_cents"]


def positions_of_account(account_id):
    return [p for p in store.positions.values() if p["account_id"] == account_id]


def account_position(account_id, security_id):
    pid = store.position_by_pair.get((account_id, security_id))
    return None if pid is None else store.positions.get(pid)


def calls_of_account(account_id):
    return [c for c in store.calls.values() if c["account_id"] == account_id]


def non_terminal_calls(account_id):
    return [c for c in calls_of_account(account_id)
            if c["call_status"] in NON_TERMINAL_CALL_STATES]


def open_calls(account_id):
    return sorted(
        (c for c in calls_of_account(account_id) if c["call_status"] == "OPEN"),
        key=lambda c: c["_seq"])


class BasisTotals:
    __slots__ = ("equity", "reg_req", "house_req", "gross_long", "gross_short")

    def __init__(self, equity, reg_req, house_req, gross_long, gross_short):
        self.equity = equity
        self.reg_req = reg_req
        self.house_req = house_req
        self.gross_long = gross_long
        self.gross_short = gross_short


def compute_basis(account, mark_type, write_mv=False):
    """Equity / maintenance requirements on one mark basis (PRD 3.5).

    equity = cash + sum(qty * price) over all position rows (qty signed).
    Per non-zero position: reg line = round_half_up(|mv| * reg_pct / 10000),
    house line = round_half_up(|mv| * max(reg_pct, house_pct) / 10000);
    house_pct = side house bps + concentration add-on (longs only).
    """
    cash = account["cash_balance_cents"]
    equity = cash
    gross_long = 0
    rows = []  # (position, mv)
    for p in positions_of_account(account["id"]):
        price = latest_mark_price(p["security_id"], mark_type)
        price = 0 if price is None else price
        mv = p["quantity"] * price
        if write_mv:
            field = "mv_realtime_cents" if mark_type == "REALTIME" else "mv_official_cents"
            p[field] = mv
        equity += mv
        if p["quantity"] > 0:
            gross_long += mv
        if p["quantity"] != 0:
            rows.append((p, mv))
    gross_short = -(equity - cash - gross_long)  # sum of |mv| over shorts

    reg_req = 0
    house_req = 0
    for p, mv in rows:
        sec = store.securities[p["security_id"]]
        abs_mv = abs(mv)
        if p["quantity"] > 0:
            reg_pct = REG_MAINT_LONG_BPS
            house_pct = sec["house_maint_long_bps"]
            # Concentration share test, cross-multiplied, strict >.
            if mv * 10000 > sec["concentration_threshold_bps"] * gross_long:
                if mv * 10000 <= CONC_MID_CAP_BPS * gross_long:
                    house_pct += CONC_MID_ADDON_BPS
                else:
                    house_pct += CONC_HIGH_ADDON_BPS
        else:
            reg_pct = REG_MAINT_SHORT_BPS
            house_pct = sec["house_maint_short_bps"]
        reg_req += round_half_up_div(abs_mv * reg_pct, 10000)
        house_req += round_half_up_div(abs_mv * max(reg_pct, house_pct), 10000)
    return BasisTotals(equity, reg_req, house_req, gross_long, gross_short)


def reg_t_initial(gross_long, gross_short):
    """Reg T initial requirement: 5000bps of gross long+short MV, round half up."""
    return round_half_up_div(REG_T_INITIAL_BPS * (gross_long + gross_short), 10000)


def compute_buying_power(account, rt):
    """buying_power_cents (PRD 3.5): PDT -> 4x excess over max(reg, house);
    else 2x excess over Reg T initial on realtime marks. Floored at zero."""
    if account["pdt_flag"]:
        excess = rt.equity - max(rt.reg_req, rt.house_req)
        return max(0, PDT_BP_MULTIPLIER * excess)
    initial_rt = reg_t_initial(rt.gross_long, rt.gross_short)
    return max(0, NON_PDT_BP_MULTIPLIER * (rt.equity - initial_rt))


def recompute_account(account, write_mv=True):
    """Refresh all computed account fields on both bases (PRD 3.5).
    This is a mutation of the account per PRD 2.7; callers decide touching."""
    rt = compute_basis(account, "REALTIME", write_mv=write_mv)
    off = compute_basis(account, "OFFICIAL_CLOSE", write_mv=write_mv)
    account["equity_realtime_cents"] = rt.equity
    account["reg_req_realtime_cents"] = rt.reg_req
    account["house_req_realtime_cents"] = rt.house_req
    account["equity_official_cents"] = off.equity
    account["reg_req_official_cents"] = off.reg_req
    account["house_req_official_cents"] = off.house_req
    account["buying_power_cents"] = compute_buying_power(account, rt)
    return rt, off


def binding_official_excess(account):
    """equity_official - max(reg_req_official, house_req_official)."""
    return account["equity_official_cents"] - max(
        account["reg_req_official_cents"], account["house_req_official_cents"])


# --- margin calls -------------------------------------------------------------
def call_cure_satisfied(call, account):
    """OPEN-call cure test (PRD 3.7): binding official maintenance excess >= 0;
    DTME cures when equity_official >= 2,500,000."""
    if call["call_type"] == "DAY_TRADE_MIN_EQUITY":
        return account["equity_official_cents"] >= PDT_MIN_EQUITY_CENTS
    return binding_official_excess(account) >= 0


def pending_call_for_account(account):
    """Most severe applicable call type + amount, or None (PRD 3.7).

    The deficiency chain picks the most severe applicable branch; if that
    branch's type already has a non-terminal call on the account, the issuance
    is skipped entirely (one non-terminal call per (account, call_type)) —
    lesser types never leapfrog a blocked branch."""
    equity = account["equity_official_cents"]
    reg_excess = equity - account["reg_req_official_cents"]
    house_excess = equity - account["house_req_official_cents"]
    off = compute_basis(account, "OFFICIAL_CLOSE")
    fed_deficiency = max(
        0, round_half_up_div(REG_T_INITIAL_BPS * off.gross_long, 10000) - equity)

    if reg_excess < 0:
        chosen = ("MAINTENANCE", max(-reg_excess, -house_excess))
    elif house_excess < 0:
        chosen = ("HOUSE", -house_excess)
    elif fed_deficiency > 0:
        chosen = ("FED_REG_T", fed_deficiency)
    elif account["pdt_flag"] and equity < PDT_MIN_EQUITY_CENTS:
        chosen = ("DAY_TRADE_MIN_EQUITY", PDT_MIN_EQUITY_CENTS - equity)
    else:
        return None

    live_types = {c["call_type"] for c in non_terminal_calls(account["id"])}
    if chosen[0] in live_types:
        return None
    return chosen


# --- interest -----------------------------------------------------------------
def select_rate_tier(debit_cents, on_date):
    """Effective tier: window covers the date (closed interval); greatest
    tier_level among those with min_balance_cents <= debit. None if none."""
    best = None
    for t in store.rate_tiers.values():
        if t["min_balance_cents"] > debit_cents:
            continue
        if t["effective_from"] > on_date:
            continue
        if t["effective_to"] is not None and t["effective_to"] < on_date:
            continue
        if best is None or t["tier_level"] > best["tier_level"]:
            best = t
    return best


def daily_accrual_amount(debit_cents, rate_bps):
    """round_half_up(debit * rate_bps / 10000 / 360), whole cents."""
    return round_half_up_div(debit_cents * rate_bps, 10000 * DAY_COUNT_YEAR)


# --- liquidation selector -------------------------------------------------------
def select_liquidation_positions(account, call):
    """Eligible: quantity != 0 and reserved_qty == 0. Rank: liquidity_tier ASC,
    |mv_official| DESC, opened_at ASC. Take whole positions in rank order until
    cumulative |mv_official| >= call_amount_cents. Returns (selected, eligible).
    """
    eligible = []
    for p in positions_of_account(account["id"]):
        if p["quantity"] == 0:
            continue
        if p["reserved_qty"] != 0:
            continue
        sec = store.securities[p["security_id"]]
        eligible.append((sec["liquidity_tier"], -abs(p["mv_official_cents"]),
                         p["opened_at"], p["_seq"], p))
    eligible.sort(key=lambda t: (t[0], t[1], t[2] or store.clock, t[3]))
    selected = []
    cumulative = 0
    for _, _, _, _, p in eligible:
        if cumulative >= call["call_amount_cents"]:
            break
        selected.append(p)
        cumulative += abs(p["mv_official_cents"])
    return selected, eligible
