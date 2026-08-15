"""Core business logic: valuations, drift assessment, trade generation,
cash waterfall, withdrawal modeling, performance returns, cascades."""
import uuid
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from calendar import monthrange

import store as db
import logical_clock as clock
from errors import ApiError

CLASS_ORDER = ["US_EQUITY", "INTL_EQUITY", "FIXED_INCOME", "CASH_EQUIVALENT",
               "ALTERNATIVES"]
PROPOSAL_TTL_DAYS = 7
AMENDMENT_QUORUM = 3
RISK_DELTA_MAX = 10
CAP_GAINS_BPS = 2000

OPEN_PROPOSAL_STATES = ("PROPOSED", "NEEDS_REVISION")
NONTERMINAL_PROPOSAL_STATES = ("PROPOSED", "NEEDS_REVISION", "APPROVED")
OPEN_WITHDRAWAL_STATES = ("SUBMITTED", "MODELED", "APPROVED")


# ---------------------------------------------------------------- helpers
def new_id():
    return str(uuid.uuid4())


def touch(e):
    e["updated_dt"] = clock.now()
    e["version"] += 1


def base_fields(e):
    return {
        "id": e["id"],
        "created_at": clock.fmt(e["created_dt"]),
        "updated_at": clock.fmt(e["updated_dt"]),
        "version": e["version"],
    }


def new_common():
    now = clock.now()
    return {"id": new_id(), "created_dt": now, "updated_dt": now,
            "version": 1, "_seq": db.next_seq()}


def rhu_frac(f):
    """Round half-up (away from zero on ties) of an exact Fraction to int."""
    f = Fraction(f)
    if f >= 0:
        return (f.numerator * 2 + f.denominator) // (2 * f.denominator)
    return -(((-f).numerator * 2 + (-f).denominator) // (2 * (-f).denominator))


def rhu_dec(d):
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_frac(f):
    f = Fraction(f)
    return -((-f.numerator) // f.denominator)


def month_add(dt, n):
    """Add n calendar months, clamping day-of-month to the target month's last day."""
    m = dt.month - 1 + n
    y = dt.year + m // 12
    m = m % 12 + 1
    d = min(dt.day, monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------- lookups
def get_or_404(table, rid):
    e = table.get(rid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return e


def resolve(table, rid, field):
    """Body-referenced FK resolution -> ERR_INVALID_REFERENCE."""
    e = table.get(rid)
    if e is None:
        raise ApiError("ERR_INVALID_REFERENCE", 422,
                       f"Referenced {field} does not resolve")
    return e


def positions_of(pf_id, positive=False):
    out = [p for p in db.positions.values() if p["portfolio_id"] == pf_id]
    if positive:
        out = [p for p in out if p["quantity"] > 0]
    out.sort(key=lambda p: p["_seq"])
    return out


def mv(p):
    return p["quantity"] * db.securities[p["security_id"]]["price_cents"]


def unrealized(p):
    return mv(p) - p["cost_basis_cents"]


def cash_balance(pf_id):
    return sum(e["amount_cents"] for e in db.events.values()
               if e["portfolio_id"] == pf_id)


def total_value(pf_id):
    return cash_balance(pf_id) + sum(mv(p) for p in positions_of(pf_id))


def active_ips_of_client(client_id):
    for i in db.ips_policies.values():
        if i["client_id"] == client_id and i["status"] == "ACTIVE":
            return i
    return None


def restriction_status(e):
    now = clock.now()
    if now < e["from_dt"]:
        return "SCHEDULED"
    if now < e["to_dt"]:
        return "ACTIVE"
    return "EXPIRED"


def is_restricted(sec_id, side):
    """True when an ACTIVE entry blocks the side (NO_TRADE blocks both,
    NO_BUY blocks BUY only)."""
    for e in db.restricted.values():
        if e["security_id"] != sec_id:
            continue
        if restriction_status(e) != "ACTIVE":
            continue
        if e["restriction_level"] == "NO_TRADE":
            return True
        if e["restriction_level"] == "NO_BUY" and side == "BUY":
            return True
    return False


def has_active_no_trade(sec_id):
    for e in db.restricted.values():
        if (e["security_id"] == sec_id
                and e["restriction_level"] == "NO_TRADE"
                and restriction_status(e) == "ACTIVE"):
            return True
    return False


# ---------------------------------------------------------------- ledger
def append_event(pf, kind, amount, occurred_dt, source_type, source_id):
    valuation_before = total_value(pf["id"])
    new_balance = cash_balance(pf["id"]) + amount
    ev = {
        "id": new_id(),
        "portfolio_id": pf["id"],
        "occurred_dt": occurred_dt,
        "kind": kind,
        "amount_cents": amount,
        "balance_after_cents": new_balance,
        "valuation_before_cents": valuation_before,
        "source_type": source_type,
        "source_id": source_id,
        "created_dt": clock.now(),
        "_seq": db.next_seq(),
    }
    db.events[ev["id"]] = ev
    return ev


# ---------------------------------------------------------------- drift
def _class_mv(pf_id, asset_class, positions):
    v = sum(mv(p) for p in positions
            if db.securities[p["security_id"]]["asset_class"] == asset_class)
    if asset_class == "CASH_EQUIVALENT":
        v += cash_balance(pf_id)
    return v


def compute_drift(pf):
    ips = active_ips_of_client(pf["client_id"])
    if ips is None:
        return "UNTRACKED"
    total = total_value(pf["id"])
    if total == 0:
        return "WITHIN_BANDS"
    tgs = [t for t in db.targets.values() if t["ips_id"] == ips["id"]]
    target_classes = {t["asset_class"] for t in tgs}
    positions = positions_of(pf["id"], positive=True)
    breached = False
    for t in tgs:
        class_mv = _class_mv(pf["id"], t["asset_class"], positions)
        actual_bps = rhu_frac(Fraction(class_mv * 10000, total))
        target_bps = rhu_dec(t["target_pct"] * 100)
        band_bps = rhu_dec(t["band_pct"] * 100)
        if abs(actual_bps - target_bps) > band_bps:  # strict >: edge is not a breach
            breached = True
    for p in positions:
        if db.securities[p["security_id"]]["asset_class"] not in target_classes:
            breached = True  # untargeted holding
    return "BREACHED" if breached else "WITHIN_BANDS"


def revert_modeled_withdrawals(pf_id):
    for w in db.withdrawals.values():
        if w["portfolio_id"] == pf_id and w["status"] == "MODELED":
            clear_model(w)
            w["status"] = "SUBMITTED"
            touch(w)


def clear_model(w):
    w["modeled_at_dt"] = None
    w["modeled_plan"] = None
    w["modeled_proceeds_cents"] = None
    w["modeled_tax_cost_cents"] = None
    w["modeled_cash_used_cents"] = None
    w["post_withdrawal_drift_status"] = None


def refresh_portfolio(pf, revert=False):
    """Recompute drift + bump version after a portfolio-affecting mutation."""
    pf["drift_status"] = compute_drift(pf)
    touch(pf)
    if revert:
        revert_modeled_withdrawals(pf["id"])


# ---------------------------------------------------------------- cascades
def cancel_open_trades(prop):
    for t in db.trades.values():
        if t["proposal_id"] == prop["id"] and t["status"] in ("PENDING", "BLOCKED"):
            t["status"] = "CANCELLED"
            touch(t)


def expire_proposal(prop):
    prop["status"] = "EXPIRED"
    cancel_open_trades(prop)
    touch(prop)


def pin_expiry_cascade(ips_id):
    """Every non-terminal proposal pinned to this IPS -> EXPIRED (+trades)."""
    for prop in db.proposals.values():
        if (prop["ips_id"] == ips_id
                and prop["status"] in NONTERMINAL_PROPOSAL_STATES):
            expire_proposal(prop)
