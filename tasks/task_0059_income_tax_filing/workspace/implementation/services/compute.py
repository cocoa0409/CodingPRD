"""Tax computation engine. All money is integer cents.

Where a calculation introduces a fraction, the result is floored (round down)
to the nearest cent unless a specific computation pins a different order.
"""
from db import db, now_iso, touch
from util import parse_iso

# --- Constants -------------------------------------------------------------

STANDARD_DEDUCTION = {
    "SINGLE": 1500000,
    "MARRIED_JOINT": 3000000,
    "MARRIED_SEPARATE": 1500000,
    "HEAD_OF_HOUSEHOLD": 2250000,
}

# Marginal brackets: list of (upper_threshold_cents_or_None, rate_pct).
# SINGLE / MARRIED_SEPARATE / HEAD_OF_HOUSEHOLD share the SINGLE structure.
BRACKETS_SINGLE = [(1160000, 10), (4715000, 12), (None, 22)]
BRACKETS_MARRIED_JOINT = [(2320000, 10), (9430000, 12), (None, 22)]

CTC_PER_CHILD = 200000
AOTC_PER_STUDENT = 250000
AOTC_PHASEOUT_START = 8000000
AOTC_PHASEOUT_END = 9000000
EITC_PHASEOUT_START = 2000000
EITC_PHASEOUT_RATE_PCT = 21
EITC_MAX = {0: 60000, 1: 396000, 2: 655000}

CAPITAL_LOSS_LIMIT = 300000

HIGH_INCOME_AGI = 15000000
PENALTY_RATE_PCT = 8
QUARTER_DUE_DATES = {
    "Q1": "2025-04-15T23:59:59Z",
    "Q2": "2025-06-16T23:59:59Z",
    "Q3": "2025-09-15T23:59:59Z",
    "Q4": "2026-01-15T23:59:59Z",
}


def floor_pct(amount, pct):
    """floor(amount * pct / 100) for non-negative amount (round down)."""
    return amount * pct // 100


def _brackets_for(filing_status):
    if filing_status == "MARRIED_JOINT":
        return BRACKETS_MARRIED_JOINT
    return BRACKETS_SINGLE


def bracket_tax(taxable, filing_status):
    """Marginal tiered tax; each tier's tax floored to the cent BEFORE summing."""
    if taxable <= 0:
        return 0
    brackets = _brackets_for(filing_status)
    total = 0
    lower = 0
    for upper, rate in brackets:
        if upper is None:
            span = taxable - lower
        else:
            span = min(taxable, upper) - lower
        if span > 0:
            # tier tax = span * rate / 100, floored
            total += span * rate // 100
        if upper is not None and taxable <= upper:
            break
        lower = upper if upper is not None else lower
    return total


# --- Child accessors -------------------------------------------------------

def _docs(return_id):
    return [d for d in db.income_documents.values() if d["return_id"] == return_id]


def _schedules(return_id):
    return [s for s in db.schedules.values() if s["return_id"] == return_id]


def _dependents(return_id):
    return [d for d in db.dependents.values() if d["return_id"] == return_id]


def _claims(return_id):
    return [c for c in db.credit_claims.values() if c["return_id"] == return_id]


def _payments(return_id):
    return [p for p in db.estimated_tax_payments.values() if p["return_id"] == return_id]


def _schedule_of(return_id, stype):
    for s in db.schedules.values():
        if s["return_id"] == return_id and s["schedule_type"] == stype:
            return s
    return None


# --- Capital gain (Schedule D) --------------------------------------------

def compute_capital_gain(return_id):
    """Recompute Schedule D net from 1099_B docs. Materialize D if B docs exist."""
    b_docs = [d for d in _docs(return_id) if d["doc_type"] == "1099_B"]
    if not b_docs:
        return
    raw_net = sum(d["proceeds_cents"] - d["cost_basis_cents"] for d in b_docs)
    if raw_net >= 0:
        sched_d_net = raw_net
    else:
        sched_d_net = max(raw_net, -CAPITAL_LOSS_LIMIT)

    sched_d = _schedule_of(return_id, "D")
    if sched_d is None:
        from db import init_common
        sched_d = {
            "return_id": return_id,
            "schedule_type": "D",
            "gross_amount_cents": 0,
            "expense_amount_cents": 0,
            "net_amount_cents": sched_d_net,
        }
        init_common(sched_d)
        db.schedules[sched_d["id"]] = sched_d
    else:
        sched_d["net_amount_cents"] = sched_d_net
        touch(sched_d)


def _set_schedule_nets(return_id):
    """Set each schedule's net. D already set by compute_capital_gain."""
    for s in _schedules(return_id):
        st = s["schedule_type"]
        if st in ("C", "E"):
            s["net_amount_cents"] = s["gross_amount_cents"] - s["expense_amount_cents"]
        elif st == "A":
            s["net_amount_cents"] = s["gross_amount_cents"]
        elif st == "B":
            s["net_amount_cents"] = 0
        # D handled by compute_capital_gain


def _refresh_dependents(return_id):
    for dep in _dependents(return_id):
        dep["qualifies_ctc"] = dep["age_years"] < 17


# --- Credit allowance ------------------------------------------------------

def compute_credit_allowance(return_id, agi_cents):
    """Set allowed_amount_cents and refundable_cents on each CreditClaim."""
    dependents = _dependents(return_id)
    ctc_children = sum(1 for dep in dependents if dep["age_years"] < 17)
    student_count = sum(1 for dep in dependents if dep.get("is_student"))

    for claim in _claims(return_id):
        ctype = claim["credit_type"]
        claimed = claim["claimed_amount_cents"]
        if ctype == "CTC":
            allowed = min(claimed, ctc_children * CTC_PER_CHILD)
            refundable = 0
        elif ctype == "AOTC":
            base = min(claimed, student_count * AOTC_PER_STUDENT)
            if agi_cents <= AOTC_PHASEOUT_START:
                allowed = base
            elif agi_cents >= AOTC_PHASEOUT_END:
                allowed = 0
            else:
                allowed = (base * (AOTC_PHASEOUT_END - agi_cents)
                           // (AOTC_PHASEOUT_END - AOTC_PHASEOUT_START))
            # refundable computed from already-floored allowed
            refundable = allowed * 40 // 100
        elif ctype == "EITC":
            band = ctc_children if ctc_children <= 2 else 2
            eitc_max = min(claimed, EITC_MAX[band])
            excess = max(0, agi_cents - EITC_PHASEOUT_START)
            allowed = max(0, eitc_max - floor_pct(excess, EITC_PHASEOUT_RATE_PCT))
            refundable = allowed
        else:
            allowed = 0
            refundable = 0
        claim["allowed_amount_cents"] = allowed
        claim["refundable_cents"] = refundable
        touch(claim)


# --- Main compute ----------------------------------------------------------

def compute_return_tax(ret):
    """Full compute in pinned order. Mutates ret and child rows. Does NOT touch ret."""
    return_id = ret["id"]
    filing_status = ret["filing_status"]

    # 1. capital gain (Schedule D) first
    compute_capital_gain(return_id)
    # 2. each schedule's net + dependent qualifies_ctc
    _set_schedule_nets(return_id)
    _refresh_dependents(return_id)

    docs = _docs(return_id)

    # 3. income aggregation
    wages = sum(d["box_amount_cents"] for d in docs if d["doc_type"] == "W2")
    nec = sum(d["box_amount_cents"] for d in docs if d["doc_type"] == "1099_NEC")
    interest = sum(d["box_amount_cents"] for d in docs if d["doc_type"] == "1099_INT")
    dividends = sum(d["box_amount_cents"] for d in docs if d["doc_type"] == "1099_DIV")

    sched_c = _schedule_of(return_id, "C")
    sched_e = _schedule_of(return_id, "E")
    sched_d = _schedule_of(return_id, "D")
    sched_c_net = sched_c["net_amount_cents"] if sched_c else 0
    sched_e_net = sched_e["net_amount_cents"] if sched_e else 0
    sched_d_net = sched_d["net_amount_cents"] if sched_d else 0

    total_income = (wages + nec + interest + dividends
                    + sched_c_net + sched_e_net + sched_d_net)
    agi = max(0, total_income)

    # 4. credits (uses agi)
    compute_credit_allowance(return_id, agi)

    # 5. deduction + bracket tax
    if ret["deduction_method"] == "STANDARD":
        deduction = STANDARD_DEDUCTION[filing_status]
    else:  # ITEMIZED
        sched_a = _schedule_of(return_id, "A")
        deduction = sched_a["gross_amount_cents"] if sched_a else 0
    taxable_income = max(0, agi - deduction)
    tax_before = bracket_tax(taxable_income, filing_status)

    # 6. tax after credits
    claims = _claims(return_id)
    nonrefundable = sum(c["allowed_amount_cents"] - c["refundable_cents"] for c in claims)
    refundable = sum(c["refundable_cents"] for c in claims)
    total_credits = sum(c["allowed_amount_cents"] for c in claims)
    tax_after = max(0, tax_before - nonrefundable) - refundable

    # 7. payments + balance
    withholding = sum(d["federal_withholding_cents"] for d in docs)
    est_paid = sum(p["amount_cents"] for p in _payments(return_id))
    total_payments = withholding + est_paid
    balance_due = tax_after - total_payments

    ret["total_income_cents"] = total_income
    ret["agi_cents"] = agi
    ret["taxable_income_cents"] = taxable_income
    ret["tax_before_credits_cents"] = tax_before
    ret["total_credits_cents"] = total_credits
    ret["tax_after_credits_cents"] = tax_after
    ret["total_payments_cents"] = total_payments
    ret["balance_due_cents"] = balance_due
    ret["computed_at"] = now_iso()


# --- Underpayment penalty projection ---------------------------------------

def compute_underpayment_penalty(ret):
    """Read-only projection. Returns dict for estimated-tax-status."""
    return_id = ret["id"]
    taxpayer = db.taxpayers.get(ret["taxpayer_id"], {})
    tax_after = ret["tax_after_credits_cents"]

    # tax_after may be negative; current-year harbor floors regardless.
    required_current = tax_after * 90 // 100

    prior_agi = taxpayer.get("prior_year_agi_cents", 0)
    prior_tax = taxpayer.get("prior_year_total_tax_cents", 0)
    py_rate = 110 if prior_agi > HIGH_INCOME_AGI else 100
    required_prior = prior_tax * py_rate // 100

    if required_current <= required_prior:
        required_annual = required_current
        safe_harbor_used = "current_year"
    else:
        required_annual = required_prior
        safe_harbor_used = "prior_year"

    payments = _payments(return_id)
    paid_on_time = sum(p["amount_cents"] for p in payments if p.get("on_time"))
    withholding = sum(d["federal_withholding_cents"] for d in _docs(return_id))
    covered = paid_on_time + withholding

    shortfall = max(0, required_annual - covered)
    penalty = shortfall * PENALTY_RATE_PCT // 100

    return {
        "required_annual_cents": required_annual,
        "covered_cents": covered,
        "shortfall_cents": shortfall,
        "penalty_cents": penalty,
        "safe_harbor_used": safe_harbor_used,
    }


def compute_on_time(quarter, paid_on_str):
    due = parse_iso(QUARTER_DUE_DATES[quarter])
    paid = parse_iso(paid_on_str)
    return paid <= due
