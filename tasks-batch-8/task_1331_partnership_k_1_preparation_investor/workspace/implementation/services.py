"""Business logic: ledger replay, proration, allocation engine, cascades, serializers."""
from datetime import date, timedelta
from fractions import Fraction

from db import db, now, new_entity, touch, fmt_ts
from util import parse_date, rhu, sort_created

POSITIVE_EVENTS = {"CONTRIBUTION", "TRANSFER_IN", "ALLOCATION_SHARE", "ADJUSTMENT"}
NEGATIVE_EVENTS = {"DISTRIBUTION", "TRANSFER_OUT"}

EVENT_TYPES = POSITIVE_EVENTS | NEGATIVE_EVENTS
PARTNER_TYPES = {"US_INDIVIDUAL", "US_ENTITY", "TAX_EXEMPT", "FOREIGN_INDIVIDUAL", "FOREIGN_ENTITY"}
PARTNER_CLASSES = {"GENERAL", "LIMITED"}
FOREIGN_TYPES = {"FOREIGN_INDIVIDUAL", "FOREIGN_ENTITY"}
RUN_KINDS = {"PROVISIONAL", "FINAL"}
SA_CATEGORIES = {"ORDINARY", "CAPITAL_GAIN", "INTEREST"}
DELIVERY_METHODS = {"PORTAL", "MAIL", "EMAIL"}
AMENDMENT_REASONS = {"ALLOCATION_CHANGE", "PARTNER_DATA_FIX", "STATE_REAPPORTIONMENT", "LATE_K1_CORRECTION"}
TICKET_CATEGORIES = {"ALLOCATION_QUESTION", "WITHHOLDING_QUESTION", "DELIVERY_ISSUE", "AMENDED_K1_QUESTION", "STATE_FILING_QUESTION"}
WH_METHODS = {"SAFE_HARBOR", "CURRENT_ACTUAL"}

SAFE_HARBOR_MULTIPLIER_BPS = 11000
PENALTY_MONTHLY_BPS = 500
PENALTY_CAP_MONTHS = 5


# ---------------------------------------------------------------------------
# Ledger replay
# ---------------------------------------------------------------------------

def partner_events(partner_id):
    evs = [e for e in db.capital_events.values() if e["partner_id"] == partner_id]
    evs.sort(key=lambda e: (e["effective_date"], e["sequence_no"]))
    return evs


def replay_balances(partner_id):
    """Full chronological replay of the partner's append-only event stream.

    Returns (book_capital, tax_basis, excess_distribution_gain).
    """
    evs = partner_events(partner_id)
    book = 0
    for e in evs:
        sign = 1 if e["event_type"] in POSITIVE_EVENTS else -1
        book += sign * e["amount_cents"]
    basis = 0
    excess = 0
    for e in evs:
        t = e["event_type"]
        amt = e["amount_cents"]
        if t == "ADJUSTMENT":
            continue  # book-only 704(b) revaluations
        if t in POSITIVE_EVENTS:
            basis += amt
        else:
            if amt <= basis:
                basis -= amt
            else:
                excess += amt - basis
                basis = 0
    return book, basis, excess


def refresh_partner_balances(partner):
    book, basis, excess = replay_balances(partner["id"])
    partner["capital_account_balance_cents"] = book
    partner["tax_basis_cents"] = basis
    partner["excess_distribution_gain_cents"] = excess


def book_balance_at(partner_id, upto_date):
    """Book capital over events with effective_date <= upto_date (all types)."""
    total = 0
    for e in partner_events(partner_id):
        if parse_date(e["effective_date"]) <= upto_date:
            sign = 1 if e["event_type"] in POSITIVE_EVENTS else -1
            total += sign * e["amount_cents"]
    return total


def beginning_capital(partner_id, year):
    """Book replay over events effective on/before Jan 1 of year, excluding ALLOCATION_SHARE."""
    cutoff = date(year, 1, 1)
    total = 0
    for e in partner_events(partner_id):
        if e["event_type"] == "ALLOCATION_SHARE":
            continue
        if parse_date(e["effective_date"]) <= cutoff:
            sign = 1 if e["event_type"] in POSITIVE_EVENTS else -1
            total += sign * e["amount_cents"]
    return total


def ownership_at_date(partner, d):
    """Ownership in effect on date d (settled transfers with effective_date <= d)."""
    own = partner["ownership_pct_bps"]
    if parse_date(partner["admission_date"]) > d:
        own = 0
    for t in db.transfers.values():
        if t["status"] != "SETTLED":
            continue
        if parse_date(t["effective_date"]) > d:
            continue
        if t["transferor_partner_id"] == partner["id"]:
            own -= t["pct_bps"]
        elif t["transferee_partner_id"] == partner["id"]:
            own += t["pct_bps"]
    return own


def current_ownership(partner):
    return ownership_at_date(partner, now().date())


# ---------------------------------------------------------------------------
# Proration
# ---------------------------------------------------------------------------

def proration_weights(fund_id, year, partners):
    """Day-weighted ownership Fraction(bps-days/365) per partner id."""
    ystart = date(year, 1, 1)
    yend = date(year, 12, 31)
    transfers = sorted(
        [t for t in db.transfers.values()
         if t["fund_id"] == fund_id and t["status"] == "SETTLED"
         and ystart <= parse_date(t["effective_date"]) <= yend],
        key=lambda t: (t["effective_date"], t["created_at"], t["_seq"]),
    )
    weights = {}
    for p in partners:
        adm = parse_date(p["admission_date"])
        pct = p["ownership_pct_bps"] if adm <= ystart else 0
        changes = []  # (date, ('set'|'delta', value), tiebreak)
        if ystart < adm <= yend:
            changes.append((adm, "set", p["ownership_pct_bps"], date.min, 0))
        for t in transfers:
            d = parse_date(t["effective_date"])
            if t["transferor_partner_id"] == p["id"]:
                changes.append((d, "delta", -t["pct_bps"], parse_date(t["created_at"].split("T")[0]) if False else t["created_at"], t["_seq"]))
            elif t["transferee_partner_id"] == p["id"]:
                changes.append((d, "delta", t["pct_bps"], t["created_at"], t["_seq"]))
        # order: date asc, then transfer created_at/seq; admission 'set' applies before transfers on same date
        changes.sort(key=lambda c: (c[0], 0 if c[1] == "set" else 1, c[3], c[4]))
        weighted = 0
        cur = ystart
        for d, kind, val, _ca, _sq in changes:
            if d > cur:
                weighted += pct * (d - cur).days
                cur = d
            pct = val if kind == "set" else pct + val
        weighted += pct * ((yend - cur).days + 1)
        weights[p["id"]] = Fraction(weighted, 365)
    return weights


# ---------------------------------------------------------------------------
# Allocation engine
# ---------------------------------------------------------------------------

def split_pool(pool_cents, weights, pmap):
    """Split integer pool by exact-rational weights, round half-up per partner,
    residual cents to the partner with the largest unrounded share
    (tie: admission_date ASC, then created_at ASC). Sums exactly to pool."""
    if not weights:
        return {}
    total_w = sum(weights.values(), Fraction(0))
    if total_w <= 0:
        weights = {pid: Fraction(1) for pid in weights}
        total_w = Fraction(len(weights))
    unrounded = {pid: Fraction(pool_cents) * wt / total_w for pid, wt in weights.items()}
    rounded = {pid: rhu(u) for pid, u in unrounded.items()}
    residual = pool_cents - sum(rounded.values())
    if residual != 0:
        def key(pid):
            p = pmap[pid]
            return (unrounded[pid], -parse_date(p["admission_date"]).toordinal(), -p["_seq"])
        best = max(unrounded.keys(), key=key)
        rounded[best] += residual
    return rounded


def window_intersects_year(sa, year):
    """Half-open [effective_from, effective_to) intersects calendar year."""
    start = date(year, 1, 1)
    end = date(year + 1, 1, 1)
    return parse_date(sa["effective_from"]) < end and parse_date(sa["effective_to"]) > start


def compute_allocation(tax_year, run_kind):
    """Compute category totals and per-partner lines. Returns
    (totals dict, amounts {pid: {cat: cents}}, mechanisms {pid: {cat: mech}}, participants)."""
    fund = db.funds[tax_year["fund_id"]]
    year = tax_year["year"]
    participants = sort_created([p for p in db.partners.values()
                                 if p["fund_id"] == fund["id"] and p["status"] == "ACTIVE"])
    if run_kind == "PROVISIONAL":
        clock_date = now().date()
        doy = (clock_date - date(clock_date.year, 1, 1)).days + 1
        doy = min(max(doy, 1), 365)
        totals = {
            "ORDINARY": rhu(Fraction(tax_year["net_ordinary_income_cents"] * 365, doy)),
            "CAPITAL_GAIN": rhu(Fraction(tax_year["capital_gain_cents"] * 365, doy)),
            "INTEREST": rhu(Fraction(tax_year["interest_income_cents"] * 365, doy)),
        }
    else:
        totals = {
            "ORDINARY": tax_year["net_ordinary_income_cents"],
            "CAPITAL_GAIN": tax_year["capital_gain_cents"],
            "INTEREST": tax_year["interest_income_cents"],
        }

    w = proration_weights(fund["id"], year, participants)
    pmap = {p["id"]: p for p in participants}
    amounts = {p["id"]: {} for p in participants}
    mechs = {p["id"]: {} for p in participants}

    # --- ORDINARY and INTEREST: special tier then pro-rata tier ---
    for cat in ("ORDINARY", "INTEREST"):
        total = totals[cat]
        special_assign = {}
        if run_kind == "FINAL":
            sas = sorted(
                [sa for sa in db.special_allocations.values()
                 if sa["tax_year_id"] == tax_year["id"] and sa["status"] == "APPROVED"
                 and sa["category"] == cat and sa["partner_id"] in amounts
                 and window_intersects_year(sa, year)],
                key=lambda s: (s["created_at"], s["_seq"]),
            )
            for sa in sas:
                amt = rhu(Fraction(total) * sa["target_pct_bps"] / 10000)
                special_assign[sa["partner_id"]] = special_assign.get(sa["partner_id"], 0) + amt
        pool = total - sum(special_assign.values())
        non_special = [p for p in participants if p["id"] not in special_assign]
        pro = split_pool(pool, {p["id"]: w[p["id"]] for p in non_special}, pmap)
        for p in participants:
            pid = p["id"]
            if pid in special_assign:
                amounts[pid][cat] = special_assign[pid]
                mechs[pid][cat] = "SPECIAL"
            else:
                amounts[pid][cat] = pro.get(pid, 0)
                mechs[pid][cat] = "PRO_RATA"

    # --- CAPITAL_GAIN: waterfall (specials never apply) ---
    total = totals["CAPITAL_GAIN"]
    limited = [p for p in participants if p["partner_class"] == "LIMITED"]
    general = [p for p in participants if p["partner_class"] == "GENERAL"]
    need = {p["id"]: Fraction(fund["waterfall_hurdle_rate_bps"]) * beginning_capital(p["id"], year) / 10000
            for p in limited}
    sum_need = sum(need.values(), Fraction(0))
    if sum_need > 0 and total > 0:
        if sum_need <= total:
            pref_pool = rhu(sum_need)
        else:
            pref_pool = total
        pref_map = split_pool(pref_pool, {pid: need[pid] for pid in need}, pmap)
    else:
        pref_pool = 0
        pref_map = {}
    catchup_cap = rhu(Fraction(pref_pool) * fund["waterfall_catchup_bps"] / 10000)
    catchup_pool = min(total - pref_pool, catchup_cap)
    if catchup_pool < 0:
        catchup_pool = 0
    if general and catchup_pool != 0:
        catchup_map = split_pool(catchup_pool, {p["id"]: w[p["id"]] for p in general}, pmap)
        catchup_used = catchup_pool
    elif general:
        catchup_map = split_pool(0, {p["id"]: w[p["id"]] for p in general}, pmap)
        catchup_used = 0
    else:
        catchup_map = {}
        catchup_used = 0
    rem = total - pref_pool - catchup_used
    if limited and general:
        lp_pool = rhu(Fraction(rem) * (10000 - fund["waterfall_carry_bps"]) / 10000)
        gp_pool = rem - lp_pool
    elif limited:
        lp_pool, gp_pool = rem, 0
    elif general:
        lp_pool, gp_pool = 0, rem
    else:
        lp_pool = gp_pool = 0
    lp_map = split_pool(lp_pool, {p["id"]: w[p["id"]] for p in limited}, pmap)
    gp_map = split_pool(gp_pool, {p["id"]: w[p["id"]] for p in general}, pmap)
    for p in participants:
        pid = p["id"]
        c_pref = pref_map.get(pid, 0)
        c_catch = catchup_map.get(pid, 0)
        c_res = lp_map.get(pid, 0) + gp_map.get(pid, 0)
        amounts[pid]["CAPITAL_GAIN"] = c_pref + c_catch + c_res
        cand = (("PREFERRED", c_pref, 0), ("CATCHUP", c_catch, 1), ("RESIDUAL", c_res, 2))
        mechs[pid]["CAPITAL_GAIN"] = max(cand, key=lambda kv: (abs(kv[1]), kv[2]))[0]

    return totals, amounts, mechs, participants


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def locked_final_run(tax_year_id):
    """Latest LOCKED FINAL run for the tax year, or None."""
    runs = [r for r in db.allocation_runs.values()
            if r["tax_year_id"] == tax_year_id and r["status"] == "LOCKED" and r["run_kind"] == "FINAL"]
    if not runs:
        return None
    return max(runs, key=lambda r: r["run_seq"])


def stale_final_run(tax_year_id):
    runs = [r for r in db.allocation_runs.values()
            if r["tax_year_id"] == tax_year_id and r["status"] == "STALE" and r["run_kind"] == "FINAL"]
    if not runs:
        return None
    return max(runs, key=lambda r: r["run_seq"])


def run_lines(run_id):
    return sort_created([l for l in db.allocation_lines.values() if l["run_id"] == run_id])


def partner_line_total(run_id, partner_id):
    return sum(l["amount_cents"] for l in db.allocation_lines.values()
               if l["run_id"] == run_id and l["partner_id"] == partner_id)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def mark_locked_runs_stale(tax_year_id):
    """Every LOCKED run of the tax year -> STALE; K1 REVIEWED/APPROVED -> GENERATED."""
    for run in db.allocation_runs.values():
        if run["tax_year_id"] == tax_year_id and run["status"] == "LOCKED":
            run["status"] = "STALE"
            touch(run)
            for k1 in db.k1_packages.values():
                if k1["run_id"] == run["id"] and k1["prep_status"] in ("REVIEWED", "APPROVED"):
                    k1["prep_status"] = "GENERATED"
                    touch(k1)


def make_capital_event(partner_id, tax_year_id, event_type, amount_cents, effective_date, memo=None,
                       reverses_event_id=None):
    ev = new_entity()
    ev.update({
        "partner_id": partner_id,
        "tax_year_id": tax_year_id,
        "event_type": event_type,
        "amount_cents": amount_cents,
        "effective_date": effective_date,
        "memo": memo,
        "reverses_event_id": reverses_event_id,
        "sequence_no": 1 + max([e["sequence_no"] for e in db.capital_events.values()
                                if e["partner_id"] == partner_id] or [0]),
        "status": "POSTED",
    })
    db.capital_events[ev["id"]] = ev
    return ev


def post_allocation_share_events(run):
    """Lock side effect: one ALLOCATION_SHARE event per allocated partner."""
    tax_year = db.tax_years[run["tax_year_id"]]
    sums = {}
    order = []
    for line in run_lines(run["id"]):
        pid = line["partner_id"]
        if pid not in sums:
            sums[pid] = 0
            order.append(pid)
        sums[pid] += line["amount_cents"]
    eff = "%d-12-31" % tax_year["year"]
    for pid in order:
        make_capital_event(pid, tax_year["id"], "ALLOCATION_SHARE", sums[pid], eff, memo=run["id"])
        partner = db.partners[pid]
        refresh_partner_balances(partner)
        touch(partner)


def maybe_complete_tax_year(tax_year):
    """Bubble-up: APPROVED -> COMPLETED when every non-SUPERSEDED package is DELIVERED."""
    if tax_year["status"] != "APPROVED":
        return
    pkgs = [k for k in db.k1_packages.values()
            if k["tax_year_id"] == tax_year["id"] and k["prep_status"] != "SUPERSEDED"]
    if pkgs and all(k["prep_status"] == "DELIVERED" for k in pkgs):
        tax_year["status"] = "COMPLETED"
        touch(tax_year)


def recompute_composite_filing(cf):
    """composite_tax: per-partner rounding then sum. Totals 0 when no LOCKED FINAL run."""
    tax_year = db.tax_years[cf["tax_year_id"]]
    run = locked_final_run(tax_year["id"])
    if run is None:
        cf["included_partner_ids"] = []
        cf["total_state_source_income_cents"] = 0
        cf["total_composite_tax_cents"] = 0
        return
    alloc = {}
    for line in run_lines(run["id"]):
        alloc[line["partner_id"]] = alloc.get(line["partner_id"], 0) + line["amount_cents"]
    partners = sort_created([p for p in db.partners.values()
                             if p["fund_id"] == tax_year["fund_id"] and p["status"] == "ACTIVE"])
    included = []
    tot_income = 0
    tot_tax = 0
    for p in partners:
        if p["is_foreign"]:
            continue
        if p["residency_state"] == cf["state_code"]:
            continue
        ssi = rhu(Fraction(alloc.get(p["id"], 0)) * cf["apportionment_pct_bps"] / 10000)
        if ssi < cf["min_income_cents"]:
            continue
        tax = rhu(Fraction(ssi) * cf["composite_rate_bps"] / 10000)
        included.append(p["id"])
        tot_income += ssi
        tot_tax += tax
    cf["included_partner_ids"] = included
    cf["total_state_source_income_cents"] = tot_income
    cf["total_composite_tax_cents"] = tot_tax


def accrue_withholding_record(partner, tax_year, quarter, method):
    """Create one WithholdingRecord per foreign_withholding rules."""
    rate = 3700 if partner["partner_type"] == "FOREIGN_INDIVIDUAL" else 2100
    if method == "CURRENT_ACTUAL":
        run = locked_final_run(tax_year["id"])
        annual = partner_line_total(run["id"], partner["id"]) if run else 0
        qbase = annual // 4 if quarter < 4 else annual - 3 * (annual // 4)
        accrued = rhu(Fraction(qbase) * rate / 10000)
        annual_ecti = annual
    else:  # SAFE_HARBOR
        prior_year = None
        for ty in db.tax_years.values():
            if ty["fund_id"] == tax_year["fund_id"] and ty["year"] == tax_year["year"] - 1:
                prior_year = ty
                break
        prior_total = 0
        if prior_year is not None:
            prior_total = sum(wr["accrued_cents"] for wr in db.withholding_records.values()
                              if wr["partner_id"] == partner["id"] and wr["tax_year_id"] == prior_year["id"])
        accrued = rhu(Fraction(prior_total) * SAFE_HARBOR_MULTIPLIER_BPS / 10000 / 4)
        annual_ecti = prior_total
    due_map = {1: "04-15", 2: "06-15", 3: "09-15", 4: "12-15"}
    wr = new_entity()
    wr.update({
        "partner_id": partner["id"],
        "tax_year_id": tax_year["id"],
        "quarter": quarter,
        "method": method,
        "annual_ecti_cents": annual_ecti,
        "rate_bps": rate,
        "accrued_cents": accrued,
        "remitted_cents": 0,
        "due_date": "%d-%s" % (tax_year["year"], due_map[quarter]),
        "penalty_cents": 0,
        "status": "ACCRUED",
    })
    db.withholding_records[wr["id"]] = wr
    return wr


def k1_snapshot(partner, tax_year, run):
    """line_snapshot frozen from the locked run and capital replay."""
    lines = {l["category"]: l["amount_cents"] for l in run_lines(run["id"]) if l["partner_id"] == partner["id"]}
    year = tax_year["year"]
    return {
        "ordinary_cents": lines.get("ORDINARY", 0),
        "capital_gain_cents": lines.get("CAPITAL_GAIN", 0),
        "interest_cents": lines.get("INTEREST", 0),
        "capital_beginning_cents": book_balance_at(partner["id"], date(year, 1, 1)),
        "capital_ending_cents": book_balance_at(partner["id"], date(year, 12, 31)),
    }


def k1_deadline(tax_year):
    suffix = "09-15" if tax_year["federal_extension_filed"] else "03-15"
    return "%d-%sT23:59:59Z" % (tax_year["year"] + 1, suffix)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def pub(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def serialize_fund(f):
    return pub(f)


def serialize_tax_year(ty):
    out = pub(ty)
    out["k1_delivery_deadline"] = k1_deadline(ty)
    return out


def serialize_partner(p):
    out = pub(p)
    out["current_ownership_pct_bps"] = current_ownership(p)
    return out


def serialize_event(e):
    return pub(e)


def serialize_transfer(t):
    return pub(t)


def serialize_run(r):
    return pub(r)


def serialize_line(l):
    return pub(l)


def serialize_sa(sa):
    return pub(sa)


def serialize_cf(cf):
    return pub(cf)


def serialize_wr(wr):
    return pub(wr)


def serialize_k1(k):
    out = pub(k)
    tax_year = db.tax_years.get(k["tax_year_id"])
    if k.get("delivered_at") and tax_year is not None:
        from util import parse_datetime
        out["is_late"] = parse_datetime(k["delivered_at"]) > parse_datetime(k1_deadline(tax_year))
    else:
        out["is_late"] = False
    return out


def serialize_amendment(a):
    return pub(a)


def serialize_ticket(t):
    out = pub(t)
    from util import parse_datetime
    out["is_escalated"] = bool(t["status"] in ("OPEN", "REOPENED") and now() > parse_datetime(t["due_at"]))
    return out
