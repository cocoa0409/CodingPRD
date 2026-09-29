"""All calculations from PRD section 3 / SCAFFOLD.yaml `calculations`.

Every monetary figure is an integer number of cents and every fractional
intermediate is rounded half up in the exact order the PRD pins.
"""
from decimal import Decimal

from core import (
    DB, add_months, by_seq, dec, days_between, days_in_month, month_first_day,
    month_last_day, parse_date, parse_month, rhu, rhu_4dp, rhu_dollars, rows,
    table,
)

# --------------------------------------------------------------------------
# Constants (SCAFFOLD calculations[].constants)
# --------------------------------------------------------------------------
OCAF_FACTORS = {"IL": Decimal("1.032"), "TX": Decimal("1.028")}
MANAGEMENT_FEE_PCT = Decimal("0.08")
BUDGET_RENT_CAP_PCT = Decimal("1.10")
UA_FIELD_OFFICE_THRESHOLD_PCT = Decimal("0.10")
TTP_ADJUSTED_INCOME_PCT = Decimal("0.30")
TTP_GROSS_INCOME_PCT = Decimal("0.10")
MINIMUM_RENT_CENTS = 2500
VACANCY_DAY_CAP = 60
VACANCY_ESTIMATE_PCT = Decimal("0.80")
VACANCY_ESTIMATE_MONTH_DAYS = 30
UNPAID_RENT_MONTH_CAP = 1
DAMAGES_MONTH_CAP = 2
MUTM_FMR_FLOOR_PCT = Decimal("1.00")
M2M_RENT_PCT_OF_MARKET = Decimal("0.90")
MAX_CHALLENGE_ROUNDS = 3
RENEWAL_WINDOW_DAYS = 420
UA_COVERAGE_MONTHS = 12
CERT_BUFFER_DAYS = 30

NOTICE_LEAD_DAYS = {
    "RENEWAL_INTENT": 120,
    "OPT_OUT_ONE_YEAR": 365,
    "TERMINATION_120_DAY": 120,
    "RENT_CHANGE": 30,
}

OPTION_TYPE_MATRIX = {
    "NEW_CONSTRUCTION": ("OPTION_1_MARK_UP_TO_MARKET", "OPTION_2_OCAF",
                         "OPTION_3_MARK_TO_MARKET"),
    "STATE_AGENCY_FINANCED": ("OPTION_2_OCAF", "OPTION_4_PORTFOLIO_REENGINEERING"),
    "LOAN_MANAGEMENT_SET_ASIDE": ("OPTION_2_OCAF",),
    "PROPERTY_DISPOSITION": ("OPTION_2_OCAF", "OPTION_4_PORTFOLIO_REENGINEERING"),
}

RENEWAL_OPTIONS = ("OPTION_1_MARK_UP_TO_MARKET", "OPTION_2_OCAF",
                   "OPTION_3_MARK_TO_MARKET", "OPTION_4_PORTFOLIO_REENGINEERING")
ADJUSTMENT_METHODS = ("OCAF", "BUDGET_BASED")
CONTRACT_TYPES = ("NEW_CONSTRUCTION", "STATE_AGENCY_FINANCED",
                  "LOAN_MANAGEMENT_SET_ASIDE", "PROPERTY_DISPOSITION")
STATE_CODES = ("IL", "TX")
NOTICE_TYPES = tuple(NOTICE_LEAD_DAYS.keys())
CLIENT_CERT_TYPES = ("INITIAL", "ANNUAL", "INTERIM")
CERT_TYPES = ("INITIAL", "ANNUAL", "INTERIM", "UA_ADJUSTMENT")
UA_METHODS = ("FACTOR_BASED", "ENGINEERING_BASED")
CLAIM_TYPES = ("VACANCY", "UNPAID_RENT", "TENANT_DAMAGES")


# --------------------------------------------------------------------------
# Relationship walks
# --------------------------------------------------------------------------
def property_of(contract):
    return table("properties").get(contract["property_id"])


def contract_of_case(case):
    return table("contracts").get(case["contract_id"])


def property_of_case(case):
    contract = contract_of_case(case)
    return property_of(contract) if contract else None


def contracts_of_property(property_id):
    return by_seq([c for c in rows("contracts") if c["property_id"] == property_id])


def contract_of_property(property_id):
    """The household's contract: the property's contract, created_at ASC."""
    found = contracts_of_property(property_id)
    return found[0] if found else None


def households_of_property(property_id):
    return by_seq([h for h in rows("households") if h["property_id"] == property_id])


def certifications_of(tenant_id):
    return by_seq([c for c in rows("certifications") if c["tenant_id"] == tenant_id])


def active_certification(tenant_id):
    for cert in certifications_of(tenant_id):
        if cert["status"] == "ACTIVE":
            return cert
    return None


def comparables_of(study_id):
    return by_seq([c for c in rows("comparables") if c["study_id"] == study_id])


def studies_of_case(case_id):
    return by_seq([s for s in rows("studies") if s["renewal_case_id"] == case_id])


def vouchers_of_case(case_id):
    return by_seq([v for v in rows("vouchers") if v["renewal_case_id"] == case_id])


def notices_of_case(case_id):
    return by_seq([n for n in rows("notices") if n["renewal_case_id"] == case_id])


def analyses_of_property(property_id):
    return by_seq([a for a in rows("analyses") if a["property_id"] == property_id])


def submissions_of_contract(contract_id):
    return by_seq([s for s in rows("submissions") if s["contract_id"] == contract_id])


def claims_of_contract(contract_id):
    return by_seq([c for c in rows("claims") if c["contract_id"] == contract_id])


def cases_of_contract(contract_id):
    return by_seq([c for c in rows("cases") if c["contract_id"] == contract_id])


def in_force_unit_rent(contract):
    """The contract's in-force per-unit rent (PRD 3.8 / 3.9)."""
    renewed = contract.get("renewed_rent_per_unit_cents")
    if renewed is not None:
        return renewed
    return contract["contract_rent_per_unit_cents"]


# --------------------------------------------------------------------------
# calculations.comparable_market_rent
# --------------------------------------------------------------------------
def comparable_adjusted_rent(raw_rent_cents, adjustment_total_cents,
                             utility_adjustment_cents):
    gross = raw_rent_cents + adjustment_total_cents + utility_adjustment_cents
    return rhu_dollars(gross)


def recompute_study_estimate(study):
    """STEP 1 rounding already stored per comparable; STEP 2/3 here."""
    accepted = [c for c in comparables_of(study["id"]) if c["status"] == "ACCEPTED"]
    study["accepted_comparable_count"] = len(accepted)
    total_weight = sum(c["weight"] for c in accepted)
    if total_weight == 0:
        study["estimated_market_rent_cents"] = None
        return None
    weighted_sum = sum(c["adjusted_rent_cents"] * c["weight"] for c in accepted)
    value = rhu(Decimal(weighted_sum) / Decimal(total_weight))
    study["estimated_market_rent_cents"] = value
    return value


# --------------------------------------------------------------------------
# calculations.ocaf_adjusted_rent
# --------------------------------------------------------------------------
def ocaf_adjusted_rent(contract, prop):
    factor = OCAF_FACTORS[prop["state_code"]]
    debt = contract["monthly_debt_service_per_unit_cents"]
    non_debt = contract["contract_rent_per_unit_cents"] - debt
    if non_debt < 0:
        non_debt = 0
    return rhu(Decimal(non_debt) * factor) + debt


# --------------------------------------------------------------------------
# calculations.budget_based_rent
# --------------------------------------------------------------------------
def budget_based_rent(contract):
    base_before_fee = (contract["operating_expense_per_unit_cents"]
                       + contract["monthly_debt_service_per_unit_cents"]
                       + contract["reserve_deposit_per_unit_cents"])
    fee = rhu(MANAGEMENT_FEE_PCT * Decimal(base_before_fee))
    return base_before_fee + fee


def recompute_case_candidate_rents(case):
    contract = contract_of_case(case)
    prop = property_of(contract) if contract else None
    if contract is None or prop is None:
        return
    case["ocaf_rent_per_unit_cents"] = ocaf_adjusted_rent(contract, prop)
    case["budget_rent_per_unit_cents"] = budget_based_rent(contract)


def recompute_rcs_required(case):
    case["rcs_required"] = bool(
        case.get("renewal_option") == "OPTION_1_MARK_UP_TO_MARKET"
        or case.get("adjustment_method") == "BUDGET_BASED"
    )
    return case["rcs_required"]


# --------------------------------------------------------------------------
# calculations.utility_allowance_adjustment
# --------------------------------------------------------------------------
def utility_allowance_adjustment(method, baseline, rate_change_pct,
                                 engineering_estimate_cents):
    if method == "FACTOR_BASED":
        proposed = rhu(Decimal(baseline) * (Decimal(1) + dec(rate_change_pct)))
    else:
        proposed = engineering_estimate_cents
    change = rhu_4dp(Decimal(proposed - baseline) / Decimal(baseline))
    requires_fo = abs(change) > UA_FIELD_OFFICE_THRESHOLD_PCT
    return proposed, change, bool(requires_fo)


# --------------------------------------------------------------------------
# calculations.tenant_rent_recalculation
# --------------------------------------------------------------------------
def tenant_rent_recalculation(household, utility_allowance_cents,
                              contract_rent_per_unit_cents):
    monthly_adjusted = rhu(Decimal(household["annual_adjusted_income_cents"]) / Decimal(12))
    monthly_gross = rhu(Decimal(household["annual_gross_income_cents"]) / Decimal(12))
    ttp = max(
        rhu(TTP_ADJUSTED_INCOME_PCT * Decimal(monthly_adjusted)),
        rhu(TTP_GROSS_INCOME_PCT * Decimal(monthly_gross)),
        MINIMUM_RENT_CENTS,
    )
    gross_rent = contract_rent_per_unit_cents + utility_allowance_cents
    return {
        "gross_rent_cents": gross_rent,
        "ttp_cents": ttp,
        "tenant_rent_cents": max(0, ttp - utility_allowance_cents),
        "utility_reimbursement_cents": max(0, utility_allowance_cents - ttp),
        "hap_cents": max(0, gross_rent - ttp),
    }


# --------------------------------------------------------------------------
# calculations.monthly_voucher_hap_request
# --------------------------------------------------------------------------
def monthly_voucher_hap_request(contract, period_month):
    year, month = parse_month(period_month)
    first = month_first_day(year, month)
    last = month_last_day(year, month)
    span = days_in_month(year, month)
    total = 0
    included = 0
    for household in households_of_property(contract["property_id"]):
        status = household["status"]
        if status not in ("ACTIVE", "OPT_OUT_NOTICED", "MOVED_OUT"):
            continue
        moved = parse_date(household.get("move_out_date")) if status == "MOVED_OUT" else None
        if status == "MOVED_OUT":
            if moved is None or not (moved > first):
                continue
        candidates = [c for c in certifications_of(household["id"])
                      if parse_date(c["effective_date"]) <= last]
        if not candidates:
            continue
        cert = sorted(candidates, key=lambda c: (c["effective_date"], c["_seq"]))[-1]
        if status == "MOVED_OUT" and moved is not None and moved <= last:
            days_occupied = days_between(first, moved)
            term = rhu(Decimal(cert["hap_cents"]) * Decimal(days_occupied) / Decimal(span))
        else:
            term = cert["hap_cents"]
        total += term
        included += 1
    return total, included


# --------------------------------------------------------------------------
# calculations.special_claim_amount
# --------------------------------------------------------------------------
def special_claim_amount(claim, contract):
    unit_rent = in_force_unit_rent(contract)
    claim_type = claim["claim_type"]
    if claim_type == "VACANCY" and claim.get("vacancy_end_date") is not None:
        start = parse_date(claim["vacancy_start_date"])
        end = parse_date(claim["vacancy_end_date"])
        raw_days = days_between(start, end)
        if raw_days < 0:
            raw_days = 0
        days = min(VACANCY_DAY_CAP, raw_days)
        amount = _vacancy_chronological_amount(start, days, unit_rent)
        return days, "ACTUAL_CHRONOLOGICAL", amount
    if claim_type == "VACANCY":
        estimated = claim.get("estimated_vacancy_days") or 0
        days = min(VACANCY_DAY_CAP, estimated)
        amount = rhu(VACANCY_ESTIMATE_PCT * Decimal(unit_rent) * Decimal(days)
                     / Decimal(VACANCY_ESTIMATE_MONTH_DAYS))
        return days, "PROJECTED_ESTIMATE", amount
    claimed = claim.get("claimed_amount_cents") or 0
    deposit = claim.get("security_deposit_balance_cents") or 0
    cap_months = UNPAID_RENT_MONTH_CAP if claim_type == "UNPAID_RENT" else DAMAGES_MONTH_CAP
    capped = min(claimed, cap_months * unit_rent)
    return 0, "DIRECT_LEDGER", max(0, capped - deposit)


def _vacancy_chronological_amount(start, days, unit_rent):
    """Walk the calendar months of [start, start + days) in ascending order."""
    total = 0
    remaining = days
    cursor = start
    while remaining > 0:
        span = days_in_month(cursor.year, cursor.month)
        in_month = span - cursor.day + 1
        if in_month > remaining:
            in_month = remaining
        daily = rhu(Decimal(unit_rent) / Decimal(span))
        total += daily * in_month
        remaining -= in_month
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1, day=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1, day=1)
    return total


def aggregate_vacancy_days(contract_id, unit_number, exclude_claim_id):
    total = 0
    for claim in claims_of_contract(contract_id):
        if claim["id"] == exclude_claim_id:
            continue
        if claim["unit_number"] != unit_number:
            continue
        if claim["state"] in ("SUBMITTED", "APPROVED", "PAID"):
            total += claim.get("vacancy_days_claimed") or 0
    return total


# --------------------------------------------------------------------------
# calculations.enhanced_voucher_entitlement
# --------------------------------------------------------------------------
def enhanced_voucher_entitlement(case, prop, household):
    market = case.get("comparable_market_rent_cents")
    market = 0 if market is None else market
    gross_market = max(market, prop["published_fmr_cents"]) + prop["current_utility_allowance_cents"]
    cert = active_certification(household["id"])
    ttp_snapshot = cert["ttp_cents"] if cert is not None else 0
    entitlement = max(0, gross_market - max(ttp_snapshot, MINIMUM_RENT_CENTS))
    return gross_market, ttp_snapshot, entitlement


# --------------------------------------------------------------------------
# calculations.restructuring_eligibility
# --------------------------------------------------------------------------
def restructuring_eligibility(determination, contract, prop):
    market = determination.get("market_rent_per_unit_cents") or 0
    rent = determination.get("current_rent_per_unit_cents") or 0
    fmr = determination.get("fmr_per_unit_cents") or 0
    if contract["contract_type"] == "LOAN_MANAGEMENT_SET_ASIDE":
        return "INELIGIBLE", "CONTRACT_TYPE_EXCLUDED"
    if market > rent:
        floor = rhu(MUTM_FMR_FLOOR_PCT * Decimal(fmr))
        if market >= floor:
            return "MUTM_ELIGIBLE", "MARKET_ABOVE_CONTRACT_AND_FMR"
        return "INELIGIBLE", "MARKET_BELOW_FMR_FLOOR"
    if rent > market and prop.get("has_fha_insured_mortgage") is True:
        return "M2M_REFERRED", "CONTRACT_ABOVE_MARKET_FHA_INSURED"
    return "INELIGIBLE", "MARKET_NOT_ABOVE_CONTRACT"


# --------------------------------------------------------------------------
# calculations.notice_window_compliance
# --------------------------------------------------------------------------
def notice_window(issued_date, effective_date, notice_type):
    lead = days_between(parse_date(issued_date), parse_date(effective_date))
    required = NOTICE_LEAD_DAYS[notice_type]
    return lead, required, lead >= required


# --------------------------------------------------------------------------
# calculations.subsidy_reconciliation
# --------------------------------------------------------------------------
def subsidy_reconciliation(contract):
    submissions = sorted(submissions_of_contract(contract["id"]),
                         key=lambda s: (s["period_month"], s["_seq"]))
    requested_total = 0
    paid_total = 0
    reversed_total = 0
    paid_periods = 0
    for row in submissions:
        if row["state"] in ("SUBMITTED", "PAID"):
            requested_total += row["requested_hap_cents"]
        if row["state"] == "PAID":
            paid_total += row.get("paid_amount_cents") or 0
            paid_periods += 1
        if row["state"] == "REVERSED":
            reversed_total += row.get("paid_amount_cents") or 0
    claims_paid_total = 0
    for claim in claims_of_contract(contract["id"]):
        if claim["state"] == "PAID":
            claims_paid_total += claim.get("paid_amount_cents") or 0
    authorized = contract["authorized_hap_budget_cents"]
    return {
        "requested_total_cents": requested_total,
        "paid_hap_total_cents": paid_total,
        "reversed_total_cents": reversed_total,
        "paid_claims_total_cents": claims_paid_total,
        "authorized_hap_budget_cents": authorized,
        "hap_ledger_balance_cents": authorized - paid_total - claims_paid_total,
        "variance_cents": requested_total - paid_total,
        "paid_period_count": paid_periods,
    }


# --------------------------------------------------------------------------
# Ledger maintenance (PRD 2.10 conserved quantities)
# --------------------------------------------------------------------------
def recompute_contract_ledger(contract):
    contract["hap_ledger_balance_cents"] = (
        contract["authorized_hap_budget_cents"]
        - contract["paid_hap_total_cents"]
        - contract["paid_claims_total_cents"]
    )


def ua_coverage_boundary(prop):
    last = parse_date(prop.get("last_applied_ua_effective_date"))
    if last is None:
        return None
    return add_months(last, UA_COVERAGE_MONTHS)


__all__ = [name for name in dir() if not name.startswith("_")]
