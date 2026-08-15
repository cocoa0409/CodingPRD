"""Business calculations: ledger replay, tiers, dividends, quorum."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

ADD_KINDS = {"DEPOSIT", "DIVIDEND_CREDIT"}
SUB_KINDS = {"WITHDRAWAL", "CLOSURE_DISBURSEMENT"}

TIER_BONUS_BPS = {"STANDARD": 0, "SELECT": 25, "PREMIER": 50}
TIER_RANK = {"STANDARD": 0, "SELECT": 1, "PREMIER": 2}

SELECT_TENURE_MONTHS = 12
SELECT_BALANCE_CENTS = 500000
PREMIER_TENURE_MONTHS = 36
PREMIER_BALANCE_CENTS = 2500000
TRAILING_WINDOW_DAYS = 90

DAYS_IN_YEAR = 365
MIN_AVG_BALANCE_FOR_DIVIDEND_CENTS = 500


# ---------------------------------------------------------------------------
# Share ledger replay
# ---------------------------------------------------------------------------

def account_txs(account_id):
    txs = [t for t in db.transactions.values() if t["share_account_id"] == account_id]
    txs.sort(key=lambda t: (t["posted_date"], t["created_at"], t["_seq"]))
    return txs


def replay_account(account):
    """Full chronological replay; rewrites running balances and balance_cents."""
    bal = 0
    for t in account_txs(account["id"]):
        if t["kind"] in ADD_KINDS:
            bal += t["amount_cents"]
        else:
            bal -= t["amount_cents"]
        t["running_balance_cents"] = bal
    account["balance_cents"] = bal


def eod_balance(account_id, day):
    """End-of-day balance: signed sum of all transactions posted on/before day."""
    day_s = day.isoformat() if isinstance(day, date) else day
    total = 0
    for t in db.transactions.values():
        if t["share_account_id"] != account_id:
            continue
        if t["posted_date"] > day_s:
            continue
        if t["kind"] in ADD_KINDS:
            total += t["amount_cents"]
        else:
            total -= t["amount_cents"]
    return total


# ---------------------------------------------------------------------------
# Tenure and tiers
# ---------------------------------------------------------------------------

def tenure_months(effective, eval_date):
    """Full calendar months from membership_effective_date to eval_date."""
    return (eval_date.year - effective.year) * 12 + (eval_date.month - effective.month) \
        - (1 if eval_date.day < effective.day else 0)


def _tier_from(tenure, balance_num, balance_den):
    """balance = balance_num / balance_den; thresholds compared exactly."""
    if tenure >= PREMIER_TENURE_MONTHS and balance_num >= PREMIER_BALANCE_CENTS * balance_den:
        return "PREMIER"
    if tenure >= SELECT_TENURE_MONTHS and balance_num >= SELECT_BALANCE_CENTS * balance_den:
        return "SELECT"
    return "STANDARD"


def member_accounts(member_id):
    return [a for a in db.accounts.values() if a["member_id"] == member_id]


def qualifying_balance_cents(member_id):
    return sum(a["balance_cents"] for a in member_accounts(member_id) if a["status"] == "OPEN")


def current_point_in_time_tier(member, eval_date):
    t = tenure_months(date.fromisoformat(member["membership_effective_date"]), eval_date)
    bal = qualifying_balance_cents(member["id"])
    return _tier_from(t, bal, 1)


def trailing_90_average_tier(member, eval_date):
    t = tenure_months(date.fromisoformat(member["membership_effective_date"]), eval_date)
    accounts = member_accounts(member["id"])
    total = 0
    start = eval_date - timedelta(days=TRAILING_WINDOW_DAYS - 1)
    for i in range(TRAILING_WINDOW_DAYS):
        day = start + timedelta(days=i)
        for acc in accounts:
            total += eod_balance(acc["id"], day)
    return _tier_from(t, total, TRAILING_WINDOW_DAYS)


# ---------------------------------------------------------------------------
# Dividends
# ---------------------------------------------------------------------------

def _window_eod_balances(account, period_start, period_end):
    """End-of-day balances over W = [max(period_start, opened_date), period_end].

    Returns None when the window is empty (start after end)."""
    start_s = max(period_start, account["opened_date"])
    start = date.fromisoformat(start_s)
    end = date.fromisoformat(period_end)
    if start > end:
        return None
    day_count = (end - start).days + 1
    balances = []
    for i in range(day_count):
        balances.append(eod_balance(account["id"], start + timedelta(days=i)))
    return balances


def compute_dividend(account, member_tier, declaration):
    """Returns (amount_cents, tier_bonus_bps) or None when the account earns
    nothing (empty window or minimum-balance gate failure)."""
    balances = _window_eod_balances(account, declaration["period_start"], declaration["period_end"])
    if balances is None:
        return None
    day_count = len(balances)
    sum_eod = sum(balances)
    # Minimum-balance gate: average end-of-day balance below 500 cents earns nothing.
    if sum_eod < MIN_AVG_BALANCE_FOR_DIVIDEND_CENTS * day_count:
        return None
    bonus = TIER_BONUS_BPS[member_tier]
    eff_bps = declaration["rate_bps"] + bonus
    if declaration["method"] == "AVERAGE_DAILY_BALANCE":
        raw = Decimal(sum_eod) * Decimal(eff_bps) / Decimal(10000) / Decimal(DAYS_IN_YEAR)
    else:  # MINIMUM_DAILY_BALANCE
        raw = Decimal(min(balances)) * Decimal(eff_bps) * Decimal(day_count) \
            / Decimal(10000) / Decimal(DAYS_IN_YEAR)
    amount = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return amount, bonus


# ---------------------------------------------------------------------------
# Meetings: reconvene chain helpers
# ---------------------------------------------------------------------------

def chain_ids(meeting):
    """The meeting plus every meeting reachable by following reconvened_from_id."""
    ids = []
    cur = meeting
    while cur is not None:
        ids.append(cur["id"])
        prev = cur.get("reconvened_from_id")
        cur = db.meetings.get(prev) if prev else None
    return ids


def chain_ballots(meeting):
    ids = set(chain_ids(meeting))
    return [b for b in db.ballots.values() if b["meeting_id"] in ids]
