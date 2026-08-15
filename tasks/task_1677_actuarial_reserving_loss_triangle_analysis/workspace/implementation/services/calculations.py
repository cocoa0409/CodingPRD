"""Actuarial calculations per PRD §2.6, §3.3–§3.9 and scaffold §1.3.

Pinned rounding discipline: every factor is rounded half-up to 4dp BEFORE it
participates in any CDF product; each CDF product is itself rounded to 4dp.
Ultimates are rounded half-up to whole cents per accident quarter before
summation. All money amounts integer cents.
"""
from decimal import Decimal

from db import db
from util import (
    dec,
    quarter_diff,
    round_4dp,
    round_int_cents,
)


# ---------------------------------------------------------------------------
# §3.3 Triangle aggregation
# ---------------------------------------------------------------------------

def aggregate_triangle(segment_id: str, basis: str, valuation_quarter: str):
    """Return (cells, large_loss_cells) lists of {accident_quarter, dev_quarter, amount_cents}.

    Bulk layer = claims with is_segregated == False at aggregation time.
    Large layer = claims with is_segregated == True.
    Only transactions with effective_quarter <= valuation_quarter contribute.
    Cells are emitted only for d <= quarterDiff(accident_quarter, valuation_quarter).
    """
    claims = [c for c in db["claims"].values() if c["segment_id"] == segment_id]
    # Organize transactions per claim, filtered to effective_quarter <= valuation_quarter.
    per_claim_txns = {}
    for txn in db["claim_transactions"].values():
        if txn["effective_quarter"] > valuation_quarter:
            continue
        per_claim_txns.setdefault(txn["claim_id"], []).append(txn)

    # Accumulate: layer -> accident_quarter -> dev -> amount
    bulk = {}
    large = {}

    for claim in claims:
        aq = quarter_of(claim["accident_date"])
        if aq > valuation_quarter:
            continue
        target = large if claim["is_segregated"] else bulk
        txns = per_claim_txns.get(claim["id"], [])
        max_dev = quarter_diff(aq, valuation_quarter)
        if max_dev < 0:
            continue
        # For each dev column d, compute cumulative amount for this claim.
        # Separate transactions into (dev_index, type, amount/case_value).
        events = []
        for t in txns:
            d = quarter_diff(aq, t["effective_quarter"])
            if d < 0:
                continue
            events.append((d, t))
        # cumulative per d
        aq_bucket = target.setdefault(aq, {})
        for d in range(0, max_dev + 1):
            paid = 0
            latest_case = None
            for dev_i, t in events:
                if dev_i > d:
                    continue
                if t["type"] == "PAYMENT":
                    paid += t["amount_cents"]
                elif t["type"] == "PAYMENT_REVERSAL":
                    paid -= t["amount_cents"]
                elif t["type"] == "CASE_RESERVE_SET":
                    # latest within window — events arrive in created_at order; keep last
                    if latest_case is None or True:
                        latest_case = t["case_value_cents"]
            amount = paid
            if basis == "INCURRED":
                amount = paid + (latest_case if latest_case is not None else 0)
            aq_bucket[d] = aq_bucket.get(d, 0) + amount

    def to_cells(layer):
        out = []
        for aq in sorted(layer.keys()):
            for d in sorted(layer[aq].keys()):
                out.append({
                    "accident_quarter": aq,
                    "dev_quarter": d,
                    "amount_cents": layer[aq][d],
                })
        return out

    return to_cells(bulk), to_cells(large)


def quarter_of(date_str: str) -> str:
    from util import quarter_of_date, parse_date
    return quarter_of_date(parse_date(date_str))


# ---------------------------------------------------------------------------
# §3.4 Development factor selection, tail, CDF
# ---------------------------------------------------------------------------

def select_factors(bulk_cells):
    """Compute selected_factors from the bulk layer's adjacent column pairs.

    Returns list of Decimals (4dp rounded half-up), index = dev age d of the
    (d, d+1) pair.
    """
    # Build lookup: aq -> {d: amount}
    by_aq = {}
    for cell in bulk_cells:
        by_aq.setdefault(cell["accident_quarter"], {})[cell["dev_quarter"]] = cell["amount_cents"]

    # Determine max d observed
    max_d = -1
    for aq, cols in by_aq.items():
        for d in cols.keys():
            if d > max_d:
                max_d = d

    factors = []
    for d in range(0, max_d):  # pair (d, d+1); need cells at both
        numer = 0
        denom = 0
        for aq, cols in by_aq.items():
            if d in cols and (d + 1) in cols:
                numer += cols[d + 1]
                denom += cols[d]
        if denom == 0 and numer == 0:
            # no eligible accident quarters at this age
            break
        # The spec says: "eligible accident quarters = those having cells at BOTH d and d+1"
        # If none, no factor for index d. We stop the array at the first gap.
        if denom == 0:
            # eligible set non-empty but denominator zero: ratio undefined.
            # Treat as no factor for this age.
            break
        raw = Decimal(numer) / Decimal(denom)
        factors.append(round_4dp(raw))
    return factors


def estimate_tail(factors):
    """Geometric mean of last 3 selected factors, 4dp; exactly 1.0000 if fewer than 3."""
    if len(factors) < 3:
        return Decimal("1.0000")
    prod = factors[-3] * factors[-2] * factors[-1]
    # Cube root via Newton or power; use Decimal ** (1/3) approximated via float for
    # the root then re-round. Better: use Decimal's own power with sufficient precision.
    # Use Decimal power on the natural log route is overkill — cube root via ** (Decimal(1)/3)
    # is supported for non-negative values in Python 3.11? Actually Decimal ** Decimal
    # with non-integer exponent uses __pow__ which requires context support. Safer: use
    # float cube root then re-decimalize with high precision.
    if prod <= 0:
        return Decimal("1.0000")
    # Newton's method on Decimal for exactness.
    x = prod
    # initial guess
    guess = Decimal(str(float(prod) ** (1.0 / 3.0)))
    three = Decimal(3)
    two = Decimal(2)
    for _ in range(40):
        guess = (two * guess + prod / (guess * guess)) / three
    return round_4dp(guess)


def cdf_at(factors, tail, age: int) -> Decimal:
    """Cumulative development factor at age d per §3.4.

    CDF(d) = round_half_up(product(F[i] for i in d..n-1) * T, 4dp)  for d < n
    CDF(d) = round_half_up(T, 4dp)                                  for d == n
    CDF(d) = 1.0000                                                 for d > n
    """
    n = len(factors)
    if age > n:
        return Decimal("1.0000")
    if age == n:
        return round_4dp(tail)
    prod = Decimal(1)
    for i in range(age, n):
        prod = prod * factors[i]
    prod = prod * tail
    return round_4dp(prod)


# ---------------------------------------------------------------------------
# §3.5 Reserve runs: chain ladder and Bornhuetter-Ferguson
# ---------------------------------------------------------------------------

def _diagonal_cells(cells, valuation_quarter):
    """Return {accident_quarter: (age_at_valuation, latest_amount)} for the diagonal."""
    out = {}
    for cell in cells:
        aq = cell["accident_quarter"]
        d_age = quarter_diff(aq, valuation_quarter)
        if cell["dev_quarter"] == d_age:
            out[aq] = (d_age, cell["amount_cents"])
    return out


def chain_ladder_ultimate(bulk_cells, large_cells, valuation_quarter, factors, tail):
    """Per scaffold §1.3 chain_ladder_ultimate.

    Returns (ultimate_cents, ibnr_cents, ultimate_by_accident_quarter).
    ultimate_by_accident_quarter is over the bulk layer only.
    """
    bulk_diag = _diagonal_cells(bulk_cells, valuation_quarter)
    large_diag = _diagonal_cells(large_cells, valuation_quarter)

    total_ultimate = 0
    total_diagonal = 0
    per_aq = []

    for aq in sorted(bulk_diag.keys()):
        age, amt = bulk_diag[aq]
        cdf = cdf_at(factors, tail, age)
        ult = round_int_cents(dec(amt) * cdf)
        total_ultimate += ult
        total_diagonal += amt
        per_aq.append({
            "accident_quarter": aq,
            "age_at_valuation": age,
            "cdf": float(cdf),
            "ultimate_cents": ult,
        })

    for aq in sorted(large_diag.keys()):
        age, amt = large_diag[aq]
        cdf = cdf_at(factors, tail, age)
        ult = round_int_cents(dec(amt) * cdf)
        total_ultimate += ult
        total_diagonal += amt

    ibnr = total_ultimate - total_diagonal
    return total_ultimate, ibnr, per_aq


def bornhuetter_ferguson_ultimate(bulk_cells, large_cells, valuation_quarter,
                                  factors, tail, earned_exposure_cents, a_priori_loss_ratio):
    """Per scaffold §1.3 bornhuetter_ferguson_ultimate."""
    bulk_diag = _diagonal_cells(bulk_cells, valuation_quarter)
    large_diag = _diagonal_cells(large_cells, valuation_quarter)

    exposure = dec(earned_exposure_cents)
    ratio = dec(a_priori_loss_ratio)

    total_ultimate = 0
    total_diagonal = 0
    per_aq = []

    for aq in sorted(bulk_diag.keys()):
        age, amt = bulk_diag[aq]
        cdf = cdf_at(factors, tail, age)
        # BF: cell + exposure * ratio * (1 - 1/CDF)
        if cdf == 0:
            # degenerate; treat 1/CDF as 0
            unpaid_frac = Decimal(0)
        else:
            unpaid_frac = Decimal(1) - (Decimal(1) / cdf)
        raw = dec(amt) + exposure * ratio * unpaid_frac
        ult = round_int_cents(raw)
        total_ultimate += ult
        total_diagonal += amt
        per_aq.append({
            "accident_quarter": aq,
            "age_at_valuation": age,
            "cdf": float(cdf),
            "ultimate_cents": ult,
        })

    # Large layer pinned to chain-ladder ultimate of the large layer.
    for aq in sorted(large_diag.keys()):
        age, amt = large_diag[aq]
        cdf = cdf_at(factors, tail, age)
        ult = round_int_cents(dec(amt) * cdf)
        total_ultimate += ult
        total_diagonal += amt

    ibnr = total_ultimate - total_diagonal
    return total_ultimate, ibnr, per_aq


def reserve_range(ibnr_cents):
    """range_low = round_half_up(ibnr * 0.75); range_high = round_half_up(ibnr * 1.50)."""
    low = round_int_cents(dec(ibnr_cents) * dec("0.75"))
    high = round_int_cents(dec(ibnr_cents) * dec("1.50"))
    return low, high


# ---------------------------------------------------------------------------
# §3.6 Case reserve adequacy (computed on claim read)
# ---------------------------------------------------------------------------

def latest_nonstale_paid_triangle(segment_id):
    """The segment's non-stale PAID triangle with the greatest valuation_quarter, or None."""
    candidates = [
        t for t in db["triangles"].values()
        if t["segment_id"] == segment_id and t["basis"] == "PAID" and not t["is_stale"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda t: t["valuation_quarter"])
    return candidates[-1]


def covering_selected_pattern(segment_id, basis, valuation_quarter):
    """SELECTED pattern of (segment, basis) whose half-open window covers valuation_quarter."""
    for p in db["development_patterns"].values():
        if p["segment_id"] != segment_id:
            continue
        if p["basis"] != basis:
            continue
        if p["status"] != "SELECTED":
            continue
        if p["effective_from_quarter"] <= valuation_quarter < p["effective_to_quarter"]:
            return p
    return None


def claim_adequacy(claim, segment):
    """Return (adequacy_ratio_development, adequacy_ratio_benchmark), each Decimal or None."""
    if claim["status"] == "CLOSED":
        return None, None

    tri = latest_nonstale_paid_triangle(claim["segment_id"])
    if tri is None:
        return None, None
    v = tri["valuation_quarter"]
    pattern = covering_selected_pattern(claim["segment_id"], "PAID", v)
    if pattern is None:
        return None, None

    factors = [dec(f) for f in pattern["selected_factors"]]
    tail = dec(pattern["tail_factor"])
    aq = quarter_of(claim["accident_date"])
    d = quarter_diff(aq, v)
    cdf = cdf_at(factors, tail, d)
    indicated_outstanding = dec(claim["paid_to_date_cents"]) * (cdf - Decimal(1))
    if indicated_outstanding == 0:
        ard = None
    else:
        ard = round_4dp(dec(claim["case_outstanding_cents"]) / indicated_outstanding)

    bench = segment.get("benchmark_open_severity_cents", 0)
    if bench == 0:
        arb = None
    else:
        arb = round_4dp(dec(claim["case_outstanding_cents"]) / dec(bench))

    return ard, arb


# ---------------------------------------------------------------------------
# §3.7 Study matched run + reconciliation variance
# ---------------------------------------------------------------------------

def matched_run_for_study(study):
    """The unique non-stale run matching (segment, valuation_quarter, selected_method, selected_basis)."""
    for r in db["reserve_runs"].values():
        if r["segment_id"] != study["segment_id"]:
            continue
        if r["valuation_quarter"] != study["valuation_quarter"]:
            continue
        if r["method"] != study["selected_method"]:
            continue
        if r["basis"] != study["selected_basis"]:
            continue
        if r["is_stale"]:
            continue
        return r
    return None


def any_run_for_study(study):
    """Any run (stale or not) matching the study's selector; used for ERR_RUN_STALE detection."""
    for r in db["reserve_runs"].values():
        if r["segment_id"] != study["segment_id"]:
            continue
        if r["valuation_quarter"] != study["valuation_quarter"]:
            continue
        if r["method"] != study["selected_method"]:
            continue
        if r["basis"] != study["selected_basis"]:
            continue
        return r
    return None


def reconciliation_variance_pct(study):
    """abs(ult_CL - ult_BF) / mean, over latest non-stale runs of each method on selected_basis."""
    cl = None
    bf = None
    for r in db["reserve_runs"].values():
        if r["segment_id"] != study["segment_id"]:
            continue
        if r["valuation_quarter"] != study["valuation_quarter"]:
            continue
        if r["basis"] != study["selected_basis"]:
            continue
        if r["is_stale"]:
            continue
        if r["method"] == "CHAIN_LADDER":
            cl = r
        elif r["method"] == "BORNHUETTER_FERGUSON":
            bf = r
    if cl is None or bf is None:
        return None
    diff = abs(dec(cl["ultimate_cents"]) - dec(bf["ultimate_cents"]))
    mean = (dec(cl["ultimate_cents"]) + dec(bf["ultimate_cents"])) / Decimal(2)
    if mean == 0:
        return None
    return round_4dp(diff / mean)


# ---------------------------------------------------------------------------
# §3.9 Roll-forward actual-vs-expected
# ---------------------------------------------------------------------------

def compute_expected_emergence(prior_run, pattern):
    """Sum over prior run's ultimate_by_accident_quarter of
    round_half_up(ultimate * (1/CDF(age+1) - 1/CDF(age)), 0dp)."""
    factors = [dec(f) for f in pattern["selected_factors"]]
    tail = dec(pattern["tail_factor"])
    total = 0
    for entry in prior_run["ultimate_by_accident_quarter"]:
        age = entry["age_at_valuation"]
        ult = dec(entry["ultimate_cents"])
        cdf_age = cdf_at(factors, tail, age)
        cdf_next = cdf_at(factors, tail, age + 1)
        inv_age = (Decimal(1) / cdf_age) if cdf_age != 0 else Decimal(0)
        inv_next = (Decimal(1) / cdf_next) if cdf_next != 0 else Decimal(0)
        contrib = round_int_cents(ult * (inv_next - inv_age))
        total += contrib
    return total


def compute_actual_emergence_paid(segment_id, valuation_quarter):
    """Net PAYMENT minus PAYMENT_REVERSAL over non-segregated claims with effective_quarter == valuation_quarter."""
    total = 0
    for txn in db["claim_transactions"].values():
        if txn["effective_quarter"] != valuation_quarter:
            continue
        claim = db["claims"].get(txn["claim_id"])
        if claim is None or claim["segment_id"] != segment_id:
            continue
        if claim["is_segregated"]:
            continue
        if txn["type"] == "PAYMENT":
            total += txn["amount_cents"]
        elif txn["type"] == "PAYMENT_REVERSAL":
            total -= txn["amount_cents"]
    return total


def _incurred_as_of(claim, txns, as_of_quarter):
    """Aggregate incurred for a claim measured as of end of the given quarter."""
    aq = quarter_of(claim["accident_date"])
    paid = 0
    latest_case = 0
    # Sort by created_at/seq for "latest" semantics
    sorted_txns = sorted(txns, key=lambda t: t.get("_seq", 0))
    for t in sorted_txns:
        if t["effective_quarter"] > as_of_quarter:
            continue
        if t["type"] == "PAYMENT":
            paid += t["amount_cents"]
        elif t["type"] == "PAYMENT_REVERSAL":
            paid -= t["amount_cents"]
        elif t["type"] == "CASE_RESERVE_SET":
            latest_case = t["case_value_cents"]
    return paid + latest_case


def compute_actual_emergence_incurred(segment_id, valuation_quarter, prior_quarter):
    """Incurred at end of Q minus incurred at end of Q-1, over non-segregated claims
    with accident_quarter <= prior_quarter."""
    total = 0
    for claim in db["claims"].values():
        if claim["segment_id"] != segment_id:
            continue
        if claim["is_segregated"]:
            continue
        aq = quarter_of(claim["accident_date"])
        if aq > prior_quarter:
            continue
        txns = [t for t in db["claim_transactions"].values() if t["claim_id"] == claim["id"]]
        at_q = _incurred_as_of(claim, txns, valuation_quarter)
        at_qm1 = _incurred_as_of(claim, txns, prior_quarter)
        total += (at_q - at_qm1)
    return total
