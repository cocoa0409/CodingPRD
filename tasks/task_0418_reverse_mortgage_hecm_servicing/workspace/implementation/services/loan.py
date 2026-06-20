"""Loan origination, accrual, payoff-quote, and recompute (§3.4, §3.6, §3.12)."""
import db
import errors
from services import calc, clock, ledger

DRAW_TYPES = {"LUMP_SUM", "LINE_OF_CREDIT", "TENURE", "TERM"}


def new_loan_blank_fields():
    """Computed/system fields at creation, before origination posts."""
    return {
        "max_claim_amount_cents": 0,
        "principal_limit_factor_micros": 0,
        "gross_principal_limit_cents": 0,
        "lesa_set_aside_cents": 0,
        "net_principal_limit_cents": 0,
        "principal_balance_cents": 0,
        "available_line_of_credit_cents": 0,
        "monthly_payment_cents": 0,
        "months_elapsed": 0,
        "servicing_status": "CURRENT",
        "disposition_status": "ACTIVE",
        "origination_date": None,
    }


def originate(loan):
    """Compute principal limit, LESA carve, initial advance, draw-type-specific
    capacity. Mutates loan in place + posts an INITIAL ADVANCE ledger entry."""
    lender = db.lenders[loan["lender_id"]]
    borrower = db.borrowers[loan["borrower_id"]]

    # state precondition: pre-origination only
    if loan["origination_date"] is not None:
        raise errors.err(errors.ERR_ALREADY_ORIGINATED, "Loan already originated")

    # body well-formedness re-checked: TERM requires tenure_term_months >= 1
    if loan["draw_type"] not in DRAW_TYPES:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid draw_type")
    if loan["draw_type"] == "TERM":
        ttm = loan.get("tenure_term_months")
        if ttm is None or not isinstance(ttm, int) or ttm < 1:
            raise errors.err(errors.ERR_INVALID_REQUEST, "TERM loan requires tenure_term_months >= 1")

    # age floor
    ref = clock.clock_date(lender)
    age = calc.whole_years_between(borrower["birthdate"], ref)
    if age < calc.MIN_AGE:
        raise errors.err(errors.ERR_BORROWER_UNDER_AGE, "Youngest borrower age below 62")

    # principal limit
    mca = calc.max_claim_amount(loan["appraised_value_cents"], lender["hud_lending_limit_cents"])
    plf_rows = [r for r in db.principal_limit_factors.values() if r["lender_id"] == loan["lender_id"]]
    row = calc.select_plf(plf_rows, loan["expected_rate_bps"], age)
    if row is None:
        raise errors.err(errors.ERR_PLF_NOT_FOUND, "No matching PLF row for rate and age")
    plf_micros = row["factor_micros"]
    gpl = calc.gross_principal_limit(mca, plf_micros)

    loan["max_claim_amount_cents"] = mca
    loan["principal_limit_factor_micros"] = plf_micros
    loan["gross_principal_limit_cents"] = gpl

    # LESA carve (sized FIRST, then subtracted)
    lesa = _find_lesa(loan["id"])
    if lesa is not None:
        initial = calc.lesa_initial_amount(
            lesa["funding_mode"], lesa["annual_property_charge_cents"], lesa["life_expectancy_years"])
        lesa["initial_amount_cents"] = initial
        lesa["drawn_cents"] = 0
        lesa["remaining_cents"] = initial
        lesa["status"] = "EXHAUSTED" if initial == 0 else "FUNDED"
        db.touch(lesa)
        loan["lesa_set_aside_cents"] = initial
    else:
        loan["lesa_set_aside_cents"] = 0

    net = gpl - loan["lesa_set_aside_cents"] - loan["initial_financed_costs_cents"]
    loan["net_principal_limit_cents"] = net

    # initial advance: balance starts at the financed costs
    loan["principal_balance_cents"] = loan["initial_financed_costs_cents"]
    loan["origination_date"] = clock.clock_date(lender).isoformat()
    loan["months_elapsed"] = 0
    loan["servicing_status"] = "CURRENT"
    loan["disposition_status"] = "ACTIVE"

    ledger.post_entry(loan, "ADVANCE", loan["initial_financed_costs_cents"], source_ref_id=None)

    # draw-type-specific capacity
    dt = loan["draw_type"]
    if dt == "LINE_OF_CREDIT":
        loan["available_line_of_credit_cents"] = net
    elif dt == "LUMP_SUM":
        loan["available_line_of_credit_cents"] = 0
        # full net principal limit advanced now
        loan["principal_balance_cents"] += net
        ledger.post_entry(loan, "ADVANCE", net, source_ref_id=None)
    else:  # TENURE or TERM
        loan["available_line_of_credit_cents"] = 0
        loan["monthly_payment_cents"] = calc.scheduled_payment(
            net, loan["expected_rate_bps"], dt, loan.get("tenure_term_months"), age)

    db.touch(loan)
    return loan


def _find_lesa(loan_id):
    for l in db.lesa_set_asides.values():
        if l["loan_id"] == loan_id:
            return l
    return None


def post_accrual(loan, number_of_months):
    """Monthly compounding: round each component per month, then accumulate."""
    erbps = loan["expected_rate_bps"]
    mipbps = loan["annual_mip_rate_bps"]
    for _ in range(number_of_months):
        interest, mip = calc.accrual_components(loan["principal_balance_cents"], erbps, mipbps)
        loan["principal_balance_cents"] += interest
        ledger.post_entry(loan, "INTEREST_ACCRUAL", interest, source_ref_id=None)
        loan["principal_balance_cents"] += mip
        ledger.post_entry(loan, "MIP_ACCRUAL", mip, source_ref_id=None)
        grow = calc.line_growth(loan["available_line_of_credit_cents"], erbps, mipbps)
        loan["available_line_of_credit_cents"] += grow
        loan["months_elapsed"] += 1
    db.touch(loan)
    return loan


def payoff_quote(loan, number_of_months):
    projected = calc.projected_balance(
        loan["principal_balance_cents"], loan["expected_rate_bps"],
        loan["annual_mip_rate_bps"], number_of_months)
    # lesser-of computed against the projected balance; basis = original appraised value
    payoff, deficiency = calc.lesser_of_payoff(projected, loan["appraised_value_cents"])
    return {
        "loan_id": loan["id"],
        "projected_balance_cents": projected,
        "lesser_of_payoff_cents": payoff,
        "deficiency_cents": deficiency,
    }


def recompute(loan):
    """Re-derive principal_balance_cents from the ledger stream and reconcile.
    Ledger entries are chronological and signed; the running balance must end
    equal to the stored principal_balance_cents."""
    entries = [e for e in db.ledger_entries.values() if e["loan_id"] == loan["id"]]
    entries.sort(key=lambda e: e["_seq"])
    derived = 0
    for e in entries:
        derived += e["amount_cents"]
        if e["balance_after_cents"] != derived:
            raise errors.err(errors.ERR_LEDGER_INCONSISTENT,
                             "Ledger balance_after does not reconcile")
    if derived != loan["principal_balance_cents"]:
        raise errors.err(errors.ERR_LEDGER_INCONSISTENT,
                         "Derived balance does not match stored balance")
    return loan
