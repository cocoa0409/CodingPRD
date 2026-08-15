"""Core fund-accounting business logic.

Implements, exactly per SCAFFOLD.yaml §1.3 and PRD.md §3:
- security_price_selection (valuation hierarchy, PROVISIONAL vs FINAL_PRICED)
- nav_computation (per-position round2 before the sum)
- expense_accrual_daily (ACT_365 vs ACT_360; prior-FINAL-TNA vs own-GAV base)
- expense_cap_test_and_waiver (strictly-greater breach; ratio vs accrual base)
- the recompute cascades (price create/approve/override, break resolve/reopen,
  distribution reinvest)
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import store

TWO = Decimal("0.01")
FOUR = Decimal("0.0001")
LEVEL_ORDER = {"LEVEL_1": 1, "LEVEL_2": 2, "LEVEL_3": 3}
VARIANT_STATUSES = {
    "PROVISIONAL": ("SUBMITTED", "APPROVED"),
    "FINAL_PRICED": ("APPROVED",),
}


def D(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def round2(x):
    return D(x).quantize(TWO, rounding=ROUND_HALF_UP)


def round4(x):
    return D(x).quantize(FOUR, rounding=ROUND_HALF_UP)


def date_of(iso):
    return date(int(iso[0:4]), int(iso[5:7]), int(iso[8:10]))


def add_months(d, months):
    """Same day-of-month N months later, clamped to the target month's end."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


# ---------------------------------------------------------------- lookups

def fund_of_class(cls):
    return store.funds[cls["fund_id"]]


def class_of_position(pos):
    return store.share_classes[pos["share_class_id"]]


def open_positions(class_id):
    return [p for p in store.positions.values()
            if p["share_class_id"] == class_id and p["status"] == "OPEN"]


def classes_holding(security_id):
    """Classes holding the security in an OPEN position (valuation scope)."""
    return {p["share_class_id"] for p in store.positions.values()
            if p["security_id"] == security_id and p["status"] == "OPEN"}


def nav_at(class_id, accounting_date):
    for n in store.nav_records.values():
        if n["share_class_id"] == class_id and n["accounting_date"] == accounting_date:
            return n
    return None


def latest_nav(class_id, statuses=None):
    rows = [n for n in store.nav_records.values()
            if n["share_class_id"] == class_id
            and (statuses is None or n["status"] in statuses)]
    if not rows:
        return None
    return max(rows, key=lambda n: n["accounting_date"])


def is_latest_nav(nav):
    latest = latest_nav(nav["share_class_id"])
    return latest is not None and latest["id"] == nav["id"]


def class_accruals(class_id, accrual_date):
    return [a for a in store.expense_accruals.values()
            if a["share_class_id"] == class_id and a["accrual_date"] == accrual_date]


def prior_final_tna(class_id, before_date):
    """TNA of the class's FINAL record with greatest accounting_date strictly
    before before_date; None when no such FINAL record exists."""
    finals = [n for n in store.nav_records.values()
              if n["share_class_id"] == class_id and n["status"] == "FINAL"
              and n["accounting_date"] < before_date]
    if not finals:
        return None
    return D(max(finals, key=lambda n: n["accounting_date"])["total_net_assets"])


def day_count(fund):
    return 365 if fund["day_count_convention"] == "ACT_365" else 360


# ------------------------------------------------------- price selection

def select_price(security_id, price_date, variant):
    """Valuation-hierarchy selector. Ranking: fair-value override first, then
    lower pricing level, then latest created_at. id is never consulted."""
    statuses = VARIANT_STATUSES[variant]
    cands = [o for o in store.price_observations.values()
             if o["security_id"] == security_id
             and o["price_date"] == price_date
             and o["status"] in statuses]
    if not cands:
        return None
    cands.sort(key=lambda o: (o["created_at"], o["_seq"]), reverse=True)
    cands.sort(key=lambda o: LEVEL_ORDER[o["pricing_level"]])
    cands.sort(key=lambda o: 0 if o["is_fair_value_override"] else 1)
    return cands[0]["price"]


def compute_gav(class_id, accounting_date, variant):
    """Sum of round2(quantity x selected price) over OPEN positions.
    Returns (gross_asset_value, all_positions_priced)."""
    total = Decimal("0")
    all_priced = True
    for pos in open_positions(class_id):
        price = select_price(pos["security_id"], accounting_date, variant)
        if price is None:
            all_priced = False
            continue
        total += round2(D(pos["quantity"]) * price)
    return total, all_priced


# ------------------------------------------------------------- accruals

def accrual_amount(base, rate_bps, fund):
    return round2(D(base) * D(rate_bps) / Decimal(10000) / Decimal(day_count(fund)))


def accrual_base_for(class_id, accounting_date):
    """Prior FINAL TNA, or None when this is the class's first record (in which
    case the base is the record's own current gross_asset_value)."""
    return prior_final_tna(class_id, accounting_date)


def new_accrual(class_id, accrual_date, category, rate_bps, gav_for_base):
    """Build an ExpenseAccrual row. gav_for_base is used only when no prior
    FINAL record exists (first-record base rule)."""
    cls = store.share_classes[class_id]
    fund = fund_of_class(cls)
    prior = prior_final_tna(class_id, accrual_date)
    base = prior if prior is not None else D(gav_for_base)
    row = {
        "id": db.new_id(),
        "share_class_id": class_id,
        "accrual_date": accrual_date,
        "category": category,
        "annual_rate_bps": D(rate_bps),
        "base_net_assets": base,
        "accrued_amount": accrual_amount(base, rate_bps, fund),
        "status": "ESTIMATED",
    }
    db.new_common(row)
    store.expense_accruals[row["id"]] = row
    return row


# --------------------------------------------------------- nav recompute

def variant_of(nav):
    return "PROVISIONAL" if nav["status"] == "ESTIMATED" else "FINAL_PRICED"


def _nav_per_share(tna, shares):
    shares = D(shares)
    if shares <= 0:
        return None
    return round4(tna / shares)


def _chain_tna(cls, fund, accounting_date, variant):
    """Full what-if chain under a pricing variant: prices -> per-position
    round2 -> GAV -> accruals (base rule) -> TNA. Returns None when any held
    security lacks an eligible price under the variant."""
    gav, all_priced = compute_gav(cls["id"], accounting_date, variant)
    if not all_priced:
        return None
    rows = class_accruals(cls["id"], accounting_date)
    prior = prior_final_tna(cls["id"], accounting_date)
    if prior is None:
        total_accr = sum((accrual_amount(gav, r["annual_rate_bps"], fund)
                          for r in rows), Decimal("0"))
    else:
        total_accr = sum((D(r["accrued_amount"]) for r in rows), Decimal("0"))
    return round2(gav - total_accr)


def recompute_nav(nav, bump=True):
    """Recompute every computed field of a NavRecord under its status's pricing
    variant, refreshing the accrual rows when the first-record base rule
    applies. bump=True increments the record's version (cascade mutation)."""
    cls = store.share_classes[nav["share_class_id"]]
    fund = fund_of_class(cls)
    variant = variant_of(nav)
    nav["pricing_variant_used"] = variant

    gav, _ = compute_gav(cls["id"], nav["accounting_date"], variant)
    nav["gross_asset_value"] = gav

    rows = class_accruals(cls["id"], nav["accounting_date"])
    prior = prior_final_tna(cls["id"], nav["accounting_date"])
    if prior is None:
        # First record: the accrual base is this record's own GAV, so any
        # recompute flows through to the accrual rows themselves.
        for r in rows:
            new_amount = accrual_amount(gav, r["annual_rate_bps"], fund)
            if D(r["base_net_assets"]) != gav or D(r["accrued_amount"]) != new_amount:
                r["base_net_assets"] = gav
                r["accrued_amount"] = new_amount
                db.touch(r)
    total_accr = sum((D(r["accrued_amount"]) for r in rows
                      if r["status"] in ("ESTIMATED", "POSTED")), Decimal("0"))
    nav["expense_accrual_total"] = total_accr
    tna = round2(gav - total_accr)
    nav["total_net_assets"] = tna

    shares = D(cls["shares_outstanding"])
    nav["nav_per_share"] = _nav_per_share(tna, shares)
    prov_tna = _chain_tna(cls, fund, nav["accounting_date"], "PROVISIONAL")
    nav["provisional_nav_per_share"] = None if prov_tna is None else _nav_per_share(prov_tna, shares)
    fin_tna = _chain_tna(cls, fund, nav["accounting_date"], "FINAL_PRICED")
    nav["final_nav_per_share"] = None if fin_tna is None else _nav_per_share(fin_tna, shares)

    if bump:
        db.touch(nav)


# ----------------------------------------------------------- cap testing

def agreement_status(agreement):
    """Derived, never stored: ACTIVE while the clock date is on or before the
    agreement's last covered day, EXPIRED thereafter."""
    return "ACTIVE" if db.clock_today() <= date_of(agreement["effective_to"]) else "EXPIRED"


def recoverable_balance(agreement_id):
    """Sum of remaining_amount over the agreement's WAIVER ledger entries."""
    return sum((D(e["remaining_amount"]) for e in store.waiver_ledger_entries.values()
                if e["waiver_agreement_id"] == agreement_id
                and e["entry_type"] == "WAIVER"), Decimal("0"))


def covering_agreement(class_id, accounting_date):
    """The class's ACTIVE agreement whose closed day-interval covers the
    accounting date (at most one exists per class per day)."""
    for ag in store.waiver_agreements.values():
        if ag["share_class_id"] != class_id:
            continue
        if ag["effective_from"] <= accounting_date <= ag["effective_to"] \
                and agreement_status(ag) == "ACTIVE":
            return ag
    return None


def run_cap_test(nav):
    """Expense-cap test (PRD §3.5): ratio against the accrual base, strictly
    greater breach, waiver booked on the agreement ledger only."""
    cls = store.share_classes[nav["share_class_id"]]
    rows = class_accruals(cls["id"], nav["accounting_date"])
    if not rows:
        return
    base = D(rows[0]["base_net_assets"])  # all rows of the date share one base
    if base <= 0:
        return
    agreement = covering_agreement(cls["id"], nav["accounting_date"])
    if agreement is None:
        return
    accrued_total = D(nav["expense_accrual_total"])
    ratio = round4(accrued_total * Decimal(365) / base * Decimal(10000))
    cap = D(agreement["cap_bps"])
    if ratio <= cap:
        return  # strictly-greater breach rule: ratio == cap is NOT a breach
    waiver_amount = round2(min(accrued_total,
                               (ratio - cap) / Decimal(10000) * base / Decimal(365)))
    if waiver_amount <= 0:
        return
    entry = {
        "id": db.new_id(),
        "waiver_agreement_id": agreement["id"],
        "entry_type": "WAIVER",
        "amount": waiver_amount,
        "entry_date": nav["accounting_date"],
        "expires_at": add_months(date_of(nav["accounting_date"]),
                                 agreement["recovery_window_months"]).isoformat(),
        "remaining_amount": waiver_amount,
    }
    db.new_ledger_row(entry)
    store.waiver_ledger_entries[entry["id"]] = entry


# -------------------------------------------------------------- cascades

def recompute_estimated_for_price(security_id, price_date):
    """Price create/approve leg: recompute the ESTIMATED record (if any) of
    every class holding the security on the observation's price_date."""
    for class_id in classes_holding(security_id):
        nav = nav_at(class_id, price_date)
        if nav is not None and nav["status"] == "ESTIMATED":
            recompute_nav(nav, bump=True)


def override_cascade(security_id, price_date):
    """Fair-value override leg: FINAL latest records on price_date are forced
    to REOPENED and recomputed under FINAL_PRICED (first-record accruals
    recompute and re-run the cap test); ESTIMATED records recompute in place."""
    for class_id in classes_holding(security_id):
        nav = nav_at(class_id, price_date)
        if nav is None:
            continue
        if nav["status"] == "ESTIMATED":
            recompute_nav(nav, bump=True)
        elif nav["status"] == "FINAL" and is_latest_nav(nav):
            nav["status"] = "REOPENED"
            recompute_nav(nav, bump=False)
            if prior_final_tna(class_id, nav["accounting_date"]) is None:
                # First record: base is the record's own GAV, so the accrual
                # recomputation re-runs the expense-cap test.
                run_cap_test(nav)
            db.touch(nav)


def recompute_latest_estimated(class_id):
    """Break resolve/reopen and reinvest leg: recompute the class's latest
    ESTIMATED record, if one exists."""
    nav = latest_nav(class_id, statuses={"ESTIMATED"})
    if nav is not None:
        recompute_nav(nav, bump=True)
